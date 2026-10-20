"""
CRM Module for User Authentication, Administration, and Files Sharing
"""
import os
import io
import base64
import shutil
from functools import wraps
from flask import request, redirect, url_for, render_template, flash, Blueprint, current_app, jsonify
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import pyotp
import qrcode
from database import db
from database.db_audit import registrar_auditoria
from lib.security_notifier import notify_admin_login_async, record_failed_login_and_alert_async, clear_failed_attempts
from lib.limiter import limiter

# Blueprint definition
auth_bp = Blueprint('auth', __name__)

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

def role_required(roles):
    """Decorator to restrict access to specific roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.rol not in roles:
                flash("No tenés permiso para acceder a esta sección.", "warning")
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    return role_required(['admin'])(f)

def broker_required(f):
    return role_required(['admin', 'broker'])(f)

def finanzas_required(f):
    return role_required(['admin', 'broker', 'finanzas'])(f)

def superadmin_required(f):
    """Decorator to restrict access strictly to the SuperAdmin GermanMazza."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.usuario != 'GermanMazza':
            flash("Acceso restringido únicamente al SuperAdmin Germán.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def privilege_required(tipo_objeto, objeto_id):
    """Decorator to check user privilege, bypassing for GermanMazza."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.usuario == 'GermanMazza':
                return f(*args, **kwargs)
            if db.check_user_privilege(current_user, tipo_objeto, objeto_id):
                return f(*args, **kwargs)
            flash("Acceso restringido. No tenés permisos suficientes para esta sección.", "danger")
            return redirect(url_for('index'))
        return decorated_function
    return decorator

# --- ROUTES ---

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("15 per minute", methods=["POST"])
def login():
    ip = request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    ua = request.headers.get('User-Agent', '')

    if request.method == 'POST':
        usuario = (request.form.get('usuario') or '').strip()
        password = request.form.get('password') or ''
        totp_code = (request.form.get('totp_code') or '').strip()
        
        user_data = db.get_usuario(usuario)
        if user_data and check_password_hash(user_data['password_hash'], password):
            # ── Chequeo de 2FA (TOTP) ──────────────────────────
            if user_data.get('totp_enabled') == 1:
                secret = user_data.get('totp_secret')
                if not totp_code:
                    # Credenciales válidas, solicitar código 2FA
                    return render_template('login.html', require_2fa=True, usuario=usuario, password_temp=password)
                
                # Validar código 2FA
                totp = pyotp.TOTP(secret)
                if not totp.verify(totp_code, valid_window=1):
                    record_failed_login_and_alert_async(usuario, ip=ip, user_agent=ua)
                    flash('Código de autenticación 2FA incorrecto o expirado.', 'danger')
                    return render_template('login.html', require_2fa=True, usuario=usuario, password_temp=password)
            
            # Login exitoso: limpiar contador de fallos
            clear_failed_attempts(usuario)
            
            user_obj = User(
                user_data['id'], 
                user_data['usuario'], 
                user_data['nombre_display'], 
                user_data['rol'], 
                user_data['db_file'],
                user_data.get('oficina_id'),
                user_data.get('oficina_nombre'),
                user_data.get('oficina_slug')
            )
            login_user(user_obj, remember=True)
            
            # Notificación asíncrona a WhatsApp y Audit Trail para Administradores
            if user_data.get('rol') == 'admin' or user_data.get('usuario') == 'GermanMazza':
                notify_admin_login_async(user_data, ip=ip, user_agent=ua)
            
            registrar_auditoria("LOGIN_EXITOSO", f"Usuario {usuario} ingresó correctamente", 
                                usuario_id=user_data['id'], usuario_nombre=usuario, oficina_id=user_data.get('oficina_id'), ip=ip, user_agent=ua)
            
            next_page = request.args.get('next')
            return redirect(next_page if next_page and next_page.startswith('/') else url_for('index'))
        else:
            # Registrar intento fallido y alertar si aplica (filtro anti-spam incluido)
            record_failed_login_and_alert_async(usuario, ip=ip, user_agent=ua)
            flash('Usuario o contraseña incorrectos', 'danger')
            
    return render_template('login.html')

@auth_bp.route('/logout')
@login_required
def logout():
    registrar_auditoria("LOGOUT", f"Usuario {current_user.usuario} cerró sesión")
    logout_user()
    return redirect(url_for('auth.login'))

# ── GESTIÓN DE 2FA (PERFIL DE USUARIO) ──────────────────────────────────────

@auth_bp.route('/perfil/2fa/setup', methods=['POST'])
@login_required
def perfil_2fa_setup():
    """Genera un nuevo secreto TOTP y el código QR para configurar en Google Authenticator."""
    secret = pyotp.random_base32()
    db.set_user_totp_secret(current_user.id, secret)
    
    totp = pyotp.TOTP(secret)
    app_name = "Ferrari CRM"
    provisioning_uri = totp.provisioning_uri(name=current_user.usuario, issuer_name=app_name)
    
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    
    return jsonify({
        'status': 'ok',
        'secret': secret,
        'qr_base64': f"data:image/png;base64,{qr_base64}"
    })

@auth_bp.route('/perfil/2fa/verificar', methods=['POST'])
@login_required
def perfil_2fa_verificar():
    """Verifica el código de 6 dígitos para habilitar formalmente el 2FA."""
    code = (request.form.get('code') or (request.json.get('code') if request.is_json else '') or '').strip()
    user_info = db.get_user_totp_info(current_user.id)
    
    if not user_info or not user_info.get('totp_secret'):
        return jsonify({'status': 'error', 'message': 'No hay configuración 2FA pendiente.'}), 400
        
    totp = pyotp.TOTP(user_info['totp_secret'])
    if totp.verify(code, valid_window=1):
        db.enable_user_2fa(current_user.id)
        registrar_auditoria("2FA_HABILITADO", f"Usuario {current_user.usuario} activó el 2FA")
        return jsonify({'status': 'ok', 'message': '2FA activado con éxito. Tu cuenta ahora está protegida.'})
    else:
        return jsonify({'status': 'error', 'message': 'Código incorrecto o expirado. Verificá la hora de tu celular e intentá nuevamente.'}), 400

@auth_bp.route('/perfil/2fa/desactivar', methods=['POST'])
@login_required
def perfil_2fa_desactivar():
    """Desactiva el 2FA del usuario actual."""
    db.disable_user_2fa(current_user.id)
    registrar_auditoria("2FA_DESHABILITADO", f"Usuario {current_user.usuario} desactivó el 2FA")
    return jsonify({'status': 'ok', 'message': 'Doble factor de autenticación desactivado.'})

@auth_bp.route('/admin/usuarios')
@privilege_required('menu_item', 'gestion_usuarios')
def admin_usuarios():
    """Panel de gestión de usuarios (SuperAdmin y Admins de Oficina)."""
    oficinas = db.get_all_oficinas()
    if current_user.usuario == 'GermanMazza':
        usuarios = db.get_all_usuarios()
    elif current_user.rol == 'admin' and getattr(current_user, 'oficina_id', None):
        usuarios = db.get_all_usuarios(oficina_id=current_user.oficina_id)
    else:
        usuarios = [db.get_usuario_by_id(current_user.id)]
    return render_template('admin_usuarios.html', usuarios=usuarios, oficinas=oficinas)

@auth_bp.route('/admin/usuarios/crear', methods=['POST'])
@privilege_required('accion', 'crear_usuario')
def crear_usuario():
    """Crea un nuevo usuario y su base de datos privada."""
    usuario = request.form.get('usuario')
    password = request.form.get('password')
    nombre = request.form.get('nombre_display')
    rol = request.form.get('rol', 'agente')
    raw_oficina_id = request.form.get('oficina_id')
    
    if current_user.usuario != 'GermanMazza' and getattr(current_user, 'oficina_id', None):
        oficina_id = current_user.oficina_id
    else:
        try:
            oficina_id = int(raw_oficina_id) if raw_oficina_id and raw_oficina_id not in ('', 'none', 'suelto') else None
        except (ValueError, TypeError):
            oficina_id = None
    
    if not usuario or not password:
        flash("Usuario y contraseña son obligatorios", "error")
        return redirect(url_for('auth.admin_usuarios'))
        
    # Sanitizar contra Path Traversal
    import re
    if not re.match(r'^[a-zA-Z0-9_\-]+$', usuario):
        flash("El usuario solo puede contener letras, números, guiones y guiones bajos.", "danger")
        return redirect(url_for('auth.admin_usuarios'))
        
    # Verificar si existe
    if db.get_usuario(usuario):
        flash("El nombre de usuario ya existe", "error")
        return redirect(url_for('auth.admin_usuarios'))
        
    db_file = f"{usuario.lower().replace(' ', '_')}.db"
    
    from werkzeug.security import generate_password_hash
    pw_hash = generate_password_hash(password)
    
    # Insert in Master
    user_id = db.insert_usuario(usuario, pw_hash, nombre, rol, db_file, oficina_id=oficina_id)
    
    # Initialize User's private DB
    db.init_user_db(db_file)
    
    flash(f"Usuario {usuario} creado con éxito y base de datos inicializada.", "success")
    return redirect(url_for('auth.admin_usuarios'))

@auth_bp.route('/admin/usuarios/editar/<int:uid>', methods=['POST'])
@privilege_required('accion', 'editar_usuario')
def editar_usuario(uid):
    """Actualiza los datos de un usuario."""
    nombre = request.form.get('nombre_display')
    rol = request.form.get('rol')
    password = request.form.get('password')
    raw_oficina_id = request.form.get('oficina_id')
    
    if current_user.usuario != 'GermanMazza' and getattr(current_user, 'oficina_id', None):
        oficina_id = current_user.oficina_id
    else:
        try:
            oficina_id = int(raw_oficina_id) if raw_oficina_id and raw_oficina_id not in ('', 'none', 'suelto') else None
        except (ValueError, TypeError):
            oficina_id = None
    
    target_user = db.get_usuario_by_id(uid)
    if uid == 1 or (target_user and target_user.get('usuario') == 'GermanMazza'):
        if rol != 'admin':
            flash("No podés degradar el rol del SuperAdmin GermanMazza.", "danger")
            return redirect(url_for('auth.admin_usuarios'))
            
    pw_hash = None
    if password:
        from werkzeug.security import generate_password_hash
        pw_hash = generate_password_hash(password)
        
    db.update_usuario(uid, nombre, rol, pw_hash, oficina_id=oficina_id, update_oficina=True)
    flash(f"Usuario actualizado correctamente.", "success")
    return redirect(url_for('auth.admin_usuarios'))

@auth_bp.route('/admin/usuarios/borrar/<int:uid>', methods=['POST'])
@privilege_required('accion', 'borrar_usuario')
def borrar_usuario(uid):
    """Elimina un usuario y limpia su carpeta de archivos."""
    target_user = db.get_usuario_by_id(uid)
    if uid == 1 or (target_user and target_user.get('usuario') == 'GermanMazza'):
        flash("La cuenta del SuperAdmin GermanMazza es in-borrable.", "danger")
        return redirect(url_for('auth.admin_usuarios'))
        
    if uid == current_user.id:
        flash("No podés borrarte a vos mismo.", "danger")
    else:
        usuario = db.delete_usuario(uid)
        if usuario:
            # Limpiar carpeta física
            user_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'archivos_agentes', usuario)
            if os.path.exists(user_dir):
                shutil.rmtree(user_dir)
        flash("Usuario y sus datos eliminados correctamente.", "success")
    return redirect(url_for('auth.admin_usuarios'))

# ==========================================
# GESTIÓN DE OFICINAS (SUPERADMIN ONLY)
# ==========================================

@auth_bp.route('/admin/oficinas')
@superadmin_required
def admin_oficinas():
    """Panel centralizado de Gestión de Oficinas (Solo SuperAdmin)."""
    oficinas = db.get_all_oficinas()
    usuarios_sueltos = db.get_all_usuarios(oficina_id='sueltos')
    return render_template('admin_oficinas.html', oficinas=oficinas, usuarios_sueltos=usuarios_sueltos)

@auth_bp.route('/admin/oficinas/crear', methods=['POST'])
@superadmin_required
def crear_oficina():
    """Crea una nueva oficina en el sistema."""
    import re
    nombre = request.form.get('nombre', '').strip()
    slug = request.form.get('slug', '').strip().lower()
    direccion = request.form.get('direccion', '').strip()
    telefono = request.form.get('telefono', '').strip()
    logo_url = request.form.get('logo_url', '').strip()
    color_primario = request.form.get('color_primario', '#0d6efd').strip()
    color_secundario = request.form.get('color_secundario', '#1a1a2e').strip()
    es_portal = 1 if request.form.get('es_portal_clientes') == '1' else 0
    activa = 1 if request.form.get('activa', '1') == '1' else 0

    if not nombre:
        flash("El nombre de la oficina es obligatorio.", "danger")
        return redirect(url_for('auth.admin_oficinas'))

    if not slug:
        slug = re.sub(r'[^a-z0-9]+', '-', nombre.lower()).strip('-')

    try:
        oid = db.insert_oficina(
            nombre=nombre,
            slug=slug,
            direccion=direccion,
            telefono=telefono,
            logo_url=logo_url,
            color_primario=color_primario,
            color_secundario=color_secundario,
            es_portal_clientes=es_portal,
            activa=activa
        )
        flash(f"Oficina '{nombre}' creada exitosamente.", "success")
    except Exception as e:
        flash(f"Error al crear oficina: {e}", "danger")

    return redirect(url_for('auth.admin_oficinas'))

@auth_bp.route('/admin/oficinas/editar/<int:oid>', methods=['POST'])
@superadmin_required
def editar_oficina(oid):
    """Actualiza la configuración de una oficina."""
    import re
    nombre = request.form.get('nombre', '').strip()
    slug = request.form.get('slug', '').strip().lower()
    direccion = request.form.get('direccion', '').strip()
    telefono = request.form.get('telefono', '').strip()
    logo_url = request.form.get('logo_url', '').strip()
    color_primario = request.form.get('color_primario', '#0d6efd').strip()
    color_secundario = request.form.get('color_secundario', '#1a1a2e').strip()
    es_portal = 1 if request.form.get('es_portal_clientes') == '1' else 0
    activa = 1 if request.form.get('activa', '1') == '1' else 0

    if not nombre:
        flash("El nombre de la oficina es obligatorio.", "danger")
        return redirect(url_for('auth.admin_oficinas'))

    if not slug:
        slug = re.sub(r'[^a-z0-9]+', '-', nombre.lower()).strip('-')

    try:
        db.update_oficina(
            oid=oid,
            nombre=nombre,
            slug=slug,
            direccion=direccion,
            telefono=telefono,
            logo_url=logo_url,
            color_primario=color_primario,
            color_secundario=color_secundario,
            es_portal_clientes=es_portal,
            activa=activa
        )
        flash(f"Oficina '{nombre}' actualizada correctamente.", "success")
    except Exception as e:
        flash(f"Error al actualizar oficina: {e}", "danger")

    return redirect(url_for('auth.admin_oficinas'))

@auth_bp.route('/admin/oficinas/set_portal/<int:oid>', methods=['POST'])
@superadmin_required
def set_portal_oficina(oid):
    """Establece qué oficina es la ÚNICA que tiene el Portal de Clientes activo."""
    try:
        db.set_portal_clientes_oficina(oid)
        ofi = db.get_oficina_by_id(oid)
        nombre = ofi['nombre'] if ofi else f"ID {oid}"
        flash(f"El Portal de Clientes ha sido asignado exclusivamente a '{nombre}'.", "success")
    except Exception as e:
        flash(f"Error al asignar Portal de Clientes: {e}", "danger")

    return redirect(url_for('auth.admin_oficinas'))

@auth_bp.route('/admin/oficinas/borrar/<int:oid>', methods=['POST'])
@superadmin_required
def borrar_oficina(oid):
    """Elimina una oficina, pasando sus agentes a Agentes Sueltos."""
    if oid == 1:
        flash("La Oficina Principal por defecto no puede ser eliminada.", "danger")
        return redirect(url_for('auth.admin_oficinas'))

    try:
        db.delete_oficina(oid)
        flash("Oficina eliminada. Los agentes asociados han pasado a 'Agentes Sueltos'.", "info")
    except Exception as e:
        flash(f"Error al eliminar oficina: {e}", "danger")

    return redirect(url_for('auth.admin_oficinas'))

@auth_bp.route('/admin/archivos/asignar', methods=['POST'])
@privilege_required('accion', 'asignar_archivo')
def asignar_archivo():
    """Asignar un archivo a un usuario o a TODOS."""
    is_solo_agent = not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza'
    if is_solo_agent:
        flash("Los agentes sueltos no tienen permisos para asignar archivos.", "danger")
        return redirect(url_for('auth.archivos_asignados'))

    user_target = request.form.get('user_id') # Puede ser un ID o "todos"
    nombre_archivo = request.form.get('nombre_archivo')
    ruta_archivo = request.form.get('ruta_archivo')
    
    if not user_target or not nombre_archivo or not ruta_archivo:
        flash("Todos los campos son obligatorios", "error")
        return redirect(url_for('auth.archivos_asignados'))
    
    if user_target == 'todos':
        if current_user.usuario == 'GermanMazza':
            usuarios = db.get_all_usuarios()
        elif getattr(current_user, 'oficina_id', None):
            usuarios = db.get_all_usuarios(oficina_id=current_user.oficina_id)
        else:
            usuarios = []
            
        count = 0
        for u in usuarios:
            if u['rol'] == 'agente':
                db.asignar_archivo_a_usuario(nombre_archivo, ruta_archivo, u['id'], current_user.id)
                count += 1
        flash(f"Archivo asignado a {count} agentes.", "success")
    else:
        db.asignar_archivo_a_usuario(nombre_archivo, ruta_archivo, user_target, current_user.id)
        flash(f"Archivo '{nombre_archivo}' asignado correctamente.", "success")
        
    return redirect(url_for('auth.archivos_asignados'))

@auth_bp.route('/archivos_asignados')
@login_required
def archivos_asignados():
    """Listado de archivos asignados. Los agentes sueltos ven pantalla de bloqueo."""
    is_solo_agent = not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza'
    
    if is_solo_agent:
        return render_template('archivos_asignados.html', archivos=[], usuarios=[], is_solo_agent=True)

    if current_user.usuario == 'GermanMazza':
        archivos = db.get_archivos_usuario(None) 
        usuarios = db.get_all_usuarios()
        return render_template('archivos_asignados.html', archivos=archivos, usuarios=usuarios, is_solo_agent=False)
    elif current_user.rol in ['admin', 'broker', 'finanzas'] and getattr(current_user, 'oficina_id', None):
        archivos = db.get_archivos_usuario(oficina_id=current_user.oficina_id)
        usuarios = db.get_all_usuarios(oficina_id=current_user.oficina_id)
        return render_template('archivos_asignados.html', archivos=archivos, usuarios=usuarios, is_solo_agent=False)
    else:
        archivos = db.get_archivos_usuario(current_user.id)
        return render_template('archivos_asignados.html', archivos=archivos, usuarios=[], is_solo_agent=False)

@auth_bp.route('/archivos_asignados/borrar/<int:aid>', methods=['POST'])
@login_required
def borrar_archivo_asignado(aid):
    """Elimina un archivo asignado. Agentes pueden borrar los suyos."""
    is_solo_agent = not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza'
    if is_solo_agent:
        flash("No tenés permiso para operar con archivos.", "danger")
        return redirect(url_for('auth.archivos_asignados'))

    archivo = db.get_archivo_by_id(aid)
    if not archivo:
        flash("Archivo no encontrado.", "error")
        return redirect(url_for('auth.archivos_asignados'))
    
    if archivo['asignado_a'] == current_user.id or current_user.rol in ['admin', 'broker', 'finanzas']:
        path_to_delete = db.delete_archivo_asignado(aid)
        
        if path_to_delete and 'uploads' in path_to_delete:
            full_path = os.path.join(current_app.root_path, path_to_delete.lstrip('/'))
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except Exception as e:
                    print(f"Error eliminando archivo físico: {e}")
                    
        flash("Asignación eliminada correctamente.", "success")
    else:
        flash("No tenés permiso para borrar este archivo.", "danger")
    
    return redirect(url_for('auth.archivos_asignados'))

@auth_bp.route('/archivos_asignados/subir', methods=['POST'])
@login_required
def subir_archivo_personal():
    """Permite al agente subir sus propios archivos (Límite 5MB). Agentes sueltos bloqueados."""
    is_solo_agent = not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza'
    if is_solo_agent:
        flash("Los agentes sueltos no tienen permisos para subir archivos al servidor ni utilizar el sistema como gestor de archivos.", "danger")
        return redirect(url_for('auth.archivos_asignados'))

    if 'archivo' not in request.files:
        flash("No se seleccionó ningún archivo.", "warning")
        return redirect(url_for('auth.archivos_asignados'))
        
    file = request.files['archivo']
    if not file.filename:
        flash("Nombre de archivo no válido.", "error")
        return redirect(url_for('auth.archivos_asignados'))
        
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.pdf', '.txt', '.jpg', '.jpeg', '.png']:
        flash("Formato no permitido. Solo PDF, TXT, JPG/PNG.", "danger")
        return redirect(url_for('auth.archivos_asignados'))
        
    user_upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'archivos_agentes', current_user.usuario)
    os.makedirs(user_upload_dir, exist_ok=True)
    
    from werkzeug.utils import secure_filename
    import uuid
    fname = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
    save_path = os.path.join(user_upload_dir, fname)
    
    file.seek(0, os.SEEK_END)
    size = file.tell()
    if size > 5 * 1024 * 1024:
        flash("El archivo excede el límite de 5MB.", "danger")
        return redirect(url_for('auth.archivos_asignados'))
    file.seek(0)
    
    file.save(save_path)
    
    db_path = f"/static/uploads/archivos_agentes/{current_user.usuario}/{fname}"
    db.asignar_archivo_a_usuario(file.filename, db_path, current_user.id, current_user.id)
    
    flash("Archivo subido con éxito.", "success")
    return redirect(url_for('auth.archivos_asignados'))

@auth_bp.route('/archivos_asignados/abrir/<int:aid>')
@login_required
def abrir_archivo_asignado(aid):
    """Abre un archivo asignado o redirige si es un enlace."""
    archivo = db.get_archivo_by_id(aid)
    if not archivo:
        flash("No se encontró el archivo.", "error")
        return redirect(url_for('auth.archivos_asignados'))
        
    if archivo['asignado_a'] == current_user.id or current_user.rol == 'admin':
        ruta = archivo['ruta_archivo']
        
        if ruta.startswith(('http://', 'https://')):
            db.marcar_archivo_leido(aid)
            return redirect(ruta)
            
        full_local_path = os.path.join(current_app.root_path, ruta.lstrip('/'))
        if os.path.exists(full_local_path):
            try:
                os.startfile(full_local_path)
                db.marcar_archivo_leido(aid)
                flash(f"Abriendo {archivo['nombre_archivo']}...", "info")
            except Exception as e:
                flash(f"Error al abrir: {e}", "error")
        else:
            flash(f"No se encontró el archivo o no es un enlace válido: {ruta}", "warning")
    else:
        flash("No tenés permiso para abrir este archivo.", "danger")
        
    return redirect(url_for('auth.archivos_asignados'))

@auth_bp.route('/admin/privilegios', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_privilegios():
    """Manage dynamic visibility/privilege matrix (Admins y SuperAdmin)."""
    plugins = [
        {'id': 'captacion_outreach', 'nombre': 'Captación y Outreach (WhatsApp/Email)'},
        {'id': 'publicacion_placa', 'nombre': 'Publicación a Placa (PAP)'},
        {'id': 'finanzas', 'nombre': 'Módulo de Finanzas'},
        {'id': 'redes_sociales', 'nombre': 'Historias e IG'},
        {'id': 'meta_ai', 'nombre': 'Chatbot Meta AI'},
        {'id': 'tokko', 'nombre': 'Cartera Tokko Broker'},
        {'id': 'scraping_engine', 'nombre': 'Motor de Scraping Compartido'},
        {'id': 'lotes_excel', 'nombre': 'Visor de Lotes Excel'},
        {'id': 'asistente_ia', 'nombre': 'Asistente IA (Fidelización & Briefing)'}
    ]
    
    menu_items = [
        {'id': 'dashboard', 'nombre': 'Dashboard'},
        {'id': 'propiedades', 'nombre': 'Propiedades (Captación)'},
        {'id': 'comunicaciones', 'nombre': 'Seguimiento Auto (Mensajes)'},
        {'id': 'busquedas', 'nombre': 'Robots de Búsqueda'},
        {'id': 'crm_contactos', 'nombre': 'Contactos CRM'},
        {'id': 'tasador', 'nombre': 'Tasador Express'},
        {'id': 'seguimiento_prop', 'nombre': 'Seguimiento Prop'},
        {'id': 'archivos_asignados', 'nombre': 'Archivos Asignados'},
        {'id': 'finanzas_oficina', 'nombre': 'Finanzas Oficina'},
        {'id': 'libro_finanzas', 'nombre': 'Libro de Finanzas'},
        {'id': 'buscador_ventas', 'nombre': 'Buscador Ventas'},
        {'id': 'buscador_alquileres', 'nombre': 'Buscador Alquileres'},
        {'id': 'busquedas_clientes', 'nombre': 'Búsquedas de Clientes'},
        {'id': 'portales_temporales', 'nombre': 'Portales Temporales Live'},
        {'id': 'panel_fichas', 'nombre': 'Publi a Fichas (PAF)'},
        {'id': 'pap', 'nombre': 'Publicación a Placa (PAP)'},
        {'id': 'historias', 'nombre': 'Publicar Historias'},
        {'id': 'tokko_cartera', 'nombre': 'Cartera Tokko Broker'},
        {'id': 'tokko_mis_operaciones', 'nombre': 'Tokko - Mis Operaciones'},
        {'id': 'planificador', 'nombre': 'Planificador 10 Sem'},
        {'id': 'lotes_excel', 'nombre': 'Visor de Lotes Excel'},
        {'id': 'gestion_usuarios', 'nombre': 'Gestión Usuarios'},
        {'id': 'configuracion', 'nombre': 'Configuración'}
    ]
    
    actions = [
        {'id': 'crear_usuario', 'nombre': 'Crear Usuarios'},
        {'id': 'editar_usuario', 'nombre': 'Editar Usuarios'},
        {'id': 'borrar_usuario', 'nombre': 'Borrar Usuarios'},
        {'id': 'asignar_archivo', 'nombre': 'Asignar Archivos a Agentes'},
        {'id': 'cambiar_ruta_db', 'nombre': 'Cambiar Ruta Base de Datos'},
        {'id': 'conectar_whatsapp', 'nombre': 'Conectar WhatsApp'},
        {'id': 'publicar_historias_manualmente', 'nombre': 'Publicar Historias'},
        {'id': 'ejecutar_scraper', 'nombre': 'Ejecutar Scraper'},
        {'id': 'limpiar_inactivas', 'nombre': 'Limpiar Inactivas'},
        {'id': 'limpiar_busqueda', 'nombre': 'Limpiar Búsqueda'},
        {'id': 'borrar_propiedad', 'nombre': 'Borrar Propiedad'},
        {'id': 'enviar_lote_5', 'nombre': 'Lanzar Lote Drip (5/5)'},
        {'id': 'lanzar_automatizacion', 'nombre': 'Lanzar Automatización Worker'},
        {'id': 'actualizar_estado', 'nombre': 'Actualizar Estado CRM'},
        {'id': 'guardar_operacion', 'nombre': 'Guardar Operación Financiera'},
        {'id': 'borrar_operacion', 'nombre': 'Borrar Operación Financiera'},
        {'id': 'toggle_estado_deuda', 'nombre': 'Modificar Estado de Deudas'},
        {'id': 'ver_config_perfil', 'nombre': 'Configuración - Ver Perfil de Agente'},
        {'id': 'ver_config_smtp', 'nombre': 'Configuración - Ver SMTP / Servidor Email'},
        {'id': 'ver_config_ia', 'nombre': 'Configuración - Ver IA (Gemini)'},
        {'id': 'ver_config_instagram', 'nombre': 'Configuración - Ver Instagram'},
        {'id': 'ver_config_tokko', 'nombre': 'Configuración - Ver API Key Tokko'},
        {'id': 'ver_config_meta_ai', 'nombre': 'Configuración - Ver Meta AI Webhook'},
        {'id': 'ver_config_db_dir', 'nombre': 'Configuración - Ver Directorio DB'},
        {'id': 'ver_config_sondeo', 'nombre': 'Configuración - Ver Sondeo en Vivo (Tasador)'},
        {'id': 'ver_config_plantillas', 'nombre': 'Configuración - Ver Plantillas de Comunicación'},
        {'id': 'ver_config_logo', 'nombre': 'Configuración - Cargar Logo Inmobiliaria'}
    ]
    
    roles = ['admin', 'broker', 'agente', 'finanzas']
    oficinas = db.get_all_oficinas()
    usuarios = db.get_all_usuarios()
    
    if request.method == 'POST':
        # Clear existing rules (protect GermanMazza)
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM privilegios_acceso WHERE NOT (tipo_entidad = 'usuario' AND entidad_id = 'GermanMazza')")
            conn.commit()
        except Exception as e:
            print(f"Error resetting permissions: {e}")
        finally:
            conn.close()
            
        # Parse submitted checkboxes into checked_perms set
        checked_perms = set()
        for key in request.form.keys():
            if key.startswith('perm__'):
                parts = key.split('__')
                if len(parts) == 5:
                    ent_type, ent_id, obj_type, obj_id = parts[1], parts[2], parts[3], parts[4]
                    if ent_type == 'usuario' and ent_id == 'GermanMazza':
                        continue
                    checked_perms.add((ent_type, ent_id, obj_type, obj_id))
                    
        # Extract entities with explicit overrides based on active toggles
        users_with_overrides = set()
        offices_with_overrides = set()
        solo_agents_override = False

        for key in request.form.keys():
            if key.startswith('toggle__usuario__'):
                parts = key.split('__')
                if len(parts) == 3 and parts[2] != 'GermanMazza':
                    users_with_overrides.add(parts[2])
            elif key.startswith('toggle__oficina__'):
                parts = key.split('__')
                if len(parts) == 3:
                    offices_with_overrides.add(parts[2])
            elif key == 'toggle__agentes_sueltos':
                solo_agents_override = True
                
        # 1. Save Roles Rules
        for r in roles:
            for pl in plugins:
                val = 1 if ('rol', r, 'plugin', pl['id']) in checked_perms else 0
                db.set_privilege('rol', r, 'plugin', pl['id'], val)
            for m in menu_items:
                val = 1 if ('rol', r, 'menu_item', m['id']) in checked_perms else 0
                db.set_privilege('rol', r, 'menu_item', m['id'], val)
            for ac in actions:
                val = 1 if ('rol', r, 'accion', ac['id']) in checked_perms else 0
                db.set_privilege('rol', r, 'accion', ac['id'], val)

        # 2. Save Offices Rules (for configured offices)
        for ofi in oficinas:
            ofi_id_str = str(ofi['id'])
            if ofi_id_str in offices_with_overrides:
                for pl in plugins:
                    val = 1 if ('oficina', ofi_id_str, 'plugin', pl['id']) in checked_perms else 0
                    db.set_privilege('oficina', ofi_id_str, 'plugin', pl['id'], val)
                for m in menu_items:
                    val = 1 if ('oficina', ofi_id_str, 'menu_item', m['id']) in checked_perms else 0
                    db.set_privilege('oficina', ofi_id_str, 'menu_item', m['id'], val)
                for ac in actions:
                    val = 1 if ('oficina', ofi_id_str, 'accion', ac['id']) in checked_perms else 0
                    db.set_privilege('oficina', ofi_id_str, 'accion', ac['id'], val)

        # 3. Save Agentes Sueltos Rules (if toggle active)
        if solo_agents_override:
            for pl in plugins:
                val = 1 if ('agentes_sueltos', 'sueltos', 'plugin', pl['id']) in checked_perms else 0
                db.set_privilege('agentes_sueltos', 'sueltos', 'plugin', pl['id'], val)
            for m in menu_items:
                val = 1 if ('agentes_sueltos', 'sueltos', 'menu_item', m['id']) in checked_perms else 0
                db.set_privilege('agentes_sueltos', 'sueltos', 'menu_item', m['id'], val)
            for ac in actions:
                val = 1 if ('agentes_sueltos', 'sueltos', 'accion', ac['id']) in checked_perms else 0
                db.set_privilege('agentes_sueltos', 'sueltos', 'accion', ac['id'], val)
                
        # 4. Save Users Overrides
        for u in users_with_overrides:
            for pl in plugins:
                val = 1 if ('usuario', u, 'plugin', pl['id']) in checked_perms else 0
                db.set_privilege('usuario', u, 'plugin', pl['id'], val)
            for m in menu_items:
                val = 1 if ('usuario', u, 'menu_item', m['id']) in checked_perms else 0
                db.set_privilege('usuario', u, 'menu_item', m['id'], val)
            for ac in actions:
                val = 1 if ('usuario', u, 'accion', ac['id']) in checked_perms else 0
                db.set_privilege('usuario', u, 'accion', ac['id'], val)
                
        flash("Matriz de privilegios guardada correctamente.", "success")
        return redirect(url_for('auth.admin_privilegios'))
        
    # Get active rules from DB to prepopulate checkboxes
    db_rules = db.get_all_privileges()
    active_rules = {}
    for rule in db_rules:
        key = f"{rule['tipo_entidad']}__{rule['entidad_id']}__{rule['tipo_objeto']}__{rule['objeto_id']}"
        active_rules[key] = bool(rule['permitido'])
        
    return render_template('admin_privilegios.html',
                           plugins=plugins,
                           menu_items=menu_items,
                           actions=actions,
                           roles=roles,
                           oficinas=oficinas,
                           usuarios=usuarios,
                           active_rules=active_rules)
