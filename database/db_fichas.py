"""
Database module for Enlaces a Fichas de Clientes (Marca Blanca)
Handles creation, retrieval, analytics tracking, and 60-day lifecycle management.
"""
import json
import sqlite3
from datetime import datetime, timedelta
from database.db import get_db, MASTER_DB_PATH

def check_and_add_fichas_table(db_path=None):
    """Ensures the enlaces_fichas_clientes table exists in SQLite/Postgres."""
    try:
        conn = get_db(db_path or MASTER_DB_PATH)
        create_sql = """
        CREATE TABLE IF NOT EXISTS enlaces_fichas_clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo_slug TEXT UNIQUE NOT NULL,
            agente_id INTEGER NOT NULL,
            portal_origen TEXT,
            url_origen TEXT,
            titulo TEXT NOT NULL,
            precio REAL,
            moneda TEXT DEFAULT 'USD',
            expensas REAL DEFAULT 0,
            tipo_operacion TEXT DEFAULT 'venta',
            tipo_propiedad TEXT DEFAULT 'Departamento',
            direccion_mostrada TEXT,
            barrio TEXT,
            ambientes INTEGER DEFAULT 0,
            dormitorios INTEGER DEFAULT 0,
            banos INTEGER DEFAULT 0,
            m2_total REAL DEFAULT 0,
            m2_cubiertos REAL DEFAULT 0,
            cocheras INTEGER DEFAULT 0,
            antiguedad TEXT,
            orientacion TEXT,
            disposicion TEXT,
            caracteristicas_json TEXT DEFAULT '{}',
            descripcion TEXT,
            fotos_json TEXT DEFAULT '[]',
            foto_portada TEXT,
            lat REAL,
            lng REAL,
            agente_nombre TEXT,
            agente_telefono TEXT,
            agente_email TEXT,
            agente_avatar TEXT,
            vistas_count INTEGER DEFAULT 0,
            primer_acceso TEXT,
            ultimo_acceso TEXT,
            logs_accesos_json TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            expires_at TEXT,
            activo INTEGER DEFAULT 1
        );
        """
        conn.execute(create_sql)
        conn.commit()
    except Exception as e:
        print(f"[db_fichas] Error initializing table: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def crear_enlace_ficha(datos, agente_id=None):
    """
    Creates a new shareable customer property ficha link.
    datos: dict containing scraped & sanitized details
    """
    check_and_add_fichas_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        # Generate 60 days expiration from now
        now_dt = datetime.now()
        expires_dt = now_dt + timedelta(days=60)
        expires_at_str = expires_dt.strftime('%Y-%m-%d %H:%M:%S')
        created_at_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')

        aid = agente_id or datos.get('agente_id') or 1

        fotos_json = datos.get('fotos_json')
        if isinstance(fotos_json, list):
            fotos_json = json.dumps(fotos_json)
        elif not fotos_json:
            fotos_json = json.dumps(datos.get('fotos', []))

        caract_json = datos.get('caracteristicas_json')
        if isinstance(caract_json, dict) or isinstance(caract_json, list):
            caract_json = json.dumps(caract_json)
        elif not caract_json:
            caract_json = json.dumps(datos.get('caracteristicas', {}))

        foto_portada = datos.get('foto_portada') or datos.get('foto_url')
        if not foto_portada and datos.get('fotos'):
            foto_portada = datos['fotos'][0]

        sql = """
        INSERT INTO enlaces_fichas_clientes (
            codigo_slug, agente_id, portal_origen, url_origen,
            titulo, precio, moneda, expensas, tipo_operacion, tipo_propiedad,
            direccion_mostrada, barrio, ambientes, dormitorios, banos,
            m2_total, m2_cubiertos, cocheras, antiguedad, orientacion, disposicion,
            caracteristicas_json, descripcion, fotos_json, foto_portada,
            lat, lng, agente_nombre, agente_telefono, agente_email, agente_avatar,
            vistas_count, logs_accesos_json, created_at, expires_at, activo
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            0, '[]', ?, ?, 1
        )
        """
        cursor = conn.execute(sql, (
            datos.get('codigo_slug'),
            aid,
            datos.get('portal_origen', 'portal'),
            datos.get('url_origen', ''),
            datos.get('titulo', 'Propiedad en Venta'),
            float(datos.get('precio') or 0),
            datos.get('moneda', 'USD'),
            float(datos.get('expensas') or 0),
            datos.get('tipo_operacion', 'venta'),
            datos.get('tipo_propiedad', 'Departamento'),
            datos.get('direccion_mostrada', ''),
            datos.get('barrio', ''),
            int(datos.get('ambientes') or 0),
            int(datos.get('dormitorios') or 0),
            int(datos.get('banos') or 0),
            float(datos.get('m2_total') or 0),
            float(datos.get('m2_cubiertos') or 0),
            int(datos.get('cocheras') or 0),
            str(datos.get('antiguedad') or ''),
            str(datos.get('orientacion') or ''),
            str(datos.get('disposicion') or ''),
            caract_json,
            datos.get('descripcion', ''),
            fotos_json,
            foto_portada,
            float(datos.get('lat')) if datos.get('lat') is not None and str(datos.get('lat')) != '' else None,
            float(datos.get('lng')) if datos.get('lng') is not None and str(datos.get('lng')) != '' else None,
            datos.get('agente_nombre', ''),
            datos.get('agente_telefono', ''),
            datos.get('agente_email', ''),
            datos.get('agente_avatar', ''),
            created_at_str,
            expires_at_str
        ))
        conn.commit()
        last_id = cursor.lastrowid if hasattr(cursor, 'lastrowid') else 1
        return last_id, datos.get('codigo_slug')
    finally:
        conn.close()


def get_enlace_ficha_by_slug(slug):
    """Fetches a single property ficha by its slug."""
    check_and_add_fichas_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        sql = "SELECT * FROM enlaces_fichas_clientes WHERE codigo_slug = ? LIMIT 1"
        cursor = conn.execute(sql, (slug,))
        row = cursor.fetchone()
        if not row:
            return None
        
        ficha = dict(row)
        
        # Sincronizar dinámicamente con el perfil del agente DUEÑO de esta ficha
        owner_id = ficha.get('agente_id')
        if owner_id:
            from database.db import get_config_for_user
            tel_actual = get_config_for_user('agente_telefono', owner_id)
            if tel_actual:
                ficha['agente_telefono'] = tel_actual

            nom_actual = get_config_for_user('agente_nombre', owner_id)
            if nom_actual:
                ficha['agente_nombre'] = nom_actual
                
            email_actual = get_config_for_user('agente_email', owner_id)
            if email_actual:
                ficha['agente_email'] = email_actual
        
        try:
            ficha['fotos'] = json.loads(ficha.get('fotos_json') or '[]')
        except Exception:
            ficha['fotos'] = []
            
        try:
            ficha['caracteristicas'] = json.loads(ficha.get('caracteristicas_json') or '{}')
        except Exception:
            ficha['caracteristicas'] = {}

        try:
            ficha['logs_accesos'] = json.loads(ficha.get('logs_accesos_json') or '[]')
        except Exception:
            ficha['logs_accesos'] = []

        ficha['esta_expirado'] = False
        if ficha.get('expires_at'):
            try:
                exp_dt = datetime.strptime(ficha['expires_at'][:19], '%Y-%m-%d %H:%M:%S')
                if datetime.now() > exp_dt:
                    ficha['esta_expirado'] = True
            except Exception:
                pass
                
        return ficha
    finally:
        conn.close()


def get_enlaces_por_agente(agente_id=None):
    """Lists all created property links for a specific agent (or all for admin)."""
    check_and_add_fichas_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        if agente_id:
            sql = "SELECT * FROM enlaces_fichas_clientes WHERE agente_id = ? AND eliminado_el IS NULL ORDER BY id DESC"
            cursor = conn.execute(sql, (agente_id,))
        else:
            sql = "SELECT * FROM enlaces_fichas_clientes WHERE eliminado_el IS NULL ORDER BY id DESC"
            cursor = conn.execute(sql)
            
        rows = cursor.fetchall()
        fichas = []
        now_dt = datetime.now()
        for r in rows:
            f = dict(r)
            try:
                f['fotos'] = json.loads(f.get('fotos_json') or '[]')
            except Exception:
                f['fotos'] = []
                
            f['dias_restantes'] = 0
            f['esta_expirado'] = False
            if f.get('expires_at'):
                try:
                    exp_dt = datetime.strptime(f['expires_at'][:19], '%Y-%m-%d %H:%M:%S')
                    diff = (exp_dt - now_dt).days
                    f['dias_restantes'] = max(0, diff)
                    if now_dt > exp_dt or not f.get('activo', 1):
                        f['esta_expirado'] = True
                except Exception:
                    pass
            fichas.append(f)
        return fichas
    finally:
        conn.close()


def registrar_vista_enlace(slug, ip=None, user_agent=None):
    """
    Registers a legitimate human view for a property link, ignoring bots.
    Returns True if view counted, False otherwise.
    """
    ua = (user_agent or '').lower()
    bot_keywords = [
        'whatsapp', 'telegrambot', 'facebookexternalhit', 'twitterbot',
        'googlebot', 'bingbot', 'slackbot', 'discordbot', 'linkedinbot',
        'applebot', 'petalbot', 'bytespider', 'yandex'
    ]
    if any(k in ua for k in bot_keywords):
        return False

    conn = get_db(MASTER_DB_PATH)
    try:
        sql = "SELECT id, vistas_count, primer_acceso, logs_accesos_json, expires_at, activo FROM enlaces_fichas_clientes WHERE codigo_slug = ? LIMIT 1"
        cursor = conn.execute(sql, (slug,))
        row = cursor.fetchone()
        if not row:
            return False

        row_dict = dict(row)
        if not row_dict.get('activo', 1):
            return False

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_count = int(row_dict.get('vistas_count') or 0) + 1
        primer_acceso = row_dict.get('primer_acceso') or now_str

        try:
            logs = json.loads(row_dict.get('logs_accesos_json') or '[]')
        except Exception:
            logs = []

        logs.insert(0, {
            'fecha': now_str,
            'ip': ip or '127.0.0.1',
            'user_agent': user_agent[:200] if user_agent else ''
        })
        logs = logs[:50]

        update_sql = """
        UPDATE enlaces_fichas_clientes
        SET vistas_count = ?,
            primer_acceso = ?,
            ultimo_acceso = ?,
            logs_accesos_json = ?
        WHERE id = ?
        """
        conn.execute(update_sql, (
            new_count,
            primer_acceso,
            now_str,
            json.dumps(logs),
            row_dict['id']
        ))
        conn.commit()
        return True
    finally:
        conn.close()


def cambiar_estado_enlace(enlace_id, activo, agente_id=None):
    """Activates or deactivates a link."""
    conn = get_db(MASTER_DB_PATH)
    try:
        if agente_id:
            sql = "UPDATE enlaces_fichas_clientes SET activo = ? WHERE id = ? AND agente_id = ?"
            conn.execute(sql, (1 if activo else 0, enlace_id, agente_id))
        else:
            sql = "UPDATE enlaces_fichas_clientes SET activo = ? WHERE id = ?"
            conn.execute(sql, (1 if activo else 0, enlace_id))
        conn.commit()
        return True
    finally:
        conn.close()


def eliminar_enlace_ficha(enlace_id, agente_id=None, deleted_by=None):
    """Soft-deletes a property link."""
    if not deleted_by:
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                deleted_by = current_user.nombre_display or current_user.usuario
        except Exception:
            deleted_by = "Sistema"
    from database.db_papelera import soft_delete_record
    return soft_delete_record('enlaces_fichas_clientes', enlace_id, deleted_by=deleted_by or "Sistema")


def purgar_enlaces_expirados_60_dias():
    """Deactivates / purges expired links past 60 days."""
    conn = get_db(MASTER_DB_PATH)
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        sql = "UPDATE enlaces_fichas_clientes SET activo = 0 WHERE expires_at < ? AND activo = 1"
        cursor = conn.execute(sql, (now_str,))
        conn.commit()
        return cursor.rowcount if hasattr(cursor, 'rowcount') else 0
    finally:
        conn.close()
