"""
Database queries for CRM contacts and blacklist
"""
import sqlite3
import json
from lib.utils import clean_phone_argentina
# Avoid circular import by importing database.db dynamically inside functions when needed.
def _get_db(db_path=None):
    from database.db import get_db
    return get_db(db_path)

def _get_config(clave, default=None):
    from database.db import get_config
    return get_config(clave, default)

def _set_config(clave, valor):
    from database.db import set_config
    return set_config(clave, valor)

def _get_master_db_path():
    from database.db import MASTER_DB_PATH
    return MASTER_DB_PATH



def _get_agent_filter():
    """
    Returns (agent_id, is_superadmin) for the current logged-in user.
    Superadmin (GermanMazza) sees all data; agents see only theirs.
    Returns (None, True) when there is no request context (background jobs).
    """
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user and current_user.is_authenticated:
            if getattr(current_user, 'usuario', None) == 'GermanMazza':
                return (None, True)
            return (current_user.id, False)
    except Exception:
        pass
    return (None, True)  # background jobs: unrestricted

def add_to_blacklist(telefono, motivo=None):
    """Adds a phone number to the blacklist."""
    tel = clean_phone_argentina(str(telefono)) if telefono else None
    if not tel: return False
    
    conn = _get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO lista_negra (telefono, motivo) VALUES (?, ?)", (tel, motivo))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()
    
def remove_from_blacklist(blacklist_id):
    """Removes a phone entry from the blacklist by its ID."""
    conn = _get_db()
    try:
        conn.execute("DELETE FROM lista_negra WHERE id = ?", (blacklist_id,))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def is_blacklisted(telefono):
    """Checks if a phone number is in the blacklist."""
    tel = clean_phone_argentina(str(telefono)) if telefono else None
    if not tel: return False
    
    conn = _get_db()
    try:
        row = conn.execute("SELECT 1 FROM lista_negra WHERE telefono = ?", (tel,)).fetchone()
        return True if row else False
    finally:
        conn.close()

