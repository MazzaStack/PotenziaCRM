import os
import time
import json
import random
from pathlib import Path
import requests
from requests.adapters import BaseAdapter
from requests.models import Response
from io import BytesIO
import types
from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    TwoFactorRequired,
    LoginRequired,
    BadPassword,
    BadCredentials,
    ClientError,
    UnknownError,
)
from lib.publisher_log import log as plog

# ── Pool de 14 dispositivos Android reales y populares ───────────────────────
# Fuente: especificaciones reales extraídas de sesiones legítimas de instagrapi.
# Solo se usan dispositivos con alta cuota de mercado para minimizar fingerprinteo.
DEVICE_POOL = [
    {"id": "samsung_s21",    "manufacturer": "samsung",  "model": "SM-G991B",  "android_version": 31, "android_release": "12",   "dpi": "421dpi",  "resolution": "1080x2280", "cpu": "exynos2100"},
    {"id": "samsung_s22",    "manufacturer": "samsung",  "model": "SM-S901B",  "android_version": 31, "android_release": "12",   "dpi": "425dpi",  "resolution": "1080x2340", "cpu": "exynos2200"},
    {"id": "samsung_a52",    "manufacturer": "samsung",  "model": "SM-A525F",  "android_version": 30, "android_release": "11",   "dpi": "407dpi",  "resolution": "1080x2400", "cpu": "qcom"},
    {"id": "samsung_a53",    "manufacturer": "samsung",  "model": "SM-A536B",  "android_version": 31, "android_release": "12",   "dpi": "400dpi",  "resolution": "1080x2408", "cpu": "exynos1280"},
    {"id": "samsung_s20fe",  "manufacturer": "samsung",  "model": "SM-G780F",  "android_version": 30, "android_release": "11",   "dpi": "407dpi",  "resolution": "1080x2400", "cpu": "exynos990"},
    {"id": "pixel6",         "manufacturer": "Google",   "model": "Pixel 6",   "android_version": 32, "android_release": "12",   "dpi": "411dpi",  "resolution": "1080x2400", "cpu": "tensor"},
    {"id": "pixel7",         "manufacturer": "Google",   "model": "Pixel 7",   "android_version": 33, "android_release": "13",   "dpi": "416dpi",  "resolution": "1080x2400", "cpu": "tensor_g2"},
    {"id": "pixel5",         "manufacturer": "Google",   "model": "Pixel 5",   "android_version": 30, "android_release": "11",   "dpi": "432dpi",  "resolution": "1080x2340", "cpu": "qcom"},
    {"id": "xiaomi_redmi11", "manufacturer": "Xiaomi",   "model": "Redmi Note 11", "android_version": 31, "android_release": "11", "dpi": "401dpi", "resolution": "1080x2400", "cpu": "qcom"},
    {"id": "xiaomi_mi11",    "manufacturer": "Xiaomi",   "model": "M2011K2G",  "android_version": 30, "android_release": "11",   "dpi": "515dpi",  "resolution": "1440x3200", "cpu": "qcom"},
    {"id": "oneplus9",       "manufacturer": "OnePlus",  "model": "LE2113",    "android_version": 31, "android_release": "12",   "dpi": "450dpi",  "resolution": "1080x2400", "cpu": "qcom"},
    {"id": "realme9pro",     "manufacturer": "realme",   "model": "RMX3393",   "android_version": 31, "android_release": "12",   "dpi": "394dpi",  "resolution": "1080x2412", "cpu": "qcom"},
    {"id": "moto_g82",       "manufacturer": "motorola", "model": "motorola edge 30", "android_version": 31, "android_release": "12", "dpi": "400dpi", "resolution": "1080x2400", "cpu": "qcom"},
    {"id": "oppo_reno6",     "manufacturer": "OPPO",     "model": "CPH2235",   "android_version": 30, "android_release": "11",   "dpi": "409dpi",  "resolution": "1080x2400", "cpu": "qcom"},
]


def _device_file_path(username: str) -> Path:
    """Ruta al archivo JSON con el dispositivo único asignado permanentemente a esta cuenta."""
    return Path(r'C:\FerrariDB\usuarios') / username / 'ig_device.json'


