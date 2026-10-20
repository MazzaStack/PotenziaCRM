"""
Social Media Scheduling Plugin
Handles Instagram Stories (via Meta Graph API) and WhatsApp Status (via Baileys/Node bridge).
Includes per-story platform toggles (instagram / whatsapp) and instant-post capability.
"""
import os
import uuid
import sys
import json
import requests
import subprocess
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from database import db
from modules.auth import superadmin_required, privilege_required
from lib.publisher_log import log as plog, get_recent_events, get_log_paths
from lib.instagram_publisher import publicar_historia_privada

redes_sociales_bp = Blueprint('redes_sociales', __name__)


def _get_node_port(user_id: int) -> int:
    """Calcula el puerto del bridge Node de Baileys para un usuario."""
    return 9000 + user_id


def _bridge_post_status(port: int, file_path: str, caption: str = "") -> dict:
    """
    Llama al endpoint POST /status del bridge de Baileys para publicar en WhatsApp Status.
    Retorna {'success': True/False, 'error': '...' (opcional), 'raw': respuesta completa}
    """
    abs_path = os.path.abspath(file_path)
    plog('info', 'whatsapp', f'Llamando bridge POST /status en puerto {port}', {'filePath': abs_path})

    try:
        r = requests.post(
            f"http://127.0.0.1:{port}/status",
            json={"filePath": abs_path, "caption": caption},
            timeout=60
        )
        raw = {}
        try:
            raw = r.json()
        except Exception:
            raw = {'text': r.text}

        plog('debug', 'whatsapp', f'Bridge respondió HTTP {r.status_code}', {'response': raw})

        if r.status_code == 200 and raw.get('success'):
            plog('info', 'whatsapp', f'Estado publicado OK. statusId: {raw.get("statusId")}, contactos notificados: {raw.get("contacts_notified")}')
            return {"success": True, "raw": raw}
        else:
            err_msg = raw.get('error') or raw.get('details') or r.text or f'HTTP {r.status_code}'
            plog('error', 'whatsapp', f'Bridge retornó error: {err_msg}', {'response': raw})
            return {"success": False, "error": err_msg, "raw": raw}

    except requests.exceptions.ConnectionError:
        msg = f'No se pudo conectar al bridge en puerto {port}. ¿Está corriendo el proceso de WhatsApp?'
        plog('error', 'whatsapp', msg)
        return {"success": False, "error": msg}
    except requests.exceptions.Timeout:
        msg = f'Timeout (60s) esperando respuesta del bridge en puerto {port}'
        plog('error', 'whatsapp', msg)
        return {"success": False, "error": msg}
    except Exception as e:
        msg = f'Excepción inesperada: {type(e).__name__}: {e}'
        plog('error', 'whatsapp', msg)
        return {"success": False, "error": msg}


def _resolve_file_path(app_root: str, archivo_path: str) -> str:
    """Convierte un db path relativo (/static/uploads/...) a un path absoluto en disco."""
    clean = archivo_path.lstrip('/')
    return os.path.join(app_root, clean.replace('/', os.sep))


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# VIEW: Calendario
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/historias')
@login_required
@privilege_required('menu_item', 'historias')
def historias_view():
    """Render calendar view for social media posting with multi-agent support for admins."""
    conn = db.get_db()
    is_admin = current_user.usuario == 'GermanMazza' or current_user.rol in ('admin', 'broker')
    agentes = []
    if is_admin:
        try:
            if current_user.usuario == 'GermanMazza':
                agentes = conn.execute("SELECT id, usuario, nombre_display, rol, oficina_id FROM usuarios ORDER BY nombre_display ASC").fetchall()
            elif current_user.oficina_id:
                agentes = conn.execute("SELECT id, usuario, nombre_display, rol, oficina_id FROM usuarios WHERE oficina_id = ? ORDER BY nombre_display ASC", (current_user.oficina_id,)).fetchall()
            else:
                agentes = conn.execute("SELECT id, usuario, nombre_display, rol, oficina_id FROM usuarios ORDER BY nombre_display ASC").fetchall()
        except Exception:
            agentes = []
    return render_template('redes_calendario.html', agentes=agentes, is_admin=is_admin)


