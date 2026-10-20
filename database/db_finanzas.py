"""
Database queries for sales operations, office finances, cash registers, OPEX and P&L.
Strict multi-tenant isolation by oficina_id.
"""
import sqlite3
import json
from datetime import datetime

def _get_db(db_path=None):
    from database.db import get_db, MASTER_DB_PATH
    return get_db(db_path or MASTER_DB_PATH)

def _clean_float(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).replace('$', '').replace('%', '').strip()
    if not val_str or val_str.lower() in ('none', 'null', 'nan'):
        return None
    if ',' in val_str and '.' in val_str:
        if val_str.rfind(',') > val_str.rfind('.'):
            val_str = val_str.replace('.', '').replace(',', '.')
        else:
            val_str = val_str.replace(',', '')
    elif ',' in val_str:
        val_str = val_str.replace(',', '.')
    try:
        return float(val_str)
    except (ValueError, TypeError):
        return None

def _clean_int(val, default=None):
    if val is None:
        return default
    try:
        val_str = str(val).strip()
        if not val_str or val_str.lower() in ('none', 'null', 'nan'):
            return default
        return int(float(val_str))
    except (ValueError, TypeError):
        return default

def _clean_bool(val):
    if val in (1, '1', True, 'true', 'True', 'on', 'yes', 'si', 'sí'):
        return 1
    return 0

def _clean_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None