def assign_device(username: str) -> dict:
    """
    Asigna UN único dispositivo Android de forma PERMANENTE a este usuario del CRM.
    Una vez creado, este hardware NUNCA cambia (garantiza el mismo modelo, procesador y DPI de por vida).
    """
    dev_file = _device_file_path(username)
    dev_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Si ya existe el dispositivo fijo, lo leemos
    if dev_file.exists():
        try:
            device = json.loads(dev_file.read_text(encoding='utf-8'))
            if 'id' in device and 'manufacturer' in device:
                return device
        except Exception:
            pass

    # 2. Migración desde el legacy pair si existiera
    legacy_pair_file = Path(r'C:\FerrariDB\usuarios') / username / 'ig_device_pair.json'
    if legacy_pair_file.exists():
        try:
            pair = json.loads(legacy_pair_file.read_text(encoding='utf-8'))
            chosen = pair.get('primary') or pair.get('secondary')
            if chosen and 'id' in chosen:
                dev_file.write_text(json.dumps(chosen, indent=2, ensure_ascii=False), encoding='utf-8')
                return chosen
        except Exception:
            pass

    # 3. Sorteamos 1 dispositivo del pool por única vez
    chosen = random.choice(DEVICE_POOL)
    dev_file.write_text(json.dumps(chosen, indent=2, ensure_ascii=False), encoding='utf-8')
    plog('info', 'instagram', f'[{username}] Dispositivo Android permanente ASIGNADO: {chosen["id"]} ({chosen["model"]})')
    return chosen


def get_session_device(username: str) -> dict:
    """Devuelve el dispositivo único fijo asignado a esta cuenta."""
    return assign_device(username)


def assign_device_pair(username: str) -> dict:
    """Compatibilidad hacia atrás con código que espera estructura {'primary': dev, 'secondary': dev}."""
    dev = assign_device(username)
    return {'primary': dev, 'secondary': dev}


# Diccionarios globales para transferir datos de verificación entre hilos/solicitudes HTTP
pending_challenges = {}
challenge_choices = {}

def challenge_code_handler(username, choice):
    """Callback invocado por instagrapi cuando detecta un desafío (checkpoint)."""
    plog('info', 'instagram', f'Desafío de seguridad detectado para {username}. Opción: {choice}')
    challenge_choices[username] = str(choice)
    start_time = time.time()
    
    # Espera hasta 90 segundos a que el usuario provea el código desde el frontend
    while time.time() - start_time < 90:
        if username in pending_challenges and pending_challenges[username] is not None:
            code = pending_challenges.pop(username)
            plog('info', 'instagram', f'Código de desafío recibido para {username}: {code}')
            challenge_choices.pop(username, None)
            return code
        time.sleep(0.5)
        
    challenge_choices.pop(username, None)
    plog('error', 'instagram', f'Timeout esperando código de desafío para {username}')
    raise TimeoutError("Timeout esperando el código de verificación de Instagram.")


def totp_code_handler(username):
    """Callback invocado por instagrapi cuando el usuario tiene autenticación de dos factores (2FA)."""
    plog('info', 'instagram', f'Autenticación de Dos Factores (2FA) requerida para {username}.')
    challenge_choices[username] = "2fa"
    start_time = time.time()
    
    while time.time() - start_time < 90:
        if username in pending_challenges and pending_challenges[username] is not None:
            code = pending_challenges.pop(username)
            plog('info', 'instagram', f'Código 2FA recibido para {username}: {code}')
            challenge_choices.pop(username, None)
            return code
        time.sleep(0.5)
        
    challenge_choices.pop(username, None)
    plog('error', 'instagram', f'Timeout esperando código 2FA para {username}')
    raise TimeoutError("Timeout esperando el código 2FA de Instagram.")


def get_session_path(username: str) -> Path:
    """Retorna la ruta del archivo de sesión persistente en el directorio home del usuario."""
    home_dir = Path(os.path.expanduser('~'))
    return home_dir / f".instagram_session_{username}.json"


