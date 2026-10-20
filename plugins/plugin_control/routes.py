from flask import Blueprint, request, redirect, url_for, render_template, flash, jsonify
from flask_login import login_required, current_user
from database import db
from modules.auth import superadmin_required

plugin_control_bp = Blueprint('plugin_control', __name__)

@plugin_control_bp.route('/admin/plugin_control', methods=['GET', 'POST'])
@login_required
@superadmin_required
def manage_plugins():
    """Manage global plugin activation status per role (SuperAdmin only)."""
    plugins = [
        {'id': 'finanzas', 'nombre': 'Módulo de Finanzas'},
        {'id': 'meta_ai', 'nombre': 'Chatbot Meta AI'},
        {'id': 'redes_sociales', 'nombre': 'Historias e IG'},
        {'id': 'captacion_outreach', 'nombre': 'Captación y Outreach (WhatsApp/Email)'},
        {'id': 'lotes_excel', 'nombre': 'Visor de Lotes Excel'},
        {'id': 'publicacion_placa', 'nombre': 'Publicación a Placa (PAP)'},
        {'id': 'db_backup', 'nombre': 'Gestión de Backups y Restauración'}
    ]
    
    roles = ['admin', 'broker', 'agente', 'finanzas']
    
    if request.method == 'POST':
        # Reset all activation rules first
        conn = db.get_db()
        try:
            conn.execute("DELETE FROM plugin_activation_roles")
            conn.commit()
        except Exception as e:
            print(f"Error resetting plugin activations: {e}")
        finally:
            conn.close()
            
        # Repopulate based on submitted form
        for r in roles:
            for pl in plugins:
                # Check if checked in the form
                input_name = f"active__{r}__{pl['id']}"
                is_active = 1 if request.form.get(input_name) == 'on' else 0
                db.set_plugin_active_for_role(r, pl['id'], is_active)
                
        flash("Configuración de activación de plugins guardada correctamente.", "success")
        return redirect(url_for('plugin_control.manage_plugins'))
        
    # Get active states from DB
    activations = db.get_all_plugin_activations()
    active_states = {}
    for act in activations:
        key = f"{act['rol']}__{act['plugin_id']}"
        active_states[key] = bool(act['activo'])
        
    return render_template('plugin_control.html',
                           plugins=plugins,
                           roles=roles,
                           active_states=active_states)
