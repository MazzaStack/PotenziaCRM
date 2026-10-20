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
