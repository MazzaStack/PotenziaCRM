"""
Módulo de Base de Datos para la Papelera de Reciclaje (Soft-Delete).
Permite visualizar, restaurar y purgar registros borrados lógicamente,
con aislamiento estricto por Oficina para Brokers y visualización extendida para Administradores.
"""
from datetime import datetime, timedelta
import json

def _get_db():
    from database.db import get_db
    return get_db()

def _get_oficina_filter_sql(table_prefix="t", agent_col="agente_id", oficina_id=None, include_unassigned=False):
    """
    Construye las cláusulas SQL para filtrar por oficina y/o agentes sueltos.
    """
    params = []
    if oficina_id == 'all' or oficina_id is None:
        return "", []
    
    if include_unassigned:
        clause = f"({table_prefix}.{agent_col} IN (SELECT id FROM usuarios WHERE oficina_id = ? OR oficina_id IS NULL) OR {table_prefix}.{agent_col} IS NULL)"
        params.append(oficina_id)
    else:
        clause = f"{table_prefix}.{agent_col} IN (SELECT id FROM usuarios WHERE oficina_id = ?)"
        params.append(oficina_id)
        
    return clause, params

def soft_delete_record(table_name, record_id, deleted_by="Sistema"):
    """Marca un registro como eliminado lógicamente."""
    allowed_tables = {
        'contactos': 'contactos',
        'propiedades': 'propiedades',
        'lotes': 'lotes',
        'seguimiento_operaciones': 'seguimiento_operaciones',
        'busquedas_clientes': 'busquedas_clientes',
        'enlaces_fichas_clientes': 'enlaces_fichas_clientes'
    }
    target_table = allowed_tables.get(table_name)
    if not target_table:
        return False
        
    conn = _get_db()
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            f"UPDATE {target_table} SET eliminado_el = ?, eliminado_por = ? WHERE id = ?",
            (now_str, str(deleted_by), record_id)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[Papelera] Error en soft_delete_record ({table_name} #{record_id}): {e}")
        return False
    finally:
        conn.close()

def restore_record(table_name, record_id):
    """Restaura un registro borrado lógicamente devolviéndolo a estado activo."""
    allowed_tables = {
        'contactos': 'contactos',
        'propiedades': 'propiedades',
        'lotes': 'lotes',
        'seguimiento_operaciones': 'seguimiento_operaciones',
        'busquedas_clientes': 'busquedas_clientes',
        'enlaces_fichas_clientes': 'enlaces_fichas_clientes'
    }
    target_table = allowed_tables.get(table_name)
    if not target_table:
        return False
        
    conn = _get_db()
    try:
        conn.execute(
            f"UPDATE {target_table} SET eliminado_el = NULL, eliminado_por = NULL WHERE id = ?",
            (record_id,)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[Papelera] Error en restore_record ({table_name} #{record_id}): {e}")
        return False
    finally:
        conn.close()

def purge_record(table_name, record_id):
    """Eliminación física definitiva de un registro."""
    allowed_tables = {
        'contactos': 'contactos',
        'propiedades': 'propiedades',
        'lotes': 'lotes',
        'seguimiento_operaciones': 'seguimiento_operaciones',
        'busquedas_clientes': 'busquedas_clientes',
        'enlaces_fichas_clientes': 'enlaces_fichas_clientes'
    }
    target_table = allowed_tables.get(table_name)
    if not target_table:
        return False
        
    conn = _get_db()
    try:
        conn.execute(f"DELETE FROM {target_table} WHERE id = ?", (record_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[Papelera] Error en purge_record ({table_name} #{record_id}): {e}")
        return False
    finally:
        conn.close()

def get_papelera_items(oficina_id=None, include_unassigned=False, user_id=None, is_superadmin=False):
    """
    Obtiene todos los elementos en papelera categorizados por entidad,
    respetando los permisos del usuario (Superadmin, Admin o Broker de Oficina).
    """
    conn = _get_db()
    res = {
        'contactos': [],
        'propiedades': [],
        'lotes': [],
        'operaciones': [],
        'busquedas': [],
        'fichas': [],
        'total_count': 0
    }
    
    try:
        # Helper para ejecutar query con o sin filtro de oficina
        def _build_and_run(query_base, agent_field="agente_id"):
            where_parts = ["t.eliminado_el IS NOT NULL"]
            params = []
            
            if not is_superadmin and oficina_id is not None and oficina_id != 'all':
                if include_unassigned:
                    where_parts.append(f"(u.oficina_id = ? OR u.oficina_id IS NULL OR t.{agent_field} IS NULL)")
                    params.append(oficina_id)
                else:
                    where_parts.append("u.oficina_id = ?")
                    params.append(oficina_id)
                    
            full_sql = f"{query_base} WHERE {' AND '.join(where_parts)} ORDER BY t.eliminado_el DESC"
            return conn.execute(full_sql, params).fetchall()

        # 1. Contactos
        q_cont = """
            SELECT t.id, t.nombre, t.apellido, t.telefono, t.email, t.categoria, t.eliminado_el, t.eliminado_por,
                   COALESCE(u.nombre_display, u.usuario, 'Sin Asignar') as agente_nombre,
                   COALESCE(ofi.nombre, 'Sin Oficina') as oficina_nombre
            FROM contactos t
            LEFT JOIN usuarios u ON t.agente_id = u.id
            LEFT JOIN oficinas ofi ON u.oficina_id = ofi.id
        """
        for r in _build_and_run(q_cont, "agente_id"):
            res['contactos'].append(dict(r))

        # 2. Propiedades
        q_props = """
            SELECT t.id, t.titulo, t.direccion, t.barrio, t.precio, t.moneda, t.tipo_operacion, t.tipo_propiedad, t.eliminado_el, t.eliminado_por,
                   COALESCE(u.nombre_display, u.usuario, 'Sin Asignar') as agente_nombre,
                   COALESCE(ofi.nombre, 'Sin Oficina') as oficina_nombre
            FROM propiedades t
            LEFT JOIN usuarios u ON t.agente_id = u.id
            LEFT JOIN oficinas ofi ON u.oficina_id = ofi.id
        """
        for r in _build_and_run(q_props, "agente_id"):
            res['propiedades'].append(dict(r))

        # 3. Lotes
        q_lotes = """
            SELECT t.id, t.barrio, t.numero, t.area, t.metros, t.valor, t.usuario, t.eliminado_el, t.eliminado_por,
                   COALESCE(u.nombre_display, u.usuario, t.usuario, 'Sin Asignar') as agente_nombre,
                   COALESCE(ofi.nombre, 'Sin Oficina') as oficina_nombre
            FROM lotes t
            LEFT JOIN usuarios u ON t.usuario = u.usuario
            LEFT JOIN oficinas ofi ON u.oficina_id = ofi.id
        """
        for r in _build_and_run(q_lotes, "usuario"):
            res['lotes'].append(dict(r))

        # 4. Operaciones
        q_ops = """
            SELECT t.id, t.domicilio, t.estado, t.bruto, t.cierre, t.eliminado_el, t.eliminado_por,
                   COALESCE(u.nombre_display, u.usuario, 'Sin Asignar') as agente_nombre,
                   COALESCE(ofi.nombre, 'Sin Oficina') as oficina_nombre
            FROM seguimiento_operaciones t
            LEFT JOIN usuarios u ON t.agente_id = u.id
            LEFT JOIN oficinas ofi ON u.oficina_id = ofi.id
        """
        for r in _build_and_run(q_ops, "agente_id"):
            res['operaciones'].append(dict(r))

        # 5. Búsquedas Clientes
        q_busq = """
            SELECT t.id, t.nombre, t.tipo_operacion, t.zona, t.min_precio, t.max_precio, t.eliminado_el, t.eliminado_por,
                   COALESCE(u.nombre_display, u.usuario, 'Sin Asignar') as agente_nombre,
                   COALESCE(ofi.nombre, 'Sin Oficina') as oficina_nombre
            FROM busquedas_clientes t
            LEFT JOIN usuarios u ON t.agente_id = u.id
            LEFT JOIN oficinas ofi ON u.oficina_id = ofi.id
        """
        for r in _build_and_run(q_busq, "agente_id"):
            res['busquedas'].append(dict(r))

        # 6. Fichas Clientes
        q_fichas = """
            SELECT t.id, t.titulo, t.codigo_slug, t.vistas_count, t.created_at, t.eliminado_el, t.eliminado_por,
                   COALESCE(u.nombre_display, u.usuario, t.agente_nombre, 'Sin Asignar') as agente_nombre,
                   COALESCE(ofi.nombre, 'Sin Oficina') as oficina_nombre
            FROM enlaces_fichas_clientes t
            LEFT JOIN usuarios u ON t.agente_id = u.id
            LEFT JOIN oficinas ofi ON u.oficina_id = ofi.id
        """
        for r in _build_and_run(q_fichas, "agente_id"):
            res['fichas'].append(dict(r))

        res['total_count'] = (
            len(res['contactos']) +
            len(res['propiedades']) +
            len(res['lotes']) +
            len(res['operaciones']) +
            len(res['busquedas']) +
            len(res['fichas'])
        )
        return res
    finally:
        conn.close()

def vaciar_papelera_scope(oficina_id=None, include_unassigned=False, is_superadmin=False, table_name=None):
    """Purga masivamente los elementos eliminados de la papelera dentro del ámbito permitido."""
    allowed_tables = ['contactos', 'propiedades', 'lotes', 'seguimiento_operaciones', 'busquedas_clientes', 'enlaces_fichas_clientes']
    tables_to_purge = [table_name] if table_name and table_name in allowed_tables else allowed_tables
    
    conn = _get_db()
    try:
        purged_count = 0
        for t in tables_to_purge:
            agent_col = "usuario" if t == 'lotes' else "agente_id"
            if is_superadmin or oficina_id == 'all' or oficina_id is None:
                cur = conn.execute(f"DELETE FROM {t} WHERE eliminado_el IS NOT NULL")
            elif include_unassigned:
                if t == 'lotes':
                    cur = conn.execute(f"DELETE FROM {t} WHERE eliminado_el IS NOT NULL AND ({agent_col} IN (SELECT usuario FROM usuarios WHERE oficina_id = ? OR oficina_id IS NULL) OR {agent_col} IS NULL)", (oficina_id,))
                else:
                    cur = conn.execute(f"DELETE FROM {t} WHERE eliminado_el IS NOT NULL AND ({agent_col} IN (SELECT id FROM usuarios WHERE oficina_id = ? OR oficina_id IS NULL) OR {agent_col} IS NULL)", (oficina_id,))
            else:
                if t == 'lotes':
                    cur = conn.execute(f"DELETE FROM {t} WHERE eliminado_el IS NOT NULL AND {agent_col} IN (SELECT usuario FROM usuarios WHERE oficina_id = ?)", (oficina_id,))
                else:
                    cur = conn.execute(f"DELETE FROM {t} WHERE eliminado_el IS NOT NULL AND {agent_col} IN (SELECT id FROM usuarios WHERE oficina_id = ?)", (oficina_id,))
            purged_count += (cur.rowcount or 0)
            
        conn.commit()
        return purged_count
    finally:
        conn.close()