class _MockRawResponse:
    def __init__(self, headers, content):
        self._content = content
        self.headers = headers
        self._original_response = self
        self.msg = self

    def info(self):
        return self

    def get_all(self, name, default=None):
        vals = []
        name_l = name.lower()
        for k, v in self.headers.items():
            if k.lower() == name_l:
                vals.append(v)
        return vals if vals else (default or [])

    def getheaders(self, name):
        return self.get_all(name)


class CurlTransportAdapter(BaseAdapter):
    """
    [FASE 2b] Adaptador de transporte de alto rendimiento basado en curl_cffi.
    Reemplaza la pila de Python (requests/urllib3/OpenSSL) por BoringSSL
    con negociación HTTP/2 (h2) e impersonación móvil (chrome131_android).
    Elimina la huella TLS de Python en las conexiones hacia Meta.
    """
    def __init__(self, impersonate='chrome131_android'):
        super().__init__()
        from curl_cffi import requests as curl_requests
        self.impersonate = impersonate
        self.curl_session = curl_requests.Session(impersonate=self.impersonate)

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        req_headers = dict(request.headers)
        curl_kwargs = {
            'method': request.method,
            'url': request.url,
            'headers': req_headers,
            'data': request.body,
            'stream': stream,
            'timeout': timeout,
            'verify': verify,
            'allow_redirects': False,
        }
        if proxies:
            curl_kwargs['proxies'] = proxies

        try:
            curl_resp = self.curl_session.request(**curl_kwargs)
        except Exception as e:
            raise requests.exceptions.ConnectionError(f'Curl transport error: {e}') from e

        response = Response()
        response.status_code = curl_resp.status_code
        response.headers = requests.structures.CaseInsensitiveDict(curl_resp.headers)
        response.raw = _MockRawResponse(curl_resp.headers, curl_resp.content)
        response._content = curl_resp.content
        response.url = curl_resp.url
        response.encoding = curl_resp.encoding
        response.request = request
        return response


def _attach_curl_transport(cl):
    """
    [FASE 2b] Configura transporte HTTP/2 (h2) de alto rendimiento basado en curl_cffi.
    Reemplaza la pila estándar de Python (requests/urllib3/OpenSSL) por BoringSSL TLS 1.3
    con soporte de curvas post-cuánticas híbridas (X25519MLKEM768), coincidiendo exactamente
    con la huella TLS de la app móvil de Instagram (Fizz TLS).
    """
    try:
        cl.set_retry_config(private_transport='curl', public_transport='curl')
        plog('debug', 'instagram', '[FASE 2b] Transporte HTTP/2 nativo instagrapi (BoringSSL Android TLS 1.3) activo.')
        return True
    except Exception as e:
        plog('warning', 'instagram', f'[FASE 2b] Transporte nativo retornó ({e}), usando CurlTransportAdapter fallback...')
        try:
            adapter = CurlTransportAdapter(impersonate='chrome131_android')
            cl.private.mount('https://', adapter)
            cl.public.mount('https://', adapter)
            return True
        except Exception as e2:
            plog('error', 'instagram', f'[FASE 2b] Falló fallback CurlTransportAdapter: {e2}')
            return False


def _parse_caa_failure(cl):
    """
    Extrae la causa real de rechazo desde la respuesta Bloks CAA de Meta.
    Evita caer en el endpoint obsoleto 'accounts/login/' que devuelve el falso error
    'Your version of Instagram is out of date'.
    """
    data = getattr(cl, 'last_json', None) or {}
    text = json.dumps(data) if isinstance(data, dict) else str(data)

    if "Incorrect password" in text or "The password you entered is incorrect" in text:
        raise BadPassword("Contraseña incorrecta. Verificá la contraseña en la app oficial de Instagram.")

    if "login_wrong_username_error_dialog_shown" in text or "user_not_found" in text.lower():
        raise BadCredentials("El nombre de usuario no existe o no fue encontrado en Instagram.")

    if "text_captcha" in text or "anti_scripting" in text:
        raise ChallengeRequired(
            "Meta activó un control anti-bot (CAPTCHA). "
            "Meta no enviará ningún SMS ni WhatsApp: abrí Instagram en tu celular para confirmar 'Sí, fui yo', o vinculá la cuenta pegando tu Session ID."
        )

    if "checkpoint_required" in text.lower() or "challenge_required" in text.lower():
        raise ChallengeRequired("Meta solicitó verificación de seguridad (Challenge/Checkpoint). Abrí Instagram en tu teléfono para confirmar el acceso.")

    if "two_factor" in text.lower() or "two_step" in text.lower():
        raise TwoFactorRequired("Se requiere código de verificación de dos factores (2FA).")

    reason = data.get("reason") if isinstance(data, dict) else None
    if reason and reason != "CAA login did not return a session":
        raise ClientError(str(reason))

    raise BadCredentials("Instagram no pudo validar el inicio de sesión. Verificá tus credenciales en la app oficial.")


