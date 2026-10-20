"""
Routes and logic for Links a Fichas de Propiedades para Clientes (LAF / Marca Blanca)
Scrapes Zonaprop, Argenprop, and MercadoLibre on-demand, creates public /ficha/<slug> links,
tracks openings, personalizes with agent data and Ferrari logo, and manages 60-day expiration.
"""
import re
import json
import random
import unicodedata
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, g, current_app
from flask_login import login_required, current_user

from database import db
from modules.auth import privilege_required
from lib.scraper_client import ScraperClient
from plugins.leads_externo.routes import sanitizar_marca_blanca, obtener_logo_empresa

fichas_bp = Blueprint('fichas_cliente', __name__)


def generar_slug_legible(titulo, barrio, portal):
    """
    Genera un slug semántico y legible como /ficha/propiedad-belgrano-3amb-445895 o /ficha/propiedad-445895
    """
    base = "propiedad"
    extra_parts = []
    
    if barrio:
        b_clean = re.sub(r'[^a-zA-Z0-9]+', '-', barrio.lower()).strip('-')
        if b_clean:
            extra_parts.append(b_clean)
            
    # Intentar extraer ambientes del titulo si existe
    m_amb = re.search(r'(\d+)\s*(?:amb|ambientes)', titulo.lower()) if titulo else None
    if m_amb:
        extra_parts.append(f"{m_amb.group(1)}amb")
        
    random_code = random.randint(100000, 999999)
    if extra_parts:
        slug = f"{base}-{'-'.join(extra_parts)}-{random_code}"
    else:
        slug = f"{base}-{random_code}"
        
    # Validar que no contenga caracteres raros
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug


@fichas_bp.route('/fichas/panel', methods=['GET'])
@login_required
@privilege_required('menu_item', 'panel_fichas')
def panel_fichas():
    """
    Panel de control donde el agente inmobiliario puede:
    1. Pegar link de portal para generar una ficha.
    2. Ver la lista de todas las fichas creadas con métricas de aperturas,
       fecha de expiración a 60 días y enlace listo para copiar.
    """
    # Por defecto, cada agente ve estrictamente SUS propias fichas creadas
    filtro_agente = request.args.get('agente_id')
    agente_filtrado = current_user.id
    
    if current_user.rol in ['admin', 'broker'] and filtro_agente:
        if filtro_agente == 'todos':
            fichas = db.get_enlaces_por_agente(agente_id=None)
            agente_filtrado = 'todos'
        else:
            try:
                f_id = int(filtro_agente)
                fichas = db.get_enlaces_por_agente(agente_id=f_id)
                agente_filtrado = f_id
            except:
                fichas = db.get_enlaces_por_agente(agente_id=current_user.id)
                agente_filtrado = current_user.id
    else:
        # Modo estándar para agentes: solo ven sus fichas
        fichas = db.get_enlaces_por_agente(agente_id=current_user.id)
        agente_filtrado = current_user.id

    usuarios_lista = db.get_all_usuarios() if current_user.rol in ['admin', 'broker'] else []
    
    # Obtener configuración del agente actual para prellenar
    ag_settings = db.get_agency_settings()
    agente_config = {
        'nombre': db.get_config('agente_nombre', current_user.nombre_display or current_user.usuario),
        'telefono': db.get_config('agente_telefono', ''),
        'email': db.get_config('agente_email', ''),
        'inmobiliaria': db.get_config('agente_inmobiliaria') or ag_settings.get('nombre', 'Inmobiliaria')
    }
    
    company_logo = obtener_logo_empresa()
    
    return render_template(
        'panel_fichas_agente.html',
        fichas=fichas,
        agente_config=agente_config,
        company_logo=company_logo,
        usuarios_lista=usuarios_lista,
        agente_filtrado=agente_filtrado
    )


