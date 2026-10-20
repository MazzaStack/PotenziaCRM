"""
Routes and logic for Publicación a Placa (PAP) plugin.
Allows real-time customization and PNG generation of real estate marketing flyers.
"""
import os
import re
import json
import uuid
import base64
from flask import Blueprint, render_template, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from database import db
from modules.auth import privilege_required
from curl_cffi import requests as requests_cffi
import requests as requests_std
from bs4 import BeautifulSoup

publicacion_placa_bp = Blueprint('publicacion_placa', __name__)

@publicacion_placa_bp.route('/pap')
@login_required
@privilege_required('menu_item', 'pap')
def index():
    """Render the PAP dashboard, passing Tokko and CRM properties."""
    # 1. Load Tokko properties only if the user belongs to an office with Tokko
    is_solo_agent = not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza'
    tokko_props = []
    if not is_solo_agent:
        user_oficina_id = getattr(current_user, 'oficina_id', None)
        # Only offices that have Tokko properties (Oficina 1 / Ferrari y Asociados or SuperAdmin)
        if user_oficina_id == 1 or current_user.usuario == 'GermanMazza':
            conn = db.get_db(db.MASTER_DB_PATH)
            try:
                rows = conn.execute("SELECT * FROM tokko_propiedades WHERE activa = 1 ORDER BY CAST(tokko_id AS INTEGER) ASC").fetchall()
                for r in rows:
                    desc = r['descripcion'] or ''
                    
                    # Read from structured columns first
                    banos = str(r['banos']) if r['banos'] else ""
                    cocheras = str(r['cocheras']) if r['cocheras'] else ""
                    
                    # Fallback to description regex parsing if empty or "0"
                    if not banos or banos == "0":
                        banos_match = re.search(r'(\d+)\s*(?:baño|bano)', desc, re.I)
                        banos = banos_match.group(1) if banos_match else ""
                        
                    if not cocheras or cocheras == "0":
                        cochera_match = re.search(r'(\d+)\s*(?:cochera|garage|coch)', desc, re.I)
                        cocheras = cochera_match.group(1) if cochera_match else ""

                    tokko_props.append({
                        'id': f"tokko_{r['tokko_id']}",
                        'portal': 'tokko',
                        'titulo': r['titulo'] or '',
                        'precio': int(r['precio']) if r['precio'] else '',
                        'moneda': r['moneda'] or 'USD',
                        'ambientes': r['ambientes'] or '',
                        'dormitorios': r['dormitorios'] or '',
                        'banos': banos,
                        'cocheras': cocheras,
                        'm2_total': int(r['superficie_total']) if r['superficie_total'] else '',
                        'foto_url': r['foto_principal'] or '',
                        'fotos_json': r['fotos_json'] or '[]',
                        'descripcion': r['descripcion'] or ''
                    })
            except Exception as e:
                print("Error fetching Tokko properties in PAP:", e)
            finally:
                conn.close()
        
    # 2. Load scraped properties from the last 5 days only (Zonaprop, Argenprop, Mercadolibre)
    from datetime import datetime, timedelta
    five_days_ago = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d %H:%M:%S')
    props = db.get_propiedades(limit=100, min_fecha=five_days_ago)
    
    agency = db.get_agency_settings()
    user_name_display = (current_user.nombre_display or current_user.usuario) if (current_user and current_user.is_authenticated) else 'Agente Inmobiliario'
    
    # Get agent config values as defaults (db.get_config automatically handles user session scoping)
    agent_name = db.get_config('pap_agent_name') or db.get_config('agente_nombre') or user_name_display
    agent_phone = db.get_config('pap_agent_phone') or db.get_config('agente_telefono') or (agency.get('telefono') if agency else '') or '+54 11 61114414'
    agent_email = db.get_config('pap_agent_email') or db.get_config('agente_email') or (agency.get('email') if agency else '') or (getattr(current_user, 'email', None) or '') or ''
    agent_web = db.get_config('pap_agent_web') or (agency.get('slogan') if agency else '') or (agency.get('nombre') if agency else '') or ''
    matricula = db.get_config('pap_matricula') or (agency.get('matricula') if agency else '') or 'Martillero y Corredor Público Colegiado'
    
    company_logo = db.get_config('company_logo_path', '/static/img/potenzia_logo_transparent.png') or '/static/img/potenzia_logo_transparent.png'
    
    # Determine default logos based on whether user is solo agent or belongs to an office (e.g. Ferrari y Asociados)
    user_oficina_id = getattr(current_user, 'oficina_id', None)
    if is_solo_agent:
        default_footer_logo = company_logo # Potenzia CRM
        agency_default_logo = company_logo
    else:
        office_logo = None
        if user_oficina_id:
            conn_off = db.get_db()
            try:
                row_off = conn_off.execute("SELECT logo_url FROM oficinas WHERE id = ?", (user_oficina_id,)).fetchone()
                if row_off and row_off['logo_url']:
                    office_logo = row_off['logo_url']
            except Exception:
                pass
            finally:
                conn_off.close()
        default_footer_logo = office_logo or '/static/uploads/footerlogo.png'
        agency_default_logo = office_logo or company_logo
        
    logo_v1 = db.get_config('pap_logo_v1')
    if logo_v1 is None:
        logo_v1 = agency_default_logo
        
    logo_v2 = db.get_config('pap_logo_v2')
    if logo_v2 is None:
        logo_v2 = default_footer_logo
        
    logo_v3 = db.get_config('pap_logo_v3')
    if logo_v3 is None:
        logo_v3 = agency_default_logo
    
    return render_template('pap.html', 
                           tokko_props=tokko_props,
                           props=props, 
                           agency=agency,
                           is_solo_agent=is_solo_agent,
                           default_agent_name=agent_name, 
                           default_agent_phone=agent_phone,
                           default_agent_email=agent_email,
                           default_agent_web=agent_web,
                           default_matricula=matricula,
                           default_company_logo=agency_default_logo,
                           default_footer_logo=default_footer_logo,
                           default_logo_v1=logo_v1,
                           default_logo_v2=logo_v2,
                           default_logo_v3=logo_v3)