def _setup_client_security(cl):
    """
    Asegura que el cliente use el transporte HTTP/2 nativo con huella Android
    y previene que instagrapi caiga al endpoint obsoleto accounts/login/ (legacy fallback).
    """
    _attach_curl_transport(cl)
    cl.login_legacy = types.MethodType(lambda self, *args, **kwargs: _parse_caa_failure(self), cl)


def _safe_login(cl, username, password, session_file):
    """
    Intenta login completo con usuario/contraseña vía CAA Bloks y persiste la sesión.
    Maneja el error 467 (Consent Required de Meta) post-login y traduce errores reales de login.
    """
    try:
        # relogin=True asegura limpiar cookies y encabezados huérfanos antes de autenticar
        cl.login(username, password, relogin=True)
        cl.dump_settings(session_file)
        return {'success': True, 'status': 'connected', 'message': 'Conectado exitosamente'}
    except (ChallengeRequired, TwoFactorRequired):
        raise
    except BadPassword as bp:
        plog('warning', 'instagram', f'[{username}] Contraseña incorrecta: {bp}')
        return {'success': False, 'status': 'bad_password', 'error': str(bp)}
    except BadCredentials as bc:
        plog('warning', 'instagram', f'[{username}] Credenciales incorrectas: {bc}')
        return {'success': False, 'status': 'bad_credentials', 'error': str(bc)}
    except Exception as e:
        err_str = str(e)
        if '467' in err_str:
            plog('warning', 'instagram',
                 f'Error 467 (Consent Required) post-login para {username}. Guardando sesión...')
            try:
                cl.dump_settings(session_file)
            except Exception as dump_err:
                plog('warning', 'instagram', f'No se pudo hacer dump de sesión: {dump_err}')
            return {'success': True, 'status': 'connected',
                    'message': 'Conectado (sesión aceptada por Instagram)'}

        # Si surge un error genérico (ej. UnknownError o ClientError), inspeccionamos last_json
        try:
            _parse_caa_failure(cl)
        except (BadPassword, BadCredentials) as typed_err:
            plog('warning', 'instagram', f'[{username}] Error de autenticación tipado: {typed_err}')
            return {'success': False, 'status': 'bad_credentials', 'error': str(typed_err)}
        except (ChallengeRequired, TwoFactorRequired):
            raise
        except Exception:
            pass

        plog('error', 'instagram', f'[{username}] Error en _safe_login: {err_str}')
        raise


def _ensure_authenticated_manual(cl, username, password, session_file) -> dict:
    """
    Usado ÚNICAMENTE en conectar_instagram (interfaz manual del panel).
    - Si existe un archivo de sesión, se carga (con override_app_version=True para modernizar la versión) y se prueba.
    - Si no existe o expiró (LoginRequired), realiza login primario con credenciales y guarda la sesión.
    """
    if session_file.exists():
        try:
            cl.load_settings(session_file, override_app_version=True)
            _setup_client_security(cl)
            plog('info', 'instagram', f'[{username}] Probando sesión existente en disco ({session_file.name})...')
            cl.get_reels_tray_feed(reason='pull_to_refresh')
            plog('info', 'instagram', f'[{username}] Sesión activa validada exitosamente.')
            # Persistimos la versión modernizada en disco
            cl.dump_settings(session_file)
            return {'success': True, 'status': 'connected', 'message': 'Sesión activa reusada'}
        except LoginRequired:
            plog('warning', 'instagram', f'[{username}] Sesión en disco expirada (LoginRequired). Re-autenticando con credenciales...')
        except (ChallengeRequired, TwoFactorRequired):
            raise
        except Exception as e:
            plog('debug', 'instagram', f'[{username}] Comprobación arrojó ({e}). Intentando login con credenciales...')

    plog('info', 'instagram', f'[{username}] Iniciando login manual con credenciales...')
    return _safe_login(cl, username, password, session_file)


