"""
Database module - Initializes and provides access to SQLite database.
Acts as a central bridge, re-exporting modularized query functions for backward compatibility.
"""
import sqlite3
import os

try:
    from lib.dependency_checker import ensure_dependencies_installed
    ensure_dependencies_installed(verbose=False)
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from flask import g
except ImportError:
    g = None

import json

import re

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(WORKSPACE_DIR, 'db_config.json')
default_db_dir = os.environ.get(
    'CRM_DATA_DIR', 
    r"C:\FerrariDB" if (os.name == 'nt' and os.path.exists(r"C:\FerrariDB")) 
    else r"C:\CRM_Data" if os.name == 'nt' 
    else os.path.join(WORKSPACE_DIR, 'database')
)

DB_DIR = default_db_dir

# --- PostgreSQL variables and wrapper classes ---
SQLITE_FALLBACK_ACTIVE = False
_pg_pool = None
_pg_config = {}

def load_db_config():
    global _pg_config, DB_DIR
    default_config = {
        "db_type": "sqlite",
        "sqlite_fallback_enabled": True,
        "postgres": {
            "local": os.environ.get("POSTGRES_LOCAL_URL", "postgresql://postgres:admin123@localhost:5432/crm_db"),
            "production": os.environ.get("POSTGRES_PROD_URL", "postgresql://postgres:CASPA%409977%40indor@173.249.38.187:5432/crm_db")
        },
        "active_env": os.environ.get("FLASK_ENV", "development")
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f_cfg:
                cfg = json.load(f_cfg)
                # Merge default keys if they are missing
                for k, v in default_config.items():
                    if k not in cfg:
                        cfg[k] = v
                    elif isinstance(v, dict) and isinstance(cfg[k], dict):
                        for sub_k, sub_v in v.items():
                            if sub_k not in cfg[k]:
                                cfg[k][sub_k] = sub_v
                # Override with environment variables if present
                if os.environ.get("POSTGRES_PROD_URL"):
                    cfg.setdefault("postgres", {})["production"] = os.environ.get("POSTGRES_PROD_URL")
                if os.environ.get("POSTGRES_LOCAL_URL"):
                    cfg.setdefault("postgres", {})["local"] = os.environ.get("POSTGRES_LOCAL_URL")
                _pg_config = cfg
                if cfg.get('db_dir'):
                    DB_DIR = cfg['db_dir']
                return cfg
        except Exception as e:
            print(f"Error reading db_config.json: {e}")
            
    # Default config if file does not exist
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f_cfg:
            json.dump(default_config, f_cfg, indent=4)
        _pg_config = default_config
    except Exception as e:
        print(f"Error creating default db_config.json: {e}")
    return default_config

cfg = load_db_config()

USERS_DB_DIR = os.path.join(DB_DIR, 'usuarios')
MASTER_DB_PATH = os.path.join(DB_DIR, 'captador.db')
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.sql')

# AUTOMATIC DATA MIGRATION FROM LOCAL FOLDER ON FIRST LAUNCH
local_db_dir = os.path.join(WORKSPACE_DIR, 'database')
if os.path.normpath(DB_DIR).lower() != os.path.normpath(local_db_dir).lower():
    local_master = os.path.join(local_db_dir, 'captador.db')
    if os.path.exists(local_master):
        import shutil
        should_copy = False
        if not os.path.exists(MASTER_DB_PATH):
            should_copy = True
        else:
            try:
                target_size = os.path.getsize(MASTER_DB_PATH)
                local_size = os.path.getsize(local_master)
                if target_size < 150000 and local_size > target_size:
                    should_copy = True
            except:
                pass
                
        if should_copy:
            try:
                os.makedirs(DB_DIR, exist_ok=True)
                shutil.copy2(local_master, MASTER_DB_PATH)
                print(f"AUTOMIGRATION: Migrated database to {MASTER_DB_PATH}")
                local_users = os.path.join(local_db_dir, 'usuarios')
                if os.path.exists(local_users):
                    os.makedirs(USERS_DB_DIR, exist_ok=True)
                    for f in os.listdir(local_users):
                        src_f = os.path.join(local_users, f)
                        if os.path.isfile(src_f):
                            shutil.copy2(src_f, os.path.join(USERS_DB_DIR, f))
                    print(f"AUTOMIGRATION: Migrated agents databases to {USERS_DB_DIR}")
            except Exception as e:
                print(f"Error migrating database files: {e}")


# ============================================================
# USER_SCOPED_KEYS: Config keys that are isolated per-user.
# Stored as key_<user_id> in DB; served without suffix to templates.
# IMPORTANT: Adding a key here means it will NEVER be shared between users.
# ============================================================
USER_SCOPED_KEYS = {
    # Instagram
    'ig_username', 'ig_password', 'ig_session_status', 'ig_checkpoint_type',
    # AI / Integrations
    'gemini_api_key', 'groq_api_key', 'groq_model', 'ia_provider_primario',
    # Email SMTP (personal agent account)
    'smtp_host', 'smtp_port', 'smtp_user', 'smtp_password',
    # Agent profile
    'agente_nombre', 'agente_telefono', 'agente_email', 'agente_inmobiliaria',
    # Publicador Automático de Placas (PAP) - User & Agent setup
    'pap_agent_name', 'pap_agent_phone', 'pap_agent_email', 'pap_agent_web', 'pap_matricula',
    'pap_logo_v1', 'pap_logo_v2', 'pap_logo_v3',
    # Tasador Express — Personal setup per agent
    'tasador_estado_activo',
    'tasador_exc_porcentaje', 'tasador_muy_bien_porcentaje',
    'tasador_bien_porcentaje', 'tasador_regular_porcentaje', 'tasador_mal_porcentaje',
    # Tasador ajuste por estado de conservación
    'tasador_ajuste_estrenar', 'tasador_ajuste_muybueno', 'tasador_ajuste_bueno',
    'tasador_ajuste_refaccionar', 'tasador_ajuste_malo',
    # Tasador country/barrios cerrados
    'tasador_country_laguna', 'tasador_country_perimetral',
    # Tasador base market deviation
    'tasador_ajuste_base',
    # Tasador strict neighborhood filtering
    'tasador_filtro_estricto_barrio',
    # 3D Modeling engine URL per user
    'modelado_3d_backend_url',
    # AI Prospecting ideas per user (24h cache)
    'ia_prospeccion_ideas',
    # Meta AI / ClaudIA personal configuration per user
    'meta_ai_config',
}

class PgRowWrapper:

    def __init__(self, tuple_row, description):
        import datetime
        cleaned_row = []
        for val in tuple_row:
            if isinstance(val, (datetime.datetime, datetime.date)):
                cleaned_row.append(val.isoformat().replace('T', ' '))
            else:
                cleaned_row.append(val)
        self._row = cleaned_row
        self._fields = [d.name for d in description]
        self._dict = dict(zip(self._fields, cleaned_row))


    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return self._dict[key]

    def keys(self):
        return self._fields

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def __repr__(self):
        return str(self._dict)

class PgCursorWrapper:
    def __init__(self, pg_cursor):
        self.cursor = pg_cursor

    def execute(self, query, params=None):
        # Prevent transaction aborts on duplicate columns in ALTER TABLE
        alter_match = re.match(r'^\s*ALTER\s+TABLE\s+(\w+)\s+ADD\s+(?:COLUMN\s+)?(\w+)', query, re.IGNORECASE)
        if alter_match:
            table_name = alter_match.group(1).lower()
            column_name = alter_match.group(2).lower()
            check_cursor = self.cursor.connection.cursor()
            try:
                check_cursor.execute("""
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = %s AND column_name = %s
                """, (table_name, column_name))
                exists = check_cursor.fetchone()
                if exists:
                    return self
            except Exception:
                pass
            finally:
                check_cursor.close()

        # 0. Per-user config key isolation (scoped keys stored as key_userId in DB)
        # Only applies to queries against the 'configuracion' table to avoid double-scoping.
        translated_query = query
        if 'configuracion' in query.lower():
            try:
                from flask import has_request_context
                from flask_login import current_user
                if has_request_context() and current_user and current_user.is_authenticated:
                    uid = current_user.id
                    for _sk in USER_SCOPED_KEYS:
                        translated_query = re.sub(rf"'{re.escape(_sk)}'", f"'{_sk}_{uid}'", translated_query)
                    
                    if params:
                        new_params = list(params)
                        for i, p in enumerate(new_params):
                            if p in USER_SCOPED_KEYS:
                                new_params[i] = f"{p}_{uid}"
                        params = tuple(new_params)
            except Exception:
                pass

        # 1. Translate STRFTIME('%m-%d', col) to SUBSTR(col, 6, 5)
        translated_query = re.sub(r"STRFTIME\('%m-%d',\s*([^)]+)\)", r"SUBSTR(\1, 6, 5)", translated_query, flags=re.IGNORECASE)

        # Translate SQLite AUTOINCREMENT to Postgres SERIAL
        translated_query = re.sub(r'INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', 'SERIAL PRIMARY KEY', translated_query, flags=re.IGNORECASE)

        # Translate STRFTIME('%Y-%m-%d', col) to SUBSTR(col, 1, 10)
        translated_query = re.sub(r"STRFTIME\('%Y-%m-%d',\s*([^)]+)\)", r"SUBSTR(\1, 1, 10)", translated_query, flags=re.IGNORECASE)
        
        # 2. Escape raw '%' to '%%' (so psycopg doesn't treat them as placeholders)
        translated_query = translated_query.replace('%', '%%')
        
        # 3. Replace '?' with '%s' (psycopg placeholder)
        translated_query = translated_query.replace('?', '%s')
        
        # INSERT OR IGNORE translation
        if 'INSERT OR IGNORE INTO' in translated_query.upper():
            translated_query = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', translated_query, flags=re.IGNORECASE)
            translated_query += " ON CONFLICT DO NOTHING"

            
        # INSERT OR REPLACE / REPLACE translation
        elif 'INSERT OR REPLACE INTO' in translated_query.upper() or 'REPLACE INTO' in translated_query.upper():
            translated_query = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO', 'INSERT INTO', translated_query, flags=re.IGNORECASE)
            translated_query = re.sub(r'REPLACE\s+INTO', 'INSERT INTO', translated_query, flags=re.IGNORECASE)
            if 'CONFIGURACION' in translated_query.upper():
                translated_query += " ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"
            elif 'PLANIFICADOR_MENSAJES' in translated_query.upper():
                translated_query += " ON CONFLICT (semana) DO UPDATE SET mensaje = EXCLUDED.mensaje, habilitado = EXCLUDED.habilitado"
            elif 'CONFIG_DEUDAS_AGENTES' in translated_query.upper():
                translated_query += " ON CONFLICT (agente_id) DO UPDATE SET monto_oficina = EXCLUDED.monto_oficina, moneda_oficina = EXCLUDED.moneda_oficina, otros_gastos_json = EXCLUDED.otros_gastos_json"
            elif 'TAREAS_DIARIAS_ESTADO' in translated_query.upper():
                translated_query += " ON CONFLICT (fecha, agente_id) DO UPDATE SET historias_ig_wa = EXCLUDED.historias_ig_wa, lanzar_lote_5_5 = EXCLUDED.lanzar_lote_5_5, automatizacion_diaria = EXCLUDED.automatizacion_diaria, mantenimiento_base = EXCLUDED.mantenimiento_base"
            elif 'ESTADISTICAS_IA' in translated_query.upper():
                translated_query += " ON CONFLICT (estrategia) DO UPDATE SET enviados = EXCLUDED.enviados, respuestas = EXCLUDED.respuestas"
            elif 'PLUGIN_ACTIVATION_ROLES' in translated_query.upper():
                translated_query += " ON CONFLICT (rol, plugin_id) DO UPDATE SET activo = EXCLUDED.activo"
            elif 'PRIVILEGIOS_ACCESO' in translated_query.upper():
                translated_query += " ON CONFLICT (tipo_entidad, entidad_id, tipo_objeto, objeto_id) DO UPDATE SET permitido = EXCLUDED.permitido"
            elif 'AGENTES_CONTACTOS_COPIA' in translated_query.upper():
                translated_query += " ON CONFLICT (agente_usuario, telefono) DO UPDATE SET nombre = EXCLUDED.nombre, email = EXCLUDED.email"
            elif 'LOTES_DETALLES_MANUALES' in translated_query.upper():
                translated_query += """ ON CONFLICT (clave_natural) DO UPDATE SET 
                    detalles_financiacion = EXCLUDED.detalles_financiacion,
                    valor_override = EXCLUDED.valor_override,
                    estado_override = EXCLUDED.estado_override,
                    tipologia_override = EXCLUDED.tipologia_override,
                    orientacion_override = EXCLUDED.orientacion_override,
                    metros_override = EXCLUDED.metros_override,
                    area_override = EXCLUDED.area_override,
                    usuario_override = EXCLUDED.usuario_override,
                    colega_override = EXCLUDED.colega_override,
                    cuotas_override = EXCLUDED.cuotas_override,
                    link_plano_override = EXCLUDED.link_plano_override,
                    link_plano2_override = EXCLUDED.link_plano2_override,
                    nombre_colega_override = EXCLUDED.nombre_colega_override,
                    observaciones_override = EXCLUDED.observaciones_override,
                    oficina_id = EXCLUDED.oficina_id"""

        # Date functions translation (flexible regex for with/without space, case-insensitive)
        translated_query = re.sub(r"datetime\s*\(\s*'now'\s*(?:,\s*'localtime'\s*)?\)", "CURRENT_TIMESTAMP", translated_query, flags=re.IGNORECASE)
        translated_query = re.sub(r"date\s*\(\s*'now'\s*(?:,\s*'localtime'\s*)?\)", "CURRENT_DATE", translated_query, flags=re.IGNORECASE)
        # Translate SQLite date(column_or_expr) to Postgres (column_or_expr)::date
        translated_query = re.sub(r"\bdate\(\s*([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?|\?|%s)\s*\)", r"(\1)::date", translated_query, flags=re.IGNORECASE)
        
        try:
            self.cursor.execute(translated_query, params)
        except Exception as e:
            err_str = str(e).lower()
            if 'closed' in err_str or 'null' in err_str or 'connection' in err_str or 'got no result' in err_str:
                try:
                    import psycopg
                    new_conn = psycopg.connect(get_pg_connection_string(), connect_timeout=5)
                    self.cursor = new_conn.cursor()
                    self.cursor.execute(translated_query, params)
                    return self
                except Exception as retry_err:
                    e = retry_err
            import sqlite3
            try:
                self.cursor.connection.rollback()
            except Exception:
                pass
            raise sqlite3.OperationalError(str(e)) from e
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        if row is None:
            return None
        return PgRowWrapper(row, self.cursor.description)

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows:
            return []
        desc = self.cursor.description
        return [PgRowWrapper(row, desc) for row in rows]

    @property
    def lastrowid(self):
        try:
            self.cursor.execute("SELECT lastval()")
            row = self.cursor.fetchone()
            return row[0] if row else None
        except:
            return None

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def close(self):
        self.cursor.close()

class PgConnectionWrapper:
    def __init__(self, pg_conn):
        self.conn = pg_conn
        self.is_standalone = False
        self._closed = False

    def cursor(self):
        if self._closed or not self.conn or getattr(self.conn, 'closed', False):
            try:
                import psycopg
                self.conn = psycopg.connect(get_pg_connection_string(), connect_timeout=5)
                self.is_standalone = True
                self._closed = False
            except Exception as e:
                print(f"[PgConnectionWrapper] Auto-reconnect failed: {e}")
        cursor = self.conn.cursor()
        return PgCursorWrapper(cursor)

    def execute(self, query, params=None):
        wrapped = self.cursor()
        wrapped.execute(query, params)
        return wrapped

    def commit(self):
        try:
            if not self._closed and self.conn and not getattr(self.conn, 'closed', False):
                self.conn.commit()
        except Exception as e:
            print(f"[PgConnectionWrapper] Commit warning: {e}")

    def rollback(self):
        try:
            if not self._closed and self.conn and not getattr(self.conn, 'closed', False):
                self.conn.rollback()
        except Exception:
            pass

    def executescript(self, sql_script):
        # On PostgreSQL, execute cannot run multiple CREATE statements separated by semicolons in one call reliably.
        # We split them and run them sequentially.
        statements = sql_script.split(';')
        for stmt in statements:
            cleaned = stmt.strip()
            if cleaned:
                self.execute(cleaned)
        return self

    @property
    def total_changes(self):
        # Compatibilidad con código que usaba sqlite3.Connection.total_changes.
        # En PostgreSQL no existe este concepto; siempre devolvemos 0 como fallback seguro.
        return 0

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if g and hasattr(g, 'pg_conn') and g.pg_conn is self:
                g.pg_conn = None
        except Exception:
            pass
        release_db_connection(self.conn)

def get_pg_connection_string():
    env = _pg_config.get("active_env", "development")
    pg_settings = _pg_config.get("postgres", {})
    return pg_settings.get(env) or pg_settings.get("local")

def auto_migrate_pg_schema():
    """Ensures all modern columns exist in PostgreSQL database."""
    global _pg_pool
    if not _pg_pool:
        return
    conn = None
    try:
        conn = _pg_pool.getconn(timeout=5.0)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS oficinas (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    direccion TEXT,
                    telefono TEXT,
                    logo_url TEXT,
                    color_primario TEXT DEFAULT '#0d6efd',
                    color_secundario TEXT DEFAULT '#1a1a2e',
                    es_portal_clientes INTEGER DEFAULT 0,
                    activa INTEGER DEFAULT 1,
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint c
                        JOIN pg_class t ON c.conrelid = t.oid
                        WHERE t.relname = 'oficinas' AND c.contype = 'p'
                    ) THEN
                        UPDATE oficinas SET id = 2 WHERE slug = 'potenzia-crm' AND id = 1 AND EXISTS (SELECT 1 FROM oficinas WHERE slug = 'ferrari-asociados' AND id = 1);
                        ALTER TABLE oficinas ADD PRIMARY KEY (id);
                    END IF;
                END $$;
            """)
            cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS oficina_id INTEGER REFERENCES oficinas(id) ON DELETE SET NULL;")
            cur.execute("INSERT INTO oficinas (nombre, slug, es_portal_clientes, activa) VALUES ('Potenzia CRM', 'potenzia-crm', 1, 1) ON CONFLICT (slug) DO NOTHING;")
            cur.execute("SELECT setval(pg_get_serial_sequence('oficinas', 'id'), (SELECT COALESCE(MAX(id), 1) FROM oficinas));")
            cur.execute("ALTER TABLE busquedas_clientes ADD COLUMN IF NOT EXISTS es_publica INTEGER DEFAULT 0;")
            cur.execute("ALTER TABLE busquedas_clientes ADD COLUMN IF NOT EXISTS modo_busqueda TEXT DEFAULT 'completa';")
            cur.execute("ALTER TABLE busquedas_clientes ADD COLUMN IF NOT EXISTS agente_id INTEGER;")
            cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS totp_secret TEXT;")
            cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS totp_enabled INTEGER DEFAULT 0;")
            
            # --- SOFT-DELETE COLUMNS (PAPELERA DE RECICLAJE) ---
            soft_delete_tables = ['contactos', 'propiedades', 'lotes', 'seguimiento_operaciones', 'busquedas_clientes', 'enlaces_fichas_clientes']
            for s_table in soft_delete_tables:
                cur.execute(f"ALTER TABLE {s_table} ADD COLUMN IF NOT EXISTS eliminado_el TIMESTAMP;")
                cur.execute(f"ALTER TABLE {s_table} ADD COLUMN IF NOT EXISTS eliminado_por TEXT;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    usuario_id INTEGER,
                    usuario_nombre TEXT,
                    oficina_id INTEGER,
                    accion TEXT NOT NULL,
                    detalle TEXT,
                    ip TEXT,
                    user_agent TEXT
                );
            """)
            conn.commit()
            print("[PostgreSQL] Auto-migration completed: verified columns, 2FA, audit, soft-delete and oficinas table.")
        from database.db_portales_temp import check_and_add_portales_temp_table
        check_and_add_portales_temp_table()
    except Exception as e:
        print(f"[PostgreSQL Auto-Migration] Warning: {e}")
    finally:
        if conn:
            try:
                _pg_pool.putconn(conn)
            except Exception:
                pass