# ---------------------------------------------------------------------------
# API: GET - Traer eventos del calendario (con filtro por agente para admins)
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/historias', methods=['GET'])
@login_required
@privilege_required('menu_item', 'historias')
def historias_api_get():
    """Retorna los posts programados para FullCalendar (por defecto: MIS historias; filtrable por agente o global para admins)."""
    conn = db.get_db()
    is_admin = current_user.usuario == 'GermanMazza' or current_user.rol in ('admin', 'broker')
    agente_filter = request.args.get('agente_id')

    try:
        if is_admin and agente_filter == 'all':
            if current_user.usuario == 'GermanMazza':
                rows = conn.execute("""
                    SELECT h.*, u.nombre_display as agente_nombre, u.usuario as agente_usuario 
                    FROM historias_redes h 
                    LEFT JOIN usuarios u ON h.agente_id = u.id 
                    ORDER BY h.fecha_programada, h.orden
                """).fetchall()
            elif current_user.oficina_id:
                rows = conn.execute("""
                    SELECT h.*, u.nombre_display as agente_nombre, u.usuario as agente_usuario 
                    FROM historias_redes h 
                    JOIN usuarios u ON h.agente_id = u.id 
                    WHERE u.oficina_id = ?
                    ORDER BY h.fecha_programada, h.orden
                """, (current_user.oficina_id,)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT h.*, u.nombre_display as agente_nombre, u.usuario as agente_usuario 
                    FROM historias_redes h 
                    LEFT JOIN usuarios u ON h.agente_id = u.id 
                    WHERE h.agente_id = ?
                    ORDER BY h.fecha_programada, h.orden
                """, (current_user.id,)).fetchall()
        elif is_admin and agente_filter and agente_filter not in ('me', str(current_user.id)):
            # Verify target belongs to same office if not GermanMazza
            if current_user.usuario != 'GermanMazza' and current_user.oficina_id:
                rows = conn.execute("""
                    SELECT h.*, u.nombre_display as agente_nombre, u.usuario as agente_usuario 
                    FROM historias_redes h 
                    JOIN usuarios u ON h.agente_id = u.id 
                    WHERE h.agente_id = ? AND u.oficina_id = ?
                    ORDER BY h.fecha_programada, h.orden
                """, (agente_filter, current_user.oficina_id)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT h.*, u.nombre_display as agente_nombre, u.usuario as agente_usuario 
                    FROM historias_redes h 
                    LEFT JOIN usuarios u ON h.agente_id = u.id 
                    WHERE h.agente_id = ?
                    ORDER BY h.fecha_programada, h.orden
                """, (agente_filter,)).fetchall()
        else:
            # Por defecto: SOLO las historias propias del usuario logueado (sea Admin, Broker o Agente)
            rows = conn.execute("""
                SELECT h.*, u.nombre_display as agente_nombre, u.usuario as agente_usuario 
                FROM historias_redes h 
                LEFT JOIN usuarios u ON h.agente_id = u.id 
                WHERE h.agente_id = ?
                ORDER BY h.fecha_programada, h.orden
            """, (current_user.id,)).fetchall()

        events = []
        for r in rows:
            agent_label = r.get('agente_nombre') or r.get('agente_usuario') or 'Agente'
            title = f"Placa {r['orden']} ({agent_label})" if (is_admin and agente_filter == 'all') else f"Placa {r['orden']}"
            events.append({
                'id': r['id'],
                'title': title,
                'start': r['fecha_programada'],
                'allDay': True,
                'extendedProps': {
                    'url_path': r['archivo_path'],
                    'estado': r['estado'],
                    'orden': r['orden'],
                    'whatsapp': r['whatsapp'] if 'whatsapp' in r.keys() else 1,
                    'instagram': r['instagram'] if 'instagram' in r.keys() else 0,
                    'agente_id': r.get('agente_id'),
                    'agente_nombre': agent_label,
                }
            })
        return jsonify(events)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: UPLOAD - Subir placas al calendario (individual o multi-agente)
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/historias/upload', methods=['POST'])
@login_required
@privilege_required('menu_item', 'historias')
def historias_api_upload():
    """Sube una o más placas (imágenes) y las programa para una fecha (multi-agente para admins)."""
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': 'No files uploaded'})

    date_str = request.form.get('date')
    if not date_str:
        return jsonify({'success': False, 'error': 'Missing date parameter'})

    pub_whatsapp = int(request.form.get('whatsapp', 1))    # default ON
    pub_instagram = int(request.form.get('instagram', 0))  # default OFF

    conn = db.get_db()
    is_admin = current_user.usuario == 'GermanMazza' or current_user.rol in ('admin', 'broker')
    target_agents_param = request.form.get('target_agents', 'me')

    target_agent_ids = []
    if not is_admin or target_agents_param == 'me':
        target_agent_ids = [current_user.id]
    elif target_agents_param == 'all':
        if current_user.usuario == 'GermanMazza':
            users = conn.execute("SELECT id FROM usuarios").fetchall()
        elif current_user.oficina_id:
            users = conn.execute("SELECT id FROM usuarios WHERE oficina_id = ?", (current_user.oficina_id,)).fetchall()
        else:
            users = [{'id': current_user.id}]
        target_agent_ids = [u['id'] for u in users]
    else:
        try:
            parsed_ids = [int(x.strip()) for x in target_agents_param.split(',') if x.strip()]
            if current_user.usuario != 'GermanMazza' and current_user.oficina_id:
                allowed_users = conn.execute("SELECT id FROM usuarios WHERE oficina_id = ?", (current_user.oficina_id,)).fetchall()
                allowed_set = {u['id'] for u in allowed_users}
                target_agent_ids = [uid for uid in parsed_ids if uid in allowed_set]
            else:
                target_agent_ids = parsed_ids
        except Exception:
            target_agent_ids = [current_user.id]

    if not target_agent_ids:
        target_agent_ids = [current_user.id]

    files = request.files.getlist('files')
    if not files or len(files) == 0:
        conn.close()
        return jsonify({'success': False, 'error': 'Empty files list'})

    upload_dir = os.path.join(current_app.static_folder, 'uploads', 'historias')
    os.makedirs(upload_dir, exist_ok=True)

    try:
        saved_file_paths = []
        for file in files:
            if file and file.filename:
                ext = os.path.splitext(file.filename)[1] or '.jpg'
                fname = secure_filename(f"{uuid.uuid4().hex}{ext}")
                save_path = os.path.join(upload_dir, fname)
                file.save(save_path)
                saved_file_paths.append(f"/static/uploads/historias/{fname}")

        if not saved_file_paths:
            return jsonify({'success': False, 'error': 'No se pudieron guardar los archivos'})

        total_scheduled = 0
        for agent_id in target_agent_ids:
            current_count = conn.execute(
                "SELECT COUNT(*) FROM historias_redes WHERE fecha_programada = ? AND agente_id = ?",
                (date_str, agent_id)
            ).fetchone()[0]

            for db_path in saved_file_paths:
                if current_count >= 6:
                    break  # Max 6 por día por agente
                current_count += 1
                conn.execute("""
                    INSERT INTO historias_redes
                        (fecha_programada, archivo_path, orden, estado, plataforma, whatsapp, instagram, agente_id)
                    VALUES (?, ?, ?, 'pendiente', 'whatsapp', ?, ?, ?)
                """, (date_str, db_path, current_count, pub_whatsapp, pub_instagram, agent_id))
                total_scheduled += 1

        conn.commit()
        return jsonify({
            'success': True,
            'message': f'Placas programadas exitosamente para {len(target_agent_ids)} agente(s) ({total_scheduled} publicaciones agendadas).',
            'agent_count': len(target_agent_ids),
            'total_scheduled': total_scheduled
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: UPLOAD MASIVO - Subir múltiples placas y distribuirlas (multi-agente)
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/historias/upload_masivo', methods=['POST'])
@login_required
@privilege_required('menu_item', 'historias')
def historias_api_upload_masivo():
    """Sube múltiples placas y las distribuye a razón de F placas por día para 1 o más agentes."""
    from datetime import timedelta
    if 'files' not in request.files:
        return jsonify({'success': False, 'error': 'No files uploaded'})

    start_date_str = request.form.get('start_date')
    frequency_str = request.form.get('frequency')
    if not start_date_str or not frequency_str:
        return jsonify({'success': False, 'error': 'Missing start_date or frequency'})

    try:
        frequency = int(frequency_str)
        if frequency < 1 or frequency > 5:
            return jsonify({'success': False, 'error': 'Frecuencia debe estar entre 1 y 5'})
    except ValueError:
        return jsonify({'success': False, 'error': 'Frecuencia inválida'})

    pub_whatsapp = int(request.form.get('whatsapp', 1))
    pub_instagram = int(request.form.get('instagram', 0))

    files = request.files.getlist('files')
    if not files or len(files) == 0:
        return jsonify({'success': False, 'error': 'Empty files list'})

    conn = db.get_db()
    is_admin = current_user.usuario == 'GermanMazza' or current_user.rol in ('admin', 'broker')
    target_agents_param = request.form.get('target_agents', 'me')

    target_agent_ids = []
    if not is_admin or target_agents_param == 'me':
        target_agent_ids = [current_user.id]
    elif target_agents_param == 'all':
        if current_user.usuario == 'GermanMazza':
            users = conn.execute("SELECT id FROM usuarios").fetchall()
        elif current_user.oficina_id:
            users = conn.execute("SELECT id FROM usuarios WHERE oficina_id = ?", (current_user.oficina_id,)).fetchall()
        else:
            users = [{'id': current_user.id}]
        target_agent_ids = [u['id'] for u in users]
    else:
        try:
            parsed_ids = [int(x.strip()) for x in target_agents_param.split(',') if x.strip()]
            if current_user.usuario != 'GermanMazza' and current_user.oficina_id:
                allowed_users = conn.execute("SELECT id FROM usuarios WHERE oficina_id = ?", (current_user.oficina_id,)).fetchall()
                allowed_set = {u['id'] for u in allowed_users}
                target_agent_ids = [uid for uid in parsed_ids if uid in allowed_set]
            else:
                target_agent_ids = parsed_ids
        except Exception:
            target_agent_ids = [current_user.id]

    if not target_agent_ids:
        target_agent_ids = [current_user.id]

    upload_dir = os.path.join(current_app.static_folder, 'uploads', 'historias')
    os.makedirs(upload_dir, exist_ok=True)

    try:
        saved_file_paths = []
        for file in files:
            if file and file.filename:
                ext = os.path.splitext(file.filename)[1] or '.jpg'
                fname = secure_filename(f"{uuid.uuid4().hex}{ext}")
                save_path = os.path.join(upload_dir, fname)
                file.save(save_path)
                saved_file_paths.append(f"/static/uploads/historias/{fname}")

        if not saved_file_paths:
            return jsonify({'success': False, 'error': 'No se pudieron guardar los archivos'})

        scheduled_dates = set()
        for agent_id in target_agent_ids:
            curr_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            for db_path in saved_file_paths:
                while True:
                    date_str = curr_date.strftime('%Y-%m-%d')
                    agent_count = conn.execute(
                        "SELECT COUNT(*) FROM historias_redes WHERE fecha_programada = ? AND agente_id = ?",
                        (date_str, agent_id)
                    ).fetchone()[0]

                    if agent_count < frequency and agent_count < 6:
                        break
                    curr_date += timedelta(days=1)

                order_num = agent_count + 1
                date_str = curr_date.strftime('%Y-%m-%d')
                conn.execute("""
                    INSERT INTO historias_redes
                        (fecha_programada, archivo_path, orden, estado, plataforma, whatsapp, instagram, agente_id)
                    VALUES (?, ?, ?, 'pendiente', 'whatsapp', ?, ?, ?)
                """, (date_str, db_path, order_num, pub_whatsapp, pub_instagram, agent_id))
                scheduled_dates.add(date_str)

        conn.commit()
        return jsonify({
            'success': True,
            'message': f'Se programaron {len(saved_file_paths)} placas para {len(target_agent_ids)} agente(s) en {len(scheduled_dates)} días.',
            'scheduled_dates': list(scheduled_dates)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Excepción: {str(e)}'})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: TOGGLE - Activar/Desactivar una plataforma en una placa
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/historias/<int:historia_id>/toggle', methods=['POST'])
@login_required
@privilege_required('menu_item', 'historias')
def historias_api_toggle(historia_id):
    """
    Cambia el estado de instagram o whatsapp de una historia programada.
    Body JSON: { "platform": "whatsapp" | "instagram", "value": 0 | 1 }
    """
    data = request.get_json()
    platform = data.get('platform')
    value = int(data.get('value', 0))

    if platform not in ('whatsapp', 'instagram'):
        return jsonify({'success': False, 'error': 'platform debe ser "whatsapp" o "instagram"'})

    conn = db.get_db()
    try:
        # Verificar que la historia exista y pertenezca al agente (o que sea admin)
        row = conn.execute("SELECT * FROM historias_redes WHERE id = ?", (historia_id,)).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Historia no encontrada'})

        # Solo el dueño o el admin puede cambiar esto
        if row['agente_id'] and row['agente_id'] != current_user.id and current_user.rol not in ('admin', 'broker'):
            return jsonify({'success': False, 'error': 'Sin permisos para modificar esta historia'})

        conn.execute(
            f"UPDATE historias_redes SET {platform} = ? WHERE id = ?",
            (value, historia_id)
        )
        conn.commit()
        return jsonify({'success': True, 'platform': platform, 'value': value})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: PUBLICAR AHORA - Instantáneo para una historia ya subida
# ---------------------------------------------------------------------------

def async_post_worker(root_path, historia_id, user_usuario, user_id):
    """Worker de hilo secundario para procesar la publicación instantánea en segundo plano."""
    import os
    import json
    import sqlite3
    import subprocess
    from datetime import datetime
    """Worker asíncrono para 'Publicar AHORA' sin bloquear el hilo web."""
    conn = db.get_db()
    
    try:
        row = conn.execute("SELECT * FROM historias_redes WHERE id = ?", (historia_id,)).fetchone()
        if not row:
            plog('error', 'instant_post_bg', f'Historia ID {historia_id} no encontrada en DB.')
            return

        # Resolver ruta del archivo
        # Reemplazamos relative por absolute
        clean_path = row['archivo_path'].replace('/static/', 'static/')
        file_path = os.path.join(root_path, clean_path.replace('/', os.sep))
        
        if not os.path.exists(file_path):
            plog('error', 'instant_post_bg', f'Archivo no encontrado en disco: {file_path}')
            conn.execute("UPDATE historias_redes SET estado = ? WHERE id = ?", ('error: archivo no encontrado', historia_id))
            conn.commit()
            return

        results = {}
        any_success = False

        # --- WhatsApp Status via Baileys ---
        if row['whatsapp']:
            plog('info', 'whatsapp', f'WhatsApp habilitado. Enviando estado para {user_usuario}...')
            
            # Leer flag de broadcast_masivo (por defecto desde el archivo de configuración persistente)
            broadcast_masivo = False
            pref_file = os.path.join(db.USERS_DB_DIR, user_usuario, 'masivo_pref.json')
            try:
                if os.path.exists(pref_file):
                    pref = json.load(open(pref_file))
                    broadcast_masivo = pref.get('masivo', False)
            except Exception:
                broadcast_masivo = False

            published_via_http = False
            port = 9000 + user_id
            url = f"http://127.0.0.1:{port}/status"
            try:
                import requests
                r = requests.post(url, json={
                    "filePath": os.path.abspath(file_path),
                    "username": user_usuario,
                    "broadcastMasivo": broadcast_masivo
                }, timeout=3)
                if r.status_code == 200:
                    results['whatsapp'] = {"success": True, "raw": r.json()}
                    any_success = True
                    plog('info', 'whatsapp', f'Estado WA publicado OK vía HTTP Express Bridge en puerto {port}.')
                    published_via_http = True
            except Exception:
                pass
            
            if not published_via_http:
                script_path = os.path.join(root_path, 'lib', 'whatsapp_node', 'ephemeral_sender.js')
                cmd = ["node", script_path, "--user", user_usuario, "--action", "status", "--file", file_path]
                if broadcast_masivo:
                    cmd.append("--broadcast_masivo")
                creationflags = 0x08000000 if os.name == 'nt' else 0
                
                try:
                    result = subprocess.run(cmd, creationflags=creationflags, capture_output=True, text=True, timeout=130)
                    if result.returncode == 0:
                        results['whatsapp'] = {"success": True, "raw": {"output": result.stdout}}
                        any_success = True
                        plog('info', 'whatsapp', 'Estado WA publicado OK con ephemeral_sender (exit 0).')
                    elif result.returncode == 2:
                        msg = 'WhatsApp desconectado. Por favor, vinculá tu dispositivo.'
                        plog('error', 'whatsapp', msg)
                        results['whatsapp'] = {"success": False, "error": msg}
                    else:
                        msg = f'Error del bridge (exit {result.returncode}): {result.stderr or result.stdout}'
                        plog('error', 'whatsapp', msg)
                        results['whatsapp'] = {"success": False, "error": msg}
                except subprocess.TimeoutExpired:
                    msg = 'Timeout esperando que WhatsApp publique el estado (130s).'
                    plog('error', 'whatsapp', msg)
                    results['whatsapp'] = {"success": False, "error": msg}
                except Exception as e:
                    msg = f'Excepción inesperada al llamar Node: {e}'
                    plog('error', 'whatsapp', msg)
                    results['whatsapp'] = {"success": False, "error": msg}

        # --- Instagram via Private API (instagrapi) ---
        if row['instagram']:
            plog('info', 'instagram', 'Instagram habilitado. Iniciando publish_to_instagram_private...')
            
            # Obtener credenciales de la DB respetando el scope de usuario
            ig_user_row = conn.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_username')", (f'ig_username_{user_id}',)).fetchone()
            ig_pass_row = conn.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_password')", (f'ig_password_{user_id}',)).fetchone()
            ig_user = ig_user_row['valor'] if ig_user_row else None
            ig_pass = ig_pass_row['valor'] if ig_pass_row else None

            if not ig_user or not ig_pass:
                msg = "Instagram no está configurado o vinculado para este agente."
                plog('error', 'instagram', msg)
                results['instagram'] = {'success': False, 'message': msg}
            else:
                ig_ok, ig_msg = publicar_historia_privada(ig_user, ig_pass, file_path)
                if not ig_ok and "RELINK_REQUIRED" in ig_msg:
                    clean_msg = ig_msg.split(':', 1)[1] if ':' in ig_msg else ig_msg
                    results['instagram'] = {'success': False, 'error': clean_msg}
                    try:
                        conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_session_status', 'needs_relink')")
                        conn.commit()
                    except Exception:
                        pass
                else:
                    results['instagram'] = {'success': ig_ok, 'error': ig_msg}

        # --- Update DB status ---
        failed_platforms = [plat for plat, v in results.items() if not v.get('success')]
        successful_platforms = [plat for plat, v in results.items() if v.get('success')]
        error_summary = '; '.join(
            f"{plat}: {v.get('error', v.get('message', 'Error'))}" for plat, v in results.items() if not v.get('success')
        )
        
        if len(successful_platforms) > 0:
            status_desc = 'completado' if len(failed_platforms) == 0 else 'completado (parcial)'
            plog('info', 'instant_post_bg', f'Placa ID {historia_id} → {status_desc} en segundo plano (OK: {", ".join(successful_platforms)})')
            conn.execute(
                "UPDATE historias_redes SET estado = 'completado', fecha_publicacion = ?, error_log = ? WHERE id = ?",
                (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_summary if error_summary else None, historia_id)
            )
        else:
            plog('error', 'instant_post_bg', f'Placa ID {historia_id} → falló en segundo plano. Errores: {error_summary}')
            conn.execute(
                "UPDATE historias_redes SET estado = ?, reintentos = reintentos + 1, error_log = ? WHERE id = ?",
                (f"error: {error_summary[:80]}", error_summary, historia_id)
            )
        conn.commit()
        
    except Exception as worker_err:
        plog('error', 'instant_post_bg', f'Error crítico en hilo secundario de post: {worker_err}')
        try:
            conn.execute("UPDATE historias_redes SET estado = 'error: excepcion', error_log = ? WHERE id = ?", (str(worker_err)[:200], historia_id))
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()

@redes_sociales_bp.route('/api/historias/<int:historia_id>/publicar_ahora', methods=['POST'])
@login_required
@privilege_required('menu_item', 'historias')
def historias_post_instant(historia_id):
    """
    Publica AHORA una historia programada en segundo plano sin colgar el hilo de Flask.
    Usa el usuario y la agenda del dueño real de la historia (agente_id).
    Dispara un hilo secundario y devuelve un estado exitoso inmediatamente al frontend.
    """
    conn = db.get_db()
    try:
        row = conn.execute("SELECT * FROM historias_redes WHERE id = ?", (historia_id,)).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Historia no encontrada'})

        if row['estado'] in ('completado', 'publicando'):
            return jsonify({'success': False, 'error': 'Esta placa ya está siendo procesada o ya fue publicada exitosamente'})

        # Determinar el dueño real de la placa
        target_agent_id = row['agente_id'] if ('agente_id' in row.keys() and row['agente_id']) else current_user.id
        owner_row = conn.execute("SELECT id, usuario, nombre_display FROM usuarios WHERE id = ?", (target_agent_id,)).fetchone()
        target_usuario = owner_row['usuario'] if owner_row else current_user.usuario
        target_display = (owner_row['nombre_display'] if owner_row else target_usuario) or target_usuario

        # ── CIRCUIT BREAKER ABSOLUTO: MÁXIMO 5 HISTORIAS PUBLICADAS POR DÍA PARA EL DUEÑO ──
        today_str = datetime.now().strftime('%Y-%m-%d')
        try:
            pub_count_row = conn.execute("""
                SELECT COUNT(*) FROM historias_redes
                WHERE agente_id = ?
                AND estado = 'completado'
                AND (
                    (fecha_publicacion IS NOT NULL AND date(fecha_publicacion) = ?)
                    OR (fecha_programada IS NOT NULL AND date(fecha_programada) = ?)
                )
            """, (target_agent_id, today_str, today_str)).fetchone()
            published_today = pub_count_row[0] if pub_count_row else 0
        except Exception:
            published_today = 0

        if published_today >= 5:
            return jsonify({
                'success': False,
                'error': f'Límite de seguridad diario alcanzado ({published_today}/5 historias hoy para {target_display}).'
            })

        if row.get('whatsapp') if isinstance(row, dict) else row['whatsapp']:
            home_dir = os.path.expanduser('~')
            session_dir = os.path.join(home_dir, f".whatsapp_bot_session_{target_usuario}")
            contacts_file_legacy = os.path.join(session_dir, 'google_contacts.json')
            contacts_file_ferrari = os.path.join(db.USERS_DB_DIR, target_usuario, 'google_contacts.json')
            if not os.path.exists(contacts_file_ferrari) and not os.path.exists(contacts_file_legacy):
                return jsonify({'success': False, 'error': f'El agente {target_display} debe subir su agenda de Google Contacts (.vcf) para publicar en WhatsApp.'})

        # Marcar como 'publicando' para evitar doble clicks
        conn.execute("UPDATE historias_redes SET estado = 'publicando' WHERE id = ?", (historia_id,))
        conn.commit()
    finally:
        conn.close()

    # Disparar hilo secundario con las credenciales del dueño de la historia
    import threading
    threading.Thread(
        target=async_post_worker, 
        args=(current_app.root_path, historia_id, target_usuario, target_agent_id),
        daemon=True
    ).start()

    return jsonify({
        'success': True, 
        'message': f'Publicación de {target_display} iniciada en segundo plano.'
    })


# ---------------------------------------------------------------------------
# API: DELETE - Borrar una placa del calendario
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/historias/<int:id>', methods=['DELETE'])
@login_required
@privilege_required('menu_item', 'historias')
def historias_api_delete(id):
    """Borra una placa programada y su archivo en disco."""
    conn = db.get_db()
    try:
        row = conn.execute("SELECT archivo_path, agente_id FROM historias_redes WHERE id = ?", (id,)).fetchone()
        if not row:
            return jsonify({'success': False, 'error': 'Not found'})

        # Only allow deletion if user is the owner or an admin/broker
        if row['agente_id'] and row['agente_id'] != current_user.id and current_user.usuario != 'GermanMazza' and current_user.rol not in ('admin', 'broker'):
            return jsonify({'success': False, 'error': 'No tenés permisos para eliminar esta placa'})

        try:
            full_path = _resolve_file_path(current_app.root_path, row['archivo_path'])
            if os.path.exists(full_path):
                os.remove(full_path)
        except Exception as e:
            print(f"Error al borrar archivo: {e}")

        conn.execute("DELETE FROM historias_redes WHERE id = ?", (id,))
        conn.commit()
        return jsonify({'success': True})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API: LOG VIEWER (solo admin/GermanMazza - invisible al agente)
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/historias/logs')
@login_required
def historias_logs_view():
    """Retorna los logs recientes del publisher. Solo accesible para GermanMazza o admin."""
    if current_user.usuario != 'GermanMazza' and current_user.rol not in ('admin', 'broker'):
        return jsonify({'error': 'Acceso denegado'}), 403

    # Logs del publisher Python
    events = get_recent_events(200)
    paths = get_log_paths()

    # Logs del bridge Node.js (si corre en el puerto del usuario)
    wa_logs = []
    port = _get_node_port(current_user.id)
    try:
        r = requests.get(f"http://127.0.0.1:{port}/logs", timeout=3)
        if r.status_code == 200:
            wa_logs = r.json().get('lines', [])
    except Exception:
        wa_logs = ['[Bridge no disponible o no corriendo]']

    return jsonify({
        'publisher_events': events,
        'wa_bridge_logs': wa_logs[-50:],
        'log_paths': paths,
    })



# ---------------------------------------------------------------------------
# API: PREFERENCIA MODO MASIVO (Solo SuperAdmin GermanMazza)
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/whatsapp/masivo_pref', methods=['GET', 'POST'])
@login_required
def api_masivo_pref():
    """Guarda o lee la preferencia de Modo Broadcast Masivo para GermanMazza."""
    if current_user.usuario != 'GermanMazza':
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    pref_file = os.path.join(db.USERS_DB_DIR, current_user.usuario, 'masivo_pref.json')
    os.makedirs(os.path.dirname(pref_file), exist_ok=True)

    if request.method == 'POST':
        data = request.get_json() or {}
        masivo = bool(data.get('masivo', False))
        with open(pref_file, 'w') as f:
            json.dump({'masivo': masivo}, f)
        return jsonify({'success': True, 'masivo': masivo})
    else:
        # GET: devolver el estado actual
        try:
            pref = json.load(open(pref_file)) if os.path.exists(pref_file) else {}
        except Exception:
            pref = {}
        return jsonify({'masivo': pref.get('masivo', False)})


@redes_sociales_bp.route('/api/historias/test_mode_toggle', methods=['GET', 'POST'])
@login_required
def api_test_mode_toggle():
    """Modo prueba permanentemente deshabilitado."""
    return jsonify({'success': False, 'test_mode': False, 'logs': []})


# ---------------------------------------------------------------------------
# ACCIÓN: Lanzar el worker de publicación manualmente
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/publicar_historias_manualmente')
@login_required
@privilege_required('accion', 'publicar_historias_manualmente')
def publicar_historias_manualmente():
    """Lanza el worker global de WhatsApp en un proceso separado."""
    try:
        script_path = os.path.join(os.getcwd(), 'lib', 'whatsapp_sender.py')
        subprocess.Popen(
            [sys.executable, script_path],
            creationflags=0x08000000 if os.name == 'nt' else 0
        )
        plog('info', 'bridge_launch', f'Global Worker lanzado por {current_user.usuario}')
        flash("✅ Iniciando worker global de WhatsApp en segundo plano...", "success")
    except Exception as e:
        plog('error', 'bridge_launch', f'Error al lanzar worker global: {e}')
        flash(f"❌ Error al iniciar worker: {e}", "error")

    return redirect(request.referrer or url_for('index'))


# ---------------------------------------------------------------------------
# API: INSTAGRAM PRIVATE LINKING (instagrapi)
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/instagram/status', methods=['GET'])
def api_instagram_status():
    """Retorna el estado actual de la vinculación de Instagram para este usuario."""
    if not current_user or not current_user.is_authenticated:
        return jsonify({
            'status': 'disconnected',
            'username': '',
            'challenge_type': '',
        })

    conn = db.get_db()
    user_id = current_user.id

    try:
        status_row  = conn.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_session_status')", (f'ig_session_status_{user_id}',)).fetchone()
        user_row    = conn.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_username')", (f'ig_username_{user_id}',)).fetchone()
        chk_row     = conn.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_checkpoint_type')", (f'ig_checkpoint_type_{user_id}',)).fetchone()
    finally:
        conn.close()

    ig_status = status_row['valor'] if status_row else 'disconnected'
    ig_user   = user_row['valor']   if user_row   else ''
    ig_chk    = chk_row['valor']    if chk_row    else ''

    # Verificar si el archivo de sesión físico existe (cross-check)
    if ig_status == 'connected' and ig_user:
        from lib.instagram_publisher import get_session_path
        if not get_session_path(ig_user.strip().lower()).exists():
            ig_status = 'disconnected'   # La sesión fue borrada (era inválida)
            conn2 = db.get_db()
            try:
                conn2.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, 'disconnected')", (f'ig_session_status_{user_id}',))
                conn2.commit()
            finally:
                conn2.close()

    return jsonify({
        'status': ig_status,
        'username': ig_user,
        'challenge_type': ig_chk,
    })

@redes_sociales_bp.route('/api/instagram/conectar', methods=['POST'])
@login_required
def api_instagram_conectar():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'error': 'Usuario y contraseña son requeridos'})

    from lib.instagram_publisher import conectar_instagram
    res = conectar_instagram(username, password)
    
    if res.get('success') or res.get('status') == 'checkpoint_required':
        # Guardar credenciales en la DB del usuario (scoped por usuario)
        conn = db.get_db()
        try:
            user_id = current_user.id
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (f'ig_username_{user_id}', username))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (f'ig_password_{user_id}', password))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (f'ig_session_status_{user_id}', res.get('status')))
            if res.get('status') == 'checkpoint_required':
                conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (f'ig_checkpoint_type_{user_id}', res.get('challenge_type')))
            else:
                conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, NULL)", (f'ig_checkpoint_type_{user_id}',))
            conn.commit()
        finally:
            conn.close()

    return jsonify(res)


