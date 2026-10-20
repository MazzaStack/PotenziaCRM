"""
CRM Module for Contacts Management, Excel Import/Export and Recordatorios
"""
import os
import json
import secrets
import pandas as pd
from flask import Blueprint, request, redirect, url_for, render_template, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from modules.auth import broker_required
from database import db

crm_bp = Blueprint('crm', __name__)

@crm_bp.route('/crm/contactos')
@login_required
def crm_contactos():
    """Vista principal del CRM de contactos."""
    sort_by = request.args.get('sort', 'calificacion')
    order = request.args.get('order', 'DESC')
    cold_only = request.args.get('cold') == '1'
    busqueda = request.args.get('busqueda', '').strip()
    
    contactos = db.get_contactos(sort_by=sort_by, order=order, cold_only=cold_only, busqueda=busqueda or None)
    custom_cols = db.get_custom_columns()
    
    for c in contactos:
        c['custom_fields'] = {}
        if c.get('campos_personalizados_json'):
            try:
                c['custom_fields'] = json.loads(c['campos_personalizados_json'])
            except: pass
            
    fidelity = db.get_fidelizacion_hoy()
    return render_template('contactos.html', 
                          contactos=contactos, 
                          sort_by=sort_by, 
                          order=order, 
                          cold_only=cold_only,
                          busqueda=busqueda,
                          custom_cols=custom_cols,
                          fidelity=fidelity)

@crm_bp.route('/crm/columnas', methods=['POST'])
@login_required
def crm_gestionar_columnas():
    """Agrega o elimina columnas personalizadas del CRM."""
    accion = request.form.get('accion')
    nombre = request.form.get('nombre_columna', '').strip()
    
    if accion == 'agregar' and nombre:
        db.add_custom_column(nombre)
        flash(f"Columna '{nombre}' agregada al CRM.", "success")
    elif accion == 'eliminar' and nombre:
        cols = db.get_custom_columns()
        if nombre in cols:
            cols.remove(nombre)
            db.set_config('crm_custom_columns', json.dumps(cols))
            flash(f"Columna '{nombre}' eliminada.", "info")
            
    return redirect(url_for('crm.crm_contactos'))

@crm_bp.route('/crm/upsert_contacto', methods=['POST'])
@login_required
def upsert_contacto():
    """Create or update a contact from a unified form."""
    def parse_int(v, default=0):
        try:
            return int(v) if v and str(v).strip() else default
        except:
            return default

    data = {
        'id': request.form.get('id'),
        'nombre': request.form.get('nombre'),
        'apellido': request.form.get('apellido'),
        'telefono': request.form.get('telefono'),
        'email': request.form.get('email'),
        'categoria': request.form.get('categoria', 'C'),
        'calificacion': parse_int(request.form.get('calificacion'), 0),
        'notas': request.form.get('notas'),
        'fecha_nacimiento': request.form.get('fecha_nacimiento') or None,
        'aniversario_casa': request.form.get('aniversario_casa') or None,
        'busqueda_activa': 1 if request.form.get('busqueda_activa') == 'on' else 0,
        'filtros_busqueda_json': request.form.get('filtros_busqueda_json'),
        'mac': parse_int(request.form.get('mac'), 0),
        'intencion_ia': request.form.get('intencion_ia'),
        'recordatorio_activo': 1 if request.form.get('recordatorio_activo') == 'on' else 0,
        'recordatorio_dias': parse_int(request.form.get('recordatorio_dias'), None) if request.form.get('recordatorio_dias') else None,
        'recordatorio_fecha': request.form.get('recordatorio_fecha') or None
    }
    
    cid = db.save_contacto(data)
    if cid:
        flash("Contacto guardado correctamente", "success")
        return redirect(url_for('crm.crm_contactos'))
    else:
        flash("Error al guardar el contacto", "error")
        return redirect(url_for('crm.crm_contactos'))