def init_pg_pool():
    global _pg_pool
    if _pg_pool is not None:
        return True
    try:
        from psycopg_pool import ConnectionPool
        conn_str = get_pg_connection_string()
        if "connect_timeout" not in conn_str:
            if "?" in conn_str:
                conn_str += "&connect_timeout=5"
            else:
                conn_str += "?connect_timeout=5"
        _pg_pool = ConnectionPool(conninfo=conn_str, min_size=1, max_size=20, open=True, timeout=3.0)
        auto_migrate_pg_schema()
        return True
    except Exception as e:
        print(f"[PostgreSQL] Failed to initialize connection pool: {e}")
        return False

def get_db(db_path=None):
    """Get a database connection. Automatically handles PostgreSQL with direct connection fallback and SQLite emergency valve."""
    global SQLITE_FALLBACK_ACTIVE
    
    db_type = _pg_config.get("db_type", "sqlite")
    
    if db_type == "postgresql":
        try:
            if g and hasattr(g, 'pg_conn') and g.pg_conn:
                if not getattr(g.pg_conn, '_closed', False) and g.pg_conn.conn and not getattr(g.pg_conn.conn, 'closed', False):
                    return g.pg_conn
                else:
                    g.pg_conn = None
                
            if init_pg_pool():
                try:
                    conn = _pg_pool.getconn(timeout=5.0)
                except Exception:
                    # Reset broken pool and retry once
                    try:
                        _pg_pool.close()
                    except Exception:
                        pass
                    _pg_pool = None
                    init_pg_pool()
                    conn = _pg_pool.getconn(timeout=5.0)

                wrapped = PgConnectionWrapper(conn)
                wrapped.is_standalone = False
                if g:
                    g.pg_conn = wrapped
                SQLITE_FALLBACK_ACTIVE = False
                return wrapped
            else:
                raise Exception("Pool initialization failed")
        except Exception as e:
            # If PostgreSQL direct standalone connection works, use it
            try:
                import psycopg
                direct_conn = psycopg.connect(get_pg_connection_string(), connect_timeout=5)
                wrapped = PgConnectionWrapper(direct_conn)
                wrapped.is_standalone = True
                SQLITE_FALLBACK_ACTIVE = False
                return wrapped
            except Exception:
                pass

            if not SQLITE_FALLBACK_ACTIVE:
                print(f"[EMERGENCY FALLBACK] PostgreSQL is down or pool saturated. Using Master SQLite DB! Error: {e}")
                SQLITE_FALLBACK_ACTIVE = True

    if not db_path and g and hasattr(g, 'db_path') and g.db_path:
        db_path = g.db_path
        
    target_path = db_path if db_path else MASTER_DB_PATH
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    conn = sqlite3.connect(target_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def get_pg_metrics():
    """Returns dictionary with current active connections and max connections for PostgreSQL."""
    db_type = _pg_config.get("db_type", "sqlite")
    if db_type != "postgresql" or SQLITE_FALLBACK_ACTIVE:
        return {'active_connections': 0, 'max_connections': 100, 'is_sqlite': True}
    conn = None
    try:
        conn = get_db()
        row = conn.execute("""
            SELECT numbackends, max_conn 
            FROM pg_stat_database db 
            CROSS JOIN (SELECT setting::int AS max_conn FROM pg_settings WHERE name = 'max_connections') s 
            WHERE datname = current_database()
        """).fetchone()
        if row:
            row_dict = dict(row)
            return {
                'active_connections': row_dict.get('numbackends', 0),
                'max_connections': row_dict.get('max_conn', 100),
                'is_sqlite': False
            }
    except Exception as e:
        print(f"[get_pg_metrics] Error: {e}")
    finally:
        if conn:
            conn.close()
    return {'active_connections': 0, 'max_connections': 100, 'is_sqlite': False}

def release_db_connection(conn):
    global _pg_pool
    if not conn:
        return
    try:
        raw_conn = getattr(conn, 'conn', conn)
        is_standalone = getattr(conn, 'is_standalone', False) or getattr(raw_conn, 'is_standalone', False)
        
        if is_standalone or not _pg_pool:
            try:
                raw_conn.close()
            except Exception:
                pass
        else:
            try:
                _pg_pool.putconn(raw_conn)
            except Exception:
                try:
                    raw_conn.close()
                except Exception:
                    pass
    except Exception as e:
        print(f"Error releasing PG connection: {e}")

def get_user_db_path(user_db_file):
    """Resolves absolute path for a user's private database."""
    if not user_db_file: return MASTER_DB_PATH
    return os.path.join(USERS_DB_DIR, user_db_file)


def check_and_add_contact_columns(db_path):
    """Verifies and adds any missing columns in the 'contactos' table for the given database."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(contactos)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        
        if existing_cols:
            target_columns = {
                'categoria': "TEXT DEFAULT 'C'",
                'fecha_nacimiento': "TEXT",
                'aniversario_casa': "TEXT",
                'rol': "TEXT",
                'referente': "TEXT",
                'notes': "TEXT", # Standard notes is notas, let's keep it safe
                'notas': "TEXT",
                'telefono': "TEXT",
                'email': "TEXT",
                'busqueda_activa': "INTEGER DEFAULT 0",
                'filtros_busqueda_json': "TEXT",
                'estado_seguimiento': "TEXT DEFAULT 'activo'",
                'campos_personalizados_json': "TEXT",
                'mac': "INTEGER DEFAULT 0",
                'intencion_ia': "TEXT",
                'recordatorio_activo': "INTEGER DEFAULT 0",
                'recordatorio_dias': "INTEGER",
                'recordatorio_fecha': "TEXT"
            }
            mutated = False
            for col, col_def in target_columns.items():
                if col not in existing_cols:
                    cursor.execute(f"ALTER TABLE contactos ADD COLUMN {col} {col_def}")
                    mutated = True
            if mutated:
                conn.commit()
                print(f"[Migration] Added missing columns to {db_path}")
    except Exception as e:
        print(f"[Migration] Error auto-migrating database {db_path}: {e}")
    finally:
        conn.close()

def check_and_add_search_columns(db_path):
    """Verifies and adds any missing columns in the 'busquedas_clientes' table for the given database."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(busquedas_clientes)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        
        if existing_cols:
            if 'modo_busqueda' not in existing_cols:
                cursor.execute("ALTER TABLE busquedas_clientes ADD COLUMN modo_busqueda TEXT DEFAULT 'completa'")
                print(f"[Migration] Added 'modo_busqueda' column to busquedas_clientes in {db_path}")
            if 'es_publica' not in existing_cols:
                cursor.execute("ALTER TABLE busquedas_clientes ADD COLUMN es_publica INTEGER DEFAULT 0")
                print(f"[Migration] Added 'es_publica' column to busquedas_clientes in {db_path}")
            conn.commit()
    except Exception as e:
        print(f"[Migration] Error auto-migrating searches in {db_path}: {e}")
    finally:
        conn.close()

def check_and_add_property_columns(db_path):
    """Verifies and adds missing columns in 'propiedades' table for the given database."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(propiedades)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        
        if existing_cols:
            target_columns = {
                'antiguedad': "INTEGER",
                'cocheras': "INTEGER DEFAULT 0",
                'toilettes': "INTEGER DEFAULT 0",
                'orientacion': "TEXT",
                'disposicion': "TEXT",
                'estado_conservacion': "TEXT",
                'fotos_json': "TEXT"
            }
            mutated = False
            for col, col_def in target_columns.items():
                if col not in existing_cols:
                    cursor.execute(f"ALTER TABLE propiedades ADD COLUMN {col} {col_def}")
                    mutated = True
            if mutated:
                conn.commit()
                print(f"[Migration] Added missing columns to propiedades in {db_path}")
    except Exception as e:
        print(f"[Migration] Error auto-migrating properties in {db_path}: {e}")
    finally:
        conn.close()

def check_and_add_historias_columns(db_path):
    """Verifies and adds missing columns in 'historias_redes' table for the given database."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if table exists first (in user DBs it might not exist if they don't have the plugin)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historias_redes'")
        if not cursor.fetchone():
            conn.close()
            return
            
        cursor.execute("PRAGMA table_info(historias_redes)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        
        if existing_cols:
            target_columns = {
                'whatsapp': "INTEGER DEFAULT 1",
                'instagram': "INTEGER DEFAULT 0",
                'agente_id': "INTEGER"
            }
            mutated = False
            for col, col_def in target_columns.items():
                if col not in existing_cols:
                    cursor.execute(f"ALTER TABLE historias_redes ADD COLUMN {col} {col_def}")
                    mutated = True
            if mutated:
                conn.commit()
                print(f"[Migration] Added missing columns to historias_redes in {db_path}")
    except Exception as e:
        print(f"[Migration] Error auto-migrating stories in {db_path}: {e}")
    finally:
        conn.close()


def check_and_add_tareas_columns(db_path):
    """Verifies and adds missing columns in 'tareas_diarias_estado' table for SQLite fallback."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tareas_diarias_estado'")
        if not cursor.fetchone():
            conn.close()
            return
            
        cursor.execute("PRAGMA table_info(tareas_diarias_estado)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        
        if existing_cols and 'agente_id' not in existing_cols:
            cursor.execute("ALTER TABLE tareas_diarias_estado ADD COLUMN agente_id INTEGER")
            conn.commit()
            print(f"[Migration] Added missing column 'agente_id' to tareas_diarias_estado in {db_path}")
    except Exception as e:
        print(f"[Migration] Error auto-migrating tasks in {db_path}: {e}")
    finally:
        conn.close()


def check_and_add_oficinas_table(db_path):
    """Ensures the 'oficinas' table exists and 'oficina_id' is added to 'usuarios'."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        cursor = conn.cursor()

        # 1. Create table oficinas if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS oficinas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                direccion TEXT,
                telefono TEXT,
                logo_url TEXT,
                color_primario TEXT DEFAULT '#0d6efd',
                color_secundario TEXT DEFAULT '#1a1a2e',
                es_portal_clientes INTEGER DEFAULT 0,
                activa INTEGER DEFAULT 1,
                fecha_creacion TEXT DEFAULT (datetime('now', 'localtime'))
            );
        """)

        # 2. Insert default office if table is empty
        cursor.execute("SELECT COUNT(*) FROM oficinas")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT OR IGNORE INTO oficinas (id, nombre, slug, es_portal_clientes, activa)
                VALUES (1, 'Oficina Central Ferrari', 'oficina-central', 1, 1)
            """)

        # 3. Add oficina_id to usuarios if missing
        cursor.execute("PRAGMA table_info(usuarios)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if existing_cols and 'oficina_id' not in existing_cols:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN oficina_id INTEGER REFERENCES oficinas(id)")
            # Assign existing users (except GermanMazza if we want) to default office 1
            cursor.execute("UPDATE usuarios SET oficina_id = 1 WHERE oficina_id IS NULL AND usuario != 'GermanMazza'")
            print(f"[Migration] Added 'oficina_id' column to usuarios and assigned existing users in {db_path}")

        conn.commit()
    except Exception as e:
        print(f"[Migration] Error verifying oficinas in {db_path}: {e}")
    finally:
        conn.close()