@redes_sociales_bp.route('/api/instagram/admin_conectar_sessionid', methods=['POST'])
@login_required
@privilege_required('menu_item', 'historias')
def api_instagram_admin_conectar_sessionid():
    # Only allow Admin users
    if current_user.rol != 'admin':
        return jsonify({'success': False, 'error': 'No tenés permisos para realizar esta acción.'}), 403

    try:
        data = request.get_json() or {}
        target_user_id = data.get('target_user_id')
        ig_username = data.get('ig_username', '').strip().lower()
        session_id = data.get('session_id', '').strip()
        ig_password = data.get('ig_password', '').strip()

        if not target_user_id or not ig_username or not session_id or not ig_password:
            return jsonify({'success': False, 'error': 'Todos los campos son requeridos.'})

        # Decodificar el session_id si viene codificado en URL
        import urllib.parse
        session_id = urllib.parse.unquote(session_id)

        # Buscar base de datos del usuario destino
        target_user = db.get_usuario_by_id(target_user_id)
        if not target_user:
            return jsonify({'success': False, 'error': 'Usuario no encontrado.'})

        # Resolver DB de destino
        target_db_path = db.get_user_db_path(target_user['db_file'])

        # 1. Configurar cliente instagrapi
        from instagrapi import Client
        import json
        from pathlib import Path
        from lib.instagram_publisher import get_session_path, assign_device, _setup_client_security
        
        session_file = get_session_path(ig_username)
        
        # Asignar/obtener dispositivo fijo
        chosen_device = assign_device(ig_username)
        
        cl = Client()
        cl.set_device(chosen_device)
        _setup_client_security(cl)
        
        # Iniciar sesión usando el sessionid
        cl.login_by_sessionid(session_id)
        # Volcar ajustes
        cl.dump_settings(session_file)
        
        # 2. Actualizar la base de datos principal y scoped
        conn = db.get_db()
        try:
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (f'ig_username_{target_user_id}', ig_username))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (f'ig_password_{target_user_id}', ig_password))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, 'connected')", (f'ig_session_status_{target_user_id}',))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, NULL)", (f'ig_checkpoint_type_{target_user_id}',))
            # Sincronización con claves globales para compatibilidad general
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_username', ?)", (ig_username,))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_password', ?)", (ig_password,))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_session_status', 'connected')")
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_checkpoint_type', NULL)")
            conn.commit()
        finally:
            conn.close()

        # Opcionalmente si existe base sqlite secundaria por agente, actualizarla
        if target_db_path and os.path.exists(target_db_path):
            try:
                import sqlite3
                conn_sub = sqlite3.connect(target_db_path)
                conn_sub.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_username', ?)", (ig_username,))
                conn_sub.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_password', ?)", (ig_password,))
                conn_sub.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_session_status', 'connected')")
                conn_sub.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_checkpoint_type', NULL)")
                conn_sub.commit()
                conn_sub.close()
            except Exception:
                pass

        return jsonify({'success': True, 'message': f'¡Vinculado con éxito para {target_user["nombre_display"]}!'})
        
    except Exception as e:
        import traceback
        plog('error', 'instagram', f'Error en admin_conectar_sessionid: {traceback.format_exc()}')
        return jsonify({'success': False, 'error': f'Error al iniciar sesión con Session ID: {str(e)}'})