@crm_bp.route('/crm/eliminar_contacto/<int:cid>', methods=['POST'])
@login_required
def eliminar_contacto(cid):
    """Mueve un contacto a la papelera de reciclaje."""
    contacto = db.get_contacto(cid)
    if not contacto:
        flash("Contacto no encontrado.", "danger")
        return redirect(url_for('crm.crm_contactos'))
        
    if current_user.rol not in ['admin', 'broker'] and current_user.usuario != 'GermanMazza':
        if contacto.get('agente_id') != current_user.id:
            flash("No tenés permiso para eliminar este contacto.", "danger")
            return redirect(url_for('crm.crm_contactos'))
            
    ok = db.delete_contacto_soft(cid, deleted_by=f"{current_user.nombre_display or current_user.usuario}")
    if ok:
        try:
            from database.db_audit import registrar_auditoria
            registrar_auditoria(current_user.id, current_user.usuario, getattr(current_user, 'oficina_id', None),
                                "Mover a Papelera Contacto", f"Contacto '{contacto.get('nombre')} {contacto.get('apellido')}' enviado a papelera")
        except Exception:
            pass
        flash(f"Contacto '{contacto.get('nombre')} {contacto.get('apellido')}' enviado a la Papelera de Reciclaje.", "info")
    else:
        flash("Error al eliminar el contacto.", "danger")
        
    return redirect(url_for('crm.crm_contactos'))

@crm_bp.route('/crm/recordatorio/completar', methods=['POST'])
@login_required
def completar_recordatorio():
    """Desactiva un recordatorio activo."""
    cid = request.form.get('id')
    if cid:
        db.update_contacto_campo(cid, 'recordatorio_activo', 0)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'Faltan datos'})

@crm_bp.route('/crm/update_contacto', methods=['POST'])
@login_required
def update_contacto():
    """Update a contact field via AJAX (Keep for quick category/small edits)."""
    cid = request.form.get('id')
    campo = request.form.get('campo')
    valor = request.form.get('valor')
    
    if cid and campo:
        db.update_contacto_campo(cid, campo, valor)
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'Faltan datos'})

@crm_bp.route('/crm/marcar_contacto_hoy', methods=['POST'])
@login_required
def marcar_contacto_hoy():
    """Update last_contact date to today for a specific contact."""
    from datetime import datetime
    cid = request.form.get('id')
    today = datetime.now().strftime('%Y-%m-%d')
    
    if cid:
        db.update_contacto_campo(cid, 'ultimo_contacto', today)
        return jsonify({'status': 'success', 'today': today})
    return jsonify({'status': 'error'})

@crm_bp.route('/crm/resumir_chat', methods=['POST'])
@login_required
def resumir_chat():
    """IA Chat Summarizer for German."""
    chat_text = request.form.get('chat_text')
    if not chat_text:
        return jsonify({'error': 'No se proporcionó texto'})
    
    from lib.gemini_service import get_gemini_client
    client = get_gemini_client()
    if not client:
        return jsonify({'error': 'Error de IA'})
        
    prompt = f"""
    Analizá el siguiente chat de WhatsApp entre un agente inmobiliario (German) y un cliente.
    Extraé y devolvé un resumen ejecutivo corto con:
    - Qué busca el cliente (Tipo, Ambientes, Zona).
    - Presupuesto aproximado (si se menciona).
    - Nivel de urgencia (Alta, Media, Baja).
    - Próximo paso recomendado para German.
    
    FORMATO: Usá bullet points claros y cortitos.
    CHAT:
    {chat_text}
    """
    try:
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        return jsonify({'resumen': response.text.strip() if response.text else "No se pudo resumir."})
    except Exception as e:
        return jsonify({'error': str(e)})

