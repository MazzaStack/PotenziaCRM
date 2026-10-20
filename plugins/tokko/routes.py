"""
Tokko Plugin Routes - Cartera Inmobiliaria, Buscador combinado, Mis Operaciones y Config.
"""
import difflib
import json
import threading
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from modules.auth import privilege_required

from database import db
from plugins.tokko.db_tokko import (
    init_tokko_tables,
    get_propiedades_cartera,
    get_propiedades_by_productor,
    get_all_productores,
    get_zonas_unicas,
    get_tokko_stats
)
from plugins.tokko.sync_scheduler import run_sync, start_scheduler

tokko_bp = Blueprint("tokko", __name__, url_prefix="/tokko")

# Inicializar tablas e iniciar scheduler al cargar el módulo
init_tokko_tables()
start_scheduler()


# ─────────────────────────────────────────────────────────────
# CARTERA DE MARCA
# ─────────────────────────────────────────────────────────────

from modules.auth import privilege_required

@tokko_bp.route("/cartera")
@login_required
@privilege_required('plugin', 'tokko')
def cartera():
    """Vista de catálogo completo de propiedades en cartera."""
    is_solo_agent = not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza'
    
    if is_solo_agent:
        return render_template(
            "tokko_cartera.html",
            props=[],
            total=0,
            page=1,
            total_pages=1,
            zonas=[],
            stats={'total': 0, 'ventas': 0, 'alquileres': 0},
            ultima_sync=db.get_config("tokko_ultima_sync", "Nunca"),
            is_solo_agent=True,
            filtros={"operacion": "", "tipo": "", "precio_min": "", "precio_max": "", "zona": ""}
        )

    tipo_operacion = request.args.get("operacion", "")
    tipo_propiedad = request.args.get("tipo", "")
    precio_min = request.args.get("precio_min", "")
    precio_max = request.args.get("precio_max", "")
    zona = request.args.get("zona", "")
    page = request.args.get("page", 1, type=int)

    props, total = get_propiedades_cartera(
        tipo_operacion=tipo_operacion or None,
        tipo_propiedad=tipo_propiedad or None,
        precio_min=precio_min or None,
        precio_max=precio_max or None,
        zona=zona or None,
        page=page,
        per_page=12
    )

    total_pages = (total + 11) // 12
    zonas = get_zonas_unicas()
    stats = get_tokko_stats()
    ultima_sync = db.get_config("tokko_ultima_sync", "Nunca")

    return render_template(
        "tokko_cartera.html",
        props=props,
        total=total,
        page=page,
        total_pages=total_pages,
        zonas=zonas,
        stats=stats,
        ultima_sync=ultima_sync,
        is_solo_agent=False,
        filtros={
            "operacion": tipo_operacion,
            "tipo": tipo_propiedad,
            "precio_min": precio_min,
            "precio_max": precio_max,
            "zona": zona
        }
    )


# ─────────────────────────────────────────────────────────────
# BUSCADOR COMBINADO (Cartera Propia + Portales)
# ─────────────────────────────────────────────────────────────

@tokko_bp.route("/buscar")
@login_required
@privilege_required('plugin', 'tokko')
def buscar():
    """Buscador que muestra primero las propiedades en cartera y luego las de portales."""
    if not request.args.get("operacion") and not request.args.get("zona"):
        return render_template("tokko_buscar.html", ferrari=[], portales=[], buscado=False,
                               filtros={"operacion": "", "tipo": "", "zona": "", "precio_min": "", "precio_max": ""})

    operacion = request.args.get("operacion", "")
    tipo = request.args.get("tipo", "")
    zona = request.args.get("zona", "")
    precio_min = request.args.get("precio_min", "")
    precio_max = request.args.get("precio_max", "")

    # 1. Propiedades en cartera desde nuestra DB
    ferrari, _ = get_propiedades_cartera(
        tipo_operacion=operacion or None,
        tipo_propiedad=tipo or None,
        precio_min=precio_min or None,
        precio_max=precio_max or None,
        zona=zona or None,
        page=1,
        per_page=50
    )

    # 2. Propiedades de portales externos vía ScraperClient
    portales = []
    try:
        from lib.scraper_client import ScraperClient
        ext_props, _ = ScraperClient.search_properties({
            'zona': zona,
            'tipo_propiedad': tipo or "departamento",
            'min_precio': float(precio_min) if precio_min else None,
            'max_precio': float(precio_max) if precio_max else None,
            'tipo_operacion': operacion or "venta"
        }, limit=30)
        portales = ext_props
    except Exception as e:
        print(f"[Tokko Buscar] Error buscando en motor de scraping: {e}")

    return render_template(
        "tokko_buscar.html",
        ferrari=ferrari,
        portales=portales,
        buscado=True,
        filtros={
            "operacion": operacion,
            "tipo": tipo,
            "zona": zona,
            "precio_min": precio_min,
            "precio_max": precio_max
        }
    )


# ─────────────────────────────────────────────────────────────
# MIS OPERACIONES (Propiedades donde el agente es productor)
# ─────────────────────────────────────────────────────────────

@tokko_bp.route("/mis_operaciones")
@login_required
@privilege_required('plugin', 'tokko')
def mis_operaciones():
    """Lista propiedades en Tokko donde el agente logueado figura como productor."""
    # Obtener el nombre de productor vinculado al usuario actual
    productor_nombre = db.get_config(f"tokko_productor_{current_user.id}")

    props = []
    if productor_nombre:
        props = get_propiedades_by_productor(productor_nombre)

    return render_template(
        "tokko_mis_operaciones.html",
        props=props,
        productor_vinculado=productor_nombre
    )