def _simulate_cdn_assets_download(cl, urls: list, max_items: int = 3) -> int:
    """
    [PUNTO 1] Descarga imágenes reales desde la CDN de Meta (Akamai / FB-CDN) usando una sesión limpia
    independiente (como lo hace el image loader nativo de Android: Glide / Fresco),
    SIN filtrar tokens ni cabeceras privadas de autorización de la API de Instagram.
    """
    import requests
    downloaded = 0
    # User-Agent del dispositivo configurado para coherencia de hardware
    ua = getattr(cl, 'user_agent', None) or 'Instagram 449.0.0.52.84 Android'
    clean_session = requests.Session()
    clean_session.headers.update({
        'User-Agent': ua,
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
    })
    try:
        for url in urls[:max_items]:
            if not url or not isinstance(url, str) or not url.startswith('http'):
                continue
            try:
                resp = clean_session.get(url, timeout=7)
                if resp.status_code == 200 and len(resp.content) > 0:
                    downloaded += 1
                time.sleep(random.uniform(0.3, 0.7))
            except Exception as _dl_err:
                plog('debug', 'instagram', f'Error menor descargando asset CDN: {_dl_err}')
    finally:
        clean_session.close()
    return downloaded


def _warmup_stories_tray(cl, username: str):
    """
    Carga la barra superior de historias (Reels Tray) y descarga avatares por canal CDN limpio.
    """
    plog('debug', 'instagram', f'[{username}] Warmup: consultando bandeja de historias (Reels Tray)...')
    tray_data = cl.get_reels_tray_feed(reason='pull_to_refresh')
    
    avatar_urls = []
    if isinstance(tray_data, dict):
        tray_items = tray_data.get('tray') or []
        for item in tray_items[:6]:
            u = item.get('user') or {}
            pic = u.get('profile_pic_url')
            if pic:
                avatar_urls.append(pic)

    if avatar_urls:
        n_dl = _simulate_cdn_assets_download(cl, avatar_urls, max_items=random.randint(2, 4))
        plog('debug', 'instagram', f'[{username}] Warmup: renderizados {n_dl} avatares de historias desde CDN.')

    pause = random.randint(4, 8)
    time.sleep(pause)


def _warmup_timeline_feed(cl, username: str):
    """
    Carga el feed principal y descarga 1-2 fotos reales de publicaciones por canal CDN limpio.
    """
    plog('debug', 'instagram', f'[{username}] Warmup: consultando Timeline Feed...')
    feed_data = cl.get_timeline_feed(reason='pull_to_refresh')
    
    post_image_urls = []
    if isinstance(feed_data, dict):
        feed_items = feed_data.get('feed_items') or []
        for item in feed_items[:4]:
            media = item.get('media_or_ad') or {}
            img_versions = media.get('image_versions2') or {}
            candidates = img_versions.get('candidates') or []
            if candidates and isinstance(candidates, list):
                post_image_urls.append(candidates[0].get('url'))

    if post_image_urls:
        n_dl = _simulate_cdn_assets_download(cl, post_image_urls, max_items=random.randint(1, 2))
        plog('debug', 'instagram', f'[{username}] Warmup: cacheadas {n_dl} imágenes del feed desde CDN.')

    pause = random.randint(5, 10)
    time.sleep(pause)


