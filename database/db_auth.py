"""
Database queries for users and authentication
"""
import sqlite3
def get_db(db_path=None):
    from database.db import get_db as _get_db, MASTER_DB_PATH as _MASTER_PATH
    return _get_db(db_path or _MASTER_PATH)

MASTER_DB_PATH = None

def get_usuario(usuario):
    """Get user by username with office info. Always uses Master DB."""
    conn = get_db(MASTER_DB_PATH) # Force Master
    try:
        row = conn.execute("""
            SELECT u.*, o.nombre as oficina_nombre, o.slug as oficina_slug, o.es_portal_clientes as oficina_es_portal
            FROM usuarios u
            LEFT JOIN oficinas o ON u.oficina_id = o.id
            WHERE u.usuario = ?
        """, (usuario,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_usuario_by_id(user_id):
    """Get user by ID with office info. Always uses Master DB."""
    conn = get_db(MASTER_DB_PATH) # Force Master
    try:
        row = conn.execute("""
            SELECT u.*, o.nombre as oficina_nombre, o.slug as oficina_slug, o.es_portal_clientes as oficina_es_portal
            FROM usuarios u
            LEFT JOIN oficinas o ON u.oficina_id = o.id
            WHERE u.id = ?
        """, (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_all_usuarios(oficina_id=None):
    """Get all users, optionally filtered by office. Always uses Master DB."""
    conn = get_db(MASTER_DB_PATH) # Force Master
    try:
        query = """
            SELECT u.*, o.nombre as oficina_nombre, o.slug as oficina_slug
            FROM usuarios u
            LEFT JOIN oficinas o ON u.oficina_id = o.id
        """
        params = []
        if oficina_id is not None:
            if oficina_id == 'sueltos' or oficina_id == 0:
                query += " WHERE u.oficina_id IS NULL"
            else:
                query += " WHERE u.oficina_id = ?"
                params.append(oficina_id)
        query += " ORDER BY u.id"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def insert_usuario(usuario, password_hash, nombre_display, rol='agente', db_file=None, oficina_id=None):
    """Insert a new user into Master DB."""
    conn = get_db(MASTER_DB_PATH)
    try:
        cursor = conn.execute(
            "INSERT INTO usuarios (usuario, password_hash, nombre_display, rol, db_file, oficina_id) VALUES (?, ?, ?, ?, ?, ?)",
            (usuario, password_hash, nombre_display, rol, db_file, oficina_id)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_usuario(user_id, nombre_display, rol, password_hash=None, oficina_id=None, update_oficina=False):
    """Update user details in Master DB."""
    conn = get_db(MASTER_DB_PATH)
    try:
        if update_oficina:
            if password_hash:
                conn.execute(
                    "UPDATE usuarios SET nombre_display = ?, rol = ?, password_hash = ?, oficina_id = ? WHERE id = ?",
                    (nombre_display, rol, password_hash, oficina_id, user_id)
                )
            else:
                conn.execute(
                    "UPDATE usuarios SET nombre_display = ?, rol = ?, oficina_id = ? WHERE id = ?",
                    (nombre_display, rol, oficina_id, user_id)
                )
        else:
            if password_hash:
                conn.execute(
                    "UPDATE usuarios SET nombre_display = ?, rol = ?, password_hash = ? WHERE id = ?",
                    (nombre_display, rol, password_hash, user_id)
                )
            else:
                conn.execute(
                    "UPDATE usuarios SET nombre_display = ?, rol = ? WHERE id = ?",
                    (nombre_display, rol, user_id)
                )
        conn.commit()
    finally:
        conn.close()

def delete_usuario(user_id):
    """Delete a user and their assignments from Master DB, returning username for folder cleanup."""
    conn = get_db(MASTER_DB_PATH)
    try:
        user = conn.execute("SELECT usuario FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        usuario = user['usuario'] if user else None
        
        # Delete assigned files records (their physical files will be handled in app layer or here)
        conn.execute("DELETE FROM archivos_asignados WHERE asignado_a = ?", (user_id,))
        conn.execute("DELETE FROM config_deudas_agentes WHERE agente_id = ?", (user_id,))
        conn.execute("DELETE FROM finanzas_deudas WHERE agente_id = ?", (user_id,))
        conn.execute("DELETE FROM seguimiento_operaciones WHERE agente_id = ?", (user_id,))
        conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        return usuario
    finally:
        conn.close()

# ==========================================
# OFICINAS CRUD (MULTI-TENANT)
# ==========================================

def get_all_oficinas():
    """Gets all offices from Master DB with member statistics."""
    conn = get_db(MASTER_DB_PATH)
    try:
        rows = conn.execute("""
            SELECT o.*, 
                   COALESCE(u_stats.total_usuarios, 0) as total_usuarios,
                   COALESCE(u_stats.total_agentes, 0) as total_agentes,
                   COALESCE(u_stats.total_brokers, 0) as total_brokers,
                   COALESCE(u_stats.total_admins, 0) as total_admins
            FROM oficinas o
            LEFT JOIN (
                SELECT oficina_id,
                       COUNT(id) as total_usuarios,
                       SUM(CASE WHEN rol = 'agente' THEN 1 ELSE 0 END) as total_agentes,
                       SUM(CASE WHEN rol = 'broker' THEN 1 ELSE 0 END) as total_brokers,
                       SUM(CASE WHEN rol = 'admin' THEN 1 ELSE 0 END) as total_admins
                FROM usuarios
                GROUP BY oficina_id
            ) u_stats ON u_stats.oficina_id = o.id
            ORDER BY o.id ASC
        """).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_oficina_by_id(oid):
    """Gets an office by ID."""
    conn = get_db(MASTER_DB_PATH)
    try:
        row = conn.execute("SELECT * FROM oficinas WHERE id = ?", (oid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_oficina_portal_clientes():
    """Gets the single office designated for the Client Portal."""
    conn = get_db(MASTER_DB_PATH)
    try:
        row = conn.execute("SELECT * FROM oficinas WHERE es_portal_clientes = 1 AND activa = 1 LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def insert_oficina(nombre, slug, direccion='', telefono='', logo_url='', color_primario='#0d6efd', color_secundario='#1a1a2e', es_portal_clientes=0, activa=1):
    """Inserts a new office."""
    conn = get_db(MASTER_DB_PATH)
    try:
        if es_portal_clientes:
            conn.execute("UPDATE oficinas SET es_portal_clientes = 0")
        cursor = conn.execute("""
            INSERT INTO oficinas (nombre, slug, direccion, telefono, logo_url, color_primario, color_secundario, es_portal_clientes, activa)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (nombre, slug, direccion, telefono, logo_url, color_primario, color_secundario, int(es_portal_clientes), int(activa)))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_oficina(oid, nombre, slug, direccion='', telefono='', logo_url='', color_primario='#0d6efd', color_secundario='#1a1a2e', es_portal_clientes=None, activa=1):
    """Updates an existing office."""
    conn = get_db(MASTER_DB_PATH)
    try:
        if es_portal_clientes is not None and int(es_portal_clientes) == 1:
            conn.execute("UPDATE oficinas SET es_portal_clientes = 0 WHERE id != ?", (oid,))
            es_portal_val = 1
        elif es_portal_clientes is not None:
            es_portal_val = int(es_portal_clientes)
        else:
            current = conn.execute("SELECT es_portal_clientes FROM oficinas WHERE id = ?", (oid,)).fetchone()
            es_portal_val = current['es_portal_clientes'] if current else 0
            
        conn.execute("""
            UPDATE oficinas 
            SET nombre = ?, slug = ?, direccion = ?, telefono = ?, logo_url = ?, color_primario = ?, color_secundario = ?, es_portal_clientes = ?, activa = ?
            WHERE id = ?
        """, (nombre, slug, direccion, telefono, logo_url, color_primario, color_secundario, es_portal_val, int(activa), oid))
        conn.commit()
    finally:
        conn.close()

def set_portal_clientes_oficina(oid):
    """Sets a specific office as the ONLY client portal office."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("UPDATE oficinas SET es_portal_clientes = CASE WHEN id = ? THEN 1 ELSE 0 END", (oid,))
        conn.commit()
    finally:
        conn.close()

def delete_oficina(oid):
    """Deletes an office, unlinking all members to Agentes Sueltos."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("UPDATE usuarios SET oficina_id = NULL WHERE oficina_id = ?", (oid,))
        conn.execute("DELETE FROM privilegios_acceso WHERE tipo_entidad = 'oficina' AND entidad_id = ?", (str(oid),))
        conn.execute("DELETE FROM oficinas WHERE id = ?", (oid,))
        conn.commit()
    finally:
        conn.close()

def asignar_archivo_a_usuario(nombre_archivo, ruta_archivo, asignado_a, asignado_por):
    """Inserts a file assignment record in Master DB."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("""
            INSERT INTO archivos_asignados (nombre_archivo, ruta_archivo, asignado_a, asignado_por)
            VALUES (?, ?, ?, ?)
        """, (nombre_archivo, ruta_archivo, asignado_a, asignado_por))
        conn.commit()
    finally:
        conn.close()

def get_archivos_usuario(user_id=None, oficina_id=None):
    """Gets files assigned to a user or within an office."""
    conn = get_db(MASTER_DB_PATH)
    try:
        query = """
            SELECT a.*, u_to.nombre_display as agente_nombre, u_from.nombre_display as asignado_por_nombre,
                   u_to.oficina_id as agente_oficina_id
            FROM archivos_asignados a
            JOIN usuarios u_to ON a.asignado_a = u_to.id
            JOIN usuarios u_from ON a.asignado_por = u_from.id
        """
        params = []
        where_clauses = []
        if user_id:
            where_clauses.append("a.asignado_a = ?")
            params.append(user_id)
        elif oficina_id:
            where_clauses.append("u_to.oficina_id = ?")
            params.append(oficina_id)
            
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += " ORDER BY a.fecha_asignado DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_archivo_by_id(aid):
    """Gets a specific assigned file record from Master DB."""
    conn = get_db(MASTER_DB_PATH)
    try:
        row = conn.execute("SELECT * FROM archivos_asignados WHERE id = ?", (aid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def marcar_archivo_leido(aid):
    """Marks an assigned file as read in Master DB."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("UPDATE archivos_asignados SET leido = 1 WHERE id = ?", (aid,))
        conn.commit()
    finally:
        conn.close()

def delete_archivo_asignado(aid):
    """Deletes an assignment record and RETURNS the physical path to be deleted."""
    conn = get_db(MASTER_DB_PATH)
    try:
        row = conn.execute("SELECT ruta_archivo FROM archivos_asignados WHERE id = ?", (aid,)).fetchone()
        path = row['ruta_archivo'] if row else None
        conn.execute("DELETE FROM archivos_asignados WHERE id = ?", (aid,))
        conn.commit()
        return path
    finally:
        conn.close()

def check_user_privilege(user, tipo_objeto, objeto_id):
    """
    Checks if a user has access to a plugin, menu item, or action.
    Hierarchy:
    1. SuperAdmin (GermanMazza) has access to EVERYTHING.
    2. Specific User Override in database (privilegios_acceso: tipo_entidad='usuario')
    3. Office Override in database (privilegios_acceso: tipo_entidad='oficina') or Solo Agent rule (tipo_entidad='agentes_sueltos')
    4. Role Rule in database (privilegios_acceso: tipo_entidad='rol')
    5. Fallback defaults.
    """
    if isinstance(user, dict):
        class _DictUserWrapper:
            def __init__(self, d):
                self.id = d.get('id')
                self.usuario = d.get('usuario')
                self.rol = d.get('rol')
                self.oficina_id = d.get('oficina_id')
                self.is_authenticated = True
        user = _DictUserWrapper(user)
    elif not user or not hasattr(user, 'is_authenticated') or not user.is_authenticated:
        return False
        
    if getattr(user, 'usuario', None) == 'GermanMazza':
        return True

    # 1. Critical Superadmin only structural actions (cannot be delegated to roles)
    SUPERADMIN_ONLY_ACTIONS = {
        'ver_config_whatsapp_portal', # WhatsApp del Portal de Clientes
        'admin_oficinas',             # Gestión de Oficinas
        'admin_database',             # Base de Datos
        'admin_backups',              # Backups
        'admin_plugin_control',       # Control de Plugins
        'scraping_studio',            # Scraping Studio
        'busquedas',                  # Robots de Búsqueda
        'busquedas_scrapers',         # Robots de Búsqueda
        'planificador',               # Planificador 10 semanas
        'ejecutar_scraper',           # Ejecución de robots
        'limpiar_busqueda',           # Limpieza de búsquedas de robots
    }
    if objeto_id in SUPERADMIN_ONLY_ACTIONS:
        return False

    conn = get_db(MASTER_DB_PATH)
    try:
        # A. Check user override
        row = conn.execute(
            "SELECT permitido FROM privilegios_acceso WHERE tipo_entidad = 'usuario' AND entidad_id = ? AND tipo_objeto = ? AND objeto_id = ?",
            (user.usuario, tipo_objeto, objeto_id)
        ).fetchone()
        if row is not None:
            return bool(row['permitido'])

        # B. Check office rule (if user belongs to an office)
        if getattr(user, 'oficina_id', None):
            row = conn.execute(
                "SELECT permitido FROM privilegios_acceso WHERE tipo_entidad = 'oficina' AND entidad_id = ? AND tipo_objeto = ? AND objeto_id = ?",
                (str(user.oficina_id), tipo_objeto, objeto_id)
            ).fetchone()
            if row is not None:
                return bool(row['permitido'])
        else:
            # C. Check solo agent general rule
            row = conn.execute(
                "SELECT permitido FROM privilegios_acceso WHERE tipo_entidad = 'agentes_sueltos' AND entidad_id = 'sueltos' AND tipo_objeto = ? AND objeto_id = ?",
                (tipo_objeto, objeto_id)
            ).fetchone()
            if row is not None:
                return bool(row['permitido'])

        # D. Check role rule (solo agents cannot inherit office-only features like archivos_asignados from global role rule)
        is_solo_agent = not getattr(user, 'oficina_id', None) and user.usuario != 'GermanMazza'
        if is_solo_agent and objeto_id in {'finanzas_oficina', 'libro_finanzas', 'analitica', 'archivos_asignados', 'asignar_archivo', 'subir_archivo_personal'}:
            return False

        row = conn.execute(
            "SELECT permitido FROM privilegios_acceso WHERE tipo_entidad = 'rol' AND entidad_id = ? AND tipo_objeto = ? AND objeto_id = ?",
            (user.rol, tipo_objeto, objeto_id)
        ).fetchone()
        if row is not None:
            return bool(row['permitido'])
    except Exception as e:
        print(f"Error checking user privilege: {e}")
    finally:
        conn.close()

    # 2. Hard blocks for Solo Agents when no explicit override exists in DB
    is_solo_agent = not getattr(user, 'oficina_id', None) and user.usuario != 'GermanMazza'
    if is_solo_agent and objeto_id in {'finanzas_oficina', 'libro_finanzas', 'analitica', 'archivos_asignados', 'asignar_archivo', 'subir_archivo_personal'}:
        return False
        
    # E. Default behavior if no DB rule is set
    if user.rol in ('admin', 'broker'):
        return True
        
    # For regular agents (non-admin/non-broker), default allowed lists
    allowed_menu_items = {
        'dashboard', 'crm_contactos', 'tasador', 'seguimiento_prop', 
        'meta_ai',
        'lotes_excel', 'pap', 'buscador_ventas', 'buscador_alquileres',
        'configuracion', 'busquedas_clientes', 'historias', 'panel_fichas',
        'portales_temporales', 'tokko_mis_operaciones'
    }
    if not is_solo_agent:
        allowed_menu_items.add('archivos_asignados')

    allowed_plugins = {
        'lotes_excel', 'publicacion_placa', 'tokko', 'redes_sociales', 
        'captacion_outreach', 'asistente_ia'
    }

    allowed_actions = {
        'actualizar_estado', 'guardar_operacion', 'toggle_estado_deuda', 
        'test_email', 'preparar_mensaje',
        'ver_config_perfil', 'ver_config_smtp', 'ver_config_ia', 
        'ver_config_tasador', 'ver_config_instagram',
    }
    
    if tipo_objeto == 'menu_item':
        return objeto_id in allowed_menu_items
    elif tipo_objeto == 'plugin':
        return objeto_id in allowed_plugins
    elif tipo_objeto == 'accion':
        return objeto_id in allowed_actions
        
    return False

def set_privilege(tipo_entidad, entidad_id, tipo_objeto, objeto_id, permitido):
    """Inserts or replaces a privilege rule in Master DB."""
    # Safety rule: Superadmin GermanMazza cannot be restricted
    if tipo_entidad == 'usuario' and entidad_id == 'GermanMazza':
        return False
        
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO privilegios_acceso (tipo_entidad, entidad_id, tipo_objeto, objeto_id, permitido)
            VALUES (?, ?, ?, ?, ?)
        """, (tipo_entidad, str(entidad_id), tipo_objeto, objeto_id, int(permitido)))
        conn.commit()
        return True
    finally:
        conn.close()

def get_all_privileges():
    """Gets all privilege rules from Master DB."""
    conn = get_db(MASTER_DB_PATH)
    try:
        rows = conn.execute("SELECT * FROM privilegios_acceso").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def init_plugin_activation_table():
    """Initializes the plugin activation table and populates defaults if empty."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plugin_activation_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rol TEXT NOT NULL,
                plugin_id TEXT NOT NULL,
                activo INTEGER DEFAULT 1,
                UNIQUE(rol, plugin_id)
            )
        """)
        # Populate default active = 1 for standard roles and plugins
        roles = ['admin', 'broker', 'agente', 'finanzas']
        plugins = ['finanzas', 'meta_ai', 'redes_sociales', 'scraping_engine', 'captacion_outreach']
        
        # Check if table is empty
        row = conn.execute("SELECT COUNT(*) as count FROM plugin_activation_roles").fetchone()
        if row['count'] == 0:
            for r in roles:
                for p in plugins:
                    conn.execute("""
                        INSERT OR IGNORE INTO plugin_activation_roles (rol, plugin_id, activo)
                        VALUES (?, ?, 1)
                    """, (r, p))
            conn.commit()
    except Exception as e:
        print(f"Error initializing plugin_activation_roles: {e}")
    finally:
        conn.close()

def is_plugin_active_for_role(rol, plugin_id):
    """Checks if a plugin is active for a specific role at the superior level."""
    init_plugin_activation_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        row = conn.execute(
            "SELECT activo FROM plugin_activation_roles WHERE rol = ? AND plugin_id = ?",
            (rol, plugin_id)
        ).fetchone()
        if row is not None:
            return bool(row['activo'])
        return True
    except Exception as e:
        print(f"Error checking plugin activation for role: {e}")
        return True
    finally:
        conn.close()

def set_plugin_active_for_role(rol, plugin_id, activo):
    """Sets a plugin's activation status for a role."""
    init_plugin_activation_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO plugin_activation_roles (rol, plugin_id, activo)
            VALUES (?, ?, ?)
        """, (rol, plugin_id, int(activo)))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error setting plugin activation: {e}")
        return False
    finally:
        conn.close()

def get_all_plugin_activations():
    """Gets all plugin activations."""
    init_plugin_activation_table()
    conn = get_db(MASTER_DB_PATH)
    try:
        rows = conn.execute("SELECT * FROM plugin_activation_roles").fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error getting all plugin activations: {e}")
        return []
    finally:
        conn.close()

def normalizar_privilegios_agente():
    """
    Normaliza la matriz de acceso de base de datos para asegurar que los agentes regulares 
    tengan habilitados por defecto todos los privilegios requeridos de fábrica.
    """
    # Permisos a habilitar (permitido = 1)
    permitir = [
        # Plugins
        ('plugin', 'captacion_outreach'),
        ('plugin', 'publicacion_placa'),
        ('plugin', 'redes_sociales'),
        ('plugin', 'meta_ai'),
        ('plugin', 'tokko'),
        ('plugin', 'lotes_excel'),
        ('plugin', 'asistente_ia'),
        
        # Menu Items
        ('menu_item', 'dashboard'),
        ('menu_item', 'crm_contactos'),
        ('menu_item', 'tasador'),
        ('menu_item', 'seguimiento_prop'),
        ('menu_item', 'archivos_asignados'),
        ('menu_item', 'buscador_ventas'),
        ('menu_item', 'buscador_alquileres'),
        ('menu_item', 'busquedas_clientes'),
        ('menu_item', 'portales_temporales'),
        ('menu_item', 'panel_fichas'),
        ('menu_item', 'pap'),
        ('menu_item', 'historias'),
        ('menu_item', 'tokko_mis_operaciones'),
        ('menu_item', 'lotes_excel'),
        ('menu_item', 'configuracion'),
        
        # Acciones de Configuración
        ('accion', 'actualizar_estado'),
        ('accion', 'guardar_operacion'),
        ('accion', 'ver_config_perfil'),
        ('accion', 'ver_config_smtp'),
        ('accion', 'ver_config_ia'),
        ('accion', 'ver_config_tasador'),
        ('accion', 'ver_config_instagram'),
    ]

    # Permisos a denegar explícitamente (permitido = 0)
    denegar = [
        ('menu_item', 'busquedas_scrapers'),
        ('menu_item', 'busquedas'), # legacy key
        ('menu_item', 'gestion_usuarios'),
        ('menu_item', 'planificador'),
        ('menu_item', 'libro_finanzas'),
        ('menu_item', 'finanzas_oficina'),
        ('menu_item', 'analitica'),
        ('accion', 'scraping_studio'),
    ]
    
    conn = get_db(MASTER_DB_PATH)
    try:
        # Forzar permitidos si no están configurados o en inicialización
        for tipo, obj_id in permitir:
            conn.execute("""
                INSERT INTO privilegios_acceso (tipo_entidad, entidad_id, tipo_objeto, objeto_id, permitido)
                VALUES ('rol', 'agente', ?, ?, 1)
                ON CONFLICT(tipo_entidad, entidad_id, tipo_objeto, objeto_id) DO UPDATE SET permitido = 1
                WHERE privilegios_acceso.permitido IS NULL
            """, (tipo, obj_id))

        # Denegar explícitamente para rol agente
        for tipo, obj_id in denegar:
            conn.execute("""
                INSERT INTO privilegios_acceso (tipo_entidad, entidad_id, tipo_objeto, objeto_id, permitido)
                VALUES ('rol', 'agente', ?, ?, 0)
                ON CONFLICT(tipo_entidad, entidad_id, tipo_objeto, objeto_id) DO UPDATE SET permitido = 0
            """, (tipo, obj_id))
            
        # Restricciones por defecto para agentes sueltos (evitar uso de filemanager/archivos_asignados sin oficina)
        restricciones_sueltos = [
            ('menu_item', 'archivos_asignados', 0),
            ('accion', 'asignar_archivo', 0),
            ('menu_item', 'finanzas_oficina', 0),
            ('menu_item', 'libro_finanzas', 0),
        ]
        for tipo, obj_id, perm in restricciones_sueltos:
            conn.execute("""
                INSERT INTO privilegios_acceso (tipo_entidad, entidad_id, tipo_objeto, objeto_id, permitido)
                VALUES ('agentes_sueltos', 'sueltos', ?, ?, ?)
                ON CONFLICT(tipo_entidad, entidad_id, tipo_objeto, objeto_id) DO UPDATE SET permitido = EXCLUDED.permitido
                WHERE privilegios_acceso.permitido IS NULL
            """, (tipo, obj_id, perm))
            
        conn.commit()
        print("[System] Matriz de Privilegios para agentes normalizada con éxito.")
    except Exception as e:
        print(f"[System] Error al normalizar privilegios de agente: {e}")
    finally:
        conn.close()

def normalizar_privilegios_broker():
    """
    Normaliza la matriz de acceso de base de datos para asegurar que los brokers
    tengan habilitados por defecto todos los privilegios requeridos de fábrica,
    incluyendo Configuración, PAP, PAF, Portales Temporales y herramientas de oficina.
    """
    permitir = [
        # Plugins
        ('plugin', 'captacion_outreach'),
        ('plugin', 'publicacion_placa'),
        ('plugin', 'finanzas'),
        ('plugin', 'redes_sociales'),
        ('plugin', 'meta_ai'),
        ('plugin', 'tokko'),
        ('plugin', 'lotes_excel'),
        ('plugin', 'asistente_ia'),
        ('plugin', 'scraping_engine'),
        
        # Menu Items
        ('menu_item', 'dashboard'),
        ('menu_item', 'propiedades'),
        ('menu_item', 'comunicaciones'),
        ('menu_item', 'crm_contactos'),
        ('menu_item', 'tasador'),
        ('menu_item', 'seguimiento_prop'),
        ('menu_item', 'archivos_asignados'),
        ('menu_item', 'finanzas_oficina'),
        ('menu_item', 'libro_finanzas'),
        ('menu_item', 'buscador_ventas'),
        ('menu_item', 'buscador_alquileres'),
        ('menu_item', 'busquedas_clientes'),
        ('menu_item', 'portales_temporales'),
        ('menu_item', 'panel_fichas'),
        ('menu_item', 'pap'),
        ('menu_item', 'historias'),
        ('menu_item', 'tokko_cartera'),
        ('menu_item', 'tokko_mis_operaciones'),
        ('menu_item', 'lotes_excel'),
        ('menu_item', 'configuracion'),
        
        # Acciones
        ('accion', 'asignar_archivo'),
        ('accion', 'conectar_whatsapp'),
        ('accion', 'publicar_historias_manualmente'),
        ('accion', 'limpiar_inactivas'),
        ('accion', 'borrar_propiedad'),
        ('accion', 'actualizar_estado'),
        ('accion', 'guardar_operacion'),
        ('accion', 'borrar_operacion'),
        ('accion', 'toggle_estado_deuda'),
        ('accion', 'ver_config_perfil'),
        ('accion', 'ver_config_smtp'),
        ('accion', 'ver_config_ia'),
        ('accion', 'ver_config_instagram'),
        ('accion', 'ver_config_tokko'),
        ('accion', 'ver_config_plantillas'),
        ('accion', 'ver_config_logo'),
    ]

    conn = get_db(MASTER_DB_PATH)
    try:
        for tipo, obj_id in permitir:
            conn.execute("""
                INSERT OR REPLACE INTO privilegios_acceso (tipo_entidad, entidad_id, tipo_objeto, objeto_id, permitido)
                VALUES ('rol', 'broker', ?, ?, 1)
            """, (tipo, obj_id))
            
        plugins_activar = ['captacion_outreach', 'publicacion_placa', 'finanzas', 'redes_sociales', 'meta_ai', 'tokko', 'lotes_excel', 'asistente_ia', 'scraping_engine']
        for p_id in plugins_activar:
            conn.execute("""
                INSERT OR REPLACE INTO plugin_activation_roles (rol, plugin_id, activo)
                VALUES ('broker', ?, 1)
            """, (p_id,))
            
        conn.commit()
        print("[System] Matriz de Privilegios para brokers regularizada con éxito.")
    except Exception as e:
        print(f"[System] Error al normalizar privilegios de broker: {e}")
    finally:
        conn.close()


# --- 2FA / TOTP MANAGEMENT ---

def set_user_totp_secret(user_id, secret):
    """Guarda el secreto TOTP generado para un usuario."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("UPDATE usuarios SET totp_secret = ? WHERE id = ?", (secret, user_id))
        conn.commit()
    finally:
        conn.close()

def enable_user_2fa(user_id):
    """Habilita definitivamente el 2FA para el usuario."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("UPDATE usuarios SET totp_enabled = 1 WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def disable_user_2fa(user_id):
    """Deshabilita el 2FA y borra el secreto TOTP del usuario."""
    conn = get_db(MASTER_DB_PATH)
    try:
        conn.execute("UPDATE usuarios SET totp_enabled = 0, totp_secret = NULL WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def get_user_totp_info(user_id):
    """Obtiene el estado de 2FA y secreto TOTP del usuario."""
    conn = get_db(MASTER_DB_PATH)
    try:
        row = conn.execute("SELECT id, usuario, totp_secret, totp_enabled FROM usuarios WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