def check_and_add_user_security_columns(db_path):
    """Verifies and adds 2FA and security columns to 'usuarios' table for SQLite."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(usuarios)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if existing_cols:
            if 'totp_secret' not in existing_cols:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN totp_secret TEXT")
                print(f"[Migration] Added 'totp_secret' column to usuarios in {db_path}")
            if 'totp_enabled' not in existing_cols:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN totp_enabled INTEGER DEFAULT 0")
                print(f"[Migration] Added 'totp_enabled' column to usuarios in {db_path}")
            conn.commit()
    except Exception as e:
        print(f"[Migration] Error auto-migrating user security columns in {db_path}: {e}")
    finally:
        conn.close()

def check_and_add_soft_delete_columns(db_path):
    """Verifies and adds 'eliminado_el' and 'eliminado_por' columns in all soft-deletable tables for SQLite."""
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        tables = ['contactos', 'propiedades', 'lotes', 'seguimiento_operaciones', 'busquedas_clientes', 'enlaces_fichas_clientes']
        for t in tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{t}'")
            if not cursor.fetchone():
                continue
            cursor.execute(f"PRAGMA table_info({t})")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if 'eliminado_el' not in existing_cols:
                cursor.execute(f"ALTER TABLE {t} ADD COLUMN eliminado_el TEXT")
                print(f"[Migration] Added 'eliminado_el' column to {t} in {db_path}")
            if 'eliminado_por' not in existing_cols:
                cursor.execute(f"ALTER TABLE {t} ADD COLUMN eliminado_por TEXT")
                print(f"[Migration] Added 'eliminado_por' column to {t} in {db_path}")
        conn.commit()
    except Exception as e:
        print(f"[Migration] Error auto-migrating soft-delete columns in {db_path}: {e}")
    finally:
        conn.close()


def init_db():
    """Initialize the Master database with schema."""
    os.makedirs(DB_DIR, exist_ok=True)
    os.makedirs(USERS_DB_DIR, exist_ok=True)
    import sqlite3
    conn = sqlite3.connect(MASTER_DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.close()
    print(f"DATABASE MASTER: Initialized at {MASTER_DB_PATH}")
    
    # Run auto-migrations for master database
    check_and_add_oficinas_table(MASTER_DB_PATH)
    check_and_add_user_security_columns(MASTER_DB_PATH)
    check_and_add_contact_columns(MASTER_DB_PATH)
    check_and_add_search_columns(MASTER_DB_PATH)
    check_and_add_property_columns(MASTER_DB_PATH)
    check_and_add_historias_columns(MASTER_DB_PATH)
    check_and_add_tareas_columns(MASTER_DB_PATH)
    check_and_add_fichas_table(MASTER_DB_PATH)
    check_and_add_soft_delete_columns(MASTER_DB_PATH)

    try:
        from database.db_audit import init_audit_table
        init_audit_table()
    except Exception as _e_audit_init:
        print(f"[DB Master] Nota inicializando db_audit: {_e_audit_init}")


    try:
        from database.db_auth import normalizar_privilegios_agente, normalizar_privilegios_broker
        normalizar_privilegios_agente()
        normalizar_privilegios_broker()
    except Exception as _e_priv:
        print(f"[DB Master] Nota normalizando privilegios: {_e_priv}")

    try:
        from database.db_growth_canvas import check_and_add_growth_canvas_table
        check_and_add_growth_canvas_table()
    except Exception as _e_gc:
        print(f"[DB Master] Error inicializando growth_canvas: {_e_gc}")

    
    # Run auto-migrations for all user databases
    if os.path.exists(USERS_DB_DIR):
        for f in os.listdir(USERS_DB_DIR):
            if f.endswith('.db'):
                db_path = os.path.join(USERS_DB_DIR, f)
                check_and_add_contact_columns(db_path)
                check_and_add_search_columns(db_path)
                check_and_add_property_columns(db_path)
                check_and_add_historias_columns(db_path)
                check_and_add_tareas_columns(db_path)
                check_and_add_soft_delete_columns(db_path)

def init_user_db(db_file):
    """Initialize a private user database if it doesn't exist."""
    path = get_user_db_path(db_file)
    if os.path.exists(path): 
        # Run auto-migrations to ensure existing user database is up to date
        check_and_add_contact_columns(path)
        check_and_add_search_columns(path)
        check_and_add_property_columns(path)
        check_and_add_historias_columns(path)
        check_and_add_tareas_columns(path)
        check_and_add_soft_delete_columns(path)
        return False
    
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.close()
    print(f"DATABASE USER: Initialized at {path}")
    
    # Run auto-migrations as a sanity check
    check_and_add_contact_columns(path)
    check_and_add_search_columns(path)
    check_and_add_property_columns(path)
    check_and_add_historias_columns(path)
    check_and_add_tareas_columns(path)
    check_and_add_soft_delete_columns(path)
    return True


