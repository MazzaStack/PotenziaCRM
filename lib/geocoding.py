"""
Intelligent Geocoding and Address Normalization Engine for Argentina (CABA, AMBA and Interior).
1. Verifies if existing portal (Argenprop, Zonaprop, ML) coordinates are valid
   and geographically coherent with the declared neighborhood (rejects Tandil/Ocean/Bogus defaults).
2. Sanitizes informal Argentine addresses (e.g. 'al 3400', 'altura 3400', 'e/', floors, deptos).
3. Queries USIG GCBA API (CABA/AMBA) + Nominatim / Photon (OSM) + Barrio Centroids fallback.
4. Uses a local in-memory cache for high throughput and zero redundancy.
"""
import re
import math
import json
import urllib.parse
import urllib.request
import threading
from typing import Tuple, Optional, Dict, Any

_GEO_CACHE: Dict[str, Tuple[float, float]] = {}
_CACHE_LOCK = threading.Lock()

BARRIO_CENTROIDS = {
    # CABA
    'palermo': (-34.5880, -58.4120),
    'palermo soho': (-34.5880, -58.4230),
    'palermo hollywood': (-34.5810, -58.4350),
    'palermo chico': (-34.5780, -58.4030),
    'recoleta': (-34.5890, -58.3930),
    'barrio norte': (-34.5910, -58.3980),
    'belgrano': (-34.5620, -58.4560),
    'belgrano r': (-34.5710, -58.4650),
    'belgrano c': (-34.5580, -58.4510),
    'puerto madero': (-34.6100, -58.3620),
    'nunez': (-34.5450, -58.4650),
    'nuñez': (-34.5450, -58.4650),
    'colegiales': (-34.5780, -58.4480),
    'caballito': (-34.6180, -58.4410),
    'almagro': (-34.6090, -58.4210),
    'villa crespo': (-34.5980, -58.4410),
    'chacarita': (-34.5880, -58.4550),
    'villa urquiza': (-34.5730, -58.4870),
    'villa devoto': (-34.6010, -58.5120),
    'villa del parque': (-34.6070, -58.4910),
    'coghlan': (-34.5640, -58.4730),
    'saavedra': (-34.5480, -58.4900),
    'san telmo': (-34.6210, -58.3710),
    'montserrat': (-34.6130, -58.3820),
    'retiro': (-34.5930, -58.3750),
    'san nicolas': (-34.6040, -58.3810),
    'centro': (-34.6037, -58.3816),
    'flores': (-34.6290, -58.4630),
    'floresta': (-34.6310, -58.4810),
    'barracas': (-34.6410, -58.3810),
    'la boca': (-34.6360, -58.3630),
    'parque patricios': (-34.6360, -58.4050),
    'boedo': (-34.6270, -58.4180),
    'balvanera': (-34.6100, -58.4010),
    'once': (-34.6080, -58.4070),
    'parque chacabuco': (-34.6340, -58.4410),
    'parque chas': (-34.5840, -58.4800),
    'agronomia': (-34.5920, -58.4890),
    'liniers': (-34.6450, -58.5250),
    'mataderos': (-34.6550, -58.5020),
    'villa luro': (-34.6380, -58.5010),
    'villa ortuzar': (-34.5810, -58.4710),
    'villa pueyrredon': (-34.5810, -58.5030),
    'villa real': (-34.6190, -58.5270),
    'villa santa rita': (-34.6180, -58.4810),
    'versalles': (-34.6280, -58.5240),
    'velez sarsfield': (-34.6350, -58.4900),

    # GBA NORTE
    'vicente lopez': (-34.5290, -58.4780),
    'olivos': (-34.5110, -58.4920),
    'florida': (-34.5360, -58.4980),
    'la lucila': (-34.4980, -58.4910),
    'martinez': (-34.4930, -58.5120),
    'san isidro': (-34.4710, -58.5280),
    'acassuso': (-34.4820, -58.5080),
    'beccar': (-34.4560, -58.5360),
    'victoria': (-34.4450, -58.5520),
    'san fernando': (-34.4420, -58.5610),
    'tigre': (-34.4250, -58.5790),
    'nordelta': (-34.4050, -58.6540),
    'rincon de milberg': (-34.4100, -58.5900),
    'general pacheco': (-34.4580, -58.6410),
    'benavidez': (-34.3980, -58.6890),
    'dique lujan': (-34.3680, -58.7050),
    'escobar': (-34.3486, -58.7908),
    'ingeniero maschwitz': (-34.3850, -58.7420),
    'garin': (-34.4250, -58.7350),
    'pilar': (-34.4580, -58.9140),
    'del viso': (-34.4450, -58.8020),
    'manuel alberti': (-34.4550, -58.7650),
    'tortuguitas': (-34.4710, -58.7550),
    'grand bourg': (-34.4900, -58.7180),
    'san martin': (-34.5770, -58.5380),
    'villa ballester': (-34.5490, -58.5550),

    # GBA OESTE & SUR
    'moron': (-34.6530, -58.6180),
    'castelar': (-34.6510, -58.6400),
    'haedo': (-34.6460, -58.5970),
    'ramos mejia': (-34.6420, -58.5650),
    'san justo': (-34.6780, -58.5580),
    'ciudadela': (-34.6360, -58.5360),
    'ituzaingo': (-34.6580, -58.6720),
    'avellaneda': (-34.6620, -58.3650),
    'lanus': (-34.7060, -58.3920),
    'lomas de zamora': (-34.7610, -58.4020),
    'banfield': (-34.7430, -58.3980),
    'temperley': (-34.7780, -58.3980),
    'quilmes': (-34.7210, -58.2560),
    'bernal': (-34.7080, -58.2810),
    'adrogue': (-34.7980, -58.3910),
    'la plata': (-34.9210, -57.9540)
}

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    try:
        r = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c
    except Exception:
        return 9999.0

