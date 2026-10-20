"""
Main Kernel Flask Application - Decoupled & Modular
"""
import os
import sys
import io
import time
import json
import random
import subprocess
from datetime import datetime, timedelta

# ── Verificación y Auto-Instalación de Dependencias al Iniciar ───────────────
try:
    from lib.dependency_checker import ensure_dependencies_installed
    ensure_dependencies_installed(verbose=False)
except Exception as _dep_err:
    print(f"[Auto-Installer] Error verificando dependencias: {_dep_err}")

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Forzar codificación UTF-8 en Windows para evitar crashes por emojis en consola
if sys.platform.startswith('win'):
    if hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass

import urllib.parse
from flask import Flask, render_template, request, redirect, flash, jsonify, send_file, g, abort
from flask import url_for as flask_url_for
from werkzeug.routing import BuildError
from flask_login import LoginManager, UserMixin, login_required, current_user

from database import db
from lib.limiter import limiter


import logging

# ── Suppress noisy log lines ────────────────────────────────────────────────
# psycopg_pool prints "rolling back returned connection" for every idle
# connection returned to the pool — not an error, just housekeeping noise.
logging.getLogger("psycopg_pool").setLevel(logging.ERROR)
logging.getLogger("psycopg").setLevel(logging.ERROR)

class PollingLogFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # Suppress high-frequency polling requests and static QR polling from terminal console
        if any(endpoint in msg for endpoint in [
            '/admin/api/worker_status',
            '/api/whatsapp/portal/status',
            '/api/whatsapp/historias/status',
            '/api/whatsapp/status',
            '/api/instagram/status',
            '/tokko/sync/status',
            '/static/uploads/qr_',
            '/static/uploads/status_',
            '/robots.txt'
        ]):
            return False
        return True

logging.getLogger("werkzeug").addFilter(PollingLogFilter())

# Initialize Flask
app = Flask(__name__)

# Configuración Criptográfica de Clave Secreta
secret_key = os.environ.get('SECRET_KEY')
if not secret_key or secret_key == 'german_crm_secure_2026':
    import secrets
    secret_key = secrets.token_hex(32)
app.secret_key = secret_key

app.config['PLUGIN_BLUEPRINTS'] = {}
app.config['JSON_AS_ASCII'] = False
app.jinja_encoding = 'utf-8'

# Registrar funciones del Termómetro de Mercado en el motor Jinja2
from lib.market_thermometer import evaluar_oportunidad_mercado, calcular_dias_en_mercado
app.jinja_env.globals['evaluar_oportunidad_mercado'] = evaluar_oportunidad_mercado
app.jinja_env.globals['calcular_dias_en_mercado'] = calcular_dias_en_mercado

# Inicializar Rate Limiter
limiter.init_app(app)

# Inyección de Cabeceras de Seguridad HTTP
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# Session Cookie Security Configurations
is_https = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=is_https
)

# Ensure root logo files exist and are mirrored to static and uploads folders
def sync_root_logos():
    try:
        import shutil
        root_dir = os.path.dirname(os.path.abspath(__file__))
        pairs = [
            (os.path.join(root_dir, 'PotenziaCRM.jpg'), os.path.join(root_dir, 'static', 'img', 'PotenziaCRM.jpg')),
            (os.path.join(root_dir, 'PotenziaCRMsm.jpg'), os.path.join(root_dir, 'static', 'img', 'PotenziaCRMsm.jpg')),
            (os.path.join(root_dir, 'footerlogo.png'), os.path.join(root_dir, 'static', 'img', 'footerlogo.png')),
            (os.path.join(root_dir, 'PotenziaCRM.jpg'), os.path.join(root_dir, 'static', 'img', 'potenzia_logo.png')),
            (os.path.join(root_dir, 'PotenziaCRMsm.jpg'), os.path.join(root_dir, 'static', 'img', 'potenzia_logo_sm.png')),
            (os.path.join(root_dir, 'footerlogo.png'), os.path.join(root_dir, 'static', 'uploads', 'footerlogo.png')),
            (os.path.join(root_dir, 'PotenziaCRM.jpg'), os.path.join(root_dir, 'static', 'uploads', 'PotenziaCRM.jpg')),
            (os.path.join(root_dir, 'PotenziaCRMsm.jpg'), os.path.join(root_dir, 'static', 'uploads', 'PotenziaCRMsm.jpg')),
        ]
        for src, dst in pairs:
            if os.path.exists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
    except Exception as e:
        print(f"[Logo Sync] Error: {e}")

sync_root_logos()

# Initialize Database
db.init_db()

@app.route('/<string:logo_name>.png')
@app.route('/<string:logo_name>.jpg')
@app.route('/<string:logo_name>.jpeg')
def serve_root_logo(logo_name):
    """Serves logo files located in the root CRM directory if requested directly."""
    ext = request.path.rsplit('.', 1)[-1]
    filename = f"{logo_name}.{ext}"
    root_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(root_dir, filename)
    if os.path.exists(file_path) and filename in ('PotenziaCRM.jpg', 'PotenziaCRMsm.jpg', 'footerlogo.png', 'logo.png', 'vista.jpg'):
        mimetype = 'image/png' if ext == 'png' else 'image/jpeg'
        return send_file(file_path, mimetype=mimetype)
    from flask import abort
    abort(404)

try:
    from database.db_scrapers import enriquecer_descripciones_existentes
    enriquecer_descripciones_existentes()
except Exception as _e_desc:
    print(f"[App] Error ejecutando enriquecimiento de descripciones: {_e_desc}")

# Configuration for Flask-Login
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.init_app(app)

class User(UserMixin):
    def __init__(self, id, usuario, nombre_display, rol, db_file, oficina_id=None, oficina_nombre=None, oficina_slug=None):
        self.id = id
        self.usuario = usuario
        self.nombre_display = nombre_display
        self.rol = rol
        self.db_file = db_file
        self.oficina_id = oficina_id
        self.oficina_nombre = oficina_nombre
        self.oficina_slug = oficina_slug

@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_usuario_by_id(user_id)
    if user_data:
        return User(
            user_data['id'], 
            user_data['usuario'], 
            user_data['nombre_display'], 
            user_data['rol'], 
            user_data['db_file'],
            user_data.get('oficina_id'),
            user_data.get('oficina_nombre'),
            user_data.get('oficina_slug')
        )
    return None

@app.before_request
def setup_user_db_context():
    """Sets the DB path for the current request based on the logged-in user."""
    if current_user.is_authenticated:
        g.db_path = db.get_user_db_path(current_user.db_file)
    else:
        g.db_path = db.MASTER_DB_PATH

@app.teardown_appcontext
def close_db_connection(exception=None):
    """Releases the PostgreSQL DB connection at the end of every request context."""
    pg_conn = getattr(g, 'pg_conn', None)
    if pg_conn is not None:
        try:
            pg_conn.close()
        except Exception:
            pass
        g.pg_conn = None

