import os
import sys
import time
import sqlite3
import requests
import argparse
from datetime import datetime, timedelta

# Configuration - Root directory mapping
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Path hack to ensure we can import from the root directory
sys.path.append(BASE_DIR)

print(">>> SISTEMA: Iniciando script de WhatsApp Multi-Usuario (Node Socket Bridge)...")

parser = argparse.ArgumentParser()
parser.add_argument('--usuario', type=str, default=None)
parser.add_argument('--user-id', type=int, default=1)
parser.add_argument('--db-path', type=str, default=None)
args, unknown = parser.parse_known_args()

try:
    import database.db
    if args.db_path:
        database.db.MASTER_DB_PATH = args.db_path
        print(f"  [DB] Forzando base de datos a: {args.db_path}")
        
    from database.db import get_db, update_comunicacion_estado
except ImportError as e:
    print(f"\n❌ ERROR DE IMPORTACIÓN: {e}")
    print("Asegurate de estar ejecutando desde la carpeta raíz del proyecto.")
    input("\nPresioná ENTER para salir...")
    sys.exit(1)

def ensure_node_bridge_running(username, user_id):
    port = 9000 + user_id
    url = f"http://127.0.0.1:{port}/status"
    try:
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            print(f"  [✓] Bridge de Node ya está corriendo para {username} en el puerto {port}")
            return port
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        pass
    
    print(f"  [!] Bridge de Node no responde en puerto {port}. Iniciándolo...")
    node_script = os.path.join(BASE_DIR, 'lib', 'whatsapp_node', 'index.js')
    cmd = [
        "node",
        node_script,
        "--usuario", username,
        "--port", str(port)
    ]
    
    # Launch without window on Windows using creationflags
    creationflags = 0
    if os.name == 'nt':
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = 0x08000000
        
    subprocess_env = os.environ.copy()
    import subprocess
    subprocess.Popen(cmd, creationflags=creationflags, env=subprocess_env)
    
    # Wait for the service to start
    for _ in range(15):
        time.sleep(1)
        try:
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                print(f"  [✓] Bridge de Node iniciado con éxito en puerto {port}")
                return port
        except:
            pass
    print("  [⚠️] Advertencia: El bridge de Node no respondió después de varios reintentos de inicio.")
    return port

def send_whatsapp_message(port, phone, message):
    try:
        url = f"http://127.0.0.1:{port}/send"
        r = requests.post(url, json={"phone": phone, "message": message}, timeout=30)
        if r.status_code == 200:
            return True
        else:
            print(f"    [!] Error enviando mensaje a {phone}: {r.text}")
            return False
    except Exception as e:
        print(f"    [X] Error de conexión con bridge Node para enviar a {phone}: {e}")
        return False

def post_whatsapp_status(port, file_path, caption=""):
    try:
        url = f"http://127.0.0.1:{port}/status"
        abs_path = os.path.abspath(file_path)
        r = requests.post(url, json={"filePath": abs_path, "caption": caption}, timeout=45)
        if r.status_code == 200:
            return True
        else:
            print(f"    [!] Error publicando estado: {r.text}")
            return False
    except Exception as e:
        print(f"    [X] Error de conexión con bridge Node para publicar estado: {e}")
        return False

