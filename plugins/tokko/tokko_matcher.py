"""
Tokko Matcher - Servicio de tasación y cruce de datos utilizando comparables de Tokko Broker.
"""
import json
import math
import statistics
import re
from datetime import datetime, timedelta
from database import db
from plugins.tokko.tokko_service import TokkoService
from plugins.tokko.db_tokko import upsert_tokko_comparable


def get_tasacion_tokko(
    zona,
    tipo_propiedad,
    tipo_operacion="venta",
    metros=0,
    ambientes=None,
    max_antiguedad_meses=None,
    ignore_out_of_market=False,
    min_m2_usd=0,
    metodo_metros="totales",
    metros_cubiertos=None,
    descartar_mal_cargados=False,
    rango_negativo=0.25,
    rango_positivo=0.25,
    filtro_estricto_barrio=False
):
    """
    Realiza una valuación de mercado (tasación) consultando la red MLS de Tokko.
    1. Si hay una API Key configurada, consulta la API de Tokko para traer propiedades similares y las cachea.
    2. Consulta la base de datos local `tokko_comparables_cache` aplicando los filtros.
    3. Calcula bajo/medio/alto y estadísticas similares a la base de datos nacional.
    """
    # 1. Intentar descargar y actualizar cache desde la API de Tokko
    api_key = db.get_config("tokko_api_key")
    if api_key:
        try:
            svc = TokkoService(api_key)
            # Mapear operacion
            # 1 = Venta, 2 = Alquiler, 3 = Alquiler Temporario
            op_types = [1]
            if tipo_operacion.lower() == "alquiler":
                op_types = [2]
            elif "temporal" in tipo_operacion.lower():
                op_types = [3]

            # Mapear tipo de propiedad
            # 1 = Departamento, 2 = PH, 3 = Casa, 4 = Quinta, 5 = Terreno/Lote, 6 = Local, 7 = Oficina
            prop_type_norm = tipo_propiedad.lower().rstrip("s")
            prop_types = [1, 2, 3, 4, 5, 6, 7]
            if "departamento" in prop_type_norm:
                prop_types = [1]
            elif "ph" in prop_type_norm or "tipo casa" in prop_type_norm:
                prop_types = [2]
            elif "casa" in prop_type_norm:
                prop_types = [3]
            elif "quinta" in prop_type_norm:
                prop_types = [4]
            elif "terreno" in prop_type_norm or "lote" in prop_type_norm:
                prop_types = [5]
            elif "local" in prop_type_norm:
                prop_types = [6]
            elif "oficina" in prop_type_norm:
                prop_types = [7]

            # Realizar búsqueda inteligente en la API
            raw_results = svc.search_properties(
                operation_types=op_types,
                property_types=prop_types,
                ambientes=ambientes
            )

            # Guardar en cache
            for raw in raw_results:
                # Normalizar comparable
                norm = svc.normalize_property(raw)
                
                # Obtener estado_tokko
                status_raw = str(raw.get("status", "")).lower()
                if "active" in status_raw or "activo" in status_raw:
                    estado = "activo"
                elif "reserve" in status_raw or "reservado" in status_raw:
                    estado = "reservado"
                elif "sold" in status_raw or "vendido" in status_raw:
                    estado = "vendido"
                elif "rented" in status_raw or "alquilado" in status_raw:
                    estado = "alquilado"
                elif "suspended" in status_raw or "suspendido" in status_raw:
                    estado = "suspendido"
                else:
                    estado = status_raw if status_raw else "activo"
                norm["estado_tokko"] = estado
                
                # Obtener fecha_publicacion
                norm["fecha_publicacion"] = raw.get("created_at") or raw.get("updated_at") or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                
                # Upsert en DB
                upsert_tokko_comparable(norm)
        except Exception as e:
            print(f"[Tokko Matcher] Error al consultar API de Tokko: {e}")

    # 2. Consultar la base de datos local tokko_comparables_cache
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        conditions = []
        params = []

        # Operación
        if tipo_operacion:
            conditions.append("LOWER(tipo_operacion) LIKE ?")
            params.append(f"%{tipo_operacion.lower()}%")

        # Tipo de propiedad
        if tipo_propiedad:
            norm_tipo = tipo_propiedad.lower().rstrip("s")
            conditions.append("LOWER(tipo_propiedad) LIKE ?")
            params.append(f"%{norm_tipo}%")

        # Zona
        is_exact = False
        clean_z = ""
        if zona:
            raw_z = zona.strip()
            if re.search(r'["\'“”«»`]', raw_z):
                is_exact = True
            clean_z = re.sub(r'["\'“”«»`]', '', raw_z).strip().lower()
            conditions.append("(LOWER(zona) LIKE ? OR LOWER(barrio) LIKE ? OR LOWER(localidad) LIKE ? OR LOWER(titulo) LIKE ?)")
            z = f"%{clean_z}%"
            params.extend([z, z, z, z])

        # Ignore out of market
        if ignore_out_of_market:
            conditions.append("estado_tokko = 'activo'")

        # Max antiguedad
        if max_antiguedad_meses:
            threshold_date = (datetime.now() - timedelta(days=max_antiguedad_meses * 30)).strftime("%Y-%m-%d %H:%M:%S")
            # Reemplazar T con espacio si la DB tiene formato ISO con T
            conditions.append("replace(fecha_publicacion, 'T', ' ') >= ?")
            params.append(threshold_date)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"SELECT * FROM tokko_comparables_cache WHERE {where_clause} ORDER BY fecha_publicacion DESC"
        
        rows = conn.execute(query, params).fetchall()
        rows = [dict(r) for r in rows]
    finally:
        conn.close()

    if not rows:
        return None

    # 3. Pipeline de procesamiento y calculo de valuación
    metros_target = metros
    if metodo_metros == "cubiertos" and metros_cubiertos:
        metros_target = metros_cubiertos
    elif metodo_metros == "homogeneizados" and metros_cubiertos is not None:
        descubiertos = max(0.0, metros - metros_cubiertos)
        metros_target = metros_cubiertos + descubiertos * 0.2

    # Filtrado por metros
    valid_comparables = []
    seen_ids = set()

    for r in rows:
        if is_exact and clean_z:
            combined = f"{r.get('zona') or ''} {r.get('barrio') or ''} {r.get('localidad') or ''} {r.get('titulo') or ''}".lower()
            if clean_z not in combined:
                continue

        if filtro_estricto_barrio and clean_z:
            prop_barrio = str(r.get('barrio') or '').lower().strip()
            if prop_barrio and clean_z not in prop_barrio and prop_barrio not in clean_z:
                continue

        tid = r["tokko_id"]
        if tid in seen_ids:
            continue
        seen_ids.add(tid)

        # Extraer superficies
        m2_t = r.get("superficie_total") or 0.0
        m2_c = r.get("superficie_cubierta") or 0.0
        if m2_t <= 0:
            m2_t = m2_c
        if m2_c <= 0:
            m2_c = m2_t

        if m2_t <= 0:
            continue

        # Descartar mal cargados
        if descartar_mal_cargados and metodo_metros in ("cubiertos", "homogeneizados"):
            if abs(m2_t - m2_c) < 0.01:
                continue

        # Calcular superficie dinamica
        if metodo_metros == "cubiertos":
            m2_val = m2_c
        elif metodo_metros == "homogeneizados":
            desc = max(0.0, m2_t - m2_c)
            m2_val = m2_c + desc * 0.2
        else:
            m2_val = m2_t

        if m2_val <= 5:
            continue

        # Filtrar rango de metros
        if metros_target > 0:
            min_m = metros_target * (1.0 - rango_negativo)
            max_m = metros_target * (1.0 + rango_positivo)
            if not (min_m <= m2_val <= max_m):
                continue

        # Precio
        p = r["precio"] or 0.0
        if r.get("moneda") == "ARS":
            p = p / 1200.0  # Tipo de cambio proxy

        if min_m2_usd > 0 and (p / m2_val) < min_m2_usd:
            continue

        item = dict(r)
        item["calculated_m2"] = m2_val
        item["usd_price"] = p
        valid_comparables.append(item)

    if not valid_comparables:
        return None

    # Medias y Percentiles
    valores_referencia = []
    usa_m2 = False

    if metros_target > 0:
        usa_m2 = True
        for item in valid_comparables:
            valores_referencia.append(item["usd_price"] / item["calculated_m2"])
    else:
        for item in valid_comparables:
            valores_referencia.append(item["usd_price"])

    val_med = statistics.median(valores_referencia)
    try:
        q1 = statistics.quantiles(valores_referencia, n=4)[0]
        q3 = statistics.quantiles(valores_referencia, n=4)[2]
    except Exception:
        q1, q3 = val_med * 0.85, val_med * 1.15

    comparables = []
    for item in valid_comparables[:20]:
        comparables.append({
            "titulo": item.get("titulo") or f"Propiedad en {item.get('barrio', 'la zona')}",
            "precio": item.get("precio"),
            "moneda": item.get("moneda", "USD"),
            "m2": round(item["calculated_m2"], 1),
            "m2_total": item.get("superficie_total"),
            "m2_cubiertos": item.get("superficie_cubierta"),
            "url": item.get("url_ficha"),
            "foto": item.get("foto_principal"),
            "barrio": item.get("barrio"),
            "direccion": item.get("zona")
        })

    return {
        "bajo": round(q1, 0),
        "medio": round(val_med, 0),
        "alto": round(q3, 0),
        "m2_medio": round(val_med, 0) if usa_m2 else 0,
        "muestra": len(valid_comparables),
        "usa_m2": usa_m2,
        "area_filtrada": True if metros_target > 0 else False,
        "has_live": True,
        "comparables": comparables,
        "rango_negativo": int(rango_negativo * 100),
        "rango_positivo": int(rango_positivo * 100)
    }