def _get_current_uid():
    """Returns current authenticated user ID or None."""
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user and current_user.is_authenticated:
            return current_user.id
    except Exception:
        pass
    return None


def _scoped_key(clave):
    """Returns the DB key: 'key_uid' for scoped keys, or plain 'key'."""
    if clave in USER_SCOPED_KEYS:
        uid = _get_current_uid()
        if uid:
            return f"{clave}_{uid}"
    return clave


def get_config(clave, default=None):
    """Get a configuration value, automatically scoping per-user keys."""
    db_key = _scoped_key(clave)
    try:
        conn = get_db()
        row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (db_key,)).fetchone()
        val = row['valor'] if row else None
        return val if val is not None and str(val).strip() != '' else default
    except Exception as e:
        try:
            import sqlite3
            conn_lite = sqlite3.connect(MASTER_DB_PATH)
            conn_lite.row_factory = sqlite3.Row
            row = conn_lite.execute("SELECT valor FROM configuracion WHERE clave = ?", (db_key,)).fetchone()
            val = row['valor'] if row else None
            conn_lite.close()
            return val if val is not None and str(val).strip() != '' else default
        except:
            return default
    finally:
        try:
            conn.close()
        except:
            pass


def get_config_for_user(clave, user_id, default=None):
    """Get a configuration value explicitly scoped for a given user_id, without falling back to other users."""
    if not user_id:
        return default
    db_key = f"{clave}_{user_id}" if clave in USER_SCOPED_KEYS else clave
    try:
        conn = get_db()
        row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (db_key,)).fetchone()
        val = row['valor'] if row else None
        return val if val is not None and str(val).strip() != '' else default
    except Exception:
        try:
            import sqlite3
            conn_lite = sqlite3.connect(MASTER_DB_PATH)
            conn_lite.row_factory = sqlite3.Row
            row = conn_lite.execute("SELECT valor FROM configuracion WHERE clave = ?", (db_key,)).fetchone()
            val = row['valor'] if row else None
            conn_lite.close()
            return val if val is not None and str(val).strip() != '' else default
        except:
            return default
    finally:
        try:
            conn.close()
        except:
            pass


