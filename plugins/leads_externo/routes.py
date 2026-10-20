"""
Plugin Leads Externo - Public Portal & White Label Search Engine
Decoupled, High Performance, 100% Original Tasador Express Backend Logic, Accent Normalization, Multi-Field Zone Matching & General San Martín GBA Mapping.
"""
import os
import json
import re
import shutil
import sqlite3
from datetime import datetime
from flask import Blueprint, request, render_template, jsonify, redirect, url_for, g
from database import db
from lib.limiter import limiter

leads_externo_bp = Blueprint('leads_externo', __name__, template_folder='templates', static_folder='static')

SUPERADMIN_PHONE = os.environ.get("SUPERADMIN_PHONE", "+5491161114414")  # Número del agente admin
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'propiedades')

os.makedirs(UPLOADS_DIR, exist_ok=True)

# --- ACCENT & ZONE NORMALIZATION HELPER ---

def generar_variantes_barrio(texto):
    """Devuelve variantes con y sin tildes para búsquedas SQL robustas (ej: San Martin vs General San Martín)."""
    if not texto:
        return []
    base = texto.strip().lower()
    
    s_sin = base.replace('á','a').replace('é','e').replace('í','i').replace('ó','o').replace('ú','u')
    s_con = base
    replacements = [('a','á'), ('e','é'), ('i','í'), ('o','ó'), ('u','ú')]
    for k, v in replacements:
        s_con = s_con.replace(k, v)
        
    variantes = set([base, s_sin, s_con])
    
    if 'san martin' in s_sin:
        variantes.update([
            'san martín', 'san martin', 
            'general san martín', 'general san martin', 
            'san martín centro', 'san martin centro',
            'villa lynch', 'san andrés', 'san andres', 'villa ballester'
        ])
    if 'constitucion' in s_sin:
        variantes.update(['constitución', 'constitucion'])
    if 'almagro' in s_sin:
        variantes.update(['almagro'])
        
    return list(variantes)

# --- LIVE PROBE HELPER ---

def probe_and_save_zone(zona, tipo_propiedad='departamento', ambientes=None, operacion='venta'):
    """Ejecuta un scrapeo en tiempo real (LiveProbe) probando fuentes de portales."""
    if not zona or len(str(zona).strip()) < 3:
        zona = "CABA"
    try:
        from lib.scraper_client import ScraperClient
        tipo_target = tipo_propiedad if (tipo_propiedad and tipo_propiedad.strip()) else 'departamento'
        print(f"[Leads_Externo] Delegando búsqueda para '{zona}' ({operacion}, {tipo_target}) al motor de scraping remoto...")
        ScraperClient.trigger_async_search({
            'zona': zona,
            'tipo_propiedad': tipo_target,
            'tipo_operacion': operacion
        }, max_pages=2)
        return 0
    except Exception as e:
        print(f"[Leads_Externo] Excepción en búsqueda remota para '{zona}': {e}")
        return 0

# --- DETERMINISTIC ZERO-AI LOGIC FOR HEAT SCORE, RED FLAGS & CHECKLIST ---

def calcular_heat_score(prop):
    """Calcula un puntaje de demanda/calidez (0-100) basado en reglas deterministas."""
    score = 60
    
    fecha_cap = prop.get('fecha_captacion') or prop.get('fecha_publicacion')
    if fecha_cap:
        try:
            if isinstance(fecha_cap, str):
                dt = datetime.strptime(fecha_cap[:10], '%Y-%m-%d')
            else:
                dt = fecha_cap
            dias = (datetime.now() - dt).days
            if dias <= 7: score += 30
            elif dias <= 30: score += 15
            elif dias > 120: score -= 20
        except Exception:
            pass
            
    precio = prop.get('precio') or 0
    m2 = prop.get('m2_cubiertos') or prop.get('m2_total') or 1
    if precio > 0 and m2 > 0:
        val_m2 = precio / m2
        if val_m2 < 1850:
            score += 15
            
    score = max(10, min(99, score))
    
    if score >= 75:
        badge = {"label": "Oportunidad 🔥", "class": "bg-danger text-white"}
    elif score >= 50:
        badge = {"label": "Demanda Normal 🏠", "class": "bg-primary text-white"}
    else:
        badge = {"label": "Estancado ❄️", "class": "bg-secondary text-white"}
        
    return score, badge

def generar_red_flags(prop):
    """Genera advertencias técnicas (Red Flags) con reglas simples de patrones y números."""
    flags = []
    desc = str(prop.get('descripcion') or '').lower()
    titulo = str(prop.get('titulo') or '').lower()
    
    m2_tot = prop.get('m2_total') or 0
    m2_cub = prop.get('m2_cubiertos') or 0
    if m2_tot > 0 and m2_cub > 0 and (m2_cub / m2_tot) < 0.5:
        flags.append("Superficie mayormente descubierta/balcón (más del 50% descubierto)")
        
    if any(k in desc or k in titulo for k in ['ex oficina', 'apto profesional', 'local comercial', 'reconvertido']):
        flags.append("Posible origen o reconversión comercial/oficina")
        
    if any(k in desc for k in ['refaccionar', 'reciclar', 'deterioro', 'detalles de pintura']):
        flags.append("Requiere inversión en pintura o refacciones")
        
    expensas = prop.get('expensas') or 0
    if expensas > 50000:
        flags.append(f"Expensas elevadas registradas (${expensas:,} ARS)")
        
    if not flags:
        flags.append("Sin advertencias graves detectadas a simple vista")
        
    return flags

def generar_checklist(prop):
    """Devuelve checklist dinámico según antigüedad y tipo de inmueble."""
    tipo = str(prop.get('tipo_propiedad') or 'departamento').lower()
    antiguedad = prop.get('antiguedad') or 0
    
    checklist = [
        "Verificar presión de agua en baños y cocina.",
        "Comprobar funcionamiento de llaves térmicas y disyuntor eléctrico.",
        "Consultar estado de expensas y si hay expensas extraordinarias aprobadas."
    ]
    
    if 'casa' in tipo or 'ph' in tipo:
        checklist.append("Inspeccionar techos, membranas y posibles filtraciones en terraza.")
        checklist.append("Verificar estado de cañerías de gas y presencia de medidor activo.")
    elif antiguedad > 20 or 'antiguo' in str(prop.get('descripcion') or '').lower():
        checklist.append("Preguntar por renovación reciente de cañerías de agua y gas en el edificio.")
        checklist.append("Revisar humedad en cimientos y esquinas de techos.")
    else:
        checklist.append("Verificar luminosidad en distintos horarios del día.")
        
    return checklist

def generar_descripcion_automatica(prop):
    """Genera una descripción detallada y profesional basada en los metadatos del inmueble."""
    tipo = str(prop.get('tipo_propiedad') or 'Propiedad').capitalize()
    op = str(prop.get('tipo_operacion') or 'Venta').capitalize()
    barrio = str(prop.get('barrio') or 'excelente ubicación').title()
    m2_tot = prop.get('m2_total')
    m2_cub = prop.get('m2_cubiertos')
    amb = prop.get('ambientes')
    dorm = prop.get('dormitorios')
    
    frases = [f"Excelente oportunidad de {tipo} en {op} situado en {barrio}."]
    if amb:
        frases.append(f"Dispone de {amb} ambiente{'s' if amb > 1 else ''} muy amplios y luminosos con excelente ventilación natural.")
    if dorm:
        frases.append(f"Cuenta con {dorm} dormitorio{'s' if dorm > 1 else ''} confortables.")
    if m2_tot or m2_cub:
        m2_info = f"Superficie total de {m2_tot} m²" if m2_tot else ""
        if m2_cub and m2_cub != m2_tot:
            m2_info += f" ({m2_cub} m² cubiertos)"
        frases.append(f"{m2_info}.")
    if prop.get('cocheras'):
        frases.append(f"Incluye {prop['cocheras']} espacio(s) de cochera.")
        
    frases.append("Unidad ideal para vivienda familiar o inversión inmobiliaria en un entorno residencial seguro y de alta demanda con conectividad estratégica.")
    return " ".join(frases)

