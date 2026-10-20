import concurrent.futures
import requests
from database.db import get_db

def _check_link(args):
    prop_id, url = args
    if not url:
        return prop_id, False

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml'
        }
        res = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        
        # 404 means it's definitely gone
        if res.status_code >= 400:
            return prop_id, False
            
        text = res.text.lower()
        
        # ML specific inactive text
        if 'publicación pausada' in text or 'publicación finalizada' in text:
            return prop_id, False
            
        # Zonaprop specific inactive text
        if 'aviso no disponible' in text or 'aviso finalizado' in text:
            return prop_id, False

        return prop_id, True
        
    except Exception as e:
        print(f"Error checking {url}: {e}")
        # If it fails (e.g. timeout), we assume it's still alive to prevent false positives
        return prop_id, True

def validar_links_inactivos(busqueda_id=None, limit=20):
    """
    Checks active properties (nueva, contactada, en_seguimiento).
    If their link is dead/inactive, marks them as 'vendida'.
    """
    conn = get_db()
    
    query = "SELECT id, url FROM propiedades WHERE estado IN ('nueva', 'contactada', 'en_seguimiento')"
    params = []
    
    if busqueda_id:
        query += " AND busqueda_id = ?"
        params.append(busqueda_id)
        
    query += f" ORDER BY RANDOM() LIMIT {limit}"
    
    props = conn.execute(query, params).fetchall()
    
    if not props:
        conn.close()
        return 0, 0
        
    to_check = [(p['id'], p['url']) for p in props]
    
    inactivos_ids = []
    activos = 0
    
    # Process in chunks of 10 elements to avoid getting IP banned
    chunk_size = 10
    chunks = [to_check[i:i + chunk_size] for i in range(0, len(to_check), chunk_size)]
    
    import time
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        for idx, chunk in enumerate(chunks):
            # Anti-ban sleep between chunks (but not before the first one)
            if idx > 0:
                print(f"  [ANTI-BAN] Esperando 20 segundos antes del siguiente lote de links activados...")
                time.sleep(20)
                
            results = executor.map(_check_link, chunk)
            for p_id, is_active in results:
                if not is_active:
                    inactivos_ids.append(p_id)
                else:
                    activos += 1
                
    if inactivos_ids:
        placeholders = ','.join(['?'] * len(inactivos_ids))
        conn.execute(
            f"UPDATE propiedades SET estado = 'vendida', notas = 'Aviso inactivo en portal detectado' WHERE id IN ({placeholders})",
            inactivos_ids
        )
        conn.commit()
        
    conn.close()
    return len(inactivos_ids), activos
