"""
Rate Limiter centralizado para CRM.
Protege contra ataques de fuerza bruta en login y abusos en endpoints públicos.
"""
from flask import request

def get_client_ip():
    """Obtiene la IP real del cliente considerando Cloudflare y Proxies Inversos."""
    ip = request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For', request.remote_addr)
    if ip and ',' in ip:
        ip = ip.split(',')[0].strip()
    return ip or request.remote_addr

try:
    from flask_limiter import Limiter
    limiter = Limiter(
        key_func=get_client_ip,
        default_limits=[],  # Sin límite global para no afectar polling interno
        storage_uri="memory://"
    )
except ImportError:
    class DummyLimiter:
        """Fallback no-op limiter en caso de que flask-limiter no esté instalado."""
        def __init__(self, *args, **kwargs):
            pass
        def init_app(self, app):
            pass
        def limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
        def shared_limit(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
        def exempt(self, f):
            return f

    limiter = DummyLimiter()