def limpiar_pie_descripcion(text):
    if not text or len(text) < 40:
        return text
        
    footer_triggers = [
        r'[\s_\-\*#=]*corredor\s+responsable',
        r'[\s_\-\*#=]*martillero\s+responsable',
        r'[\s_\-\*#=]*martillero\s+y\s+corredor',
        r'[\s_\-\*#=]*todas\s+las\s+propiedades\s+que\s+figuran',
        r'[\s_\-\*#=]*cada\s+oficina\s+es\s+de\s+propiedad',
        r'[\s_\-\*#=]*en\s+cumplimiento\s+de\s+las\s+leyes',
        r'[\s_\-\*#=]*la\s+intermediaci[oó]n\s+y\s+la\s+conclusi[oó]n',
        r'[\s_\-\*#=]*cmcpsi\b',
        r'[\s_\-\*#=]*cucicba\b',
        r'[\s_\-\*#=]*cmzc\b',
        r'[\s_\-\*#=]*asesoramiento\s+experto\s+para\s+tu\s+mejor\s+decisi[oó]n'
    ]
    
    combined_regex = re.compile('|'.join(footer_triggers), re.IGNORECASE)
    match = combined_regex.search(text)
    if match and match.start() >= 40:
        cleaned = text[:match.start()].strip()
        cleaned = re.sub(r'[\s_\-\*#=]+$', '', cleaned)
        return cleaned
        
    return text

def obtener_branding_portal():
    """
    Returns (logo_url, agency_name) for the public /portal:
    1. Checks if there is an office assigned as portal (es_portal_clientes = 1).
    2. Checks global configuracion (company_logo_path and nombre_inmobiliaria).
    3. Falls back to Potenzia CRM transparent logo and generic network name.
    """
    default_logo = '/static/img/potenzia_logo_transparent.png'
    default_name = 'Potenzia Real Estate'
    
    try:
        conn = db.get_db()
        # 1. Office with es_portal_clientes = 1
        ofi = conn.execute("""
            SELECT nombre, logo_url FROM oficinas 
            WHERE es_portal_clientes = 1 AND activa = 1 
            ORDER BY id ASC LIMIT 1
        """).fetchone()
        
        if ofi:
            ofi_logo = (ofi['logo_url'] or '').strip()
            ofi_nombre = (ofi['nombre'] or '').strip()
            if ofi_logo and ofi_logo not in ['/static/img/potenzia_logo.png', '/static/img/potenzia_logo_sm.png', '/static/img/logo.png', '/static/img/potenzia_logo_transparent.png']:
                return ofi_logo, ofi_nombre or default_name
            elif ofi_nombre:
                return default_logo, ofi_nombre

        # 2. Global configuracion
        cfg_logo_row = conn.execute("SELECT valor FROM configuracion WHERE clave = 'company_logo_path'").fetchone()
        cfg_nombre_row = conn.execute("SELECT valor FROM configuracion WHERE clave = 'nombre_inmobiliaria'").fetchone()
        
        cfg_logo = (cfg_logo_row['valor'] or '').strip() if cfg_logo_row else ''
        cfg_nombre = (cfg_nombre_row['valor'] or '').strip() if cfg_nombre_row else ''
        
        if cfg_logo and cfg_logo not in ['/static/img/potenzia_logo.png', '/static/img/potenzia_logo_sm.png', '/static/img/logo.png', '/static/img/potenzia_logo_transparent.png']:
            return cfg_logo, cfg_nombre or default_name
        elif cfg_nombre:
            return default_logo, cfg_nombre
            
    except Exception as e:
        print(f"[obtener_branding_portal] Error: {e}")
        
    return default_logo, default_name

def obtener_logo_empresa():
    logo, _ = obtener_branding_portal()
    return logo

def sanitizar_marca_blanca(prop):
    """Limpia referencias explícitas a portales externos y garantiza atributos limpios para HTML/JS."""
    if isinstance(prop, sqlite3.Row):
        p = dict(prop)
    elif isinstance(prop, dict):
        p = dict(prop)
    else:
        try:
            p = dict(prop)
        except Exception:
            p = {}
        
    p['portal_display'] = 'Red Exclusiva'
    
    titulo = str(p.get('titulo') or 'Propiedad Exclusiva')
    titulo = re.sub(r'(?i)\b(zonaprop|argenprop|mercadolibre|meli|remax|oppel|tokko)\b', '', titulo).strip()
    titulo = re.sub(r'\s+', ' ', titulo).strip() or 'Propiedad Exclusiva'
    
    if len(titulo) > 90:
        # Try cutting at first period
        if '.' in titulo[:90]:
            titulo = titulo[:titulo.find('.') + 1].strip()
        else:
            titulo = titulo[:85].rsplit(' ', 1)[0] + '...'
            
    p['titulo'] = titulo
    
    desc_clean = str(p.get('descripcion') or '').strip()
    if not desc_clean or desc_clean.lower() in ['none', 'null', 'ver detalles en link...', 'ver detalles en link'] or len(desc_clean) < 15:
        desc_clean = generar_descripcion_automatica(p)
    else:
        desc_clean = limpiar_pie_descripcion(desc_clean)
        desc_clean = re.sub(r'(?i)\b(zonaprop|argenprop|mercadolibre|meli|remax|oppel|tokko)\b', '', desc_clean)
    p['descripcion'] = re.sub(r'\s+', ' ', desc_clean).strip()
    
    # Clean tipo_propiedad string (remove brackets like {departamento})
    tipo_p = str(p.get('tipo_propiedad') or 'Departamento')
    p['tipo_propiedad'] = re.sub(r'[\{\}\[\]]', '', tipo_p).strip().capitalize() or 'Departamento'
    
    # Infer missing environments/bedrooms from title & description
    full_text = (str(p.get('titulo') or '') + ' ' + str(p.get('descripcion') or '')).lower()
    
    try:
        amb_val = int(p.get('ambientes') or 0)
    except Exception:
        amb_val = 0
        
    try:
        dorm_val = int(p.get('dormitorios') or 0)
    except Exception:
        dorm_val = 0
        
    if amb_val <= 1:
        m_title_amb = re.search(r'(\d+)\s*(?:ambientes|amb\b)', full_text)
        if m_title_amb:
            amb_val = int(m_title_amb.group(1))
            p['ambientes'] = amb_val
            
    if dorm_val == 0:
        m_title_dorm = re.search(r'(\d+)\s*(?:dormitorios|dorm\b|habitaciones)', full_text)
        if m_title_dorm:
            dorm_val = int(m_title_dorm.group(1))
            p['dormitorios'] = dorm_val
        elif amb_val > 1:
            p['dormitorios'] = amb_val - 1

    # Clean and infer m2 surface area
    try: m2_tot = float(p.get('m2_total') or 0)
    except: m2_tot = 0.0
    try: m2_cub = float(p.get('m2_cubiertos') or 0)
    except: m2_cub = 0.0
    
    if m2_tot <= 0 and m2_cub > 0:
        m2_tot = m2_cub
    elif m2_cub <= 0 and m2_tot > 0:
        m2_cub = m2_tot
        
    if m2_tot <= 0:
        m_match = re.search(r'(\d+)\s*(?:m²|m2|mts2|mts\u00b2|metros\s*cuadrados)', full_text)
        if m_match:
            try:
                val = float(m_match.group(1))
                if 15 <= val <= 2000:
                    m2_tot = val
                    m2_cub = val
            except Exception: pass

    if m2_tot <= 0:
        if 'casa' in p['tipo_propiedad'].lower():
            m2_tot = max(100.0, amb_val * 35.0)
        elif 'lote' in p['tipo_propiedad'].lower() or 'terreno' in p['tipo_propiedad'].lower():
            m2_tot = 500.0
        else:
            if amb_val == 1: m2_tot = 32.0
            elif amb_val == 2: m2_tot = 48.0
            elif amb_val == 3: m2_tot = 68.0
            elif amb_val == 4: m2_tot = 88.0
            else: m2_tot = max(30.0, amb_val * 22.0)
        m2_cub = m2_tot

    p['m2_total'] = int(round(m2_tot))
    p['m2_cubiertos'] = int(round(m2_cub))

    fotos = []
    if p.get('fotos_json'):
        try:
            if isinstance(p['fotos_json'], list):
                fotos = p['fotos_json']
            elif isinstance(p['fotos_json'], str):
                fotos = json.loads(p['fotos_json'])
        except Exception:
            pass
            
    if not fotos and p.get('foto_url'):
        fotos = [p['foto_url']]
        
    # Sanitizar fotos (remover QR AFIP, logos y promocionar portada limpia)
    from lib.photo_sanitizer import sanitize_property_photos
    clean_cover, clean_fotos, _ = sanitize_property_photos(p.get('foto_url'), fotos, check_cover_content=False)
    p['lista_fotos'] = clean_fotos
    p['foto_url'] = clean_cover or (clean_fotos[0] if clean_fotos else '')
    
    is_tokko = bool(p.get('es_propio')) or bool(p.get('tokko_id')) or str(p.get('portal', '')).lower() in ('tokko', 'tokko_broker', 'propio', 'ferrari', 'directo') or bool(p.get('busqueda_id'))
    p['es_propio'] = is_tokko

    score, badge = calcular_heat_score(p)
    if is_tokko:
        badge = {"label": "Exclusiva 🏆", "class": "bg-success text-white fw-bold"}
        score = 99

    p['heat_score'] = score
    p['heat_badge'] = badge
    p['red_flags'] = generar_red_flags(p)
    p['checklist'] = generar_checklist(p)
    
    return p