@fichas_bp.route('/fichas/api/scrape', methods=['POST'])
@login_required
def api_scrape_url():
    """
    Scrapea en tiempo real una URL de Zonaprop, Argenprop o MercadoLibre.
    Devuelve todos los datos parseados, galería completa de fotos, bullets y descripción sanitizada.
    """
    url = (request.json.get('url') or request.form.get('url') or '').strip()
    if not url:
        return jsonify({'success': False, 'error': 'Por favor ingresá un enlace válido.'}), 400

    url_low = url.lower()
    portal = None
    if 'zonaprop.com' in url_low:
        portal = 'zonaprop'
    elif 'argenprop.com' in url_low:
        portal = 'argenprop'
    elif 'mercadolibre.com' in url_low or 'mercadopago.com' in url_low or 'articulo.mercadolibre' in url_low:
        portal = 'mercadolibre'
    else:
        return jsonify({
            'success': False,
            'error': 'El portal ingresado no es compatible. Usá enlaces de Zonaprop, Argenprop o Mercado Libre Inmuebles.'
        }), 400

    try:
        detail_data = {}
        remote_res = ScraperClient.test_inspect_property(url)
        if remote_res and remote_res.get('success') and remote_res.get('data'):
            detail_data = remote_res['data']
        elif remote_res and not remote_res.get('success'):
            return jsonify({'success': False, 'error': remote_res.get('error', 'Error extrayendo datos del portal')}), 422

        # Estructurar objeto de propiedad
        prop_raw = {
            'portal': portal,
            'url': url,
            'titulo': detail_data.get('titulo') or '',
            'precio': detail_data.get('precio') or 0,
            'moneda': detail_data.get('moneda') or 'USD',
            'expensas': detail_data.get('expensas') or 0,
            'tipo_operacion': detail_data.get('tipo_operacion') or ('alquiler' if 'alquiler' in url_low else 'venta'),
            'tipo_propiedad': detail_data.get('tipo_propiedad') or 'Departamento',
            'direccion': detail_data.get('direccion') or detail_data.get('exact_address') or '',
            'barrio': detail_data.get('barrio') or '',
            'ambientes': detail_data.get('ambientes') or 0,
            'dormitorios': detail_data.get('dormitorios') or 0,
            'banos': detail_data.get('banos') or 0,
            'm2_total': detail_data.get('m2_total') or detail_data.get('m2') or 0,
            'm2_cubiertos': detail_data.get('m2_cubiertos') or 0,
            'cocheras': detail_data.get('cocheras') or 0,
            'antiguedad': detail_data.get('antiguedad') or '',
            'orientacion': detail_data.get('orientacion') or '',
            'disposicion': detail_data.get('disposicion') or '',
            'descripcion': detail_data.get('descripcion') or '',
            'fotos': detail_data.get('fotos') or ([detail_data['foto_url']] if detail_data.get('foto_url') else []),
            'lat': detail_data.get('lat'),
            'lng': detail_data.get('lng')
        }

        # Aplicar sanitización integral de Marca Blanca Ferrari
        prop_sanitizada = sanitizar_marca_blanca(prop_raw)
        
        # Resolver coordenadas geográficas inteligentes
        from lib.geocoding import resolve_property_coordinates
        prop_sanitizada = resolve_property_coordinates(prop_sanitizada)
        
        # Preservar todas las fotos encontradas (sin recortar)
        if detail_data.get('fotos'):
            prop_sanitizada['fotos'] = detail_data['fotos']
        elif prop_sanitizada.get('lista_fotos'):
            prop_sanitizada['fotos'] = prop_sanitizada['lista_fotos']
        
        # Generar slug sugerido
        suggested_slug = generar_slug_legible(prop_sanitizada.get('titulo', ''), prop_sanitizada.get('barrio', ''), portal)
        prop_sanitizada['suggested_slug'] = suggested_slug
        prop_sanitizada['portal_origen'] = portal
        prop_sanitizada['url_origen'] = url

        return jsonify({
            'success': True,
            'propiedad': prop_sanitizada
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Error procesando el enlace: {str(e)}'
        }), 500


