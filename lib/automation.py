"""
Automation module - Handles automated email sending and task triggering
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import db
from datetime import datetime
import threading

def _get_smtp_config_for_agent(agente_id=None):
    """Fetch SMTP config for a specific agent (by ID).
    Falls back gracefully:
    1. If agente_id is None, try request context (logged-in user)
    2. Try agent-specific scoped keys (smtp_host_<id>, etc.)
    3. Fallback to bare global keys (smtp_host, etc.)
    4. Fallback to primary admin user (GermanMazza / id=4)
    """
    if agente_id is None:
        try:
            from flask import has_request_context
            from flask_login import current_user
            if has_request_context() and current_user and current_user.is_authenticated:
                agente_id = current_user.id
        except Exception:
            pass

    target_id = agente_id
    try:
        conn = db.get_db()
        result = {}
        for key in ('smtp_host', 'smtp_port', 'smtp_user', 'smtp_password'):
            val = None
            # 1. Try agent scoped key if target_id is present
            if target_id is not None:
                scoped_key = f"{key}_{target_id}"
                row = conn.execute(
                    "SELECT valor FROM configuracion WHERE clave = ?", (scoped_key,)
                ).fetchone()
                if row and row['valor'] and str(row['valor']).strip():
                    val = str(row['valor']).strip()
            
            # 2. Try bare key
            if not val:
                row = conn.execute(
                    "SELECT valor FROM configuracion WHERE clave = ?", (key,)
                ).fetchone()
                if row and row['valor'] and str(row['valor']).strip():
                    val = str(row['valor']).strip()

            # 3. Fallback to default admin agent (GermanMazza = 4)
            if not val and target_id != 4:
                row = conn.execute(
                    "SELECT valor FROM configuracion WHERE clave = ?", (f"{key}_4",)
                ).fetchone()
                if row and row['valor'] and str(row['valor']).strip():
                    val = str(row['valor']).strip()

            result[key] = val
        conn.close()
        return result
    except Exception as e:
        print(f"  ⚠️ Error fetching SMTP config for agent {agente_id}: {e}")
        return {}


def _get_agent_profile(agente_id=None):
    """Fetch agent profile keys (nombre, telefono, etc.) for background jobs."""
    profile_keys = ('agente_nombre', 'agente_telefono', 'agente_email', 'agente_inmobiliaria')
    if agente_id is None:
        try:
            from flask import has_request_context
            from flask_login import current_user
            if has_request_context() and current_user and current_user.is_authenticated:
                agente_id = current_user.id
        except Exception:
            pass

    target_id = agente_id
    try:
        conn = db.get_db()
        result = {}
        for key in profile_keys:
            val = None
            if target_id is not None:
                scoped_key = f"{key}_{target_id}"
                row = conn.execute(
                    "SELECT valor FROM configuracion WHERE clave = ?", (scoped_key,)
                ).fetchone()
                if row and row['valor'] and str(row['valor']).strip():
                    val = str(row['valor']).strip()
            
            if not val:
                row = conn.execute(
                    "SELECT valor FROM configuracion WHERE clave = ?", (key,)
                ).fetchone()
                if row and row['valor'] and str(row['valor']).strip():
                    val = str(row['valor']).strip()

            if not val and target_id != 4:
                row = conn.execute(
                    "SELECT valor FROM configuracion WHERE clave = ?", (f"{key}_4",)
                ).fetchone()
                if row and row['valor'] and str(row['valor']).strip():
                    val = str(row['valor']).strip()

            result[key] = val or ''
        conn.close()
        return result
    except Exception as e:
        print(f"  ⚠️ Error fetching agent profile for agent {agente_id}: {e}")
        return {k: '' for k in profile_keys}


def send_email(to_email, subject, body, is_html=False, agente_id=None):
    """Send an email using the SMTP settings of the specified agent (or current user).
    
    agente_id: int or None. If None, reads from current request user context.
               Pass an explicit int when calling from background threads.
    """
    if agente_id is None:
        try:
            from flask import has_request_context
            from flask_login import current_user
            if has_request_context() and current_user and current_user.is_authenticated:
                agente_id = current_user.id
        except Exception:
            pass

    smtp_cfg = _get_smtp_config_for_agent(agente_id)
    smtp_host = smtp_cfg.get('smtp_host')
    smtp_port = smtp_cfg.get('smtp_port')
    smtp_user = smtp_cfg.get('smtp_user')
    smtp_pass = smtp_cfg.get('smtp_password')

    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        missing = [k for k, v in [('smtp_host', smtp_host), ('smtp_port', smtp_port), ('smtp_user', smtp_user), ('smtp_password', smtp_pass)] if not v]
        print(f"  ⚠️ Error: Configuración SMTP incompleta para agente {agente_id}. Faltan: {', '.join(missing)}. No se puede enviar email.")
        return False

    try:
        msg = MIMEMultipart('related')
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject

        # Create alternative part for HTML/Text
        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)

        logo_path_rel = db.get_config('company_logo_path', '')
        logo_attached = False

        if is_html and logo_path_rel:
            import os
            # Resolve absolute path to local logo file
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            clean_rel = logo_path_rel.lstrip('/')
            logo_abs_path = os.path.join(base_dir, clean_rel.replace('/', os.sep))

            if os.path.exists(logo_abs_path):
                # Replace relative path with cid:company_logo in HTML body
                body = body.replace(logo_path_rel, "cid:company_logo")
                logo_attached = True

        msg_alternative.attach(MIMEText(body, 'html' if is_html else 'plain', 'utf-8'))

        # Attach inline logo if needed
        if logo_attached:
            from email.mime.image import MIMEImage
            try:
                with open(logo_abs_path, 'rb') as img_f:
                    img_data = img_f.read()
                msg_image = MIMEImage(img_data)
                msg_image.add_header('Content-ID', '<company_logo>')
                msg_image.add_header('Content-Disposition', 'inline', filename=os.path.basename(logo_abs_path))
                msg.attach(msg_image)
            except Exception as attachment_err:
                print(f"  ⚠️ Warning: No se pudo adjuntar el logo al email: {attachment_err}")

        # Support both port 465 (SSL) and port 587 / others (starttls)
        port = int(smtp_port)
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_host, port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, port, timeout=15)
            server.starttls()
            
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"  ❌ Error enviando email a {to_email}: {e}")
        return False

import os
import time

def _email_queue_worker_loop(app):
    print("[Email Queue Worker] Thread loop started.")
    
    # Auto-recovery: reset any email stuck in 'enviando' back to 'pendiente' on start
    try:
        conn = db.get_db()
        conn.execute("UPDATE cola_correos_clientes SET estado = 'pendiente' WHERE estado = 'enviando'")
        conn.commit()
        conn.close()
        print("[Email Queue Worker] Reset any stuck 'enviando' emails to 'pendiente'.")
    except Exception as e:
        print(f"[Email Queue Worker] Error resetting stuck emails: {e}")

    while True:
        try:
            # Staggered 12 seconds check
            time.sleep(12)
            
            # Check if current time is between 8:00 AM and 11:50 PM (23:50)
            now = datetime.now()
            start_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
            end_time = now.replace(hour=23, minute=50, second=0, microsecond=0)
            
            if not (start_time <= now <= end_time):
                continue
            
            # Read pending mails from database
            pending = db.get_pending_correos_clientes()
            if not pending:
                continue
            
            email = pending[0]
            cid = email['id']
            email_dest = email['email_dest']
            asunto = email['asunto']
            cuerpo_html = email['cuerpo_html']
            # agente_id may be stored in the queue row (added below)
            agente_id = email.get('agente_id') if hasattr(email, 'get') else None
            
            print(f"[Email Queue Worker] Found pending email {cid} to {email_dest} (agente_id={agente_id}). Sending...")
            
            # Mark it first to prevent multiple threads pick up
            db.update_correo_cliente_estado(cid, 'enviando')
            
            # Use agent-specific SMTP if agente_id is set
            success = send_email(email_dest, asunto, cuerpo_html, is_html=True, agente_id=agente_id)
            if success:
                print(f"[Email Queue Worker] Email {cid} sent successfully to {email_dest}")
                db.update_correo_cliente_estado(cid, 'enviado')
            else:
                print(f"[Email Queue Worker] Failed sending email {cid} to {email_dest}")
                db.update_correo_cliente_estado(cid, 'error', "Error sending SMTP email (check server logs/credentials)")
        except Exception as ex:
            print(f"[Email Queue Worker] Error in worker loop: {ex}")

def start_staggered_email_worker(app):
    # Reloader safeguard
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        t = threading.Thread(target=_email_queue_worker_loop, args=(app,), daemon=True)
        t.start()
        print("[Email Queue Worker] Thread spawned.")


def trigger_automation_for_property(prop_id):
    """
    Check if automation is active and send the first contact email 
    if the property is new and has an email address.
    """
    # Run in a separate thread to not block the scraper
    threading.Thread(target=_process_automation, args=(prop_id,)).start()

def _process_automation(prop_id):
    """Internal process to send automated email."""
    config = db.get_all_config()
    
    # Check if global automation is active
    if config.get('automatizacion_email_activa') != '1':
        return

    prop = db.get_propiedad(prop_id)
    if not prop or not prop['email_contacto']:
        return
    
    # Check if already contacted
    if prop['estado'] != 'nueva':
        return

    print(f"  🤖 Iniciando contacto automático para: {prop['titulo']}")

    # Get template for Step 1
    asunto_template = config.get('template_email_asunto_1', '')
    mensaje_template = config.get('template_email_1', '')

    placeholders = {
        'nombre': prop['nombre_contacto'] or 'propietario',
        'direccion': prop['direccion'] or 'tu propiedad',
        'barrio': prop['barrio'] or '',
        'portal': prop['portal'].capitalize(),
        'agente_nombre': config.get('agente_nombre', ''),
        'agente_telefono': config.get('agente_telefono', ''),
        'agente_inmobiliaria': config.get('agente_inmobiliaria', '')
    }

    try:
        asunto = asunto_template.format(**placeholders)
        mensaje = mensaje_template.format(**placeholders)
    except KeyError as e:
        print(f"  ⚠️ Error en placeholders del template: {e}")
        return

    # Send email
    if send_email(prop['email_contacto'], asunto, mensaje):
        print(f"  ✅ Email enviado automáticamente a {prop['email_contacto']}")
        
        # Log communication
        db.insert_comunicacion({
            'propiedad_id': prop_id,
            'tipo': 'email',
            'mensaje': mensaje,
            'asunto': asunto,
            'paso': 1,
            'estado': 'enviada',
            'fecha_enviada': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
        # Update property status
        db.update_propiedad_estado(prop_id, 'contactada', f"Contacto automático realizado vía Email el {datetime.now().strftime('%Y-%m-%d')}")
    else:
        print(f"  ❌ Falló el envío automático a {prop['email_contacto']}")

def _execute_all_saved_searches_for_agents(app):
    """Iterates through all client saved searches, finds new properties and emails the agent.
    Each search is scoped to an agente_id; their own SMTP and profile are used.
    """
    import json
    from database import db as db_module
    
    with app.app_context():
        try:
            searches = db_module.get_busquedas_clientes()
            if not searches:
                return
                
            for b in searches:
                print(f"[Daily Saved Searches Worker] Processing search: {b['nombre']}")
                
                try:
                    tipo_prop = json.loads(b['tipo_propiedad'])
                    if not isinstance(tipo_prop, list): tipo_prop = [tipo_prop]
                except:
                    tipo_prop = [b['tipo_propiedad']] if b['tipo_propiedad'] else ['departamento']
                    
                try:
                    ambientes = json.loads(b['ambientes']) if b['ambientes'] else None
                    if ambientes and not isinstance(ambientes, list): ambientes = [ambientes]
                except:
                    ambientes = [int(b['ambientes'])] if b['ambientes'] else None

                extras_list = []
                if b.get('extras'):
                    try:
                        extras_list = json.loads(b['extras'])
                        if not isinstance(extras_list, list): extras_list = [extras_list]
                    except:
                        extras_list = [b['extras']]

                try:
                    from plugins.captacion_outreach.routes import procesar_busqueda_multi_zona
                    results, _ = procesar_busqueda_multi_zona(
                        zona_input=b['zona'],
                        tipo=tipo_prop,
                        operacion=b['tipo_operacion'],
                        ambientes=ambientes,
                        dormitorios=b.get('dormitorios'),
                        min_m2=b.get('min_m2'),
                        max_m2=b.get('max_m2'),
                        min_precio=b.get('min_precio'),
                        max_precio=b.get('max_precio'),
                        extras=extras_list,
                        keyword=b.get('keyword'),
                        page=1
                    )
                except Exception as ex:
                    print(f"Error querying search motor in daily search: {ex}")
                    results = []
                    
                if not results:
                    continue
                    
                vistas = json.loads(b['propiedades_vistas']) if b['propiedades_vistas'] else []
                search_created_at = b.get('fecha_creacion')
                
                new_results = []
                for r in results:
                    url = r.get('url')
                    if not url or url in vistas:
                        continue
                    
                    # Filtrar propiedades anteriores a la fecha de creación de la búsqueda guardada
                    prop_date = r.get('fecha_captacion') or r.get('created_at')
                    if search_created_at and prop_date:
                        try:
                            # Comparación ISO de fechas
                            if str(prop_date) < str(search_created_at):
                                continue
                        except Exception:
                            pass
                            
                    new_results.append(r)
                        
                if not new_results:
                    print(f"[Daily Saved Searches Worker] No new properties for search: {b['nombre']}")
                    continue

                # --- Resolve agent email and profile using scoped config ---
                search_agente_id = b.get('agente_id')
                agent_email = None
                
                if search_agente_id:
                    # First try the agent's own scoped email (from Configuracion)
                    try:
                        conn = db_module.get_db()
                        row = conn.execute(
                            "SELECT valor FROM configuracion WHERE clave = ?",
                            (f"agente_email_{search_agente_id}",)
                        ).fetchone()
                        conn.close()
                        if row and row['valor']:
                            agent_email = row['valor']
                    except:
                        pass
                    
                    # Fallback to the usuarios table email field
                    if not agent_email:
                        try:
                            conn = db_module.get_db()
                            row = conn.execute(
                                "SELECT email FROM usuarios WHERE id = ?",
                                (search_agente_id,)
                            ).fetchone()
                            conn.close()
                            agent_email = row[0] if row and row[0] else None
                        except:
                            pass
                    
                if not agent_email:
                    print(f"[Daily Saved Searches Worker] No agent email found for agent ID {search_agente_id} on search: {b['nombre']}")
                    continue
                    
                print(f"[Daily Saved Searches Worker] Found {len(new_results)} new properties. Enqueuing report to agent: {agent_email}")
                
                # Fetch this agent's profile for the email footer
                agent_profile = _get_agent_profile(search_agente_id)
                
                props_data = []
                for p in new_results:
                    desc = p.get('descripcion', '') or ''
                    desc_clean = desc.strip()
                    if not desc_clean or desc_clean.startswith("Detalles disponibles") or len(desc_clean) < 60:
                        desc_acotada = ""
                    else:
                        cutoff = int(len(desc_clean) * 0.15)
                        if cutoff < 50 and len(desc_clean) > 50: cutoff = 50
                        if cutoff > 120: cutoff = 120
                        desc_acotada = desc_clean[:cutoff].strip() + ("..." if len(desc_clean) > cutoff else "")
                    
                    fotos_raw = p.get('fotos') or []
                    foto_portada = p.get('foto') or (fotos_raw[0] if fotos_raw else None)
                    if foto_portada and foto_portada not in fotos_raw:
                        fotos_raw = [foto_portada] + fotos_raw
                    elif foto_portada and fotos_raw and fotos_raw[0] != foto_portada:
                        fotos_raw = [foto_portada] + [f for f in fotos_raw if f != foto_portada]
                    
                    fotos = ([foto_portada] if foto_portada else []) + [f for f in fotos_raw[1:] if f]
                    
                    props_data.append({
                        'titulo': p.get('titulo', 'Propiedad en ' + b['zona']),
                        'precio': p.get('precio', 0),
                        'moneda': p.get('moneda', 'USD'),
                        'ambientes': p.get('ambientes'),
                        'm2': p.get('m2') or p.get('superficie_total') or 0,
                        'barrio': p.get('barrio') or b['zona'],
                        'descripcion_acotada': desc_acotada,
                        'fotos': fotos[:6],
                        'tipo_propiedad': p.get('tipo_propiedad'),
                        'm2_total': p.get('m2_total') or p.get('superficie_total') or p.get('m2') or 0,
                        'm2_cubiertos': p.get('m2_cubiertos'),
                        'dormitorios': p.get('dormitorios'),
                        'banos': p.get('banos'),
                        'toilettes': p.get('toilettes'),
                        'cocheras': p.get('cocheras'),
                        'antiguedad': p.get('antiguedad'),
                        'orientacion': p.get('orientacion'),
                        'disposicion': p.get('disposicion'),
                        'estado_conservacion': p.get('estado_conservacion')
                    })
                    
                from flask import render_template
                cuerpo_html = render_template(
                    'email_propiedades.html',
                    zona=b['zona'],
                    props=props_data,
                    logo_url="",
                    agente_nombre=agent_profile.get('agente_nombre', 'Tu Asesor'),
                    agente_telefono=agent_profile.get('agente_telefono', ''),
                    agente_email=agent_profile.get('agente_email', ''),
                    agente_inmobiliaria=agent_profile.get('agente_inmobiliaria', '')
                )
                
                asunto = f"[Novedades] Búsqueda: {b['nombre']} para {b['cliente_nombre']} {b['cliente_apellido']}"
                # Enqueue with agente_id so the worker uses the right SMTP account
                db_module.enqueue_correo_cliente(agent_email, asunto, cuerpo_html, agente_id=search_agente_id)
                
                # ACTUALIZAR PROPIEDADES VISTAS EN BD PARA EVITAR ENVIOS DUPLICADOS FUTUROS
                for nr in new_results:
                    if nr.get('url') and nr['url'] not in vistas:
                        vistas.append(nr['url'])
                db_module.update_busqueda_cliente_vistas(b['id'], json.dumps(vistas))
        except Exception as e:
            print(f"[Daily Saved Searches Worker] General error: {e}")

def _daily_saved_searches_worker_loop(app):
    print("[Daily Saved Searches Worker] Thread loop started.")
    time.sleep(30)
    
    last_run_date = None
    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            now = datetime.now()
            if last_run_date != today and now.hour >= 9:
                _execute_all_saved_searches_for_agents(app)
                last_run_date = today
                
            time.sleep(3600)
        except Exception as e:
            print(f"[Daily Saved Searches Worker] Error: {e}")
            time.sleep(600)

def start_daily_saved_searches_worker(app):
    # Reloader safeguard
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        t = threading.Thread(target=_daily_saved_searches_worker_loop, args=(app,), daemon=True)
        t.start()
        print("[Daily Saved Searches Worker] Thread spawned.")