@publicacion_placa_bp.route('/pap/save-agent-config', methods=['POST'])
@login_required
@privilege_required('menu_item', 'pap')
def save_agent_config():
    """Save user-scoped agent configuration for PAP (Name, Phone, Email, Web, Matrícula, Logos per version)."""
    data = request.get_json() or {}
    try:
        if 'agent_name' in data:
            val = (data['agent_name'] or '').strip()
            db.set_config('pap_agent_name', val)
            if val:
                db.set_config('agente_nombre', val)
        if 'agent_phone' in data:
            val = (data['agent_phone'] or '').strip()
            db.set_config('pap_agent_phone', val)
            if val:
                db.set_config('agente_telefono', val)
        if 'agent_email' in data:
            db.set_config('pap_agent_email', (data['agent_email'] or '').strip())
        if 'agent_web' in data:
            db.set_config('pap_agent_web', (data['agent_web'] or '').strip())
        if 'matricula' in data:
            db.set_config('pap_matricula', (data['matricula'] or '').strip())
        if 'logo_v1' in data:
            db.set_config('pap_logo_v1', (data['logo_v1'] or '').strip())
        if 'logo_v2' in data:
            db.set_config('pap_logo_v2', (data['logo_v2'] or '').strip())
        if 'logo_v3' in data:
            db.set_config('pap_logo_v3', (data['logo_v3'] or '').strip())
            
        return jsonify({'success': True, 'message': '¡Tu configuración de agente y logos ha sido guardada con éxito!'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@publicacion_placa_bp.route('/pap/upload-logo', methods=['POST'])
@login_required
@privilege_required('menu_item', 'pap')
def upload_logo():
    """Upload an isolated logo image file for the current agent."""
    if 'logo_file' not in request.files:
        return jsonify({'success': False, 'error': 'No se envió ningún archivo.'}), 400
    
    file = request.files['logo_file']
    version = request.form.get('version', 'v3').strip().lower() # 'v1', 'v2', 'v3' or 'all'
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': 'Archivo no válido o vacío.'}), 400
        
    allowed_extensions = {'png', 'jpg', 'jpeg', 'webp', 'svg', 'gif'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed_extensions:
        return jsonify({'success': False, 'error': 'Formato no permitido. Usa PNG, JPG, WEBP o SVG.'}), 400
        
    import time
    uid = current_user.id if current_user and current_user.is_authenticated else 'agent'
    filename = f"agent_logo_{uid}_{version}_{int(time.time())}.{ext}"
    
    upload_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'static', 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    save_path = os.path.join(upload_folder, filename)
    file.save(save_path)
    
    relative_url = f"/static/uploads/{filename}"
    
    # Save directly to user's config key for this version
    if version == 'v1':
        db.set_config('pap_logo_v1', relative_url)
    elif version == 'v2':
        db.set_config('pap_logo_v2', relative_url)
    elif version == 'v3':
        db.set_config('pap_logo_v3', relative_url)
    elif version == 'all':
        db.set_config('pap_logo_v1', relative_url)
        db.set_config('pap_logo_v2', relative_url)
        db.set_config('pap_logo_v3', relative_url)
        
    return jsonify({
        'success': True,
        'url': relative_url,
        'filename': filename,
        'message': 'Logo subido y guardado con éxito.'
    })

@publicacion_placa_bp.route('/pap/scrape', methods=['POST'])
@login_required
@privilege_required('menu_item', 'pap')
def scrape_listing():
    """Scrape details or parse pasted HTML for a single property detail URL."""
    data = request.get_json() or {}
    url = data.get('url', '').strip()
    html_content = data.get('html_content', '').strip()
    portal = data.get('portal', '').strip() # 'zonaprop', 'mercadolibre', 'argenprop'
    
    if not url and not html_content:
        return jsonify({'success': False, 'error': 'Falta la URL o el contenido HTML de la propiedad.'}), 400
        
    try:
        scraped_data = None
        
        # Scenario A: User pasted HTML source code directly
        if html_content:
            if portal == 'mercadolibre' or 'mercadolibre.com' in html_content or 'mlstatic.com' in html_content:
                scraped_data = _parse_mercadolibre_html(html_content, url or "https://inmuebles.mercadolibre.com.ar/")
            elif portal == 'zonaprop' or 'zonaprop.com' in html_content or 'naventcdn.com' in html_content:
                scraped_data = _parse_zonaprop_html(html_content, url or "https://www.zonaprop.com.ar/")
            elif portal == 'argenprop' or 'argenprop.com' in html_content:
                scraped_data = _parse_argenprop_html(html_content, url or "https://www.argenprop.com/")
            else:
                return jsonify({
                    'success': False, 
                    'error': 'No pudimos detectar el portal en el HTML. Selecciona el portal de origen manualmente.'
                }), 400
                
        # Scenario B: Automatic scraping from URL
        else:
            if 'zonaprop.com.ar' in url:
                scraped_data = _scrape_zonaprop_detail(url)
            elif 'mercadolibre.com.ar' in url:
                scraped_data = _scrape_mercadolibre_detail(url)
            elif 'argenprop.com' in url:
                scraped_data = _scrape_argenprop_detail(url)
            else:
                return jsonify({
                    'success': False, 
                    'error': 'Portal no soportado. Debe ser Zonaprop, MercadoLibre o Argenprop.'
                }), 400
            
        if not scraped_data:
            return jsonify({
                'success': False, 
                'error': 'No se pudo obtener información del aviso. Verifique el enlace o intente pegando el código HTML.'
            }), 500
            
        return jsonify({
            'success': True,
            'data': scraped_data
        })
        
    except Exception as e:
        print(f"Error scraping detail URL: {e}")
        return jsonify({'success': False, 'error': f"Error al procesar: {str(e)}"}), 500

def is_safe_image_url(image_url: str) -> bool:
    """
    Protección Anti-SSRF para descarga de imágenes en PAP.
    Bloquea accesos a localhost, IPs privadas, loopback, link-local y esquemas inseguros.
    """
    if not image_url or not isinstance(image_url, str):
        return False
    try:
        import ipaddress
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(image_url.strip())
        if parsed.scheme.lower() not in ('http', 'https'):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False

        hostname_lower = hostname.lower().strip()
        if hostname_lower in ('localhost', '127.0.0.1', '::1', '0.0.0.0', '169.254.169.254', 'metadata.google.internal'):
            return False

        # Resolver IP y bloquear subredes privadas o loopback
        try:
            ip_str = socket.gethostbyname(hostname_lower)
            ip_obj = ipaddress.ip_address(ip_str)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved or ip_obj.is_multicast:
                return False
        except Exception:
            return False

        return True
    except Exception:
        return False

@publicacion_placa_bp.route('/pap/proxy-image')
@login_required
def proxy_image():
    """Proxy image downloads locally to bypass browser CORS restriction on Canvas exports (SSRF-protected)."""
    image_url = request.args.get('url')
    if not image_url:
        return "Falta el parámetro 'url'", 400

    if not is_safe_image_url(image_url):
        return "URL rechazada por políticas de seguridad del servidor.", 403
        
    try:
        # standard requests doesn't trigger datadome/cloudflare checks on static images CDN
        resp = requests_std.get(image_url, timeout=15)
        if resp.status_code != 200:
            # Fallback to curl_cffi
            resp = requests_cffi.get(image_url, impersonate='chrome', timeout=15)
            
        if resp.status_code != 200:
            return f"Error al descargar imagen: HTTP {resp.status_code}", resp.status_code
            
        return Response(
            resp.content,
            mimetype=resp.headers.get('Content-Type', 'image/jpeg'),
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=86400'
            }
        )
    except Exception as e:
        return f"Error de red: {e}", 500

@publicacion_placa_bp.route('/pap/save_story', methods=['POST'])
@login_required
@privilege_required('menu_item', 'pap')
def save_story():
    """Save base64 image data directly into the stories queue/calendar of the CRM."""
    data = request.get_json() or {}
    image_data_b64 = data.get('image', '')
    date_str = data.get('date', '') # YYYY-MM-DD
    
    if not image_data_b64 or not date_str:
        return jsonify({'success': False, 'error': 'Falta la imagen o la fecha.'}), 400
        
    try:
        if ',' in image_data_b64:
            header, image_data_b64 = image_data_b64.split(',', 1)
            
        img_bytes = base64.b64decode(image_data_b64)
        
        upload_dir = os.path.join(current_app.static_folder, 'uploads', 'historias')
        os.makedirs(upload_dir, exist_ok=True)
        
        fname = f"pap_{uuid.uuid4().hex}.png"
        save_path = os.path.join(upload_dir, fname)
        with open(save_path, 'wb') as f:
            f.write(img_bytes)
            
        db_path = f"/static/uploads/historias/{fname}"
        
        conn = db.get_db()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM historias_redes WHERE fecha_programada = ?", 
                (date_str,)
            ).fetchone()
            current_count = row[0] if row else 0
            
            conn.execute("""
                INSERT INTO historias_redes (fecha_programada, archivo_path, orden, estado, plataforma)
                VALUES (?, ?, ?, 'pendiente', 'whatsapp')
            """, (date_str, db_path, current_count + 1))
            conn.commit()
        finally:
            conn.close()
            
        return jsonify({
            'success': True,
            'message': 'Placa guardada y programada en tu sección de Historias.'
        })
    except Exception as e:
        print(f"Error saving PAP story: {e}")
        return jsonify({'success': False, 'error': f"Error al guardar: {str(e)}"}), 500


# --- SCRAPING AND HTML PARSING HELPERS ---

def _scrape_zonaprop_detail(url):
    """Fetch and parse Zonaprop detail page."""
    headers = {
        'Accept-Language': 'es-AR,es;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.google.com/'
    }
    resp = requests_cffi.get(url, impersonate='chrome', headers=headers, timeout=20)
    if resp.status_code != 200:
        return None
    return _parse_zonaprop_html(resp.text, url)

def _scrape_mercadolibre_detail(url):
    """Fetch and parse MercadoLibre detail page using standard requests to bypass js check."""
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-AR,es;q=0.9,en-US;q=0.8,en;q=0.7',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0'
    }
    resp = requests_std.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        # Fallback to curl_cffi
        resp = requests_cffi.get(url, impersonate='chrome', timeout=20)
        
    if resp.status_code != 200:
        return None
    return _parse_mercadolibre_html(resp.text, url)