@app.before_request
def check_plugin_access():
    """Dynamically checks if the user has access to the requested plugin's routes."""
    if not request.endpoint:
        return
        
    if '.' in request.endpoint:
        blueprint_name = request.endpoint.split('.')[0]
        blueprint_to_plugin = app.config.get('PLUGIN_BLUEPRINTS', {})
        
        # Public Portal & REST API Bypass: leads_externo y scraper_api gestionan su propio acceso
        if request.endpoint.startswith('leads_externo.') or request.endpoint.startswith('scraper_api.'):
            return

        if blueprint_name in blueprint_to_plugin:
            plugin_id = blueprint_to_plugin[blueprint_name]
            if not current_user or not current_user.is_authenticated:
                if request.endpoint in ['meta_ai.webhook_meta_ai',
                                        'captacion_outreach.ver_reporte_compartido',
                                        'captacion_outreach.ver_portal_temporal_publico',
                                        'captacion_outreach.ver_portal_temporal_propiedad_detalle',
                                        'fichas_cliente.ver_ficha_publica']:
                    return
                return redirect(url_for('login'))

            # GermanMazza bypasses everything
            if current_user.usuario == 'GermanMazza':
                return

            # Fine-grained route permissions (allow access if granted specifically in Matrix)
            if request.endpoint in ('captacion_outreach.configuracion', 'captacion_outreach.debug_meta_token'):
                if not db.check_user_privilege(current_user, 'menu_item', 'configuracion'):
                    from flask import abort
                    abort(403, description="No tenés permisos para acceder a Configuración.")
                return

            if blueprint_name == 'fichas_cliente' or request.endpoint == 'captacion_outreach.panel_fichas':
                if not db.check_user_privilege(current_user, 'menu_item', 'panel_fichas'):
                    from flask import abort
                    abort(403, description="No tenés permisos para acceder a Publi a Fichas (PAF).")
                return

            if 'portaltemp' in request.endpoint or request.endpoint == 'captacion_outreach.panel_portales_temporales':
                if not db.check_user_privilege(current_user, 'menu_item', 'portales_temporales'):
                    from flask import abort
                    abort(403, description="No tenés permisos para acceder a Portales Temporales.")
                return

            if request.endpoint in ('captacion_outreach.buscador_compradores', 'captacion_outreach.compradores_reporte', 'captacion_outreach.ver_reporte_compartido'):
                if not db.check_user_privilege(current_user, 'menu_item', 'buscador_ventas'):
                    from flask import abort
                    abort(403, description="No tenés permisos para acceder a Buscador Propiedades.")
                return

            if request.endpoint in ('captacion_outreach.buscador_alquileres', 'captacion_outreach.alquileres_reporte'):
                if not db.check_user_privilege(current_user, 'menu_item', 'buscador_alquileres'):
                    from flask import abort
                    abort(403, description="No tenés permisos para acceder a Buscador Alquileres.")
                return

            if 'busqueda' in request.endpoint or 'busquedas_clientes' in request.endpoint:
                if not db.check_user_privilege(current_user, 'menu_item', 'busquedas_clientes'):
                    from flask import abort
                    abort(403, description="No tenés permisos para acceder a Búsquedas de Clientes.")
                return

            if blueprint_name == 'publicacion_placa':
                if not db.check_user_privilege(current_user, 'menu_item', 'pap') and not db.check_user_privilege(current_user, 'plugin', 'publicacion_placa'):
                    from flask import abort
                    abort(403, description="No tenés permisos para acceder a Publicación a Placa (PAP).")
                return

            # 1. Superior activation level check
            if not db.is_plugin_active_for_role(current_user.rol, plugin_id):
                from flask import abort
                abort(403, description="Este módulo / plugin ha sido desactivado globalmente para tu rol.")
                
            # 2. Matrix privileges check
            if not db.check_user_privilege(current_user, 'plugin', plugin_id):
                from flask import abort
                abort(403, description="No tenés permisos para acceder a este módulo / plugin.")

@app.context_processor
def inject_helpers():
    def user_can(tipo_objeto, objeto_id):
        if not current_user or not current_user.is_authenticated:
            return False
            
        # GermanMazza bypasses everything
        if current_user.usuario == 'GermanMazza':
            return True

        # Independent core sections directly governed by matrix menu_item rules
        if tipo_objeto == 'menu_item' and objeto_id in (
            'configuracion', 'pap', 'panel_fichas', 'portales_temporales',
            'buscador_ventas', 'buscador_alquileres', 'busquedas_clientes',
            'tokko_cartera', 'tokko_mis_operaciones'
        ):
            return db.check_user_privilege(current_user, 'menu_item', objeto_id)
            
        menu_to_plugin = {
            'propiedades': 'captacion_outreach',
            'comunicaciones': 'captacion_outreach',
            'busquedas': 'captacion_outreach',
            'planificador': 'captacion_outreach',
            'seguimiento_prop': 'finanzas',
            'finanzas_oficina': 'finanzas',
            'libro_finanzas': 'finanzas',
            'historias': 'redes_sociales',
            'meta_ai': 'meta_ai',
            'tokko_cartera': 'tokko',
            'tokko_buscar': 'tokko',
            'tokko_mis_operaciones': 'tokko',
            'pap': 'publicacion_placa',
            'lotes_excel': 'lotes_excel',
            'busquedas_clientes': 'captacion_outreach',
            'buscador_ventas': 'captacion_outreach',
            'buscador_alquileres': 'captacion_outreach',
            'panel_fichas': 'captacion_outreach',
            'portales_temporales': 'captacion_outreach',
        }
        
        if tipo_objeto == 'plugin':
            if not db.is_plugin_active_for_role(current_user.rol, objeto_id):
                return False
        elif tipo_objeto == 'menu_item' and objeto_id in menu_to_plugin:
            linked_plugin = menu_to_plugin[objeto_id]
            if not db.is_plugin_active_for_role(current_user.rol, linked_plugin):
                return False
                
        # Check database privilege and return boolean
        return db.check_user_privilege(current_user, tipo_objeto, objeto_id)
        
    agency_data = db.get_agency_settings()
    try:
        proximos_eventos_default = db.get_proximos_eventos(limit=6)
    except Exception:
        proximos_eventos_default = []
    return {
        'now': datetime.now(),
        'agency': agency_data,
        'agency_name': agency_data.get('nombre', 'CRM Inmobiliario'),
        'user_can': user_can,
        'get_config': db.get_config,
        'sqlite_fallback_active': db.SQLITE_FALLBACK_ACTIVE,
        'active_db_type': db._pg_config.get("db_type", "sqlite"),
        'proximos_eventos': proximos_eventos_default
    }

