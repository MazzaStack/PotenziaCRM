"""
Routes & API Blueprint for Asistente IA Plugin.
Handles AI greeting generation for birthdays/anniversaries and Morning Briefing management.
"""
import urllib.parse
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, g
from flask_login import login_required, current_user
from database import db
from plugins.asistente_ia.service import (
    generar_saludo_cumpleanios,
    generar_saludo_aniversario,
    generar_morning_briefing
)
from plugins.asistente_ia.morning_worker import (
    recopilar_datos_agente,
    enviar_morning_briefing_agente,
    start_morning_briefing_scheduler
)

asistente_ia_bp = Blueprint('asistente_ia', __name__)

# Auto-start scheduler in background when plugin is loaded
try:
    start_morning_briefing_scheduler()
except Exception as e:
    print(f"[AsistenteIA] Error iniciando scheduler: {e}")

@asistente_ia_bp.route('/api/asistente_ia/fidelizacion_hoy', methods=['GET'])
@login_required
def api_fidelizacion_hoy():
    """Devuelve los cumpleaños y aniversarios de hoy para el usuario actual."""
    try:
        today_md = datetime.now().strftime('%m-%d')
        conn = db.get_db()
        is_super = (current_user.usuario == 'GermanMazza')
        
        if is_super:
            cumple_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, fecha_nacimiento, categoria, rol, notas 
                FROM contactos 
                WHERE fecha_nacimiento LIKE ? OR SUBSTR(fecha_nacimiento, 6, 5) = ?
            """, (f"%{today_md}%", today_md)).fetchall()
            
            aniv_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, aniversario_casa, categoria, rol, notas 
                FROM contactos 
                WHERE aniversario_casa LIKE ? OR SUBSTR(aniversario_casa, 6, 5) = ?
            """, (f"%{today_md}%", today_md)).fetchall()
        else:
            cumple_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, fecha_nacimiento, categoria, rol, notas 
                FROM contactos 
                WHERE (fecha_nacimiento LIKE ? OR SUBSTR(fecha_nacimiento, 6, 5) = ?) AND agente_id = ?
            """, (f"%{today_md}%", today_md, current_user.id)).fetchall()
            
            aniv_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, aniversario_casa, categoria, rol, notas 
                FROM contactos 
                WHERE (aniversario_casa LIKE ? OR SUBSTR(aniversario_casa, 6, 5) = ?) AND agente_id = ?
            """, (f"%{today_md}%", today_md, current_user.id)).fetchall()
        conn.close()

        cumples = [dict(r) for r in cumple_rows]
        aniversarios = [dict(r) for r in aniv_rows]

        return jsonify({
            'status': 'success',
            'total': len(cumples) + len(aniversarios),
            'cumples': cumples,
            'aniversarios': aniversarios
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@asistente_ia_bp.route('/api/asistente_ia/generar_saludo', methods=['POST'])
@login_required
def api_generar_saludo():
    """
    Genera un saludo personalizado con Groq (openai/gpt-oss-20b) para un contacto específico.
    Devuelve el texto y el enlace directo de WhatsApp (wa.me) para enviar desde su propio WhatsApp.
    """
    data = request.get_json() or {}
    contacto_id = data.get('contacto_id')
    tipo = data.get('tipo', 'cumpleanios') # 'cumpleanios' o 'aniversario'
    
    if not contacto_id:
        return jsonify({'status': 'error', 'message': 'Falta contacto_id'}), 400

    conn = db.get_db()
    try:
        row = conn.execute("SELECT * FROM contactos WHERE id = ?", (contacto_id,)).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({'status': 'error', 'message': 'Contacto no encontrado'}), 404

    contacto = dict(row)
    agente_nombre = getattr(current_user, 'nombre_display', None) or getattr(current_user, 'usuario', 'German')
    
    if tipo == 'aniversario':
        mensaje = generar_saludo_aniversario(contacto, agente_nombre=agente_nombre)
    else:
        mensaje = generar_saludo_cumpleanios(contacto, agente_nombre=agente_nombre)

    # Construir enlace directo de WhatsApp para el agente
    tel = str(contacto.get('telefono') or '').replace(" ", "").replace("-", "").replace("+", "")
    encoded_msg = urllib.parse.quote(mensaje)
    wa_link = f"https://wa.me/{tel}?text={encoded_msg}" if tel else f"https://wa.me/?text={encoded_msg}"

    return jsonify({
        'status': 'success',
        'tipo': tipo,
        'contacto_nombre': f"{contacto.get('nombre', '')} {contacto.get('apellido', '')}".strip(),
        'telefono': tel,
        'mensaje': mensaje,
        'wa_link': wa_link
    })

@asistente_ia_bp.route('/api/asistente_ia/preview_briefing', methods=['GET', 'POST'])
@login_required
def api_preview_briefing():
    """Previsualiza el contenido del Morning Briefing para el usuario logueado."""
    try:
        agente_nombre = getattr(current_user, 'nombre_display', None) or getattr(current_user, 'usuario', 'German')
        datos = recopilar_datos_agente(current_user.id, current_user.usuario)
        
        mensaje = generar_morning_briefing(
            agente_nombre=agente_nombre,
            recordatorios_hoy=datos['recordatorios_hoy'],
            cumples_hoy=datos['cumples_hoy'],
            aniversarios_hoy=datos['aniversarios_hoy'],
            cold_count=datos['cold_count']
        )

        return jsonify({
            'status': 'success',
            'agente': agente_nombre,
            'datos': datos,
            'mensaje': mensaje
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@asistente_ia_bp.route('/api/asistente_ia/enviar_briefing_prueba', methods=['POST'])
@login_required
def api_enviar_briefing_prueba():
    """Envía inmediatamente el Morning Briefing de prueba al WhatsApp del agente usando la sesión del Portal."""
    try:
        agente_nombre = getattr(current_user, 'nombre_display', None) or getattr(current_user, 'usuario', 'German')
        
        # Número opcional enviado en el POST o tomado de su perfil
        data = request.get_json() or {}
        tel_override = data.get('telefono')
        
        success, msg = enviar_morning_briefing_agente(
            agente_id=current_user.id,
            agente_usuario=current_user.usuario,
            agente_nombre=agente_nombre,
            telefono_override=tel_override,
            force=True
        )

        if success:
            return jsonify({'status': 'success', 'message': msg})
        else:
            return jsonify({'status': 'error', 'message': msg}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@asistente_ia_bp.route('/api/asistente_ia/agentes_config', methods=['GET'])
@login_required
def api_agentes_config():
    """Devuelve la lista de agentes comerciales con su estado de Morning Briefing."""
    is_admin_or_broker = (getattr(current_user, 'rol', '') in ('admin', 'broker') or getattr(current_user, 'usuario', '') == 'GermanMazza')
    if not is_admin_or_broker:
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    conn = db.get_db()
    try:
        if getattr(current_user, 'usuario', '') == 'GermanMazza':
            users = conn.execute("""
                SELECT id, usuario, nombre_display, rol, oficina_id 
                FROM usuarios 
                WHERE rol IN ('agente', 'broker', 'admin')
                ORDER BY id ASC
            """).fetchall()
        elif getattr(current_user, 'oficina_id', None):
            users = conn.execute("""
                SELECT id, usuario, nombre_display, rol, oficina_id 
                FROM usuarios 
                WHERE rol IN ('agente', 'broker', 'admin') AND oficina_id = ?
                ORDER BY id ASC
            """, (current_user.oficina_id,)).fetchall()
        else:
            users = []
        
        agentes = []
        for u in users:
            u_dict = dict(u)
            uid = u_dict['id']
            tel = db.get_config(f'agente_telefono_{uid}') or ''
            if not tel and (u_dict['usuario'] == 'GermanMazza' or uid == 4):
                import os
                tel = os.environ.get("SUPERADMIN_PHONE", "+5491161114414")
                
            hab_cfg = db.get_config(f'morning_briefing_habilitado_{uid}')
            habilitado = (hab_cfg not in ('0', 'false', 'False', False))
            ultimo_envio = db.get_config(f'morning_briefing_last_sent_{uid}') or 'Nunca'
            
            # Cantidad de contactos
            cnt_row = conn.execute("SELECT COUNT(*) as cant FROM contactos WHERE agente_id = ? AND estado_seguimiento = 'activo'", (uid,)).fetchone()
            cant_contactos = cnt_row['cant'] if cnt_row else 0
            
            agentes.append({
                'id': uid,
                'usuario': u_dict['usuario'],
                'nombre': u_dict['nombre_display'] or u_dict['usuario'],
                'rol': u_dict['rol'],
                'telefono': tel,
                'habilitado': habilitado,
                'ultimo_envio': ultimo_envio,
                'cant_contactos': cant_contactos
            })
            
        return jsonify({'status': 'success', 'agentes': agentes})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        conn.close()

@asistente_ia_bp.route('/api/asistente_ia/guardar_agente_config', methods=['POST'])
@login_required
def api_guardar_agente_config():
    """Actualiza el teléfono y la activación de Morning Briefing de un agente."""
    is_admin_or_broker = (getattr(current_user, 'rol', '') in ('admin', 'broker') or getattr(current_user, 'usuario', '') == 'GermanMazza')
    if not is_admin_or_broker:
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    data = request.get_json() or {}
    agente_id = data.get('agente_id')
    telefono = (data.get('telefono') or '').strip()
    habilitado = data.get('habilitado', True)

    if not agente_id:
        return jsonify({'status': 'error', 'message': 'Falta agente_id'}), 400

    if getattr(current_user, 'usuario', '') != 'GermanMazza' and getattr(current_user, 'oficina_id', None):
        conn = db.get_db()
        try:
            target = conn.execute("SELECT id FROM usuarios WHERE id = ? AND oficina_id = ?", (agente_id, current_user.oficina_id)).fetchone()
            if not target:
                return jsonify({'status': 'error', 'message': 'Agente no pertenece a su oficina'}), 403
        finally:
            conn.close()

    try:
        db.set_config(f'agente_telefono_{agente_id}', telefono)
        db.set_config(f'morning_briefing_habilitado_{agente_id}', '1' if habilitado else '0')
        return jsonify({'status': 'success', 'message': 'Configuración del agente guardada exitosamente.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@asistente_ia_bp.route('/api/asistente_ia/enviar_briefing_agente_especifico', methods=['POST'])
@login_required
def api_enviar_briefing_agente_especifico():
    """Permite al Broker disparar un envío de prueba individual a cualquier agente de su oficina."""
    is_admin_or_broker = (getattr(current_user, 'rol', '') in ('admin', 'broker') or getattr(current_user, 'usuario', '') == 'GermanMazza')
    if not is_admin_or_broker:
        return jsonify({'status': 'error', 'message': 'No autorizado'}), 403

    data = request.get_json() or {}
    agente_id = data.get('agente_id')
    
    if not agente_id:
        return jsonify({'status': 'error', 'message': 'Falta agente_id'}), 400

    conn = db.get_db()
    try:
        if getattr(current_user, 'usuario', '') == 'GermanMazza':
            u_row = conn.execute("SELECT id, usuario, nombre_display FROM usuarios WHERE id = ?", (agente_id,)).fetchone()
        elif getattr(current_user, 'oficina_id', None):
            u_row = conn.execute("SELECT id, usuario, nombre_display FROM usuarios WHERE id = ? AND oficina_id = ?", (agente_id, current_user.oficina_id)).fetchone()
        else:
            u_row = None
    finally:
        conn.close()

    if not u_row:
        return jsonify({'status': 'error', 'message': 'Agente no encontrado o no pertenece a su oficina'}), 404

    success, msg = enviar_morning_briefing_agente(
        agente_id=u_row['id'],
        agente_usuario=u_row['usuario'],
        agente_nombre=u_row['nombre_display'],
        force=True
    )

    if success:
        return jsonify({'status': 'success', 'message': msg})
    else:
        return jsonify({'status': 'error', 'message': msg}), 400