def run_bridge():
    username = args.usuario or 'admin'
    user_id = args.user_id
    
    port = ensure_node_bridge_running(username, user_id)
    
    print(f"Iniciando ciclo de envío en puerto {port}...")
    qr_message_shown = False

    while True:
        try:
            # Check connection status
            try:
                r = requests.get(f"http://127.0.0.1:{port}/status", timeout=2)
                status_info = r.json()
                status = status_info.get('status')
            except Exception as e:
                print(f"  [!] No se pudo comunicar con el Bridge Node en puerto {port}: {e}")
                time.sleep(10)
                continue
                
            if status != 'connected':
                if status == 'qr_ready':
                    if not qr_message_shown:
                        print(f"  [!] WhatsApp desconectado. Código QR listo en static/uploads/qr_{username}.png")
                        qr_message_shown = True
                else:
                    print(f"  [⏳] WhatsApp no está conectado (Status: {status}). Esperando...")
                    qr_message_shown = False
                time.sleep(10)
                continue
                
            if qr_message_shown:
                print("  [OK] ¡WhatsApp Conectado y Listo!")
                qr_message_shown = False

            now = datetime.now()
            # Regla de seguridad 1: Ventana de horario humano (09:00 a 21:30 hs)
            is_daytime = 9 <= now.hour <= 21

            conn = get_db()
            story = None
            msg = None
            try:
                cursor = conn.cursor()
                # Prioridad 1: Historias/Estados (solo dentro de ventana diurna y con fecha cumplida)
                if is_daytime:
                    # Regla de seguridad 2: Verificar espaciado humano con la última historia publicada
                    last_pub_row = cursor.execute("""
                        SELECT fecha_publicacion FROM historias_redes 
                        WHERE estado = 'completado' 
                        ORDER BY fecha_publicacion DESC LIMIT 1
                    """).fetchone()

                    min_spacing_minutes = 30 # Mínimo 30 minutos entre historias
                    can_post_story = True

                    if last_pub_row and last_pub_row['fecha_publicacion']:
                        try:
                            last_pub_time = datetime.strptime(last_pub_row['fecha_publicacion'], '%Y-%m-%d %H:%M:%S')
                            minutes_since_last = (now - last_pub_time).total_seconds() / 60.0
                            if minutes_since_last < min_spacing_minutes:
                                can_post_story = False
                        except Exception:
                            pass

                    if can_post_story:
                        cursor.execute("""
                            SELECT * FROM historias_redes 
                            WHERE date(fecha_programada) <= date('now', 'localtime')
                            AND estado = 'pendiente' 
                            AND (plataforma = 'whatsapp' OR plataforma IS NULL)
                            ORDER BY fecha_programada ASC, orden ASC
                            LIMIT 1
                        """)
                        story = cursor.fetchone()
                
                # Prioridad 2: Mensajes Directos
                if not story:
                    cursor.execute("""
                        SELECT c.*, p.telefono 
                        FROM comunicaciones c
                        JOIN propiedades p ON c.propiedad_id = p.id
                        WHERE c.estado = 'pendiente' AND c.tipo = 'whatsapp'
                        ORDER BY c.fecha_programada ASC
                        LIMIT 1
                    """)
                    msg = cursor.fetchone()
            finally:
                conn.close()
            
            if story:
                print(f"\n[>] PRIORIDAD: Procesando HISTORIA ID {story['id']} (Orden: {story['orden']}) para fecha {story['fecha_programada']}")
                clean_path = story['archivo_path'].replace('/static/', 'static/')
                file_path = os.path.join(BASE_DIR, clean_path.replace('/', os.sep))
                
                if os.path.exists(file_path):
                    # Pausa humana aleatoria previa (10 a 25 segundos)
                    import random
                    pre_delay = random.randint(10, 25)
                    print(f"  [⏳] ANTI-BAN: Simulación humana previa de {pre_delay}s antes de publicar estado...")
                    time.sleep(pre_delay)

                    success = post_whatsapp_status(port, file_path)
                    
                    conn = get_db()
                    if success:
                        conn.execute("UPDATE historias_redes SET estado = 'completado', fecha_publicacion = ? WHERE id = ?", 
                                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), story['id']))
                        print(f"  [✓] HISTORIA ID {story['id']} publicada exitosamente.")
                    else:
                        reintentos = (story['reintentos'] or 0) + 1
                        if reintentos < 3:
                            proximo = datetime.now() + timedelta(minutes=30)
                            new_fecha = proximo.strftime('%Y-%m-%d %H:%M:%S')
                            print(f"  [!] Fallo Story - Reintentando en 30 minutos. Intento {reintentos}/3")
                            conn.execute("UPDATE historias_redes SET fecha_programada = ?, reintentos = ? WHERE id = ?", 
                                        (new_fecha, reintentos, story['id']))
                        else:
                            print(f"  [!] Fallo Story definitivo.")
                            conn.execute("UPDATE historias_redes SET estado = 'error: WA Status failed multiple times' WHERE id = ?", (story['id'],))
                    conn.commit()
                    conn.close()
                    
                    # Pausa post-publicación
                    post_delay = random.randint(20, 45)
                    print(f"  [⏳] ANTI-BAN: Pausa de seguridad post-publicación de {post_delay}s...")
                    time.sleep(post_delay)
                else:
                    print(f"  [!] Archivo no encontrado para historia: {file_path}")
                    conn = get_db()
                    conn.execute("UPDATE historias_redes SET estado = 'error: archivo vacante' WHERE id = ?", (story['id'],))
                    conn.commit()
                    conn.close()

            elif msg:
                raw_phone = str(msg['telefono'])
                clean_phone = raw_phone.replace(" ", "").replace("-", "").replace("+", "")
                
                if not clean_phone or "000000" in clean_phone or len(clean_phone) < 8:
                    print(f"  [!] Omitiendo número inválido: {raw_phone}")
                    update_comunicacion_estado(msg['id'], 'error')
                    continue

                print(f"  [+] Procesando mensaje ID {msg['id']} para {clean_phone}...")
                success = send_whatsapp_message(port, clean_phone, msg['mensaje'])
                
                if success:
                    print(f"  [OK] Mensaje enviado a {clean_phone}")
                    update_comunicacion_estado(msg['id'], 'enviada')
                    
                    import random
                    delay = random.randint(15, 30)
                    print(f"  [⏳] ANTI-BAN: Pausa de seguridad de {delay} segundos...")
                    time.sleep(delay)
                else:
                    update_comunicacion_estado(msg['id'], 'error')
                    time.sleep(10)
            
            else:
                conn = get_db()
                count_comm = conn.execute("SELECT COUNT(*) FROM comunicaciones WHERE estado = 'pendiente' AND tipo = 'whatsapp'").fetchone()[0]
                count_story = conn.execute("SELECT COUNT(*) FROM historias_redes WHERE estado = 'pendiente' AND plataforma = 'whatsapp'").fetchone()[0]
                conn.close()
                
                now_str_log = datetime.now().strftime("%H:%M:%S")
                print(f"  [-] {now_str_log}: Esperando tareas... (Historias: {count_story} | Mensajes: {count_comm})")
                time.sleep(15)
            
        except Exception as e:
            print(f"  [!] Error en el ciclo del bridge: {e}")
            time.sleep(10)

if __name__ == "__main__":
    try:
        run_bridge()
    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        input("\n⚠️ La ventana se cerrará. Presioná ENTER para salir...")