def _scrape_argenprop_detail(url):
    """Fetch and parse Argenprop detail page."""
    headers = {
        'Accept-Language': 'es-AR,es;q=0.9,en-US;q=0.8,en;q=0.7',
        'Referer': 'https://www.google.com/'
    }
    resp = requests_cffi.get(url, impersonate='chrome', headers=headers, timeout=20)
    if resp.status_code != 200:
        return None
    return _parse_argenprop_html(resp.text, url)


# --- HTML DOM PARSERS ---

def _parse_zonaprop_html(html_text, url):
    """Parse Zonaprop detail HTML."""
    soup = BeautifulSoup(html_text, 'lxml')
    
    # 1. Parse JSON-LD
    schema_data = {}
    for s in soup.find_all('script', type='application/ld+json'):
        try:
            js = json.loads(s.string)
            if isinstance(js, dict) and js.get('@type') in ['House', 'Apartment', 'SingleFamilyResidence', 'Product']:
                schema_data = js
                break
        except Exception:
            pass
            
    title = schema_data.get('name')
    if not title:
        title_el = soup.find('h1')
        title = title_el.text.strip() if title_el else "Propiedad en Zonaprop"
        
    description = schema_data.get('description', '')
    
    # 2. Extract Price
    precio = None
    moneda = 'USD'
    price_el = soup.select_one('[class*="price-value"]') or soup.select_one('.price-value') or soup.select_one('[data-qa="price"]')
    price_text = price_el.text.strip() if price_el else ""
    
    if price_text:
        price_text_clean = price_text.upper()
        if '$' in price_text_clean and 'U$S' not in price_text_clean and 'USD' not in price_text_clean:
            moneda = 'ARS'
        nums = re.findall(r'[\d\.]+', price_text)
        if nums:
            try:
                precio = float(nums[0].replace('.', ''))
            except:
                pass
                
    # 3. Extract Images
    img_urls = re.findall(r'https?://imgar\.zonapropcdn\.com/avisos/[^\s\"\'\>\)]+\.(?:jpg|jpeg|webp|png)', html_text, re.IGNORECASE)
    high_res_imgs = []
    for img in img_urls:
        img_clean = re.sub(r'/\d+x\d+/', '/730x532/', img)
        if '?' in img_clean:
            img_clean = img_clean.split('?')[0]
        if img_clean not in high_res_imgs:
            high_res_imgs.append(img_clean)
            
    # 4. Extract Features
    features = {
        'dormitorios': "",
        'banos': "",
        'cocheras': "",
        'm2_total': ""
    }
    
    if schema_data:
        if schema_data.get('numberOfRooms'):
            features['dormitorios'] = schema_data.get('numberOfRooms')
            
    text_content = soup.get_text().lower()
    
    m2_match = re.search(r'(\d+)\s*(?:m2|m²)\s*(?:tot|cub)?', text_content)
    if m2_match:
        features['m2_total'] = int(m2_match.group(1))
        
    dorm_match = re.search(r'(\d+)\s*(?:dormitorio|dorm|hab)', text_content)
    if dorm_match:
        features['dormitorios'] = int(dorm_match.group(1))
        
    banos_match = re.search(r'(\d+)\s*(?:baño|bano)', text_content)
    if banos_match:
        features['banos'] = int(banos_match.group(1))
        
    cochera_match = re.search(r'(\d+)\s*(?:cochera|garage|coch)', text_content)
    if cochera_match:
        features['cocheras'] = int(cochera_match.group(1))
        
    return {
        'portal': 'zonaprop',
        'url': url,
        'titulo': title,
        'precio': precio or "",
        'moneda': moneda,
        'dormitorios': features['dormitorios'],
        'banos': features['banos'],
        'cocheras': features['cocheras'],
        'm2_total': features['m2_total'],
        'descripcion': description,
        'fotos': high_res_imgs[:25]
    }

