"""
Módulo de Notificaciones de Seguridad y Detección de Anomalías para CRM.
Despacho 100% asíncrono (threading) con impacto CERO en la velocidad web.
Filtro anti-spam de bots: solo alerta sobre cuentas reales existentes.
"""
import os
import time
import threading
from datetime import datetime
from database import db
from database.db_audit import registrar_auditoria

# Memoria de intentos fallidos para cuentas reales: { 'username': [ts1, ts2, ...] }
_FAILED_ATTEMPTS = {}
_LOCK = threading.Lock()

def _get_config_value(conn, clave, default="0"):
    try:
        row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
        if row and row['valor'] is not None:
            return str(row['valor']).strip()
    except Exception:
        pass
    return default

def _get_destination_phones(conn):
    """Obtiene los números de destino configurados en la BD o en variables de entorno."""
    phones_str = _get_config_value(conn, "alerta_whatsapp_telefonos", "")
    if not phones_str:
        phones_str = os.environ.get("SECURITY_NOTIFIER_PHONE", os.environ.get("SUPERADMIN_PHONE", "+5491161114414"))
    
    # Limpiar y dividir números separados por coma o espacio
    raw_list = [p.strip() for p in phones_str.replace(";", ",").split(",") if p.strip()]
    cleaned_list = []
    for p in raw_list:
        clean = p.replace(" ", "").replace("-", "").replace("+", "")
        if clean and len(clean) >= 8:
            cleaned_list.append(clean)
    return cleaned_list

def _dispatch_whatsapp_message(mensaje):
    """Inserta el mensaje de seguridad en cola_mensajes para cada teléfono receptor."""
    conn = None
    try:
        conn = db.get_db()
        phones = _get_destination_phones(conn)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for phone in phones:
            conn.execute("""
                INSERT INTO cola_mensajes (propiedad_id, telefono, mensaje, tipo, estrategia, fecha_creacion, fecha_programada, estado)
                VALUES (NULL, ?, ?, 'whatsapp', 'alerta_seguridad', ?, ?, 'pendiente')
            """, (phone, mensaje, now_str, now_str))
            
        conn.commit()
    except Exception as e:
        print(f"[SecurityNotifier] Error encolando mensaje de seguridad: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def notify_admin_login_async(user_data, ip="Desconocida", user_agent="Navegador Web"):
    """Notifica de forma asíncrona el inicio de sesión exitoso de un Administrador."""
    def _worker():
        conn = None
        try:
            conn = db.get_db()
            activo = _get_config_value(conn, "alerta_whatsapp_activo", "1")
            alerta_login = _get_config_value(conn, "alerta_admin_login", "1")
            
            if activo != "1" or alerta_login != "1":
                return
                
            hora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            ua_clean = str(user_agent)[:60]
            
            msg = (
                f"🛡️ *[CRM SEGURIDAD]* Inicio de Sesión Admin\n\n"
                f"👤 *Usuario:* {user_data.get('usuario')}\n"
                f"🏷️ *Nombre:* {user_data.get('nombre_display')}\n"
                f"⏰ *Hora:* {hora_str}\n"
                f"🌐 *IP:* {ip}\n"
                f"💻 *Dispositivo:* {ua_clean}\n\n"
                f"_Si no fuiste vos, cambiá tu contraseña inmediatamente desde el panel._"
            )
            
            _dispatch_whatsapp_message(msg)
            registrar_auditoria("LOGIN_EXITOSO_ADMIN", f"Usuario: {user_data.get('usuario')}, IP: {ip}")
        except Exception as e:
            print(f"[SecurityNotifier] Error en alert de login admin: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def record_failed_login_and_alert_async(usuario_input, ip="Desconocida", user_agent=""):
    """
    Registra intentos fallidos.
    Aplica filtro anti-spam: Solo alerta si el usuario ingresado EXISTE en la base de datos
    y acumula 3 o más fallos en una ventana de 10 minutos.
    """
    def _worker():
        conn = None
        try:
            conn = db.get_db()
            
            # Verificar si el usuario existe realmente en el sistema
            from database.db_auth import get_usuario
            user_exists = get_usuario(usuario_input)
            if not user_exists:
                # Bot probando nombres aleatorios (admin, root, test) -> Registro de auditoría silencioso
                registrar_auditoria("LOGIN_FALLIDO_DESCONOCIDO", f"Intento con usuario inexistente: '{usuario_input}', IP: {ip}")
                return
                
            activo = _get_config_value(conn, "alerta_whatsapp_activo", "1")
            alerta_fallos = _get_config_value(conn, "alerta_failed_logins", "1")
            
            now = time.time()
            u_key = str(usuario_input).lower().strip()
            
            with _LOCK:
                if u_key not in _FAILED_ATTEMPTS:
                    _FAILED_ATTEMPTS[u_key] = []
                # Limpiar intentos con más de 10 minutos (600s)
                _FAILED_ATTEMPTS[u_key] = [ts for ts in _FAILED_ATTEMPTS[u_key] if now - ts < 600]
                _FAILED_ATTEMPTS[u_key].append(now)
                count = len(_FAILED_ATTEMPTS[u_key])
                
            registrar_auditoria("LOGIN_FALLIDO_CUENTA_REAL", f"Usuario real: '{usuario_input}', Intento #{count}, IP: {ip}")
            
            # Disparar alerta en el 3er intento fallido
            if count == 3 and activo == "1" and alerta_fallos == "1":
                hora_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                msg = (
                    f"⚠️ *[CRM ALERTA]* Múltiples Intentos Fallidos de Contraseña\n\n"
                    f"🎯 *Cuenta Afectada:* {usuario_input} ({user_exists.get('nombre_display')})\n"
                    f"🔢 *Intentos:* 3 intentos en menos de 10 minutos\n"
                    f"⏰ *Hora:* {hora_str}\n"
                    f"🌐 *IP Origen:* {ip}\n\n"
                    f"_Se ha aplicado protección de Rate Limit en el sistema._"
                )
                _dispatch_whatsapp_message(msg)
        except Exception as e:
            print(f"[SecurityNotifier] Error en failed login tracker: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def clear_failed_attempts(usuario):
    """Limpia el contador de fallos cuando el usuario ingresa su contraseña correctamente."""
    u_key = str(usuario).lower().strip()
    with _LOCK:
        if u_key in _FAILED_ATTEMPTS:
            _FAILED_ATTEMPTS.pop(u_key, None)
