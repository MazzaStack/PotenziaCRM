import os
import requests
from flask import Blueprint, request, jsonify, render_template, Response, stream_with_context
from flask_login import login_required, current_user
from database import db

modelado_3d_bp = Blueprint('modelado_3d', __name__, template_folder='templates')

# Backend Configuration (Localhost for dev, commercial VPN IP in production)
def get_user_backend_url():
    """Helper to retrieve the 3D Engine URL dynamically per-user."""
    fallback = os.environ.get('BACKEND_3D_ENGINE_URL', 'http://localhost:5001')
    try:
        # Fetch per-user URL from database configuration (automatically scoped because it's in USER_SCOPED_KEYS)
        url = db.get_config('modelado_3d_backend_url')
        if url:
            return url.strip().rstrip('/')
    except Exception as e:
        print(f"Error reading modelado_3d_backend_url: {e}")
    return fallback

def get_db_properties():
    """Helper to fetch properties from the CRM database to link models to actual homes."""
    # We can fetch simple properties to let the UI choose which house they are generating for
    try:
        props = db.get_propiedades(limit=100)
        return props
    except Exception as e:
        print(f"Error fetching properties: {e}")
        return []

@modelado_3d_bp.route('/admin/modelado_3d')
@login_required
def index():
    """
    Renders the main dashboard for 3D modeling where users can upload videos,
    view training tasks, clean splats with SuperSplat, and preview 3D tours.
    """
    # Fetch properties list to bind the 3D model in the dropdown list
    properties = get_db_properties()
    return render_template('modelado_3d.html', properties=properties)

@modelado_3d_bp.route('/modelado_3d/api/settings', methods=['GET'])
@login_required
def get_settings():
    """Get current user's 3D engine URL."""
    return jsonify({"backend_url": get_user_backend_url()})

@modelado_3d_bp.route('/modelado_3d/api/settings', methods=['POST'])
@login_required
def save_settings():
    """Save current user's 3D engine URL."""
    data = request.json or {}
    url = data.get('backend_url', '').strip()
    if not url:
        return jsonify({"error": "La dirección del backend no puede estar vacía"}), 400
    try:
        db.set_config('modelado_3d_backend_url', url)
        return jsonify({"success": True, "message": "Configuración guardada correctamente"})
    except Exception as e:
        return jsonify({"error": f"Error al guardar la configuración: {str(e)}"}), 500

@modelado_3d_bp.route('/modelado_3d/api/settings/test', methods=['POST'])
@login_required
def test_settings_connection():
    """Pings the user-supplied (or saved) backend URL to check connection."""
    data = request.json or {}
    url = data.get('backend_url', '').strip()
    if not url:
        url = get_user_backend_url()
    else:
        url = url.rstrip('/')
    try:
        r = requests.get(f"{url}/api/projects", timeout=4)
        if r.status_code == 200:
            return jsonify({"status": "online", "message": "Conexión exitosa con el motor 3D."})
        else:
            return jsonify({"status": "error", "message": f"El servidor respondió con código {r.status_code}."})
    except requests.exceptions.RequestException as e:
        return jsonify({"status": "offline", "message": f"No se pudo conectar al motor 3D: {str(e)}"})

@modelado_3d_bp.route('/modelado_3d/api/projects', methods=['GET'])
@login_required
def get_projects():
    """Proxy to list all 3D projects from the creation engine."""
    engine_url = get_user_backend_url()
    try:
        r = requests.get(f"{engine_url}/api/projects", timeout=5)
        return jsonify(r.json()), r.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"No se pudo conectar al motor de creación 3D ({engine_url}): {str(e)}"}), 503

@modelado_3d_bp.route('/modelado_3d/api/projects', methods=['POST'])
@login_required
def upload_project():
    """Proxy video file uploads to the backend creation engine."""
    if 'video' not in request.files:
        return jsonify({"error": "No se recibió ningún video"}), 400
        
    video_file = request.files['video']
    name = request.form.get('name', '')
    property_id = request.form.get('property_id', '')
    
    files = {
        'video': (video_file.filename, video_file.read(), video_file.content_type)
    }
    data = {
        'name': name,
        'property_id': property_id
    }
    
    engine_url = get_user_backend_url()
    try:
        r = requests.post(f"{engine_url}/api/projects", files=files, data=data, timeout=60)
        return jsonify(r.json()), r.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Error al enviar el video al motor 3D ({engine_url}): {str(e)}"}), 503

@modelado_3d_bp.route('/modelado_3d/api/projects/<project_id>/train', methods=['POST'])
@login_required
def train_project(project_id):
    """Proxy training triggers to the backend."""
    # Defaults to False for actual training
    simulate = request.json.get('simulate', False) if request.json else False
    engine_url = get_user_backend_url()
    try:
        r = requests.post(
            f"{engine_url}/api/projects/{project_id}/train",
            json={"simulate": simulate},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        return jsonify(r.json()), r.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Error al iniciar entrenamiento en el motor 3D ({engine_url}): {str(e)}"}), 503

@modelado_3d_bp.route('/modelado_3d/api/projects/<project_id>/status', methods=['GET'])
@login_required
def get_project_status(project_id):
    """Proxy progress checking."""
    engine_url = get_user_backend_url()
    try:
        r = requests.get(f"{engine_url}/api/projects/{project_id}/status", timeout=5)
        return jsonify(r.json()), r.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Error al conectar con el motor 3D ({engine_url}): {str(e)}"}), 503

@modelado_3d_bp.route('/modelado_3d/api/projects/<project_id>', methods=['DELETE'])
@login_required
def delete_project(project_id):
    """Proxy deletion requests."""
    engine_url = get_user_backend_url()
    try:
        r = requests.delete(f"{engine_url}/api/projects/{project_id}", timeout=5)
        return jsonify(r.json()), r.status_code
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Error al conectar con el motor 3D ({engine_url}): {str(e)}"}), 503

@modelado_3d_bp.route('/modelado_3d/model/<project_id>/<filename>', methods=['GET'])
@login_required
def download_model(project_id, filename):
    """
    Proxies and streams model files (.ply or .spz) from the creation engine
    directly to the client, preventing CORS issues.
    """
    if filename not in ['model.ply', 'model.spz']:
        return jsonify({"error": "Nombre de archivo no permitido"}), 400
        
    engine_url = get_user_backend_url()
    try:
        url = f"{engine_url}/api/projects/{project_id}/model/{filename}"
        r = requests.get(url, stream=True, timeout=10)
        
        if r.status_code != 200:
            return jsonify({"error": "El archivo del modelo 3D no está disponible"}), r.status_code
            
        def generate():
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
                    
        headers = {
            'Content-Type': r.headers.get('Content-Type', 'application/octet-stream'),
            'Content-Disposition': f'attachment; filename="{filename}"'
        }
        
        return Response(stream_with_context(generate()), status=r.status_code, headers=headers)
        
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Error al descargar el modelo desde el motor 3D ({engine_url}): {str(e)}"}), 503
