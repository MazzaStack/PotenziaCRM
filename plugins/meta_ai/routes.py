"""
Webhook and Admin Panel Blueprint for Meta AI Chatbot Connector (ClaudIA) Plugin
"""
import os
import requests
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, g
from flask_login import login_required, current_user
from database import db
from lib.hooks import fire_hook
from modules.auth import privilege_required

meta_ai_bp = Blueprint('meta_ai', __name__)

NODE_BOT_API = "http://localhost:3000/api"

@meta_ai_bp.route('/webhook/<username>', methods=['GET', 'POST'])
def proxy_webhook(username):
    """Proxy requests to the Node.js Chatbot microservice webhook endpoint."""
    node_webhook_url = f"http://localhost:3000/webhook/{username}"
    try:
        # Exclude Host header to prevent issues with local request routing
        headers = {key: value for key, value in request.headers if key.lower() != 'host'}
        
        if request.method == 'GET':
            # Verification challenge from Meta
            r = requests.get(node_webhook_url, params=request.args, headers=headers, timeout=10)
            return r.text, r.status_code
        elif request.method == 'POST':
            # Respond immediately to Meta to prevent webhook retry loops
            payload = request.json
            import threading
            def run_proxy():
                try:
                    requests.post(node_webhook_url, json=payload, headers=headers, timeout=15)
                except Exception as ex:
                    print(f"[Meta AI Proxy Webhook Async Error] {ex}")
            threading.Thread(target=run_proxy).start()
            return 'EVENT_RECEIVED', 200
    except Exception as e:
        print(f"[Meta AI Proxy Webhook Error] {e}")
        return jsonify({'error': 'No se pudo conectar con el servicio Node.js', 'details': str(e)}), 502

@meta_ai_bp.route('/api/leads/meta', methods=['POST'])
def webhook_meta_ai():
    """Webhook to receive leads from the Meta AI Chatbot Connector in a sandboxed plugin."""
    # Check if CRM connection is enabled
    crm_enabled = db.get_config('meta_ai_crm_enabled', '1') != '0'
    if not crm_enabled:
        print("[Meta AI Plugin] CRM Connection is disabled. Request ignored.")
        return jsonify({
            'status': 'disabled', 
            'message': 'La conexión con el CRM está desactivada en la configuración.'
        }), 403

    # Strict authorization
    token_esperado = (os.environ.get('META_AI_WEBHOOK_TOKEN') or db.get_config('meta_ai_webhook_token') or 'crm_secure_webhook_token').strip()
    auth_header = request.headers.get('Authorization', '').strip()
    token_query = request.args.get('token', '').strip()
    is_valid = (auth_header == f"Bearer {token_esperado}") or (token_query == token_esperado)
    if not is_valid:
        return jsonify({'status': 'error', 'message': 'No autorizado. Token de webhook inválido o ausente.'}), 401
        
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'No JSON data'}), 400
        
    # Extract fields
    nombre = data.get('nombre', 'Lead Meta AI')
    telefono = data.get('telefono')
    mensaje_original = data.get('mensaje_original', '')
    intencion = data.get('intencion', '')
    
    if not telefono:
        return jsonify({'status': 'error', 'message': 'Falta el telefono'}), 400
        
    # Determine user DB destination (Master or agent specific DB)
    db_path = db.MASTER_DB_PATH
    usuario_asignado = data.get('usuario_asignado')
    if usuario_asignado:
        user_data = db.get_usuario(usuario_asignado)
        if user_data:
            db_path = db.get_user_db_path(user_data['db_file'])
            
    # Set DB Context for request
    g.db_path = db_path
    
    # Calculate follow-up reminder date (default 1 day)
    fecha_recordatorio = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    notas = f"Meta AI: {mensaje_original}"
    
    contacto_data = {
        'nombre': nombre,
        'telefono': telefono,
        'mac': 1,
        'intencion_ia': intencion,
        'recordatorio_activo': 1,
        'recordatorio_dias': 1,
        'recordatorio_fecha': fecha_recordatorio,
        'notas': notas
    }
    
    print(f"[Meta AI Plugin] Processing lead for {nombre} ({telefono})...")
    cid = db.save_contacto(contacto_data)
    
    if cid:
        # Fire Event Hook to notify other decoupled modules/plugins
        fire_hook('on_lead_received', cid, contacto_data)
        return jsonify({'status': 'success', 'message': 'Lead guardado', 'id': cid}), 201
    else:
        return jsonify({'status': 'error', 'message': 'Error al guardar el lead'}), 500