# --- ROUTES ---

@leads_externo_bp.route('/portal')
def portal_home():
    """Landing Page Principal del Portal Público con Menú Lateral."""
    conn = db.get_db()
    barrios_rows = conn.execute("""
        SELECT DISTINCT barrio FROM propiedades 
        WHERE barrio IS NOT NULL AND barrio != '' 
        ORDER BY barrio ASC LIMIT 80
    """).fetchall()
    barrios = [r['barrio'] for r in barrios_rows if r['barrio']]
    
    tipos_propiedad = ['Departamento', 'PH', 'Casa', 'Terreno / Lote', 'Local / Oficina']
    
    # 1. Propiedades Exclusivas Tokko (si existen)
    props = []
    try:
        tokko_rows = conn.execute("""
            SELECT ('tokko_' || tokko_id) as id, tokko_id, titulo, tipo_operacion, tipo_propiedad, precio, moneda,
                   superficie_total as m2_total, superficie_cubierta as m2_cubiertos,
                   ambientes, dormitorios, banos, cocheras, barrio, localidad, zona,
                   lat, lon as lng, url_ficha as url, foto_principal as foto_url,
                   fotos_json, descripcion, 'tokko' as portal, 1 as es_propio
            FROM tokko_propiedades 
            WHERE activa = 1
            ORDER BY id DESC LIMIT 6
        """).fetchall()
        props = [sanitizar_marca_blanca(dict(p)) for p in tokko_rows]
    except Exception as e:
        print(f"[Portal Home] Error cargando Tokko: {e}")

    # 2. Propiedades de Portales con Foto para completar la selección destacada
    needed = 12 - len(props)
    if needed > 0:
        try:
            props_rows = conn.execute("""
                SELECT * FROM propiedades 
                WHERE (foto_url IS NOT NULL AND foto_url != '' OR fotos_json IS NOT NULL)
                ORDER BY id DESC LIMIT ?
            """, (needed,)).fetchall()
            props.extend([sanitizar_marca_blanca(dict(p)) for p in props_rows])
        except Exception as e:
            print(f"[Portal Home] Error cargando propiedades generales: {e}")
            
    company_logo, portal_agency_name = obtener_branding_portal()
    
    return render_template('portal.html', barrios=barrios, tipos_propiedad=tipos_propiedad, propiedades=props, company_logo=company_logo, portal_agency_name=portal_agency_name)

def enriquecer_ficha_al_vuelo(p):
    """Extrae en tiempo real la galería completa de fotos, características y descripción real si faltan datos."""
    if not p or not isinstance(p, dict):
        return p
        
    fotos = p.get('lista_fotos') or []
    url = p.get('url')
    desc = str(p.get('descripcion') or '')
    
    needs_photos = len(fotos) <= 1
    needs_desc = (not desc or len(desc) < 250 or 'entorno residencial destacado' in desc.lower())
    needs_features = (not p.get('m2_total') or not p.get('dormitorios') or (p.get('ambientes') or 0) <= 1)
    if (needs_photos or needs_desc or needs_features) and url and len(url) > 10:
        try:
            from lib.scraper_client import ScraperClient
            res_detail = ScraperClient.test_inspect_property(url)
            if res_detail and res_detail.get('success') and res_detail.get('data'):
                d = res_detail['data']
                if needs_desc and d.get('descripcion'):
                    p['descripcion'] = d['descripcion']
                if needs_photos and d.get('fotos'):
                    p['fotos_json'] = json.dumps(d['fotos'])
                    p['lista_fotos'] = d['fotos']
                    p['foto_url'] = d['fotos'][0]
                if d.get('m2_total'): p['m2_total'] = d['m2_total']
                if d.get('m2_cubiertos'): p['m2_cubiertos'] = d['m2_cubiertos']
                if d.get('ambientes'): p['ambientes'] = d['ambientes']
                if d.get('dormitorios'): p['dormitorios'] = d['dormitorios']
                if d.get('banos'): p['banos'] = d['banos']
                if d.get('cocheras'): p['cocheras'] = d['cocheras']
                if d.get('antiguedad'): p['antiguedad'] = d['antiguedad']
                if d.get('orientacion'): p['orientacion'] = d['orientacion']

                if not p.get('m2_cubiertos') and p.get('m2_total'):
                    p['m2_cubiertos'] = p['m2_total']
                elif not p.get('m2_total') and p.get('m2_cubiertos'):
                    p['m2_total'] = p['m2_cubiertos']

                # Save to database
                try:
                    conn = db.get_db()
                    conn.execute("""
                        UPDATE propiedades 
                        SET descripcion = COALESCE(?, descripcion),
                            fotos_json = COALESCE(?, fotos_json),
                            foto_url = COALESCE(?, foto_url),
                            ambientes = COALESCE(?, ambientes),
                            dormitorios = COALESCE(?, dormitorios),
                            banos = COALESCE(?, banos),
                            m2_total = COALESCE(?, m2_total),
                            m2_cubiertos = COALESCE(?, m2_cubiertos),
                            cocheras = COALESCE(?, cocheras),
                            antiguedad = COALESCE(?, antiguedad),
                            orientacion = COALESCE(?, orientacion)
                        WHERE id = ?
                    """, (
                        p.get('descripcion'), p.get('fotos_json'), p.get('foto_url'),
                        p.get('ambientes'), p.get('dormitorios'), p.get('banos'),
                        p.get('m2_total'), p.get('m2_cubiertos'), p.get('cocheras'),
                        p.get('antiguedad'), p.get('orientacion'), p['id']
                    ))
                except Exception as e:
                    print(f"[Routes] Error actualizando DB en enriquecimiento al vuelo: {e}")
        except Exception as e:
            print(f"[Routes] Error en enriquecer_ficha_al_vuelo: {e}")
            
    return p

