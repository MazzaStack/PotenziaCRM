import os
import sys
import io
import time
import json
import sqlite3
import subprocess
import random
from datetime import datetime, timedelta

# Forzar codificación UTF-8 en Windows para evitar crashes por emojis en consola
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# Configuration - Root directory mapping
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add project root to sys.path to import database module
sys.path.insert(0, BASE_DIR)
from database import db

# Master DB for user iteration
MASTER_DB = r"C:\FerrariDB\captador.db"

def get_target_datetime(fecha_programada, orden):
    """Calcula la hora objetivo con un jitter aleatorio de +/- 15 minutos para lucir humano."""
    import random
    from datetime import datetime, timedelta
    
    seed_str = f"{fecha_programada}_{orden}"
    val = sum(ord(c) for c in seed_str)
    rng = random.Random(val)
    jitter = rng.randint(-15, 15) # minutos
    
    if orden == 1:
        base_hour, base_min = 7, 0
    elif orden == 2:
        base_hour, base_min = 11, 30
    elif orden == 3:
        base_hour, base_min = 15, 30
    elif orden == 4:
        base_hour, base_min = 19, 30
    elif orden == 5:
        base_hour, base_min = 22, 0
    else:
        base_hour, base_min = 23, 15
        
    date_part = fecha_programada.split(' ')[0]
    base_dt = datetime.strptime(f"{date_part} {base_hour:02d}:{base_min:02d}:00", "%Y-%m-%d %H:%M:%S")
    return base_dt + timedelta(minutes=jitter)

# ── LOCK DE PROCESO: sólo 1 worker corriendo a la vez ──────────────────────
LOCK_FILE = r"C:\FerrariDB\wa_worker.lock"

def acquire_lock():
    """Devuelve True si somos el único worker. False si ya hay otro corriendo."""
    try:
        if os.path.exists(LOCK_FILE):
            # Leer el PID guardado con manejo de errores por archivo vacío o corrupto
            old_pid = None
            try:
                with open(LOCK_FILE, 'r') as f:
                    content = f.read().strip()
                if content:
                    old_pid = int(content)
            except Exception:
                old_pid = None

            if old_pid is not None:
                # Verificar si ese proceso todavía está vivo y si es efectivamente nuestro script
                try:
                    import psutil
                    if psutil.pid_exists(old_pid):
                        proc = psutil.Process(old_pid)
                        cmdline = proc.cmdline()
                        is_our_worker = any('whatsapp_sender.py' in part for part in cmdline)
                        if is_our_worker:
                            print(f"[LOCK] Ya hay un worker corriendo (PID {old_pid}). Abortando.")
                            return False
                        else:
                            print(f"[LOCK] PID {old_pid} pertenece a otro proceso ({proc.name()}). Asumiendo lock obsoleto.")
                    else:
                        print(f"[LOCK] Lock obsoleto de PID {old_pid} (proceso muerto). Tomando control.")
                except ImportError:
                    # psutil no disponible: si el lock tiene más de 10 segundos asumimos que el proceso murió si no se actualizó
                    pass
                except Exception as e:
                    print(f"[LOCK] Error consultando PID {old_pid}: {e}. Asumiendo lock obsoleto.")
            else:
                print("[LOCK] Lock vacío o inválido. Tomando control.")
        # Escribir nuestro PID
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        print(f"[LOCK] Fallo general al adquirir lock: {e}. Corriendo igual.")
        return True

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

print(">>> SISTEMA: Iniciando Global WhatsApp Worker (Ephemeral Mode)...")

