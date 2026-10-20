"""
Scraper Client SDK for CRM
Provides seamless abstraction to communicate with the standalone Scraping Server.
Supports User/Password authentication, 30-day license tracking, and remote HTTP execution.
Does NOT import or run any scraping code locally in the CRM.
"""
import os
import json
import time
import requests
from datetime import datetime

def normalizar_fecha_filtro(fecha_val):
    """Normaliza strings o datetimes a formato estándar 'YYYY-MM-DD HH:MM:SS' para comparaciones seguras."""
    if not fecha_val:
        return None
    if hasattr(fecha_val, 'strftime'):
        return fecha_val.strftime('%Y-%m-%d %H:%M:%S')
    s = str(fecha_val).strip().replace('T', ' ')
    if '+' in s:
        s = s.split('+')[0].strip()
    if s.endswith('Z'):
        s = s[:-1].strip()
    if len(s) > 19 and (s[19] == '-' or s[19] == '+'):
        s = s[:19]
    if '.' in s:
        s = s.split('.')[0]
    if len(s) == 10:
        s = f"{s} 00:00:00"
    return s[:19]


class ScraperClient:
    _last_remote_failure = 0.0

    @classmethod
    def _get_config(cls):
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_file = os.path.join(workspace_dir, 'db_config.json')
        s_cfg = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    s_cfg = cfg.get('scraper_service', {})
            except Exception:
                pass

        return {
            'mode': 'remote',
            'url': s_cfg.get('url', 'http://127.0.0.1:5001').rstrip('/'),
            'usuario': s_cfg.get('usuario', ''),
            'api_token': s_cfg.get('api_token') or s_cfg.get('api_key', ''),
            'fecha_expiracion': s_cfg.get('fecha_expiracion', ''),
            'dias_restantes': s_cfg.get('dias_restantes', 0),
            'timeout_seconds': s_cfg.get('timeout_seconds', 15)
        }

    @classmethod
    def get_config(cls):
        return cls._get_config()

    @classmethod
    def save_scraper_config(cls, data_dict):
        return cls._save_scraper_config(data_dict)

    @classmethod
    def _save_scraper_config(cls, data_dict):
        """Guarda la configuración del scraper en db_config.json."""
        workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_file = os.path.join(workspace_dir, 'db_config.json')
        cfg = {}
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}

        current_s = cfg.get('scraper_service', {})
        current_s.update(data_dict)
        cfg['scraper_service'] = current_s

        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=4)
            return True
        except Exception as e:
            print(f"[ScraperClient] Error guardando config: {e}")
            return False

    @classmethod
    def login_and_connect(cls, url, usuario, password):
        """
        Conecta el CRM al Scraper Server validando usuario y contraseña.
        Obtiene el token de acceso y la fecha de expiración del período de 30 días.
        """
        target_url = (url or 'http://127.0.0.1:5001').rstrip('/')
        try:
            res = requests.post(
                f"{target_url}/api/v1/auth/login",
                json={'usuario': usuario, 'password': password},
                timeout=6.0
            )
            data = res.json()
            if res.status_code == 200 and data.get('success'):
                # Guardar sesión en db_config.json
                token = data.get('token')
                expira = data.get('fecha_expiracion', '')
                dias = data.get('dias_restantes', 30)
                cls._save_scraper_config({
                    'url': target_url,
                    'usuario': usuario,
                    'api_token': token,
                    'api_key': token,
                    'fecha_expiracion': expira,
                    'dias_restantes': dias,
                    'connected_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                return {
                    'success': True,
                    'message': data.get('message', f'Conectado exitosamente ({dias} días restantes).'),
                    'dias_restantes': dias,
                    'fecha_expiracion': expira
                }
            else:
                return {
                    'success': False,
                    'message': data.get('message', f'Error {res.status_code}: Credenciales rechazadas por el motor.')
                }
        except Exception as e:
            return {
                'success': False,
                'message': f'No se pudo conectar al servidor de scraping en {target_url}: {e}'
            }

    @classmethod
    def disconnect(cls):
        """Desconecta el CRM del motor de scraping."""
        cls._save_scraper_config({
            'usuario': '',
            'api_token': '',
            'api_key': '',
            'fecha_expiracion': '',
            'dias_restantes': 0
        })
        return {'success': True, 'message': 'Desconectado del motor de scraping.'}

    @classmethod
    def check_license_status(cls):
        """Devuelve el estado de la licencia de 30 días guardada."""
        cfg = cls._get_config()
        if not cfg.get('api_token'):
            return {'connected': False, 'message': 'No conectado al motor de scraping'}

        exp_str = cfg.get('fecha_expiracion')
        if not exp_str:
            return {'connected': True, 'expired': False, 'dias_restantes': 30, 'message': 'Conectado'}

        try:
            exp_dt = datetime.strptime(str(exp_str)[:19], "%Y-%m-%d %H:%M:%S")
            ahora = datetime.now()
            if ahora > exp_dt:
                return {
                    'connected': True,
                    'expired': True,
                    'dias_restantes': 0,
                    'fecha_expiracion': exp_str,
                    'message': f'Acceso de 30 días vencido el {exp_dt.strftime("%d/%m/%Y")}. Solicite renovación.'
                }
            delta = exp_dt - ahora
            dias = delta.days
            return {
                'connected': True,
                'expired': False,
                'dias_restantes': dias,
                'fecha_expiracion': exp_str,
                'message': f'Acceso activo ({dias} días restantes, vence {exp_dt.strftime("%d/%m/%Y")})'
            }
        except Exception:
            return {'connected': True, 'expired': False, 'dias_restantes': 30, 'message': 'Conectado'}

    @classmethod
    def _get_headers(cls):
        cfg = cls._get_config()
        token = cfg.get('api_token') or cfg.get('api_key', '')
        return {
            'Authorization': f'Bearer {token}',
            'X-Scraper-API-Key': token,
            'Content-Type': 'application/json'
        }

    @classmethod
    def is_paused(cls):
        cfg = cls._get_config()
        try:
            res = requests.get(f"{cfg['url']}/api/v1/health", headers=cls._get_headers(), timeout=3.0)
            if res.status_code == 200:
                return res.json().get('telemetry', {}).get('is_paused', False)
        except Exception:
            pass
        return False

    @classmethod
    def test_inspect_property(cls, url, save_to_db=False):
        """Delega la extracción de prueba en vivo al servidor central de scraping."""
        cfg = cls._get_config()
        lic = cls.check_license_status()
        if lic.get('expired'):
            return {'success': False, 'error': lic.get('message', 'Período de scraping vencido.')}

        try:
            res = requests.post(
                f"{cfg['url']}/api/v1/test/inspect",
                json={'url': url, 'save_to_db': save_to_db},
                headers=cls._get_headers(),
                timeout=30
            )
            if res.status_code in (200, 400, 422):
                return res.json()
            return {'success': False, 'error': f'El servidor de scraping respondió con código {res.status_code}'}
        except Exception as e:
            return {'success': False, 'error': f'No se pudo conectar al servidor de scraping ({cfg["url"]}): {e}'}

    @classmethod
    def search_properties(cls, filters=None, limit=50, offset=0):
        """Consulta propiedades vía API REST al motor de scraping."""
        filters = filters or {}
        cfg = cls._get_config()

        now = time.time()
        if now - cls._last_remote_failure > 60:
            try:
                payload = {**filters, 'limit': limit, 'offset': offset}
                res = requests.post(
                    f"{cfg['url']}/api/v1/properties",
                    json=payload,
                    headers=cls._get_headers(),
                    timeout=(1.5, 4.0)
                )
                if res.status_code == 200:
                    data = res.json()
                    return data.get('properties', []), data.get('total', 0)
            except Exception:
                cls._last_remote_failure = time.time()

        return [], 0

    @classmethod
    def trigger_async_search(cls, params, max_pages=6):
        """Inicia un barrido asíncrono en el servidor de scraping."""
        cfg = cls._get_config()
        try:
            payload = {**params, 'max_pages': max_pages}
            res = requests.post(
                f"{cfg['url']}/api/v1/search/async",
                json=payload,
                headers=cls._get_headers(),
                timeout=cfg.get('timeout_seconds', 10)
            )
            if res.status_code == 200:
                return res.json().get('job_uuid')
        except Exception as e:
            print(f"[ScraperClient] Error disparando búsqueda remota: {e}")
        return None

    @classmethod
    def get_search_job_status(cls, job_uuid):
        """Consulta el progreso de un job asíncrono en el motor de scraping."""
        cfg = cls._get_config()
        try:
            res = requests.get(f"{cfg['url']}/api/v1/search/status/{job_uuid}", headers=cls._get_headers(), timeout=3.0)
            if res.status_code == 200:
                return res.json().get('job')
        except Exception:
            pass
        return None

    @classmethod
    def test_connection(cls, url=None, usuario=None, password=None, api_key=None):
        """Prueba la conexión y estado del motor de scraping."""
        cfg = cls._get_config()
        target_url = (url or cfg.get('url', 'http://127.0.0.1:5001')).rstrip('/')
        
        # Si se envían credenciales, intentar login directo
        if usuario and password:
            return cls.login_and_connect(target_url, usuario, password)

        target_token = api_key or cfg.get('api_token') or cfg.get('api_key', '')
        try:
            headers = {
                'Authorization': f'Bearer {target_token}',
                'X-Scraper-API-Key': target_token
            }
            res = requests.get(f"{target_url}/api/v1/health", headers=headers, timeout=4.0)
            if res.status_code == 200:
                data = res.json()
                telemetry = data.get('telemetry', {})
                proxies = telemetry.get('proxies', {}).get('total', 0)
                lic = cls.check_license_status()
                return {
                    'success': True,
                    'status': 'online',
                    'proxies': proxies,
                    'license': lic,
                    'message': f"Servidor Online. {proxies} proxies disponibles. {lic.get('message', '')}"
                }
            return {'success': False, 'status': 'error', 'message': f"El servidor respondió con código {res.status_code}"}
        except Exception as e:
            return {'success': False, 'status': 'offline', 'message': f"No se pudo conectar a {target_url}: {e}"}