# --- ENDPOINT ALIASES FOR BACKWARD COMPATIBILITY IN TEMPLATES ---
ENDPOINT_ALIASES = {
    'login': 'auth.login',
    'logout': 'auth.logout',
    'admin_usuarios': 'auth.admin_usuarios',
    'admin_oficinas': 'auth.admin_oficinas',
    'crear_oficina': 'auth.crear_oficina',
    'editar_oficina': 'auth.editar_oficina',
    'borrar_oficina': 'auth.borrar_oficina',
    'set_portal_oficina': 'auth.set_portal_oficina',
    'admin_privilegios': 'auth.admin_privilegios',
    'admin_plugin_control': 'plugin_control.manage_plugins',
    'admin_backups': 'db_backup.admin_backups',
    'crear_usuario': 'auth.crear_usuario',
    'admin_crear_usuario': 'auth.crear_usuario',
    'editar_usuario': 'auth.editar_usuario',
    'borrar_usuario': 'auth.borrar_usuario',
    'asignar_archivo': 'auth.asignar_archivo',
    'admin_asignar_archivos': 'auth.asignar_archivo',
    'archivos_asignados': 'auth.archivos_asignados',
    'borrar_archivo_asignado': 'auth.borrar_archivo_asignado',
    'subir_archivo_personal': 'auth.subir_archivo_personal',
    'subir_archivo_asignado': 'auth.subir_archivo_personal',
    'abrir_archivo_asignado': 'auth.abrir_archivo_asignado',
    
    'crm_contactos': 'crm.crm_contactos',
    'crm_gestionar_columnas': 'crm.crm_gestionar_columnas',
    'upsert_contacto': 'crm.upsert_contacto',
    'completar_recordatorio': 'crm.completar_recordatorio',
    'update_contacto': 'crm.update_contacto',
    'marcar_contacto_hoy': 'crm.marcar_contacto_hoy',
    'resumir_chat': 'crm.resumir_chat',
    'importar_excel': 'crm.importar_excel',
    'exportar_excel': 'crm.exportar_excel',
    'blacklist': 'crm.blacklist',
    'add_blacklist_route': 'crm.add_blacklist_route',
    'remove_blacklist_route': 'crm.remove_blacklist_route',
    'importador': 'crm.importador',
    'importar_paso_1': 'crm.importar_paso_1',
    'importar_paso_2': 'crm.importar_paso_2',

    'tasador': 'tasador.tasador',
    'acm_report': 'tasador.acm_report',
    'reporte_tasacion': 'tasador.reporte_tasacion',

    'historias_view': 'redes_sociales.historias_view',
    'historias_api_get': 'redes_sociales.historias_api_get',
    'historias_api': 'redes_sociales.historias_api_get',
    'historias_api_upload': 'redes_sociales.historias_api_upload',
    'upload_historia': 'redes_sociales.historias_api_upload',
    'historias_api_delete': 'redes_sociales.historias_api_delete',
    'delete_historia': 'redes_sociales.historias_api_delete',
    'historias_api_toggle': 'redes_sociales.historias_api_toggle',
    'historias_post_instant': 'redes_sociales.historias_post_instant',
    'historias_logs_view': 'redes_sociales.historias_logs_view',

    'seguimiento_prop': 'finanzas_plugin.seguimiento_prop',
    'guardar_operacion': 'finanzas_plugin.guardar_operacion',
    'borrar_operacion': 'finanzas_plugin.borrar_operacion',
    'importar_operaciones': 'finanzas_plugin.importar_operaciones',
    'finanzas_oficina': 'finanzas_plugin.finanzas_oficina',
    'guardar_config_finanzas': 'finanzas_plugin.guardar_config_finanzas',
    'generar_mes_agente': 'finanzas_plugin.generar_mes_agente',
    'asignar_deuda_puntual': 'finanzas_plugin.asignar_deuda_puntual',
    'toggle_estado_deuda': 'finanzas_plugin.toggle_estado_deuda',
    'libro_finanzas': 'finanzas_plugin.libro_finanzas',

    'propiedades_view': 'captacion_outreach.propiedades_view',
    'propiedad_detalle': 'captacion_outreach.propiedad_detalle',
    'actualizar_estado': 'captacion_outreach.actualizar_estado',
    'buscador_compradores': 'captacion_outreach.buscador_compradores',
    'buscador_alquileres': 'captacion_outreach.buscador_alquileres',
    'toggle_ia_provider': 'captacion_outreach.toggle_ia_provider',
    'generar_reporte_comprador': 'captacion_outreach.generar_reporte_comprador',
    'generar_reporte_alquiler': 'captacion_outreach.generar_reporte_alquiler',
    'busquedas': 'captacion_outreach.busquedas',
    'nueva_busqueda': 'captacion_outreach.nueva_busqueda',
    'activar_desactivar_busqueda': 'captacion_outreach.activar_desactivar_busqueda',
    'borrar_busqueda': 'captacion_outreach.borrar_busqueda',
    'configuracion': 'captacion_outreach.configuracion',
    'debug_meta_token': 'captacion_outreach.debug_meta_token',
    'panel_fichas': 'fichas_cliente.panel_fichas',

    'planificador': 'captacion_outreach.planificador',
    'preparar_mensaje': 'captacion_outreach.preparar_mensaje',
    'conectar_whatsapp': 'captacion_outreach.conectar_whatsapp',
    'whatsapp_status': 'captacion_outreach.whatsapp_status',
    'logout_whatsapp': 'captacion_outreach.logout_whatsapp',
    'publicar_historias_manualmente': 'redes_sociales.publicar_historias_manualmente',
    'borrar_comunicacion': 'captacion_outreach.borrar_comunicacion',
    'comunicaciones': 'captacion_outreach.comunicaciones',
    'marcar_enviada': 'captacion_outreach.marcar_enviada',
    'test_email': 'captacion_outreach.test_email',
    'test_whatsapp': 'captacion_outreach.test_whatsapp',
    'test_full_cycle': 'captacion_outreach.test_full_cycle',
    'ejecutar_scraper': 'captacion_outreach.ejecutar_scraper',
    'limpiar_inactivas': 'captacion_outreach.limpiar_inactivas',
    'limpiar_busqueda': 'captacion_outreach.limpiar_busqueda',
    'borrar_propiedad': 'captacion_outreach.borrar_propiedad',
    'borrar_propiedades_bulk': 'captacion_outreach.borrar_propiedades_bulk',
    'enviar_lote_5': 'captacion_outreach.enviar_lote_5',
    'lanzar_automatizacion': 'captacion_outreach.lanzar_automatizacion',
    'update_daily_task': 'captacion_outreach.update_daily_task',

    # Tokko Broker
    'tokko_cartera': 'tokko.cartera',
    'tokko_buscar': 'tokko.buscar',
    'tokko_mis_operaciones': 'tokko.mis_operaciones',
    'tokko_importar_operaciones': 'tokko.importar_operaciones',
    'tokko_trigger_sync': 'tokko.trigger_sync',
    'tokko_sync_status': 'tokko.sync_status',
    'tokko_buscar_productor': 'tokko.buscar_productor',
    'tokko_vincular_productor': 'tokko.vincular_productor',
    'tokko_verificar_conexion': 'tokko.verificar_conexion',
    'pap': 'publicacion_placa.index',
    'api_instagram_admin_conectar_sessionid': 'redes_sociales.api_instagram_admin_conectar_sessionid'
}

def custom_url_for(endpoint, **values):
    """Custom url_for mapper that maps non-namespaced endpoints to namespaced blueprints."""
    if endpoint in ENDPOINT_ALIASES:
        endpoint = ENDPOINT_ALIASES[endpoint]
    try:
        return flask_url_for(endpoint, **values)
    except BuildError:
        # If the blueprint/plugin is disabled or inactive, return '#' instead of crashing
        return '#'

