"""
Database queries for property valuation (Tasador)
"""
import sqlite3
import math
import statistics
import random
import re
from database.db import get_db

def get_tasacion_zona(zona, tipo_propiedad, tipo_operacion='venta', metros=0, live_results=None, ambientes=None, min_m2_usd=0, metodo_metros='totales', metros_cubiertos=None, descartar_mal_cargados=False, rango_negativo=0.25, rango_positivo=0.25, filtro_estricto_barrio=False):
    """ Calculates market valuation based on scraped properties in the same zone. """
    conn = get_db()
    
    # Define PARTIDOS_MAP
    caba_list = [
        'palermo', 'recoleta', 'belgrano', 'nunez', 'saavedra', 'coghlan', 'villa urquiza',
        'villa pueyrredon', 'colegiales', 'chacarita', 'villa crespo', 'almagro', 'caballito',
        'flores', 'floresta', 'liniers', 'villa devoto', 'villa del parque', 'agronomia',
        'paternal', 'villa ortuzar', 'san telmo', 'puerto madero', 'monserrat', 'constitucion',
        'retiro', 'san nicolas', 'balvanera', 'boedo', 'parque patricios', 'barracas',
        'nueva pompeya', 'parque chacabuco', 'san cristobal', 'mataderos', 'villa luro',
        'versalles', 'villa real', 'monte castro', 'velez sarsfield', 'parque avellaneda',
        'villa lugano', 'villa riachuelo', 'villa soldati'
    ]
    
    san_martin_list = [
        'general san martin', 'san martin', 'villa ballester', 'san andres', 'billinghurst',
        'chilavert', 'jose leon suarez', 'malaver'
    ]

    PARTIDOS_MAP = {
        'caba': caba_list,
        'capital federal': caba_list,
        'vicente lopez': ['vicente lopez', 'olivos', 'florida', 'munro', 'la lucila', 'villa martelli', 'villa adelina', 'carapachay'],
        'san isidro': ['san isidro', 'martinez', 'acassuso', 'beccar', 'boulogne', 'villa adelina'],
        'san fernando': ['san fernando', 'victoria', 'virreyes'],
        'tigre': ['tigre', 'nordelta', 'benavidez', 'don torcuato', 'general pacheco', 'rincon de milberg', 'troncos del talar', 'dique lujan', 'villa la nata', 'el talar'],
        'escobar': ['escobar', 'belen de escobar', 'garin', 'maschwitz', 'ingeniero maschwitz', 'el cazador', 'loma verde', 'puertos', 'el canton', 'san matias', 'haras santa maria', 'el naudir'],
        'pilar': ['pilar', 'del viso', 'derqui', 'tortuguitas', 'fabiola', 'manzanares', 'zelaya', 'estancias', 'fatima', 'alberti'],
        'malvinas argentinas': ['malvinas argentinas', 'grand bourg', 'los polvorines', 'villa de mayo', 'tortuguitas', 'tierras altas', 'adolfo sourdeaux'],
        'jose c paz': ['jose c paz', 'del viso'],
        'san miguel': ['san miguel', 'bella vista', 'muñiz', 'campo de mayo'],
        'general san martin': san_martin_list,
        'san martin': san_martin_list,
        'tres de febrero': ['tres de febrero', 'caseros', 'ciudad jardin', 'martin coronado', 'villa bosch', 'saenz peña', 'santos lugares', 'loma hermosa', 'palomar'],
        'moron': ['moron', 'castelar', 'haedo', 'el palomar', 'villa sarmiento'],
        'ituzaingo': ['ituzaingo', 'villa udaondo'],
        'hurlingham': ['hurlingham', 'villa tesei', 'william morris'],
        'la matanza': ['la matanza', 'san justo', 'ramos mejia', 'ciudad evita', 'aldo bonzi', 'tapiales', 'villa luzuriaga', 'lomas del mirador', 'tablada', 'madero', 'gonzalez catan', 'isidro casanova', 'gregorio de laferrere', 'virrey del pino'],
        'merlo': ['merlo', 'libertad', 'san antonio de padua', 'mariano acosta', 'parque san martin'],
        'moreno': ['moreno', 'paso del rey', 'francisco alvarez'],
        'general rodriguez': ['general rodriguez'],
        'lujan': ['lujan', 'jauregui', 'open door']
    }
    
    def normalize_string(s):
        if not s:
            return ""
        s = s.lower()
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ü': 'u', 'ñ': 'n'
        }
        for original, replacement in replacements.items():
            s = s.replace(original, replacement)
        return " ".join(s.split()).strip()

    # Normalize property types (lowercase and strip 's' for better matching)
    norm_tipo = tipo_propiedad.lower().rstrip('s')
    
    # Calculate target metros
    metros_target = metros
    if metodo_metros == 'cubiertos' and metros_cubiertos:
        metros_target = metros_cubiertos
    elif metodo_metros == 'homogeneizados' and metros_cubiertos is not None:
        descubiertos = max(0.0, metros - metros_cubiertos)
        metros_target = metros_cubiertos + descubiertos * 0.2
        
    # Check if exact quoted search is requested
    is_exact = False
    raw_zona = (zona or "").strip()
    if raw_zona and re.search(r'["\'“”«»`]', raw_zona):
        is_exact = True
        
    clean_zona = re.sub(r'["\'“”«»`]', '', raw_zona).strip() if raw_zona else ""
    norm_zona = normalize_string(clean_zona)
    
    print(f"DEBUG: get_tasacion_zona - Zona: {zona} (Exacta: {is_exact}), Tipo: {norm_tipo}, Metros Target: {metros_target} (Metodo: {metodo_metros})")
    
    # Resolve the search zona against PARTIDOS_MAP only if NOT exact search
    subzones = [clean_zona] if clean_zona else []
    
    if not is_exact and clean_zona:
        matched = False
        # 1. Try exact match
        for k, v in PARTIDOS_MAP.items():
            norm_key = normalize_string(k)
            if norm_key == norm_zona:
                subzones = v
                matched = True
                break
                
        # 2. Try matching key inside normalized zone (e.g. "partido de tigre" contains "tigre")
        if not matched:
            for k, v in PARTIDOS_MAP.items():
                norm_key = normalize_string(k)
                if norm_key in norm_zona:
                    subzones = v
                    matched = True
                    break
                    
        # 3. Try matching normalized zone inside key (e.g. "tigre" inside "tigre")
        # To avoid matching short strings like "san" to "san isidro", require length > 3
        if not matched:
            for k, v in PARTIDOS_MAP.items():
                norm_key = normalize_string(k)
                if norm_zona in norm_key and len(norm_zona) > 3:
                    subzones = v
                    matched = True
                    break

    def process_comparable(r):
        """Returns (m2_val, discard_flag) for a comparable."""
        # Check keys
        m2_t = r.get('m2_total') if r.get('m2_total') is not None else r.get('m2')
        m2_c = r.get('m2_cubiertos') if r.get('m2_cubiertos') is not None else r.get('m2_cubierta')
        
        if m2_t is None: m2_t = m2_c
        if m2_c is None: m2_c = m2_t
        
        if m2_t is None or m2_t <= 0:
            return None, True
            
        # Check bad loaded data
        if descartar_mal_cargados and metodo_metros in ('cubiertos', 'homogeneizados'):
            if abs(m2_t - m2_c) < 0.01:
                return None, True
                
        # Calculate dynamic surface
        if metodo_metros == 'cubiertos':
            m2_val = m2_c
        elif metodo_metros == 'homogeneizados':
            desc = max(0.0, m2_t - m2_c)
            m2_val = m2_c + desc * 0.2
        else: # 'totales'
            m2_val = m2_t
            
        if m2_val <= 5:
            return None, True
            
        return m2_val, False

    def fetch_rows(m2_range=None):
        where_m2 = ""
        where_amb = ""
        
        # Build OR conditions for each subzone
        zone_conditions = []
        zone_params = []
        for sz in subzones:
            norm_sz = normalize_string(sz)
            if not norm_sz:
                continue
            zone_conditions.append("(LOWER(barrio) LIKE ? OR LOWER(direccion) LIKE ? OR LOWER(titulo) LIKE ?)")
            zone_params.extend([f"%{norm_sz}%", f"%{norm_sz}%", f"%{norm_sz}%"])
        
        if not zone_conditions:
            return []
            
        where_zone = "(" + " OR ".join(zone_conditions) + ")"
        
        params = []
        params.extend(zone_params)
        params.extend([f"%{norm_tipo}%", tipo_operacion])
        
        if m2_range:
            m2_col = "m2_cubiertos" if metodo_metros == "cubiertos" else "m2_total"
            where_m2 = f" AND {m2_col} BETWEEN ? AND ?"
            params.extend(m2_range)
            
        if ambientes:
            amb_list = ambientes if isinstance(ambientes, list) else [ambientes]
            conditions = []
            has_max = False
            for a in amb_list:
                try:
                    val = int(a)
                    if val >= 6:
                        has_max = True
                    else:
                        conditions.append(val)
                except ValueError:
                    pass
            
            clauses = []
            if conditions:
                placeholders = ",".join(["?"] * len(conditions))
                clauses.append(f"ambientes IN ({placeholders})")
                params.extend(conditions)
            if has_max:
                clauses.append("ambientes >= 6")
            
            if clauses:
                where_amb = " AND (" + " OR ".join(clauses) + ")"
                
        from datetime import datetime, timedelta
        threshold_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
        params.append(threshold_date)
        
        q = f"""
            SELECT id, precio, moneda, m2_total, m2_cubiertos, lat, lng, direccion, barrio, titulo, foto_url, url, fecha_captacion FROM propiedades 
            WHERE {where_zone}
            AND LOWER(tipo_propiedad) LIKE ?
            AND tipo_operacion = ?
            AND precio > 0
            {where_m2}
            {where_amb}
            ORDER BY CASE WHEN CAST(fecha_captacion AS TEXT) >= ? THEN 0 ELSE 1 END, fecha_captacion DESC
        """
        try:
            rows_found = conn.execute(q, params).fetchall()
            print(f"  DEBUG: fetch_rows ({'con m2' if m2_range else 'general'}) - Encontrados: {len(rows_found)}")
            return [dict(r) for r in rows_found]
        except Exception as e:
            print(f"  [TASADOR] Error en fetch_rows: {e}")
            return []

    # Try with dynamic % meters range first
    rows = []
    area_filtrada = False
    if metros_target > 0:
        rows = fetch_rows((metros_target * (1.0 - rango_negativo), metros_target * (1.0 + rango_positivo)))
        if rows: 
            area_filtrada = True
            print("  DEBUG: Filtrado por metros exitoso.")
        
    if not rows:
        rows = fetch_rows()
        
    # Deep fuzzy search (ONLY if NOT is_exact)
    if not rows and clean_zona and not is_exact:
        print("  DEBUG: Sin resultados por zona, intentando búsqueda difusa profunda...")
        stop_words = ['buenos', 'aires', 'argentina', 'ciudad', 'autonoma', 'autnoma', 'caba', 'calle', 'avenida', 'nacional', 'villa', 'san', 'santa', 'del', 'los', 'las', 'de', 'la', 'el', 'parque', 'barrio']
        
        # Collect words from all subzones
        words = []
        for sz in subzones:
            clean_sz = normalize_string(sz).replace(",", " ").replace(".", " ")
            for w in clean_sz.split():
                if len(w) > 3 and w not in stop_words and w not in words:
                    words.append(w)
        
        if words:
            fuzzy_conditions = []
            params = []
            for w in words:
                fuzzy_conditions.append("LOWER(titulo) LIKE ?")
                params.append(f"%{w}%")
                if 'ñ' in w:
                    fuzzy_conditions.append("LOWER(titulo) LIKE ?")
                    params.append(f"%{w.replace('ñ', 'n')}%")
                    fuzzy_conditions.append("LOWER(titulo) LIKE ?")
                    params.append(f"%{w.replace('ñ', 'z')}%") 

            fuzzy_where_m2 = ""
            fuzzy_where_amb = ""
            if metros_target > 0:
                m2_col = "m2_cubiertos" if metodo_metros == "cubiertos" else "m2_total"
                fuzzy_where_m2 = f" AND {m2_col} BETWEEN ? AND ?"
            fuzzy_amb_params = []
            if ambientes:
                amb_list = ambientes if isinstance(ambientes, list) else [ambientes]
                conditions = []
                has_max = False
                for a in amb_list:
                    try:
                        val = int(a)
                        if val >= 6:
                            has_max = True
                        else:
                            conditions.append(val)
                    except ValueError:
                        pass
                
                clauses = []
                if conditions:
                    placeholders = ",".join(["?"] * len(conditions))
                    clauses.append(f"ambientes IN ({placeholders})")
                    fuzzy_amb_params.extend(conditions)
                if has_max:
                    clauses.append("ambientes >= 6")
                
                if clauses:
                    fuzzy_where_amb = " AND (" + " OR ".join(clauses) + ")"
                    
            from datetime import datetime, timedelta
            threshold_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
            params.extend([f"%{norm_tipo}%", tipo_operacion])
            
            if metros_target > 0:
                params.extend([metros_target * (1.0 - rango_negativo), metros_target * (1.0 + rango_positivo)])
            if fuzzy_where_amb:
                params.extend(fuzzy_amb_params)
            params.append(threshold_date)
            
            q = f"""
                SELECT id, precio, moneda, m2_total, m2_cubiertos, lat, lng, direccion, barrio, titulo, foto_url, url, fecha_captacion FROM propiedades 
                WHERE ({" OR ".join(fuzzy_conditions)}) 
                AND LOWER(tipo_propiedad) LIKE ? 
                AND tipo_operacion = ? 
                AND precio > 0
                {fuzzy_where_m2}
                {fuzzy_where_amb}
                ORDER BY CASE WHEN fecha_captacion >= ? THEN 0 ELSE 1 END, fecha_captacion DESC
            """
            rows = [dict(r) for r in conn.execute(q, params).fetchall()]
            print(f"  DEBUG: Búsqueda difusa profunda encontrados: {len(rows)}")
            if rows: area_filtrada = False 
            
    conn.close()
    
    if not rows and not live_results:
        return None
        
    # Programmatic filtering of live results to match range
    if live_results and metros_target > 0:
        filtered_live = []
        for lr in live_results:
            m2_val, discard = process_comparable(lr)
            if not discard and (metros_target * (1.0 - rango_negativo) <= m2_val <= metros_target * (1.0 + rango_positivo)):
                filtered_live.append(lr)
        if filtered_live:
            live_results = filtered_live
            area_filtrada = True
            
    # Process properties through calculation pipeline
    valid_comparables = []
    seen_urls = set()
    source_list = []
    for r in (live_results or []) + (rows or []):
        url = r.get('url')
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        source_list.append(r)
    
    for r in source_list:
        # If is_exact, strictly verify that the exact zone phrase is in barrio, direccion, or titulo
        if is_exact and norm_zona:
            combined = normalize_string(f"{r.get('barrio') or ''} {r.get('direccion') or ''} {r.get('titulo') or ''}")
            if norm_zona not in combined:
                continue

        # If filtro_estricto_barrio is active:
        # Prevent homonym street names (e.g. "Av. Constitución 797" in Pilar) from matching the neighborhood "Constitución"
        if filtro_estricto_barrio and subzones:
            prop_barrio = normalize_string(r.get('barrio') or '')
            prop_dir = normalize_string(r.get('direccion') or '')
            prop_tit = normalize_string(r.get('titulo') or '')

            # Check if any subzone matches the property's explicit barrio
            matches_subzone_barrio = False
            for sz in subzones:
                norm_sz = normalize_string(sz)
                if norm_sz and (norm_sz in prop_barrio or prop_barrio in norm_sz):
                    matches_subzone_barrio = True
                    break

            # If the property has an explicit barrio that doesn't match any target subzone, discard it!
            if prop_barrio and not matches_subzone_barrio:
                continue

            # If prop_barrio is empty/missing, ensure the subzone keyword isn't just a street name with a number while located in another known town
            if not prop_barrio:
                other_known_zones = ['pilar', 'tigre', 'escobar', 'moron', 'san isidro', 'vicente lopez', 'san fernando', 'avellaneda', 'lanus', 'quilmes', 'la matanza', 'merlo', 'moreno', 'lujan']
                has_other_zone = any(oz in (prop_dir + ' ' + prop_tit) for oz in other_known_zones if oz not in [normalize_string(sz) for sz in subzones])
                if has_other_zone:
                    continue

        m2_val, discard = process_comparable(r)
        if discard:
            continue
            
        p = r['precio']
        if r.get('moneda') == 'ARS':
            p = p / 1200
            
        if min_m2_usd > 0 and (p / m2_val) < min_m2_usd:
            continue
            
        item = dict(r)
        item['calculated_m2'] = m2_val
        item['usd_price'] = p
        valid_comparables.append(item)
        
    if not valid_comparables:
        return None
        
    valores_referencia = []
    usa_m2 = False
    
    if metros_target > 0:
        usa_m2 = True
        for item in valid_comparables:
            valores_referencia.append(item['usd_price'] / item['calculated_m2'])
    else:
        for item in valid_comparables:
            valores_referencia.append(item['usd_price'])
            
    val_med = statistics.median(valores_referencia)
    try:
        q1 = statistics.quantiles(valores_referencia, n=4)[0]
        q3 = statistics.quantiles(valores_referencia, n=4)[2]
    except:
        q1, q3 = val_med * 0.85, val_med * 1.15

    comparables = []
    for item in valid_comparables[:20]:
        comparables.append({
            'titulo': item.get('titulo') or f"Propiedad en {item.get('barrio', 'la zona')}",
            'precio': item.get('precio'),
            'moneda': item.get('moneda', 'USD'),
            'm2': round(item['calculated_m2'], 1),
            'm2_total': item.get('m2_total'),
            'm2_cubiertos': item.get('m2_cubiertos'),
            'url': item.get('url'),
            'foto': item.get('foto') or item.get('foto_url') or (item.get('fotos', [None])[0] if item.get('fotos') else None),
            'barrio': item.get('barrio'),
            'direccion': item.get('direccion')
        })

    return {
        'bajo': round(q1, 0),
        'medio': round(val_med, 0),
        'alto': round(q3, 0),
        'm2_medio': round(val_med, 0) if usa_m2 else 0,
        'muestra': len(valid_comparables),
        'usa_m2': usa_m2,
        'area_filtrada': area_filtrada,
        'has_live': True if live_results else False,
        'comparables': comparables,
        'rango_negativo': int(rango_negativo * 100),
        'rango_positivo': int(rango_positivo * 100)
    }