@fichas_bp.route('/fichas/api/guardar', methods=['POST'])
@login_required
def api_guardar_ficha():
    """
    Guarda la ficha confirmada por el agente y devuelve la URL final /ficha/<slug>.
    """
    data = request.json or request.form.to_dict()
    if not data:
        return jsonify({'success': False, 'error': 'Datos incompletos.'}), 400

    # Determinar slug final
    slug = (data.get('codigo_slug') or '').strip()
    if not slug:
        slug = generar_slug_legible(data.get('titulo', ''), data.get('barrio', ''), data.get('portal_origen', 'portal'))
    
    # Sanitizar slug a minúsculas y caracteres válidos
    slug = re.sub(r'[^a-zA-Z0-9_-]', '-', slug.lower()).strip('-')

    # Tomar datos del perfil del agente logueado
    agente_nombre = db.get_config('agente_nombre', current_user.nombre_display or current_user.usuario)
    agente_telefono = db.get_config('agente_telefono', '')
    agente_email = db.get_config('agente_email', '')
    agente_avatar = getattr(current_user, 'avatar_url', None) or '/static/img/no-photo.png'

    # Permitir overrides si el formulario los envía
    if data.get('agente_nombre_override'):
        agente_nombre = data['agente_nombre_override']
    if data.get('agente_telefono_override'):
        agente_telefono = data['agente_telefono_override']

    fotos = data.get('fotos') or []
    if isinstance(fotos, str):
        try:
            fotos = json.loads(fotos)
        except Exception:
            fotos = [fotos] if fotos else []

    datos_guardar = {
        'codigo_slug': slug,
        'portal_origen': data.get('portal_origen', 'portal'),
        'url_origen': data.get('url_origen', ''),
        'titulo': data.get('titulo', 'Propiedad Destacada'),
        'precio': float(data.get('precio') or 0),
        'moneda': data.get('moneda', 'USD'),
        'expensas': float(data.get('expensas') or 0),
        'tipo_operacion': data.get('tipo_operacion', 'venta'),
        'tipo_propiedad': data.get('tipo_propiedad', 'Departamento'),
        'direccion_mostrada': data.get('direccion_mostrada') or data.get('direccion') or '',
        'barrio': data.get('barrio', ''),
        'ambientes': int(data.get('ambientes') or 0),
        'dormitorios': int(data.get('dormitorios') or 0),
        'banos': int(data.get('banos') or 0),
        'm2_total': float(data.get('m2_total') or 0),
        'm2_cubiertos': float(data.get('m2_cubiertos') or 0),
        'cocheras': int(data.get('cocheras') or 0),
        'antiguedad': str(data.get('antiguedad') or ''),
        'orientacion': str(data.get('orientacion') or ''),
        'disposicion': str(data.get('disposicion') or ''),
        'caracteristicas_json': data.get('caracteristicas') or {},
        'descripcion': data.get('descripcion', ''),
        'fotos_json': fotos,
        'foto_portada': fotos[0] if fotos else None,
        'lat': float(data.get('lat')) if data.get('lat') else None,
        'lng': float(data.get('lng')) if data.get('lng') else None,
        'agente_nombre': agente_nombre,
        'agente_telefono': agente_telefono,
        'agente_email': agente_email,
        'agente_avatar': agente_avatar
    }

    # Resolver coordenadas antes de guardar
    from lib.geocoding import resolve_property_coordinates
    datos_guardar = resolve_property_coordinates(datos_guardar)

    try:
        db.crear_enlace_ficha(datos_guardar, current_user.id)
        final_url = f"/ficha/{slug}"
        return jsonify({
            'success': True,
            'slug': slug,
            'url': final_url,
            'full_url': request.host_url.rstrip('/') + final_url
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Error guardando ficha: {str(e)}'}), 500


@fichas_bp.route('/ficha/<path:slug>')
def ver_ficha_publica(slug):
    """
    Vista pública para el cliente final (Acceso sin login).
    Estética del Portal Cliente Ferrari, fotos completas, bullets, datos del agente y botón WhatsApp.
    Registra tracking de apertura ignorando bots de WhatsApp/redes.
    """
    clean_slug = slug.strip().lstrip('/')
    ficha = db.get_enlace_ficha_by_slug(clean_slug)
    
    if not ficha:
        return render_template('ficha_no_encontrada.html', slug=clean_slug), 404
        
    if ficha.get('esta_expirado') or not ficha.get('activo', 1):
        return render_template('ficha_expirada.html', ficha=ficha), 410

    # Auto-resolución de coordenadas si estaban ausentes o desubicadas
    from lib.geocoding import is_valid_and_coherent_coordinate, resolve_property_coordinates
    if not is_valid_and_coherent_coordinate(ficha.get('lat'), ficha.get('lng'), barrio=ficha.get('barrio', ''), direccion=ficha.get('direccion_mostrada', '')):
        resolved = resolve_property_coordinates({
            'lat': ficha.get('lat'),
            'lng': ficha.get('lng'),
            'titulo': ficha.get('titulo') or '',
            'direccion_mostrada': ficha.get('direccion_mostrada') or '',
            'barrio': ficha.get('barrio') or ''
        })
        if resolved.get('lat') and resolved.get('lng'):
            ficha['lat'] = resolved['lat']
            ficha['lng'] = resolved['lng']
            try:
                conn = db.get_db()
                conn.execute("UPDATE enlaces_fichas_clientes SET lat = ?, lng = ? WHERE id = ?", (resolved['lat'], resolved['lng'], ficha['id']))
                conn.commit()
                conn.close()
            except Exception:
                pass

    # Tracking en background (solo suma si no es bot)
    user_agent = request.headers.get('User-Agent', '')
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    db.registrar_vista_enlace(clean_slug, ip=ip, user_agent=user_agent)

    branding = db.get_branding_for_agent(ficha.get('agente_id'))
    company_logo = branding.get('logo_url')
    agency_name = branding.get('nombre')
    
    # Generar mensaje de WhatsApp prearmado
    agente_tel = re.sub(r'[^\d+]', '', ficha.get('agente_telefono') or '')
    if not agente_tel:
        agente_tel = "+5491100000000"
    elif not agente_tel.startswith('+'):
        if agente_tel.startswith('54'):
            agente_tel = '+' + agente_tel
        else:
            agente_tel = '+549' + agente_tel.lstrip('0').lstrip('15')
            
    texto_wa = f"Hola {ficha.get('agente_nombre', 'Asesor')}! Estoy viendo la propiedad '{ficha.get('titulo')}' ({ficha.get('moneda', 'USD')} {int(ficha.get('precio', 0)):,}) y me gustaría recibir más información o coordinar una visita."
    import urllib.parse
    wa_link = f"https://wa.me/{agente_tel.replace('+', '')}?text={urllib.parse.quote(texto_wa)}"

    return render_template(
        'ficha_cliente.html',
        f=ficha,
        company_logo=company_logo,
        agency_name=agency_name,
        wa_link=wa_link
    )


@fichas_bp.route('/fichas/api/eliminar/<int:ficha_id>', methods=['POST'])
@login_required
def api_eliminar_ficha(ficha_id):
    """Permite al agente eliminar una de sus fichas."""
    agente_id = None if current_user.rol == 'admin' else current_user.id
    res = db.eliminar_enlace_ficha(ficha_id, agente_id=agente_id)
    return jsonify({'success': bool(res)})


@fichas_bp.route('/fichas/api/toggle/<int:ficha_id>', methods=['POST'])
@login_required
def api_toggle_ficha(ficha_id):
    """Activa o desactiva una ficha."""
    activo = bool(request.json.get('activo', 1))
    agente_id = None if current_user.rol == 'admin' else current_user.id
    res = db.cambiar_estado_enlace(ficha_id, activo, agente_id=agente_id)
    return jsonify({'success': bool(res)})
