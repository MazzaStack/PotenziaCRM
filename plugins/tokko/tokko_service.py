"""
TokkoService - Servicio de conexión con la API de Tokko Broker.
Maneja paginación automática, descarga de propiedades y búsqueda filtrada.
"""
import json
import time
import urllib.parse
import requests
from database import db


BASE_URL = "https://www.tokkobroker.com/api/v1"
PROPERTIES_PER_PAGE = 20


class TokkoService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "RealEstateCRM/1.0"
        })

    def _get(self, resource: str, params: dict = None, retries: int = 3) -> dict | None:
        """Realiza GET a la API de Tokko con reintentos automáticos."""
        url = f"{BASE_URL}/{resource}/"
        base_params = {
            "format": "json",
            "key": self.api_key,
            "lang": "es_ar"
        }
        if params:
            base_params.update(params)

        for attempt in range(retries):
            try:
                r = self.session.get(url, params=base_params, timeout=20)
                if r.status_code == 429:
                    print(f"[Tokko] Rate limit, esperando 5s (intento {attempt + 1})...")
                    time.sleep(5)
                    continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.Timeout:
                print(f"[Tokko] Timeout en intento {attempt + 1}")
                time.sleep(2)
            except requests.exceptions.RequestException as e:
                print(f"[Tokko] Error HTTP: {e}")
                return None
        return None

    def verify_connection(self) -> dict:
        """Verifica si la API Key es válida haciendo una consulta mínima."""
        data_filter = json.dumps({
            "current_localization_type": "country",
            "current_localization_id": 0,
            "price_from": 0,
            "price_to": 99999999,
            "operation_types": [1, 2, 3],
            "property_types": [1, 2, 3, 4, 5, 6, 7]
        })
        result = self._get("property/search", {
            "data": data_filter,
            "limit": 1
        })
        if result is None:
            return {"ok": False, "message": "No se pudo conectar con Tokko. Verificá la API Key."}
        
        meta = result.get("meta", {})
        total = meta.get("total_count", 0)
        return {
            "ok": True,
            "message": f"✅ Conexión exitosa. {total} propiedades disponibles en tu cuenta.",
            "total": total
        }

    def fetch_all_properties(self, callback=None) -> list[dict]:
        """
        Descarga todas las propiedades con paginación automática.
        Callback opcional para reportar progreso: callback(fetched, total)
        """
        all_props = []
        offset = 0
        limit = 100
        total = None

        while True:
            data_filter = json.dumps({
                "current_localization_type": "country",
                "current_localization_id": 0,
                "price_from": 0,
                "price_to": 99999999,
                "operation_types": [1, 2, 3],
                "property_types": [1, 2, 3, 4, 5, 6, 7]
            })
            result = self._get("property/search", {
                "data": data_filter,
                "limit": limit,
                "offset": offset
            })

            if not result:
                print(f"[Tokko] Error en fetch offset={offset}, abortando sync.")
                break

            meta = result.get("meta", {})
            objects = result.get("objects", [])

            if total is None:
                total = meta.get("total_count", 0)
                print(f"[Tokko] Total propiedades a descargar: {total}")

            all_props.extend(objects)
            offset += len(objects)

            if callback:
                callback(len(all_props), total)

            print(f"[Tokko] Descargadas {len(all_props)}/{total}")

            if not objects or offset >= total:
                break

            time.sleep(0.3)  # Respetar rate limit

        return all_props

    def search_properties(self, operation_types: list = None, property_types: list = None,
                          price_from: float = None, price_to: float = None,
                          location_id: int = 0, location_type: str = "country",
                          currency: str = None, ambientes=None) -> list[dict]:
        """
        Búsqueda filtrada de propiedades en Tokko.
        Devuelve lista de propiedades que matchean los filtros.
        """
        data_filter = {
            "current_localization_type": location_type,
            "current_localization_id": location_id,
            "price_from": price_from if price_from is not None else 0,
            "price_to": price_to if price_to is not None else 99999999,
            "operation_types": operation_types or [1, 2, 3],
            "property_types": property_types or [1, 2, 3, 4, 5, 6, 7]
        }

        if operation_types:
            data_filter["operation_types"] = operation_types
        if property_types:
            data_filter["property_types"] = property_types
        if currency:
            data_filter["currency"] = currency

        filters = []
        if ambientes:
            if isinstance(ambientes, (list, tuple)):
                int_ambientes = []
                for item in ambientes:
                    try:
                        int_ambientes.append(int(item))
                    except (ValueError, TypeError):
                        pass
                if int_ambientes:
                    if len(int_ambientes) > 1:
                        filters.append(["room_amount", "in", int_ambientes])
                    else:
                        filters.append(["room_amount", "=", int_ambientes[0]])
            else:
                try:
                    filters.append(["room_amount", "=", int(ambientes)])
                except (ValueError, TypeError):
                    pass

        if filters:
            data_filter["filters"] = filters

        result = self._get("property/search", {
            "data": json.dumps(data_filter),
            "limit": 50
        })

        if not result:
            return []

        return result.get("objects", [])

    def get_unique_producers(self, properties: list[dict]) -> list[dict]:
        """
        Extrae todos los productores únicos de la lista de propiedades descargadas.
        Devuelve lista de dicts con nombre, tokko_id y cantidad.
        """
        producer_map = {}
        for prop in properties:
            # El campo del productor puede variar según el plan, intentamos varios campos
            single_prod = prop.get("producer") or {}
            producers = []
            if single_prod and single_prod.get("name"):
                producers = [single_prod]
            else:
                producers = prop.get("producers", []) or []

            if not producers:
                # Fallback: intentar extraer del broker_id o agent
                agent = prop.get("agent") or {}
                if agent and agent.get("name"):
                    name = agent["name"].strip()
                    tid = str(agent.get("id", ""))
                    if name not in producer_map:
                        producer_map[name] = {"nombre": name, "tokko_id": tid, "cantidad": 0}
                    producer_map[name]["cantidad"] += 1
            else:
                for prod in producers:
                    name = (prod.get("name") or prod.get("nombre") or "").strip()
                    if not name:
                        continue
                    tid = str(prod.get("id", ""))
                    if name not in producer_map:
                        producer_map[name] = {"nombre": name, "tokko_id": tid, "cantidad": 0}
                    producer_map[name]["cantidad"] += 1

        return list(producer_map.values())

    @staticmethod
    def normalize_property(raw: dict) -> dict:
        """
        Normaliza una propiedad cruda de la API de Tokko al formato interno del CRM.
        """
        # Extraer primera operación y tipo de propiedad
        ops = raw.get("operations", [{}])
        op = ops[0] if ops else {}
        
        prices = op.get("prices", [{}])
        price_data = prices[0] if prices else {}
        precio = price_data.get("price", 0) or 0
        moneda = price_data.get("currency", "USD")
        tipo_op = op.get("operation_type", "") or ""
        
        prop_type = raw.get("type", {}) or {}
        tipo_prop = prop_type.get("name", "") or ""
        
        location = raw.get("location", {}) or {}
        address = raw.get("address", "") or ""
        barrio = location.get("name", "") or ""
        localidad = location.get("short_location", barrio) or barrio
        zona = location.get("full_location", localidad) or localidad
        
        geo = raw.get("geo_lat"), raw.get("geo_long")
        
        fotos = raw.get("photos", []) or []
        foto_principal = fotos[0].get("image", "") if fotos else ""
        fotos_urls = [f.get("image", "") for f in fotos if f.get("image")]
        
        # Extraer productor
        single_prod = raw.get("producer") or {}
        producers = []
        if single_prod and single_prod.get("name"):
            producers = [single_prod]
        else:
            producers = raw.get("producers", []) or []

        productor_nombre = ""
        productor_id = ""
        if producers:
            p = producers[0]
            productor_nombre = (p.get("name") or p.get("nombre") or "").strip()
            productor_id = str(p.get("id", ""))
        else:
            agent = raw.get("agent") or {}
            productor_nombre = (agent.get("name") or "").strip()
            productor_id = str(agent.get("id", ""))

        return {
            "tokko_id": str(raw.get("id", "")),
            "titulo": raw.get("publication_title") or raw.get("title") or address,
            "tipo_operacion": tipo_op,
            "tipo_propiedad": tipo_prop,
            "precio": float(precio) if precio else 0.0,
            "moneda": moneda,
            "superficie_total": raw.get("surface_total") or raw.get("total_surface") or 0,
            "superficie_cubierta": raw.get("surface") or raw.get("roofed_surface") or 0,
            "ambientes": raw.get("room_amount") or 0,
            "dormitorios": raw.get("suite_amount") or 0,
            "banos": raw.get("bathroom_amount") or 0,
            "cocheras": raw.get("parking_lot_amount") or 0,
            "barrio": barrio,
            "localidad": localidad,
            "zona": zona,
            "lat": geo[0] or 0,
            "lon": geo[1] or 0,
            "productor_nombre": productor_nombre,
            "productor_tokko_id": productor_id,
            "url_ficha": raw.get("public_url") or "",
            "foto_principal": foto_principal,
            "fotos_json": json.dumps(fotos_urls),
            "descripcion": raw.get("description") or "",
        }