@leads_externo_bp.route('/portal/propiedad/<path:prop_id>')
def detalle_propiedad(prop_id):
    """Ficha Completa de Detalle Estilo Zonaprop (Marca Blanca)."""
    conn = db.get_db()
    str_id = str(prop_id).replace('tokko_', '').strip()
    
    # 1. Buscar primero en tokko_propiedades
    p_tokko = conn.execute("""
        SELECT ('tokko_' || tokko_id) as id, tokko_id, titulo, tipo_operacion, tipo_propiedad, precio, moneda,
               superficie_total as m2_total, superficie_cubierta as m2_cubiertos,
               ambientes, dormitorios, banos, cocheras, barrio, localidad, zona,
               lat, lon as lng, url_ficha as url, foto_principal as foto_url,
               fotos_json, descripcion, 'tokko' as portal, 1 as es_propio
        FROM tokko_propiedades 
        WHERE tokko_id = ? OR CAST(id AS TEXT) = ?
    """, (str_id, str_id)).fetchone()
    
    company_logo, portal_agency_name = obtener_branding_portal()
    if p_tokko:
        prop = sanitizar_marca_blanca(dict(p_tokko))
        return render_template('portal_detalle.html', p=prop, prop=prop, company_logo=company_logo, portal_agency_name=portal_agency_name)
        
    # 2. Buscar en propiedades generales por ID exacto (si es numérico)
    p_row = None
    if str_id.isdigit():
        p_row = conn.execute("SELECT * FROM propiedades WHERE id = ?", (int(str_id),)).fetchone()
    
    if not p_row:
        p_row = conn.execute("SELECT * FROM propiedades WHERE CAST(id AS TEXT) = ? OR url = ?", (str_id, str_id)).fetchone()
        
    if not p_row:
        return redirect(url_for('leads_externo.portal_home'))
        
    prop_dict = dict(p_row)
    prop = sanitizar_marca_blanca(prop_dict)
    prop = enriquecer_ficha_al_vuelo(prop)
    return render_template('portal_detalle.html', p=prop, prop=prop, company_logo=company_logo, portal_agency_name=portal_agency_name)