# Expose url_for both in templates and in Python redirects inside app.py namespace
app.jinja_env.globals.update(url_for=custom_url_for)

def url_for(endpoint, **values):
    """Local override of url_for for app.py redirects/calls."""
    if endpoint in ENDPOINT_ALIASES:
        endpoint = ENDPOINT_ALIASES[endpoint]
    return flask_url_for(endpoint, **values)

# --- CORE ROUTE ---
@app.route('/')
@login_required
def index():
    """Dashboard principal personalizado para el agente logueado."""
    daily_tasks = db.get_tareas_diarias()
    cold_contacts_count = db.count_contactos_frios()
    fidelity = db.get_fidelizacion_hoy()
    recordatorios = db.get_recordatorios_pendientes()

    # 1. Propiedades en Seguimiento del agente logueado
    from database.db_finanzas import get_operaciones, get_deudas
    seguimiento_operaciones = get_operaciones(agente_id=current_user.id)

    # 2. Búsquedas de Clientes Abiertas del agente logueado
    busquedas_clientes_abiertas = db.get_busquedas_clientes(agente_id=current_user.id)

    # 3. Deudas de Finanzas Oficina (si el plugin está permitido/activado para el rol)
    deudas_oficina = []
    can_see_finanzas = db.is_plugin_active_for_role(current_user.rol, 'finanzas') and db.check_user_privilege(current_user, 'plugin', 'finanzas')
    if current_user.usuario == 'GermanMazza':
        can_see_finanzas = True

    if can_see_finanzas:
        deudas_oficina = get_deudas(agente_id=current_user.id, estado='falta')

    # 4. Status de Mi ClaudIA (Meta AI Chatbot microservice status)
    claudia_status = {'online': False, 'message': 'Offline'}
    try:
        import requests
        r = requests.get('http://localhost:3000/api/status', timeout=0.5)
        if r.status_code < 500:
            claudia_status = {'online': True, 'message': 'Online'}
    except Exception:
        # Check if plugin is enabled as fallback indicator
        meta_enabled = db.get_config('meta_ai_crm_enabled', '1') != '0'
        claudia_status = {'online': meta_enabled, 'message': 'Online' if meta_enabled else 'Offline'}

    # 5. Publicaciones programadas (Historias IG y WhatsApp Status) del agente logueado (solo futuras)
    publicaciones_programadas = []
    try:
        conn = db.get_db()
        today_str = datetime.now().strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT * FROM historias_redes 
            WHERE (agente_id = ? OR agente_id IS NULL) 
              AND estado = 'pendiente' 
              AND fecha_programada >= ?
            ORDER BY fecha_programada ASC, orden ASC
        """, (current_user.id, today_str)).fetchall()
        publicaciones_programadas = [dict(r) for r in rows]
    except Exception as e_hist:
        print(f"Error consultando historias programadas: {e_hist}")

    # 6. Próximos eventos (Efemérides, Días Patrios y Feriados de Argentina + Cumpleaños y Aniversarios de compra de clientes)
    proximos_eventos = db.get_proximos_eventos(limit=6)

    return render_template('index.html', 
                          daily_tasks=daily_tasks,
                          cold_contacts_count=cold_contacts_count,
                          fidelity=fidelity,
                          recordatorios=recordatorios,
                          proximos_eventos=proximos_eventos,
                          seguimiento_operaciones=seguimiento_operaciones,
                          busquedas_clientes_abiertas=busquedas_clientes_abiertas,
                          deudas_oficina=deudas_oficina,
                          can_see_finanzas=can_see_finanzas,
                          claudia_status=claudia_status,
                          publicaciones_programadas=publicaciones_programadas,
                          user=current_user)

@app.route('/presentacion')
def presentacion_ventas():
    """Presentación comercial interactiva para venta a inmobiliarias y brokers."""
    return send_file(os.path.join(app.root_path, 'presentacion_ventas.html'))

@app.route('/presentacion-broker')
def presentacion_broker():
    """Nueva presentación comercial estratégica y pulida para Brokers y Directores."""
    return send_file(os.path.join(app.root_path, 'presentacion_broker.html'))

@app.route('/api/proximos_eventos')
def api_proximos_eventos():
    """Devuelve los próximos eventos en formato JSON para consumo dinámico del frontend."""
    limit = request.args.get('limit', 6, type=int)
    agent_id = current_user.id if current_user and current_user.is_authenticated else None
    is_super = (current_user.usuario == 'GermanMazza') if current_user and current_user.is_authenticated else False
    from lib.eventos import get_proximos_eventos as _get_ev
    eventos = _get_ev(agente_id=agent_id, limit=limit, is_superadmin=is_super)
    return jsonify({'status': 'success', 'eventos': eventos})

# --- REGISTER BLUEPRINTS FOR CRM MODULES ---
from modules.auth import auth_bp
from modules.crm import crm_bp
from modules.tasador import tasador_bp
from modules.analitica import analitica_bp
from modules.papelera import papelera_bp

app.register_blueprint(auth_bp)
app.register_blueprint(crm_bp)
app.register_blueprint(tasador_bp)
app.register_blueprint(analitica_bp)
app.register_blueprint(papelera_bp)

# --- DYNAMIC PLUGINS LOADER ---
def register_dynamic_plugins(app):
    """Dynamically scan the plugins directory and register blueprints for enabled plugins."""
    plugins_dir = os.path.join(app.root_path, 'plugins')
    if not os.path.exists(plugins_dir):
        return
        
    for item in os.listdir(plugins_dir):
        item_path = os.path.join(plugins_dir, item)
        if os.path.isdir(item_path):
            manifest_path = os.path.join(item_path, 'manifest.json')
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                    
                    if manifest.get('enabled', True):
                        plugin_id = manifest.get('id', item)
                        module_name = f"plugins.{plugin_id}.routes"
                        __import__(module_name)
                        module = sys.modules[module_name]
                        
                        from flask import Blueprint
                        for attr_name in dir(module):
                            attr = getattr(module, attr_name)
                            if isinstance(attr, Blueprint):
                                app.register_blueprint(attr)
                                app.config['PLUGIN_BLUEPRINTS'][attr.name] = plugin_id
                                print(f"[Plugins] Registered blueprint '{attr.name}' from plugin '{plugin_id}'")
                except Exception as e:
                    print(f"[Plugins] Error loading plugin '{item}': {e}")

# Load dynamic plugins on startup
register_dynamic_plugins(app)

# Normalizar privilegios de agente y broker de fábrica en base de datos
try:
    from database.db_auth import normalizar_privilegios_agente, normalizar_privilegios_broker
    normalizar_privilegios_agente()
    normalizar_privilegios_broker()
except Exception as startup_err:
    print(f"[System] Error al ejecutar normalización de privilegios: {startup_err}")

# --- DATABASE ADMINISTRATION & MIGRATION ROUTES ---
@app.route('/admin/database')
@login_required
def admin_database():
    if current_user.rol != 'admin':
        from flask import abort
        abort(403)
    db.load_db_config()
    return render_template('db_admin.html', db_config=db._pg_config, sqlite_fallback_active=db.SQLITE_FALLBACK_ACTIVE, active_env=db._pg_config.get("active_env", "development"))

@app.route('/admin/database/toggle', methods=['POST'])
@login_required
def admin_database_toggle():
    if current_user.rol != 'admin':
        from flask import abort
        abort(403)
    active_env = request.form.get('active_env', 'development')
    db.load_db_config()
    db._pg_config['active_env'] = active_env
    if db._pg_pool:
        try:
            db._pg_pool.close()
            db._pg_pool = None
        except:
            pass
    try:
        with open(db.CONFIG_FILE, 'w', encoding='utf-8') as f_cfg:
            json.dump(db._pg_config, f_cfg, indent=4)
        flash(f"Entorno cambiado a {active_env} exitosamente.", "success")
    except Exception as e:
        flash(f"Error al guardar entorno: {e}", "danger")
    return redirect(url_for('admin_database'))

@app.route('/admin/database/save', methods=['POST'])
@login_required
def admin_database_save_config():
    if current_user.rol != 'admin':
        from flask import abort
        abort(403)
    
    db_type = request.form.get('db_type', 'sqlite')
    sqlite_fallback = request.form.get('sqlite_fallback_enabled') == 'true' or request.form.get('sqlite_fallback_enabled') == 'on'
    pg_local = request.form.get('pg_local', '')
    pg_prod = request.form.get('pg_prod', '')
    
    db.load_db_config()
    db._pg_config['db_type'] = db_type
    db._pg_config['sqlite_fallback_enabled'] = sqlite_fallback
    db._pg_config['postgres']['local'] = pg_local
    db._pg_config['postgres']['production'] = pg_prod
    
    if db._pg_pool:
        try:
            db._pg_pool.close()
            db._pg_pool = None
        except:
            pass
            
    try:
        with open(db.CONFIG_FILE, 'w', encoding='utf-8') as f_cfg:
            json.dump(db._pg_config, f_cfg, indent=4)
        
        if db_type == 'postgresql':
            if db.init_pg_pool():
                try:
                    conn = db._pg_pool.getconn()
                    db._pg_pool.putconn(conn)
                    db.SQLITE_FALLBACK_ACTIVE = False
                    flash("Configuración guardada y conexión exitosa con PostgreSQL.", "success")
                except Exception as pg_err:
                    db.SQLITE_FALLBACK_ACTIVE = True
                    flash(f"Configuración guardada pero falló la conexión con PostgreSQL: {pg_err}", "warning")
            else:
                db.SQLITE_FALLBACK_ACTIVE = True
                flash("Configuración guardada pero falló al inicializar el pool de PostgreSQL.", "warning")
        else:
            flash("Configuración de SQLite guardada exitosamente.", "success")
            
    except Exception as e:
        flash(f"Error al guardar la configuración: {e}", "danger")
        
    return redirect(url_for('admin_database'))

@app.route('/admin/database/migrate/stream')
@login_required
def admin_database_migrate_stream():
    if current_user.rol != 'admin':
        from flask import abort
        abort(403)
        
    from flask import Response
    
    def generate():
        yield "data: [INICIO] Conectando a PostgreSQL de destino...\n\n"
        import sqlite3
        
        if not db.init_pg_pool():
            yield "data: [ERROR] No se pudo conectar a PostgreSQL. Verifica las cadenas de conexión.\n\n"
            return
            
        pg_conn = None
        try:
            pg_conn = db._pg_pool.getconn()
            pg_conn.autocommit = False
            pg_cursor = pg_conn.cursor()
            
            # Disable triggers and foreign keys temporarily for clean bulk migration
            pg_cursor.execute("SET session_replication_role = 'replica'")
            pg_conn.commit()
            
            tables = [
                'configuracion', 'busquedas', 'propiedades', 'comunicaciones', 
                'cola_mensajes', 'estadisticas_ia', 'usuarios', 'archivos_asignados', 
                'contactos', 'lista_negra', 'tareas_diarias_estado', 'tasaciones_logs', 
                'planificador_mensajes', 'seguimiento_operaciones', 'finanzas_deudas', 
                'config_deudas_agentes', 'privilegios_acceso', 'historias_redes', 
                'agentes_contactos_copia', 'busquedas_clientes', 'cola_correos_clientes', 'marcas',
                'lotes', 'lotes_detalles_manuales'
            ]

            yield "data: [LIMPIEZA] Eliminando tablas existentes en PostgreSQL...\n\n"
            for table in tables:
                pg_cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
            pg_conn.commit()
            yield "data: [LIMPIEZA] PostgreSQL limpio de tablas anteriores.\n\n"

            yield "data: [ESQUEMA] Creando tablas en PostgreSQL...\n\n"
            schema_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'schema_postgres.sql')
            if not os.path.exists(schema_file_path):
                yield f"data: [ERROR] No se encontró el archivo de esquema: {schema_file_path}\n\n"
                return
                
            with open(schema_file_path, 'r', encoding='utf-8') as f_schema:
                schema_sql = f_schema.read()
                
            pg_cursor.execute(schema_sql)
            pg_conn.commit()
            
            # Clear default entries inserted by schema script to prevent unique/primary key duplicates
            pg_cursor.execute("DELETE FROM usuarios")
            pg_cursor.execute("DELETE FROM configuracion")
            pg_cursor.execute("DELETE FROM estadisticas_ia")
            pg_cursor.execute("DELETE FROM planificador_mensajes")
            pg_conn.commit()
            
            # Reinitialize plugin-specific tables on the newly created PostgreSQL database
            try:
                from plugins.lotes_excel.routes import init_lotes_table
                init_lotes_table()
            except Exception as e_lotes_init:
                print(f"[Migration] Error initializing lotes tables on destination: {e_lotes_init}")
                
            try:
                from plugins.tokko.db_tokko import init_tokko_tables
                init_tokko_tables()
            except Exception as e_tokko_init:
                print(f"[Migration] Error initializing tokko tables on destination: {e_tokko_init}")
            
            yield "data: [ESQUEMA] Tablas creadas/verificadas exitosamente en PostgreSQL.\n\n"
            
            yield "data: [MIGRACION] Conectando a SQLite master (captador.db)...\n\n"
            sqlite_master = sqlite3.connect(db.MASTER_DB_PATH)
            sqlite_master.row_factory = sqlite3.Row
            
            german_id = None

            for table in tables:
                yield f"data: [TABLA] Migrando {table} desde base maestra...\n\n"
                try:
                    # If we are about to migrate 'tareas_diarias_estado' (or contacts/props) and need GermanMazza's ID, fetch it if we haven't already
                    if table in ['contactos', 'propiedades', 'tareas_diarias_estado'] and german_id is None:
                        pg_cursor.execute("SELECT id FROM usuarios WHERE LOWER(usuario) = 'germanmazza'")
                        german_row = pg_cursor.fetchone()
                        german_id = german_row[0] if german_row else None

                    sqlite_rows = sqlite_master.execute(f"SELECT * FROM {table}").fetchall()
                    if sqlite_rows:
                        cols = list(sqlite_rows[0].keys())
                        if table in ['contactos', 'propiedades', 'tareas_diarias_estado'] and german_id is not None:
                            if 'agente_id' not in cols:
                                cols.append('agente_id')
                            
                        placeholders = ", ".join(["%s"] * len(cols))
                        insert_query = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
                        
                        count = 0
                        for row in sqlite_rows:
                            row_dict = dict(row)
                            if table in ['contactos', 'propiedades', 'tareas_diarias_estado'] and german_id is not None:
                                row_dict['agente_id'] = german_id
                            
                            # Clean row: convert empty string "" to None (NULL in SQL) to avoid type conversion crashes
                            cleaned_row = tuple(None if row_dict.get(val) == "" or row_dict.get(val) is None else row_dict.get(val) for val in cols)
                            pg_cursor.execute(insert_query, cleaned_row)
                            count += 1
                        pg_conn.commit()
                        yield f"data: [TABLA] {table} migrada: {count} filas insertadas.\n\n"
                    else:
                        yield f"data: [TABLA] {table} está vacía.\n\n"
                except Exception as tbl_err:
                    pg_conn.rollback()
                    yield f"data: [INFO] Tabla {table} omitida o fallida: {tbl_err}\n\n"
            
            sqlite_master.close()
            
            # Reset sequences to prevent duplicate key errors during auto-increment inserts
            yield "data: [MIGRACION] Ajustando secuencias autoincrementales en PostgreSQL...\n\n"
            seq_tables = [
                'busquedas', 'propiedades', 'comunicaciones', 'cola_mensajes', 
                'usuarios', 'archivos_asignados', 'contactos', 'lista_negra', 
                'tasaciones_logs', 'seguimiento_operaciones', 'finanzas_deudas', 
                'privilegios_acceso', 'historias_redes', 'busquedas_clientes', 
                'cola_correos_clientes', 'marcas', 'lotes'
            ]
            for seq_table in seq_tables:
                try:
                    pg_cursor.execute(f"SELECT setval(pg_get_serial_sequence('{seq_table}', 'id'), COALESCE(MAX(id), 1)) FROM {seq_table}")
                except Exception as seq_err:
                    pg_conn.rollback()
            pg_conn.commit()

            
            yield "data: [MIGRACION] Buscando bases de datos de agentes individuales...\n\n"
            if os.path.exists(db.USERS_DB_DIR):
                for f in os.listdir(db.USERS_DB_DIR):
                    if f.endswith('.db'):
                        agent_db_path = os.path.join(db.USERS_DB_DIR, f)
                        username = f[:-3]
                        yield f"data: [AGENTE] Migrando base del agente '{username}'...\n\n"
                        
                        pg_cursor.execute("SELECT id FROM usuarios WHERE LOWER(usuario) = LOWER(%s)", (username,))
                        user_row = pg_cursor.fetchone()
                        if not user_row:
                            yield f"data: [ADVERTENCIA] Agente '{username}' no registrado en la tabla usuarios. Saltando...\n\n"
                            continue
                        agent_id = user_row[0]
                        
                        try:
                            lite_agent = sqlite3.connect(agent_db_path)
                            lite_agent.row_factory = sqlite3.Row
                            
                            contact_id_map = {}
                            property_id_map = {}
                            
                            agent_tables = ['contactos', 'propiedades', 'comunicaciones', 'historias_redes', 'busquedas_clientes', 'seguimiento_operaciones', 'finanzas_deudas']
                            for atable in agent_tables:
                                try:
                                    rows = lite_agent.execute(f"SELECT * FROM {atable}").fetchall()
                                    if rows:
                                        count = 0
                                        if atable == 'contactos':
                                            for row in rows:
                                                row_dict = dict(row)
                                                old_id = row_dict.get('id')
                                                tel = row_dict.get('telefono')
                                                
                                                # Check if contact already exists in postgres by telefono
                                                existing_id = None
                                                if tel:
                                                    pg_cursor.execute("SELECT id FROM contactos WHERE telefono = %s", (tel,))
                                                    existing_row = pg_cursor.fetchone()
                                                    if existing_row:
                                                        existing_id = existing_row[0]
                                                        
                                                if existing_id:
                                                    contact_id_map[old_id] = existing_id
                                                else:
                                                    # Insert and get new ID
                                                    cols = [c for c in row_dict.keys() if c != 'id']
                                                    cols.append('agente_id')
                                                    row_dict['agente_id'] = agent_id
                                                    placeholders = ", ".join(["%s"] * len(cols))
                                                    vals = tuple(None if row_dict.get(c) == "" or row_dict.get(c) is None else row_dict.get(c) for c in cols)
                                                    insert_q = f"INSERT INTO contactos ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id"
                                                    pg_cursor.execute(insert_q, vals)
                                                    new_id = pg_cursor.fetchone()[0]
                                                    contact_id_map[old_id] = new_id
                                                    count += 1
                                            pg_conn.commit()
                                            yield f"data: [AGENTE] {username} -> {atable} migrado: {count} filas insertadas.\n\n"
                                            
                                        elif atable == 'propiedades':
                                            for row in rows:
                                                row_dict = dict(row)
                                                old_id = row_dict.get('id')
                                                url = row_dict.get('url')
                                                
                                                # Check if property already exists in postgres by url
                                                existing_id = None
                                                if url:
                                                    pg_cursor.execute("SELECT id FROM propiedades WHERE url = %s", (url,))
                                                    existing_row = pg_cursor.fetchone()
                                                    if existing_row:
                                                        existing_id = existing_row[0]
                                                        
                                                if existing_id:
                                                    property_id_map[old_id] = existing_id
                                                else:
                                                    # Insert and get new ID
                                                    cols = [c for c in row_dict.keys() if c != 'id']
                                                    cols.append('agente_id')
                                                    row_dict['agente_id'] = agent_id
                                                    placeholders = ", ".join(["%s"] * len(cols))
                                                    vals = tuple(None if row_dict.get(c) == "" or row_dict.get(c) is None else row_dict.get(c) for c in cols)
                                                    insert_q = f"INSERT INTO propiedades ({', '.join(cols)}) VALUES ({placeholders}) RETURNING id"
                                                    pg_cursor.execute(insert_q, vals)
                                                    new_id = pg_cursor.fetchone()[0]
                                                    property_id_map[old_id] = new_id
                                                    count += 1
                                            pg_conn.commit()
                                            yield f"data: [AGENTE] {username} -> {atable} migrado: {count} filas insertadas.\n\n"
                                            
                                        else:
                                            # Other agent tables: communications, histories, search clients, tracking, debts
                                            # We drop the 'id' column so Postgres auto-generates it, avoiding any collisions
                                            # And we map foreign keys to their new values
                                            cols_origin = list(rows[0].keys())
                                            cols = [c for c in cols_origin if c != 'id']
                                            
                                            has_agent_col = False
                                            if atable in ['seguimiento_operaciones', 'finanzas_deudas', 'historias_redes', 'busquedas_clientes']:
                                                has_agent_col = True
                                                if 'agente_id' not in cols:
                                                    cols.append('agente_id')
                                                    
                                            placeholders = ", ".join(["%s"] * len(cols))
                                            insert_query = f"INSERT INTO {atable} ({', '.join(cols)}) VALUES ({placeholders})"
                                            
                                            for row in rows:
                                                row_dict = dict(row)
                                                if has_agent_col:
                                                    row_dict['agente_id'] = agent_id
                                                    
                                                # Map foreign keys
                                                if atable in ['comunicaciones', 'cola_mensajes'] and 'propiedad_id' in row_dict:
                                                    old_prop_id = row_dict['propiedad_id']
                                                    row_dict['propiedad_id'] = property_id_map.get(old_prop_id)
                                                    # Skip orphans if they reference a property that didn't import
                                                    if row_dict['propiedad_id'] is None:
                                                        continue
                                                        
                                                if atable == 'busquedas_clientes' and 'cliente_id' in row_dict:
                                                    old_client_id = row_dict['cliente_id']
                                                    row_dict['cliente_id'] = contact_id_map.get(old_client_id)
                                                    # Skip orphans if they reference a contact that didn't import
                                                    if row_dict['cliente_id'] is None:
                                                        continue
                                                
                                                val_tuple = tuple(None if row_dict.get(c) == "" else row_dict.get(c) for c in cols)
                                                pg_cursor.execute(insert_query, val_tuple)
                                                count += 1
                                            pg_conn.commit()
                                            yield f"data: [AGENTE] {username} -> {atable} migrado: {count} filas insertadas.\n\n"
                                except Exception as agent_tbl_err:
                                    pg_conn.rollback()
                                    yield f"data: [INFO] Agente {username} -> tabla {atable} fallida o no encontrada: {agent_tbl_err}\n\n"
                                    
                            lite_agent.close()
                        except Exception as agent_db_err:
                            pg_conn.rollback()
                            yield f"data: [ERROR] Error al migrar base de datos {f}: {agent_db_err}\n\n"
                            
            # Restore triggers and foreign keys after migration completes
            pg_cursor.execute("SET session_replication_role = 'origin'")
            pg_conn.commit()
            
            yield "data: [DONE]\n\n"

            
        except Exception as e:
            if pg_conn:
                pg_conn.rollback()
            yield f"data: [ERROR] Error en el proceso de migración: {e}\n\n"
        finally:
            if pg_conn:
                db._pg_pool.putconn(pg_conn)
                
    return Response(generate(), mimetype='text/event-stream')

# ── WORKER CONTROL & HEARTBEAT SYSTEM ──
WORKER_MANUAL_STOPPED = False
HEARTBEAT_PATH = os.path.join(db.DB_DIR, "crm_heartbeat.json")
LOCK_FILE_PATH = os.path.join(db.DB_DIR, "wa_worker.lock")

def start_heartbeat_service():
    """Escribe periódicamente el latido del proceso app.py cada 3 segundos."""
    import threading
    import time
    import json
    
    def heartbeat_loop():
        while True:
            try:
                os.makedirs(db.DB_DIR, exist_ok=True)
                data = {
                    "timestamp": time.time(),
                    "app_pid": os.getpid(),
                    "status": "alive",
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                tmp_path = HEARTBEAT_PATH + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                if os.path.exists(HEARTBEAT_PATH):
                    try:
                        os.remove(HEARTBEAT_PATH)
                    except Exception:
                        pass
                os.rename(tmp_path, HEARTBEAT_PATH)
            except Exception:
                pass
            time.sleep(3)

    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()

def get_current_worker_info():
    """Consulta el estado del proceso del worker de WhatsApp/Historias."""
    is_running = False
    current_pid = None
    if os.path.exists(LOCK_FILE_PATH):
        try:
            with open(LOCK_FILE_PATH, 'r', encoding='utf-8') as f:
                lock_pid_str = f.read().strip()
            if lock_pid_str:
                current_pid = int(lock_pid_str)
                tasklist_out = subprocess.check_output(f'tasklist /FI "PID eq {current_pid}" /FO CSV', shell=True, text=True, errors='ignore')
                if str(current_pid) in tasklist_out:
                    is_running = True
                else:
                    current_pid = None
        except Exception:
            current_pid = None
            is_running = False

    return {
        "running": is_running,
        "pid": current_pid,
        "manual_stopped": WORKER_MANUAL_STOPPED,
        "app_pid": os.getpid()
    }

def kill_existing_workers():
    """Mata cualquier proceso de whatsapp_sender.py corriendo y limpia el lock."""
    try:
        if os.path.exists(LOCK_FILE_PATH):
            try:
                with open(LOCK_FILE_PATH, 'r') as f:
                    old_pid = f.read().strip()
                if old_pid:
                    subprocess.run(f"taskkill /PID {old_pid} /F /T", shell=True, capture_output=True)
            except Exception:
                pass
            try:
                os.remove(LOCK_FILE_PATH)
            except Exception:
                pass
        subprocess.run('wmic process where "CommandLine like \'%whatsapp_sender.py%\'" call terminate', shell=True, capture_output=True)
    except Exception as e:
        print(f"[Worker Control] Error matando workers: {e}")

@app.route('/admin/api/worker_status', methods=['GET'])
@login_required
def admin_worker_status():
    if current_user.rol != 'admin' and current_user.usuario != 'GermanMazza':
        from flask import abort
        abort(403)
    info = get_current_worker_info()
    
    # Check heartbeat freshness
    last_hb_sec = None
    if os.path.exists(HEARTBEAT_PATH):
        try:
            with open(HEARTBEAT_PATH, 'r', encoding='utf-8') as f:
                hb = json.load(f)
            last_hb_sec = round(time.time() - hb.get('timestamp', 0), 1)
        except Exception:
            pass
            
    info['last_heartbeat_ago'] = last_hb_sec
    return jsonify({'success': True, 'worker': info})

@app.route('/admin/api/worker_action', methods=['POST'])
@login_required
def admin_worker_action():
    global WORKER_MANUAL_STOPPED
    if current_user.rol != 'admin' and current_user.usuario != 'GermanMazza':
        from flask import abort
        abort(403)
        
    data = request.get_json() or {}
    action = data.get('action')
    
    if action == 'stop':
        WORKER_MANUAL_STOPPED = True
        kill_existing_workers()
        return jsonify({'success': True, 'message': 'Worker detenido manualmente y watchdog pausado.'})
    
    elif action == 'start':
        WORKER_MANUAL_STOPPED = False
        kill_existing_workers()
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'whatsapp_sender.py')
        log_dir = os.path.join(db.DB_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "whatsapp_worker_console.log")
        creationflags = 0x08000000 if os.name == 'nt' else 0
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            p = subprocess.Popen(['python', script_path], stdout=log_file, stderr=log_file, creationflags=creationflags)
        return jsonify({'success': True, 'message': f'Worker iniciado exitosamente (PID: {p.pid}).'})
        
    elif action == 'restart':
        WORKER_MANUAL_STOPPED = False
        kill_existing_workers()
        time.sleep(1)
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'whatsapp_sender.py')
        log_dir = os.path.join(db.DB_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "whatsapp_worker_console.log")
        creationflags = 0x08000000 if os.name == 'nt' else 0
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            p = subprocess.Popen(['python', script_path], stdout=log_file, stderr=log_file, creationflags=creationflags)
        return jsonify({'success': True, 'message': f'Worker reiniciado exitosamente (PID: {p.pid}).'})
        
    return jsonify({'success': False, 'error': f'Acción desconocida: {action}'}), 400

@app.route('/admin/api/purge_zombies', methods=['POST'])
@login_required
def admin_purge_zombies():
    if current_user.rol != 'admin' and current_user.usuario != 'GermanMazza':
        return jsonify({'success': False, 'error': 'Acceso no autorizado'}), 403
    
    try:
        from lib.process_cleaner import purge_crm_zombie_processes
        killed = purge_crm_zombie_processes(exclude_current=True, kill_workers_only=False)
        return jsonify({
            'success': True,
            'killed_count': len(killed),
            'killed_details': killed,
            'message': f'Limpieza quirúrgica completada: {len(killed)} procesos zombis del CRM purgados. Claudia, ngrok y demás apps intactas.'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error en purga: {e}'}), 500


# ── GROWTH MARKETING CANVAS (SuperAdmin Exclusivo) ───────────────────────────
@app.route('/growth-canvas')
@login_required
def growth_canvas():
    if current_user.usuario != 'GermanMazza' and current_user.rol != 'superadmin':
        abort(403)
    
    projects = db.get_growth_canvas_projects()
    if not projects:
        db.check_and_add_growth_canvas_table()
        projects = db.get_growth_canvas_projects()

    req_id = request.args.get('project_id', type=int)
    active_project = None
    if req_id:
        active_project = db.get_growth_canvas_project(req_id)
    if not active_project and projects:
        active_project = db.get_growth_canvas_project(projects[0]['id'])

    return render_template(
        'growth_canvas.html',
        projects=projects,
        active_project=active_project
    )

@app.route('/api/growth-canvas/save', methods=['POST'])
@login_required
def api_growth_canvas_save():
    if current_user.usuario != 'GermanMazza' and current_user.rol != 'superadmin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    payload = request.get_json() or {}
    project_id = payload.get('project_id')
    if not project_id:
        return jsonify({'success': False, 'error': 'Falta project_id'}), 400

    nombre = payload.get('nombre')
    empresa = payload.get('empresa')
    data_dict = payload.get('data')

    ok = db.save_growth_canvas_project(project_id, nombre, empresa, data_dict)
    if ok:
        return jsonify({'success': True, 'timestamp': datetime.now().strftime('%H:%M:%S')})
    return jsonify({'success': False, 'error': 'No se pudo guardar'}), 500

@app.route('/api/growth-canvas/project/new', methods=['POST'])
@login_required
def api_growth_canvas_new_project():
    if current_user.usuario != 'GermanMazza' and current_user.rol != 'superadmin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    payload = request.get_json() or {}
    nombre = payload.get('nombre', 'Nuevo Proyecto').strip() or 'Nuevo Proyecto'
    empresa = payload.get('empresa', '').strip()
    new_id = db.create_growth_canvas_project(nombre, empresa)
    if new_id:
        return jsonify({'success': True, 'project_id': new_id})
    return jsonify({'success': False, 'error': 'No se pudo crear el proyecto'}), 500

@app.route('/api/growth-canvas/project/delete', methods=['POST'])
@login_required
def api_growth_canvas_delete_project():
    if current_user.usuario != 'GermanMazza' and current_user.rol != 'superadmin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    payload = request.get_json() or {}
    project_id = payload.get('project_id')
    if not project_id:
        return jsonify({'success': False, 'error': 'Falta project_id'}), 400

    ok = db.delete_growth_canvas_project(project_id)
    return jsonify({'success': ok})

@app.route('/api/growth-canvas/project/<int:project_id>')
@login_required
def api_growth_canvas_get_project(project_id):
    if current_user.usuario != 'GermanMazza' and current_user.rol != 'superadmin':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    proj = db.get_growth_canvas_project(project_id)
    if proj:
        return jsonify({'success': True, 'project': proj})
    return jsonify({'success': False, 'error': 'Proyecto no encontrado'}), 404


if __name__ == '__main__':
    # Limpieza quirúrgica de arranque: mata solo zombis viejos del CRM sin tocar Claudia ni ngrok
    try:
        from lib.process_cleaner import purge_crm_zombie_processes
        initial_purged = purge_crm_zombie_processes(exclude_current=True, kill_workers_only=False)
        if initial_purged:
            print(f"[System] Limpieza quirúrgica de arranque: {len(initial_purged)} procesos zombis del CRM purgados.")
    except Exception as e:
        print(f"[System] Error en limpieza de arranque: {e}")

    # Iniciar servicio de latido (Heartbeat)
    try:
        start_heartbeat_service()
        print("[System] Servicio de Latido (Heartbeat) iniciado.")
    except Exception as e:
        print(f"[System] Error iniciando Heartbeat: {e}")

    # Launch background workers
    try:
        from lib.automation import start_staggered_email_worker, start_daily_saved_searches_worker
        from plugins.db_backup.backup_engine import start_backup_scheduler
        from lib.scraper_client import ScraperClient

        start_staggered_email_worker(app)
        start_daily_saved_searches_worker(app)
        start_backup_scheduler(app)

        s_cfg = ScraperClient.get_config()
        remote_url = s_cfg.get('url', 'http://173.249.38.187:5001')
        print(f"[System] Modo Scraper REMOTO ESTRICTO activo ({remote_url}): Todos los barridos, enriquecimientos y rotaciones de proxies se ejecutan exclusivamente en el microservicio central.")

        print("[System] Email, Daily Searches & Backup Workers launched.")
    except Exception as e:
        print(f"[System] Error launching Background Workers: {e}")

    # Launch global whatsapp worker automatically with Watchdog
    def start_whatsapp_worker_watchdog():
        import threading
        import time
        import subprocess

        def watchdog_loop():
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib', 'whatsapp_sender.py')
            log_dir = r"C:\FerrariDB\logs"
            os.makedirs(log_dir, exist_ok=True)
            log_file_path = os.path.join(log_dir, "whatsapp_worker_console.log")
            creationflags = 0x08000000 if os.name == 'nt' else 0

            while True:
                try:
                    if not WORKER_MANUAL_STOPPED:
                        info = get_current_worker_info()
                        if not info['running']:
                            if os.path.exists(LOCK_FILE_PATH):
                                try:
                                    os.remove(LOCK_FILE_PATH)
                                except Exception:
                                    pass
                            with open(log_file_path, "a", encoding="utf-8") as log_file:
                                p = subprocess.Popen(['python', script_path], stdout=log_file, stderr=log_file, creationflags=creationflags)
                                print(f"[Watchdog] Global WhatsApp Worker iniciado en segundo plano (PID: {p.pid}).")
                                p.wait()
                except Exception as e:
                    print(f"[Watchdog] Error en guardian WhatsApp Worker: {e}")
                
                time.sleep(5)

        t = threading.Thread(target=watchdog_loop, daemon=True)
        t.start()

    try:
        start_whatsapp_worker_watchdog()
        print("[System] Global WhatsApp Worker Watchdog activado.")
    except Exception as e:
        print(f"[System] Error activando Watchdog de WhatsApp: {e}")
        
    app.run(debug=True, use_reloader=False, port=5000)