def init_finanzas_tables():
    """Ensures that all modern finance tables exist in database."""
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS finanzas_cajas_bancos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oficina_id INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'caja_efectivo',
                moneda TEXT NOT NULL DEFAULT 'USD',
                saldo_inicial REAL DEFAULT 0.0,
                activa INTEGER DEFAULT 1,
                fecha_creacion TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS finanzas_proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oficina_id INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                cuit_rut TEXT,
                rubro TEXT,
                contacto TEXT,
                telefono TEXT,
                email TEXT,
                fecha_creacion TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS finanzas_gastos_opex (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oficina_id INTEGER NOT NULL,
                proveedor_id INTEGER,
                descripcion TEXT NOT NULL,
                categoria TEXT DEFAULT 'operativo',
                monto REAL NOT NULL DEFAULT 0.0,
                moneda TEXT DEFAULT 'ARS',
                tipo_cambio REAL DEFAULT 1.0,
                fecha_emision TEXT,
                fecha_vencimiento TEXT,
                fecha_pago TEXT,
                estado TEXT DEFAULT 'pendiente',
                caja_id INTEGER,
                comprobante_url TEXT,
                notas TEXT,
                fecha_registro TEXT DEFAULT (datetime('now', 'localtime')),
                modificado_por TEXT DEFAULT 'usuario'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS finanzas_movimientos_caja (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                oficina_id INTEGER NOT NULL,
                caja_id INTEGER NOT NULL,
                tipo_movimiento TEXT NOT NULL,
                origen TEXT,
                origen_id INTEGER,
                monto REAL NOT NULL,
                moneda TEXT NOT NULL,
                tipo_cambio REAL DEFAULT 1.0,
                monto_caja REAL DEFAULT NULL,
                descripcion TEXT,
                fecha_movimiento TEXT DEFAULT (datetime('now', 'localtime')),
                modificado_por TEXT DEFAULT 'usuario'
            )
        """)
        # Safe column additions for existing databases
        for col_def in ["tipo_cambio REAL DEFAULT 1.0", "monto_caja REAL DEFAULT NULL"]:
            try:
                conn.execute(f"ALTER TABLE finanzas_movimientos_caja ADD COLUMN {col_def}")
            except Exception:
                pass
        conn.commit()
    except Exception as e:
        print(f"[init_finanzas_tables] Warning: {e}")
    finally:
        conn.close()

# Auto-initialize on import
try:
    init_finanzas_tables()
except Exception:
    pass

# ==========================================
# 1. SEGUIMIENTO DE OPERACIONES (VENTAS)
# ==========================================

def get_operaciones(agente_id=None, oficina_id=None):
    """Gets all sales operations, filtered by agent or office if provided."""
    conn = _get_db()
    try:
        query = """
            SELECT o.*, COALESCE(u.nombre_display, u.usuario, 'Agente') as agente_nombre, u.oficina_id as agente_oficina_id
            FROM seguimiento_operaciones o
            LEFT JOIN usuarios u ON o.agente_id = u.id
        """
        params = []
        where_clauses = ["o.eliminado_el IS NULL"]
        if agente_id:
            where_clauses.append("o.agente_id = ?")
            params.append(_clean_int(agente_id))
        elif oficina_id:
            where_clauses.append("u.oficina_id = ?")
            params.append(_clean_int(oficina_id))
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
            
        query += " ORDER BY o.cierre DESC, o.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def save_operacion(data):
    """Inserts or updates an operation record in Master DB."""
    conn = _get_db()
    try:
        raw_oid = data.get('id')
        oid = _clean_int(raw_oid)
        
        fields = [
            'agente_id', 'comision_rendida', 'iva_rendido', 'doc_rendida', 'domicilio',
            'juris', 'puntas', 'porcentaje', 'cierre', 'bruto', 'neto', 'pago',
            'estado', 'mes', 'colaborador', 'particularidades', 'refuerzo',
            'fecha_reserva', 'fecha_firma', 'ad_ref_comp', 'ad_ref_vend',
            'proforma', 'sucesion', 'doc_escribania', 'informes', 'estado_parc',
            'modificado_por'
        ]
        
        clean_data = {
            'agente_id': _clean_int(data.get('agente_id')),
            'comision_rendida': _clean_bool(data.get('comision_rendida')),
            'iva_rendido': _clean_bool(data.get('iva_rendido')),
            'doc_rendida': _clean_bool(data.get('doc_rendida')),
            'domicilio': _clean_str(data.get('domicilio')),
            'juris': _clean_str(data.get('juris')),
            'puntas': _clean_str(data.get('puntas')),
            'porcentaje': _clean_float(data.get('porcentaje')),
            'cierre': _clean_str(data.get('cierre')),
            'bruto': _clean_float(data.get('bruto')),
            'neto': _clean_float(data.get('neto')),
            'pago': _clean_str(data.get('pago')),
            'informes': _clean_str(data.get('informes')),
            'estado_parc': _clean_str(data.get('estado_parc')),
            'refuerzo': _clean_str(data.get('refuerzo')),
            'sucesion': _clean_str(data.get('sucesion')),
            'doc_escribania': _clean_str(data.get('doc_escribania')),
            'proforma': _clean_str(data.get('proforma')),
            'ad_ref_comp': _clean_str(data.get('ad_ref_comp')),
            'ad_ref_vend': _clean_str(data.get('ad_ref_vend')),
            'fecha_reserva': _clean_str(data.get('fecha_reserva')),
            'fecha_firma': _clean_str(data.get('fecha_firma')),
            'particularidades': _clean_str(data.get('particularidades')),
            'estado': _clean_str(data.get('estado')),
            'mes': _clean_str(data.get('mes')),
            'colaborador': _clean_str(data.get('colaborador')),
            'modificado_por': _clean_str(data.get('modificado_por')) or 'usuario'
        }
        
        if oid:
            set_clause = ", ".join([f"{f} = ?" for f in fields])
            params = [clean_data.get(f) for f in fields]
            params.append(oid)
            conn.execute(f"UPDATE seguimiento_operaciones SET {set_clause} WHERE id = ?", params)
        else:
            placeholders = ", ".join(["?"] * len(fields))
            cols = ", ".join(fields)
            params = [clean_data.get(f) for f in fields]
            cursor = conn.execute(f"INSERT INTO seguimiento_operaciones ({cols}) VALUES ({placeholders})", params)
            oid = cursor.lastrowid
            
        conn.commit()
        return oid
    finally:
        conn.close()

def delete_operacion(oid, agente_id=None, deleted_by=None):
    """Soft-deletes an operation record."""
    if not deleted_by:
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                deleted_by = current_user.nombre_display or current_user.usuario
        except Exception:
            deleted_by = "Sistema"
    from database.db_papelera import soft_delete_record
    return soft_delete_record('seguimiento_operaciones', _clean_int(oid), deleted_by=deleted_by or "Sistema")

# ==========================================
# 2. DEUDAS Y GASTOS FIJOS DE AGENTES
# ==========================================

def get_deudas(agente_id=None, estado=None, oficina_id=None):
    """Gets all debts, filtered by agent, office, and status."""
    conn = _get_db()
    try:
        query = """
            SELECT d.*, COALESCE(u.nombre_display, u.usuario, 'Agente') as agente_nombre, u.oficina_id as agente_oficina_id
            FROM finanzas_deudas d
            LEFT JOIN usuarios u ON d.agente_id = u.id
            WHERE 1=1
        """
        params = []
        if agente_id:
            query += " AND d.agente_id = ?"
            params.append(_clean_int(agente_id))
        elif oficina_id:
            query += " AND u.oficina_id = ?"
            params.append(_clean_int(oficina_id))
            
        if estado:
            query += " AND d.estado = ?"
            params.append(estado)
            
        query += " ORDER BY d.fecha_vencimiento ASC, d.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def save_deuda(data):
    """Inserts or updates a debt record."""
    conn = _get_db()
    try:
        raw_did = data.get('id')
        did = _clean_int(raw_did)
        
        fields = ['agente_id', 'descripcion', 'monto', 'moneda', 'fecha_vencimiento', 'estado', 'tipo', 'modificado_por']
        clean_data = {
            'agente_id': _clean_int(data.get('agente_id')),
            'descripcion': _clean_str(data.get('descripcion')),
            'monto': _clean_float(data.get('monto')) or 0.0,
            'moneda': _clean_str(data.get('moneda')) or 'USD',
            'fecha_vencimiento': _clean_str(data.get('fecha_vencimiento')),
            'estado': _clean_str(data.get('estado')) or 'falta',
            'tipo': _clean_str(data.get('tipo')) or 'mensual',
            'modificado_por': _clean_str(data.get('modificado_por')) or 'usuario'
        }
        
        if did:
            set_clause = ", ".join([f"{f} = ?" for f in fields])
            params = [clean_data.get(f) for f in fields]
            params.append(did)
            conn.execute(f"UPDATE finanzas_deudas SET {set_clause} WHERE id = ?", params)
        else:
            placeholders = ", ".join(["?"] * len(fields))
            cols = ", ".join(fields)
            params = [clean_data.get(f) for f in fields]
            cursor = conn.execute(f"INSERT INTO finanzas_deudas ({cols}) VALUES ({placeholders})", params)
            did = cursor.lastrowid
            
        conn.commit()
        return did
    finally:
        conn.close()

def get_config_deuda_agente(agente_id):
    """Gets the recurring debt configuration for an agent."""
    conn = _get_db()
    try:
        aid = _clean_int(agente_id)
        row = conn.execute("SELECT * FROM config_deudas_agentes WHERE agente_id = ?", (aid,)).fetchone()
        return dict(row) if row else {'agente_id': aid, 'monto_oficina': 80, 'moneda_oficina': 'USD', 'otros_gastos_json': '[]'}
    finally:
        conn.close()

def save_config_deuda_agente(data):
    """Saves recurring debt configuration."""
    conn = _get_db()
    try:
        aid = _clean_int(data['agente_id'])
        monto = _clean_float(data.get('monto_oficina')) or 0.0
        moneda = _clean_str(data.get('moneda_oficina')) or 'USD'
        otros = data.get('otros_gastos_json')
        if not isinstance(otros, str):
            otros = json.dumps(otros or [])
        conn.execute("""
            INSERT OR REPLACE INTO config_deudas_agentes (agente_id, monto_oficina, moneda_oficina, otros_gastos_json)
            VALUES (?, ?, ?, ?)
        """, (aid, monto, moneda, otros))
        conn.commit()
    finally:
        conn.close()

# ==========================================
# 3. CAJAS, BANCOS Y TESORERÍA (MULTI-TENANT)
# ==========================================

def get_cajas_bancos(oficina_id=None):
    """Gets all cash registers and bank accounts for an office, with real computed balance."""
    conn = _get_db()
    try:
        query = "SELECT * FROM finanzas_cajas_bancos WHERE activa = 1"
        params = []
        if oficina_id:
            query += " AND oficina_id = ?"
            params.append(_clean_int(oficina_id))
        query += " ORDER BY id ASC"
        
        rows = conn.execute(query, params).fetchall()
        cajas = [dict(r) for r in rows]
        
        # Calculate real-time balance for each account: saldo_inicial + ingresos - egresos (in caja's native currency)
        for c in cajas:
            cid = c['id']
            c_moneda = c.get('moneda', 'USD')
            m_rows = conn.execute(
                "SELECT tipo_movimiento, monto, moneda, COALESCE(tipo_cambio, 1.0) as tipo_cambio, monto_caja FROM finanzas_movimientos_caja WHERE caja_id = ?",
                (cid,)
            ).fetchall()
            
            saldo = float(c.get('saldo_inicial') or 0.0)
            for m in m_rows:
                m_monto_caja = m['monto_caja']
                if m_monto_caja is not None and float(m_monto_caja or 0) > 0:
                    eff_monto = float(m_monto_caja)
                else:
                    m_monto = float(m['monto'] or 0.0)
                    m_moneda = m['moneda']
                    tc = float(m['tipo_cambio'] or 1.0)
                    if tc <= 0:
                        tc = 1.0
                    if m_moneda == c_moneda:
                        eff_monto = m_monto
                    elif c_moneda == 'ARS' and m_moneda == 'USD':
                        eff_monto = m_monto * (tc if tc > 1 else 1530.0)
                    elif c_moneda == 'USD' and m_moneda == 'ARS':
                        eff_monto = m_monto / (tc if tc > 1 else 1530.0)
                    else:
                        eff_monto = m_monto
                        
                if m['tipo_movimiento'] in ('ingreso', 'entrada'):
                    saldo += eff_monto
                elif m['tipo_movimiento'] in ('egreso', 'salida'):
                    saldo -= eff_monto
            c['saldo_actual'] = saldo
            
        return cajas
    finally:
        conn.close()

def get_caja_by_id(caja_id, oficina_id=None):
    """Gets a specific cash register by ID with office validation."""
    conn = _get_db()
    try:
        cid = _clean_int(caja_id)
        if not cid:
            return None
        query = "SELECT * FROM finanzas_cajas_bancos WHERE id = ?"
        params = [cid]
        if oficina_id:
            query += " AND oficina_id = ?"
            params.append(_clean_int(oficina_id))
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def save_caja_banco(data):
    """Inserts or updates a cash register / bank account."""
    conn = _get_db()
    try:
        cid = _clean_int(data.get('id'))
        oficina_id = _clean_int(data.get('oficina_id'))
        if not oficina_id:
            return None
            
        nombre = _clean_str(data.get('nombre')) or 'Caja Principal'
        tipo = _clean_str(data.get('tipo')) or 'caja_efectivo'
        moneda = _clean_str(data.get('moneda')) or 'USD'
        saldo_inicial = _clean_float(data.get('saldo_inicial')) or 0.0
        activa = _clean_bool(data.get('activa', 1))
        
        if cid:
            conn.execute("""
                UPDATE finanzas_cajas_bancos 
                SET nombre = ?, tipo = ?, moneda = ?, saldo_inicial = ?, activa = ?
                WHERE id = ? AND oficina_id = ?
            """, (nombre, tipo, moneda, saldo_inicial, activa, cid, oficina_id))
        else:
            cur = conn.execute("""
                INSERT INTO finanzas_cajas_bancos (oficina_id, nombre, tipo, moneda, saldo_inicial, activa)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (oficina_id, nombre, tipo, moneda, saldo_inicial, activa))
            cid = cur.lastrowid
            
        conn.commit()
        return cid
    finally:
        conn.close()