def normalize_text_key(text: str) -> str:
    if not text: return ''
    from unicodedata import normalize
    clean = re.sub(r'([^n\u0300-\u036f]|n(?!\u0303(?![\u0300-\u036f])))[\u0300-\u036f]+', r'\1',
                   normalize('NFD', str(text)), 0, re.I)
    return clean.lower().strip()

def clean_argentine_address(raw_address: str) -> str:
    if not raw_address:
        return ''
    addr = str(raw_address).strip()
    addr = re.sub(r'\([^)]*\)', '', addr)
    addr = re.sub(r'\b(?:piso|depto|departamento|dpto|dto|uf|unidad|torre|bloque|pb|ambientes|amb)\b.*', '', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\b\d+(?:ro|do|to|er|mo|vo|no)?\s*[\"\'A-Za-z]\b', '', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\b(?:frente|contrafrente|lateral|interno)\b', '', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bal\s+(\d+)\b', r'\1', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\baltura\s+(\d+)\b', r'\1', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\b(?:nro|n°|num|numero)\.?\s*(\d+)\b', r'\1', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\b(?:avda|av)\.?\s*', 'Av. ', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bpje\.?\s*', 'Pasaje ', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bdiag\.?\s*', 'Diagonal ', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\s+', ' ', addr)
    return addr.strip(' ,-./')

def is_valid_and_coherent_coordinate(lat: Any, lng: Any, barrio: str = '', direccion: str = '') -> bool:
    if lat is None or lng is None:
        return False
    try:
        f_lat = float(lat)
        f_lng = float(lng)
    except (ValueError, TypeError):
        return False

    if abs(f_lat) < 0.001 and abs(f_lng) < 0.001:
        return False

    if not (-56.0 <= f_lat <= -21.0) or not (-74.0 <= f_lng <= -53.0):
        return False

    if haversine_distance_km(f_lat, f_lng, -38.416097, -63.616672) < 40.0:
        return False
    if haversine_distance_km(f_lat, f_lng, -37.32167, -59.13316) < 30.0:
        return False
    if haversine_distance_km(f_lat, f_lng, -36.6769, -60.5588) < 30.0:
        return False

    barrio_norm = normalize_text_key(barrio)
    target_zone = barrio_norm if barrio_norm in BARRIO_CENTROIDS else extract_zone_from_text(direccion or barrio)
    if target_zone and target_zone in BARRIO_CENTROIDS:
        c_lat, c_lng = BARRIO_CENTROIDS[target_zone]
        dist = haversine_distance_km(f_lat, f_lng, c_lat, c_lng)
        if dist > 8.0:
            return False

    return True

def _geocode_via_usig_caba(clean_dir: str) -> Optional[Tuple[float, float]]:
    try:
        q = urllib.parse.quote(clean_dir)
        url = f'http://servicios.usig.buenosaires.gob.ar/normalizar/?direccion={q}'
        req = urllib.request.Request(url, headers={'User-Agent': 'FerrariCRM/2.0'})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and isinstance(data, dict):
                norm_list = data.get('direccionesNormalizadas', [])
                if norm_list and len(norm_list) > 0:
                    first = norm_list[0]
                    coords = first.get('coordenadas', {})
                    if coords and 'x' in coords and 'y' in coords:
                        c_lng = float(coords['x'])
                        c_lat = float(coords['y'])
                        if is_valid_and_coherent_coordinate(c_lat, c_lng):
                            return (c_lat, c_lng)
    except Exception:
        pass
    return None

def _geocode_via_nominatim(query_str: str) -> Optional[Tuple[float, float]]:
    try:
        q = urllib.parse.quote(query_str)
        url = f'https://nominatim.openstreetmap.org/search?format=json&q={q}&countrycodes=ar&limit=1'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'FerrariAsociadosCRM/2.0 (crm.ferrariasociados.com; contact@ferrariasociados.com)'
        })
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and isinstance(data, list) and len(data) > 0:
                first = data[0]
                lat = float(first['lat'])
                lng = float(first['lon'])
                if is_valid_and_coherent_coordinate(lat, lng):
                    return (lat, lng)
    except Exception:
        pass
    return None