def _human_warmup(cl, username: str):
    """
    [PUNTO 2] Secuencia canónica de apertura de la app móvil (App Launch / Cold Start):
    1. Carga la bandeja superior de historias (Reels Tray) y descarga avatares por CDN limpio.
    2. Pausa natural de 4 a 8 segundos.
    3. Carga el timeline/feed de noticias y descarga imágenes por CDN limpio.
    4. Pausa natural de 5 a 10 segundos.
    Esto reproduce la secuencia real de apertura de Android y valida la sesión de forma 100% natural.
    """
    plog('info', 'instagram', f'[{username}] Iniciando secuencia natural de apertura de app...')
    _warmup_stories_tray(cl, username)
    _warmup_timeline_feed(cl, username)
    plog('info', 'instagram', f'[{username}] Secuencia de apertura completada.')


def pad_image_to_9_16(image_path: str) -> str:
    """
    Ajusta una imagen para que tenga una relación de aspecto de 9:16 sin distorsionarla ni recortarla (zoom).
    Le agrega barras negras laterales o superior/inferior para encuadrarla perfectamente en 1080x1920.
    Retorna la ruta de una nueva imagen temporal JPEG de 1080x1920.
    """
    from PIL import Image
    import tempfile
    
    try:
        with Image.open(image_path) as img:
            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                background = Image.new('RGB', img.size, (0, 0, 0))
                background.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else img.convert('RGBA').split()[3])
                img = background
            else:
                img = img.convert('RGB')
                
            orig_w, orig_h = img.size
            target_w = 1080
            target_h = 1920
            
            scale_w = target_w / orig_w
            scale_h = target_h / orig_h
            scale = min(scale_w, scale_h)
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
            
            resampling = getattr(Image, 'Resampling', None)
            if resampling:
                img_resized = img.resize((new_w, new_h), resampling.LANCZOS)
            else:
                img_resized = img.resize((new_w, new_h), Image.ANTIALIAS)
            
            canvas = Image.new('RGB', (target_w, target_h), (0, 0, 0))
            x = (target_w - new_w) // 2
            y = (target_h - new_h) // 2
            canvas.paste(img_resized, (x, y))
            
            temp_dir = tempfile.gettempdir()
            out_filename = f"ig_story_padded_{os.path.basename(image_path)}"
            if not out_filename.lower().endswith(('.jpg', '.jpeg')):
                out_filename = os.path.splitext(out_filename)[0] + '.jpg'
            out_path = os.path.join(temp_dir, out_filename)
            
            canvas.save(out_path, 'JPEG', quality=95)
            return out_path
    except Exception as e:
        plog('warning', 'instagram', f'Error al reencuadrar la imagen a 9:16: {e}')
        return image_path


def conectar_instagram(username, password) -> dict:
    """
    Intenta vincular una cuenta de Instagram usando instagrapi.
    Retorna un diccionario indicando el resultado.
    """
    username = username.strip().lower()
    session_file = get_session_path(username)
    
    # 1. Asignar dispositivo Android fijo y permanente para este agente
    device = assign_device(username)
    plog('info', 'instagram', f'[{username}] Dispositivo de sesión fijo: {device["id"]} ({device["model"]})')

    cl = Client()
    cl.set_device(device)
    _setup_client_security(cl)
    cl.challenge_code_handler = lambda choice: challenge_code_handler(username, choice)
    cl.totp_code_handler = lambda: totp_code_handler(username)
    
    pending_challenges.pop(username, None)
    challenge_choices.pop(username, None)

    plog('info', 'instagram', f'Iniciando vinculación de cuenta para: {username}')

    try:
        result = _ensure_authenticated_manual(cl, username, password, session_file)
        plog('info', 'instagram', f'Vinculación exitosa y sesión lista para {username}')
        return result

    except (ChallengeRequired, TwoFactorRequired) as sec_exc:
        err_msg = str(sec_exc)
        plog('info', 'instagram', f'Se requiere verificación para {username}: {err_msg}')
        choice = challenge_choices.get(username, 'verificación')
        is_captcha = 'captcha' in err_msg.lower() or 'anti_scripting' in err_msg.lower()
        if is_captcha:
            return {
                'success': False,
                'status': 'captcha_required',
                'challenge_type': 'captcha',
                'message': err_msg,
                'error': err_msg
            }
        return {
            'success': False,
            'status': 'checkpoint_required',
            'challenge_type': choice,
            'message': f'Se requiere código de verificación ({choice})'
        }
    except Exception as e:
        err_msg = str(e)
        plog('error', 'instagram', f'Error de vinculación para {username}: {err_msg}')
        return {'success': False, 'status': 'disconnected', 'error': err_msg}