def delete_caja_banco(caja_id, oficina_id=None):
    """Soft deletes or deactivates a cash register."""
    conn = _get_db()
    try:
        cid = _clean_int(caja_id)
        if not cid:
            return
        if oficina_id:
            conn.execute("UPDATE finanzas_cajas_bancos SET activa = 0 WHERE id = ? AND oficina_id = ?", (cid, _clean_int(oficina_id)))
        else:
            conn.execute("UPDATE finanzas_cajas_bancos SET activa = 0 WHERE id = ?", (cid,))
        conn.commit()
    finally:
        conn.close()

# ==========================================
# 4. PROVEEDORES (MULTI-TENANT)
# ==========================================

def get_proveedores(oficina_id=None):
    """Gets all registered suppliers for an office."""
    conn = _get_db()
    try:
        query = "SELECT * FROM finanzas_proveedores WHERE 1=1"
        params = []
        if oficina_id:
            query += " AND oficina_id = ?"
            params.append(_clean_int(oficina_id))
        query += " ORDER BY nombre ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_proveedor_by_id(proveedor_id, oficina_id=None):
    """Gets a supplier by ID with office scoping."""
    conn = _get_db()
    try:
        pid = _clean_int(proveedor_id)
        if not pid:
            return None
        query = "SELECT * FROM finanzas_proveedores WHERE id = ?"
        params = [pid]
        if oficina_id:
            query += " AND oficina_id = ?"
            params.append(_clean_int(oficina_id))
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def save_proveedor(data):
    """Inserts or updates a supplier."""
    conn = _get_db()
    try:
        pid = _clean_int(data.get('id'))
        oficina_id = _clean_int(data.get('oficina_id'))
        if not oficina_id:
            return None
            
        nombre = _clean_str(data.get('nombre'))
        if not nombre:
            return None
            
        cuit_rut = _clean_str(data.get('cuit_rut'))
        rubro = _clean_str(data.get('rubro')) or 'General'
        contacto = _clean_str(data.get('contacto'))
        telefono = _clean_str(data.get('telefono'))
        email = _clean_str(data.get('email'))
        
        if pid:
            conn.execute("""
                UPDATE finanzas_proveedores
                SET nombre = ?, cuit_rut = ?, rubro = ?, contacto = ?, telefono = ?, email = ?
                WHERE id = ? AND oficina_id = ?
            """, (nombre, cuit_rut, rubro, contacto, telefono, email, pid, oficina_id))
        else:
            cur = conn.execute("""
                INSERT INTO finanzas_proveedores (oficina_id, nombre, cuit_rut, rubro, contacto, telefono, email)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (oficina_id, nombre, cuit_rut, rubro, contacto, telefono, email))
            pid = cur.lastrowid
            
        conn.commit()
        return pid
    finally:
        conn.close()

def delete_proveedor(proveedor_id, oficina_id=None):
    """Deletes a supplier."""
    conn = _get_db()
    try:
        pid = _clean_int(proveedor_id)
        if not pid:
            return
        if oficina_id:
            conn.execute("DELETE FROM finanzas_proveedores WHERE id = ? AND oficina_id = ?", (pid, _clean_int(oficina_id)))
        else:
            conn.execute("DELETE FROM finanzas_proveedores WHERE id = ?", (pid,))
        conn.commit()
    finally:
        conn.close()

# ==========================================
# 5. GASTOS OPEX / CUENTAS POR PAGAR (MULTI-TENANT)
# ==========================================

def get_gastos_opex(oficina_id=None, estado=None, proveedor_id=None, categoria=None, mes=None):
    """Gets operating expenses for an office with filters."""
    conn = _get_db()
    try:
        query = """
            SELECT g.*, 
                   COALESCE(p.nombre, 'Proveedor Directo') as proveedor_nombre,
                   c.nombre as caja_nombre
            FROM finanzas_gastos_opex g
            LEFT JOIN finanzas_proveedores p ON g.proveedor_id = p.id
            LEFT JOIN finanzas_cajas_bancos c ON g.caja_id = c.id
            WHERE 1=1
        """
        params = []
        if oficina_id:
            query += " AND g.oficina_id = ?"
            params.append(_clean_int(oficina_id))
        if estado:
            query += " AND g.estado = ?"
            params.append(estado)
        if proveedor_id:
            query += " AND g.proveedor_id = ?"
            params.append(_clean_int(proveedor_id))
        if categoria:
            query += " AND g.categoria = ?"
            params.append(categoria)
        if mes:
            query += " AND (g.fecha_vencimiento LIKE ? OR g.fecha_emision LIKE ?)"
            params.extend([f"%{mes}%", f"%{mes}%"])
            
        query += " ORDER BY g.fecha_vencimiento ASC, g.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_gasto_by_id(gasto_id, oficina_id=None):
    """Gets an OPEX expense by ID with office scoping."""
    conn = _get_db()
    try:
        gid = _clean_int(gasto_id)
        if not gid:
            return None
        query = """
            SELECT g.*, COALESCE(p.nombre, 'Proveedor Directo') as proveedor_nombre
            FROM finanzas_gastos_opex g
            LEFT JOIN finanzas_proveedores p ON g.proveedor_id = p.id
            WHERE g.id = ?
        """
        params = [gid]
        if oficina_id:
            query += " AND g.oficina_id = ?"
            params.append(_clean_int(oficina_id))
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def save_gasto_opex(data):
    """Inserts or updates an OPEX expense."""
    conn = _get_db()
    try:
        gid = _clean_int(data.get('id'))
        oficina_id = _clean_int(data.get('oficina_id'))
        if not oficina_id:
            return None
            
        descripcion = _clean_str(data.get('descripcion'))
        if not descripcion:
            return None
            
        proveedor_id = _clean_int(data.get('proveedor_id'))
        categoria = _clean_str(data.get('categoria')) or 'operativo'
        monto = _clean_float(data.get('monto')) or 0.0
        moneda = _clean_str(data.get('moneda')) or 'ARS'
        tipo_cambio = _clean_float(data.get('tipo_cambio')) or 1.0
        fecha_emision = _clean_str(data.get('fecha_emision')) or datetime.now().strftime('%Y-%m-%d')
        fecha_vencimiento = _clean_str(data.get('fecha_vencimiento')) or fecha_emision
        fecha_pago = _clean_str(data.get('fecha_pago'))
        estado = _clean_str(data.get('estado')) or 'pendiente'
        caja_id = _clean_int(data.get('caja_id'))
        comprobante_url = _clean_str(data.get('comprobante_url'))
        notas = _clean_str(data.get('notas'))
        modificado_por = _clean_str(data.get('modificado_por')) or 'usuario'
        
        fields = [
            'oficina_id', 'proveedor_id', 'descripcion', 'categoria', 'monto',
            'moneda', 'tipo_cambio', 'fecha_emision', 'fecha_vencimiento',
            'fecha_pago', 'estado', 'caja_id', 'comprobante_url', 'notas', 'modificado_por'
        ]
        values = [
            oficina_id, proveedor_id, descripcion, categoria, monto,
            moneda, tipo_cambio, fecha_emision, fecha_vencimiento,
            fecha_pago, estado, caja_id, comprobante_url, notas, modificado_por
        ]
        
        if gid:
            set_clause = ", ".join([f"{f} = ?" for f in fields])
            params = values + [gid, oficina_id]
            conn.execute(f"UPDATE finanzas_gastos_opex SET {set_clause} WHERE id = ? AND oficina_id = ?", params)
        else:
            placeholders = ", ".join(["?"] * len(fields))
            cols = ", ".join(fields)
            cur = conn.execute(f"INSERT INTO finanzas_gastos_opex ({cols}) VALUES ({placeholders})", values)
            gid = cur.lastrowid
            
        conn.commit()
        return gid
    finally:
        conn.close()

def pagar_gasto_opex(gasto_id, caja_id, oficina_id, modificado_por='usuario'):
    """Marks an OPEX expense as paid and records an outflow movement in cash register."""
    conn = _get_db()
    try:
        gid = _clean_int(gasto_id)
        cid = _clean_int(caja_id)
        oid = _clean_int(oficina_id)
        if not gid or not cid or not oid:
            return False
            
        # Get gasto details
        gasto = conn.execute(
            "SELECT * FROM finanzas_gastos_opex WHERE id = ? AND oficina_id = ?",
            (gid, oid)
        ).fetchone()
        if not gasto:
            return False
            
        g_dict = dict(gasto)
        now_str = datetime.now().strftime('%Y-%m-%d')
        
        # 1. Update gasto status
        conn.execute("""
            UPDATE finanzas_gastos_opex
            SET estado = 'pagado', fecha_pago = ?, caja_id = ?, modificado_por = ?
            WHERE id = ? AND oficina_id = ?
        """, (now_str, cid, modificado_por, gid, oid))
        
        # 2. Register cash outflow in finanzas_movimientos_caja
        conn.execute("""
            INSERT INTO finanzas_movimientos_caja 
            (oficina_id, caja_id, tipo_movimiento, origen, origen_id, monto, moneda, descripcion, modificado_por)
            VALUES (?, ?, 'egreso', 'gasto_opex', ?, ?, ?, ?, ?)
        """, (
            oid, cid, gid, g_dict['monto'], g_dict['moneda'],
            f"Pago de gasto: {g_dict['descripcion']}", modificado_por
        ))
        
        conn.commit()
        return True
    finally:
        conn.close()

def delete_gasto_opex(gasto_id, oficina_id=None):
    """Deletes an OPEX expense record."""
    conn = _get_db()
    try:
        gid = _clean_int(gasto_id)
        if not gid:
            return
        if oficina_id:
            conn.execute("DELETE FROM finanzas_gastos_opex WHERE id = ? AND oficina_id = ?", (gid, _clean_int(oficina_id)))
        else:
            conn.execute("DELETE FROM finanzas_gastos_opex WHERE id = ?", (gid,))
        conn.commit()
    finally:
        conn.close()

# ==========================================
# 6. MOVIMIENTOS DE CAJA / LIBRO DIARIO
# ==========================================

def registrar_movimiento_caja(data):
    """Inserts a cash register movement (ingreso, egreso, transferencia) with multi-currency conversion."""
    conn = _get_db()
    try:
        oficina_id = _clean_int(data.get('oficina_id'))
        caja_id = _clean_int(data.get('caja_id'))
        if not oficina_id or not caja_id:
            return None
            
        # Get target caja's native currency
        caja_row = conn.execute("SELECT moneda FROM finanzas_cajas_bancos WHERE id = ?", (caja_id,)).fetchone()
        caja_moneda = caja_row['moneda'] if caja_row else 'USD'
        
        tipo_movimiento = _clean_str(data.get('tipo_movimiento')) or 'ingreso'
        origen = _clean_str(data.get('origen')) or 'ajuste_manual'
        origen_id = _clean_int(data.get('origen_id'))
        monto = _clean_float(data.get('monto')) or 0.0
        mov_moneda = _clean_str(data.get('moneda')) or caja_moneda
        tipo_cambio = _clean_float(data.get('tipo_cambio')) or 1.0
        if tipo_cambio <= 0:
            tipo_cambio = 1.0
            
        # Calculate amount expressed in the caja's native currency
        if mov_moneda == caja_moneda:
            monto_caja = monto
        elif caja_moneda == 'ARS' and mov_moneda == 'USD':
            monto_caja = monto * (tipo_cambio if tipo_cambio > 1 else 1530.0)
        elif caja_moneda == 'USD' and mov_moneda == 'ARS':
            monto_caja = monto / (tipo_cambio if tipo_cambio > 1 else 1530.0)
        else:
            monto_caja = monto
            
        descripcion = _clean_str(data.get('descripcion'))
        modificado_por = _clean_str(data.get('modificado_por')) or 'usuario'
        
        cur = conn.execute("""
            INSERT INTO finanzas_movimientos_caja
            (oficina_id, caja_id, tipo_movimiento, origen, origen_id, monto, moneda, tipo_cambio, monto_caja, descripcion, modificado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (oficina_id, caja_id, tipo_movimiento, origen, origen_id, monto, mov_moneda, tipo_cambio, monto_caja, descripcion, modificado_por))
        mid = cur.lastrowid
        conn.commit()
        return mid
    finally:
        conn.close()

def delete_movimiento_caja(mov_id, oficina_id=None):
    """Deletes a cash register movement."""
    conn = _get_db()
    try:
        mid = _clean_int(mov_id)
        if not mid:
            return
        if oficina_id:
            conn.execute("DELETE FROM finanzas_movimientos_caja WHERE id = ? AND oficina_id = ?", (mid, _clean_int(oficina_id)))
        else:
            conn.execute("DELETE FROM finanzas_movimientos_caja WHERE id = ?", (mid,))
        conn.commit()
    finally:
        conn.close()

def get_movimientos_caja(oficina_id=None, caja_id=None, limit=100):
    """Gets recent cash movements for an office or account."""
    conn = _get_db()
    try:
        query = """
            SELECT m.*, c.nombre as caja_nombre
            FROM finanzas_movimientos_caja m
            JOIN finanzas_cajas_bancos c ON m.caja_id = c.id
            WHERE 1=1
        """
        params = []
        if oficina_id:
            query += " AND m.oficina_id = ?"
            params.append(_clean_int(oficina_id))
        if caja_id:
            query += " AND m.caja_id = ?"
            params.append(_clean_int(caja_id))
        query += " ORDER BY m.fecha_movimiento DESC, m.id DESC LIMIT ?"
        params.append(_clean_int(limit, 100))
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ==========================================
# 7. BALANCE GENERAL & P&L DE SUCURSAL
# ==========================================

def calcular_balance_oficina(oficina_id=None):
    """
    Computes complete P&L (Profit & Loss), Liquidity, and Agent Ledger totals for an office.
    Strict multi-tenant isolation.
    """
    conn = _get_db()
    try:
        oid = _clean_int(oficina_id)
        
        # 1. Fetch Operations
        ops = get_operaciones(oficina_id=oid)
        
        tot_bruto = sum(float(o['bruto'] or 0.0) for o in ops)
        tot_neto_agentes = sum(float(o['neto'] or 0.0) for o in ops)
        margen_oficina_bruto = tot_bruto - tot_neto_agentes
        
        com_rendidas = sum(float(o['neto'] or 0.0) for o in ops if o['comision_rendida'] == 1)
        com_pendientes = sum(float(o['neto'] or 0.0) for o in ops if o['comision_rendida'] == 0)
        
        # 2. Fetch Agent Debts (Desk fees, ads) strictly separated by currency
        deudas = get_deudas(oficina_id=oid)
        deudas_cobradas_usd = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'cancelada' and d.get('moneda', 'USD') == 'USD')
        deudas_cobradas_ars = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'cancelada' and d.get('moneda') == 'ARS')
        deudas_pendientes_usd = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'falta' and d.get('moneda', 'USD') == 'USD')
        deudas_pendientes_ars = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'falta' and d.get('moneda') == 'ARS')
        
        # 3. Fetch OPEX Expenses strictly separated by currency
        gastos = get_gastos_opex(oficina_id=oid)
        
        opex_pagado_usd = sum(float(g['monto'] or 0.0) for g in gastos if g['estado'] == 'pagado' and g['moneda'] == 'USD')
        opex_pagado_ars = sum(float(g['monto'] or 0.0) for g in gastos if g['estado'] == 'pagado' and g['moneda'] == 'ARS')
        
        opex_pendiente_usd = sum(float(g['monto'] or 0.0) for g in gastos if g['estado'] == 'pendiente' and g['moneda'] == 'USD')
        opex_pendiente_ars = sum(float(g['monto'] or 0.0) for g in gastos if g['estado'] == 'pendiente' and g['moneda'] == 'ARS')
        
        # Breakdown by category
        categorias_opex = {}
        for g in gastos:
            cat = g.get('categoria') or 'otros'
            if cat not in categorias_opex:
                categorias_opex[cat] = {'monto_usd': 0.0, 'monto_ars': 0.0, 'count': 0}
            if g['moneda'] == 'USD':
                categorias_opex[cat]['monto_usd'] += float(g['monto'] or 0.0)
            else:
                categorias_opex[cat]['monto_ars'] += float(g['monto'] or 0.0)
            categorias_opex[cat]['count'] += 1
            
        # 4. Fetch Cash Registers & Liquidity strictly separated
        cajas = get_cajas_bancos(oficina_id=oid)
        liquidez_usd = sum(c['saldo_actual'] for c in cajas if c['moneda'] == 'USD')
        liquidez_ars = sum(c['saldo_actual'] for c in cajas if c['moneda'] == 'ARS')
        
        # 5. Ingresos y Resultados Operativos Netos (100% Separados por Moneda)
        ingresos_totales_oficina_usd = margen_oficina_bruto + deudas_cobradas_usd
        ingresos_totales_oficina_ars = deudas_cobradas_ars
        
        resultado_neto_usd = ingresos_totales_oficina_usd - opex_pagado_usd
        resultado_neto_ars = ingresos_totales_oficina_ars - opex_pagado_ars
        
        return {
            'resumen': {
                'ventas_totales_brutas': tot_bruto,
                'comisiones_agentes': tot_neto_agentes,
                'comisiones_rendidas': com_rendidas,
                'comisiones_pendientes': com_pendientes,
                'margen_oficina_bruto': margen_oficina_bruto,
                'deudas_cobradas_usd': deudas_cobradas_usd,
                'deudas_cobradas_ars': deudas_cobradas_ars,
                'deudas_pendientes_usd': deudas_pendientes_usd,
                'deudas_pendientes_ars': deudas_pendientes_ars,
                'ingresos_totales_oficina_usd': ingresos_totales_oficina_usd,
                'ingresos_totales_oficina_ars': ingresos_totales_oficina_ars,
                'opex_pagado_usd': opex_pagado_usd,
                'opex_pagado_ars': opex_pagado_ars,
                'opex_pendiente_usd': opex_pendiente_usd,
                'opex_pendiente_ars': opex_pendiente_ars,
                'resultado_neto_usd': resultado_neto_usd,
                'resultado_neto_ars': resultado_neto_ars,
                'liquidez_usd': liquidez_usd,
                'liquidez_ars': liquidez_ars
            },
            'cajas': cajas,
            'categorias_opex': categorias_opex,
            'gastos_recientes': gastos[:15],
            'operaciones_recientes': ops[:15]
        }
    finally:
        conn.close()