def set_config(clave, valor):
    """Set a configuration value, automatically scoping per-user keys."""
    db_key = _scoped_key(clave)
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (db_key, valor)
        )
        conn.commit()
    finally:
        conn.close()


def get_all_config():
    """Get all configuration values as a dict, presenting scoped keys without suffix.
    
    Rules:
    - Global keys (NOT in USER_SCOPED_KEYS): visible to all users.
    - Per-user scoped keys (IN USER_SCOPED_KEYS):
        * If a logged-in user: only return key_<uid> value (never another user's or global).
        * If no user context (background): return global value (no suffix) or admin fallback.
    - Keys like 'key_123' that belong to OTHER users are never exposed.
    """
    uid = _get_current_uid()
    try:
        conn = get_db()
        rows = conn.execute("SELECT clave, valor FROM configuracion").fetchall()
        raw = {row['clave']: row['valor'] for row in rows}
    except Exception:
        try:
            import sqlite3
            conn_lite = sqlite3.connect(MASTER_DB_PATH)
            conn_lite.row_factory = sqlite3.Row
            rows = conn_lite.execute("SELECT clave, valor FROM configuracion").fetchall()
            raw = {row['clave']: row['valor'] for row in rows}
            conn_lite.close()
        except:
            return {}
    finally:
        try:
            conn.close()
        except:
            pass

    # Build a fast lookup: which canonical scoped keys belong to this user
    user_scoped_values = {}  # canonical_key -> value for THIS user
    if uid:
        for sk in USER_SCOPED_KEYS:
            user_key = f"{sk}_{uid}"
            if user_key in raw:
                user_scoped_values[sk] = raw[user_key]

    # Build result dict
    result = {}
    for k, v in raw.items():
        # --- Case 1: key is 'something_<digits>' — check if it's a scoped key ---
        is_handled = False
        for sk in USER_SCOPED_KEYS:
            # Matches pattern 'sk_<any_integer>'
            if k.startswith(f"{sk}_") and k[len(sk)+1:].isdigit():
                # This is a scoped entry. Only include if it belongs to current user.
                if uid and k == f"{sk}_{uid}":
                    result[sk] = v  # This user's own value
                # Other users' scoped keys: silently skip
                is_handled = True
                break

        if not is_handled:
            # --- Case 2: bare key (no suffix) ---
            if k in USER_SCOPED_KEYS:
                if uid:
                    # Logged-in user: only include bare value if user has no scoped override
                    if k not in user_scoped_values:
                        result[k] = v
                else:
                    # No user context (background jobs): include as-is
                    result[k] = v
            else:
                # --- Case 3: truly global config key (not in USER_SCOPED_KEYS) ---
                result[k] = v

    # Fallback for background contexts (uid is None): if scoped keys are missing, populate from admin (id 4)
    if not uid:
        for sk in USER_SCOPED_KEYS:
            if (sk not in result or not result[sk]) and f"{sk}_4" in raw and raw[f"{sk}_4"]:
                result[sk] = raw[f"{sk}_4"]

    return result