def geocode_address(direccion: str, barrio: str = '', zona: str = '') -> Optional[Tuple[float, float]]:
    clean_dir = clean_argentine_address(direccion)
    clean_barrio = str(barrio or zona or '').strip()
    
    cache_key = f"{clean_dir}|{clean_barrio}".lower()
    with _CACHE_LOCK:
        if cache_key in _GEO_CACHE:
            return _GEO_CACHE[cache_key]

    coords = None

    if clean_dir and re.search(r'\d+', clean_dir):
        coords = _geocode_via_usig_caba(clean_dir)

    if not coords and clean_dir:
        query_full = f"{clean_dir}, {clean_barrio}, Buenos Aires, Argentina".strip(' ,')
        coords = _geocode_via_nominatim(query_full)

    if not coords and clean_dir:
        street_only = re.sub(r'\d+', '', clean_dir).strip(' ,')
        if len(street_only) >= 4:
            query_street = f"{street_only}, {clean_barrio}, Buenos Aires, Argentina".strip(' ,')
            coords = _geocode_via_nominatim(query_street)

    if not coords and clean_barrio:
        query_barrio = f"{clean_barrio}, Buenos Aires, Argentina"
        coords = _geocode_via_nominatim(query_barrio)

    if not coords and clean_barrio:
        b_key = normalize_text_key(clean_barrio)
        if b_key in BARRIO_CENTROIDS:
            coords = BARRIO_CENTROIDS[b_key]

    if coords:
        with _CACHE_LOCK:
            _GEO_CACHE[cache_key] = coords

    return coords

def extract_zone_from_text(text: str) -> Optional[str]:
    """Scans text (like title, description, or raw address) for recognized neighborhoods/zones."""
    if not text:
        return None
    norm = normalize_text_key(text)
    
    # Sort centroids by length descending to match compound names first (e.g. 'ingeniero maschwitz' before 'escobar')
    sorted_zones = sorted(BARRIO_CENTROIDS.keys(), key=lambda x: len(x), reverse=True)
    for zone in sorted_zones:
        # Match as whole word/phrase
        pattern = r'(?:\b|_)' + re.escape(zone) + r'(?:\b|_)'
        if re.search(pattern, norm):
            return zone
    return None

def resolve_property_coordinates(prop: Dict[str, Any], allow_network: bool = False) -> Dict[str, Any]:
    if not isinstance(prop, dict):
        return prop

    current_lat = prop.get('lat')
    current_lng = prop.get('lng')
    direccion = prop.get('direccion_mostrada') or prop.get('direccion') or ''
    barrio = prop.get('barrio') or ''
    zona = prop.get('zona') or ''
    titulo = prop.get('titulo') or ''

    if is_valid_and_coherent_coordinate(current_lat, current_lng, barrio=barrio, direccion=direccion):
        return prop

    # If barrio is empty, try extracting from title or address
    if not barrio or any(bad in str(barrio).lower() for bad in ['desde mercado libre', 'contraseña', 'seguridad']):
        detected_zone = extract_zone_from_text(titulo) or extract_zone_from_text(direccion)
        if detected_zone:
            barrio = detected_zone

    resolved = None

    # 1. Try in-memory geocache first
    clean_dir = clean_argentine_address(direccion)
    clean_barrio = str(barrio or zona or '').strip()
    cache_key = f"{clean_dir}|{clean_barrio}".lower()
    with _CACHE_LOCK:
        if cache_key in _GEO_CACHE:
            resolved = _GEO_CACHE[cache_key]

    # 2. Query external HTTP geocoding services ONLY if explicitly allowed
    if not resolved and allow_network:
        resolved = geocode_address(direccion=direccion, barrio=barrio, zona=zona)

    # 3. Fallback immediately to barrio / zone centroid (0 ms, completely offline and accurate)
    if not resolved and barrio:
        b_key = normalize_text_key(barrio)
        if b_key in BARRIO_CENTROIDS:
            resolved = BARRIO_CENTROIDS[b_key]

    if not resolved and zona:
        z_key = normalize_text_key(zona)
        if z_key in BARRIO_CENTROIDS:
            resolved = BARRIO_CENTROIDS[z_key]

    if not resolved and titulo:
        detected_zone = extract_zone_from_text(titulo)
        if detected_zone and detected_zone in BARRIO_CENTROIDS:
            resolved = BARRIO_CENTROIDS[detected_zone]

    if resolved:
        prop['lat'] = resolved[0]
        prop['lng'] = resolved[1]

    return prop