@tokko_bp.route("/mis_operaciones/importar", methods=["POST"])
@login_required
def importar_operaciones():
    """Importa propiedades seleccionadas al seguimiento de operaciones del agente."""
    tokko_ids = request.form.getlist("tokko_ids")
    if not tokko_ids:
        flash("No seleccionaste ninguna propiedad.", "warning")
        return redirect(url_for("tokko.mis_operaciones"))

    conn = db.get_db(db.MASTER_DB_PATH)
    importadas = 0
    try:
        for tid in tokko_ids:
            row = conn.execute(
                "SELECT * FROM tokko_propiedades WHERE tokko_id = ?", (tid,)
            ).fetchone()
            if not row:
                continue
            p = dict(row)
            # Insertar en seguimiento_operaciones con datos de Tokko
            conn.execute("""
                INSERT INTO seguimiento_operaciones (
                    agente_id, domicilio, estado, mes, informes, modificado_por, fecha_registro
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """, (
                current_user.id,
                p.get("titulo") or p.get("barrio") or "Sin dirección",
                "activo",
                datetime.now().strftime("%m/%Y"),
                f"Importado desde Tokko ID: {tid}",
                current_user.usuario
            ))
            importadas += 1

        conn.commit()
        flash(f"✅ {importadas} operación/es importada/s al seguimiento.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error al importar: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("finanzas_plugin.seguimiento_prop"))


# ─────────────────────────────────────────────────────────────
# FUZZY SEARCH DE PRODUCTORES
# ─────────────────────────────────────────────────────────────

@tokko_bp.route("/config/productores/buscar")
@login_required
def buscar_productor():
    """Busca productores en Tokko con fuzzy matching para vincular al usuario."""
    query = request.args.get("q", "").strip().lower()
    if not query or len(query) < 2:
        return jsonify([])

    productores = get_all_productores()
    nombres = [p["nombre"] for p in productores]

    if not nombres:
        return jsonify([])

    # SequenceMatcher fuzzy matching
    matches = difflib.get_close_matches(query, [n.lower() for n in nombres], n=8, cutoff=0.25)

    # Mapear de vuelta a nombre original con score
    resultado = []
    for prod in productores:
        nombre_lower = prod["nombre"].lower()
        if nombre_lower in matches or query in nombre_lower:
            score = difflib.SequenceMatcher(None, query, nombre_lower).ratio()
            resultado.append({
                "nombre": prod["nombre"],
                "tokko_id": prod.get("tokko_id", ""),
                "cantidad": prod.get("cantidad_propiedades", 0),
                "score": round(score, 3)
            })

    resultado.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(resultado[:5])


@tokko_bp.route("/config/productores/vincular", methods=["POST"])
@login_required
def vincular_productor():
    """Vincula el nombre de productor Tokko al usuario logueado."""
    productor_nombre = request.form.get("productor_nombre", "").strip()
    if not productor_nombre:
        return jsonify({"ok": False, "message": "Nombre vacío."})

    db.set_config(f"tokko_productor_{current_user.id}", productor_nombre)
    return jsonify({
        "ok": True,
        "message": f"✅ Vinculado como: <strong>{productor_nombre}</strong>"
    })


# ─────────────────────────────────────────────────────────────
# SINCRONIZACIÓN MANUAL
# ─────────────────────────────────────────────────────────────

@tokko_bp.route("/sync/trigger", methods=["POST"])
@login_required
def trigger_sync():
    """Dispara sincronización manual en hilo de fondo. Solo admins."""
    api_key = db.get_config("tokko_api_key")
    if not api_key:
        return jsonify({"ok": False, "message": "❌ API Key de Tokko no configurada."})

    status = db.get_config("tokko_sync_status")
    if status == "running":
        return jsonify({"ok": False, "message": "⏳ Ya hay una sincronización en curso."})

    def _sync_bg():
        try:
            from plugins.loading_overlay.routes import push_log, start_log_session
            start_log_session('tokko-sync')
            push_log('[Tokko] Iniciando sincronización de cartera...')
        except Exception:
            pass
        run_sync(api_key)

    t = threading.Thread(target=_sync_bg, daemon=True)
    t.start()

    return jsonify({"ok": True, "message": "⚡ Sincronización iniciada en segundo plano."})


@tokko_bp.route("/sync/status")
@login_required
def sync_status():
    """Devuelve el estado actual de la sincronización."""
    return jsonify({
        "status": db.get_config("tokko_sync_status", "idle"),
        "ultima_sync": db.get_config("tokko_ultima_sync", "Nunca"),
        "total": db.get_config("tokko_sync_total", "0")
    })


# ─────────────────────────────────────────────────────────────
# VERIFICAR CONEXIÓN
# ─────────────────────────────────────────────────────────────

@tokko_bp.route("/config/verificar", methods=["POST"])
@login_required
def verificar_conexion():
    """Verifica si la API Key ingresada funciona."""
    api_key = request.form.get("tokko_api_key", "").strip()
    if not api_key:
        return jsonify({"ok": False, "message": "Ingresá la API Key primero."})

    from plugins.tokko.tokko_service import TokkoService
    svc = TokkoService(api_key)
    result = svc.verify_connection()
    return jsonify(result)