@crm_bp.route('/api/ia_propuestas_prospeccion', methods=['GET', 'POST'])
@login_required
def ia_propuestas_prospeccion():
    """
    Gestiona la visualización progresiva (2 en 2 hasta 6) y la persistencia por 24 hrs
    de las propuestas de prospección con IA para el agente logueado.
    """
    import time, json
    from datetime import datetime
    from lib.gemini_service import generar_propuestas_prospeccion_ia
    
    action = request.form.get('action') or request.args.get('action') # 'unlock', 'reset', or None (status check)
    
    # Read user-scoped config
    cache_raw = db.get_config('ia_prospeccion_ideas')
    cache_data = None
    if cache_raw:
        try:
            cache_data = json.loads(cache_raw)
        except Exception:
            cache_data = None

    now_ts = time.time()
    
    # Check if cached ideas exist and are valid for 24 hours (86400 seconds)
    is_valid_cache = False
    if cache_data and isinstance(cache_data, dict):
        gen_ts = cache_data.get('generated_at', 0)
        if (now_ts - gen_ts) < 86400 and len(cache_data.get('ideas', [])) > 0:
            is_valid_cache = True
            
    if action == 'reset':
        is_valid_cache = False
        cache_data = None

    if action == 'unlock':
        if not is_valid_cache:
            agente_nombre = getattr(current_user, 'nombre_display', None) or getattr(current_user, 'usuario', 'Agente')
            cold_count = db.count_contactos_frios()
            context_str = f"Agente inmobiliario: {agente_nombre}. Contactos fríos pendientes: {cold_count}."
            
            ideas = generar_propuestas_prospeccion_ia(agente_nombre=agente_nombre, context_summary=context_str)
            visible_count = 2
            cache_data = {
                'generated_at': now_ts,
                'generated_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'ideas': ideas,
                'visible_count': visible_count
            }
        else:
            current_visible = cache_data.get('visible_count', 0)
            total_ideas = len(cache_data.get('ideas', []))
            new_visible = min(current_visible + 2, 6, total_ideas)
            cache_data['visible_count'] = new_visible

        db.set_config('ia_prospeccion_ideas', json.dumps(cache_data))
        
        visible_subset = cache_data['ideas'][:cache_data['visible_count']]
        return jsonify({
            'status': 'success',
            'unlocked': True,
            'ideas': visible_subset,
            'visible_count': cache_data['visible_count'],
            'total_ideas': len(cache_data['ideas']),
            'max_reached': cache_data['visible_count'] >= min(6, len(cache_data['ideas']))
        })

    # GET / Default check: return current unlocked state without generating LLM calls
    if is_valid_cache and cache_data and cache_data.get('visible_count', 0) > 0:
        visible_subset = cache_data['ideas'][:cache_data['visible_count']]
        return jsonify({
            'status': 'success',
            'unlocked': True,
            'ideas': visible_subset,
            'visible_count': cache_data['visible_count'],
            'total_ideas': len(cache_data['ideas']),
            'max_reached': cache_data['visible_count'] >= min(6, len(cache_data['ideas']))
        })
    else:
        return jsonify({
            'status': 'success',
            'unlocked': False,
            'ideas': [],
            'visible_count': 0,
            'total_ideas': 0,
            'max_reached': False
        })

@crm_bp.route('/importar_excel', methods=['POST'])
@login_required
def importar_excel():
    """Receives file from dashboard and redirects to the column mapper screen (step 1)."""
    file = request.files.get('archivo_excel') or request.files.get('excel_file')
    if not file or file.filename == '':
        flash("No se seleccionó ningún archivo", "error")
        return redirect(url_for('crm.crm_contactos'))
        
    temp_filename = f"import_{current_user.id}_{secrets.token_hex(4)}_{file.filename}"
    temp_path = os.path.join(current_app.root_path, 'scratch', temp_filename)
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    file.save(temp_path)
    
    try:
        # Read headers
        if file.filename.endswith('.csv'):
            df = pd.read_csv(temp_path, nrows=0)
        else:
            df = pd.read_excel(temp_path, nrows=0)
            
        headers = df.columns.tolist()
        custom_cols = db.get_custom_columns()
        return render_template('importador.html', headers=headers, temp_filename=temp_filename, custom_cols=custom_cols)
        
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        flash(f"Error al leer el archivo: {e}", "error")
        return redirect(url_for('crm.crm_contactos'))