def _parse_mercadolibre_html(html_text, url):
    """Parse MercadoLibre detail HTML."""
    soup = BeautifulSoup(html_text, 'lxml')
    
    # 1. Title
    title_el = soup.select_one('.ui-pdp-title')
    title = title_el.text.strip() if title_el else "Propiedad en MercadoLibre"
    
    # 2. Price & Currency
    precio = None
    moneda = 'USD'
    price_fraction = soup.select_one('.ui-pdp-price__part .andes-money-amount__fraction')
    if price_fraction:
        try:
            precio = float(price_fraction.text.strip().replace('.', ''))
        except:
            pass
            
    price_symbol = soup.select_one('.ui-pdp-price__part .andes-money-amount__currency-symbol')
    if price_symbol and '$' in price_symbol.text:
        moneda = 'ARS'
        if 'U$S' in price_symbol.text or 'USD' in price_symbol.text:
            moneda = 'USD'
            
    # 3. Description
    desc_el = soup.select_one('.ui-pdp-description__content')
    description = desc_el.text.strip() if desc_el else ""
    
    # 4. Features
    features = {
        'dormitorios': "",
        'banos': "",
        'cocheras': "",
        'm2_total': ""
    }
    
    for row in soup.select('.ui-pdp-specs__table tr') or soup.select('.ui-pdp-specs__list li'):
        text = row.get_text().lower()
        if 'dormitorio' in text or 'habitación' in text or 'habitacion' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['dormitorios'] = int(nums[0])
        elif 'baño' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['banos'] = int(nums[0])
        elif 'cochera' in text or 'cocheras' in text or 'garage' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['cocheras'] = int(nums[0])
        elif 'superficie total' in text or 'm²' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['m2_total'] = int(nums[0])
            
    text_content = soup.get_text().lower()
    if not features['m2_total']:
        m2_match = re.search(r'(\d+)\s*(?:m2|m²)', text_content)
        if m2_match: features['m2_total'] = int(m2_match.group(1))
    if not features['dormitorios']:
        dorm_match = re.search(r'(\d+)\s*(?:dormitorio|dorm|hab)', text_content)
        if dorm_match: features['dormitorios'] = int(dorm_match.group(1))
        
    # 5. Extract Images
    img_urls = re.findall(r'https?://http2\.mlstatic\.com/D_NQ_NP_[^\s\"\'\>\)]+\.(?:jpg|jpeg|webp|png)', html_text, re.IGNORECASE)
    high_res_imgs = []
    for img in img_urls:
        img_clean = re.sub(r'-[FIV]\.(webp|jpg|jpeg)', r'-O.\1', img)
        if not img_clean.startswith('http'):
            img_clean = 'https:' + img_clean
        if img_clean not in high_res_imgs:
            high_res_imgs.append(img_clean)
            
    return {
        'portal': 'mercadolibre',
        'url': url,
        'titulo': title,
        'precio': precio or "",
        'moneda': moneda,
        'dormitorios': features['dormitorios'],
        'banos': features['banos'],
        'cocheras': features['cocheras'],
        'm2_total': features['m2_total'],
        'descripcion': description,
        'fotos': high_res_imgs[:25]
    }