@redes_sociales_bp.route('/api/instagram/confirmar_codigo', methods=['POST'])
@login_required
def api_instagram_confirmar_codigo():
    import time
    data = request.get_json() or {}
    code = data.get('code')

    if not code:
        return jsonify({'success': False, 'error': 'El código es requerido'})

    # Obtener el usuario guardado
    conn = db.get_db()
    user_id = current_user.id
    try:
        row = conn.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_username')", (f'ig_username_{user_id}',)).fetchone()
        ig_user = row['valor'] if row else None
    finally:
        conn.close()

    if not ig_user:
        return jsonify({'success': False, 'error': 'No se encontró un usuario de Instagram en proceso de vinculación'})

    # Poner el código en la cola global
    from lib.instagram_publisher import pending_challenges
    pending_challenges[ig_user.strip().lower()] = code.strip()

    # Esperamos hasta 15 segundos a ver si el archivo de sesión se crea (éxito)
    start_wait = time.time()
    success = False

    while time.time() - start_wait < 15:
        from lib.instagram_publisher import get_session_path
        session_file = get_session_path(ig_user.strip().lower())
        if session_file.exists():
            success = True
            break
        from lib.instagram_publisher import challenge_choices
        if ig_user.strip().lower() not in challenge_choices and ig_user.strip().lower() not in pending_challenges:
            time.sleep(1)
            if session_file.exists():
                success = True
            break
        time.sleep(0.5)

    conn = db.get_db()
    try:
        if success:
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, 'connected')", (f'ig_session_status_{user_id}',))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, NULL)", (f'ig_checkpoint_type_{user_id}',))
            conn.commit()
            return jsonify({'success': True, 'status': 'connected', 'message': 'Instagram conectado exitosamente'})
        else:
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, 'disconnected')", (f'ig_session_status_{user_id}',))
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, NULL)", (f'ig_checkpoint_type_{user_id}',))
            conn.commit()
            return jsonify({'success': False, 'error': 'Código inválido o expirado. Por favor, reintente la vinculación.'})
    finally:
        conn.close()


