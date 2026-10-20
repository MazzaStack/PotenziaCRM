"""
Módulo de Auditoría Liviana (Audit Trail) para CRM Inmobiliario.
Registra exclusivamente mutaciones críticas (seguridad, usuarios, permisos, borrados).
Diseñado para impacto cero en rendimiento y auto-purga configurable.
"""
import os
import json
from datetime import datetime, timedelta
from database.db import get_db, MASTER_DB_PATH

def init_audit_table():
    """Inicializa la tabla audit_log en la base de datos Master/PostgreSQL."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT DEFAULT (datetime('now', 'localtime')),
                usuario_id INTEGER,
                usuario_nombre TEXT,
                oficina_id INTEGER,
                accion TEXT NOT NULL,
                detalle TEXT,
                ip TEXT,
                user_agent TEXT
            )
        """)
        # Índice para búsquedas rápidas y purga eficiente por fecha
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_fecha ON audit_log(fecha)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_accion ON audit_log(accion)")
        conn.commit()
    except Exception as e:
        print(f"[Audit] Error inicializando tabla de auditoría: {e}")
    finally:
        conn.close()

def registrar_auditoria(accion, detalle="", usuario_id=None, usuario_nombre=None, oficina_id=None, ip=None, user_agent=None):
    """
    Registra una acción crítica de forma segura y no bloqueante.
    Si se ejecuta dentro de un contexto Flask, auto-detecta IP, User Agent y Usuario actual.
    """
    try:
        from flask import has_request_context, request
        from flask_login import current_user
        
        if has_request_context():
            if ip is None:
                # Soporte para proxies / Cloudflare
                ip = request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip and ',' in ip:
                    ip = ip.split(',')[0].strip()
            if user_agent is None:
                user_agent = request.headers.get('User-Agent', '')[:250]
                
            if current_user and getattr(current_user, 'is_authenticated', False):
                if usuario_id is None:
                    usuario_id = getattr(current_user, 'id', None)
                if usuario_nombre is None:
                    usuario_nombre = getattr(current_user, 'usuario', None)
                if oficina_id is None:
                    oficina_id = getattr(current_user, 'oficina_id', None)
    except Exception:
        pass
        
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("""
            INSERT INTO audit_log (fecha, usuario_id, usuario_nombre, oficina_id, accion, detalle, ip, user_agent)
            VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?)
        """, (usuario_id, usuario_nombre, oficina_id, accion, str(detalle)[:1000], ip, user_agent))
        conn.commit()
    except Exception as e:
        print(f"[Audit] Error al registrar evento ({accion}): {e}")
    finally:
        conn.close()

def get_audit_logs(limit=100, offset=0, accion=None, usuario=None):
    """Obtiene los últimos eventos de auditoría con filtros opcionales."""
    init_audit_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if accion:
            query += " AND accion = ?"
            params.append(accion)
        if usuario:
            query += " AND usuario_nombre = ?"
            params.append(usuario)
            
        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[Audit] Error consultando logs: {e}")
        return []
    finally:
        conn.close()

def purgar_auditoria(dias_retencion=90):
    """Elimina logs más antiguos que los días de retención especificados."""
    if not dias_retencion or dias_retencion < 7:
        dias_retencion = 90
    init_audit_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        limite = (datetime.now() - timedelta(days=int(dias_retencion))).strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("DELETE FROM audit_log WHERE fecha < ?", (limite,))
        conn.commit()
        print(f"[Audit] Purga completada: eliminados registros anteriores a {limite}")
    except Exception as e:
        print(f"[Audit] Error al purgar auditoría: {e}")
    finally:
        conn.close()