@crm_bp.route('/exportar_excel')
@broker_required
def exportar_excel():
    """Export CRM contacts back to the original Excel format."""
    xl_path = 'base_temp.xlsx'
    if not os.path.exists(xl_path):
        flash("No se encontró el archivo base para exportar", "error")
        return redirect(url_for('crm.crm_contactos'))
    
    try:
        df = pd.read_excel(xl_path)
        contactos = db.get_contactos(limit=1000)
        
        cols = df.columns.tolist()
        col_nombre = next((c for c in cols if 'nombre' in c.lower()), None)
        col_apellido = next((c for c in cols if 'apellido' in c.lower()), None)
        col_cat = next((c for c in cols if 'califica' in c.lower()), None)
        col_ultimo = next((c for c in cols if 'ultimo' in c.lower() or 'contacto 12m' in c.lower()), None)
        col_notas = next((c for c in cols if 'nota' in c.lower() or 'coment' in c.lower()), None)
        
        for idx, row in df.iterrows():
            nom = str(row[col_nombre]).strip() if col_nombre and pd.notnull(row[col_nombre]) else ''
            ape = str(row[col_apellido]).strip() if col_apellido and pd.notnull(row[col_apellido]) else ''
            
            match = next((c for c in contactos if c['nombre'].strip() == nom and c['apellido'].strip() == ape), None)
            
            if match:
                if col_cat: df.at[idx, col_cat] = match['categoria']
                if col_ultimo: df.at[idx, col_ultimo] = match['ultimo_contacto']
                if col_notas: df.at[idx, col_notas] = match['notas']
        
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scratch')
        os.makedirs(temp_dir, exist_ok=True)
        output_path = os.path.join(temp_dir, 'Base_CRM_Actualizada.xlsx')
        df.to_excel(output_path, index=False)
        
        return send_file(output_path, as_attachment=True, download_name='Base_Contactos_Actualizada.xlsx')
        
    except Exception as e:
        flash(f"Error al exportar: {e}", "error")
        print(f"EXPORT ERROR: {e}")
        return redirect(url_for('crm.crm_contactos'))

@crm_bp.route('/importador')
@login_required
def importador():
    """Vista inicial del importador."""
    return render_template('importador.html')

@crm_bp.route('/importador/paso1', methods=['POST'])
@login_required
def importar_paso_1():
    """Recibe el Excel y extrae las cabeceras."""
    file = request.files.get('excel_file')
    if not file or file.filename == '':
        flash("No se seleccionó ningún archivo", "error")
        return redirect(url_for('crm.importador'))
        
    temp_filename = f"import_{current_user.id}_{secrets.token_hex(4)}_{file.filename}"
    temp_path = os.path.join(current_app.root_path, 'scratch', temp_filename)
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    file.save(temp_path)
    
    try:
        # Read headers
        if file.filename.endswith('.csv'):
            df = pd.read_csv(temp_path, nrows=0)
        else:
            df = pd.read_excel(temp_path, nrows=0)
            
        headers = df.columns.tolist()
        custom_cols = db.get_custom_columns()
        return render_template('importador.html', headers=headers, temp_filename=temp_filename, custom_cols=custom_cols)
        
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        flash(f"Error al leer el archivo: {e}", "error")
        return redirect(url_for('crm.importador'))

