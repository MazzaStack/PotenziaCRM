"""
social_publisher.py
Publica en Instagram Stories via Meta Graph API.
Usa publisher_log para registrar cada paso con detalle diagnóstico.
"""
import os
import time
import json
import sqlite3
import requests
from datetime import datetime, timedelta

# ── Logging ──────────────────────────────────────────────────────────────────
from lib.publisher_log import log as plog

# ── Database ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Resuelve el path real de la DB (respetando db_config.json)
def _resolve_db_path():
    config_file = os.path.join(BASE_DIR, 'db_config.json')
    default = r"C:\FerrariDB\captador.db" if os.name == 'nt' else os.path.join(BASE_DIR, 'database', 'captador.db')
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            db_dir = cfg.get('db_dir')
            if db_dir:
                return os.path.join(db_dir, 'captador.db')
    except Exception:
        pass
    return default

DB_PATH = _resolve_db_path()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_config_value(clave):
    conn = get_db()
    try:
        row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
        return row['valor'] if row else None
    finally:
        conn.close()


def get_ngrok_url():
    return get_config_value('ngrok_url')


# ── Instagram via Meta Graph API ──────────────────────────────────────────────

def publish_to_meta(file_path: str) -> tuple[bool, str]:
    """
    Publica una imagen en Instagram Stories via Meta Graph API.

    Returns:
        (success: bool, message: str)  — message contiene el error detallado si falla
    """
    plog('info', 'instagram', f'Iniciando intento de publicación. Archivo: {file_path}')

    # 1. Verificar credenciales
    meta_token = get_config_value('meta_access_token')
    ig_id = get_config_value('ig_account_id')

    if not meta_token:
        msg = 'meta_access_token no configurado en el CRM (Configuración → Meta API Token)'
        plog('error', 'instagram', msg)
        return False, msg

    if not ig_id:
        msg = 'ig_account_id no configurado en el CRM (Configuración → Instagram Account ID)'
        plog('error', 'instagram', msg)
        return False, msg

    plog('debug', 'instagram', f'Credenciales OK. IG Account ID: {ig_id}, Token: ...{meta_token[-8:]}')

    # 2. Verificar ngrok_url
    ngrok_url = get_ngrok_url()
    if not ngrok_url:
        msg = 'ngrok_url no configurado. Meta API requiere una URL pública para acceder a la imagen.'
        plog('error', 'instagram', msg)
        return False, msg

    plog('debug', 'instagram', f'ngrok_url: {ngrok_url}')

    # 3. Armar URL pública de la imagen
    if 'static' not in file_path:
        msg = f'No se pudo armar URL pública: la ruta "{file_path}" no contiene "static".'
        plog('error', 'instagram', msg)
        return False, msg

    rel_path = file_path.split('static', 1)[1].replace('\\', '/')
    public_url = f"{ngrok_url.rstrip('/')}/static{rel_path}"
    plog('info', 'instagram', f'URL pública construida: {public_url}')

    # 4. Verificar que la imagen es accesible públicamente
    try:
        r_check = requests.head(public_url, timeout=8, allow_redirects=True)
        plog('debug', 'instagram', f'Check URL pública: HTTP {r_check.status_code}')
        if r_check.status_code != 200:
            msg = f'La imagen no es accesible públicamente. URL: {public_url} → HTTP {r_check.status_code}. ¿Está ngrok corriendo?'
            plog('error', 'instagram', msg)
            return False, msg
    except Exception as e:
        msg = f'No se pudo alcanzar la URL pública {public_url}: {e}'
        plog('error', 'instagram', msg)
        return False, msg

    try:
        # 5. Crear Contenedor de Media en Instagram
        url_container = f"https://graph.facebook.com/v19.0/{ig_id}/media"
        payload_container = {
            'image_url': public_url,
            'media_type': 'STORIES',
            'access_token': meta_token
        }
        plog('debug', 'instagram', f'POST → {url_container}', {'payload': {k: v for k, v in payload_container.items() if k != 'access_token'}})

        r1 = requests.post(url_container, data=payload_container, timeout=30)
        res1 = r1.json()
        plog('debug', 'instagram', f'Respuesta contenedor HTTP {r1.status_code}', {'response': res1})

        if 'error' in res1:
            err = res1['error']
            msg = f"Meta API Error #{err.get('code')}: {err.get('message')} (type: {err.get('type')})"
            plog('error', 'instagram', msg, {'full_response': res1})
            return False, msg

        if 'id' not in res1:
            msg = f'Respuesta inesperada al crear contenedor (sin campo "id"): {res1}'
            plog('error', 'instagram', msg)
            return False, msg

        creation_id = res1['id']
        plog('info', 'instagram', f'Contenedor creado OK. creation_id: {creation_id}')
        time.sleep(3)  # Meta puede necesitar unos segundos para procesar

        # 6. Publicar el Contenedor
        url_publish = f"https://graph.facebook.com/v19.0/{ig_id}/media_publish"
        payload_publish = {
            'creation_id': creation_id,
            'access_token': meta_token
        }
        plog('debug', 'instagram', f'POST → {url_publish}', {'creation_id': creation_id})

        r2 = requests.post(url_publish, data=payload_publish, timeout=30)
        res2 = r2.json()
        plog('debug', 'instagram', f'Respuesta publicación HTTP {r2.status_code}', {'response': res2})

        if 'error' in res2:
            err = res2['error']
            msg = f"Meta API Error al publicar #{err.get('code')}: {err.get('message')} (type: {err.get('type')})"
            plog('error', 'instagram', msg, {'full_response': res2})
            return False, msg

        if 'id' in res2:
            media_id = res2['id']
            plog('info', 'instagram', f'¡Historia publicada en Instagram! Media ID: {media_id}')
            return True, f'Publicado OK. Media ID: {media_id}'
        else:
            msg = f'Respuesta inesperada al publicar (sin campo "id"): {res2}'
            plog('error', 'instagram', msg)
            return False, msg

    except requests.exceptions.Timeout:
        msg = 'Timeout al contactar Meta Graph API (>30s)'
        plog('error', 'instagram', msg)
        return False, msg
    except Exception as e:
        msg = f'Excepción inesperada en Meta publish: {type(e).__name__}: {e}'
        plog('error', 'instagram', msg)
        return False, msg


