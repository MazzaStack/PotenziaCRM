"""
Database module for Portales Temporales Live.
Handles creation, retrieval, analytics tracking, and 15-day lifecycle management.
"""
import json
import re
import uuid
from datetime import datetime, timedelta
from database.db import get_db, MASTER_DB_PATH

def check_and_add_portales_temp_table(db_path=None):
    """Ensures the portales_temporales_live table exists in SQLite and PostgreSQL."""
    try:
        conn = get_db(db_path or MASTER_DB_PATH)
        create_sql = """
        CREATE TABLE IF NOT EXISTS portales_temporales_live (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_slug TEXT UNIQUE NOT NULL,
            titulo TEXT NOT NULL,
            agente_id INTEGER NOT NULL,
            cliente_id INTEGER,
            tipo_operacion TEXT DEFAULT 'venta',
            zona TEXT,
            propiedades_json TEXT NOT NULL,
            total_propiedades INTEGER DEFAULT 0,
            agente_nombre TEXT,
            agente_telefono TEXT,
            agente_email TEXT,
            agente_avatar TEXT,
            vistas_count INTEGER DEFAULT 0,
            primer_acceso TEXT,
            ultimo_acceso TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            expires_at TEXT,
            activo INTEGER DEFAULT 1
        );
        """
        conn.execute(create_sql)
        conn.commit()
    except Exception as e:
        print(f"[db_portales_temp] Error initializing table: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def generar_slug_portal(titulo, custom_id=None):
    """Generates a clean URL slug like 'seleccion-225' or 'seleccion-palermo-a8f1'."""
    clean_title = re.sub(r'[^a-zA-Z0-9]+', '-', (titulo or 'seleccion').lower()).strip('-')
    if not clean_title or clean_title == 'seleccion':
        clean_title = 'seleccion'
    
    unique_suffix = custom_id or str(uuid.uuid4())[:4]
    return f"seleccion-{clean_title[:20].rstrip('-')}-{unique_suffix}".replace('--', '-')

def crear_portal_temporal(datos, agente_id):
    """
    Creates a new 15-day live temporary portal.
    datos: dict containing {
        'titulo': str,
        'propiedades': list of dicts,
        'tipo_operacion': str,
        'zona': str,
        'cliente_id': int (optional),
        'agente_nombre': str,
        'agente_telefono': str,
        'agente_email': str,
        'agente_avatar': str
    }
    """
    check_and_add_portales_temp_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        now_dt = datetime.now()
        expires_dt = now_dt + timedelta(days=15)
        created_at_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
        expires_at_str = expires_dt.strftime('%Y-%m-%d %H:%M:%S')

        aid = agente_id or 1
        titulo = datos.get('titulo') or f"Selección de Propiedades ({datos.get('tipo_operacion', 'venta').capitalize()})"
        
        # Determine unique slug
        random_code = str(uuid.uuid4())[:4]
        # Count existing portales to generate friendly numbering e.g. seleccion-225
        try:
            row_count = conn.execute("SELECT COUNT(*) as c FROM portales_temporales_live").fetchone()
            portal_num = (row_count['c'] if row_count else 0) + 1
        except Exception:
            portal_num = int(datetime.now().timestamp()) % 10000

        codigo_slug = f"seleccion-{portal_num}-{random_code}"

        props = datos.get('propiedades') or []
        propiedades_json = json.dumps(props, ensure_ascii=False)

        sql = """
        INSERT INTO portales_temporales_live (
            codigo_slug, titulo, agente_id, cliente_id, tipo_operacion,
            zona, propiedades_json, total_propiedades,
            agente_nombre, agente_telefono, agente_email, agente_avatar,
            created_at, expires_at, activo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """
        cursor = conn.execute(sql, (
            codigo_slug,
            titulo,
            aid,
            datos.get('cliente_id'),
            datos.get('tipo_operacion', 'venta'),
            datos.get('zona', ''),
            propiedades_json,
            len(props),
            datos.get('agente_nombre', ''),
            datos.get('agente_telefono', ''),
            datos.get('agente_email', ''),
            datos.get('agente_avatar', ''),
            created_at_str,
            expires_at_str
        ))
        conn.commit()
        return {
            'id': cursor.lastrowid,
            'codigo_slug': codigo_slug,
            'expires_at': expires_at_str,
            'total_propiedades': len(props)
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_portal_temporal_by_slug(slug):
    """
    Retrieves a portal temporal by its slug with expiration verification.
    """
    check_and_add_portales_temp_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        row = conn.execute("SELECT * FROM portales_temporales_live WHERE codigo_slug = ?", (slug,)).fetchone()
        if not row:
            return None

        p = dict(row)
        
        # Parse properties JSON
        try:
            p['propiedades'] = json.loads(p.get('propiedades_json') or '[]')
        except Exception:
            p['propiedades'] = []

        # Check expiration
        now_dt = datetime.now()
        expira_dt = None
        if p.get('expires_at'):
            try:
                expira_dt = datetime.strptime(p['expires_at'][:19], '%Y-%m-%d %H:%M:%S')
            except Exception:
                try:
                    expira_dt = datetime.strptime(p['expires_at'][:10], '%Y-%m-%d')
                except Exception:
                    pass

        p['expirado'] = False
        p['dias_restantes'] = 15
        if expira_dt:
            if now_dt > expira_dt or p.get('activo') == 0:
                p['expirado'] = True
                p['dias_restantes'] = 0
            else:
                p['dias_restantes'] = max(0, (expira_dt - now_dt).days)

        return p
    finally:
        try:
            conn.close()
        except Exception:
            pass

def registrar_vista_portal_temporal(slug):
    """Increments the view count for a temporal portal."""
    conn = get_db(MASTER_DB_PATH)
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("""
            UPDATE portales_temporales_live 
            SET vistas_count = COALESCE(vistas_count, 0) + 1,
                primer_acceso = CASE WHEN primer_acceso IS NULL THEN ? ELSE primer_acceso END,
                ultimo_acceso = ?
            WHERE codigo_slug = ?
        """, (now_str, now_str, slug))
        conn.commit()
    except Exception as e:
        print(f"[db_portales_temp] Error registering view: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_portales_temporales_por_agente(agente_id=None, viewer_admin_id=None):
    """
    Gets temporary portals created by an agent, or all regular agents for an admin.
    - If agente_id is provided: returns portals for that specific agent.
    - If agente_id is None:
        - If viewer_admin_id is provided: returns portals belonging to viewer_admin_id PLUS all non-admin agents (rol != 'admin'), strictly excluding any other admins.
        - If viewer_admin_id is None: returns all portals.
    """
    check_and_add_portales_temp_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        query = """
            SELECT pt.*, 
                   c.nombre as cliente_nombre, c.apellido as cliente_apellido, c.email as cliente_email,
                   u.nombre_display as creador_nombre, u.usuario as creador_usuario, u.rol as creador_rol
            FROM portales_temporales_live pt
            LEFT JOIN contactos c ON pt.cliente_id = c.id
            LEFT JOIN usuarios u ON pt.agente_id = u.id
        """
        params = []
        if agente_id is not None:
            query += " WHERE pt.agente_id = ?"
            params.append(agente_id)
        elif viewer_admin_id is not None:
            query += " WHERE (pt.agente_id = ? OR COALESCE(u.rol, 'agente') != 'admin')"
            params.append(viewer_admin_id)
            
        query += " ORDER BY pt.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        
        now_dt = datetime.now()
        results = []
        for r in rows:
            p = dict(r)
            expira_dt = None
            if p.get('expires_at'):
                try:
                    expira_dt = datetime.strptime(p['expires_at'][:19], '%Y-%m-%d %H:%M:%S')
                except Exception:
                    pass
            
            p['expirado'] = False
            p['dias_restantes'] = 15
            if expira_dt:
                if now_dt > expira_dt or p.get('activo') == 0:
                    p['expirado'] = True
                    p['dias_restantes'] = 0
                else:
                    p['dias_restantes'] = max(0, (expira_dt - now_dt).days)
            results.append(p)
            
        return results
    finally:
        try:
            conn.close()
        except Exception:
            pass

def eliminar_portal_temporal(portal_id, agente_id=None, requester_admin_id=None):
    """
    Deletes a temporary portal with strict role isolation.
    - If agente_id is passed (regular agent): can only delete if pt.id == portal_id AND pt.agente_id == agente_id.
    - If requester_admin_id is passed (admin): can delete if it belongs to requester_admin_id OR belongs to a non-admin agent. Cannot delete another admin's portal.
    """
    conn = get_db(MASTER_DB_PATH)
    try:
        if agente_id:
            conn.execute("DELETE FROM portales_temporales_live WHERE id = ? AND agente_id = ?", (portal_id, agente_id))
        elif requester_admin_id:
            portal = conn.execute("""
                SELECT pt.id, pt.agente_id, u.rol as creador_rol 
                FROM portales_temporales_live pt
                LEFT JOIN usuarios u ON pt.agente_id = u.id
                WHERE pt.id = ?
            """, (portal_id,)).fetchone()
            if portal:
                p_agente_id = portal['agente_id']
                p_rol = portal['creador_rol'] or 'agente'
                if p_agente_id == requester_admin_id or p_rol != 'admin':
                    conn.execute("DELETE FROM portales_temporales_live WHERE id = ?", (portal_id,))
        else:
            conn.execute("DELETE FROM portales_temporales_live WHERE id = ?", (portal_id,))
        conn.commit()
        return True
    finally:
        try:
            conn.close()
        except Exception:
            pass

def purgar_portales_temporales_expirados():
    """Removes all temporary portals expired more than 30 days ago."""
    conn = get_db(MASTER_DB_PATH)
    try:
        purge_limit = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        cursor = conn.execute("DELETE FROM portales_temporales_live WHERE expires_at < ?", (purge_limit,))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"[db_portales_temp] Error purging expired portals: {e}")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