@crm_bp.route('/importador/paso2', methods=['POST'])
@login_required
def importar_paso_2():
    """Procesa el archivo completo usando el mapeo de columnas."""
    temp_filename = request.form.get('temp_filename')
    temp_path = os.path.join(current_app.root_path, 'scratch', temp_filename)
    
    if not os.path.exists(temp_path):
        flash("El archivo temporal expiró o no existe.", "error")
        return redirect(url_for('crm.importador'))
        
    # Get mapping from form
    mapping = {
        'nombre': request.form.get('mapping_nombre'),
        'apellido': request.form.get('mapping_apellido'),
        'telefono': request.form.get('mapping_telefono'),
        'email': request.form.get('mapping_email'),
        'rol': request.form.get('mapping_rol'),
        'categoria': request.form.get('mapping_categoria'),
        'calificacion': request.form.get('mapping_calificacion'),
        'ultimo_contacto': request.form.get('mapping_ultimo_contacto'),
        'fecha_nacimiento': request.form.get('mapping_fecha_nacimiento'),
        'referente': request.form.get('mapping_referente'),
        'notas': request.form.get('mapping_notas')
    }
    
    # Add custom mappings
    custom_cols = db.get_custom_columns()
    custom_mapping = {}
    for col in custom_cols:
        mapped_excel_col = request.form.get(f'mapping_custom_{col}')
        if mapped_excel_col:
            custom_mapping[col] = mapped_excel_col
    
    try:
        if temp_filename.endswith('.csv'):
            df = pd.read_csv(temp_path)
        else:
            df = pd.read_excel(temp_path)
            
        success_count = 0
        for _, row in df.iterrows():
            contacto_data = {}
            for field, excel_col in mapping.items():
                if excel_col and pd.notnull(row.get(excel_col)):
                    val = row.get(excel_col)
                    # Handle datetime formats
                    if hasattr(val, 'strftime'):
                        val = val.strftime('%Y-%m-%d')
                    contacto_data[field] = str(val).strip()
            
            # Additional cleanings/parses for rating and category
            if 'calificacion' in contacto_data:
                try:
                    contacto_data['calificacion'] = int(float(contacto_data['calificacion']))
                except:
                    contacto_data['calificacion'] = 0
            else:
                contacto_data['calificacion'] = 0
                
            if 'categoria' in contacto_data:
                contacto_data['categoria'] = contacto_data['categoria'].upper()
            else:
                contacto_data['categoria'] = 'C'
                
            # Map custom fields
            custom_fields = {}
            for custom_field, excel_col in custom_mapping.items():
                if excel_col and pd.notnull(row.get(excel_col)):
                    custom_fields[custom_field] = str(row.get(excel_col)).strip()
            if custom_fields:
                contacto_data['campos_personalizados_json'] = json.dumps(custom_fields)
            
            # Simple validation: need at least a name or phone
            if contacto_data.get('nombre') or contacto_data.get('telefono'):
                # Handle save / insert
                db.save_contacto(contacto_data)
                success_count += 1
                
        os.remove(temp_path) # Cleanup
        flash(f"Se importaron {success_count} contactos exitosamente.", "success")
        return redirect(url_for('crm.crm_contactos'))
        
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        flash(f"Error durante la importación: {e}", "error")
        return redirect(url_for('crm.importador'))

@crm_bp.route('/blacklist')
@login_required
def blacklist():
    """List of blacklisted phones."""
    numbers = db.get_blacklist()
    return render_template('blacklist.html', numbers=numbers)

@crm_bp.route('/blacklist/add', methods=['POST'])
@login_required
def add_blacklist_route():
    """Add a number to the blacklist."""
    telefono = request.form.get('telefono')
    motivo = request.form.get('motivo')
    if db.add_to_blacklist(telefono, motivo):
        flash(f"Teléfono {telefono} añadido a la lista negra", "warning")
    else:
        flash("Error al añadir a la lista negra", "error")
    return redirect(request.referrer or url_for('crm.blacklist'))

@crm_bp.route('/blacklist/remove/<int:id>', methods=['POST'])
@login_required
def remove_blacklist_route(id):
    """Remove a number from the blacklist."""
    if db.remove_from_blacklist(id):
        flash("Número removido de la lista negra con éxito.", "success")
    else:
        flash("Error al remover el número de la lista negra.", "danger")
    return redirect(url_for('crm.blacklist'))