@leads_externo_bp.route('/portal/api/buscar')
@limiter.limit("60 per minute")
def api_buscar():
    """
    API de Búsqueda Profesional Avanzada con Búsqueda Multi-Campo Insensible a Acentos.
    """
    barrio = request.args.get('barrio', '').strip()
    tipo_propiedad = request.args.get('tipo_propiedad', 'departamento').strip()
    ambientes = request.args.get('ambientes', '').strip()
    dormitorios = request.args.get('dormitorios', '').strip()
    tipo_operacion = request.args.get('tipo_operacion', 'venta').strip()
    min_precio = request.args.get('min_precio', type=float)
    max_precio = request.args.get('max_precio', type=float)
    min_m2 = request.args.get('min_m2', type=float)
    ordenar = request.args.get('ordenar', 'recientes')
    
    amenities_param = request.args.get('amenities', '')
    amenities_list = [a.strip().lower() for a in amenities_param.split(',') if a.strip()]
    
    page = request.args.get('page', 1, type=int)
    limit = 12
    offset = (page - 1) * limit
    
    conn = db.get_db()

    # 1. Búsqueda en Stock Nativo Tokko Broker (tokko_propiedades)
    def build_tokko_query():
        q_tok = """
            SELECT ('tokko_' || tokko_id) as id, tokko_id, titulo, tipo_operacion, tipo_propiedad, precio, moneda,
                   superficie_total as m2_total, superficie_cubierta as m2_cubiertos,
                   ambientes, dormitorios, banos, cocheras, barrio, localidad, zona,
                   lat, lon as lng, url_ficha as url, foto_principal as foto_url,
                   fotos_json, descripcion, 'tokko' as portal, 1 as es_propio
            FROM tokko_propiedades
            WHERE activa = 1
        """
        p_tok = []
        
        if tipo_operacion:
            q_tok += " AND LOWER(tipo_operacion) = ?"
            p_tok.append(tipo_operacion.lower())
            
        if tipo_propiedad:
            norm_tipo = tipo_propiedad.lower()
            if 'terreno' in norm_tipo or 'lote' in norm_tipo:
                q_tok += " AND (LOWER(tipo_propiedad) LIKE '%terreno%' OR LOWER(tipo_propiedad) LIKE '%lote%')"
            elif 'ph' in norm_tipo:
                q_tok += " AND LOWER(tipo_propiedad) LIKE '%ph%'"
            elif 'casa' in norm_tipo:
                q_tok += " AND LOWER(tipo_propiedad) LIKE '%casa%'"
            elif 'local' in norm_tipo or 'oficina' in norm_tipo:
                q_tok += " AND (LOWER(tipo_propiedad) LIKE '%local%' OR LOWER(tipo_propiedad) LIKE '%oficina%')"
            else:
                q_tok += " AND LOWER(tipo_propiedad) LIKE '%departamento%'"

        if barrio:
            variantes = generar_variantes_barrio(barrio)
            conds = []
            for v in variantes:
                conds.append("(LOWER(barrio) LIKE ? OR LOWER(localidad) LIKE ? OR LOWER(zona) LIKE ? OR LOWER(titulo) LIKE ?)")
                p_tok.extend([f"%{v}%"] * 4)
            if conds:
                q_tok += " AND (" + " OR ".join(conds) + ")"
                
        if ambientes:
            try:
                amb_val = int(ambientes)
                if amb_val >= 5:
                    q_tok += " AND ambientes >= 5"
                else:
                    q_tok += " AND ambientes = ?"
                    p_tok.append(amb_val)
            except ValueError:
                pass

        if dormitorios:
            try:
                dorm_val = int(dormitorios)
                if dorm_val >= 4:
                    q_tok += " AND dormitorios >= 4"
                else:
                    q_tok += " AND dormitorios = ?"
                    p_tok.append(dorm_val)
            except ValueError:
                pass

        if min_precio:
            q_tok += " AND precio >= ?"
            p_tok.append(min_precio)
        if max_precio:
            q_tok += " AND precio <= ?"
            p_tok.append(max_precio)
            
        if min_m2:
            q_tok += " AND (superficie_cubierta >= ? OR superficie_total >= ?)"
            p_tok.extend([min_m2, min_m2])

        if 'balcon' in amenities_list or 'balcón' in amenities_list:
            q_tok += " AND (COALESCE(LOWER(descripcion),'') LIKE '%balcon%' OR COALESCE(LOWER(descripcion),'') LIKE '%balcón%' OR COALESCE(LOWER(titulo),'') LIKE '%balcon%')"
        if 'pileta' in amenities_list or 'piscina' in amenities_list:
            q_tok += " AND (COALESCE(LOWER(descripcion),'') LIKE '%pileta%' OR COALESCE(LOWER(descripcion),'') LIKE '%piscina%' OR COALESCE(LOWER(titulo),'') LIKE '%pileta%')"
        if 'parrilla' in amenities_list:
            q_tok += " AND (COALESCE(LOWER(descripcion),'') LIKE '%parrilla%' OR COALESCE(LOWER(descripcion),'') LIKE '%quincho%' OR COALESCE(LOWER(titulo),'') LIKE '%parrilla%')"
        if 'terraza' in amenities_list:
            q_tok += " AND (COALESCE(LOWER(descripcion),'') LIKE '%terraza%' OR COALESCE(LOWER(descripcion),'') LIKE '%solarium%' OR COALESCE(LOWER(titulo),'') LIKE '%terraza%')"
        if 'cochera' in amenities_list:
            q_tok += " AND (cocheras > 0 OR COALESCE(LOWER(descripcion),'') LIKE '%cochera%' OR COALESCE(LOWER(descripcion),'') LIKE '%garage%')"
        if 'jardin' in amenities_list or 'jardín' in amenities_list:
            q_tok += " AND (COALESCE(LOWER(descripcion),'') LIKE '%jardin%' OR COALESCE(LOWER(descripcion),'') LIKE '%jardín%' OR COALESCE(LOWER(descripcion),'') LIKE '%patio%')"

        q_tok += " ORDER BY id DESC"
        return q_tok, p_tok

    # 2. Búsqueda en Propiedades Escrapeadas de Portales
    def build_query():
        query = "SELECT * FROM propiedades WHERE 1=1"
        params = []
        
        # Búsqueda insensibles a tildes/acentos en barrio, dirección o título
        if barrio:
            variantes = generar_variantes_barrio(barrio)
            conds = []
            for v in variantes:
                conds.append("(LOWER(barrio) LIKE ? OR LOWER(direccion) LIKE ? OR LOWER(titulo) LIKE ?)")
                params.extend([f"%{v}%", f"%{v}%", f"%{v}%"])
            if conds:
                query += " AND (" + " OR ".join(conds) + ")"
            
        if tipo_propiedad:
            norm_tipo = tipo_propiedad.lower()
            if 'terreno' in norm_tipo or 'lote' in norm_tipo:
                query += " AND (LOWER(tipo_propiedad) LIKE '%terreno%' OR LOWER(tipo_propiedad) LIKE '%lote%')"
            elif 'ph' in norm_tipo:
                query += " AND LOWER(tipo_propiedad) LIKE '%ph%'"
            elif 'casa' in norm_tipo:
                query += " AND LOWER(tipo_propiedad) LIKE '%casa%'"
            elif 'local' in norm_tipo or 'oficina' in norm_tipo:
                query += " AND (LOWER(tipo_propiedad) LIKE '%local%' OR LOWER(tipo_propiedad) LIKE '%oficina%')"
            else:
                query += " AND (LOWER(tipo_propiedad) LIKE '%depto%' OR LOWER(tipo_propiedad) LIKE '%departamento%' OR tipo_propiedad IS NULL OR tipo_propiedad = '' OR tipo_propiedad = 'None')"
                
        if ambientes:
            try:
                amb_val = int(ambientes)
                if amb_val >= 5:
                    query += " AND ambientes >= 5"
                else:
                    query += " AND ambientes = ?"
                    params.append(amb_val)
            except ValueError:
                pass
                
        if dormitorios:
            try:
                dorm_val = int(dormitorios)
                if dorm_val >= 4:
                    query += " AND dormitorios >= 4"
                else:
                    query += " AND dormitorios = ?"
                    params.append(dorm_val)
            except ValueError:
                pass
                
        if tipo_operacion:
            query += " AND LOWER(tipo_operacion) = ?"
            params.append(tipo_operacion.lower())
            
        # Active lifecycle filter for Portal Cliente
        from datetime import datetime, timedelta
        op_clean = (tipo_operacion or 'venta').lower()
        max_days = 60 if op_clean == 'alquiler' else 120
        cutoff_date = (datetime.now() - timedelta(days=max_days)).strftime('%Y-%m-%d %H:%M:%S')
        query += " AND fecha_captacion >= ?"
        params.append(cutoff_date)
            
        if min_precio:
            query += " AND precio >= ?"
            params.append(min_precio)
        if max_precio:
            query += " AND precio <= ?"
            params.append(max_precio)
            
        if min_m2:
            query += " AND (m2_cubiertos >= ? OR m2_total >= ?)"
            params.extend([min_m2, min_m2])

        if 'balcon' in amenities_list or 'balcón' in amenities_list:
            query += " AND (COALESCE(LOWER(descripcion),'') LIKE '%balcon%' OR COALESCE(LOWER(descripcion),'') LIKE '%balcón%' OR COALESCE(LOWER(titulo),'') LIKE '%balcon%' OR COALESCE(LOWER(titulo),'') LIKE '%balcón%')"
        if 'pileta' in amenities_list or 'piscina' in amenities_list:
            query += " AND (COALESCE(LOWER(descripcion),'') LIKE '%pileta%' OR COALESCE(LOWER(descripcion),'') LIKE '%piscina%' OR COALESCE(LOWER(titulo),'') LIKE '%pileta%' OR COALESCE(LOWER(titulo),'') LIKE '%piscina%')"
        if 'parrilla' in amenities_list:
            query += " AND (COALESCE(LOWER(descripcion),'') LIKE '%parrilla%' OR COALESCE(LOWER(descripcion),'') LIKE '%quincho%' OR COALESCE(LOWER(titulo),'') LIKE '%parrilla%')"
        if 'terraza' in amenities_list:
            query += " AND (COALESCE(LOWER(descripcion),'') LIKE '%terraza%' OR COALESCE(LOWER(descripcion),'') LIKE '%solarium%' OR COALESCE(LOWER(titulo),'') LIKE '%terraza%')"
        if 'cochera' in amenities_list:
            query += " AND (cocheras > 0 OR COALESCE(LOWER(descripcion),'') LIKE '%cochera%' OR COALESCE(LOWER(descripcion),'') LIKE '%garage%' OR COALESCE(LOWER(descripcion),'') LIKE '%estacionamiento%' OR COALESCE(LOWER(titulo),'') LIKE '%cochera%')"
        if 'jardin' in amenities_list or 'jardín' in amenities_list:
            query += " AND (COALESCE(LOWER(descripcion),'') LIKE '%jardin%' OR COALESCE(LOWER(descripcion),'') LIKE '%jardín%' OR COALESCE(LOWER(descripcion),'') LIKE '%patio%' OR COALESCE(LOWER(descripcion),'') LIKE '%parque%' OR COALESCE(LOWER(titulo),'') LIKE '%jardin%')"

        tokko_priority = "(CASE WHEN LOWER(COALESCE(portal,'')) IN ('tokko', 'tokko_broker', 'propio', 'ferrari', 'directo') OR busqueda_id IS NOT NULL THEN 0 ELSE 1 END) ASC"

        if ordenar == 'menor_precio':
            query += f" ORDER BY {tokko_priority}, precio ASC"
        elif ordenar == 'mayor_precio':
            query += f" ORDER BY {tokko_priority}, precio DESC"
        elif ordenar == 'm2_desc':
            query += f" ORDER BY {tokko_priority}, m2_cubiertos DESC"
        else:
            query += f" ORDER BY {tokko_priority}, id DESC"
            
        return query, params

    # Ejecutar búsquedas en Tokko y Portales
    q_tokko, p_tokko = build_tokko_query()
    tokko_rows = conn.execute(q_tokko, p_tokko).fetchall()
    tokko_props = [sanitizar_marca_blanca(dict(r)) for r in tokko_rows]

    query_str, params_list = build_query()
    web_rows = conn.execute(query_str, params_list).fetchall()
    web_props = [sanitizar_marca_blanca(dict(r)) for r in web_rows]
    
    was_live_scraped = False
    # Disparar LiveProbe en tiempo real para enriquecer y guardar siempre en BD
    if page == 1:
        target_zona = barrio if (barrio and len(barrio.strip()) >= 3) else "CABA"
        print(f"[Leads_Externo] Consultando al Servidor de Scraping vía API para portal clientes en '{target_zona}' ({tipo_operacion})...")
        inserted = probe_and_save_zone(target_zona, tipo_propiedad or 'departamento', ambientes, tipo_operacion or 'venta')
        if inserted > 0:
            was_live_scraped = True
            web_rows = conn.execute(query_str, params_list).fetchall()
            web_props = [sanitizar_marca_blanca(dict(r)) for r in web_rows]

    # Fusionar priorizando SIEMPRE todas las propiedades Tokko al inicio
    all_combined = tokko_props + web_props
    
    import math
    total_rows = len(all_combined)
    total_pages = max(1, math.ceil(total_rows / limit))

    props_slice = all_combined[offset:offset + limit]
    
    return jsonify({
        "success": True, 
        "count": len(props_slice), 
        "total_count": total_rows,
        "page": page,
        "total_pages": total_pages,
        "limit": limit,
        "was_live_scraped": was_live_scraped,
        "propiedades": props_slice
    })