def run_job(user_name, action, **kwargs):
    """
    Executes the short-lived Node script for a specific job.
    Returns the exit code: 0 = Success, 2 = QR Needed (Logged out), 1 = Error
    """
    if action == "status" and kwargs.get("user_id"):
        port = 9000 + kwargs["user_id"]
        url = f"http://127.0.0.1:{port}/status"
        try:
            import requests
            r = requests.post(url, json={"filePath": os.path.abspath(kwargs["file_path"]), "caption": kwargs.get("caption", "")}, timeout=3)
            if r.status_code == 200:
                print(f"  [OK] Estado WA publicado exitosamente vía HTTP Express Bridge para {user_name}.")
                return 0
        except Exception:
            pass

    if action == "message":
        script_path = os.path.join(BASE_DIR, "lib", "whatsapp_node", "wwebjs_sender.js")
        cmd = ["node", script_path, "--user", user_name, "--phone", kwargs["phone"], "--text", kwargs["message"]]
    else:
        script_path = os.path.join(BASE_DIR, "lib", "whatsapp_node", "ephemeral_sender.js")
        cmd = ["node", script_path, "--user", user_name, "--action", action]
        if action == "status":
            cmd.extend(["--file", kwargs["file_path"]])
            if kwargs.get("caption"):
                cmd.extend(["--caption", kwargs["caption"]])
    
    # Hide window on Windows
    creationflags = 0x08000000 if os.name == 'nt' else 0
    print(f"  [>] Ejecutando script node ({os.path.basename(script_path)}) para {user_name} (Acción: {action})")
    
    # Run synchronously with a timeout buffer
    try:
        result = subprocess.run(cmd, creationflags=creationflags, capture_output=True, text=True, timeout=90)
        return result.returncode
    except subprocess.TimeoutExpired:
        print("  [!] Error: Timeout del proceso de node.")
        return 1

def update_contacts_cache(user_name, db_file):
    # Deshabilitado: no queremos usar contactos de ZonaProp de la base de datos de propiedades.
    # El archivo contacts_cache.json será generado directamente por el bridge de Node.js al sincronizar.
    pass