@meta_ai_bp.route('/crm/meta_ai/panel', methods=['GET', 'POST'])
@login_required
@privilege_required('menu_item', 'meta_ai')
def panel():
    """Agent's ClaudIA Chatbot Configuration Panel."""
    is_solo_agent = not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza'

    if is_solo_agent and request.method == 'POST':
        flash("Los agentes sueltos no pueden modificar la configuración de Mi ClaudIA.", "warning")
        return redirect(url_for('meta_ai.panel'))

    username = current_user.usuario
    
    # Defaults in case Node API is offline
    config_data = {
        "system": {"botName": f"ClaudIA ({username})", "openMode": False, "strangersOnly": True, "humanDelay": {"min": 4, "max": 7}},
        "personality": {"tone": "profesional, empático", "globalGreeting": "Hola", "initialQuestion": "¿En qué puedo ayudarte?", "baseInstructions": ""},
        "catalog": {"synonymRules": []},
        "paths": [
            {
                "id": "vender",
                "name": "Vender Propiedad",
                "description": "Cuando el cliente quiere vender, tasar o publicar su propiedad.",
                "instructions": "Primero presentate: ¡Hola! 👋 Soy ClaudIA, la asistente virtual de la inmobiliaria.\nSiguiente: Habla como rioplatense Argentina formal, presentate como ClaudIA, la asistente virtual.\nTu objetivo es recolectar: 1) Si ya estuvo publicada en el pasado, 2) Si la decisión de venta está firme, 3) Si tiene escritura o es con boleto, 4) Si quiere vender para comprar otra cosa, 5) Plazos de venta. 6) cuantos titulares tiene la propiedad. Una pregunta a la vez, estilo rioplatense. \nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando",
                "steps": "Primero presentate: ¡Hola! 👋 Soy ClaudIA, la asistente virtual de la inmobiliaria.\nSiguiente: Habla como rioplatense Argentina formal, presentate como ClaudIA, la asistente virtual.\nTu objetivo es recolectar: 1) Si ya estuvo publicada en el pasado, 2) Si la decisión de venta está firme, 3) Si tiene escritura o es con boleto, 4) Si quiere vender para comprar otra cosa, 5) Plazos de venta. 6) cuantos titulares tiene la propiedad. Una pregunta a la vez, estilo rioplatense. \nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando"
            },
            {
                "id": "comprar",
                "name": "Comprar / Ver Propiedades",
                "description": "Cuando el cliente quiere ver casas publicadas para comprar o quiere más información sobre una propiedad",
                "instructions": "IMPORTANTE: Si sabes qué propiedad es, es obligatorio que el link de Zonaprop o Mercadolibre esté escrito textualmente en tu primer párrafo y saludar al mismo tiempo avisando que eres ClaudIA, la asistente virtual del asesor inmobiliario.\nSino sabemos cual es preguntamos algún dato para poder ubicarla. Si no podemos ubicarla le mostramos lo mas parecido a la que pide. No mencionar que tenemos propiedades en otros barrios o zonas.\n\nNunca ofrecer casas o departamentos o ph o lotes en zonas o lugares que no están en nuestro catálogo.\n\nAl terminar debes preguntarle si quiere visitar la propiedad que eligió y si quiere debes iniciar un cuestionario de precalificación:\n1. Si conoce la zona (si no la conoce le recomendamos que lo haga antes de ver la casa para estar seguros que la zona es la correcta) \n2. Si ya vendió su propiedad o si cuenta con la capacidad de hacer una oferta en el momento de la visita (queremos respetar que el propietario necesita vender y que la casa debe ser mostrada solo a personas que estén listas para hacer una oferta en el momento, a pedido del propietario).\nImportante: Si no vendió hay que preguntarle si le gustaría que nosotros le ayudemos a vender su propiedad. \nSi acepta, hay que preguntarle esto, una pregunta a la vez estilo rioplatense:\nA) Si su propiedad ya estuvo publicada, \nB) Si la decisión de venta está firme, \nC) Si tiene escritura o boleto\nD) Plazos de venta. \nE) cuantos titulares tiene la propiedad. \nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando",
                "steps": "IMPORTANTE: Si sabes qué propiedad es, es obligatorio que el link de Zonaprop o Mercadolibre esté escrito textualmente en tu primer párrafo y saludar al mismo tiempo avisando que eres ClaudIA, la asistente virtual del asesor inmobiliario.\nSino sabemos cual es preguntamos algún dato para poder ubicarla. Si no podemos ubicarla le mostramos lo mas parecido a la que pide. No mencionar que tenemos propiedades en otros barrios o zonas.\n\nNunca ofrecer casas o departamentos o ph o lotes en zonas o lugares que no están en nuestro catálogo.\n\nAl terminar debes preguntarle si quiere visitar la propiedad que eligió y si quiere debes iniciar un cuestionario de precalificación:\n1. Si conoce la zona (si no la conoce le recomendamos que lo haga antes de ver la casa para estar seguros que la zona es la correcta) \n2. Si ya vendió su propiedad o si cuenta con la capacidad de hacer una oferta en el momento de la visita (queremos respetar que el propietario necesita vender y que la casa debe ser mostrada solo a personas que estén listas para hacer una oferta en el momento, a pedido del propietario).\nImportante: Si no vendió hay que preguntarle si le gustaría que nosotros le ayudemos a vender su propiedad. \nSi acepta, hay que preguntarle esto, una pregunta a la vez estilo rioplatense:\nA) Si su propiedad ya estuvo publicada, \nB) Si la decisión de venta está firme, \nC) Si tiene escritura o boleto\nD) Plazos de venta. \nE) cuantos titulares tiene la propiedad. \nUna vez terminado todo esto, le agradecemos al cliente y le avisamos que un asesor se contactará a la brevedad.\nIMPORTANTE: Si el cliente se despide o dice algo como \"ok\" o \"gracias\", decimos de nada amigablemente y luego no hay que seguir conversando",
                "trigger": "Cuando el cliente quiere ver casas publicadas para comprar o quiere más información sobre una propiedad"
            },
            {
                "id": "hablarasesor",
                "name": "Hablar con Asesor",
                "description": "Cuando una persona pide hablar directamente con el asesor inmobiliario",
                "instructions": "Habla como rioplatense Argentina formal.\nClaudIA debe despedirse amablemente y avisar que un asesor se sumará al chat",
                "steps": "Habla como rioplatense Argentina formal.\nClaudIA debe despedirse amablemente y avisar que un asesor se sumará al chat",
                "trigger": "Cuando una persona pide hablar directamente con el asesor inmobiliario"
            }
        ],
        "credentials": {"groqApiKey": "", "adminPhone": "", "metaToken": "", "metaVerifyToken": "", "licenseKey": ""}
    }

    if request.method == 'POST':
        # Gather posted configuration
        import json
        
        # Parse paths, synonyms and catalog items from forms (sent as JSON strings)
        paths_json = request.form.get('paths_json', '[]')
        synonyms_json = request.form.get('synonyms_json', '[]')
        catalog_items_json = request.form.get('catalog_items_json', '[]')
        
        try:
            paths = json.loads(paths_json)
        except Exception:
            paths = []
            
        try:
            synonyms = json.loads(synonyms_json)
        except Exception:
            synonyms = []

        try:
            catalog_items = json.loads(catalog_items_json)
        except Exception:
            catalog_items = []

        updated_config = {
            "system": {
                "botName": request.form.get('botName'),
                "openMode": request.form.get('openMode') == '1',
                "strangersOnly": request.form.get('strangersOnly') == '1',
                "onlyGreet": request.form.get('onlyGreet') == '1',
                "ignoreAudio": request.form.get('ignoreAudio') == '1',
                "humanDelay": {
                    "min": int(request.form.get('delayMin', 4)),
                    "max": int(request.form.get('delayMax', 7))
                }
            },
            "personality": {
                "tone": request.form.get('tone'),
                "globalGreeting": request.form.get('globalGreeting'),
                "initialQuestion": request.form.get('initialQuestion'),
                "baseInstructions": request.form.get('baseInstructions')
            },
            "catalog": {
                "schema": [
                    { "id": "id", "label": "ID", "type": "id" },
                    { "id": "nombre", "label": "Propiedad", "type": "text", "searchable": True },
                    { "id": "precio", "label": "Precio", "type": "text", "searchable": False },
                    { "id": "descripcion", "label": "Descripción", "type": "text", "searchable": True },
                    { "id": "link", "label": "Enlace Web", "type": "url", "searchable": False }
                ],
                "items": catalog_items,
                "synonymRules": synonyms
            },
            "paths": paths,
            "credentials": {
                "groqApiKey": request.form.get('groqApiKey'),
                "adminPhone": request.form.get('adminPhone'),
                "metaToken": request.form.get('metaToken'),
                "metaVerifyToken": request.form.get('metaVerifyToken'),
                "licenseKey": request.form.get('licenseKey'),
                "crmWebhookUrl": request.url_root + "api/leads/meta",
                "crmWebhookToken": db.get_config('meta_ai_webhook_token', 'crm_secure_webhook_token'),
                "crmUsuarioAsignado": username,
                "crmEnabled": True
            }
        }
        
        # Save locally in user-scoped DB
        db.set_config('meta_ai_config', json.dumps(updated_config))
        
        try:
            r = requests.post(f"{NODE_BOT_API}/config/{username}", json=updated_config, timeout=5)
            if r.status_code == 200:
                flash("Configuración de tu ClaudIA guardada correctamente.", "success")
            else:
                flash(f"Configuración guardada en CRM. Aviso de motor Node.js: {r.json().get('error', 'Sin respuesta')}", "info")
        except Exception as e:
            flash("Configuración de tu ClaudIA guardada correctamente en el CRM.", "success")
            
        return redirect(url_for('meta_ai.panel'))

    # Load configuration: strictly per-user
    import json
    user_saved_json = db.get_config('meta_ai_config')
    if user_saved_json:
        try:
            config_data = json.loads(user_saved_json)
        except Exception:
            pass
    elif current_user.usuario == 'GermanMazza':
        # SuperAdmin initial load from Node API if available
        try:
            r = requests.get(f"{NODE_BOT_API}/config/{username}", timeout=3)
            if r.status_code == 200:
                node_data = r.json()
                if isinstance(node_data, dict) and 'credentials' in node_data:
                    config_data = node_data
                    db.set_config('meta_ai_config', json.dumps(config_data))
        except Exception:
            pass

    return render_template('meta_ai_panel.html', config=config_data, username=username, is_solo_agent=is_solo_agent)


