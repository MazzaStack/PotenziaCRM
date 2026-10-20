"""
Tokko Sync Scheduler - Sincronización automática de propiedades a las 10:00 y 15:00.
Se inicia como hilo de fondo al arrancar el plugin.
"""
import threading
import time
from datetime import datetime

from database import db


# Horas de sincronización (10 AM y 3 PM)
SYNC_HOURS = [10, 15]

_scheduler_thread = None
_running = False


# ─────────────────────────────────────────────
# FUNCIONES DE BASE DE DATOS
# ─────────────────────────────────────────────

def _get_api_key() -> str | None:
    return db.get_config("tokko_api_key")


def run_sync(api_key: str = None) -> dict:
    """
    Ejecuta la sincronización completa de propiedades Tokko.
    Devuelve un resumen {inserted, updated, deactivated, total, error}.
    """
    from plugins.tokko.tokko_service import TokkoService
    from plugins.tokko.db_tokko import upsert_propiedad, mark_inactive_not_in, save_productores

    key = api_key or _get_api_key()
    if not key:
        return {"error": "API Key de Tokko no configurada."}

    print("[Tokko Sync] Iniciando sincronización...")
    db.set_config("tokko_sync_status", "running")

    try:
        svc = TokkoService(key)
        raw_props = svc.fetch_all_properties()

        if not raw_props:
            db.set_config("tokko_sync_status", "idle")
            return {"error": "No se obtuvieron propiedades de Tokko. Verificá la API Key."}

        # Normalizar y persistir
        tokko_ids_seen = []
        inserted = 0
        updated = 0

        for raw in raw_props:
            normalized = TokkoService.normalize_property(raw)
            if not normalized["tokko_id"]:
                continue
            tokko_ids_seen.append(normalized["tokko_id"])
            result = upsert_propiedad(normalized)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1

        # Desactivar propiedades que ya no aparecen en Tokko
        deactivated = mark_inactive_not_in(tokko_ids_seen)

        # Actualizar tabla de productores
        all_producers = svc.get_unique_producers(raw_props)
        save_productores(all_producers)

        total = len(raw_props)
        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        db.set_config("tokko_ultima_sync", now_str)
        db.set_config("tokko_sync_total", str(total))
        db.set_config("tokko_sync_status", "idle")

        print(f"[Tokko Sync] ✅ Completada: {inserted} nuevas, {updated} actualizadas, {deactivated} desactivadas.")
        return {
            "inserted": inserted,
            "updated": updated,
            "deactivated": deactivated,
            "total": total,
            "timestamp": now_str
        }

    except Exception as e:
        db.set_config("tokko_sync_status", "idle")
        print(f"[Tokko Sync] ❌ Error: {e}")
        return {"error": str(e)}


# ─────────────────────────────────────────────
# SCHEDULER EN HILO DE FONDO
# ─────────────────────────────────────────────

def _scheduler_loop():
    """Loop infinito que dispara sync a las 10:00 y 15:00."""
    global _running
    fired_today = set()

    print("[Tokko Scheduler] Hilo de sincronización iniciado. Syncs a las 10:00 y 15:00.")
    
    while _running:
        now = datetime.now()
        today_key = now.strftime("%Y-%m-%d")
        hour = now.hour

        # Reset a medianoche
        if hour == 0 and today_key in fired_today:
            fired_today.discard(today_key)

        for sync_hour in SYNC_HOURS:
            fire_key = f"{today_key}-{sync_hour}"
            if hour == sync_hour and fire_key not in fired_today:
                fired_today.add(fire_key)
                print(f"[Tokko Scheduler] [SYNC] Disparando sync automática a las {sync_hour}:00")
                try:
                    run_sync()
                except Exception as e:
                    print(f"[Tokko Scheduler] Error en sync automática: {e}")
                break

        time.sleep(30)  # Verificar cada 30 segundos


def start_scheduler():
    """Inicia el hilo del scheduler de Tokko (solo una instancia)."""
    global _scheduler_thread, _running
    if _scheduler_thread and _scheduler_thread.is_alive():
        return

    _running = True
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop,
        name="TokkoScheduler",
        daemon=True
    )
    _scheduler_thread.start()
    print("[Tokko Scheduler] Hilo iniciado correctamente.")


def stop_scheduler():
    """Detiene el scheduler."""
    global _running
    _running = False
    print("[Tokko Scheduler] Hilo detenido.")