def get_agency_settings():
    """Returns dynamic branding dictionary for the agency / white-label, respecting office-level branding."""
    nombre = "Potenzia CRM"
    slogan = "El CRM Inmobiliario que potencia tu negocio"
    logo_path = None
    favicon_path = get_config('company_favicon_path') or "/static/favicon.ico"
    color_primario = get_config('theme_primary_color') or "#0d6efd"
    color_secundario = get_config('theme_secondary_color') or "#1a1a2e"
    matricula = get_config('matricula_colegio') or get_config('agente_matricula') or ""
    telefono = get_config('telefono_inmobiliaria') or get_config('agente_telefono') or ""
    email = get_config('email_inmobiliaria') or get_config('agente_email') or ""
    direccion = get_config('direccion_inmobiliaria') or ""
    oficina_nombre = None
    oficina_id = None
    es_portal_clientes = 0
    tiene_logo_personalizado = False
    
    # Check if user has an associated office
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user and current_user.is_authenticated:
            oficina_id = getattr(current_user, 'oficina_id', None)
            if oficina_id:
                conn = get_db(MASTER_DB_PATH)
                try:
                    ofi = conn.execute("SELECT * FROM oficinas WHERE id = ?", (oficina_id,)).fetchone()
                    if ofi:
                        oficina_nombre = ofi['nombre']
                        if ofi['nombre']:
                            nombre = ofi['nombre']
                        es_portal_clientes = ofi['es_portal_clientes']
                        if ofi['logo_url'] and ofi['logo_url'].strip() and ofi['logo_url'].strip() not in ['/static/img/potenzia_logo.png', '/static/img/potenzia_logo_sm.png', '/static/img/logo.png']:
                            logo_path = ofi['logo_url'].strip()
                            tiene_logo_personalizado = True
                        if ofi['color_primario']:
                            color_primario = ofi['color_primario']
                        if ofi['color_secundario']:
                            color_secundario = ofi['color_secundario']
                        if ofi['telefono']:
                            telefono = ofi['telefono']
                        if ofi['direccion']:
                            direccion = ofi['direccion']
                finally:
                    conn.close()
    except Exception:
        pass
    
    # If no office-specific custom logo found, check global/user config
    if not logo_path:
        cfg_logo = get_config('company_logo_path')
        if cfg_logo and cfg_logo.strip() and cfg_logo.strip() not in ['/static/img/potenzia_logo.png', '/static/img/potenzia_logo_sm.png', '/static/img/logo.png']:
            logo_path = cfg_logo.strip()
            tiene_logo_personalizado = True

    # Fallback to system default Potenzia CRM if no custom logo is active
    if not logo_path:
        logo_path = '/static/img/potenzia_logo_transparent.png'

    cfg_nombre = get_config('nombre_inmobiliaria')
    if cfg_nombre and not oficina_nombre:
        nombre = cfg_nombre

    cfg_slogan = get_config('slogan_inmobiliaria')
    if cfg_slogan:
        slogan = cfg_slogan

    return {
        'nombre': nombre,
        'oficina_nombre': oficina_nombre,
        'oficina_id': oficina_id,
        'es_portal_clientes': es_portal_clientes,
        'slogan': slogan,
        'logo_url': logo_path,
        'logo_sm_url': '/static/img/potenzia_logo_sm_transparent.png',
        'tiene_logo_personalizado': tiene_logo_personalizado,
        'custom_logo_url': logo_path if tiene_logo_personalizado else None,
        'favicon_url': favicon_path,
        'color_primario': color_primario,
        'color_secundario': color_secundario,
        'matricula': matricula,
        'telefono': telefono,
        'email': email,
        'direccion': direccion
    }


def get_branding_for_agent(agente_id=None):
    """
    Returns branding dictionary for a given agent based on their assigned office:
    {
        'logo_url': str,
        'nombre': str,
        'color_primario': str,
        'color_secundario': str,
        'tiene_logo_personalizado': bool
    }
    Falls back to Potenzia CRM if the agent has no office, the office has no custom logo, or agente_id is None.
    """
    default_potenzia_logo = '/static/img/potenzia_logo_transparent.png'
    default_potenzia_name = 'Potenzia CRM'
    
    if agente_id:
        try:
            conn = get_db(MASTER_DB_PATH)
            row = conn.execute("""
                SELECT u.id, u.usuario, u.nombre_display, u.oficina_id,
                       o.nombre as oficina_nombre, o.logo_url as oficina_logo_url,
                       o.color_primario as oficina_color_primario,
                       o.color_secundario as oficina_color_secundario
                FROM usuarios u
                LEFT JOIN oficinas o ON u.oficina_id = o.id
                WHERE u.id = ?
            """, (agente_id,)).fetchone()
            
            if row:
                ofi_logo = (row['oficina_logo_url'] or '').strip()
                ofi_nombre = (row['oficina_nombre'] or '').strip()
                
                # Check if office has a custom logo (not a generic fallback or legacy placeholder)
                if ofi_logo and ofi_logo not in ['/static/img/potenzia_logo.png', '/static/img/potenzia_logo_sm.png', '/static/img/logo.png', '/static/img/potenzia_logo_transparent.png']:
                    return {
                        'logo_url': ofi_logo,
                        'nombre': ofi_nombre or default_potenzia_name,
                        'color_primario': row['oficina_color_primario'] or '#1A365D',
                        'color_secundario': row['oficina_color_secundario'] or '#2B6CB0',
                        'tiene_logo_personalizado': True
                    }
                elif ofi_nombre:
                    # Office has a name, but no custom logo -> logo is Potenzia CRM
                    return {
                        'logo_url': default_potenzia_logo,
                        'nombre': ofi_nombre,
                        'color_primario': row['oficina_color_primario'] or '#1A365D',
                        'color_secundario': row['oficina_color_secundario'] or '#2B6CB0',
                        'tiene_logo_personalizado': False
                    }
        except Exception as e:
            print(f"[db.get_branding_for_agent] Error fetching branding for agent {agente_id}: {e}")

    # Fallback to global agency settings or Potenzia CRM default
    agency_cfg = get_agency_settings()
    logo = agency_cfg.get('logo_url')
    if not logo or logo in ['/static/img/potenzia_logo.png', '/static/img/potenzia_logo_sm.png', '/static/img/logo.png']:
        logo = default_potenzia_logo
        
    return {
        'logo_url': logo,
        'nombre': agency_cfg.get('nombre') or default_potenzia_name,
        'color_primario': agency_cfg.get('color_primario') or '#1A365D',
        'color_secundario': agency_cfg.get('color_secundario') or '#2B6CB0',
        'tiene_logo_personalizado': agency_cfg.get('tiene_logo_personalizado', False)
    }

# --- RE-EXPORTING MODULARIZED SQL QUERY MODULES (BACKWARD COMPATIBILITY) ---

from database.db_auth import (
    get_usuario,
    get_usuario_by_id,
    get_all_usuarios,
    insert_usuario,
    update_usuario,
    delete_usuario,
    get_all_oficinas,
    get_oficina_by_id,
    get_oficina_portal_clientes,
    insert_oficina,
    update_oficina,
    delete_oficina,
    set_portal_clientes_oficina,
    asignar_archivo_a_usuario,
    get_archivos_usuario,
    get_archivo_by_id,
    marcar_archivo_leido,
    delete_archivo_asignado,
    check_user_privilege,
    set_privilege,
    get_all_privileges,
    is_plugin_active_for_role,
    set_plugin_active_for_role,
    get_all_plugin_activations,
    set_user_totp_secret,
    enable_user_2fa,
    disable_user_2fa,
    get_user_totp_info,
    normalizar_privilegios_agente,
    normalizar_privilegios_broker
)

from database.db_audit import (
    registrar_auditoria,
    get_audit_logs,
    purgar_auditoria
)

from database.db_crm import (
    add_to_blacklist,
    remove_from_blacklist,
    is_blacklisted,
    get_blacklist,
    get_custom_columns,
    add_custom_column,
    save_contacto,
    insert_contacto,
    get_recordatorios_pendientes,
    get_contactos,
    count_contactos_frios,
    get_contacto_by_phone,
    get_fidelizacion_hoy,
    update_contacto_campo,
    get_contacto,
    delete_contacto_soft,
    get_proximos_eventos
)

from database.db_papelera import (
    soft_delete_record,
    restore_record,
    purge_record,
    get_papelera_items,
    vaciar_papelera_scope
)

from database.db_tasador import (
    get_tasacion_zona,
    get_tasacion_geografica
)

from database.db_finanzas import (
    get_operaciones,
    save_operacion,
    delete_operacion,
    get_deudas,
    save_deuda,
    get_config_deuda_agente,
    save_config_deuda_agente
)

from database.db_scrapers import (
    insert_propiedad,
    get_propiedades,
    get_propiedad,
    update_propiedad_estado,
    delete_propiedad,
    delete_propiedades_bulk,
    delete_propiedades_by_busqueda,
    insert_comunicacion,
    get_comunicaciones,
    marcar_comunicacion_enviada,
    marcar_comunicacion_respondida,
    update_comunicacion_estado,
    delete_comunicacion,
    get_ready_for_step1,
    get_ready_for_next_step,
    get_estadisticas,
    incrementar_respuesta_ia,
    get_busquedas,
    insert_busqueda,
    toggle_busqueda,
    delete_busqueda,
    get_planificador,
    update_planificador_semana,
    get_tareas_diarias,
    update_tarea_diaria,
    purgar_inmobiliarias,
    insert_busqueda_cliente,
    get_busquedas_clientes,
    get_busquedas_publicas_oficina,
    get_busqueda_cliente,
    update_busqueda_cliente_cliente,
    update_busqueda_cliente_vistas,
    delete_busqueda_cliente,
    enqueue_correo_cliente,
    update_correo_cliente_estado
)