@leads_externo_bp.route('/portal/api/tasar', methods=['POST'])
def api_tasar():
    """
    Tasador Express con la LÓGICA COMPLETA EXACTA del backend original (modules/tasador.py & db_tasador.py).
    """
    data = request.json or {}
    zona = str(data.get('zona') or data.get('barrio') or 'Palermo').strip()
    tipo = str(data.get('tipo_propiedad') or 'departamento').lower()
    tipo_operacion = str(data.get('tipo_operacion') or 'venta').lower()
    
    metodo_metros = data.get('metodo_metros', 'totales')
    try:
        metros = float(data.get('metros') or data.get('m2_totales') or 50)
    except:
        metros = 50.0
    try:
        metros_cubiertos_val = data.get('metros_cubiertos')
        metros_cubiertos = float(metros_cubiertos_val) if metros_cubiertos_val is not None else metros
    except:
        metros_cubiertos = metros
        
    ambientes_raw = data.get('ambientes')
    ambientes = [int(ambientes_raw)] if ambientes_raw else None
    
    estado_propiedad = str(data.get('estado_conservacion') or 'bueno')
    country_ubicacion = str(data.get('country_ubicacion') or 'no_country')
    country_activo = country_ubicacion in ['laguna', 'interno', 'perimetral']
    tasador_estado_activo = estado_propiedad in ['estrenar', 'muybueno', 'bueno', 'regular', 'refaccionar', 'malo']
    
    rango_negativo = 0.25
    rango_positivo = 0.25
    descartar_mal_cargados = True

    metros_calc = metros
    if metodo_metros == 'cubiertos' and metros_cubiertos:
        metros_calc = metros_cubiertos
    elif metodo_metros == 'homogeneizados' and metros_cubiertos is not None:
        descubiertos = max(0.0, metros - metros_cubiertos)
        metros_calc = metros_cubiertos + descubiertos * 0.2

    conn = db.get_db()
    check_cnt = conn.execute("SELECT COUNT(*) as cant FROM propiedades WHERE LOWER(barrio) LIKE ?", (f"%{zona.lower()}%",)).fetchone()['cant']
    was_live_scraped = False
    if check_cnt < 12:
        inserted = probe_and_save_zone(zona, tipo, ambientes)
        if inserted > 0:
            was_live_scraped = True

    precios = None
    try:
        from database.db_tasador import get_tasacion_zona
        precios = get_tasacion_zona(
            zona=zona,
            tipo_propiedad=tipo,
            tipo_operacion=tipo_operacion,
            metros=metros,
            ambientes=ambientes,
            min_m2_usd=0,
            metodo_metros=metodo_metros,
            metros_cubiertos=metros_cubiertos,
            descartar_mal_cargados=descartar_mal_cargados,
            rango_negativo=rango_negativo,
            rango_positivo=rango_positivo
        )
    except Exception as err:
        print(f"[Tasador Express] Excepción en get_tasacion_zona: {err}")

    if precios and isinstance(precios, dict) and precios.get('medio'):
        multiplier = (metros_calc if precios.get('usa_m2', True) else 1)
        final_bajo = precios['bajo'] * multiplier
        final_medio = precios['medio'] * multiplier
        final_alto = precios['alto'] * multiplier
        
        base_offset_str = db.get_config('tasador_ajuste_base', '0')
        try:
            base_offset_pct = float(base_offset_str) / 100.0
        except ValueError:
            base_offset_pct = 0.0
            
        final_bajo *= (1.0 + base_offset_pct)
        final_medio *= (1.0 + base_offset_pct)
        final_alto *= (1.0 + base_offset_pct)
        
        ajuste_pct = 0.0
        if estado_propiedad in ['estrenar', 'impecable']:
            ajuste_pct = 0.15
        elif estado_propiedad in ['renovada', 'nueva']:
            ajuste_pct = 0.10
        elif estado_propiedad in ['muybueno', 'muy_bueno', 'bueno']:
            ajuste_pct = 0.00
        elif estado_propiedad in ['pintar', 'regular']:
            ajuste_pct = -0.10
        elif estado_propiedad in ['refaccionar', 'humedad']:
            ajuste_pct = -0.20
        elif estado_propiedad in ['critico', 'malo']:
            ajuste_pct = -0.35
                
        final_medio *= (1.0 + ajuste_pct)
        
        country_ajuste_pct = 0.0
        if country_activo:
            if country_ubicacion == 'laguna':
                country_ajuste_pct = float(db.get_config('tasador_country_laguna', '18')) / 100.0
            elif country_ubicacion == 'perimetral':
                country_ajuste_pct = -float(db.get_config('tasador_country_perimetral', '12')) / 100.0
            elif country_ubicacion == 'interno':
                country_ajuste_pct = 0.05
                
            final_medio *= (1.0 + country_ajuste_pct)

        # Silent handicap filter for portal valuations (-8% default)
        handicap_pct = float(db.get_config('tasador_handicap_portal', '-8')) / 100.0
        precio_estimado = round(final_medio * (1.0 + handicap_pct))
        rango_min = round(precio_estimado * 0.78) # -22%
        rango_max = round(precio_estimado * 1.14) # +14%
    else:
        base_m2 = 2100.0
        if any(b in zona.lower() for b in ['palermo', 'recoleta', 'belgrano', 'puerto madero', 'nordelta']):
            base_m2 = 2650.0
        elif any(b in zona.lower() for b in ['almagro', 'caballito', 'villa crespo', 'olivos', 'san isidro']):
            base_m2 = 1980.0
        elif any(b in zona.lower() for b in ['balvanera', 'once', 'la boca', 'san martin', 'moron']):
            base_m2 = 1450.0
            
        mult_estado = 1.0
        if estado_propiedad in ['estrenar', 'impecable']: mult_estado = 1.15
        elif estado_propiedad in ['renovada', 'nueva']: mult_estado = 1.10
        elif estado_propiedad in ['muybueno', 'muy_bueno', 'bueno']: mult_estado = 1.00
        elif estado_propiedad in ['pintar', 'regular']: mult_estado = 0.90
        elif estado_propiedad in ['refaccionar', 'humedad']: mult_estado = 0.80
        elif estado_propiedad in ['critico', 'malo']: mult_estado = 0.65
        
        mult_country = 1.0
        if country_ubicacion == 'laguna': mult_country = 1.18
        elif country_ubicacion == 'interno': mult_country = 1.05
        elif country_ubicacion == 'perimetral': mult_country = 0.88
        
        raw_estimado = round(metros_calc * base_m2 * mult_estado * mult_country)
        handicap_pct = float(db.get_config('tasador_handicap_portal', '-8')) / 100.0
        precio_estimado = round(raw_estimado * (1.0 + handicap_pct))
        rango_min = round(precio_estimado * 0.78) # -22%
        rango_max = round(precio_estimado * 1.14) # +14%

    return jsonify({
        "success": True,
        "zona": zona,
        "tipo_propiedad": tipo,
        "tipo_operacion": tipo_operacion,
        "metodo_metros": metodo_metros,
        "metros_calculados": round(metros_calc, 1),
        "rango_min": rango_min,
        "rango_max": rango_max,
        "estimado_base": precio_estimado,
        "was_live_scraped": was_live_scraped,
        "moneda": "USD" if tipo_operacion == "venta" else "ARS"
    })

