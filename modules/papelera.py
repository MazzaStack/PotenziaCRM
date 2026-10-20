"""
Módulo de Papelera de Reciclaje (Soft-Delete)
Control de acceso exclusivo para Brokers y Administradores.
Aislamiento a nivel Oficina para Brokers; visualización combinada (su oficina + agentes sueltos) para Administradores.
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from modules.auth import role_required
from database import db

papelera_bp = Blueprint('papelera', __name__, url_prefix='/admin/papelera')


def _can_manage_papelera():
    """Valida si el usuario actual tiene permisos de Administrador o Broker."""
    if not current_user.is_authenticated:
        return False
    if current_user.usuario == 'GermanMazza' or current_user.rol in ['admin', 'broker']:
        return True
    return False


@papelera_bp.route('/')
@login_required
@role_required(['admin', 'broker'])
def index():
    """Panel principal de la Papelera de Reciclaje."""
    is_superadmin = (current_user.usuario == 'GermanMazza')
    is_admin = (current_user.rol == 'admin')
    
    # Determinar ámbito de oficina
    user_oficina_id = getattr(current_user, 'oficina_id', None)
    
    # Selector de oficina para Superadmin o Admin
    filtro_oficina = request.args.get('oficina_id')
    
    if is_superadmin:
        # Superadmin puede ver 'all' o filtrar por cualquier oficina
        if filtro_oficina and filtro_oficina != 'all':
            target_oficina_id = int(filtro_oficina)
            include_unassigned = False
        else:
            target_oficina_id = 'all'
            include_unassigned = True
    elif is_admin:
        # Admin puede ver su oficina + agentes sueltos (sin oficina)
        if filtro_oficina and filtro_oficina != 'all':
            target_oficina_id = int(filtro_oficina)
            include_unassigned = False
        else:
            target_oficina_id = user_oficina_id
            include_unassigned = True
    else:
        # Broker estricto: solo su propia oficina
        target_oficina_id = user_oficina_id
        include_unassigned = False
        filtro_oficina = str(user_oficina_id) if user_oficina_id else None

    # Obtener elementos en papelera
    items = db.get_papelera_items(
        oficina_id=target_oficina_id,
        include_unassigned=include_unassigned,
        user_id=current_user.id,
        is_superadmin=(is_superadmin and target_oficina_id == 'all')
    )
    
    oficinas = db.get_all_oficinas() if (is_superadmin or is_admin) else []

    return render_template(
        'papelera.html',
        items=items,
        oficinas=oficinas,
        filtro_oficina=filtro_oficina or ('all' if is_superadmin else str(user_oficina_id or '')),
        is_superadmin=is_superadmin,
        is_admin=is_admin,
        user_oficina_id=user_oficina_id
    )


@papelera_bp.route('/restaurar', methods=['POST'])
@login_required
@role_required(['admin', 'broker'])
def restaurar():
    """Restaura un registro borrado lógicamente."""
    entidad = request.form.get('entidad')
    item_id = request.form.get('id', type=int)
    
    if not entidad or not item_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Datos incompletos'}), 400
        flash("Datos incompletos para restaurar.", "danger")
        return redirect(url_for('papelera.index'))
        
    ok = db.restore_record(entidad, item_id)
    if ok:
        try:
            from database.db_audit import registrar_auditoria
            registrar_auditoria(current_user.id, current_user.usuario, getattr(current_user, 'oficina_id', None),
                                f"Restaurar {entidad}", f"ID #{item_id} restaurado desde papelera")
        except Exception:
            pass
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'Elemento de {entidad} restaurado correctamente.'})
        flash(f"Elemento de {entidad} #{item_id} restaurado con éxito.", "success")
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'No se pudo restaurar el elemento'}), 500
        flash("Error al restaurar el elemento.", "danger")
        
    return redirect(url_for('papelera.index'))


@papelera_bp.route('/purgar', methods=['POST'])
@login_required
@role_required(['admin', 'broker'])
def purgar():
    """Eliminación física definitiva de un elemento."""
    entidad = request.form.get('entidad')
    item_id = request.form.get('id', type=int)
    
    if not entidad or not item_id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'Datos incompletos'}), 400
        flash("Datos incompletos para purgar.", "danger")
        return redirect(url_for('papelera.index'))
        
    ok = db.purge_record(entidad, item_id)
    if ok:
        try:
            from database.db_audit import registrar_auditoria
            registrar_auditoria(current_user.id, current_user.usuario, getattr(current_user, 'oficina_id', None),
                                f"Purgar definitivamente {entidad}", f"ID #{item_id} eliminado de forma permanente")
        except Exception:
            pass
            
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'message': f'Elemento de {entidad} purgado permanentemente.'})
        flash(f"Elemento de {entidad} #{item_id} eliminado definitivamente.", "info")
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': 'No se pudo purgar el elemento'}), 500
        flash("Error al purgar el elemento.", "danger")
        
    return redirect(url_for('papelera.index'))


@papelera_bp.route('/vaciar', methods=['POST'])
@login_required
@role_required(['admin', 'broker'])
def vaciar():
    """Vacía masivamente la papelera en el ámbito del usuario."""
    entidad = request.form.get('entidad') or None
    is_superadmin = (current_user.usuario == 'GermanMazza')
    is_admin = (current_user.rol == 'admin')
    user_oficina_id = getattr(current_user, 'oficina_id', None)
    
    if is_superadmin:
        target_oficina = request.form.get('oficina_id') or 'all'
        include_unassigned = True
    elif is_admin:
        target_oficina = user_oficina_id
        include_unassigned = True
    else:
        target_oficina = user_oficina_id
        include_unassigned = False
        
    count = db.vaciar_papelera_scope(
        oficina_id=target_oficina,
        include_unassigned=include_unassigned,
        is_superadmin=(is_superadmin and target_oficina == 'all'),
        table_name=entidad
    )
    
    try:
        from database.db_audit import registrar_auditoria
        registrar_auditoria(current_user.id, current_user.usuario, user_oficina_id,
                            "Vaciar Papelera", f"Se eliminaron definitivamente {count} registros")
    except Exception:
        pass
        
    flash(f"Papelera vaciada con éxito. Se eliminaron definitivamente {count} elementos.", "success")
    return redirect(url_for('papelera.index'))


# Endpoint directo de eliminación suave de contactos desde el CRM
@papelera_bp.route('/eliminar_contacto/<int:cid>', methods=['POST'])
@login_required
def eliminar_contacto_endpoint(cid):
    """Mueve un contacto a la Papelera de Reciclaje."""
    contacto = db.get_contacto(cid)
    if not contacto:
        flash("Contacto no encontrado.", "danger")
        return redirect(url_for('crm.crm_contactos'))
        
    # Verificar permiso sobre el contacto si no es admin/broker
    if current_user.rol not in ['admin', 'broker'] and current_user.usuario != 'GermanMazza':
        if contacto.get('agente_id') != current_user.id:
            flash("No tenés permiso para eliminar este contacto.", "danger")
            return redirect(url_for('crm.crm_contactos'))
            
    ok = db.delete_contacto_soft(cid, deleted_by=f"{current_user.nombre_display or current_user.usuario}")
    if ok:
        try:
            from database.db_audit import registrar_auditoria
            registrar_auditoria(current_user.id, current_user.usuario, getattr(current_user, 'oficina_id', None),
                                "Mover a Papelera Contacto", f"Contacto '{contacto.get('nombre')} {contacto.get('apellido')}' (ID #{cid}) enviado a papelera")
        except Exception:
            pass
        flash(f"Contacto '{contacto.get('nombre')} {contacto.get('apellido')}' enviado a la Papelera de Reciclaje. Puede ser restaurado por el Broker/Admin.", "info")
    else:
        flash("Error al mover el contacto a la papelera.", "danger")
        
    return redirect(url_for('crm.crm_contactos'))