def global_worker():
    from datetime import datetime, timedelta
    while True:
        try:
            # ── 1. CONTROL DE LATIDO (HEARTBEAT) CON AUTO-DESTRUCCIÓN ──
            # Si el servidor web app.py se cierra, cae o no actualiza el latido hace >15s, el worker se auto-apaga
            hb_file = r"C:\FerrariDB\crm_heartbeat.json"
            if os.path.exists(hb_file):
                try:
                    with open(hb_file, 'r', encoding='utf-8') as f:
                        hb_data = json.load(f)
                    hb_ts = hb_data.get('timestamp', 0)
                    app_pid = hb_data.get('app_pid')
                    
                    # Chequeo 1: Antigüedad del latido
                    time_since_hb = time.time() - hb_ts
                    if time_since_hb > 15:
                        print(f"\n[HEARTBEAT PERDIDO] Servidor inactivo hace {time_since_hb:.1f}s (>15s). Auto-cerrando worker...")
                        break
                    
                    # Chequeo 2: Proceso de Flask vivo en el OS
                    if app_pid:
                        tasklist_out = subprocess.check_output(f'tasklist /FI "PID eq {app_pid}" /FO CSV', shell=True, text=True, errors='ignore')
                        if str(app_pid) not in tasklist_out:
                            print(f"\n[HEARTBEAT PERDIDO] Proceso Flask (PID {app_pid}) no existe. Auto-cerrando worker...")
                            break
                except Exception as e_hb:
                    # En caso de colisión de lectura transitoria, ignorar
                    pass

            conn_user = None
            try:
                conn_user = db.get_db()
            except Exception as e_conn:
                print(f"  [!] Error obteniendo conexión a BD en worker: {e_conn}")
                time.sleep(10)
                continue

            try:
                users = conn_user.execute("SELECT id, usuario, db_file FROM usuarios").fetchall()
            except Exception:
                users = [{'id': 1, 'usuario': 'GermanMazza', 'db_file': 'captador.db'}]

            jobs_processed = 0  # Reset job counter every iteration

            # --- PRIORIDAD 0 GLOBAL: Alertas y Verificaciones del Portal (cola_mensajes) ---
            try:
                cola_msg = conn_user.execute("""
                    SELECT * FROM cola_mensajes
                    WHERE estado = 'pendiente'
                    ORDER BY id ASC
                    LIMIT 1
                """).fetchone()
                
                if cola_msg:
                    raw_phone = str(cola_msg['telefono'])
                    clean_phone = raw_phone.replace(" ", "").replace("-", "").replace("+", "")
                    if clean_phone and len(clean_phone) >= 8:
                        print(f"\n[Portal WA] Procesando alerta/código COLA_MENSAJES ID {cola_msg['id']} para {raw_phone}")
                        conn_user.execute("UPDATE cola_mensajes SET estado = 'enviando' WHERE id = ?", (cola_msg['id'],))
                        conn_user.commit()
                        
                        exit_code = run_job('GermanMazza', 'message', phone=clean_phone, message=cola_msg['mensaje'])
                        
                        if exit_code == 0:
                            print("  [✓] Alerta/código de portal enviado con éxito.")
                            conn_user.execute("UPDATE cola_mensajes SET estado = 'enviado' WHERE id = ?", (cola_msg['id'],))
                        else:
                            print(f"  [!] Error enviando alerta/código (exit {exit_code}).")
                            conn_user.execute("UPDATE cola_mensajes SET estado = 'error' WHERE id = ?", (cola_msg['id'],))
                        conn_user.commit()
                        jobs_processed += 1
            except Exception as e_cola:
                print(f"  [!] Error consultando cola_mensajes: {e_cola}")

            for user in users:
                try:
                    now = datetime.now()
                    today_str = now.strftime('%Y-%m-%d')

                    # ── RECUPERACIÓN SEGURA DE PLACAS TRABADAS ──
                    # Si alguna historia quedó en 'publicando' por más de 10 minutos (e.g. crash de server),
                    # marcar como error si ya tuvo intentos para EVITAR bucles infinitos.
                    try:
                        conn_user.execute("""
                            UPDATE historias_redes 
                            SET estado = CASE 
                                WHEN COALESCE(reintentos, 0) >= 2 THEN 'error: limite de reintentos'
                                ELSE 'pendiente'
                            END,
                            reintentos = COALESCE(reintentos, 0) + 1
                            WHERE estado = 'publicando' 
                            AND (fecha_publicacion IS NULL OR fecha_publicacion < ?)
                        """, ((now - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S'),))
                        conn_user.commit()
                    except Exception:
                        pass

                    # ── CIRCUIT BREAKER ABSOLUTO: MÁXIMO 5 HISTORIAS PUBLICADAS POR DÍA ──
                    try:
                        pub_count_row = conn_user.execute("""
                            SELECT COUNT(*) FROM historias_redes
                            WHERE agente_id = ?
                            AND estado = 'completado'
                            AND (
                                (fecha_publicacion IS NOT NULL AND date(fecha_publicacion) = ?)
                                OR (fecha_programada IS NOT NULL AND date(fecha_programada) = ?)
                            )
                        """, (user['id'], today_str, today_str)).fetchone()
                        published_today = pub_count_row[0] if pub_count_row else 0
                    except Exception:
                        published_today = 0

                    if published_today >= 5:
                        # BLOQUEO TOTAL: Límite diario alcanzado para este agente
                        continue
                    
                    # --- PRIORIDAD 1: Historias/Estados ---
                    # BLOQUEO DE SEGURIDAD ESTRICTO: Solo se publican historias de HOY (nunca futuras).
                    try:
                        # REGLA FUNDAMENTAL: Solo placas cuya fecha_programada sea HOY o anterior para ESTE agente
                        candidates = conn_user.execute("""
                            SELECT * FROM historias_redes 
                            WHERE agente_id = ?
                            AND estado = 'pendiente'
                            AND date(fecha_programada) <= ?
                            ORDER BY fecha_programada ASC, orden ASC
                        """, (user['id'], today_str)).fetchall()
                    except Exception as e_cand:
                        candidates = []
                    
                    story = None
                    
                    # Ventana horaria humana: 09:00 a 23:30 hs
                    if 9 <= now.hour <= 23:
                        for candidate in candidates:
                            if not candidate['fecha_programada']:
                                continue
                            cand_date = str(candidate['fecha_programada']).split(' ')[0]
                            # Seguridad extra en código: jamás procesar fechas futuras
                            if cand_date > today_str:
                                continue
                                
                            target_dt = get_target_datetime(candidate['fecha_programada'], candidate['orden'])
                            if now >= target_dt:
                                story = candidate
                                break

                        if story:
                            # Control Anti-bot inquebrantable para WhatsApp:
                            # Verificar el último intento/publicación (sin importar el estado para evitar bypass en caso de fallo)
                            last_wa_row = conn_user.execute("""
                                SELECT fecha_publicacion FROM historias_redes
                                WHERE agente_id = ?
                                AND whatsapp = 1 
                                AND fecha_publicacion IS NOT NULL
                                ORDER BY fecha_publicacion DESC LIMIT 1
                            """, (user['id'],)).fetchone()

                            if last_wa_row and last_wa_row['fecha_publicacion']:
                                try:
                                    last_pub = datetime.strptime(str(last_wa_row['fecha_publicacion'])[:19], '%Y-%m-%d %H:%M:%S')
                                    secs_since = (now - last_pub).total_seconds()
                                    if secs_since < 2100: # 35 minutos obligatorios
                                        mins_left = (2100 - secs_since) / 60
                                        print(f"  [WA] Anti-bot: último intento hace {secs_since/60:.0f} min. Pausa de seguridad obligatoria de {mins_left:.0f} min restantes...")
                                        story = None # Descartar candidato por este ciclo
                                except Exception:
                                    pass
                    
                    if story:
                        print(f"\n[>] Procesando HISTORIA ID {story['id']} para usuario '{user['usuario']}'")
                        clean_path = story['archivo_path'].replace('/static/', 'static/')
                        file_path = os.path.join(BASE_DIR, clean_path.replace('/', os.sep))
                        
                        if not os.path.exists(file_path):
                            print(f"  [!] Archivo vacante: {file_path}")
                            conn_user.execute("UPDATE historias_redes SET estado = 'error: archivo vacante' WHERE id = ?", (story['id'],))
                        else:
                            # ── ANTI-DUPLICADO: Marcar como 'publicando' ANTES de empezar ──
                            # Esto previene que dos workers simultáneos agarren la misma placa
                            _cur = conn_user.execute("UPDATE historias_redes SET estado = 'publicando', fecha_publicacion = ? WHERE id = ? AND estado = 'pendiente'",
                                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), story['id']))
                            conn_user.commit()
                            
                            # Verificar que realmente tomamos el lock
                            # rowcount funciona tanto en SQLite como en PostgreSQL (psycopg2)
                            rows_affected = getattr(_cur, 'rowcount', 1)  # fallback 1 si no disponible
                            if rows_affected == 0:
                                print(f"  [!] Historia ID {story['id']} ya está siendo procesada por otro worker. Saltando.")
                                continue
                            
                            # Determinar plataformas habilitadas
                            pub_whatsapp = story['whatsapp'] if 'whatsapp' in story.keys() else 1
                            pub_instagram = story['instagram'] if 'instagram' in story.keys() else 0
                            is_test_mode = False
                            
                            results = {}
                            
                            # 1. WhatsApp
                            if pub_whatsapp:
                                print("  [>] Iniciando publicación en WhatsApp Status...")
                                exit_code = run_job(user['usuario'], 'status', user_id=user['id'], file_path=file_path)
                                if exit_code == 0:
                                    print("  [OK] Estado WA publicado.")
                                    results['whatsapp'] = {'success': True}
                                elif exit_code == 2:
                                    print("  [!] Sesión de WA inválida (Requiere QR).")
                                    results['whatsapp'] = {'success': False, 'error': 'WA desconectado (QR)'}
                                else:
                                    results['whatsapp'] = {'success': False, 'error': f'Bridge exit code {exit_code}'}
                            
                            # 2. Instagram (API Privada)
                            if pub_instagram:
                                # ── REGLA 1: Horario humano (06:20 – 23:50) ──────────────────
                                now = datetime.now()
                                hora_actual = now.hour * 60 + now.minute  # minutos desde medianoche
                                hora_inicio = 6 * 60 + 20   # 06:20
                                hora_fin    = 23 * 60 + 50  # 23:50
                                if not (hora_inicio <= hora_actual <= hora_fin):
                                    print(f"  [IG] Fuera del horario humano ({now.strftime('%H:%M')}). "
                                          f"IG se publicará entre 06:20 y 23:50.")
                                    results['instagram'] = {'success': False,
                                                            'error': 'Fuera de horario humano (06:20–23:50)'}
                                else:
                                    # ── REGLA 2: Mínimo 60-90 min entre stories del mismo agente ──
                                    min_gap_min = random.randint(60, 90)
                                    last_ig_row = conn_user.execute(
                                        """SELECT fecha_publicacion FROM historias_redes
                                           WHERE agente_id = ?
                                           AND instagram = 1
                                           AND fecha_publicacion IS NOT NULL
                                           ORDER BY fecha_publicacion DESC LIMIT 1""",
                                        (user['id'],)
                                    ).fetchone()
                                    if last_ig_row and last_ig_row['fecha_publicacion']:
                                        try:
                                            last_pub = datetime.strptime(str(last_ig_row['fecha_publicacion'])[:19],
                                                                         '%Y-%m-%d %H:%M:%S')
                                            mins_since = (now - last_pub).total_seconds() / 60
                                            if mins_since < min_gap_min:
                                                wait_msg = (f"  [IG] Última historia publicada hace {mins_since:.0f} min. "
                                                            f"Mínimo requerido: {min_gap_min} min. Saltando IG por ahora.")
                                                print(wait_msg)
                                                results['instagram'] = {'success': False,
                                                                        'error': f'Pausa anti-ban: {min_gap_min - mins_since:.0f} min restantes'}
                                                # No es un error real → no contar como reintento
                                                pub_instagram = False  # forzar skip sin penalizar reintentos
                                        except Exception:
                                            pass

                                    if pub_instagram:
                                        delay = random.randint(15, 45)
                                        print(f"  [⏳] ANTI-BAN WA→IG: Esperando {delay} segundos antes de subir a Instagram...")
                                        time.sleep(delay)
                                        
                                        print("  [>] Iniciando publicación en Instagram Stories...")
                                        # Obtener credenciales de la DB de este usuario (scoped por usuario)
                                        user_id = user['id']
                                        ig_user_row = conn_user.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_username')", (f'ig_username_{user_id}',)).fetchone()
                                        ig_pass_row = conn_user.execute("SELECT valor FROM configuracion WHERE clave IN (?, 'ig_password')", (f'ig_password_{user_id}',)).fetchone()
                                        ig_user = ig_user_row['valor'] if ig_user_row else None
                                        ig_pass = ig_pass_row['valor'] if ig_pass_row else None
                                        
                                        if not ig_user or not ig_pass:
                                            print("  [!] Error: Instagram no configurado o vinculado para este agente.")
                                            results['instagram'] = {'success': False, 'error': 'IG no configurado'}
                                        else:
                                            # Importar helper y publicar (incluye warmup variado + pre-delay)
                                            sys.path.append(os.path.join(BASE_DIR, 'lib'))
                                            from lib.instagram_publisher import publicar_historia_privada
                                            ig_ok, ig_msg = publicar_historia_privada(ig_user, ig_pass, file_path)
                                            if ig_ok:
                                                print("  [✓] Historia de Instagram publicada.")
                                                results['instagram'] = {'success': True}
                                                # ── REGLA 3: Pausa aleatoria entre agentes (12-22 seg) ──
                                                inter_agent_delay = random.randint(12, 22)
                                                print(f"  [⏳] Pausa inter-agente: {inter_agent_delay}s antes de procesar el siguiente...")
                                                time.sleep(inter_agent_delay)
                                            else:
                                                print(f"  [!] Falló publicación de Instagram: {ig_msg}")
                                                if "RELINK_REQUIRED" in ig_msg:
                                                    clean_msg = ig_msg.split(':', 1)[1] if ':' in ig_msg else ig_msg
                                                    results['instagram'] = {'success': False, 'error': clean_msg}
                                                    # Actualizar estado de sesión en la DB de este usuario
                                                    conn_user.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('ig_session_status', 'needs_relink')")
                                                else:
                                                    results['instagram'] = {'success': False, 'error': ig_msg}


                            # Evaluar resultados
                            failed_platforms = [plat for plat, v in results.items() if not v.get('success')]
                            successful_platforms = [plat for plat, v in results.items() if v.get('success')]
                            error_summary = '; '.join(f"{k}: {v.get('error', 'Fallo')}" for k, v in results.items() if not v.get('success'))
                            
                            # Si al menos una plataforma principal (ej: WhatsApp) tuvo éxito:
                            if len(successful_platforms) > 0:
                                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                print(f"  [✓] Placa ID {story['id']} publicada exitosamente en: {', '.join(successful_platforms)}")
                                if failed_platforms:
                                    print(f"  [i] Nota: Falló o se omitió en {', '.join(failed_platforms)} ({error_summary}) pero no se reintenta para evitar duplicados en WhatsApp.")
                                conn_user.execute("""UPDATE historias_redes 
                                                  SET estado = 'completado', fecha_publicacion = ?, error_log = ? 
                                                  WHERE id = ?""", 
                                              (now_str, error_summary if error_summary else None, story['id']))
                            else:
                                # Fallaron TODAS las plataformas seleccionadas
                                reintentos = (story['reintentos'] or 0) + 1
                                if reintentos < 3:
                                    proximo = datetime.now() + timedelta(minutes=15)
                                    print(f"  [!] Falló publicación total (Errores: {error_summary}) - Reintentando {reintentos}/3")
                                    conn_user.execute("""UPDATE historias_redes 
                                                      SET fecha_programada = ?, reintentos = ?, estado = 'pendiente', fecha_publicacion = NULL, error_log = ?
                                                      WHERE id = ?""",
                                                  (proximo.strftime('%Y-%m-%d %H:%M:%S'), reintentos, error_summary, story['id']))
                                else:
                                    print(f"  [!] Agotados los reintentos. Estado marcado como error.")
                                    conn_user.execute("UPDATE historias_redes SET estado = ?, error_log = ? WHERE id = ?", 
                                                  (f"error: {error_summary[:80]}", error_summary, story['id']))
                        
                        conn_user.commit()
                        conn_user.close()
                        jobs_processed += 1
                        time.sleep(3)
                        continue # Move to next user to prevent one user from hogging the queue
                    


                    # --- PRIORIDAD 2: Mensajes ---
                    try:
                        msg = conn_user.execute("""
                            SELECT c.*, p.telefono 
                            FROM comunicaciones c
                            JOIN propiedades p ON c.propiedad_id = p.id
                            WHERE c.estado = 'pendiente' AND c.tipo = 'whatsapp'
                            ORDER BY c.fecha_programada ASC
                            LIMIT 1
                        """).fetchone()
                    except Exception:
                        msg = None
                    
                    if msg:
                        raw_phone = str(msg['telefono'])
                        clean_phone = raw_phone.replace(" ", "").replace("-", "").replace("+", "")
                        if not clean_phone or "000000" in clean_phone or len(clean_phone) < 8:
                            conn_user.execute("UPDATE comunicaciones SET estado = 'error' WHERE id = ?", (msg['id'],))
                            conn_user.commit()
                        else:
                            print(f"\n[+] Procesando MENSAJE ID {msg['id']} para usuario '{user['usuario']}'")
                            exit_code = run_job(user['usuario'], 'message', phone=clean_phone, message=msg['mensaje'])
                            
                            if exit_code == 0:
                                print("  [✓] Mensaje enviado.")
                                conn_user.execute("UPDATE comunicaciones SET estado = 'enviada', fecha_enviada = ? WHERE id = ?", 
                                              (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg['id']))
                                conn_user.commit()
                                delay = random.randint(15, 30)
                                print(f"  [⏳] ANTI-BAN: Pausa de seguridad de {delay} segundos...")
                                time.sleep(delay)
                            elif exit_code == 2:
                                print("  [!] Sesión inválida (Requiere QR).")
                                conn_user.execute("UPDATE comunicaciones SET estado = 'error' WHERE id = ?", (msg['id'],))
                                conn_user.commit()
                            else:
                                print(f"  [!] Error enviando (exit {exit_code}).")
                                conn_user.execute("UPDATE comunicaciones SET estado = 'error' WHERE id = ?", (msg['id'],))
                                conn_user.commit()
                                
                        jobs_processed += 1

                    
                except Exception as e_user:
                    print(f"  [!] Error procesando DB del usuario {user['usuario']}: {e_user}")

            if conn_user and hasattr(conn_user, 'close'):
                try:
                    conn_user.close()
                except Exception:
                    pass

            # If no jobs processed for ANY user, wait 15 seconds before polling again
            if jobs_processed == 0:
                print(f"  [-] {datetime.now().strftime('%H:%M:%S')}: Esperando tareas en la red global...")
                time.sleep(15)
                
        except Exception as e:
            print(f"  [CRITICAL ERROR] Error en worker global: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(15)

if __name__ == "__main__":
    if not acquire_lock():
        print("[LOCK] Worker ya activo. Saliendo.")
        sys.exit(0)
    
    try:
        global_worker()
    finally:
        release_lock()