def desvincular_instagram(username):
    """Elimina los archivos de sesión persistentes de la cuenta de Instagram."""
    username = username.strip().lower()
    session_file = get_session_path(username)
    if session_file.exists():
        try:
            session_file.unlink()
            plog('info', 'instagram', f'Sesión eliminada para {username}')
        except Exception as e:
            plog('error', 'instagram', f'No se pudo eliminar el archivo de sesión para {username}: {e}')
    
    pending_challenges.pop(username, None)
    challenge_choices.pop(username, None)
    return {'success': True, 'message': 'Cuenta desvinculada y sesión eliminada'}


def invalidar_sesion(username):
    """Elimina el archivo de sesión local para forzar una renovación limpia."""
    session_file = get_session_path(username.strip().lower())
    if session_file.exists():
        try:
            session_file.unlink()
            plog('warning', 'instagram', f'Sesión inválida eliminada para {username}')
        except Exception as e:
            plog('error', 'instagram', f'No se pudo eliminar sesión de {username}: {e}')


def publicar_historia_privada(username, password, file_path: str) -> tuple[bool, str]:
    """
    Publica una imagen o video local en Instagram Stories utilizando la sesión persistente de instagrapi.
    Incluye:
      - Cero logins redundantes (reutilización pasiva de sesión)
      - Transporte HTTP/2 nativo con huella TLS Android vía curl_cffi
      - Calentamiento humano auténtico con descarga real de assets desde Meta CDN
      - Pausa humana previa a la cámara (20-60 seg)
      - Reencuadre automático a 9:16 (1080x1920) sin distorsión ni recorte
      - Reintentos automáticos para errores transitorios (412 retriable)

    Returns:
        (success: bool, message: str)
    """
    username = username.strip().lower()
    session_file = get_session_path(username)
    abs_path = os.path.abspath(file_path)

    if not os.path.exists(abs_path):
        return False, f"Archivo no encontrado en disco: {abs_path}"

    plog('info', 'instagram', f'Iniciando subida de historia privada para {username}. Archivo: {abs_path}')

    cl = Client()
    # Asignar el dispositivo Android fijo permanente de este usuario
    device = get_session_device(username)
    if device:
        cl.set_device(device)
    _setup_client_security(cl)
    
    # Handlers silenciosos para no bloquear procesos en segundo plano
    cl.challenge_code_handler = lambda choice: None
    cl.totp_code_handler = lambda: None

    temp_padded_path = None
    try:
        try:
            # 1. [PUNTO 3] Cero login con contraseña en modo automático.
            # La sesión DEBE existir previamente desde el panel de Configuración.
            if not session_file.exists():
                plog('error', 'instagram', f'[{username}] No existe archivo de sesión ({session_file.name}). Cancelando subida automática.')
                return False, f"RELINK_REQUIRED:No existe sesión vinculada para {username}. Vinculá la cuenta desde el panel de Configuración."

            try:
                cl.load_settings(session_file, override_app_version=True)
                _setup_client_security(cl)
                plog('info', 'instagram', f'[{username}] Sesión cargada desde {session_file.name}.')
            except Exception as load_err:
                plog('error', 'instagram', f'[{username}] Error al cargar sesión: {load_err}')
                return False, f"RELINK_REQUIRED:Error al leer sesión guardada para {username}. Re-vinculá desde el panel."

            # 2. [PUNTO 2] Secuencia humana de apertura de app (Stories Tray + Timeline Feed con descargas limpias de CDN)
            # Esto además valida la sesión de forma 100% natural sin endpoints artificiales.
            try:
                _human_warmup(cl, username)
            except LoginRequired:
                plog('warning', 'instagram', f'[{username}] Meta retornó LoginRequired durante la apertura de app.')
                return False, "RELINK_REQUIRED:La sesión de Instagram ha expirado. Re-vinculá tu cuenta desde el panel de Configuración."
            except ChallengeRequired:
                plog('error', 'instagram', f'[{username}] Meta solicitó Challenge durante apertura. Se preserva archivo de sesión.')
                return False, "RELINK_REQUIRED:Meta solicitó verificación de seguridad (Challenge). Validá desde el panel o la app."

            # 3. Pausa Humana Previa a la Subida (Apertura de cámara/editor)
            from database import db
            _conn_test = None
            _is_test_mode = False
            try:
                _conn_test = db.get_db()
                _test_row = _conn_test.execute("SELECT valor FROM configuracion WHERE clave = 'publisher_test_mode'").fetchone()
                _is_test_mode = (_test_row and _test_row['valor'] == '1')
            except Exception:
                pass
            finally:
                if _conn_test and hasattr(_conn_test, 'close'):
                    _conn_test.close()

            if not _is_test_mode:
                pre_delay = random.randint(18, 45)
                plog('info', 'instagram', f'[{username}] Pausa pre-upload de {pre_delay}s simulando selección y edición en la app...')
                time.sleep(pre_delay)
            else:
                plog('info', 'instagram', f'[{username}] ⚡ TEST MODE: Saltando pre-delay de Instagram.')

            # 4. Determinar tipo de medio y reencuadrar a 9:16
            ext = os.path.splitext(abs_path)[1].lower()
            is_video = ext in ['.mp4', '.mov', '.avi']

            upload_path = abs_path
            if not is_video:
                try:
                    temp_padded_path = pad_image_to_9_16(abs_path)
                    upload_path = temp_padded_path
                except Exception as pad_err:
                    plog('warning', 'instagram', f'Paso alternativo por error de pad: {pad_err}')

            # 5. Subida con gestión de reintentos
            max_intentos = 3
            for intento in range(1, max_intentos + 1):
                try:
                    if is_video:
                        plog('debug', 'instagram', f'Subiendo video a Story (intento {intento}): {upload_path}')
                        media = cl.video_upload_to_story(Path(upload_path))
                    else:
                        plog('debug', 'instagram', f'Subiendo foto a Story (intento {intento}): {upload_path}')
                        media = cl.photo_upload_to_story(Path(upload_path))

                    media_id = getattr(media, 'pk', 'unknown')
                    msg = f"Historia publicada con éxito en Instagram. Media ID: {media_id}"
                    plog('info', 'instagram', msg)
                    return True, msg

                except ChallengeRequired:
                    plog('error', 'instagram', f'challenge_required durante subida para {username}. Se preserva archivo de sesión.')
                    return False, "RELINK_REQUIRED:Meta solicitó verificación de seguridad (Challenge/Checkpoint). Validá desde el panel o la app."

                except Exception as upload_err:
                    err_str = str(upload_err)
                    if ('412' in err_str or 'retriable' in err_str.lower()) and intento < max_intentos:
                        delay = intento * 12
                        plog('warning', 'instagram', f'Error 412 (retriable) en intento {intento}/{max_intentos}. Esperando {delay}s...')
                        time.sleep(delay)
                        continue
                    plog('error', 'instagram', f'Error al publicar historia para {username} (intento {intento}): {err_str}')
                    return False, err_str

        except (LoginRequired, ChallengeRequired) as _sec_err:
            msg = f"RELINK_REQUIRED:La sesión de Instagram requiere validación manual ({_sec_err})."
            plog('error', 'instagram', msg)
            return False, msg
        except Exception as e:
            err_msg = str(e)
            plog('error', 'instagram', f'Error inesperado al publicar historia para {username}: {err_msg}')
            return False, err_msg
    finally:
        # [PUNTO 4] Persistir siempre las cookies y tokens rotados por Meta tras cualquier interacción con la API
        if session_file and cl and getattr(cl, 'user_id', None):
            try:
                cl.dump_settings(session_file)
                plog('debug', 'instagram', f'[{username}] [FASE 1] Sesión y cookies rotadas sincronizadas en disco ({session_file.name}).')
            except Exception as _dump_err:
                plog('warning', 'instagram', f'No se pudo sincronizar sesión en disco: {_dump_err}')

        if temp_padded_path and os.path.exists(temp_padded_path):
            try:
                os.remove(temp_padded_path)
            except Exception:
                pass