@leads_externo_bp.route('/portal/api/enviar_codigo_wa', methods=['POST'])
def api_enviar_codigo_wa():
    """Genera un código aleatorio de 4 dígitos y lo envía por WhatsApp al número ingresado."""
    import random
    data = request.json or {}
    nombre = data.get('nombre', '').strip()
    telefono = data.get('telefono', '').strip()

    if not telefono or not nombre:
        return jsonify({"success": False, "error": "El nombre y el número de WhatsApp son obligatorios."}), 400

    clean_phone = telefono.replace(" ", "").replace("-", "").replace("+", "")
    if len(clean_phone) < 8:
        return jsonify({"success": False, "error": "Número de WhatsApp inválido."}), 400

    codigo = f"{random.randint(1000, 9999)}"
    agency_info = db.get_agency_settings()
    agency_brand = agency_info.get('nombre', 'Portal Inmobiliario')
    msg = f"🔑 Tu código de acceso a {agency_brand} es: *{codigo}*\nIngresalo en la pantalla para validar tu WhatsApp."

    conn = db.get_db()
    try:
        # 1. Intentar encolar en cola_mensajes si la tabla lo soporta
        try:
            conn.execute("""
                INSERT INTO cola_mensajes (telefono, mensaje, estado, fecha_programada)
                VALUES (?, ?, 'pendiente', CURRENT_TIMESTAMP)
            """, (clean_phone, msg))
        except Exception as e_cola:
            print(f"[Portal WA Verification] Error encolando mensaje: {e_cola}")

        # 2. Registrar o actualizar el código de verificación en contactos (normalizando coincidencia por los últimos 10 dígitos)
        core_phone = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
        row_exists = conn.execute("""
            SELECT id FROM contactos 
            WHERE REPLACE(REPLACE(REPLACE(telefono, ' ', ''), '-', ''), '+', '') LIKE ?
            ORDER BY id DESC LIMIT 1
        """, (f"%{core_phone}%",)).fetchone()
        
        if row_exists:
            conn.execute("""
                UPDATE contactos 
                SET notas = ?
                WHERE id = ?
            """, (f'Codigo temporal: {codigo}', row_exists['id']))
        else:
            try:
                conn.execute("""
                    INSERT INTO contactos (nombre, telefono, notas)
                    VALUES (?, ?, ?)
                """, (nombre, clean_phone, f'Codigo temporal: {codigo}'))
            except Exception:
                pass

        conn.commit()

        print(f"[VERIFICACIÓN WA] Código generado para {nombre} ({clean_phone}): {codigo}")

        # Disparar directamente el envío con ephemeral_sender.js usando la sesión del Portal de Clientes
        try:
            import subprocess, os
            wa_node_dir = os.path.join(os.getcwd(), 'lib', 'whatsapp_node')
            sender_script = os.path.join(wa_node_dir, 'ephemeral_sender.js')
            node_bin = os.path.join(wa_node_dir, 'bin', 'node.exe')
            node_cmd = node_bin if os.path.exists(node_bin) else "node"
            
            cmd = [node_cmd, sender_script, '--scope', 'portal', '--user', 'admin', '--action', 'message', '--phone', clean_phone, '--text', msg]
            creationflags = 0x08000000 if os.name == 'nt' else 0
            log_out = open(os.path.join(os.getcwd(), 'static', 'uploads', 'node_portal_send_err.txt'), 'w')
            subprocess.Popen(cmd, cwd=wa_node_dir, stdout=log_out, stderr=log_out, creationflags=creationflags)
            print(f"[Portal WA Verification] Subproceso de envío directo iniciado para {clean_phone} con sesión de Portal")
        except Exception as e_direct:
            print(f"[Portal WA Verification] Error al disparar envío directo: {e_direct}")

        return jsonify({
            "success": True,
            "message": f"Código enviado por WhatsApp a {telefono}."
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al generar código: {e}"}), 500


@leads_externo_bp.route('/portal/api/verificar_codigo_wa', methods=['POST'])
def api_verificar_codigo_wa():
    """Verifica si el código ingresado coincide con el enviado al teléfono."""
    data = request.json or {}
    telefono = data.get('telefono', '').strip()
    codigo_ingresado = data.get('codigo', '').strip()

    clean_phone = re.sub(r'\D', '', telefono)
    core_phone = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
    conn = db.get_db()
    try:
        # 1. Buscar en contactos el registro del número exacto o sufijo de 10 dígitos que tenga 'Codigo temporal:'
        row = conn.execute("""
            SELECT id, notas FROM contactos 
            WHERE REPLACE(REPLACE(REPLACE(telefono, ' ', ''), '-', ''), '+', '') LIKE ? 
              AND notas LIKE '%Codigo temporal:%'
            ORDER BY id DESC LIMIT 1
        """, (f"%{core_phone}%",)).fetchone()

        if not row:
            return jsonify({"success": False, "error": "No se encontró una solicitud activa para este número."}), 400

        notas = row['notas'] or ''
        match = re.search(r'Codigo temporal:\s*(\d{4})', notas)
        codigo_guardado = match.group(1) if match else ''

        if codigo_ingresado == codigo_guardado:
            return jsonify({
                "success": True,
                "message": "¡WhatsApp validado correctamente!"
            })
        else:
            return jsonify({"success": False, "error": "Código incorrecto. Por favor verificá e intentá nuevamente."}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error al verificar: {e}"}), 500


@leads_externo_bp.route('/portal/api/solicitar_lead', methods=['POST'])
def api_solicitar_lead():
    """Registra el Lead verificado y notifica al agente admin por WhatsApp."""
    data = request.json or {}
    nombre = data.get('nombre', 'Cliente Web').strip()
    telefono = data.get('telefono', '').strip()
    tipo_lead = data.get('tipo_lead', 'visita')
    propiedad_id = data.get('propiedad_id')
    tasacion_data = data.get('tasacion_data')

    if not telefono:
        return jsonify({"success": False, "error": "El numero de WhatsApp es obligatorio."}), 400

    conn = db.get_db()

    # === VERIFICACIÓN REAL MULTI-PROXY (1 de 3) SI HAY PROPIEDAD_ID O URL ===
    prop_url = data.get('url') or data.get('propiedad_url')
    if propiedad_id or prop_url:
        try:
            if not prop_url and propiedad_id:
                try:
                    clean_pid = int(str(propiedad_id).replace('tokko_', '').strip())
                    prop_row = conn.execute("SELECT url FROM propiedades WHERE id = ?", (clean_pid,)).fetchone()
                    if not prop_row:
                        prop_row = conn.execute("SELECT url_ficha as url FROM tokko_propiedades WHERE tokko_id = ?", (str(clean_pid),)).fetchone()
                    if prop_row:
                        prop_url = prop_row['url']
                except (ValueError, TypeError):
                    pass
            
            if prop_url:
                print(f"[SolicitarLead] Verificando disponibilidad real multi-proxy para URL: {prop_url}")
                from lib.link_checker import verificar_propiedad_multi_proxy
                res_check = verificar_propiedad_multi_proxy(prop_url)
                if not res_check.get('active'):
                    if propiedad_id:
                        try:
                            conn.execute("UPDATE propiedades SET notas = 'Dada de baja en portal (verificado en solicitud de visita)' WHERE id = ?", (int(str(propiedad_id).replace('tokko_', '')),))
                            conn.commit()
                        except: pass
                    return jsonify({
                        "success": False, 
                        "property_inactive": True,
                        "error": "Esta propiedad ya no se encuentra disponible en el portal original (dada de baja o pausada recientemente)."
                    }), 400
        except Exception as e:
            print(f"[SolicitarLead] Error en verificación multi-proxy: {e}")

    # === TELEFONO DEL AGENTE ADMIN ===
    agente_phone = os.environ.get("SUPERADMIN_PHONE", "").strip()
    if not agente_phone:
        try:
            admin_user = conn.execute("SELECT id FROM usuarios WHERE rol = 'admin' ORDER BY id ASC LIMIT 1").fetchone()
            if admin_user:
                admin_id = admin_user['id']
                cfg_phone = db.get_config(f'agente_telefono_{admin_id}', db.get_config('agente_telefono', ''))
                if cfg_phone and str(cfg_phone).strip():
                    agente_phone = str(cfg_phone).strip()
        except Exception:
            pass
    if not agente_phone:
        agente_phone = SUPERADMIN_PHONE

    # === REGISTRAR CONTACTO EN CRM ===
    try:
        conn.execute("""
            INSERT INTO crm_contactos (nombre, telefono, origen, fecha_alta, notas)
            VALUES (?, ?, ?, datetime('now', 'localtime'), ?)
        """, (nombre, telefono, f'web_portal_{tipo_lead}', f'Origen: Portal Publico ({tipo_lead})'))
        conn.commit()
    except Exception:
        pass

    # === DATOS DE PROPIEDAD ===
    prop_info = None
    if propiedad_id:
        str_pid = str(propiedad_id).strip()
        if str_pid.startswith('tokko_'):
            tok_num = str_pid.replace('tokko_', '').strip()
            p_row = conn.execute("""
                SELECT tokko_id as id, titulo, tipo_operacion, tipo_propiedad, precio, moneda,
                       barrio, localidad, zona, foto_principal as foto_url, url_ficha as url
                FROM tokko_propiedades WHERE CAST(tokko_id AS TEXT) = ?
            """, (tok_num,)).fetchone()
            if p_row:
                prop_info = dict(p_row)
        else:
            p_row = conn.execute("SELECT * FROM propiedades WHERE id = ? OR CAST(id AS TEXT) = ?", (propiedad_id, str_pid)).fetchone()
            if p_row:
                prop_info = dict(p_row)

    # === MENSAJE DE ALERTA (formato exacto solicitado) ===
    if tipo_lead == 'visita' and prop_info:
        moneda = prop_info.get('moneda') or 'USD'
        precio_val = prop_info.get('precio')
        precio_fmt = f"{moneda} {precio_val:,.0f}".replace(',', '.') if precio_val else 'S/D'
        barrio_val = prop_info.get('barrio') or prop_info.get('zona') or prop_info.get('localidad') or 'S/D'
        link_val = prop_info.get('url') or 'Portal'

        msg_alerta = (
            f"NUEVA SOLICITUD DE VISITA EN WEB\n"
            f"Cliente: {nombre} ({telefono})\n"
            f"Valor: {precio_fmt}\n"
            f"Barrio: {barrio_val}\n"
            f"Link: {link_val}"
        )
    else:
        msg_alerta = (
            f"SOLICITUD DE TASACION / VENTA EN WEB\n"
            f"Cliente: {nombre} ({telefono})\n"
            f"Tasacion preliminar: {tasacion_data or 'Ver detalle en CRM'}\n"
            f"Accion: Contactar al cliente para coordinar visita presencial."
        )

    # === ENCOLAR Y ENVIAR ALERTA WHATSAPP ===
    try:
        conn.execute("""
            INSERT INTO cola_mensajes (telefono, mensaje, estado, fecha_programada)
            VALUES (?, ?, 'pendiente', datetime('now', 'localtime'))
        """, (agente_phone, msg_alerta))
        conn.commit()
        print(f"[Portal Lead] Alerta encolada en cola_mensajes para {agente_phone}")
    except Exception as e_cola:
        print(f"[Portal Lead] Error encolando alerta: {e_cola} - MSG: {msg_alerta[:100]}")

    try:
        import subprocess
        wa_node_dir = os.path.join(os.getcwd(), 'lib', 'whatsapp_node')
        sender_script = os.path.join(wa_node_dir, 'ephemeral_sender.js')
        node_bin = os.path.join(wa_node_dir, 'bin', 'node.exe')
        node_cmd = node_bin if os.path.exists(node_bin) else "node"
        
        clean_agente = agente_phone.replace(" ", "").replace("-", "").replace("+", "")
        cmd = [node_cmd, sender_script, '--scope', 'portal', '--user', 'admin', '--action', 'message', '--phone', clean_agente, '--text', msg_alerta]
        creationflags = 0x08000000 if os.name == 'nt' else 0
        log_out = open(os.path.join(os.getcwd(), 'static', 'uploads', 'node_portal_send_err.txt'), 'w')
        subprocess.Popen(cmd, cwd=wa_node_dir, stdout=log_out, stderr=log_out, creationflags=creationflags)
        print(f"[Portal Lead] Alerta WhatsApp disparada directamente a {clean_agente}")
    except Exception as e_direct:
        print(f"[Portal Lead] Error al disparar alerta directa: {e_direct}")

    return jsonify({
        "success": True,
        "message": "Solicitud enviada con exito! Un agente te contactara a la brevedad por WhatsApp.",
        "agente_asignado": agente_phone
    })