def get_tasacion_geografica(lat, lng, radio_km, tipo_propiedad, tipo_operacion='venta', metros=0, ambientes=None, live_results=None, zona_name=None, min_m2_usd=0, metodo_metros='totales', metros_cubiertos=None, descartar_mal_cargados=False, rango_negativo=0.25, rango_positivo=0.25, solo_geolocalizadas=False, filtro_estricto_barrio=False):
    """Calculates valuation based on coordinates and radius using Haversine distance."""
    conn = get_db()
    norm_tipo = tipo_propiedad.lower().rstrip('s')
    
    def normalize_string(s):
        if not s:
            return ""
        s = s.lower()
        replacements = {
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
            'ü': 'u', 'ñ': 'n'
        }
        for original, replacement in replacements.items():
            s = s.replace(original, replacement)
        return " ".join(s.split()).strip()

    is_exact_geo = False
    raw_zona_name = (zona_name or "").strip()
    if raw_zona_name and re.search(r'["\'“”«»`]', raw_zona_name):
        is_exact_geo = True
    clean_zona_name = re.sub(r'["\'“”«»`]', '', raw_zona_name).strip() if raw_zona_name else ""
    norm_zona_name = normalize_string(clean_zona_name) if clean_zona_name else ""
    
    # Calculate target metros
    metros_target = metros
    if metodo_metros == 'cubiertos' and metros_cubiertos:
        metros_target = metros_cubiertos
    elif metodo_metros == 'homogeneizados' and metros_cubiertos is not None:
        descubiertos = max(0.0, metros - metros_cubiertos)
        metros_target = metros_cubiertos + descubiertos * 0.2
        
    # 1. Bounding Box Filter
    lat_delta = radio_km / 111.0
    lng_delta = radio_km / (111.0 * math.cos(math.radians(lat)))
    
    min_lat, max_lat = lat - lat_delta, lat + lat_delta
    min_lng, max_lng = lng - lng_delta, lng + lng_delta
    
    def process_comparable(r):
        """Returns (m2_val, discard_flag) for a comparable."""
        m2_t = r.get('m2_total') if r.get('m2_total') is not None else r.get('m2')
        m2_c = r.get('m2_cubiertos') if r.get('m2_cubiertos') is not None else r.get('m2_cubierta')
        
        if m2_t is None: m2_t = m2_c
        if m2_c is None: m2_c = m2_t
        
        if m2_t is None or m2_t <= 0:
            return None, True
            
        # Check bad loaded data
        if descartar_mal_cargados and metodo_metros in ('cubiertos', 'homogeneizados'):
            if abs(m2_t - m2_c) < 0.01:
                return None, True
                
        # Calculate dynamic surface
        if metodo_metros == 'cubiertos':
            m2_val = m2_c
        elif metodo_metros == 'homogeneizados':
            desc = max(0.0, m2_t - m2_c)
            m2_val = m2_c + desc * 0.2
        else: # 'totales'
            m2_val = m2_t
            
        if m2_val <= 5:
            return None, True
            
        return m2_val, False

    def fetch_geo_rows(m2_range=None):
        where_m2 = ""
        where_amb = ""
        params = [min_lat, max_lat, min_lng, max_lng, f"%{norm_tipo}%", tipo_operacion]
        
        if m2_range:
            m2_col = "m2_cubiertos" if metodo_metros == "cubiertos" else "m2_total"
            where_m2 = f" AND {m2_col} BETWEEN ? AND ?"
            params.extend(m2_range)
            
        if ambientes:
            amb_list = ambientes if isinstance(ambientes, list) else [ambientes]
            conditions = []
            has_max = False
            for a in amb_list:
                try:
                    val = int(a)
                    if val >= 6:
                        has_max = True
                    else:
                        conditions.append(val)
                except ValueError:
                    pass
            
            clauses = []
            if conditions:
                placeholders = ",".join(["?"] * len(conditions))
                clauses.append(f"ambientes IN ({placeholders})")
                params.extend(conditions)
            if has_max:
                clauses.append("ambientes >= 6")
            
            if clauses:
                where_amb = " AND (" + " OR ".join(clauses) + ")"
                
        from datetime import datetime, timedelta
        threshold_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
        params.append(threshold_date)
        
        q = f"""
            SELECT id, precio, moneda, m2_total, m2_cubiertos, lat, lng, direccion, barrio, titulo, foto_url, url, fecha_captacion FROM propiedades 
            WHERE lat BETWEEN ? AND ? 
            AND lng BETWEEN ? AND ?
            AND LOWER(tipo_propiedad) LIKE ?
            AND tipo_operacion = ?
            AND precio > 0
            {where_m2}
            {where_amb}
            ORDER BY CASE WHEN fecha_captacion >= ? THEN 0 ELSE 1 END, fecha_captacion DESC
        """
        return [dict(r) for r in conn.execute(q, params).fetchall()]

    # Try with dynamic % meters range first
    rows = []
    area_filtrada = False
    if metros_target > 0:
        rows = fetch_geo_rows((metros_target * (1.0 - rango_negativo), metros_target * (1.0 + rango_positivo)))
        if rows: area_filtrada = True
        
    if not rows:
        rows = fetch_geo_rows()
        
    conn.close()
    
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371  # Earth radius in km
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = math.sin(d_lat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    # Filter DB Rows by precise radius
    zona_lat_proxy, zona_lng_proxy = None, None
    if live_results:
        for lr in live_results:
            if lr.get('lat') and lr.get('lng'):
                zona_lat_proxy, zona_lng_proxy = float(lr['lat']), float(lr['lng'])
                break
                
    precise_rows = []
    for r in rows:
        if r['lat'] is not None and r['lng'] is not None:
            dist = haversine(lat, lng, r['lat'], r['lng'])
            if dist <= radio_km:
                precise_rows.append(r)
        elif not solo_geolocalizadas and norm_zona_name and r.get('barrio') and norm_zona_name in normalize_string(r.get('barrio', '')):
            base_dist = haversine(lat, lng, zona_lat_proxy or lat, zona_lng_proxy or lng)
            if base_dist <= radio_km:
                precise_rows.append(r)

    # Filter live results programmatically to match radius & range
    precise_live_results = []
    if live_results:
        for lr in live_results:
            m2_val, discard = process_comparable(lr)
            if discard:
                continue
                
            # Filter by radius if coordinates exist
            if lr.get('lat') and lr.get('lng'):
                dist = haversine(lat, lng, float(lr['lat']), float(lr['lng']))
                if dist > radio_km:
                    continue
            elif solo_geolocalizadas:
                continue
                    
            # Filter by range if target meters provided
            if metros_target > 0 and not (metros_target * (1.0 - rango_negativo) <= m2_val <= metros_target * (1.0 + rango_positivo)):
                continue
                
            precise_live_results.append(lr)
            
        if precise_live_results and metros_target > 0:
            area_filtrada = True

    # Process final list of items to calculate pricing and build comparables
    valid_comparables = []
    seen_urls = set()
    source_list = []
    for r in (precise_live_results or []) + (precise_rows or []):
        url = r.get('url')
        if url:
            if url in seen_urls:
                continue
            seen_urls.add(url)
        source_list.append(r)
    
    for r in source_list:
        if is_exact_geo and norm_zona_name:
            combined = normalize_string(f"{r.get('barrio') or ''} {r.get('direccion') or ''} {r.get('titulo') or ''}")
            if norm_zona_name not in combined:
                continue

        if filtro_estricto_barrio and norm_zona_name:
            prop_barrio = normalize_string(r.get('barrio') or '')
            if prop_barrio and norm_zona_name not in prop_barrio and prop_barrio not in norm_zona_name:
                continue

        m2_val, discard = process_comparable(r)
        if discard:
            continue
            
        p = r['precio']
        if r.get('moneda') == 'ARS':
            p = p / 1200
            
        if min_m2_usd > 0 and (p / m2_val) < min_m2_usd:
            continue
            
        item = dict(r)
        item['calculated_m2'] = m2_val
        item['usd_price'] = p
        valid_comparables.append(item)
        
    if not valid_comparables:
        return None
        
    valores_referencia = []
    usa_m2 = False
    
    if metros_target > 0:
        usa_m2 = True
        for item in valid_comparables:
            valores_referencia.append(item['usd_price'] / item['calculated_m2'])
    else:
        for item in valid_comparables:
            valores_referencia.append(item['usd_price'])
            
    val_med = statistics.median(valores_referencia)
    try:
        q1 = statistics.quantiles(valores_referencia, n=4)[0]
        q3 = statistics.quantiles(valores_referencia, n=4)[2]
    except:
        q1, q3 = val_med * 0.85, val_med * 1.15
        
    comparables = []
    for item in valid_comparables[:20]:
        comparables.append({
            'titulo': item.get('titulo') or f"Propiedad en {item.get('barrio', 'la zona')}",
            'precio': item.get('precio'),
            'moneda': item.get('moneda', 'USD'),
            'm2': round(item['calculated_m2'], 1),
            'm2_total': item.get('m2_total'),
            'm2_cubiertos': item.get('m2_cubiertos'),
            'url': item.get('url'),
            'foto': item.get('foto') or item.get('foto_url') or (item.get('fotos', [None])[0] if item.get('fotos') else None),
            'barrio': item.get('barrio'),
            'direccion': item.get('direccion')
        })
            
    return {
        'bajo': round(q1, 0),
        'medio': round(val_med, 0),
        'alto': round(q3, 0),
        'm2_medio': round(val_med, 0) if usa_m2 else 0,
        'muestra': len(valid_comparables),
        'usa_m2': usa_m2,
        'area_filtrada': area_filtrada,
        'has_live': True if precise_live_results else False,
        'comparables': comparables,
        'rango_negativo': int(rango_negativo * 100),
        'rango_positivo': int(rango_positivo * 100)
    }
