"""
publisher_log.py - Sistema de logging centralizado para el publisher de historias.
Escribe en un archivo rotativo en disco (solo visible internamente).
"""
import os
import json
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

# --- Directorio de logs ---
# Intentar escribir en FerrariDB/logs, sino usar el directorio del proyecto
_BASE_CANDIDATES = [
    r"C:\FerrariDB\logs",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"),
]
LOG_DIR = None
for _candidate in _BASE_CANDIDATES:
    try:
        os.makedirs(_candidate, exist_ok=True)
        LOG_DIR = _candidate
        break
    except Exception:
        continue

LOG_FILE = os.path.join(LOG_DIR, "publisher.log") if LOG_DIR else None
EVENT_LOG_FILE = os.path.join(LOG_DIR, "publisher_events.jsonl") if LOG_DIR else None

# --- Logger configuracion ---
_logger = logging.getLogger("publisher")
_logger.setLevel(logging.DEBUG)

if LOG_FILE:
    _fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(_fh)

# Console handler (siempre, para el terminal)
_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
_logger.addHandler(_ch)


def log(level: str, source: str, message: str, extra: dict = None):
    """
    Escribe una entrada en el log de texto y en el JSONL de eventos.
    :param level: 'info', 'warn', 'error', 'debug'
    :param source: quien lo emitió (ej: 'instagram', 'whatsapp', 'upload', 'instant_post')
    :param message: descripción legible
    :param extra: dict con datos adicionales (payload, response, etc.)
    """
    full_msg = f"[{source.upper()}] {message}"
    if extra:
        full_msg += f" | {extra}"

    getattr(_logger, level if level in ('debug', 'info', 'warning', 'error', 'critical') else 'info')(full_msg)

    # Escribir evento estructurado JSONL
    if EVENT_LOG_FILE:
        try:
            entry = {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": level,
                "source": source,
                "message": message,
                "extra": extra or {}
            }
            with open(EVENT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass


def get_recent_events(limit: int = 100) -> list:
    """
    Retorna los últimos N eventos del log JSONL (más recientes al final).
    """
    if not EVENT_LOG_FILE or not os.path.exists(EVENT_LOG_FILE):
        return []
    try:
        with open(EVENT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        events = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
        return events[-limit:]
    except Exception:
        return []


def get_log_paths() -> dict:
    return {
        "log_dir": LOG_DIR,
        "log_file": LOG_FILE,
        "events_file": EVENT_LOG_FILE,
    }