@meta_ai_bp.route('/crm/meta_ai/status', methods=['GET', 'POST'])
@login_required
def status():
    """Proxies status checks and controls for WhatsApp Baileys connection."""
    username = current_user.usuario
    action = request.args.get('action')

    if request.method == 'POST' or action:
        # Trigger start/logout actions
        action_type = request.form.get('action') or action
        try:
            if action_type == 'start':
                r = requests.post(f"{NODE_BOT_API}/whatsapp/{username}/start", timeout=5)
            elif action_type == 'logout':
                r = requests.post(f"{NODE_BOT_API}/whatsapp/{username}/logout", timeout=5)
            
            if r.status_code == 200:
                return jsonify(r.json())
            return jsonify({'error': 'Error en la respuesta del motor'}), r.status_code
        except Exception as e:
            return jsonify({'error': f'Motor offline: {e}'}), 503

    # Simply query status or QR
    try:
        r = requests.get(f"{NODE_BOT_API}/whatsapp/{username}/qr", timeout=3)
        if r.status_code == 200:
            return jsonify(r.json())
        return jsonify({'status': 'disconnected'})
    except Exception as e:
        return jsonify({'status': 'disconnected', 'error': 'Motor offline'})


@meta_ai_bp.route('/crm/meta_ai/save_partial', methods=['POST'])
@login_required
def save_partial():
    """AJAX endpoint: merge-save a partial config without losing other sections."""
    import json
    username = current_user.usuario
    partial = request.json or {}

    # Load current full config from Node
    try:
        r = requests.get(f"{NODE_BOT_API}/config/{username}", timeout=3)
        current_config = r.json() if r.status_code == 200 else {}
    except Exception:
        current_config = {}

    # Deep merge: only overwrite keys present in partial
    for section_key in ('system', 'personality', 'credentials', 'catalog'):
        if section_key in partial:
            if section_key not in current_config:
                current_config[section_key] = {}
            current_config[section_key].update(partial[section_key])

    # Top-level arrays overwrite entirely when present
    if 'paths' in partial:
        current_config['paths'] = partial['paths']

    # Ensure catalog.synonymRules is preserved/updated
    if 'catalog' in partial and 'synonymRules' in partial['catalog']:
        if 'catalog' not in current_config:
            current_config['catalog'] = {}
        current_config['catalog']['synonymRules'] = partial['catalog']['synonymRules']

    try:
        r = requests.post(f"{NODE_BOT_API}/config/{username}", json=current_config, timeout=5)
        if r.status_code == 200:
            return jsonify({'status': 'ok', 'message': 'Guardado parcial exitoso.'})
        return jsonify({'status': 'error', 'message': 'Error del servidor Node.js'}), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Motor offline: {e}'}), 503