from database.db_fichas import (
    check_and_add_fichas_table,
    crear_enlace_ficha,
    get_enlace_ficha_by_slug,
    get_enlaces_por_agente,
    registrar_vista_enlace,
    cambiar_estado_enlace,
    eliminar_enlace_ficha,
    purgar_enlaces_expirados_60_dias
)

from database.db_portales_temp import (
    check_and_add_portales_temp_table,
    crear_portal_temporal,
    get_portal_temporal_by_slug,
    registrar_vista_portal_temporal,
    get_portales_temporales_por_agente,
    eliminar_portal_temporal,
    purgar_portales_temporales_expirados
)


def verificar_y_obtener_propiedades_zona(zona, tipo_propiedad=None, tipo_operacion='venta', min_precio=None, max_precio=None, min_m2=None, max_m2=None, ambientes=None, dormitorios=None, keyword=None, extras=None, fecha_desde=None):
    """
    Verifies if properties for a given zone/neighborhood have been captured TODAY in the local database.
    - Returns (matching_properties, is_fresh_today, is_new_zone)
    - is_fresh_today: True if today's capture exists (count > 0 today)
    - is_new_zone: True if this zone has 0 records historically in the local DB
    """
    if not zona:
        return [], False, True

    clean_zona = zona.lower().strip()
    conn = get_db()
    try:
        from datetime import datetime
        today_str = datetime.now().strftime('%Y-%m-%d')
        exact_barrio = clean_zona
        like_pattern = f"%{clean_zona}%"

        # 1. Check today's capture count for this exact neighborhood or matching address/title
        query_today = """
            SELECT COUNT(*) FROM propiedades 
            WHERE (LOWER(barrio) = ? OR (LOWER(barrio) LIKE ? AND LOWER(barrio) NOT LIKE ?) OR LOWER(direccion) LIKE ? OR LOWER(titulo) LIKE ?)
            AND tipo_operacion = ?
            AND DATE(fecha_captacion) = DATE(?)
        """
        # If searching 'flores', exclude 'floresta' from fuzzy barrio match
        exclude_pattern = f"%floresta%" if clean_zona == "flores" else "%XYZ_NO_MATCH%"
        today_count = conn.execute(query_today, (exact_barrio, like_pattern, exclude_pattern, like_pattern, like_pattern, tipo_operacion, today_str)).fetchone()[0]

        # 2. Check historical total count for this zone
        query_total = """
            SELECT COUNT(*) FROM propiedades 
            WHERE (LOWER(barrio) = ? OR (LOWER(barrio) LIKE ? AND LOWER(barrio) NOT LIKE ?) OR LOWER(direccion) LIKE ? OR LOWER(titulo) LIKE ?)
            AND tipo_operacion = ?
        """
        total_count = conn.execute(query_total, (exact_barrio, like_pattern, exclude_pattern, like_pattern, like_pattern, tipo_operacion)).fetchone()[0]

        is_new_zone = (total_count == 0)

        # Fetch matching properties from local DB (applying active lifecycle age filter or fecha_desde)
        from datetime import datetime, timedelta
        if fecha_desde:
            cutoff_date = str(fecha_desde).strip()[:19]
        else:
            max_age_days = 30 if tipo_operacion == 'alquiler' else 120
            cutoff_date = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d %H:%M:%S')
        sql = """
            SELECT * FROM propiedades 
            WHERE (LOWER(barrio) = ? OR (LOWER(barrio) LIKE ? AND LOWER(barrio) NOT LIKE ?) OR LOWER(direccion) LIKE ? OR LOWER(titulo) LIKE ?)
            AND tipo_operacion = ?
            AND fecha_captacion >= ?
        """
        params = [exact_barrio, like_pattern, exclude_pattern, like_pattern, like_pattern, tipo_operacion, cutoff_date]

        if tipo_propiedad:
            if isinstance(tipo_propiedad, list):
                or_clauses = ["LOWER(tipo_propiedad) LIKE ?" for _ in tipo_propiedad]
                sql += f" AND ({' OR '.join(or_clauses)})"
                params.extend([f"%{t.lower().strip('{').strip('}')}%" for t in tipo_propiedad])
            else:
                clean_t = tipo_propiedad.lower().strip('{').strip('}')
                sql += " AND LOWER(tipo_propiedad) LIKE ?"
                params.append(f"%{clean_t}%")

        if min_precio is not None:
            sql += " AND precio >= ?"
            params.append(min_precio)
        if max_precio is not None:
            sql += " AND precio <= ?"
            params.append(max_precio)

        if min_m2 is not None:
            sql += " AND (m2_total >= ? OR m2_cubiertos >= ?)"
            params.extend([min_m2, min_m2])
        if max_m2 is not None:
            sql += " AND (m2_total <= ? OR m2_cubiertos <= ?)"
            params.extend([max_m2, max_m2])

        if ambientes is not None:
            if isinstance(ambientes, list):
                valid_ambs = [a for a in ambientes if a is not None]
                if valid_ambs:
                    placeholders = ', '.join(['?'] * len(valid_ambs))
                    sql += f" AND ambientes IN ({placeholders})"
                    params.extend(valid_ambs)
            else:
                sql += " AND ambientes = ?"
                params.append(ambientes)

        if dormitorios is not None:
            sql += " AND dormitorios = ?"
            params.append(dormitorios)

        if keyword:
            kw_pattern = f"%{keyword.lower().strip()}%"
            sql += " AND (LOWER(titulo) LIKE ? OR LOWER(descripcion) LIKE ?)"
            params.extend([kw_pattern, kw_pattern])

        sql += """ ORDER BY 
            CASE 
                WHEN LOWER(portal) LIKE '%argenprop%' THEN 1
                WHEN LOWER(portal) LIKE '%mercadolibre%' OR LOWER(portal) LIKE '%ml%' THEN 2
                WHEN LOWER(portal) LIKE '%zonaprop%' THEN 3
                ELSE 4
            END ASC, fecha_captacion DESC, precio ASC"""
        rows = conn.execute(sql, params).fetchall()

        from lib.extras_matcher import coincide_extras

        results = []
        for r in rows:
            row_dict = dict(r)

            p_url = (row_dict.get('url') or '').lower()
            p_title = (row_dict.get('titulo') or '').lower()
            p_moneda = row_dict.get('moneda') or 'USD'
            p_precio = row_dict.get('precio') or 0

            # 1. Operation integrity check
            if tipo_operacion == 'venta':
                if any(k in p_url for k in ['-alquiler-', '/alquiler/', '_alquiler_']) or p_title.startswith(('alquiler ', 'alquilo ', 'alquila ', 'en alquiler ')):
                    continue
                if p_moneda == 'ARS' and p_precio < 10000000:
                    continue
            elif tipo_operacion == 'alquiler':
                if any(k in p_url for k in ['-venta-', '/venta/', '_venta_']) or p_title.startswith(('venta ', 'vendo ', 'vende ', 'en venta ')):
                    continue

            # 2. Property type integrity check
            if tipo_propiedad:
                t_list = tipo_propiedad if isinstance(tipo_propiedad, list) else [tipo_propiedad]
                t_clean = [t.lower().strip('{').strip('}') for t in t_list]
                if 'casa' in t_clean:
                    if any(sub in p_url for sub in ('departamento.mercadolibre', 'oficina.mercadolibre', 'local.mercadolibre', 'inmueble.mercadolibre')):
                        continue
                    if p_title.startswith(('departamento ', 'depto ', 'semipiso ', 'monoambiente ', 'oficina ', 'local ', 'cochera ')):
                        continue
                elif 'departamento' in t_clean:
                    if any(sub in p_url for sub in ('casa.mercadolibre', 'oficina.mercadolibre', 'terreno.mercadolibre', 'inmueble.mercadolibre')):
                        continue
                    if p_title.startswith(('casa ', 'chalet ', 'triplex ', 'terreno ', 'lote ', 'oficina ', 'local ')):
                        continue

            # Filter by extras (cochera, balcon, pileta, etc.) with smart positive/negative check
            if extras and not coincide_extras(row_dict, extras):
                continue

            fotos_list = []
            if row_dict.get('fotos_json'):
                try:
                    parsed = json.loads(row_dict['fotos_json'])
                    if isinstance(parsed, list):
                        fotos_list = [f for f in parsed if isinstance(f, str) and f.startswith('http') and not any(k in f.lower() for k in ['_a/', 'logo', 'agea', 'placeholder'])]
                except Exception:
                    pass
            
            if not fotos_list and row_dict.get('foto_url'):
                f_url = row_dict['foto_url']
                if not any(k in f_url.lower() for k in ['_a/', 'logo', 'agea', 'placeholder']):
                    fotos_list.append(f_url)

            raw_primary = row_dict.get('foto_url') or ''
            if raw_primary and not any(k in raw_primary.lower() for k in ['_a/', 'logo', 'agea', 'placeholder']):
                primary_photo = raw_primary
            else:
                primary_photo = fotos_list[0] if fotos_list else ''

            results.append({
                'id': row_dict.get('id'),
                'titulo': row_dict.get('titulo') or '',
                'foto': primary_photo,
                'fotos': fotos_list,
                'portal': row_dict.get('portal') or 'local',
                'precio': row_dict.get('precio') or 0,
                'moneda': row_dict.get('moneda') or 'USD',
                'direccion': row_dict.get('direccion') or row_dict.get('barrio') or zona,
                'barrio': row_dict.get('barrio') or zona,
                'ambientes': row_dict.get('ambientes') or 0,
                'dormitorios': row_dict.get('dormitorios'),
                'cocheras': row_dict.get('cocheras'),
                'm2': row_dict.get('m2_total') or row_dict.get('m2_cubiertos') or 0,
                'm2_total': row_dict.get('m2_total'),
                'm2_cubiertos': row_dict.get('m2_cubiertos'),
                'url': row_dict.get('url') or '',
                'lat': row_dict.get('lat') or 0,
                'lng': row_dict.get('lng') or 0,
                'descripcion': row_dict.get('descripcion') or '',
                'fecha_captacion': str(row_dict.get('fecha_captacion') or ''),
                'fecha_publicacion': row_dict.get('fecha_publicacion'),
                'dias_publicado': row_dict.get('dias_publicado'),
                'precio_anterior': row_dict.get('precio_anterior')
            })

        return results, (today_count > 0 or len(results) > 0), is_new_zone
    except Exception as e:
        print(f"[DB] Error verificando propiedades locales para '{zona}': {e}")
        return [], False, True
    finally:
        conn.close()