def get_blacklist():
    """Gets the full list of blacklisted numbers."""
    conn = _get_db()
    try:
        rows = conn.execute("SELECT * FROM lista_negra ORDER BY fecha_creacion DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_custom_columns():
    """Gets defined custom column names from configuration."""
    cols_json = _get_config('crm_custom_columns', '[]')
    try:
        return json.loads(cols_json)
    except:
        return []

def add_custom_column(column_name):
    """Adds a new custom column definition."""
    cols = get_custom_columns()
    if column_name not in cols:
        cols.append(column_name)
        _set_config('crm_custom_columns', json.dumps(cols))
    return cols

def save_contacto(data):
    """
    Create or update a contact with smart deduplication and full field support.
    Handles both UI manual input (with ID) and Excel sync (with Phone/Name match).
    Supports custom fields via campos_personalizados_json.
    """
    cid = data.get('id')
    raw_tel = data.get('telefono')
    tel = clean_phone_argentina(str(raw_tel)) if raw_tel else None
    
    # Extract custom fields (everything not in the standard list)
    standard_fields = [
        'id', 'nombre', 'apellido', 'calificacion', 'categoria', 'ultimo_contacto',
        'fecha_nacimiento', 'aniversario_casa', 'rol', 'referente', 'notas',
        'telefono', 'email', 'busqueda_activa', 'filtros_busqueda_json', 'campos_personalizados_json',
        'mac', 'intencion_ia', 'recordatorio_activo', 'recordatorio_dias', 'recordatorio_fecha',
        'agente_id'
    ]
    
    custom_data = {}
    for k, v in data.items():
        if k not in standard_fields and v is not None:
            custom_data[k] = v
            
    custom_json = json.dumps(custom_data) if custom_data else data.get('campos_personalizados_json')
    
    # Resolve agente_id
    agente_id = data.get('agente_id')
    if not agente_id:
        try:
            from flask import has_request_context
            from flask_login import current_user
            if has_request_context() and current_user and current_user.is_authenticated:
                agente_id = current_user.id
        except Exception:
            pass
            
    conn = _get_db()
    
    # CASE 1: Explicit ID provided (Manual Edit from UI)
    if cid:
        try:
            row = conn.execute("SELECT agente_id FROM contactos WHERE id = ?", (cid,)).fetchone()
            existing_agente_id = row['agente_id'] if row else None
            final_agente_id = existing_agente_id if existing_agente_id is not None else agente_id
            
            conn.execute("""
                UPDATE contactos SET
                    nombre=?, apellido=?, calificacion=?, categoria=?, ultimo_contacto=?, 
                    fecha_nacimiento=?, aniversario_casa=?, rol=?, referente=?, notas=?, 
                    telefono=?, email=?, busqueda_activa=?, filtros_busqueda_json=?,
                    campos_personalizados_json=?,
                    mac=?, intencion_ia=?, recordatorio_activo=?, recordatorio_dias=?, recordatorio_fecha=?,
                    agente_id=?
                WHERE id = ?
            """, (
                data.get('nombre'), data.get('apellido'), data.get('calificacion', 0),
                data.get('categoria', 'C'), data.get('ultimo_contacto'),
                data.get('fecha_nacimiento'), data.get('aniversario_casa'),
                data.get('rol'), data.get('referente'), data.get('notas'),
                tel, data.get('email'),
                data.get('busqueda_activa', 0), data.get('filtros_busqueda_json'),
                custom_json,
                data.get('mac', 0), data.get('intencion_ia'),
                data.get('recordatorio_activo', 0), data.get('recordatorio_dias'), data.get('recordatorio_fecha'),
                final_agente_id,
                cid
            ))
            conn.commit()
            return cid
        except Exception as e:
            print(f"Error actualizando contacto por ID {cid}: {e}")
            return None
        finally:
            conn.close()

    # CASE 2: No ID (New contact or Excel sync)
    try:
        found_id = None
        if tel:
            row = conn.execute("SELECT id FROM contactos WHERE telefono = ?", (tel,)).fetchone()
            if row: found_id = row['id']
        
        # Fallback deduplication by (nombre, apellido) if phone is missing or not matched
        if not found_id:
            nom = (data.get('nombre') or '').strip()
            ape = (data.get('apellido') or '').strip()
            if nom or ape:
                row = conn.execute(
                    "SELECT id FROM contactos WHERE LOWER(COALESCE(nombre, '')) = LOWER(?) AND LOWER(COALESCE(apellido, '')) = LOWER(?)",
                    (nom, ape)
                ).fetchone()
                if row: found_id = row['id']

        if found_id:
            row = conn.execute("SELECT agente_id FROM contactos WHERE id = ?", (found_id,)).fetchone()
            existing_agente_id = row['agente_id'] if row else None
            final_agente_id = existing_agente_id if existing_agente_id is not None else agente_id
            
            conn.execute("""
                UPDATE contactos SET
                    nombre=?, apellido=?, calificacion=?, categoria=?, ultimo_contacto=?, 
                    fecha_nacimiento=?, aniversario_casa=?, rol=?, referente=?, notas=?, 
                    email=?, busqueda_activa=?, filtros_busqueda_json=?,
                    campos_personalizados_json=?,
                    mac=?, intencion_ia=?, recordatorio_activo=?, recordatorio_dias=?, recordatorio_fecha=?,
                    agente_id=?
                WHERE id = ?
            """, (
                data.get('nombre'), data.get('apellido'), data.get('calificacion', 0),
                data.get('categoria', 'C'), data.get('ultimo_contacto'),
                data.get('fecha_nacimiento'), data.get('aniversario_casa'),
                data.get('rol'), data.get('referente'), data.get('notas'),
                data.get('email'), data.get('busqueda_activa', 0), data.get('filtros_busqueda_json'),
                custom_json,
                data.get('mac', 0), data.get('intencion_ia'),
                data.get('recordatorio_activo', 0), data.get('recordatorio_dias'), data.get('recordatorio_fecha'),
                final_agente_id,
                found_id
            ))
            conn.commit()
            return found_id
        else:
            cursor = conn.execute("""
                INSERT INTO contactos (
                    nombre, apellido, calificacion, categoria, ultimo_contacto, 
                    fecha_nacimiento, aniversario_casa, rol, referente, notas, 
                    telefono, email, busqueda_activa, filtros_busqueda_json,
                    campos_personalizados_json,
                    mac, intencion_ia, recordatorio_activo, recordatorio_dias, recordatorio_fecha,
                    agente_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data.get('nombre'), data.get('apellido'), data.get('calificacion', 0),
                data.get('categoria', 'C'), data.get('ultimo_contacto'),
                data.get('fecha_nacimiento'), data.get('aniversario_casa'),
                data.get('rol'), data.get('referente'), data.get('notas'),
                tel, data.get('email'),
                data.get('busqueda_activa', 0), data.get('filtros_busqueda_json'),
                custom_json,
                data.get('mac', 0), data.get('intencion_ia'),
                data.get('recordatorio_activo', 0), data.get('recordatorio_dias'), data.get('recordatorio_fecha'),
                agente_id
            ))
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        print(f"Error en save_contacto: {e}")
        return None
    finally:
        conn.close()

def insert_contacto(data):
    """Legacy wrapper for backward compatibility with Excel sync."""
    return save_contacto(data)

def get_recordatorios_pendientes():
    """Get active reminders where the target date is today or earlier.
    Scoped to the current agent unless user is superadmin."""
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    agent_id, is_superadmin = _get_agent_filter()
    conn = _get_db()
    try:
        if is_superadmin or agent_id is None:
            query = """
                SELECT id, nombre, apellido, telefono, recordatorio_fecha, notas
                FROM contactos 
                WHERE recordatorio_activo = 1 
                  AND recordatorio_fecha IS NOT NULL
                  AND recordatorio_fecha <= ?
                  AND eliminado_el IS NULL
                ORDER BY recordatorio_fecha ASC
            """
            rows = conn.execute(query, (today,)).fetchall()
        else:
            query = """
                SELECT id, nombre, apellido, telefono, recordatorio_fecha, notas
                FROM contactos 
                WHERE recordatorio_activo = 1 
                  AND recordatorio_fecha IS NOT NULL
                  AND recordatorio_fecha <= ?
                  AND agente_id = ?
                  AND eliminado_el IS NULL
                ORDER BY recordatorio_fecha ASC
            """
            rows = conn.execute(query, (today, agent_id)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_contactos(limit=5000, offset=0, cold_only=False, sort_by='calificacion', order='DESC', busqueda=None):
    """Get list of contacts with optional filtering, search and sorting."""
    from datetime import datetime, timedelta
    conn = _get_db()
    try:
        # Validate sort field to prevent SQL injection
        allowed_sorts = ['nombre', 'apellido', 'calificacion', 'categoria', 'ultimo_contacto']
        if sort_by not in allowed_sorts:
            sort_by = 'calificacion'
        
        order = 'ASC' if order.upper() == 'ASC' else 'DESC'
        
        params = []
        where_clauses = ["eliminado_el IS NULL"]
        
        # Check current user to filter by agent unless they are the superadmin (GermanMazza)
        try:
            from flask import has_request_context
            from flask_login import current_user
            if has_request_context() and current_user and current_user.is_authenticated:
                if current_user.usuario != 'GermanMazza':
                    where_clauses.append("agente_id = ?")
                    params.append(current_user.id)
        except Exception as e:
            pass
            
        if cold_only:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            where_clauses.append("(ultimo_contacto < ? OR ultimo_contacto IS NULL OR ultimo_contacto = '')")
            where_clauses.append("estado_seguimiento = 'activo'")
            params.append(thirty_days_ago)

        if busqueda:
            term = f'%{busqueda}%'
            where_clauses.append("(nombre LIKE ? OR apellido LIKE ? OR telefono LIKE ?)")
            params.extend([term, term, term])
        
        where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''
        query = f"SELECT * FROM contactos {where_sql} ORDER BY {sort_by} {order}, nombre ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def count_contactos_frios():
    """Count contacts not contacted in the last 30 days.
    Scoped to the current agent unless user is superadmin."""
    from datetime import datetime, timedelta
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    agent_id, is_superadmin = _get_agent_filter()
    conn = _get_db()
    try:
        if is_superadmin or agent_id is None:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM contactos WHERE (ultimo_contacto < ? OR ultimo_contacto IS NULL OR ultimo_contacto = '') AND estado_seguimiento = 'activo' AND eliminado_el IS NULL",
                (thirty_days_ago,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM contactos WHERE (ultimo_contacto < ? OR ultimo_contacto IS NULL OR ultimo_contacto = '') AND estado_seguimiento = 'activo' AND agente_id = ? AND eliminado_el IS NULL",
                (thirty_days_ago, agent_id)
            ).fetchone()
        return row['count'] if row else 0
    finally:
        conn.close()

def get_contacto_by_phone(phone):
    """Find a contact by cleaned phone number."""
    if not phone: return None
    clean_p = clean_phone_argentina(phone)
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM contactos WHERE telefono = ? AND eliminado_el IS NULL", (clean_p,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_fidelizacion_hoy():
    """Get contacts with birthdays or anniversaries today.
    Scoped to the current agent unless user is superadmin."""
    from datetime import datetime
    today_md = datetime.now().strftime('%m-%d') # Month-Day only
    agent_id, is_superadmin = _get_agent_filter()
    conn = _get_db()
    try:
        if is_superadmin or agent_id is None:
            cumples = conn.execute("SELECT * FROM contactos WHERE STRFTIME('%m-%d', fecha_nacimiento) = ? AND eliminado_el IS NULL", (today_md,)).fetchall()
            aniversarios = conn.execute("SELECT * FROM contactos WHERE STRFTIME('%m-%d', aniversario_casa) = ? AND eliminado_el IS NULL", (today_md,)).fetchall()
        else:
            cumples = conn.execute("SELECT * FROM contactos WHERE STRFTIME('%m-%d', fecha_nacimiento) = ? AND agente_id = ? AND eliminado_el IS NULL", (today_md, agent_id)).fetchall()
            aniversarios = conn.execute("SELECT * FROM contactos WHERE STRFTIME('%m-%d', aniversario_casa) = ? AND agente_id = ? AND eliminado_el IS NULL", (today_md, agent_id)).fetchall()
        return {
            'cumples': [dict(r) for r in cumples],
            'aniversarios': [dict(r) for r in aniversarios]
        }
    finally:
        conn.close()

def update_contacto_campo(contacto_id, campo, valor):
    """Generic update for contact fields (category, search, etc)."""
    conn = _get_db()
    try:
        # Validate column name to be extra safe against SQL injection
        allowed_fields = ['categoria', 'calificacion', 'ultimo_contacto', 'busqueda_activa', 'estado_seguimiento', 'recordatorio_activo', 'recordatorio_fecha']
        if campo in allowed_fields:
            conn.execute(f"UPDATE contactos SET {campo} = ? WHERE id = ?", (valor, contacto_id))
            conn.commit()
    finally:
        conn.close()

def get_contacto(contacto_id):
    """Find a contact by ID."""
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM contactos WHERE id = ? AND eliminado_el IS NULL", (contacto_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def delete_contacto_soft(contacto_id, deleted_by="Usuario"):
    """Marks a contact as deleted (Soft-delete)."""
    from database.db_papelera import soft_delete_record
    return soft_delete_record('contactos', contacto_id, deleted_by)

def get_proximos_eventos(limit=6, dt=None):
    """Obtiene los próximos eventos (días patrios, feriados, festividades argentinas, cumpleaños y aniversarios de compra)."""
    from lib.eventos import get_proximos_eventos as _get_ev
    agent_id, is_superadmin = _get_agent_filter()
    return _get_ev(agente_id=agent_id, limit=limit, dt=dt, is_superadmin=is_superadmin)