@meta_ai_bp.route('/crm/meta_ai/simulate/reset', methods=['POST'])
@login_required
def simulate_reset():
    username = current_user.usuario
    try:
        r = requests.post(f"{NODE_BOT_API}/config/{username}/simulate/reset", json=request.json or {}, timeout=5)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@meta_ai_bp.route('/crm/meta_ai/simulate/message', methods=['POST'])
@login_required
def simulate_message():
    username = current_user.usuario
    try:
        r = requests.post(f"{NODE_BOT_API}/config/{username}/simulate/message", json=request.json or {}, timeout=15)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({'error': str(e)}), 503


@meta_ai_bp.route('/crm/meta_ai/audit_logs', methods=['GET'])
@login_required
def audit_logs():
    """Proxy requests to the Node.js Chatbot microservice /audit-logs endpoint."""
    username = current_user.usuario
    try:
        r = requests.get(f"{NODE_BOT_API}/config/{username}/audit-logs", timeout=5)
        if r.status_code == 200:
            return jsonify(r.json())
        return jsonify({'error': 'Error en la respuesta del motor'}), r.status_code
    except Exception as e:
        return jsonify({'error': f'Motor offline: {e}'}), 503


@meta_ai_bp.route('/crm/meta_ai/simulate/concurrency', methods=['POST'])
@login_required
def simulate_concurrency():
    """Proxy requests to run the test_concurrency.js suite in Node."""
    username = current_user.usuario
    try:
        r = requests.post(f"{NODE_BOT_API}/config/{username}/simulate/concurrency", json=request.json or {}, timeout=60)
        if r.status_code == 200:
            return jsonify(r.json())
        return jsonify({'error': 'Error en la ejecución de la suite de pruebas'}), r.status_code
    except Exception as e:
        return jsonify({'error': f'Motor offline: {e}'}), 503