# ── Worker Loop ───────────────────────────────────────────────────────────────

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

def process_historias():
    plog('info', 'worker_ig', '--- Iniciando Social Publisher Worker (INSTAGRAM via Meta Graph API) ---')

    while True:
        now = datetime.now()
        # Ampliamos ventana horaria humanizada de 06:20 a 23:50
        if (now.hour == 6 and now.minute >= 20) or (7 <= now.hour <= 23 and not (now.hour == 23 and now.minute > 50)):
            try:
                conn = get_db()
                today_date = now.strftime('%Y-%m-%d')

                # Obtener candidatos pendientes para hoy o antes
                jobs = conn.execute("""
                    SELECT * FROM historias_redes
                    WHERE date(fecha_programada) <= ? AND estado = 'pendiente'
                    AND (
                        instagram = 1
                        OR (instagram IS NULL AND plataforma = 'instagram')
                    )
                    ORDER BY fecha_programada ASC, orden ASC
                """, (today_date,)).fetchall()

                if jobs:
                    # Encontrar el primer job que ya superó su horario objetivo
                    job_to_process = None
                    for job in jobs:
                        target_dt = get_target_datetime(job['fecha_programada'], job['orden'])
                        if now >= target_dt:
                            job_to_process = job
                            break

                    if job_to_process:
                        # Control Anti-bot: Verificar que no hayamos publicado nada hace menos de 30 min
                        last_pub_row = conn.execute("""
                            SELECT fecha_publicacion FROM historias_redes
                            WHERE estado = 'completado' AND fecha_publicacion IS NOT NULL
                            ORDER BY fecha_publicacion DESC LIMIT 1
                        """).fetchone()

                        if last_pub_row:
                            last_pub_dt = datetime.strptime(last_pub_row['fecha_publicacion'], '%Y-%m-%d %H:%M:%S')
                            if (now - last_pub_dt).total_seconds() < 1800:
                                plog('info', 'worker_ig', 'Anti-bot: última publicación hace menos de 30 minutos. Esperando...')
                                conn.close()
                                time.sleep(120)
                                continue

                        job = job_to_process
                        clean_path = job['archivo_path'].replace('/static/', 'static/')
                        file_path = os.path.join(BASE_DIR, clean_path.replace('/', os.sep))

                        plog('info', 'worker_ig', f'Procesando placa ID {job["id"]} (orden {job["orden"]}, fecha {job["fecha_programada"]})')

                        if os.path.exists(file_path):
                            ok, msg = publish_to_meta(file_path)

                            if ok:
                                conn.execute(
                                    "UPDATE historias_redes SET estado = 'completado', fecha_publicacion = ? WHERE id = ?",
                                    (now.strftime('%Y-%m-%d %H:%M:%S'), job['id'])
                                )
                                plog('info', 'worker_ig', f'Placa ID {job["id"]} → completado. {msg}')
                            else:
                                reintentos = (job['reintentos'] or 0) + 1
                                if reintentos < 3:
                                    proximo = now + timedelta(minutes=15)
                                    plog('warning', 'worker_ig', f'Placa ID {job["id"]} falló. Reintento {reintentos}/3 en 15 min. Error: {msg}')
                                    conn.execute(
                                        "UPDATE historias_redes SET fecha_programada = ?, reintentos = ?, error_log = ? WHERE id = ?",
                                        (proximo.strftime('%Y-%m-%d %H:%M:%S'), reintentos, msg, job['id'])
                                    )
                                else:
                                    plog('error', 'worker_ig', f'Placa ID {job["id"]} falló definitivamente tras {reintentos} intentos. Error: {msg}')
                                    conn.execute(
                                        "UPDATE historias_redes SET estado = ?, error_log = ? WHERE id = ?",
                                        (f'error: {msg[:100]}', msg, job['id'])
                                    )

                            conn.commit()
                            time.sleep(60)
                        else:
                            plog('error', 'worker_ig', f'Archivo no encontrado: {file_path}')
                            conn.execute(
                                "UPDATE historias_redes SET estado = 'error: archivo vacante', error_log = ? WHERE id = ?",
                                (f'Ruta buscada: {file_path}', job['id'])
                            )
                            conn.commit()
                    else:
                        # Ningún candidato ha llegado a su hora objetivo de publicación
                        time.sleep(120)
                else:
                    time.sleep(300)

                conn.close()

            except Exception as e:
                plog('error', 'worker_ig', f'Error crítico en ciclo principal: {type(e).__name__}: {e}')
                time.sleep(60)
        else:
            time.sleep(3600)


if __name__ == '__main__':
    print("Social Publisher (IG) está en pausa. Las historias se procesan ahora vía whatsapp_sender.py")