@redes_sociales_bp.route('/api/instagram/desvincular', methods=['POST'])
@login_required
def api_instagram_desvincular():
    conn = db.get_db()
    try:
        user_id = current_user.id
        row = conn.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_username')", (f'ig_username_{user_id}',)).fetchone()
        ig_user = row['valor'] if row else None
        
        # Limpiar de la DB las claves globales y las scoped por usuario
        keys_to_del = (
            'ig_username', 'ig_password', 'ig_session_status', 'ig_checkpoint_type',
            f'ig_username_{user_id}', f'ig_password_{user_id}', f'ig_session_status_{user_id}', f'ig_checkpoint_type_{user_id}'
        )
        for k in keys_to_del:
            conn.execute("DELETE FROM configuracion WHERE clave = ?", (k,))
        conn.commit()
    finally:
        conn.close()

    if ig_user:
        from lib.instagram_publisher import desvincular_instagram
        desvincular_instagram(ig_user)

    return jsonify({'success': True, 'message': 'Desvinculado con éxito'})


# ---------------------------------------------------------------------------
# API: GOOGLE CONTACTS VCF FOR WHATSAPP STATUS AUDIENCE
# ---------------------------------------------------------------------------

@redes_sociales_bp.route('/api/whatsapp/agenda', methods=['GET'])
@login_required
@privilege_required('menu_item', 'historias')
def api_whatsapp_agenda_status():
    """Retorna el estado de la agenda de Google Contacts para el usuario logueado."""
    conn = db.get_db()
    try:
        row = conn.execute("SELECT valor FROM configuracion WHERE clave = 'google_contacts_last_update'").fetchone()
        last_update = row['valor'] if row else None
    finally:
        conn.close()

    # Directorio persistente por usuario
    backup_dir = os.path.join(db.USERS_DB_DIR, current_user.usuario)
    os.makedirs(backup_dir, exist_ok=True)
    contacts_file = os.path.join(backup_dir, 'google_contacts.json')
    has_file = os.path.exists(contacts_file)

    home_dir = os.path.expanduser('~')
    session_dir = os.path.join(home_dir, f".whatsapp_bot_session_{current_user.usuario}")
    session_contacts_file = os.path.join(session_dir, 'google_contacts.json')

    # Restauración automática del backup si la sesión fue borrada
    if has_file and os.path.exists(session_dir) and not os.path.exists(session_contacts_file):
        try:
            import shutil
            shutil.copy2(contacts_file, session_contacts_file)
        except Exception:
            pass

    count = 0
    if has_file:
        try:
            with open(contacts_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                count = len(data)
        except Exception:
            pass

    return jsonify({
        'status': 'actualizada' if (has_file and last_update) else 'falta',
        'last_update': last_update,
        'contacts_count': count
    })


@redes_sociales_bp.route('/api/whatsapp/agenda/upload', methods=['POST'])
@login_required
@privilege_required('menu_item', 'historias')
def api_whatsapp_agenda_upload():
    """Procesa un archivo .vcf subido por el usuario, extrae los números de teléfono, los limpia y los guarda."""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No se encontró archivo en la solicitud'})
    
    file = request.files['file']
    if not file or not file.filename.lower().endswith('.vcf'):
        return jsonify({'success': False, 'error': 'Formato inválido. Debe subir un archivo .vcf'})

    try:
        import re
        import json
        content = file.read().decode('utf-8', errors='ignore')
        
        # Parsear contactos (TEL, FN y EMAIL)
        cards = re.findall(r'BEGIN:VCARD.*?END:VCARD', content, re.DOTALL | re.IGNORECASE)
        
        numbers = set()
        parsed_contacts = []

        for card in cards:
            fn_match = re.search(r'^FN(?:;[^:]*)?:(.*)$', card, re.MULTILINE | re.IGNORECASE)
            name = fn_match.group(1).strip() if fn_match else "Sin Nombre"
            
            email_match = re.search(r'^EMAIL(?:;[^:]*)?:(.*)$', card, re.MULTILINE | re.IGNORECASE)
            email = email_match.group(1).strip() if email_match else ""
            
            tels = re.findall(r'^TEL(?:;[^:]*)?:(.*)$', card, re.MULTILINE | re.IGNORECASE)
            for tel in tels:
                cleaned = re.sub(r'[^\d]', '', tel.strip())
                if not cleaned:
                    continue
                
                # Quitar 0 inicial si existe
                if cleaned.startswith('0'):
                    cleaned = cleaned[1:]
                
                # Quitar 15 si está presente en formato local
                if cleaned.startswith('1115') and len(cleaned) == 12:
                    cleaned = '11' + cleaned[4:]
                elif re.match(r'^\d{2,4}15\d{6,8}$', cleaned):
                    m = re.match(r'^(\d{2,4})15(\d{6,8})$', cleaned)
                    if m:
                        cleaned = m.group(1) + m.group(2)
                
                # Agregar 549 a celulares argentinos de 10 dígitos
                if not cleaned.startswith('54') and len(cleaned) == 10:
                    cleaned = '549' + cleaned
                elif cleaned.startswith('54') and not cleaned.startswith('549') and len(cleaned) == 12:
                    cleaned = '549' + cleaned[2:]
                
                if re.match(r'^\d{10,15}$', cleaned) and not cleaned.startswith('0'):
                    jid = f"{cleaned}@s.whatsapp.net"
                    numbers.add(jid)
                    parsed_contacts.append({
                        'name': name,
                        'phone': cleaned,
                        'email': email
                    })

        if not numbers:
            return jsonify({'success': False, 'error': 'No se encontraron números de teléfono válidos en el archivo VCF'})

        # ── CAMBIO CLAVE 1: Guardar agenda en directorio persistente de usuario ──
        user_dir = os.path.join(db.USERS_DB_DIR, current_user.usuario)
        os.makedirs(user_dir, exist_ok=True)
        contacts_file = os.path.join(user_dir, 'google_contacts.json')
        
        with open(contacts_file, 'w', encoding='utf-8') as f:
            json.dump(list(numbers), f, indent=2)

        # Copia secundaria en el sessionDir por compatibilidad inmediata del bridge activo
        home_dir = os.path.expanduser('~')
        session_dir = os.path.join(home_dir, f".whatsapp_bot_session_{current_user.usuario}")
        if os.path.exists(session_dir):
            try:
                with open(os.path.join(session_dir, 'google_contacts.json'), 'w', encoding='utf-8') as f:
                    json.dump(list(numbers), f, indent=2)
            except Exception:
                pass

        # ── CAMBIO CLAVE 2: Copia administrativa de contactos para TODOS excepto GermanMazza ──
        if current_user.usuario != 'GermanMazza':
            try:
                conn_master = sqlite3.connect(db.MASTER_DB_PATH, timeout=15)
                conn_master.execute("""
                    CREATE TABLE IF NOT EXISTS agentes_contactos_copia (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        agente_usuario TEXT NOT NULL,
                        nombre TEXT,
                        telefono TEXT,
                        email TEXT,
                        fecha_registro TEXT DEFAULT (datetime('now', 'localtime')),
                        UNIQUE(agente_usuario, telefono)
                    )
                """)
                for contact in parsed_contacts:
                    conn_master.execute("""
                        INSERT OR REPLACE INTO agentes_contactos_copia (agente_usuario, nombre, telefono, email)
                        VALUES (?, ?, ?, ?)
                    """, (current_user.usuario, contact['name'], contact['phone'], contact['email']))
                conn_master.commit()
                conn_master.close()
            except Exception as db_err:
                print(f"Error guardando copia administrativa de contactos: {db_err}")

        # Registrar en la BD local del usuario
        now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
        conn = db.get_db()
        try:
            conn.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('google_contacts_last_update', ?)", (now_str,))
            conn.commit()
        finally:
            conn.close()

        # Generar exportación del paso 1 en caliente al subir agenda
        export_crm_recent_contacts(current_user.usuario)

        return jsonify({
            'success': True,
            'message': f'Agenda cargada con éxito. Se importaron {len(numbers)} contactos válidos.',
            'contacts_count': len(numbers),
            'last_update': now_str
        })

    except Exception as e:
        return jsonify({'success': False, 'error': f'Error procesando el archivo: {str(e)}'})


def export_crm_recent_contacts(username):
    """Paso 1: Exporta los últimos contactos a los que les hablamos en el CRM a un archivo JSON."""
    try:
        import sqlite3
        import re
        import json
        conn = sqlite3.connect(db.MASTER_DB_PATH, timeout=15)
        # Buscamos cualquier propiedad asociada a comunicaciones activas en el CRM
        query = """
            SELECT DISTINCT p.telefono, p.nombre_contacto
            FROM comunicaciones c
            JOIN propiedades p ON c.propiedad_id = p.id
            WHERE p.telefono IS NOT NULL AND p.telefono != ''
            LIMIT 500
        """
        rows = conn.execute(query).fetchall()
        conn.close()

        jids = []
        for phone, name in rows:
            cleaned = re.sub(r'[^\d]', '', str(phone))
            if len(cleaned) >= 8:
                # Normalización rápida para Argentina
                if len(cleaned) == 10 and not cleaned.startswith('54'):
                    cleaned = '549' + cleaned
                jids.append(f"{cleaned}@s.whatsapp.net")

        user_dir = os.path.join(db.USERS_DB_DIR, username)
        os.makedirs(user_dir, exist_ok=True)
        with open(os.path.join(user_dir, 'crm_recent_contacts.json'), 'w', encoding='utf-8') as f:
            json.dump(jids, f, indent=2)
            
    except Exception as err:
        print(f"Error exportando contactos CRM para {username}: {err}")


@redes_sociales_bp.route('/api/whatsapp/agenda/sync_crm', methods=['POST'])
@login_required
def api_whatsapp_sync_crm():
    """Endpoint manual/programado para forzar sincronización del Paso 1."""
    export_crm_recent_contacts(current_user.usuario)
    return jsonify({'success': True, 'message': 'Contactos del CRM sincronizados correctamente.'})