def _parse_argenprop_html(html_text, url):
    """Parse Argenprop detail HTML."""
    soup = BeautifulSoup(html_text, 'lxml')
    
    # 1. Title
    title_el = soup.select_one('.titlebar__title') or soup.find('h1')
    title = title_el.text.strip() if title_el else "Propiedad en Argenprop"
    
    # 2. Price
    precio = None
    moneda = 'USD'
    price_el = soup.select_one('.titlebar__price') or soup.select_one('.property-price')
    if price_el:
        price_text = price_el.text.strip().upper()
        if '$' in price_text and 'U$S' not in price_text:
            moneda = 'ARS'
        nums = re.findall(r'[\d\.]+', price_text)
        if nums:
            try:
                precio = float(nums[0].replace('.', ''))
            except:
                pass
                
    # 3. Description
    desc_el = (soup.select_one('.section-description--content') or 
               soup.select_one('.section-description') or 
               soup.select_one('.property-description__text') or 
               soup.select_one('.description-text'))
    description = desc_el.text.strip() if desc_el else ""
    
    # 4. Features
    features = {
        'dormitorios': "",
        'banos': "",
        'cocheras': "",
        'm2_total': ""
    }
    
    for item in soup.select('.property-main-features li') or soup.select('.custom-sidebar-properties li'):
        text = item.get_text().lower()
        if 'dorm' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['dormitorios'] = int(nums[0])
        elif 'baño' in text or 'bano' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['banos'] = int(nums[0])
        elif 'cochera' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['cocheras'] = int(nums[0])
        elif 'cubierta' in text or 'total' in text or 'm²' in text:
            nums = re.findall(r'\d+', text)
            if nums: features['m2_total'] = int(nums[0])
            
    # 5. Extract Images from multiple sources
    img_urls = []
    
    # A. Broad regex matches for argenprop domains
    regex_matches = re.findall(r'https?://(?:[a-zA-Z0-9\-]+\.)*argenprop\.com/[^\s\"\'\>\)]+\.(?:jpg|jpeg|webp|png)', html_text, re.IGNORECASE)
    img_urls.extend(regex_matches)
    
    # B. CSS Inline styles (background: url(...))
    for tag in soup.select('[style*="static-content"], [style*="argenprop.com"]'):
        style = tag.get('style', '')
        urls_in_style = re.findall(r'url\([\'\"]?(https?://[^\)\'\"\s]+)[\'\"]?\)', style, re.I)
        for u in urls_in_style:
            img_urls.append(u)
            
    # C. Standard <img> tags with lazy attributes
    for img in soup.find_all('img'):
        for attr in ['data-src', 'src', 'data-lazy', 'data-original']:
            val = img.get(attr)
            if val:
                val_clean = val.strip()
                if 'argenprop.com' in val_clean or 'static-content' in val_clean:
                    img_urls.append(val_clean)
                    
    # D. JSON-LD Schemas
    for s in soup.find_all('script', type='application/ld+json'):
        try:
            js = json.loads(s.string)
            if isinstance(js, dict):
                img_val = js.get('image')
                if isinstance(img_val, str):
                    img_urls.append(img_val)
                elif isinstance(img_val, list):
                    for img_item in img_val:
                        if isinstance(img_item, str):
                            img_urls.append(img_item)
        except:
            pass
            
    # Normalize, filter and de-duplicate images
    high_res_imgs = []
    for img in img_urls:
        # Ignore common layout icons, app logos and buttons
        if any(term in img.lower() for term in ['logo', 'google-play', 'app-store', 'data-fiscal', 'agea', 'ficha-camera.svg']):
            continue
            
        # Strip sizing suffixes (_u_medium, _u_small, etc.) to get high resolution original
        img_normalized = re.sub(r'_(?:u_medium|u_small|small|medium|u_large|large)\.(jpg|jpeg|png|webp)', r'.\1', img, flags=re.IGNORECASE)
        
        # Format absolute links
        if img_normalized.startswith('//'):
            img_normalized = 'https:' + img_normalized
        elif img_normalized.startswith('/'):
            img_normalized = 'https://www.argenprop.com' + img_normalized
            
        if img_normalized not in high_res_imgs:
            high_res_imgs.append(img_normalized)
        
    return {
        'portal': 'argenprop',
        'url': url,
        'titulo': title,
        'precio': precio or "",
        'moneda': moneda,
        'dormitorios': features['dormitorios'],
        'banos': features['banos'],
        'cocheras': features['cocheras'],
        'm2_total': features['m2_total'],
        'descripcion': description,
        'fotos': high_res_imgs[:25]
    }

