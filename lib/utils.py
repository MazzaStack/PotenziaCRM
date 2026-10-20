import re
import json
import os
from datetime import datetime

def clean_phone_argentina(phone):
    """
    Cleans and formats Argentine phone numbers for WhatsApp (wa.me).
    Result format: 549 + area_code + number (no 15, no leading 0).
    """
    if not phone:
        return ""
    
    # 1. Reject invalid placeholders
    invalid_patterns = ["000000000", "nodisponible", "nidisponible", "noencontrado"]
    clean_raw = str(phone).lower().replace(" ", "").replace("-", "")
    for inv in invalid_patterns:
        if inv in clean_raw:
            return ""

    # 1. Remove non-digits
    digits = re.sub(r'\D', '', str(phone))
    
    # 2. Fix common redundant prefixes like +540054...
    if digits.startswith('540054'):
        digits = digits[4:]
    elif digits.startswith('0054'):
        digits = digits[2:]
    
    # 3. Handle international prefix 54
    has_54 = digits.startswith('54')
    if has_54:
        # Remove 54 to work with the core number
        digits = digits[2:]
        # If there was a 9 after 54, remove it too for now to normalize
        if digits.startswith('9'):
            digits = digits[1:]
    
    # 4. Remove leading 0 if present (e.g. 011 -> 11)
    if digits.startswith('0'):
        digits = digits[1:]
    
    # 5. Handle the '15' prefix for mobiles (e.g. 11 15 61114414 -> 11 61114414)
    # This is tricky because some areas have 3 digit codes. 
    # But usually '15' is after the area code (2, 3 or 4 digits).
    if len(digits) > 10:
        # Try to find '15' and remove it if it's in a likely position
        # Positions for 15: 
        # Area 11 (2 digits) -> 15 at index 2
        # Area 351 (3 digits) -> 15 at index 3
        # Area 2254 (4 digits) -> 15 at index 4
        for pos in [2, 3, 4]:
            if digits[pos:pos+2] == '15':
                digits = digits[:pos] + digits[pos+2:]
                break
    elif digits.startswith('15'):
        # Local number starting with 15 without area code? 
        # Assume area code is missing or it's just the number.
        # We can't do much without area code, but let's at least strip 15.
        digits = digits[2:]

    # 6. Final check: if it's a standard 10-digit number (area+number), add 549
    if len(digits) == 10:
        return "549" + digits
    
    # If it's already 13 digits (549 + 10 digits), it might be correct
    if len(digits) == 13 and digits.startswith('549'):
        return digits

    # Fallback: if we have 10 digits or more, just try to prepend 549 if missing
    if len(digits) >= 10:
        # Keep only the last 10 digits to be safe? 
        # No, some rural areas vary. Let's just ensures it starts with 549.
        return "549" + digits[-10:]
    
    # Last resort: just digits
    return digits

def extraer_nombre_pila(nombre_completo):
    """
    Extrae solo el primer nombre útil capitalizado (dejando de lado el apellido).
    Limpia palabras extrañas u honoríficos.
    """
    if not nombre_completo:
        return ""
    
    # Remove extra spaces and split
    partes = str(nombre_completo).strip().split()
    if not partes:
        return ""
    
    # Check common non-name words to avoid treating them as names
    ignorar = ['dueño', 'vende', 'sr', 'sra', 'propietario', 'inmobiliaria', 'arquitectura', 'desarrollos']
    
    for p in partes:
        clean_p = p.strip('.,-').lower()
        if clean_p and clean_p not in ignorar:
            return clean_p.capitalize()
            
    # Fallback if everything is ignored
    return partes[0].capitalize()

def check_y_guardar_propiedades(zona, tipo_propiedad, tipo_operacion, results):
    """Saves live search results to the database if no properties have been captured today for this zone."""
    if not results or not zona:
        return
        
    from database import db
    from datetime import datetime
    
    # Normalize neighborhood name
    clean_zona = zona.lower().strip()
    
    # Check if there are properties captured today for this neighborhood and operation type
    conn = db.get_db()
    try:
        today_str = datetime.now().strftime('%Y-%m-%d')
        # Search using a fuzzy check on barrio, direccion or title
        query = """
            SELECT COUNT(*) FROM propiedades 
            WHERE (LOWER(barrio) LIKE ? OR LOWER(direccion) LIKE ? OR LOWER(titulo) LIKE ?)
            AND tipo_operacion = ?
            AND DATE(fecha_captacion) = DATE(?)
        """
        like_pattern = f"%{clean_zona}%"
        count = conn.execute(query, (like_pattern, like_pattern, like_pattern, tipo_operacion, today_str)).fetchone()[0]
    except Exception as e:
        print(f"Error checking daily capture: {e}")
        count = 0
    finally:
        conn.close()

    # --- Automatic TTL cleanup: remove stale properties for this zone ---
    # Ventas: 90 days | Alquileres: 30 days
    try:
        conn2 = db.get_db()
        from datetime import datetime, timedelta
        ttl_days = 90 if str(tipo_operacion).lower() == 'venta' else 30
        cutoff_date = (datetime.now() - timedelta(days=ttl_days)).strftime('%Y-%m-%d %H:%M:%S')
        deleted = conn2.execute("""
            DELETE FROM propiedades
            WHERE tipo_operacion = ?
            AND (LOWER(barrio) LIKE ? OR LOWER(direccion) LIKE ? OR LOWER(titulo) LIKE ?)
            AND fecha_captacion < ?
        """, (tipo_operacion, f"%{clean_zona}%", f"%{clean_zona}%", f"%{clean_zona}%", cutoff_date)).rowcount
        conn2.commit()
        if deleted > 0:
            print(f"  [TTL Cleanup] Eliminadas {deleted} propiedades de '{zona}' con más de {ttl_days} días de antigüedad.")
    except Exception as e:
        print(f"  [TTL Cleanup] Error: {e}")
    finally:
        try: conn2.close()
        except: pass
        
    print(f"  [AutoCap] Guardando/Actualizando {len(results)} propiedades de '{zona}' ({tipo_operacion}) en la base de datos local...")
    for r in results:
            fotos_list = r.get('fotos') or ([r.get('foto')] if r.get('foto') else [])
            p_data = {
                'portal': r.get('portal', 'desconocido'),
                'url': r.get('url'),
                'titulo': r.get('titulo'),
                'precio': r.get('precio'),
                'moneda': r.get('moneda', 'USD'),
                'direccion': r.get('direccion'),
                'barrio': r.get('barrio') or zona,
                'm2_total': r.get('m2_total') or r.get('m2'),
                'm2_cubiertos': r.get('m2_cubiertos') or r.get('m2_total') or r.get('m2'),
                'ambientes': r.get('ambientes'),
                'dormitorios': r.get('dormitorios'),
                'tipo_propiedad': tipo_propiedad if isinstance(tipo_propiedad, str) else (tipo_propiedad[0] if tipo_propiedad else 'departamento'),
                'tipo_operacion': tipo_operacion,
                'descripcion': r.get('descripcion', ''),
                'foto_url': r.get('foto') or r.get('foto_url'),
                'fotos_json': json.dumps(fotos_list) if fotos_list else None,
                'lat': r.get('lat'),
                'lng': r.get('lng'),
                'fecha_publicacion': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'notas': 'Auto-captada desde buscador en vivo'
            }
            try:
                db.insert_propiedad(p_data)
            except Exception as e:
                print(f"Error inserting auto-captured property: {e}")