# Export helper functions from db_scrapers for central access
from database.db_scrapers import (
    asegurar_descripcion_propiedad,
    enriquecer_descripciones_existentes,
    get_pending_correos_clientes
)

# Run master and user database migrations automatically on startup/import
try:
    check_and_add_contact_columns(MASTER_DB_PATH)
    check_and_add_search_columns(MASTER_DB_PATH)
    check_and_add_property_columns(MASTER_DB_PATH)
    check_and_add_historias_columns(MASTER_DB_PATH)
    check_and_add_tareas_columns(MASTER_DB_PATH)
    
    # Run migrations for all existing agent databases
    if os.path.exists(USERS_DB_DIR):
        for f in os.listdir(USERS_DB_DIR):
            if f.endswith('.db'):
                u_db_path = os.path.join(USERS_DB_DIR, f)
                check_and_add_contact_columns(u_db_path)
                check_and_add_search_columns(u_db_path)
                check_and_add_property_columns(u_db_path)
                check_and_add_historias_columns(u_db_path)
                check_and_add_tareas_columns(u_db_path)

    # --- AUTOMATIC POSTGRESQL PRODUCTION MIGRATIONS ON STARTUP ---
    if _pg_config.get("db_type") == "postgresql":
        try:
            # We open a direct connection to PostgreSQL to run system tables alter/updates
            conn_str = get_pg_connection_string()
            if conn_str:
                import psycopg
                pg_conn = psycopg.connect(conn_str)
                pg_conn.autocommit = False
                cur = pg_conn.cursor()
                
                # Resolve GermanMazza user ID
                cur.execute("SELECT id FROM usuarios WHERE usuario = 'GermanMazza' LIMIT 1")
                row = cur.fetchone()
                german_id = row[0] if row else 4 # default to 4 which is his local id
                
                # 1. Update tareas_diarias_estado
                cur.execute("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'tareas_diarias_estado' AND column_name = 'agente_id'
                """)
                if not cur.fetchone():
                    print("[Auto-Migration] Adding 'agente_id' to 'tareas_diarias_estado' in Postgres...")
                    cur.execute("ALTER TABLE tareas_diarias_estado ADD COLUMN agente_id INTEGER")
                    cur.execute("UPDATE tareas_diarias_estado SET agente_id = %s", (german_id,))
                    
                    cur.execute("""
                        SELECT constraint_name FROM information_schema.table_constraints
                        WHERE table_name = 'tareas_diarias_estado' AND constraint_type = 'PRIMARY KEY'
                    """)
                    pk_row = cur.fetchone()
                    if pk_row:
                        cur.execute(f"ALTER TABLE tareas_diarias_estado DROP CONSTRAINT {pk_row[0]}")
                    
                    cur.execute("ALTER TABLE tareas_diarias_estado ADD PRIMARY KEY (fecha, agente_id)")
                    cur.execute("ALTER TABLE tareas_diarias_estado ALTER COLUMN agente_id SET NOT NULL")
                    cur.execute("ALTER TABLE tareas_diarias_estado ADD CONSTRAINT fk_tareas_agente FOREIGN KEY (agente_id) REFERENCES usuarios(id) ON DELETE CASCADE")
                    print("[Auto-Migration] Table 'tareas_diarias_estado' updated successfully.")
                
                # 2. Update cola_correos_clientes
                cur.execute("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'cola_correos_clientes' AND column_name = 'agente_id'
                """)
                if not cur.fetchone():
                    print("[Auto-Migration] Adding 'agente_id' to 'cola_correos_clientes' in Postgres...")
                    cur.execute("ALTER TABLE cola_correos_clientes ADD COLUMN agente_id INTEGER REFERENCES usuarios(id)")
                    print("[Auto-Migration] Table 'cola_correos_clientes' updated successfully.")

                # 3. Clean up legacy configuration keys (No Suffix)
                migrated_keys = 0
                for key in USER_SCOPED_KEYS:
                    scoped_key = f"{key}_{german_id}"
                    
                    cur.execute("SELECT valor FROM configuracion WHERE clave = %s", (key,))
                    global_row = cur.fetchone()
                    
                    cur.execute("SELECT valor FROM configuracion WHERE clave = %s", (scoped_key,))
                    scoped_row = cur.fetchone()
                    
                    if global_row and not scoped_row:
                        cur.execute(
                            "INSERT INTO configuracion (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
                            (scoped_key, global_row[0])
                        )
                        cur.execute("DELETE FROM configuracion WHERE clave = %s", (key,))
                        migrated_keys += 1
                    elif global_row and scoped_row:
                        cur.execute("DELETE FROM configuracion WHERE clave = %s", (key,))
                        migrated_keys += 1

                # Promote scoped tasador keys to global keys
                tasador_keys = [
                    'tasador_estado_activo', 'tasador_exc_porcentaje', 'tasador_muy_bien_porcentaje',
                    'tasador_bien_porcentaje', 'tasador_regular_porcentaje', 'tasador_mal_porcentaje',
                    'tasador_ajuste_estrenar', 'tasador_ajuste_muybueno', 'tasador_ajuste_bueno',
                    'tasador_ajuste_refaccionar', 'tasador_ajuste_malo', 'tasador_country_laguna',
                    'tasador_country_perimetral', 'tasador_ajuste_base'
                ]
                cur = pg_conn.cursor()
                for tk in tasador_keys:
                    cur.execute("SELECT valor FROM configuracion WHERE clave LIKE %s AND valor IS NOT NULL AND valor != '0' AND valor != '' LIMIT 1", (f"{tk}_%",))
                    row = cur.fetchone()
                    if row and row[0]:
                        cur.execute(
                            "INSERT INTO configuracion (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
                            (tk, row[0])
                        )
                pg_conn.commit()
                cur.close()
                if migrated_keys > 0:
                    print(f"[Auto-Migration] Migrated {migrated_keys} global config keys to GermanMazza user.")
        except Exception as pg_mig_err:
            print(f"[Auto-Migration] PostgreSQL production database check skipped/failed: {pg_mig_err}")

except Exception as migration_err:
    print(f"[Migration] Auto-migration on startup failed: {migration_err}")

# Re-export Growth Canvas helpers
from database.db_growth_canvas import (
    check_and_add_growth_canvas_table,
    get_growth_canvas_projects,
    get_growth_canvas_project,
    save_growth_canvas_project,
    create_growth_canvas_project,
    delete_growth_canvas_project
)

if __name__ == '__main__':
    init_db()

