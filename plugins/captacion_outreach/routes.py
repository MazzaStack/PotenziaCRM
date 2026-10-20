"""
CRM Module for Scrapers Control, Properties, and Messaging/Automation Queue
Modularized as a Plugin in plugins/captacion_outreach/routes.py
"""
import os
import sys
import re
import random
import secrets
import shutil
import urllib.parse
import subprocess
from datetime import datetime, timedelta

from flask import Blueprint, request, redirect, url_for, render_template, flash, jsonify, send_file, current_app, g
from flask_login import login_required, current_user

from database import db
from lib.utils import clean_phone_argentina
from lib.gemini_service import generar_mensaje_ia
from lib.scraper_client import ScraperClient
from modules.auth import superadmin_required, privilege_required
from plugins.captacion_outreach.routes_fichas import fichas_bp

captacion_outreach_bp = Blueprint('captacion_outreach', __name__)


def _build_static_map_url(map_coords_json, width=800, height=280, zoom=13):
    """
    Builds a static OpenStreetMap image URL using marker coordinates
    captured from the Leaflet map on the client side.
    Returns a URL string or None if no valid coords are available.
    """
    import json as _json
    try:
        coords = _json.loads(map_coords_json) if map_coords_json else []
    except Exception:
        coords = []

    if not coords:
        return None

    # Filter valid numeric coordinate pairs
    valid = []
    for c in coords:
        try:
            lat = float(c[0])
            lng = float(c[1])
            valid.append((lat, lng))
        except Exception:
            continue

    if not valid:
        return None

    # Build markers string for static map
    markers = '|'.join(f"{lat},{lng},red-pushpin" for lat, lng in valid[:20])

    # Calculate center from bounding box
    lats = [c[0] for c in valid]
    lngs = [c[1] for c in valid]
    center_lat = (min(lats) + max(lats)) / 2
    center_lng = (min(lngs) + max(lngs)) / 2

    url = (
        f"https://staticmap.openstreetmap.de/staticmap.php"
        f"?center={center_lat:.6f},{center_lng:.6f}"
        f"&zoom={zoom}"
        f"&size={width}x{height}"
        f"&markers={markers}"
    )
    return url


@captacion_outreach_bp.route('/propiedades')
@login_required
@superadmin_required
def propiedades_view():
    """Lista de propiedades capturadas (Solo SuperAdmin)."""
    estado = request.args.get('estado')
    portal = request.args.get('portal')
    telefono = request.args.get('telefono')
    
    props = db.get_propiedades(estado=estado, portal=portal, telefono=telefono)
    
    # Get total stats for the counter
    stats = db.get_estadisticas()
    total_scrapeadas = stats.get('total', 0)
    
    # Tag properties in Week 2 (Improved logic for UI display)
    threshold = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    for p in props:
        p['es_semana2'] = False
        if p['estado'] == 'contactada':
            comms = db.get_comunicaciones(propiedad_id=p['id'])
            step1 = next((c for c in comms if c['paso'] == 1 and c['estado'] == 'enviada'), None)
            step2 = next((c for c in comms if c['paso'] == 2), None)
            if step1 and not step2 and step1['fecha_enviada'] < threshold:
                p['es_semana2'] = True
                
    return render_template('propiedades.html', 
                          props=props, 
                          current_estado=estado, 
                          current_portal=portal, 
                          current_telefono=telefono,
                          total_scrapeadas=total_scrapeadas)

@captacion_outreach_bp.route('/propiedad/<int:prop_id>')
@login_required
@superadmin_required
def propiedad_detalle(prop_id):
    """Detalle de una propiedad."""
    prop = db.get_propiedad(prop_id)
    if not prop:
        flash("Propiedad no encontrada", "error")
        return redirect(url_for('captacion_outreach.propiedades_view'))
    
    comms = db.get_comunicaciones(propiedad_id=prop_id)
    config = db.get_all_config()
    
    # Rematriculación: ¿Ya es contacto?
    contacto_existente = db.get_contacto_by_phone(prop.get('telefono'))
    bloqueado = db.is_blacklisted(prop.get('telefono'))
    
    return render_template('detalle.html', prop=prop, comms=comms, config=config, 
                         contacto_existente=contacto_existente, bloqueado=bloqueado)

@captacion_outreach_bp.route('/propiedad/<int:prop_id>/estado', methods=['POST'])
@login_required
@superadmin_required
def actualizar_estado(prop_id):
    """Actualizar estado de una propiedad y contar respuestas de IA test."""
    nuevo_estado = request.form.get('estado')
    notas = request.form.get('notas')
    
    # --- Tracking Real A/B Testing ---
    prop_actual = db.get_propiedad(prop_id)
    if prop_actual and prop_actual.get('estado') == 'contactada' and nuevo_estado in ['interesada', 'tasacion', 'visita', 'comprador_potencial', 'captada']:
        comms = db.get_comunicaciones(propiedad_id=prop_id)
        if comms:
            # We assume the most recent message's strategy is the one that got the response
            ultima = comms[0]
            estrategia = ultima.get('estrategia_usada')
            if estrategia:
                db.incrementar_respuesta_ia(estrategia)
                flash(f"¡Genial! Esto suma un punto a la estrategia '{estrategia}' (A/B Testing en Dashboard).", "info")
    # ---------------------------------
                
    db.update_propiedad_estado(prop_id, nuevo_estado, notas)
    flash(f"Estado actualizado a {nuevo_estado}", "success")
    return redirect(request.referrer or url_for('captacion_outreach.propiedad_detalle', prop_id=prop_id))

def procesar_busqueda_multi_zona(zona_input, tipo=None, ambientes=None, min_m2=None, max_m2=None, extras=[], dormitorios=None, min_precio=None, max_precio=None, operacion='venta', page=1, keyword='', fecha_desde=None):
    """
    Processes multi-neighborhood comma-separated search with daily freshness & hybrid auto-scrape.
    Returns (aggregated_results, desglose_zonas)
    - Preserves sequential zone order: Zone 1 first, Zone 2 second, etc.
    - Deduplicates properties by URL across bordering neighborhoods.
    - Supports fecha_desde for filtering new properties captured after search creation.
    """
    if not zona_input:
        zonas = ['']
    else:
        zonas = [z.strip() for z in zona_input.split(',') if z.strip()]

    if not zonas:
        zonas = ['']

    from database.db import verificar_y_obtener_propiedades_zona
    from lib.scraper_client import ScraperClient

    aggregated_results = []
    seen_urls = set()
    desglose_zonas = []

    for z in zonas:
        if not z:
            continue

        is_fresh_today = True
        is_new_zone = False
        zone_props = []

        # 1. Propiedades locales de cartera propia / Tokko Broker
        local_props, is_fresh_today, is_new_zone = verificar_y_obtener_propiedades_zona(
            zona=z,
            tipo_propiedad=tipo,
            tipo_operacion=operacion,
            min_precio=min_precio,
            max_precio=max_precio,
            min_m2=min_m2,
            max_m2=max_m2,
            ambientes=ambientes,
            dormitorios=dormitorios,
            keyword=keyword,
            extras=extras,
            fecha_desde=fecha_desde
        )
        if local_props:
            for p in local_props:
                p_url = p.get('url')
                if p_url and p_url in seen_urls:
                    continue
                if fecha_desde:
                    f_cap = str(p.get('fecha_captacion') or p.get('created_at') or '')
                    if not f_cap or f_cap < str(fecha_desde)[:19]:
                        continue
                if p_url:
                    seen_urls.add(p_url)
                zone_props.append(p)

        # 2. Consultar Base Centralizada de Scraping / Servidor Remoto
        try:
            filters = {
                'zona': z,
                'tipo_propiedad': tipo,
                'tipo_operacion': operacion,
                'min_precio': min_precio,
                'max_precio': max_precio,
                'ambientes': ambientes,
                'dormitorios': dormitorios
            }
            if fecha_desde:
                filters['fecha_desde'] = str(fecha_desde).strip()
                query_limit = 100
            else:
                query_limit = 50

            ext_props, total_scraped = ScraperClient.search_properties(filters=filters, limit=query_limit, offset=(page - 1) * query_limit)
            if ext_props:
                from lib.extras_matcher import coincide_extras
                for p in ext_props:
                    p_url = p.get('url') or ''
                    p_url_low = p_url.lower()
                    p_title = p.get('titulo') or ''
                    p_title_low = p_title.lower()
                    p_moneda = p.get('moneda') or 'USD'
                    p_precio = p.get('precio') or 0

                    if p_url and p_url in seen_urls:
                        continue

                    # 1. Operation integrity check
                    if operacion == 'venta':
                        if any(k in p_url_low for k in ['-alquiler-', '/alquiler/', '_alquiler_']) or p_title_low.startswith(('alquiler ', 'alquilo ', 'alquila ', 'en alquiler ')):
                            continue
                        if p_moneda == 'ARS' and p_precio < 10000000:
                            continue
                    elif operacion == 'alquiler':
                        if any(k in p_url_low for k in ['-venta-', '/venta/', '_venta_']) or p_title_low.startswith(('venta ', 'vendo ', 'vende ', 'en venta ')):
                            continue

                    # 2. Property type integrity check
                    if tipo:
                        t_list = tipo if isinstance(tipo, list) else [tipo]
                        t_clean = [t.lower().strip('{').strip('}') for t in t_list]
                        if 'casa' in t_clean:
                            if any(sub in p_url_low for sub in ('departamento.mercadolibre', 'oficina.mercadolibre', 'local.mercadolibre', 'inmueble.mercadolibre')):
                                continue
                            if p_title_low.startswith(('departamento ', 'depto ', 'semipiso ', 'monoambiente ', 'oficina ', 'local ', 'cochera ')):
                                continue
                        elif 'departamento' in t_clean:
                            if any(sub in p_url_low for sub in ('casa.mercadolibre', 'oficina.mercadolibre', 'terreno.mercadolibre', 'inmueble.mercadolibre')):
                                continue
                            if p_title_low.startswith(('casa ', 'chalet ', 'triplex ', 'terreno ', 'lote ', 'oficina ', 'local ')):
                                continue

                    # 3. Extras filter (cochera, patio, etc.)
                    if extras and not coincide_extras(p, extras):
                        continue

                    # 4. Strict Price Bounds Check
                    if min_precio is not None and str(min_precio).strip() != '':
                        try:
                            if float(p_precio) < float(min_precio):
                                continue
                        except:
                            pass
                    if max_precio is not None and str(max_precio).strip() != '':
                        try:
                            if float(p_precio) > float(max_precio):
                                continue
                        except:
                            pass

                    # 5. Strict m2 Bounds Check
                    p_m2 = p.get('m2_total') or p.get('m2_cubiertos') or p.get('m2') or 0
                    if min_m2 is not None and str(min_m2).strip() != '':
                        try:
                            if float(p_m2) < float(min_m2):
                                continue
                        except:
                            pass
                    if max_m2 is not None and str(max_m2).strip() != '':
                        try:
                            if float(p_m2) > float(max_m2):
                                continue
                        except:
                            pass

                    # 6. Bedrooms Check
                    if dormitorios is not None and str(dormitorios).strip() != '' and p.get('dormitorios') is not None:
                        try:
                            if int(p.get('dormitorios')) != int(dormitorios):
                                continue
                        except:
                            pass

                    if p_url:
                        seen_urls.add(p_url)
                    fotos_p = p.get('fotos') or ([p.get('foto_portada')] if p.get('foto_portada') else [])
                    zone_props.append({
                        'id': p.get('id'),
                        'portal': p.get('portal'),
                        'url': p.get('url'),
                        'titulo': p.get('titulo'),
                        'precio': p.get('precio', 0),
                        'moneda': p.get('moneda', 'USD'),
                        'direccion': p.get('direccion') or z,
                        'barrio': p.get('barrio') or z,
                        'ambientes': p.get('ambientes'),
                        'dormitorios': p.get('dormitorios'),
                        'm2': p.get('m2_total') or p.get('m2_cubiertos') or 0,
                        'm2_total': p.get('m2_total') or 0,
                        'm2_cubiertos': p.get('m2_cubiertos'),
                        'cocheras': p.get('cocheras'),
                        'descripcion': p.get('descripcion', ''),
                        'foto': p.get('foto_portada') or (fotos_p[0] if fotos_p else None),
                        'fotos': fotos_p,
                        'lat': p.get('lat'),
                        'lng': p.get('lng'),
                        'dias_publicado': p.get('dias_publicado'),
                        'fecha_publicacion_portal': p.get('fecha_publicacion_portal'),
                        'primera_deteccion': p.get('primera_deteccion'),
                        'precio_anterior': p.get('precio_anterior'),
                        'fecha_cambio_precio': p.get('fecha_cambio_precio'),
                        'fecha_captacion': p.get('fecha_captacion')
                    })
        except Exception as e:
            print(f"[MultiZona] Error consultando Scraper Service para '{z}': {e}")

        # Re-sort zone properties: Tokko -> Argenprop -> MercadoLibre -> Zonaprop
        zone_props.sort(key=lambda item: 0 if 'tokko' in str(item.get('portal', '')).lower() else (1 if 'argenprop' in str(item.get('portal', '')).lower() else (2 if ('mercadolibre' in str(item.get('portal', '')).lower() or 'ml' in str(item.get('portal', '')).lower()) else 3)))

        # Sanitize and validate coordinates for geographical coherence with zone
        from lib.geocoding import resolve_property_coordinates
        for p in zone_props:
            if not p.get('zona'):
                p['zona'] = z
            resolve_property_coordinates(p)

        desglose_zonas.append({
            'zona': z,
            'count': len(zone_props),
            'fresco': is_fresh_today,
            'nuevo': is_new_zone
        })

        aggregated_results.extend(zone_props)

    # Global sort across all neighborhoods: 1. Argenprop, 2. MercadoLibre, 3. Zonaprop
    def portal_rank(item):
        p = str(item.get('portal', '')).lower()
        if 'argenprop' in p:
            return 1
        if 'mercadolibre' in p or 'ml' in p:
            return 2
        if 'zonaprop' in p:
            return 3
        return 4

    aggregated_results.sort(key=portal_rank)

    return aggregated_results, desglose_zonas


@captacion_outreach_bp.route('/compradores', methods=['GET', 'POST'])
@login_required
@privilege_required('menu_item', 'buscador_ventas')
def buscador_compradores():
    """Buscador avanzado para encontrar propiedades para compradores."""
    if request.method == 'POST':
        zona = request.form.get('zona')
        tipo = request.form.getlist('tipo')
        if not tipo:
            tipo = ['departamento']
        
        ambientes = [int(a) for a in request.form.getlist('ambientes') if a.isdigit()]
        if not ambientes:
            ambientes = None
        
        dormitorios = request.form.get('dormitorios')
        dormitorios = int(dormitorios) if dormitorios and dormitorios.isdigit() else None
        
        min_precio = request.form.get('min_precio')
        min_precio = float(min_precio) if min_precio else None
        max_precio = request.form.get('max_precio')
        max_precio = float(max_precio) if max_precio else None
        
        min_m2 = request.form.get('min_m2')
        min_m2 = float(min_m2) if min_m2 else None
        max_m2 = request.form.get('max_m2')
        max_m2 = float(max_m2) if max_m2 else None
        
        extras = request.form.getlist('extras')
        page = request.form.get('page', 1, type=int)
        keyword = request.form.get('keyword', '')
        
        results = []
        desglose_zonas = []
        
        # 1. Prioridad: Buscar en nuestras propiedades locales de Tokko Broker
        if page == 1:
            try:
                from plugins.tokko.db_tokko import get_propiedades_cartera
                tokko_props, _ = get_propiedades_cartera(
                    tipo_operacion='venta',
                    tipo_propiedad=tipo,
                    precio_min=min_precio,
                    precio_max=max_precio,
                    zona=zona,
                    page=1,
                    per_page=50
                )
                from lib.extras_matcher import coincide_extras
                for tp in tokko_props:
                    fotos_list = []
                    if tp.get("fotos_json"):
                        try:
                            fotos_list = json.loads(tp["fotos_json"])
                        except:
                            pass
                    normalized = {
                        'titulo': f"[Propia] {tp.get('titulo') or ''}",
                        'foto': tp.get('foto_principal') or (fotos_list[0] if fotos_list else ''),
                        'fotos': fotos_list,
                        'portal': 'tokko',
                        'precio': tp.get('precio', 0),
                        'moneda': tp.get('moneda', 'USD'),
                        'direccion': tp.get('direccion') or tp.get('barrio') or zona,
                        'barrio': tp.get('barrio') or '',
                        'ambientes': tp.get('ambientes') or 0,
                        'cocheras': tp.get('cocheras') or tp.get('parking_lots'),
                        'm2': tp.get('superficie_total') or tp.get('superficie_cubierta') or 0,
                        'url': tp.get('url_ficha') or '',
                        'lat': tp.get('lat') or tp.get('geo_lat') or 0,
                        'lng': tp.get('lon') or tp.get('geo_long') or 0,
                        'descripcion': tp.get('descripcion') or ''
                    }
                    if extras and not coincide_extras(normalized, extras):
                        continue
                    results.append(normalized)
            except Exception as e:
                print(f"[Buscador Compradores] Error al buscar en Tokko local: {e}")
        
        # 2. Multi-Zona Hybrid Search (Instant local DB for today's scraped zones + auto-scrape for new/unscraped today)
        try:
            external_results, desglose_zonas = procesar_busqueda_multi_zona(
                zona_input=zona,
                tipo=tipo,
                ambientes=ambientes,
                min_m2=min_m2,
                max_m2=max_m2,
                extras=extras,
                dormitorios=dormitorios,
                min_precio=min_precio,
                max_precio=max_precio,
                operacion='venta',
                page=page,
                keyword=keyword
            )
            results.extend(external_results)
        except Exception as e:
            print(f"[Buscador Compradores] Error al buscar multi zona: {e}")
        
        # Apply strict portal rank sorting: Tokko -> Argenprop -> MercadoLibre -> Zonaprop
        def final_portal_rank(item):
            p = str(item.get('portal', '')).lower()
            if 'tokko' in p: return 0
            if 'argenprop' in p: return 1
            if 'mercadolibre' in p or 'ml' in p: return 2
            if 'zonaprop' in p: return 3
            return 4

        results.sort(key=final_portal_rank)

        return render_template('buscador_compradores.html', 
                             results=results, 
                             zona=zona, 
                             tipo=tipo, 
                             ambientes=ambientes,
                             dormitorios=dormitorios,
                             min_m2=min_m2, 
                             max_m2=max_m2,
                             min_precio=min_precio,
                             max_precio=max_precio,
                             selected_extras=extras,
                             current_page=page,
                             keyword=keyword,
                             desglose_zonas=desglose_zonas,
                             contactos=db.get_contactos())
                             
    return render_template('buscador_compradores.html', contactos=db.get_contactos())


@captacion_outreach_bp.route('/alquileres', methods=['GET', 'POST'])
@login_required
@privilege_required('menu_item', 'buscador_alquileres')
def buscador_alquileres():
    """Buscador avanzado para encontrar alquileres."""
    if request.method == 'POST':
        zona = request.form.get('zona')
        tipo = request.form.getlist('tipo')
        if not tipo:
            tipo = ['departamento']
            
        ambientes = [int(a) for a in request.form.getlist('ambientes') if a.isdigit()]
        if not ambientes:
            ambientes = None
        
        dormitorios = request.form.get('dormitorios')
        dormitorios = int(dormitorios) if dormitorios and dormitorios.isdigit() else None
        
        min_precio = request.form.get('min_precio')
        min_precio = float(min_precio) if min_precio else None
        max_precio = request.form.get('max_precio')
        max_precio = float(max_precio) if max_precio else None
        
        min_m2 = request.form.get('min_m2')
        min_m2 = float(min_m2) if min_m2 else None
        max_m2 = request.form.get('max_m2')
        max_m2 = float(max_m2) if max_m2 else None
        
        extras = request.form.getlist('extras')
        page = request.form.get('page', 1, type=int)
        keyword = request.form.get('keyword', '')
        
        results = []
        desglose_zonas = []
        
        # 1. Prioridad: Buscar en nuestras propiedades locales de Tokko Broker
        if page == 1:
            try:
                from plugins.tokko.db_tokko import get_propiedades_cartera
                tokko_props, _ = get_propiedades_cartera(
                    tipo_operacion='alquiler',
                    tipo_propiedad=tipo,
                    precio_min=min_precio,
                    precio_max=max_precio,
                    zona=zona,
                    page=1,
                    per_page=50
                )
                from lib.extras_matcher import coincide_extras
                for tp in tokko_props:
                    fotos_list = []
                    if tp.get("fotos_json"):
                        try:
                            fotos_list = json.loads(tp["fotos_json"])
                        except:
                            pass
                    normalized = {
                        'titulo': f"[Propia] {tp.get('titulo') or ''}",
                        'foto': tp.get('foto_principal') or (fotos_list[0] if fotos_list else ''),
                        'fotos': fotos_list,
                        'portal': 'tokko',
                        'precio': tp.get('precio', 0),
                        'moneda': tp.get('moneda', 'ARS'),
                        'direccion': tp.get('direccion') or tp.get('barrio') or zona,
                        'barrio': tp.get('barrio') or '',
                        'ambientes': tp.get('ambientes') or 0,
                        'cocheras': tp.get('cocheras') or tp.get('parking_lots'),
                        'm2': tp.get('superficie_total') or tp.get('superficie_cubierta') or 0,
                        'url': tp.get('url_ficha') or '',
                        'lat': tp.get('lat') or tp.get('geo_lat') or 0,
                        'lng': tp.get('lon') or tp.get('geo_long') or 0,
                        'descripcion': tp.get('descripcion') or ''
                    }
                    if extras and not coincide_extras(normalized, extras):
                        continue
                    results.append(normalized)
            except Exception as e:
                print(f"[Buscador Alquileres] Error al buscar en Tokko local: {e}")
        
        # 2. Multi-Zona Hybrid Search (Instant local DB for today's scraped zones + auto-scrape for new/unscraped today)
        try:
            external_results, desglose_zonas = procesar_busqueda_multi_zona(
                zona_input=zona,
                tipo=tipo,
                ambientes=ambientes,
                min_m2=min_m2,
                max_m2=max_m2,
                extras=extras,
                dormitorios=dormitorios,
                min_precio=min_precio,
                max_precio=max_precio,
                operacion='alquiler',
                page=page,
                keyword=keyword
            )
            results.extend(external_results)
        except Exception as e:
            print(f"[Buscador Alquileres] Error al buscar multi zona: {e}")
        
        # Apply strict portal rank sorting: Tokko -> Argenprop -> MercadoLibre -> Zonaprop
        def final_portal_rank(item):
            p = str(item.get('portal', '')).lower()
            if 'tokko' in p: return 0
            if 'argenprop' in p: return 1
            if 'mercadolibre' in p or 'ml' in p: return 2
            if 'zonaprop' in p: return 3
            return 4

        results.sort(key=final_portal_rank)

        return render_template('buscador_alquileres.html', 
                             results=results, 
                             zona=zona, 
                             tipo=tipo, 
                             ambientes=ambientes,
                             dormitorios=dormitorios,
                             min_m2=min_m2, 
                             max_m2=max_m2,
                             min_precio=min_precio,
                             max_precio=max_precio,
                             selected_extras=extras,
                             current_page=page,
                             keyword=keyword,
                             desglose_zonas=desglose_zonas,
                             contactos=db.get_contactos())
                             
    return render_template('buscador_alquileres.html', contactos=db.get_contactos())

@captacion_outreach_bp.route('/toggle_ia_provider', methods=['POST'])
@login_required
def toggle_ia_provider():
    """Toggles the primary AI provider between desactivada, gemini, and groq."""
    current = db.get_config('ia_provider_primario', 'desactivada')
    if current == 'desactivada':
        new_provider = 'gemini'
    elif current == 'gemini':
        new_provider = 'groq'
    else:
        new_provider = 'desactivada'
    db.set_config('ia_provider_primario', new_provider)
    return jsonify({'success': True, 'new_provider': new_provider})

def resolve_details_ondemand(propiedades):
    """Fetches details on-demand in parallel with a strict timeout to prevent blocking the web server."""
    if not propiedades:
        return propiedades

    from lib.scraper_client import ScraperClient

    def _fetch_single(p):
        url = p.get('url')
        if not url:
            return
        
        needs_details = (
            not p.get('fotos') or len(p.get('fotos')) <= 1 or
            not p.get('descripcion') or p.get('descripcion') == "Detalles disponibles en el portal..." or
            len(p.get('descripcion', '')) < 20
        )
        if needs_details:
            try:
                res = ScraperClient.test_inspect_property(url)
                if res and res.get('success') and res.get('data'):
                    p.update(res['data'])
            except Exception as e:
                print(f"[On-Demand] Error fetching details via ScraperClient: {e}")

    # Process all selected properties concurrently with a max timeout of 6 seconds
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(propiedades))) as executor:
        futures = [executor.submit(_fetch_single, p) for p in propiedades]
        concurrent.futures.wait(futures, timeout=6.0)

    return propiedades

@captacion_outreach_bp.route('/compradores/reporte', methods=['POST'])
@login_required
def generar_reporte_comprador():
    """Genera la vista de reporte para el cliente comprador."""
    import json
    selected_data_json = request.form.getlist('selected_data')
    zona = request.form.get('cliente_zona')
    tipo = request.form.get('cliente_tipo')
    map_coords_json = request.form.get('map_coords', '[]')  # coordinates from Leaflet markers
    
    from lib.gemini_service import resumir_propiedad_ia
    propiedades = []
    for p_json in selected_data_json:
        try:
            p = json.loads(p_json)
            propiedades.append(p)
        except:
            continue
            
    # Fetch Argenprop details on-demand
    resolve_details_ondemand(propiedades)
    
    # Real-time Multi-Proxy Verification (Quorum 1 of 3)
    try:
        from lib.link_checker import verificar_lote_propiedades
        urls_to_check = [p.get('url') for p in propiedades if p.get('url')]
        if urls_to_check:
            status_map = verificar_lote_propiedades(urls_to_check)
            initial_count = len(propiedades)
            propiedades = [p for p in propiedades if status_map.get(p.get('url'), True)]
            removed_count = initial_count - len(propiedades)
            if removed_count > 0:
                flash(f"Se excluyeron {removed_count} propiedad(es) que fueron dadas de baja en el portal recientemente.", "warning")
    except Exception as e:
        print(f"[ReporteComprador] Error en verificación multi-proxy: {e}")
    
    # Process photos and summaries after fetching details
    for p in propiedades:
        fotos_raw = p.get('fotos') or []
        foto_portada = p.get('foto') or (fotos_raw[0] if fotos_raw else None)
        if foto_portada and foto_portada not in fotos_raw:
            fotos_raw = [foto_portada] + fotos_raw
        elif foto_portada and fotos_raw and fotos_raw[0] != foto_portada:
            fotos_raw = [foto_portada] + [f for f in fotos_raw if f != foto_portada]
        resto = [f for f in fotos_raw[1:] if f]
        random.shuffle(resto)
        p['fotos'] = ([foto_portada] if foto_portada else []) + resto[:5]
        
        # Resumen IA
        provider = db.get_config('ia_provider_primario', 'desactivada')
        if provider == 'desactivada':
            desc = p.get('descripcion', '')
            if desc:
                cutoff = int(len(desc) * 0.75)
                p['resumen_ia'] = desc[:cutoff] + ("..." if len(desc) > cutoff else "")
            else:
                p['resumen_ia'] = "Sin descripción disponible."
        else:
            res = resumir_propiedad_ia(p.get('titulo', ''), p.get('descripcion', ''))
            if isinstance(res, dict):
                p['titulo'] = res.get('nuevo_titulo', p.get('titulo', ''))
                p['resumen_ia'] = res.get('resumen_ejecutivo', '')
            else:
                p['resumen_ia'] = res
        
    if not propiedades:
        flash("No seleccionaste ninguna propiedad para el reporte", "warning")
        return redirect(url_for('captacion_outreach.buscador_compradores'))
    
    # ── Generar URL de mapa estático con los marcadores capturados ──
    map_url = _build_static_map_url(map_coords_json)
    
    import uuid
    import os
    report_id = str(uuid.uuid4())[:8]
    os.makedirs(os.path.join('static', 'reports'), exist_ok=True)
    report_data = {
        'props': propiedades,
        'zona': zona,
        'tipo': tipo,
        'map_url': map_url,
        'modalidad': 'venta'
    }
    with open(os.path.join('static', 'reports', f"{report_id}.json"), 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=4)
        
    return redirect(url_for('captacion_outreach.ver_reporte_compartido', report_id=report_id))

@captacion_outreach_bp.route('/alquileres/reporte', methods=['POST'])
@login_required
def generar_reporte_alquiler():
    """Genera la vista de reporte para alquileres."""
    import json
    selected_data_json = request.form.getlist('selected_data')
    zona = request.form.get('cliente_zona')
    tipo = request.form.get('cliente_tipo')
    map_coords_json = request.form.get('map_coords', '[]')  # coordinates from Leaflet markers
    
    from lib.gemini_service import resumir_propiedad_ia
    propiedades = []
    for p_json in selected_data_json:
        try:
            p = json.loads(p_json)
            propiedades.append(p)
        except:
            continue
            
    # Fetch Argenprop details on-demand
    resolve_details_ondemand(propiedades)
    
    # Process photos and summaries after fetching details
    for p in propiedades:
        fotos_raw = p.get('fotos') or []
        foto_portada = p.get('foto') or (fotos_raw[0] if fotos_raw else None)
        if foto_portada and foto_portada not in fotos_raw:
            fotos_raw = [foto_portada] + fotos_raw
        elif foto_portada and fotos_raw and fotos_raw[0] != foto_portada:
            fotos_raw = [foto_portada] + [f for f in fotos_raw if f != foto_portada]
        resto = [f for f in fotos_raw[1:] if f]
        random.shuffle(resto)
        p['fotos'] = ([foto_portada] if foto_portada else []) + resto[:5]
        
        # Resumen IA
        provider = db.get_config('ia_provider_primario', 'desactivada')
        if provider == 'desactivada':
            desc = p.get('descripcion', '')
            if desc:
                cutoff = int(len(desc) * 0.75)
                p['resumen_ia'] = desc[:cutoff] + ("..." if len(desc) > cutoff else "")
            else:
                p['resumen_ia'] = "Sin descripción disponible."
        else:
            res = resumir_propiedad_ia(p.get('titulo', ''), p.get('descripcion', ''))
            if isinstance(res, dict):
                p['titulo'] = res.get('nuevo_titulo', p.get('titulo', ''))
                p['resumen_ia'] = res.get('resumen_ejecutivo', '')
            else:
                p['resumen_ia'] = res
         
    if not propiedades:
        flash("No seleccionaste ninguna propiedad para el reporte", "warning")
        return redirect(url_for('captacion_outreach.buscador_alquileres'))
    
    # ── Generar URL de mapa estático con los marcadores capturados ──
    map_url = _build_static_map_url(map_coords_json)
    
    import uuid
    import os
    report_id = str(uuid.uuid4())[:8]
    os.makedirs(os.path.join('static', 'reports'), exist_ok=True)
    report_data = {
        'props': propiedades,
        'zona': zona,
        'tipo': tipo,
        'map_url': map_url,
        'modalidad': 'alquiler'
    }
    with open(os.path.join('static', 'reports', f"{report_id}.json"), 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=4)
        
    return redirect(url_for('captacion_outreach.ver_reporte_compartido', report_id=report_id))

@captacion_outreach_bp.route('/reporte/compartir/<report_id>', methods=['GET'])
def ver_reporte_compartido(report_id):
    """Muestra el reporte guardado para compartir digitalmente (acceso público sin login)."""
    import os
    import json
    report_file = os.path.join('static', 'reports', f"{report_id}.json")
    if not os.path.exists(report_file):
        flash("El reporte no existe o ha expirado.", "danger")
        return redirect(url_for('captacion_outreach.buscador_compradores'))
        
    try:
        with open(report_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return render_template('reporte_comprador.html', 
                               props=data.get('props', []), 
                               zona=data.get('zona', ''), 
                               tipo=data.get('tipo', ''), 
                               map_url=data.get('map_url'),
                               modalidad=data.get('modalidad', 'venta'))
    except Exception as e:
        print(f"Error cargando reporte compartido {report_id}: {e}")
        flash("Error al cargar el reporte.", "danger")
        return redirect(url_for('captacion_outreach.buscador_compradores'))

# ==========================================
# PORTALES TEMPORALES LIVE ROUTES (15 DÍAS)
# ==========================================

@captacion_outreach_bp.route('/portaltemp/crear', methods=['POST'])
@login_required
@privilege_required('menu_item', 'portales_temporales')
def crear_portal_temporal_route():
    """Generates a 15-day live temporary customer portal with selected properties in HD."""
    import json
    import re
    selected_data_json = request.form.getlist('selected_data')
    titulo_portal = request.form.get('titulo_portal') or request.form.get('nombre_seleccion') or 'Selección Exclusiva de Propiedades'
    zona = request.form.get('cliente_zona') or request.form.get('zona') or ''
    tipo = request.form.get('cliente_tipo') or request.form.get('tipo') or 'departamento'
    modalidad = request.form.get('modalidad') or 'venta'
    cliente_id = request.form.get('cliente_id', type=int)

    propiedades = []
    for p_json in selected_data_json:
        try:
            p = json.loads(p_json)
            propiedades.append(p)
        except Exception:
            continue

    if not propiedades:
        flash("Debés seleccionar al menos una propiedad para crear el portal temporal.", "warning")
        return redirect(request.referrer or url_for('captacion_outreach.buscador_compradores'))

    # Fetch on-demand HD details and full photo galleries
    resolve_details_ondemand(propiedades)

    # Process and sanitize HD photos
    for p in propiedades:
        fotos_raw = p.get('fotos') or []
        foto_portada = p.get('foto') or (fotos_raw[0] if fotos_raw else None)
        if foto_portada and foto_portada not in fotos_raw:
            fotos_raw = [foto_portada] + fotos_raw
        elif foto_portada and fotos_raw and fotos_raw[0] != foto_portada:
            fotos_raw = [foto_portada] + [f for f in fotos_raw if f != foto_portada]
        
        # Upgrade photos to HD where applicable
        hd_photos = []
        for f in fotos_raw:
            if not f or 'unsplash.com' in f: continue
            # For Argenprop: upgrade _small / _u_small to _medium / _u_medium (do NOT strip suffix as Argenprop requires it)
            f_clean = re.sub(r'_small\.(jpg|jpeg|png|webp)', r'_medium.\1', f)
            f_clean = re.sub(r'_u_small\.(jpg|jpeg|png|webp)', r'_u_medium.\1', f_clean)
            # Upgrade MercadoLibre thumbnails -V to -O
            f_clean = re.sub(r'-V\.(jpg|jpeg|png|webp)', r'-O.\1', f_clean)
            if f_clean not in hd_photos:
                hd_photos.append(f_clean)
        
        p['fotos'] = hd_photos if hd_photos else ([foto_portada] if (foto_portada and 'unsplash.com' not in foto_portada) else [])
        p['foto'] = hd_photos[0] if hd_photos else (foto_portada if (foto_portada and 'unsplash.com' not in foto_portada) else None)

    # Agent info
    agente_nombre = db.get_config('agente_nombre') or current_user.nombre_display or current_user.usuario
    agente_tel = db.get_config('agente_telefono') or ''
    agente_email = db.get_config('agente_email') or ''

    datos_portal = {
        'titulo': titulo_portal,
        'propiedades': propiedades,
        'tipo_operacion': modalidad,
        'zona': zona,
        'cliente_id': cliente_id,
        'agente_nombre': agente_nombre,
        'agente_telefono': agente_tel,
        'agente_email': agente_email,
        'agente_avatar': ''
    }

    resultado = db.crear_portal_temporal(datos_portal, agente_id=current_user.id)
    slug = resultado.get('codigo_slug')
    
    flash(f"¡Portal Temporal Live creado exitosamente! Vigente por 15 días hasta {resultado.get('expires_at')[:10]}.", "success")
    return redirect(url_for('captacion_outreach.ver_portal_temporal_publico', slug=slug))

def extraer_propiedad_desde_url(url, tipo_operacion_hint='venta', live_prober=None):
    """
    Extracts full property data from a single MercadoLibre, Argenprop, or Zonaprop URL.
    Returns a standardized dictionary ready for Portales Temporales Live.
    """
    if not url or not isinstance(url, str):
        return None
        
    url = url.strip()
    url_low = url.lower()
    
    # 1. Identify portal
    portal = None
    if 'mercadolibre.com' in url_low or 'articulo.mercadolibre' in url_low or 'departamento.mercadolibre' in url_low or 'inmueble.mercadolibre' in url_low:
        portal = 'mercadolibre'
    elif 'argenprop.com' in url_low:
        portal = 'argenprop'
    elif 'zonaprop.com' in url_low:
        portal = 'zonaprop'
    else:
        return None

    detail_data = {}
    try:
        from lib.scraper_client import ScraperClient
        res = ScraperClient.test_inspect_property(url)
        if res and res.get('success') and res.get('data'):
            detail_data = res['data']
    except Exception as e:
        print(f"[ExtraerURL] Error extrayendo {portal} para {url} via ScraperClient: {e}")
        detail_data = {}

    if not detail_data or not isinstance(detail_data, dict):
        detail_data = {}

    # Extract / format fields
    titulo = detail_data.get('titulo') or ''
    if not titulo:
        # Fallback title from URL
        slug_part = url.split('/')[-1].split('?')[0].replace('.html', '').replace('-', ' ').title()
        titulo = slug_part if len(slug_part) > 5 else f"Propiedad en {portal.capitalize()}"

    # Operation type
    tipo_op = detail_data.get('tipo_operacion') or tipo_operacion_hint or 'venta'
    if 'alquiler' in url_low:
        tipo_op = 'alquiler'
    elif 'venta' in url_low:
        tipo_op = 'venta'

    # Property type
    tipo_prop = detail_data.get('tipo_propiedad') or 'Departamento'
    for tp in ['departamento', 'casa', 'ph', 'terreno', 'lote', 'oficina', 'local', 'cochera']:
        if tp in url_low or tp in titulo.lower():
            tipo_prop = tp.capitalize()
            break

    # Photos processing (HD)
    fotos_raw = detail_data.get('fotos') or []
    foto_portada = detail_data.get('foto_url') or detail_data.get('foto') or (fotos_raw[0] if fotos_raw else None)
    if foto_portada and foto_portada not in fotos_raw:
        fotos_raw = [foto_portada] + fotos_raw
    elif foto_portada and fotos_raw and fotos_raw[0] != foto_portada:
        fotos_raw = [foto_portada] + [f for f in fotos_raw if f != foto_portada]

    hd_photos = []
    for f in fotos_raw:
        if not f or 'unsplash.com' in f or 'data:image' in f:
            continue
        # Upgrade Argenprop
        f_clean = re.sub(r'_small\.(jpg|jpeg|png|webp)', r'_medium.\1', f)
        f_clean = re.sub(r'_u_small\.(jpg|jpeg|png|webp)', r'_u_medium.\1', f_clean)
        # Upgrade ML
        f_clean = re.sub(r'-V\.(jpg|jpeg|png|webp)', r'-O.\1', f_clean)
        f_clean = re.sub(r'-I\.(jpg|jpeg|png|webp)', r'-O.\1', f_clean)
        if f_clean not in hd_photos:
            hd_photos.append(f_clean)

    foto_final = hd_photos[0] if hd_photos else foto_portada

    # Resumen IA / descripción
    desc = detail_data.get('descripcion') or ""
    resumen_ia = ""
    try:
        provider = db.get_config('ia_provider_primario', 'desactivada')
        if provider != 'desactivada':
            from lib.gemini_service import resumir_propiedad_ia
            res = resumir_propiedad_ia(titulo, desc)
            if isinstance(res, dict):
                titulo = res.get('nuevo_titulo', titulo)
                resumen_ia = res.get('resumen_ejecutivo', '')
            elif isinstance(res, str):
                resumen_ia = res
    except Exception:
        pass

    if not resumen_ia:
        if desc:
            cutoff = int(len(desc) * 0.75)
            resumen_ia = desc[:cutoff] + ("..." if len(desc) > cutoff else "")
        else:
            resumen_ia = "Detalles disponibles en el portal oficial."

    m2_tot = detail_data.get('m2_total') or detail_data.get('m2')
    m2_cub = detail_data.get('m2_cubiertos') or m2_tot

    propiedad = {
        'portal': portal,
        'url': url,
        'titulo': titulo,
        'precio': float(detail_data.get('precio') or 0),
        'moneda': detail_data.get('moneda') or 'USD',
        'expensas': float(detail_data.get('expensas') or 0),
        'direccion': detail_data.get('direccion') or '',
        'barrio': detail_data.get('barrio') or detail_data.get('direccion') or '',
        'tipo_propiedad': tipo_prop,
        'tipo_operacion': tipo_op,
        'm2_total': m2_tot,
        'm2_cubiertos': m2_cub,
        'm2': m2_tot,
        'ambientes': detail_data.get('ambientes'),
        'dormitorios': detail_data.get('dormitorios'),
        'banos': detail_data.get('banos'),
        'toilettes': detail_data.get('toilettes'),
        'cocheras': detail_data.get('cocheras'),
        'antiguedad': detail_data.get('antiguedad'),
        'orientacion': detail_data.get('orientacion'),
        'disposicion': detail_data.get('disposicion'),
        'estado_conservacion': detail_data.get('estado_conservacion'),
        'foto': foto_final,
        'foto_url': foto_final,
        'fotos': hd_photos if hd_photos else ([foto_final] if foto_final else []),
        'descripcion': desc,
        'resumen_ia': resumen_ia,
        'lat': detail_data.get('lat'),
        'lng': detail_data.get('lng'),
        'telefono': detail_data.get('telefono') or '',
        'nombre_contacto': detail_data.get('nombre_contacto') or ''
    }

    # Resolver coordenadas inteligentes y descartar defaults absurdos de portales
    try:
        from lib.geocoding import resolve_property_coordinates
        propiedad = resolve_property_coordinates(propiedad)
    except Exception as _e_geo:
        print(f"[ExtraerURL] Error resolviendo geocodificación: {_e_geo}")

    return propiedad

def _es_usuario_oficina_portal(user):
    """Checks if the user belongs to the single office designated for the Client Portal."""
    if not user or not user.is_authenticated:
        return False
    if user.usuario == 'GermanMazza':
        return True
    if not getattr(user, 'oficina_id', None):
        return False
    ofi = db.get_oficina_by_id(user.oficina_id)
    return bool(ofi and ofi.get('es_portal_clientes') == 1)

@captacion_outreach_bp.route('/portaltemp/crear-desde-links', methods=['POST'])
@login_required
@privilege_required('menu_item', 'portales_temporales')
def crear_portal_desde_links_route():
    """
    Creates a temporary live portal by parsing up to 6 MercadoLibre, Argenprop, or Zonaprop URLs.
    Extracts all details & HD photos in parallel.
    """
    is_json = request.is_json
    import concurrent.futures

    # Check if JSON or Form
    if is_json:
        data = request.get_json() or {}
        raw_links = data.get('links') or []
        titulo_portal = data.get('titulo') or 'Selección de Propiedades'
        tipo_op = data.get('tipo_operacion') or 'venta'
        zona = data.get('zona') or ''
        cliente_id = data.get('cliente_id')
        if cliente_id:
            try: cliente_id = int(cliente_id)
            except: cliente_id = None
    else:
        raw_links = request.form.getlist('links')
        if not raw_links or (len(raw_links) == 1 and ('\n' in (raw_links[0] or '') or ',' in (raw_links[0] or ''))):
            raw_text = request.form.get('links_text') or (raw_links[0] if raw_links else '') or ''
            raw_links = [l.strip() for l in re.split(r'[\r\n\s,]+', raw_text) if l.strip()]
        titulo_portal = request.form.get('titulo') or request.form.get('titulo_portal') or 'Selección de Propiedades'
        tipo_op = request.form.get('tipo_operacion') or 'venta'
        zona = request.form.get('zona') or ''
        cliente_id = request.form.get('cliente_id', type=int)

    # Clean and filter URLs (up to 6)
    valid_links = []
    for l in raw_links:
        if not l or not isinstance(l, str): continue
        l_clean = l.strip()
        if not l_clean.startswith('http'):
            continue
        if any(dom in l_clean.lower() for dom in ['mercadolibre', 'argenprop', 'zonaprop']):
            if l_clean not in valid_links:
                valid_links.append(l_clean)

    if not valid_links:
        msg = "Debés ingresar al menos 1 enlace válido de MercadoLibre, Argenprop o Zonaprop."
        if is_json:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, "warning")
        return redirect(url_for('captacion_outreach.panel_portales_temporales'))

    # Limit to maximum 6 links
    valid_links = valid_links[:6]

    propiedades = []
    errors = []

    def _fetch(url):
        try:
            prop = extraer_propiedad_desde_url(url, tipo_operacion_hint=tipo_op)
            return url, prop, None
        except Exception as ex:
            return url, None, str(ex)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(valid_links))) as executor:
        futures = [executor.submit(_fetch, u) for u in valid_links]
        for f in concurrent.futures.as_completed(futures):
            u, prop, err = f.result()
            if prop:
                propiedades.append(prop)
            else:
                errors.append({'url': u, 'error': err or 'No se pudo extraer la propiedad.'})

    if not propiedades:
        msg = "No se pudo extraer ninguna propiedad de los enlaces ingresados. Verificá que las publicaciones sigan activas."
        if is_json:
            return jsonify({'success': False, 'error': msg, 'details': errors}), 422
        flash(msg, "danger")
        return redirect(url_for('captacion_outreach.panel_portales_temporales'))

    # Infer zone if not provided
    if not zona:
        barrios = [p.get('barrio') for p in propiedades if p.get('barrio')]
        if barrios:
            zona = barrios[0]

    # Agent info
    agente_nombre = db.get_config('agente_nombre') or current_user.nombre_display or current_user.usuario
    agente_tel = db.get_config('agente_telefono') or ''
    agente_email = db.get_config('agente_email') or ''

    datos_portal = {
        'titulo': titulo_portal,
        'propiedades': propiedades,
        'tipo_operacion': tipo_op,
        'zona': zona,
        'cliente_id': cliente_id,
        'agente_nombre': agente_nombre,
        'agente_telefono': agente_tel,
        'agente_email': agente_email,
        'agente_avatar': ''
    }

    resultado = db.crear_portal_temporal(datos_portal, agente_id=current_user.id)
    slug = resultado.get('codigo_slug')
    portal_url = url_for('captacion_outreach.ver_portal_temporal_publico', slug=slug, _external=True)

    if is_json:
        return jsonify({
            'success': True,
            'slug': slug,
            'portal_url': portal_url,
            'total_propiedades': len(propiedades),
            'expires_at': resultado.get('expires_at'),
            'titulo': titulo_portal,
            'errores': errors,
            'message': f"¡Portal Temporal Live creado con {len(propiedades)} propiedades vigentes por 15 días!"
        })

    flash(f"¡Portal Temporal Live creado exitosamente con {len(propiedades)} propiedades! Vigente hasta {resultado.get('expires_at')[:10]}.", "success")
    return redirect(url_for('captacion_outreach.ver_portal_temporal_publico', slug=slug))

@captacion_outreach_bp.route('/portaltemp/mis-portales')
@login_required
@privilege_required('menu_item', 'portales_temporales')
def panel_portales_temporales():
    """Agent dashboard for managing live temporary portals (isolated per agent and strictly isolated between offices/admins)."""
    is_admin_or_broker = (current_user.rol in ('admin', 'broker') or current_user.usuario == 'GermanMazza')
    filtro_agente = request.args.get('agente_id')
    
    agentes = []
    if is_admin_or_broker:
        try:
            if current_user.usuario == 'GermanMazza':
                all_usuarios = db.get_all_usuarios()
            elif current_user.oficina_id:
                all_usuarios = db.get_all_usuarios(oficina_id=current_user.oficina_id)
            else:
                all_usuarios = []
            # Include regular agents in the dropdown for admin/broker
            agentes = [u for u in all_usuarios if u.get('usuario') != 'GermanMazza']
        except Exception:
            agentes = []
        
        if filtro_agente == 'todos':
            # Returns own portals + all office agents
            portales = db.get_portales_temporales_por_agente(agente_id=None, viewer_admin_id=current_user.id)
        elif filtro_agente and filtro_agente.isdigit():
            target_id = int(filtro_agente)
            target_u = db.get_usuario_by_id(target_id)
            if target_id == current_user.id or (target_u and (current_user.usuario == 'GermanMazza' or target_u.get('oficina_id') == current_user.oficina_id)):
                portales = db.get_portales_temporales_por_agente(agente_id=target_id)
            else:
                filtro_agente = str(current_user.id)
                portales = db.get_portales_temporales_por_agente(agente_id=current_user.id)
        else:
            portales = db.get_portales_temporales_por_agente(agente_id=current_user.id)
    else:
        filtro_agente = str(current_user.id)
        portales = db.get_portales_temporales_por_agente(agente_id=current_user.id)
        
    contactos = []
    try:
        contactos = db.get_contactos()
    except Exception:
        contactos = []

    return render_template(
        'portales_temporales_panel.html', 
        portales=portales,
        is_admin=is_admin_or_broker,
        agentes=agentes,
        filtro_agente=filtro_agente,
        contactos=contactos,
        is_solo_agent=False
    )

@captacion_outreach_bp.route('/portaltemp/<int:pid>/eliminar', methods=['POST'])
@login_required
@privilege_required('menu_item', 'portales_temporales')
def eliminar_portal_temporal_route(pid):
    """Deletes a temporary portal with strict isolation."""
    is_admin_or_broker = (current_user.rol in ('admin', 'broker') or current_user.usuario == 'GermanMazza')
    if is_admin_or_broker:
        db.eliminar_portal_temporal(pid, requester_admin_id=current_user.id)
    else:
        db.eliminar_portal_temporal(pid, agente_id=current_user.id)
    flash("Portal temporal eliminado correctamente.", "info")
    return redirect(url_for('captacion_outreach.panel_portales_temporales'))

@captacion_outreach_bp.route('/portaltemp/<slug>')
def ver_portal_temporal_publico(slug):
    """Public customer-facing live temporary portal (No login required)."""
    portal = db.get_portal_temporal_by_slug(slug)
    if not portal:
        flash("El portal temporal solicitado no existe o fue eliminado.", "danger")
        return redirect(url_for('captacion_outreach.buscador_compradores'))
    
    if not portal.get('expirado'):
        db.registrar_vista_portal_temporal(slug)
        
    branding = db.get_branding_for_agent(portal.get('agente_id'))
    company_logo = branding.get('logo_url')
    agency_name = branding.get('nombre')
    return render_template('portal_temporal_listado.html', portal=portal, company_logo=company_logo, agency_name=agency_name)

@captacion_outreach_bp.route('/portaltemp/<slug>/propiedad/<int:prop_idx>')
def ver_portal_temporal_propiedad_detalle(slug, prop_idx):
    """Public property detail view inside a temporary portal (No login required)."""
    portal = db.get_portal_temporal_by_slug(slug)
    if not portal:
        flash("El portal temporal no existe.", "danger")
        return redirect(url_for('captacion_outreach.buscador_compradores'))
        
    propiedades = portal.get('propiedades', [])
    if prop_idx < 0 or prop_idx >= len(propiedades):
        flash("La propiedad seleccionada no existe en este portal.", "warning")
        return redirect(url_for('captacion_outreach.ver_portal_temporal_publico', slug=slug))
        
    p = propiedades[prop_idx]
    branding = db.get_branding_for_agent(portal.get('agente_id'))
    company_logo = branding.get('logo_url')
    agency_name = branding.get('nombre')
    return render_template('portal_temporal_detalle.html', portal=portal, p=p, prop_idx=prop_idx, company_logo=company_logo, agency_name=agency_name)

@captacion_outreach_bp.route('/busquedas')
@login_required
@superadmin_required
def busquedas():
    """Gestión de búsquedas guardadas (Solo SuperAdmin)."""
    searches = db.get_busquedas()
    return render_template('busquedas.html', searches=searches)

@captacion_outreach_bp.route('/busquedas/nueva', methods=['POST'])
@login_required
@superadmin_required
def nueva_busqueda():
    """Crear una nueva búsqueda (Solo SuperAdmin)."""
    data = {
        'nombre': request.form.get('nombre'),
        'portal': request.form.get('portal'),
        'url_busqueda': request.form.get('url_busqueda'),
        'frecuencia_minutos': int(request.form.get('frecuencia', 60))
    }
    db.insert_busqueda(data)
    flash("Búsqueda guardada", "success")
    return redirect(url_for('captacion_outreach.busquedas'))

@captacion_outreach_bp.route('/busquedas/<int:bid>/toggle', methods=['GET', 'POST'])
@login_required
@superadmin_required
def activar_desactivar_busqueda(bid):
    db.toggle_busqueda(bid)
    return redirect(url_for('captacion_outreach.busquedas'))

@captacion_outreach_bp.route('/busquedas/<int:bid>/borrar', methods=['GET', 'POST'])
@login_required
@superadmin_required
def borrar_busqueda(bid):
    db.delete_busqueda(bid)
    flash("Búsqueda eliminada", "warning")
    return redirect(url_for('captacion_outreach.busquedas'))

# ==========================================
# CLIENT SAVED SEARCHES ROUTES
# ==========================================

@captacion_outreach_bp.route('/busquedas/clientes')
@login_required
@privilege_required('menu_item', 'busquedas_clientes')
def busquedas_clientes():
    """Client saved searches dashboard."""
    if current_user.usuario == 'GermanMazza':
        mis_busquedas = db.get_busquedas_clientes()
        busquedas_publicas = db.get_busquedas_publicas_oficina(excluir_agente_id=current_user.id)
    elif not getattr(current_user, 'oficina_id', None):
        mis_busquedas = db.get_busquedas_clientes(agente_id=current_user.id)
        busquedas_publicas = []
    else:
        mis_busquedas = db.get_busquedas_clientes(agente_id=current_user.id)
        busquedas_publicas = db.get_busquedas_publicas_oficina(excluir_agente_id=current_user.id, oficina_id=current_user.oficina_id)
    return render_template(
        'busquedas_clientes.html', 
        busquedas=mis_busquedas, 
        busquedas_publicas=busquedas_publicas,
        contactos=db.get_contactos()
    )

@captacion_outreach_bp.route('/busquedas/clientes/nueva', methods=['POST'])
@login_required
def nueva_busqueda_cliente():
    """Create a new saved search for a client."""
    import json
    
    tipo_propiedad_raw = request.form.getlist('tipo_propiedad')
    if not tipo_propiedad_raw:
        # Check single values fallback
        single_tipo = request.form.get('tipo_propiedad')
        tipo_propiedad_raw = [single_tipo] if single_tipo else ['departamento']
    
    # Clean if elements are JSON strings from the checkbox layout
    cleaned_types = []
    for t in tipo_propiedad_raw:
        if t.startswith('['):
            try:
                cleaned_types.extend(json.loads(t))
            except:
                cleaned_types.append(t)
        else:
            cleaned_types.append(t)
            
    # Ambientes list
    ambientes_raw = request.form.getlist('ambientes')
    ambientes_list = []
    for a in ambientes_raw:
        if a.startswith('['):
            try:
                ambientes_list.extend([int(x) for x in json.loads(a) if str(x).isdigit()])
            except:
                pass
        elif a.isdigit():
            ambientes_list.append(int(a))
            
    if not ambientes_list:
        single_amb = request.form.get('ambientes')
        if single_amb and single_amb.isdigit():
            ambientes_list = [int(single_amb)]

    extras_raw = request.form.get('extras', '[]')
    try:
        extras = json.loads(extras_raw)
    except:
        extras = []
        
    es_pub_val = request.form.get('es_publica')
    es_publica = 1 if es_pub_val in ('1', 'true', 'on', 1) else 0

    data = {
        'nombre': request.form.get('nombre'),
        'cliente_id': int(request.form.get('cliente_id')),
        'tipo_operacion': request.form.get('tipo_operacion', 'venta'),
        'tipo_propiedad': json.dumps(cleaned_types),
        'zona': request.form.get('zona'),
        'ambientes': json.dumps(ambientes_list) if ambientes_list else None,
        'dormitorios': int(request.form.get('dormitorios')) if request.form.get('dormitorios') else None,
        'min_precio': float(request.form.get('min_precio')) if request.form.get('min_precio') else None,
        'max_precio': float(request.form.get('max_precio')) if request.form.get('max_precio') else None,
        'min_m2': float(request.form.get('min_m2')) if request.form.get('min_m2') else None,
        'max_m2': float(request.form.get('max_m2')) if request.form.get('max_m2') else None,
        'keyword': request.form.get('keyword', ''),
        'extras': json.dumps(extras),
        'agente_id': current_user.id,
        'modo_busqueda': request.form.get('modo_busqueda', 'completa'),
        'es_publica': es_publica
    }
    db.insert_busqueda_cliente(data)
    flash("Búsqueda de cliente guardada correctamente.", "success")
    return redirect(url_for('captacion_outreach.busquedas_clientes'))

@captacion_outreach_bp.route('/busquedas/clientes/<int:bid>/reasignar_cliente', methods=['POST'])
@login_required
def reasignar_cliente_busqueda(bid):
    """Reassign the client for a saved search."""
    b = db.get_busqueda_cliente(bid)
    if not b:
        flash("Búsqueda no encontrada", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
    
    if current_user.usuario != 'GermanMazza' and b.get('agente_id') != current_user.id:
        flash("No tenés permiso para reasignar el cliente de esta búsqueda", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    nuevo_cliente_id = request.form.get('cliente_id', type=int)
    if not nuevo_cliente_id:
        flash("Debés seleccionar un cliente válido", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    db.update_busqueda_cliente_cliente(bid, nuevo_cliente_id)
    flash("Cliente de la búsqueda reasignado correctamente.", "success")
    return redirect(url_for('captacion_outreach.busquedas_clientes'))

@captacion_outreach_bp.route('/busquedas/clientes/<int:bid>/probar')
@login_required
def probar_busqueda_cliente(bid):
    """Executes the search and shows results in the standard search results page."""
    import json
    import traceback

    try:
        b = db.get_busqueda_cliente(bid)
        if not b:
            flash("Búsqueda no encontrada", "danger")
            return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
        solo_nuevas = request.args.get('solo_nuevas', 0, type=int)
            
        # Parse lists de forma segura (soporta lista directa, JSON o valor simple)
        raw_tp = b.get('tipo_propiedad')
        if isinstance(raw_tp, list):
            tipo_prop = [str(x) for x in raw_tp if x]
        elif raw_tp:
            try:
                parsed_tp = json.loads(raw_tp)
                if isinstance(parsed_tp, list):
                    tipo_prop = [str(x) for x in parsed_tp if x]
                else:
                    tipo_prop = [str(parsed_tp)]
            except Exception:
                tipo_prop = [str(raw_tp)]
        else:
            tipo_prop = ['departamento']
        if not tipo_prop:
            tipo_prop = ['departamento']
            
        raw_amb = b.get('ambientes')
        if isinstance(raw_amb, list):
            ambientes = [int(a) for a in raw_amb if a is not None and str(a).isdigit()]
        elif raw_amb:
            try:
                parsed_amb = json.loads(raw_amb)
                if isinstance(parsed_amb, list):
                    ambientes = [int(a) for a in parsed_amb if a is not None and str(a).isdigit()]
                elif str(parsed_amb).isdigit():
                    ambientes = [int(parsed_amb)]
                else:
                    ambientes = None
            except Exception:
                ambientes = [int(raw_amb)] if str(raw_amb).isdigit() else None
        else:
            ambientes = None
        if not ambientes:
            ambientes = None

        extras_list = []
        raw_ext = b.get('extras')
        if isinstance(raw_ext, list):
            extras_list = [str(x) for x in raw_ext if x]
        elif raw_ext:
            try:
                parsed_ext = json.loads(raw_ext)
                if isinstance(parsed_ext, list):
                    extras_list = [str(x) for x in parsed_ext if x]
                elif parsed_ext:
                    extras_list = [str(parsed_ext)]
            except Exception:
                extras_list = [str(raw_ext)]

        operacion = str(b.get('tipo_operacion') or 'venta').lower().strip()
        zona_val = b.get('zona') or ''

        fecha_desde = None
        fecha_creacion_str = ""
        if solo_nuevas:
            fc_raw = b.get('fecha_creacion')
            if fc_raw:
                from lib.scraper_client import normalizar_fecha_filtro
                fecha_desde = normalizar_fecha_filtro(fc_raw)
                fecha_creacion_str = str(fecha_desde)[:10] if fecha_desde else ""

        # Usar el motor unificado de búsqueda con filtros estrictos y saneamiento
        results, _ = procesar_busqueda_multi_zona(
            zona_input=zona_val,
            tipo=tipo_prop,
            operacion=operacion,
            ambientes=ambientes,
            dormitorios=b.get('dormitorios'),
            min_m2=b.get('min_m2'),
            max_m2=b.get('max_m2'),
            min_precio=b.get('min_precio'),
            max_precio=b.get('max_precio'),
            extras=extras_list,
            keyword=b.get('keyword', ''),
            page=1,
            fecha_desde=fecha_desde
        )
            
        if solo_nuevas:
            vistas = []
            if b.get('propiedades_vistas'):
                raw_vistas = b['propiedades_vistas']
                if isinstance(raw_vistas, list):
                    vistas = raw_vistas
                else:
                    try:
                        vistas = json.loads(raw_vistas)
                    except Exception:
                        vistas = []
            vistas_set = set()
            for v in vistas:
                if isinstance(v, str):
                    vistas_set.add(v)
                elif isinstance(v, dict) and v.get('url'):
                    vistas_set.add(v['url'])

            for r in results:
                r['ya_enviada'] = bool(r.get('url') and r.get('url') in vistas_set)
                
            if not results:
                msg_fecha = f" captadas con posterioridad al {fecha_creacion_str}" if fecha_creacion_str else ""
                flash(f"No se encontraron nuevas propiedades{msg_fecha}. Hacé clic en 'Ejecutar Búsqueda' para ver el listado completo.", "info")

        template = 'buscador_compradores.html' if operacion == 'venta' else 'buscador_alquileres.html'
        nombre_original = b.get('nombre') or f"Búsqueda #{bid}"
        nombre_busq = f"{nombre_original} (Nuevas)" if solo_nuevas else nombre_original

        return render_template(
            template,
            results=results,
            zona=zona_val,
            tipo=tipo_prop,
            ambientes=ambientes,
            dormitorios=b.get('dormitorios'),
            min_m2=b.get('min_m2'),
            max_m2=b.get('max_m2'),
            min_precio=b.get('min_precio'),
            max_precio=b.get('max_precio'),
            selected_extras=extras_list,
            current_page=1,
            keyword=b.get('keyword', ''),
            contactos=db.get_contactos(),
            preselected_busqueda_nombre=nombre_busq
        )
    except Exception as e:
        print(f"[ERROR] Excepción ejecutando probar_busqueda_cliente ({bid}): {e}")
        traceback.print_exc()
        flash(f"Error al ejecutar la búsqueda: {e}", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))

def _build_html_email_report(b, results):
    """Auxiliary to build the HTML email body with safe truncated descriptions."""
    props_data = []
    for p in results:
        desc = p.get('descripcion', '') or ''
        desc_clean = desc.strip()
        
        # Decide nice fraction (about 15% of original, limit between 50-120 chars, ignore ML placeholder)
        if not desc_clean or desc_clean.startswith("Detalles disponibles") or len(desc_clean) < 60:
            desc_acotada = ""
        else:
            cutoff = int(len(desc_clean) * 0.15)
            if cutoff < 50 and len(desc_clean) > 50:
                cutoff = 50
            if cutoff > 120:
                cutoff = 120
            desc_acotada = desc_clean[:cutoff].strip() + ("..." if len(desc_clean) > cutoff else "")
        
        fotos_raw = p.get('fotos') or []
        foto_portada = p.get('foto') or (fotos_raw[0] if fotos_raw else None)
        if foto_portada and foto_portada not in fotos_raw:
            fotos_raw = [foto_portada] + fotos_raw
        elif foto_portada and fotos_raw and fotos_raw[0] != foto_portada:
            fotos_raw = [foto_portada] + [f for f in fotos_raw if f != foto_portada]
        
        fotos = ([foto_portada] if foto_portada else []) + [f for f in fotos_raw[1:] if f]
        
        props_data.append({
            'titulo': p.get('titulo', 'Propiedad en ' + b['zona']),
            'precio': p.get('precio', 0),
            'moneda': p.get('moneda', 'USD'),
            'ambientes': p.get('ambientes'),
            'm2': p.get('m2') or p.get('superficie_total') or 0,
            'barrio': p.get('barrio') or b['zona'],
            'descripcion_acotada': desc_acotada,
            'fotos': fotos[:6],
            'tipo_propiedad': p.get('tipo_propiedad'),
            'm2_total': p.get('m2_total') or p.get('superficie_total') or p.get('m2') or 0,
            'm2_cubiertos': p.get('m2_cubiertos'),
            'dormitorios': p.get('dormitorios'),
            'banos': p.get('banos'),
            'toilettes': p.get('toilettes'),
            'cocheras': p.get('cocheras'),
            'antiguedad': p.get('antiguedad'),
            'orientacion': p.get('orientacion'),
            'disposicion': p.get('disposicion'),
            'estado_conservacion': p.get('estado_conservacion')
        })
        
    config = db.get_all_config()
    logo_path = config.get('company_logo_path')
    logo_url = ""
    if logo_path:
        logo_url = request.url_root.rstrip('/') + logo_path
        
    return render_template(
        'email_propiedades.html',
        zona=b['zona'],
        props=props_data,
        logo_url=logo_url,
        agente_nombre=config.get('agente_nombre', 'Tu Asesor'),
        agente_telefono=config.get('agente_telefono', ''),
        agente_email=config.get('agente_email', ''),
        agente_inmobiliaria=config.get('agente_inmobiliaria', '')
    )

@captacion_outreach_bp.route('/busquedas/clientes/<int:bid>/enviar_agente')
@login_required
def enviar_busqueda_agente(bid):
    """Runs search and sends HTML copy directly to agent's inbox."""
    import json
    b = db.get_busqueda_cliente(bid)
    if not b:
        flash("Búsqueda no encontrada", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    try:
        tipo_prop = json.loads(b['tipo_propiedad'])
        if not isinstance(tipo_prop, list): tipo_prop = [tipo_prop]
    except:
        tipo_prop = [b['tipo_propiedad']] if b['tipo_propiedad'] else ['departamento']
        
    try:
        ambientes = json.loads(b['ambientes']) if b['ambientes'] else None
        if ambientes and not isinstance(ambientes, list): ambientes = [ambientes]
    except:
        ambientes = [int(b['ambientes'])] if b['ambientes'] else None

    extras_list = []
    if b.get('extras'):
        try:
            extras_list = json.loads(b['extras'])
            if not isinstance(extras_list, list): extras_list = [extras_list]
        except:
            extras_list = [b['extras']]

    # Usar el motor unificado de búsqueda con filtros estrictos
    results, _ = procesar_busqueda_multi_zona(
        zona_input=b['zona'],
        tipo=tipo_prop,
        operacion=b['tipo_operacion'],
        ambientes=ambientes,
        dormitorios=b.get('dormitorios'),
        min_m2=b.get('min_m2'),
        max_m2=b.get('max_m2'),
        min_precio=b.get('min_precio'),
        max_precio=b.get('max_precio'),
        extras=extras_list,
        keyword=b.get('keyword'),
        page=1
    )
        
    if not results:
        flash("No se encontraron propiedades para enviar", "warning")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    cuerpo_html = _build_html_email_report(b, results)
    
    config = db.get_all_config()
    dest = config.get('agente_email')
    if not dest:
        flash("Configurá primero tu email de agente en Ajustes.", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    agente_uid = current_user.id if current_user and current_user.is_authenticated else None
    db.enqueue_correo_cliente(dest, f"COPIA AGENTE: {b['nombre']}", cuerpo_html, agente_id=agente_uid)
    flash(f"Correo de copia agendado en cola para {dest}. Se enviará en breve (intervalo de 12 segundos).", "success")
    return redirect(url_for('captacion_outreach.busquedas_clientes'))

@captacion_outreach_bp.route('/busquedas/clientes/<int:bid>/enviar_cliente')
@login_required
def enviar_busqueda_cliente(bid):
    """Runs search, filters for NEW results, sends HTML to client, updates vistas."""
    import json
    b = db.get_busqueda_cliente(bid)
    if not b:
        flash("Búsqueda no encontrada", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    if not b['cliente_email']:
        flash("El cliente no tiene un email configurado.", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    try:
        tipo_prop = json.loads(b['tipo_propiedad'])
        if not isinstance(tipo_prop, list): tipo_prop = [tipo_prop]
    except:
        tipo_prop = [b['tipo_propiedad']] if b['tipo_propiedad'] else ['departamento']
        
    try:
        ambientes = json.loads(b['ambientes']) if b['ambientes'] else None
        if ambientes and not isinstance(ambientes, list): ambientes = [ambientes]
    except:
        ambientes = [int(b['ambientes'])] if b['ambientes'] else None

    extras_list = []
    if b.get('extras'):
        try:
            extras_list = json.loads(b['extras'])
            if not isinstance(extras_list, list): extras_list = [extras_list]
        except:
            extras_list = [b['extras']]

    # Usar el motor unificado de búsqueda con filtros estrictos
    results, _ = procesar_busqueda_multi_zona(
        zona_input=b['zona'],
        tipo=tipo_prop,
        operacion=b['tipo_operacion'],
        ambientes=ambientes,
        dormitorios=b.get('dormitorios'),
        min_m2=b.get('min_m2'),
        max_m2=b.get('max_m2'),
        min_precio=b.get('min_precio'),
        max_precio=b.get('max_precio'),
        extras=extras_list,
        keyword=b.get('keyword'),
        page=1
    )
        
    if not results:
        flash("No se encontraron propiedades", "warning")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    vistas = json.loads(b['propiedades_vistas']) if b['propiedades_vistas'] else []
    
    new_results = []
    all_urls = []
    
    for r in results:
        url = r.get('url')
        if not url: continue
        all_urls.append(url)
        if url not in vistas:
            new_results.append(r)
            
    if not new_results:
        flash("Hoy no hay propiedades nuevas!", "warning")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    cuerpo_html = _build_html_email_report(b, new_results)
    
    search_agente_id = b.get('agente_id') or (current_user.id if current_user and current_user.is_authenticated else None)
    db.enqueue_correo_cliente(b['cliente_email'], f"Nuevas Propiedades: {b['nombre']}", cuerpo_html, agente_id=search_agente_id)
    
    updated_vistas = list(set(vistas + all_urls))
    db.update_busqueda_cliente_vistas(bid, json.dumps(updated_vistas))
    
    flash(f"Se han encolado {len(new_results)} propiedades nuevas para enviar a {b['cliente_email']}.", "success")
    return redirect(url_for('captacion_outreach.busquedas_clientes'))

@captacion_outreach_bp.route('/busquedas/clientes/<int:bid>/borrar', methods=['GET', 'POST'])
@login_required
def borrar_busqueda_cliente(bid):
    b = db.get_busqueda_cliente(bid)
    if not b:
        flash("Búsqueda no encontrada o ya eliminada.", "warning")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))
        
    # Verificación estricta de pertenencia (Anti-IDOR)
    is_owner = (b.get('agente_id') == current_user.id)
    is_superadmin = (current_user.usuario == 'GermanMazza')
    is_office_admin = (
        current_user.rol in ['admin', 'broker'] 
        and getattr(current_user, 'oficina_id', None) is not None 
        and b.get('agente_oficina_id') == current_user.oficina_id
    )
    
    if not (is_owner or is_superadmin or is_office_admin):
        flash("Acceso denegado: No tenés permisos para eliminar esta búsqueda de cliente.", "danger")
        return redirect(url_for('captacion_outreach.busquedas_clientes'))

    db.delete_busqueda_cliente(bid)
    flash("Búsqueda de cliente eliminada", "warning")
    return redirect(url_for('captacion_outreach.busquedas_clientes'))

@captacion_outreach_bp.route('/busquedas/clientes/enviar_seleccionados', methods=['POST'])
@login_required
def enviar_seleccionados_cliente():
    """Queues an HTML email containing manual selected properties to a client."""
    import json
    cliente_id = request.form.get('cliente_id')
    if not cliente_id:
        flash("Debe seleccionar un cliente.", "danger")
        return redirect(request.referrer or url_for('index'))
        
    contacto = db.get_contacto(int(cliente_id))
    if not contacto or not contacto.get('email'):
        flash("Cliente no encontrado o no posee dirección de email.", "danger")
        return redirect(request.referrer or url_for('index'))
        
    selected_json_list = request.form.getlist('selected_data')
    if not selected_json_list:
        flash("Debe seleccionar al menos una propiedad para enviar.", "danger")
        return redirect(request.referrer or url_for('index'))
        
    # Reconstruct property objects
    results = []
    all_urls = []
    for item_str in selected_json_list:
        try:
            p = json.loads(item_str)
            results.append(p)
            url = p.get('url')
            if url:
                all_urls.append(url)
        except Exception as e:
            print(f"[Enviar Seleccionados] Error parsing item: {e}")
            
    # Fetch Argenprop details on-demand before emailing
    resolve_details_ondemand(results)
            
    if not results:
        flash("Error al interpretar las propiedades seleccionadas.", "danger")
        return redirect(request.referrer or url_for('index'))
        
    detected_zones = [r.get('barrio') or r.get('direccion') for r in results if r.get('barrio') or r.get('direccion')]
    main_zone = detected_zones[0] if detected_zones else "Varios"
    
    b = {
        'zona': main_zone,
        'nombre': f"Selección de Propiedades - {main_zone}"
    }
    
    cuerpo_html = _build_html_email_report(b, results)
    
    current_uid = current_user.id if current_user and current_user.is_authenticated else None
    db.enqueue_correo_cliente(contacto['email'], f"Selección de Propiedades: {main_zone}", cuerpo_html, agente_id=current_uid)
    
    if current_user and getattr(current_user, 'email', None):
        agent_subject = f"[Copia Enviada a {contacto['nombre']} {contacto['apellido']}] Selección de Propiedades: {main_zone}"
        db.enqueue_correo_cliente(current_user.email, agent_subject, cuerpo_html, agente_id=current_uid)
    
    # Update vistas for saved searches of this client
    try:
        searches = db.get_busquedas_clientes(cliente_id=contacto['id'])
        for s in searches:
            vistas = json.loads(s['propiedades_vistas']) if s['propiedades_vistas'] else []
            updated_vistas = list(set(vistas + all_urls))
            db.update_busqueda_cliente_vistas(s['id'], json.dumps(updated_vistas))
    except Exception as e:
        print(f"[Enviar Seleccionados] Error updating vistas history: {e}")
        
    flash(f"Se ha encolado la selección de {len(results)} propiedades para enviar a {contacto['nombre']} {contacto['apellido']} ({contacto['email']}). Se despachará en la cola de envíos.", "success")
    return redirect(request.referrer or url_for('index'))




@captacion_outreach_bp.route('/configuracion', methods=['GET', 'POST'])
@privilege_required('menu_item', 'configuracion')
def configuracion():
    """Configuración del sistema."""
    if request.method == 'POST':
        import shutil
        import json
        
        # Check if database directory path is updated
        new_db_dir = request.form.get('db_dir')
        if new_db_dir:
            new_db_dir = new_db_dir.strip()
            
            # Read old db_dir first to migrate files
            from database.db import DB_DIR
            old_db_dir = DB_DIR
            
            norm_new = os.path.normpath(new_db_dir).lower()
            norm_old = os.path.normpath(old_db_dir).lower()
            
            if norm_new != norm_old:
                try:
                    os.makedirs(new_db_dir, exist_ok=True)
                    
                    # Copy Master DB
                    old_master = os.path.join(old_db_dir, 'captador.db')
                    new_master = os.path.join(new_db_dir, 'captador.db')
                    if os.path.exists(old_master):
                        shutil.copy2(old_master, new_master)
                        
                    # Copy usuarios/ subfolder
                    old_users_dir = os.path.join(old_db_dir, 'usuarios')
                    new_users_dir = os.path.join(new_db_dir, 'usuarios')
                    if os.path.exists(old_users_dir):
                        os.makedirs(new_users_dir, exist_ok=True)
                        for f in os.listdir(old_users_dir):
                            src_f = os.path.join(old_users_dir, f)
                            if os.path.isfile(src_f):
                                shutil.copy2(src_f, os.path.join(new_users_dir, f))
                                
                    # Update config file in workspace root
                    workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                    config_file = os.path.join(workspace_dir, 'db_config.json')
                    with open(config_file, 'w', encoding='utf-8') as f_cfg:
                        json.dump({'db_dir': new_db_dir}, f_cfg, indent=4)
                        
                    # Update active constants in db module
                    import database.db
                    database.db.DB_DIR = new_db_dir
                    database.db.USERS_DB_DIR = new_users_dir
                    database.db.MASTER_DB_PATH = new_master
                    
                    flash(f"Ruta de base de datos actualizada y archivos migrados a: {new_db_dir}", "success")
                except Exception as e:
                    flash(f"Error al cambiar la ruta o migrar bases de datos: {e}", "danger")
                    
        # Handle Logo Upload
        logo_file = request.files.get('company_logo_file')
        if logo_file and logo_file.filename:
            ext = os.path.splitext(logo_file.filename)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg']:
                upload_dir = os.path.join(current_app.root_path, 'static', 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                # Save with timestamp or unique tag to prevent browser caching
                import time
                fname = f"company_logo_{int(time.time())}{ext}"
                new_logo_url = f"/static/uploads/{fname}"
                
                # Delete old logo file if it exists to clean up static files
                old_logo_path = db.get_config('company_logo_path')
                if old_logo_path and old_logo_path.startswith('/static/uploads/'):
                    old_full = os.path.join(current_app.root_path, old_logo_path.lstrip('/'))
                    if os.path.exists(old_full):
                        try:
                            os.remove(old_full)
                        except Exception as e:
                            print(f"Error removing old logo: {e}")
                            
                save_path = os.path.join(upload_dir, fname)
                logo_file.save(save_path)
                db.set_config('company_logo_path', new_logo_url)

                # If user belongs to an office, update the office logo as well
                if getattr(current_user, 'oficina_id', None):
                    try:
                        _conn = db.get_db(db.MASTER_DB_PATH)
                        _conn.execute("UPDATE oficinas SET logo_url = ? WHERE id = ?", (new_logo_url, current_user.oficina_id))
                        _conn.close()
                    except Exception as _e_ofi:
                        print(f"Error updating office logo: {_e_ofi}")

                flash("Logo de la compañía subido correctamente.", "success")
            else:
                flash("Formato de logo no permitido. Solo se permiten PNG, JPG, JPEG, GIF o SVG.", "danger")

        # Handle Logo Clearing
        if request.form.get('action_clear_logo') == '1':
            logo_path_rel = db.get_config('company_logo_path')
            if logo_path_rel and logo_path_rel.startswith('/static/uploads/'):
                full_path = os.path.join(current_app.root_path, logo_path_rel.lstrip('/'))
                if os.path.exists(full_path):
                    try:
                        os.remove(full_path)
                    except Exception as e:
                        print(f"Error removing logo file: {e}")
            db.set_config('company_logo_path', '')

            # If user belongs to an office, clear office logo as well
            if getattr(current_user, 'oficina_id', None):
                try:
                    _conn = db.get_db(db.MASTER_DB_PATH)
                    _conn.execute("UPDATE oficinas SET logo_url = '' WHERE id = ?", (current_user.oficina_id,))
                    _conn.close()
                except Exception as _e_ofi:
                    print(f"Error clearing office logo: {_e_ofi}")

            flash("Logo de la compañía eliminado. El sistema usará la marca por defecto.", "info")

        # Admin-only config keys: cannot be saved by non-admins even via form manipulation
        # Permission-aware key validation (allows admin/broker and users with matrix privileges)
        from database.db_auth import check_user_privilege
        from flask_login import current_user as _cu
        is_super = (_cu.usuario == 'GermanMazza')
        is_admin = (is_super or _cu.rol == 'admin')
        is_admin_or_broker = (is_super or _cu.rol in ('admin', 'broker'))
        
        def can_save_key(k):
            if is_admin:
                return True
            if k == 'tokko_api_key':
                return is_admin_or_broker or check_user_privilege(_cu, 'accion', 'ver_config_tokko')
            if k == 'company_logo_path':
                return is_admin_or_broker or check_user_privilege(_cu, 'accion', 'ver_config_logo')
            if k == 'automatizacion_email_activa':
                return is_admin_or_broker or check_user_privilege(_cu, 'accion', 'ver_config_plantillas')
            if k in ('meta_access_token', 'ig_account_id', 'meta_ai_crm_enabled', 'webhook_verify_token'):
                return is_admin_or_broker or check_user_privilege(_cu, 'accion', 'ver_config_meta_ai')
            if k in ('alerta_whatsapp_activo', 'alerta_admin_login', 'alerta_failed_logins', 'alerta_whatsapp_telefonos', 'audit_retention_days'):
                return is_admin
            return True

        # Handle Scraper Service Configuration (SuperAdmin / Admin only)
        if is_admin and 'scraper_mode' in request.form:
            try:
                from lib.scraper_client import ScraperClient
                sc_mode = request.form.get('scraper_mode', 'remote').strip()
                sc_url = request.form.get('scraper_url', 'http://173.249.38.187:5001').strip().rstrip('/')
                sc_key = request.form.get('scraper_api_key', '').strip()
                ScraperClient.save_scraper_config({
                    'mode': sc_mode,
                    'url': sc_url,
                    'api_key': sc_key,
                    'timeout_seconds': 15
                })
            except Exception as e_sc:
                print(f"[Configuracion] Error guardando scraper_service: {e_sc}")

        for key in request.form.keys():
            if key in ('db_dir', 'action_clear_logo', 'scraper_mode', 'scraper_url', 'scraper_api_key'):
                continue
            if not can_save_key(key):
                continue  # Skip keys without permission
            value = request.form.getlist(key)[-1]
            db.set_config(key, value)
            
        if is_admin and 'audit_retention_days' in request.form:
            try:
                from database.db_audit import purgar_auditoria
                purgar_auditoria(int(request.form.get('audit_retention_days', 90)))
            except Exception:
                pass

        flash("Configuración actualizada", "success")
        return redirect(url_for('captacion_outreach.configuracion'))
    
    config = db.get_all_config()
    from database.db import DB_DIR
    from lib.scraper_client import ScraperClient
    scraper_cfg = ScraperClient.get_config()
    usuarios = db.get_all_usuarios()
    user_totp = db.get_user_totp_info(current_user.id) if current_user.is_authenticated else None
    return render_template('configuracion.html', config=config, db_dir=DB_DIR, usuarios=usuarios, scraper_cfg=scraper_cfg, user_totp=user_totp)

@captacion_outreach_bp.route('/api/scraper/login-connect', methods=['POST'])
@login_required
def api_scraper_login_connect():
    """Conecta el CRM al motor de scraping mediante usuario y contraseña (Admins y Brokers)."""
    if current_user.rol not in ('admin', 'broker') and current_user.usuario != 'GermanMazza':
        return jsonify({'success': False, 'message': 'No autorizado. Solo Brokers y Administradores pueden gestionar la conexión del scraper.'}), 403

    data = request.get_json() or {}
    url = data.get('url')
    usuario = data.get('usuario')
    password = data.get('password')

    if not usuario or not password:
        return jsonify({'success': False, 'message': 'Usuario y contraseña requeridos.'}), 400

    from lib.scraper_client import ScraperClient
    result = ScraperClient.login_and_connect(url=url, usuario=usuario, password=password)
    return jsonify(result)

@captacion_outreach_bp.route('/api/scraper/disconnect', methods=['POST'])
@login_required
def api_scraper_disconnect():
    """Desconecta el motor de scraping en el CRM."""
    if current_user.rol not in ('admin', 'broker') and current_user.usuario != 'GermanMazza':
        return jsonify({'success': False, 'message': 'No autorizado.'}), 403

    from lib.scraper_client import ScraperClient
    result = ScraperClient.disconnect()
    return jsonify(result)

@captacion_outreach_bp.route('/api/scraper/test-connection', methods=['POST'])
@login_required
def api_scraper_test_connection():
    """Prueba la conexión con el motor de scraping (local o remoto)."""
    data = request.get_json() or {}
    url = data.get('url')
    usuario = data.get('usuario')
    password = data.get('password')
    api_key = data.get('api_key')
    
    from lib.scraper_client import ScraperClient
    result = ScraperClient.test_connection(url=url, usuario=usuario, password=password, api_key=api_key)
    return jsonify(result)

@captacion_outreach_bp.route('/api/debug_meta_token')
@privilege_required('menu_item', 'configuracion')
def debug_meta_token():
    """Verify if the Meta Access Token and IG Account ID are valid and linked."""
    config = db.get_all_config()
    token = config.get('meta_access_token')
    ig_id = config.get('ig_account_id')
    
    if not token or not ig_id:
        return jsonify({'success': False, 'message': 'Faltan datos en la configuración.'})
        
    import requests
    try:
        # Check permissions and object access
        url = f"https://graph.facebook.com/v19.0/{ig_id}"
        params = {'fields': 'name,username', 'access_token': token}
        r = requests.get(url, params=params)
        res = r.json()
        
        if 'error' in res:
            return jsonify({
                'success': False, 
                'message': f"Meta dice: {res['error'].get('message')}",
                'code': res['error'].get('code'),
                'subcode': res['error'].get('error_subcode')
            })
            
        return jsonify({
            'success': True, 
            'message': f"¡Conexión Exitosa! Acceso a: {res.get('name')} (@{res.get('username')})"
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f"Error de conexión: {str(e)}"})

@captacion_outreach_bp.route('/configuracion/planificador', methods=['GET', 'POST'])
@login_required
@superadmin_required
def planificador():
    """Gestión del planificador de mensajes de 10 semanas (Solo SuperAdmin)."""
    if request.method == 'POST':
        for i in range(1, 11):
            mensaje = request.form.get(f'mensaje_semana_{i}', '')
            habilitado = 1 if request.form.get(f'habilitado_semana_{i}') == 'on' else 0
            db.update_planificador_semana(i, mensaje, habilitado)
        flash('Planificador actualizado correctamente.', 'success')
        return redirect(url_for('captacion_outreach.planificador'))
    
    semanas = db.get_planificador()
    return render_template('planificador.html', semanas=semanas)

@captacion_outreach_bp.route('/propiedad/<int:prop_id>/preparar_mensaje/<int:paso>')
def preparar_mensaje(prop_id, paso):
    """Generar contenido del mensaje personalizado."""
    prop = db.get_propiedad(prop_id)
    config = db.get_all_config()
    tipo = request.args.get('tipo', 'whatsapp') # whatsapp o email

    # Obtener templates según el paso
    template_key = f'template_{tipo}_{paso}'
    asunto_key = f'template_email_asunto_{paso}'
    
    mensaje_raw = config.get(template_key, "")
    asunto_raw = config.get(asunto_key, "")

    # Reemplazar placeholders
    placeholders = {
        'nombre': prop['nombre_contacto'] or 'propietario',
        'direccion': prop['direccion'] or 'tu propiedad',
        'barrio': prop['barrio'] or '',
        'portal': prop['portal'].capitalize(),
        'agente_nombre': config.get('agente_nombre', ''),
        'agente_telefono': config.get('agente_telefono', ''),
        'agente_inmobiliaria': config.get('agente_inmobiliaria', '')
    }

    mensaje = mensaje_raw.format(**placeholders)
    asunto = asunto_raw.format(**placeholders) if tipo == 'email' else ""

    if tipo == 'whatsapp':
        # Generar link wa.me
        # Limpiar teléfono usando la utilidad robusta
        telefono_clean = clean_phone_argentina(prop['telefono'])
        
        wa_url = f"https://wa.me/{telefono_clean}?text={urllib.parse.quote(mensaje)}"
        
        # Guardar en comunicaciones como pendiente
        db.insert_comunicacion({
            'propiedad_id': prop_id,
            'tipo': 'whatsapp',
            'mensaje': mensaje,
            'paso': paso,
            'estado': 'pendiente'
        })
        
        return redirect(wa_url)
    
    else: # Email
        # Esto sería para enviar vía SMTP, por ahora solo guardamos y mostramos
        db.insert_comunicacion({
            'propiedad_id': prop_id,
            'tipo': 'email',
            'mensaje': mensaje,
            'asunto': asunto,
            'paso': paso,
            'estado': 'pendiente'
        })
        flash("Email preparado en la sección de comunicaciones", "info")
        return redirect(url_for('captacion_outreach.propiedad_detalle', prop_id=prop_id))

# --- RUTAS DE CONEXIÓN WHATSAPP PORTAL DE CLIENTES (SUPERADMIN ONLY) ---

@captacion_outreach_bp.route('/crm/whatsapp/portal/conectar', methods=['GET', 'POST'])
@login_required
def conectar_whatsapp_portal():
    """Lanza el vinculador de WhatsApp para el Portal de Clientes (Solo SuperAdmin GermanMazza)."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.args.get('ajax')
    if current_user.usuario != 'GermanMazza':
        if is_ajax:
            return jsonify({'error': 'Acceso denegado: solo el SuperAdmin Germán puede gestionar el WhatsApp del Portal.'}), 403
        flash("Acceso denegado: solo el SuperAdmin Germán puede gestionar el WhatsApp del Portal.", "danger")
        return redirect(request.referrer or url_for('index'))
    import json, shutil, time
    session_dir = os.path.join(os.path.expanduser('~'), '.whatsapp_portal_session_admin')
    qr_file = os.path.join(os.getcwd(), 'static', 'uploads', 'qr_portal_admin.png')
    status_file = os.path.join(os.getcwd(), 'static', 'uploads', 'status_portal_admin.json')
    
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                old_pid = data.get('pid')
                if old_pid:
                    subprocess.run(["taskkill", "/F", "/PID", str(old_pid)], creationflags=0x08000000)
        except: pass

    time.sleep(0.3)
    try:
        if os.path.exists(session_dir): shutil.rmtree(session_dir, ignore_errors=True)
        if os.path.exists(qr_file): os.remove(qr_file)
        if os.path.exists(status_file): os.remove(status_file)
    except: pass

    try:
        wa_node_dir = os.path.join(os.getcwd(), 'lib', 'whatsapp_node')
        script_path = os.path.join(wa_node_dir, 'wa_linker.js')
        node_bin = os.path.join(wa_node_dir, 'bin', 'node.exe')
        node_cmd = node_bin if os.path.exists(node_bin) else "node"

        init_payload = json.dumps({"status": "connecting", "usuario": "admin", "scope": "portal", "ts": int(time.time()*1000)})
        try:
            with open(status_file, 'w', encoding='utf-8') as f: f.write(init_payload)
        except: pass

        cmd = [node_cmd, script_path, '--user', 'admin', '--scope', 'portal', '--clean']
        log_out = open(os.path.join(os.getcwd(), 'static', 'uploads', 'node_portal_err.txt'), 'w')
        subprocess.Popen(cmd, cwd=wa_node_dir, stdout=log_out, stderr=log_out, creationflags=0x08000000 if os.name == 'nt' else 0)
        if is_ajax:
            return jsonify({'status': 'connecting', 'message': 'Vinculador del Portal iniciado'})
        flash("Iniciando vinculador del Portal de Clientes... Verificando código QR.", "success")
    except Exception as e:
        if is_ajax:
            return jsonify({'error': str(e)}), 500
        flash(f"Error al iniciar vinculador del portal: {e}", "error")
    return redirect(request.referrer or url_for('index'))

@captacion_outreach_bp.route('/crm/whatsapp/portal/logout', methods=['GET', 'POST'])
@login_required
def logout_whatsapp_portal():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.args.get('ajax')
    if current_user.usuario != 'GermanMazza':
        if is_ajax:
            return jsonify({'error': 'Acceso denegado: solo el SuperAdmin Germán puede gestionar el WhatsApp del Portal.'}), 403
        flash("Acceso denegado.", "danger")
        return redirect(request.referrer or url_for('index'))
    import shutil, json, time
    session_dir = os.path.join(os.path.expanduser('~'), '.whatsapp_portal_session_admin')
    status_file = os.path.join(os.getcwd(), 'static', 'uploads', 'status_portal_admin.json')
    qr_file = os.path.join(os.getcwd(), 'static', 'uploads', 'qr_portal_admin.png')
    
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                old_pid = data.get('pid')
                if old_pid:
                    subprocess.run(["taskkill", "/F", "/PID", str(old_pid)], creationflags=0x08000000)
        except: pass

    try:
        time.sleep(0.5)
        if os.path.exists(session_dir): shutil.rmtree(session_dir, ignore_errors=True)
        if os.path.exists(status_file): os.remove(status_file)
        if os.path.exists(qr_file): os.remove(qr_file)
        if is_ajax:
            return jsonify({'status': 'disconnected', 'message': 'Sesión desconectada'})
        flash("Sesión de WhatsApp del Portal desconectada con éxito.", "success")
    except Exception as e:
        if is_ajax:
            return jsonify({'error': str(e)}), 500
        flash(f"No se pudo desconectar el Portal: {e}", "danger")
    return redirect(request.referrer or url_for('index'))

@captacion_outreach_bp.route('/api/whatsapp/portal/status')
def whatsapp_portal_status():
    # Only SuperAdmin GermanMazza can query portal WhatsApp status
    if not current_user or not current_user.is_authenticated or current_user.usuario != 'GermanMazza':
        return jsonify({'status': 'disconnected', 'error': 'Solo SuperAdmin'}), 403

    import json, time
    session_dir = os.path.join(os.path.expanduser('~'), '.whatsapp_portal_session_admin')
    creds_file = os.path.join(session_dir, 'creds.json')
    status_file = os.path.join(os.getcwd(), 'static', 'uploads', 'status_portal_admin.json')
    
    # 1. Verificar credenciales reales en disco
    has_valid_creds = False
    if os.path.exists(creds_file):
        try:
            with open(creds_file, 'r', encoding='utf-8') as f_c:
                creds = json.load(f_c)
                if creds and (creds.get('me') or creds.get('registered')):
                    has_valid_creds = True
        except Exception:
            pass

    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                status = data.get('status', 'disconnected')
                qr = data.get('qr')
                ts = data.get('ts', 0)
                now_ts = int(time.time() * 1000)

                # Si creds son válidas y no se está pidiendo un QR nuevo en los últimos 20s
                if has_valid_creds and (status != 'qr_ready' or (now_ts - ts) > 20000):
                    return jsonify({'status': 'connected', 'usuario': 'admin', 'qr': None})

                return jsonify({
                    'status': status, 
                    'usuario': 'admin',
                    'qr': qr
                })
        except: pass

    if has_valid_creds:
        return jsonify({'status': 'connected', 'usuario': 'admin', 'qr': None})

    return jsonify({'status': 'disconnected', 'usuario': 'admin', 'qr': None})


# --- RUTAS DE CONEXIÓN WHATSAPP PUBLICADOR DE HISTORIAS (TODOS LOS AGENTES) ---

@captacion_outreach_bp.route('/conectar_whatsapp', methods=['GET', 'POST'])
@login_required
def conectar_whatsapp():
    """Lanza el vinculador de WhatsApp para el Publicador de Historias del agente."""
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.args.get('ajax')
    import json, shutil, time
    session_dir = os.path.join(os.path.expanduser('~'), f'.whatsapp_bot_session_{current_user.usuario}')
    qr_file = os.path.join(os.getcwd(), 'static', 'uploads', f'qr_historias_{current_user.usuario}.png')
    legacy_qr = os.path.join(os.getcwd(), 'static', 'uploads', f'qr_{current_user.usuario}.png')
    status_file = os.path.join(os.getcwd(), 'static', 'uploads', f'status_historias_{current_user.usuario}.json')
    legacy_status = os.path.join(os.getcwd(), 'static', 'uploads', f'status_{current_user.usuario}.json')
    
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                old_pid = data.get('pid')
                if old_pid:
                    subprocess.run(["taskkill", "/F", "/PID", str(old_pid)], creationflags=0x08000000)
        except: pass

    time.sleep(0.3)
    try:
        if os.path.exists(session_dir): shutil.rmtree(session_dir, ignore_errors=True)
        if os.path.exists(qr_file): os.remove(qr_file)
        if os.path.exists(legacy_qr): os.remove(legacy_qr)
        if os.path.exists(status_file): os.remove(status_file)
        if os.path.exists(legacy_status): os.remove(legacy_status)
    except: pass

    try:
        wa_node_dir = os.path.join(os.getcwd(), 'lib', 'whatsapp_node')
        script_path = os.path.join(wa_node_dir, 'wa_linker.js')
        node_bin = os.path.join(wa_node_dir, 'bin', 'node.exe')
        node_cmd = node_bin if os.path.exists(node_bin) else "node"
        
        # Escribir estado 'connecting' inmediatamente para evitar carrera en el polling del cliente
        init_payload = json.dumps({"status": "connecting", "usuario": current_user.usuario, "scope": "historias", "ts": int(time.time()*1000)})
        try:
            with open(status_file, 'w', encoding='utf-8') as f: f.write(init_payload)
            with open(legacy_status, 'w', encoding='utf-8') as f: f.write(init_payload)
        except: pass

        cmd = [node_cmd, script_path, '--user', current_user.usuario, '--scope', 'historias', '--clean']
        log_out = open(os.path.join(os.getcwd(), 'static', 'uploads', f'node_historias_{current_user.usuario}_err.txt'), 'w')
        subprocess.Popen(cmd, cwd=wa_node_dir, stdout=log_out, stderr=log_out, creationflags=0x08000000 if os.name == 'nt' else 0)
        if is_ajax:
            return jsonify({'status': 'connecting', 'message': 'Vinculador de Historias iniciado'})
        flash(f"Iniciando vinculador de Publicador de Historias para {current_user.nombre_display}... Verificando código QR.", "success")
    except Exception as e:
        if is_ajax:
            return jsonify({'error': str(e)}), 500
        flash(f"Error al iniciar vinculador: {e}", "error")
    return redirect(request.referrer or url_for('index'))

@captacion_outreach_bp.route('/api/whatsapp/historias/status')
@captacion_outreach_bp.route('/api/whatsapp/status')
def whatsapp_status():
    if not current_user or not current_user.is_authenticated:
        return jsonify({'status': 'disconnected', 'usuario': '', 'qr': None})
    import json, time
    session_dir = os.path.join(os.path.expanduser('~'), f'.whatsapp_bot_session_{current_user.usuario}')
    creds_file = os.path.join(session_dir, 'creds.json')
    status_file = os.path.join(os.getcwd(), 'static', 'uploads', f'status_historias_{current_user.usuario}.json')
    legacy_status = os.path.join(os.getcwd(), 'static', 'uploads', f'status_{current_user.usuario}.json')

    # 1. Verificar credenciales reales en disco
    has_valid_creds = False
    if os.path.exists(creds_file):
        try:
            with open(creds_file, 'r', encoding='utf-8') as f_c:
                creds = json.load(f_c)
                if creds and (creds.get('me') or creds.get('registered')):
                    has_valid_creds = True
        except Exception:
            pass

    target_file = status_file if os.path.exists(status_file) else legacy_status
    if os.path.exists(target_file):
        try:
            with open(target_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                status = data.get('status', 'disconnected')
                qr = data.get('qr')
                ts = data.get('ts', 0)
                now_ts = int(time.time() * 1000)

                # Si las credenciales son válidas y no se está pidiendo un QR nuevo en los últimos 20s
                if has_valid_creds and (status != 'qr_ready' or (now_ts - ts) > 20000):
                    return jsonify({'status': 'connected', 'usuario': current_user.usuario, 'qr': None})

                return jsonify({
                    'status': status, 
                    'usuario': current_user.usuario,
                    'qr': qr
                })
        except: pass

    if has_valid_creds:
        return jsonify({'status': 'connected', 'usuario': current_user.usuario, 'qr': None})

    return jsonify({'status': 'disconnected', 'usuario': current_user.usuario, 'qr': None})

@captacion_outreach_bp.route('/logout_whatsapp', methods=['GET', 'POST'])
@login_required
def logout_whatsapp():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.args.get('ajax')
    import shutil, json, time
    session_dir = os.path.join(os.path.expanduser('~'), f'.whatsapp_bot_session_{current_user.usuario}')
    status_file = os.path.join(os.getcwd(), 'static', 'uploads', f'status_historias_{current_user.usuario}.json')
    legacy_status = os.path.join(os.getcwd(), 'static', 'uploads', f'status_{current_user.usuario}.json')
    qr_file = os.path.join(os.getcwd(), 'static', 'uploads', f'qr_historias_{current_user.usuario}.png')
    legacy_qr = os.path.join(os.getcwd(), 'static', 'uploads', f'qr_{current_user.usuario}.png')
    
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                old_pid = data.get('pid')
                if old_pid:
                    subprocess.run(["taskkill", "/F", "/PID", str(old_pid)], creationflags=0x08000000)
        except: pass

    try:
        time.sleep(0.5)
        if os.path.exists(session_dir): shutil.rmtree(session_dir, ignore_errors=True)
        if os.path.exists(status_file): os.remove(status_file)
        if os.path.exists(legacy_status): os.remove(legacy_status)
        if os.path.exists(qr_file): os.remove(qr_file)
        if os.path.exists(legacy_qr): os.remove(legacy_qr)
        if is_ajax:
            return jsonify({'status': 'disconnected', 'message': 'Sesión desconectada'})
        flash("Sesión de WhatsApp desconectada con éxito.", "success")
    except Exception as e:
        if is_ajax:
            return jsonify({'error': str(e)}), 500
        flash(f"No se pudo desconectar WhatsApp: {e}", "danger")
    return redirect(request.referrer or url_for('index'))

@captacion_outreach_bp.route('/publicar_historias_manualmente')
@login_required
def publicar_historias_manualmente():
    """Lanza el worker global en un proceso separado (modo manual temporal)."""
    try:
        script_path = os.path.join(os.getcwd(), 'lib', 'whatsapp_sender.py')
        cmd = [sys.executable, script_path]
        subprocess.Popen(cmd, creationflags=0x08000000 if os.name == 'nt' else 0)
        flash("Worker global de WhatsApp iniciado en segundo plano...", "success")
    except Exception as e:
        flash(f"Error al iniciar worker: {e}", "error")
    return redirect(request.referrer or url_for('index'))

@captacion_outreach_bp.route('/comunicaciones/borrar/<int:cid>', methods=['GET', 'POST'])
@login_required
@superadmin_required
def borrar_comunicacion(cid):
    """Borrar una comunicación de la cola."""
    db.delete_comunicacion(cid)
    flash("Comunicación eliminada de la cola", "warning")
    return redirect(request.referrer or url_for('captacion_outreach.comunicaciones'))

@captacion_outreach_bp.route('/comunicaciones')
@login_required
@superadmin_required
def comunicaciones():
    """Lista de comunicaciones pendientes y enviadas (Solo SuperAdmin)."""
    comms = db.get_comunicaciones()
    return render_template('comunicaciones.html', comms=comms)

@captacion_outreach_bp.route('/comunicaciones/<int:cid>/marcar_enviada')
@login_required
@superadmin_required
def marcar_enviada(cid):
    db.marcar_comunicacion_enviada(cid)
    return redirect(request.referrer or url_for('captacion_outreach.comunicaciones'))

@captacion_outreach_bp.route('/test_email', methods=['POST'])
@login_required
def test_email():
    """Prueba de envío de email SMTP."""
    from lib.automation import send_email
    email = request.form.get('test_email_dest')
    if not email:
        return jsonify({'status': 'error', 'message': 'Falta el email de destino'})
    
    asunto = "Prueba de Captador de Propiedades"
    mensaje = "Si estás leyendo esto, tu configuración SMTP funciona correctamente!"
    
    current_uid = current_user.id if current_user and current_user.is_authenticated else None
    if send_email(email, asunto, mensaje, is_html=False, agente_id=current_uid):
        return jsonify({'status': 'success', 'message': f'Email de prueba enviado a {email}'})
    else:
        return jsonify({'status': 'error', 'message': 'Falló el envío. Revisa la configuración SMTP y la terminal para más detalles.'})

@captacion_outreach_bp.route('/test_whatsapp', methods=['POST'])
@login_required
def test_whatsapp():
    """Envía un mensaje de prueba al número configurado."""
    test_phone = clean_phone_argentina(request.form.get('test_phone'))
    
    if not test_phone:
        return jsonify({'status': 'error', 'message': 'Falta el número de destino o es inválido'})
    
    # Asegurarnos de que exista la propiedad 'SISTEMA' con ID 0 para pruebas
    conn = db.get_db()
    try:
        # Intentamos insertar la propiedad 0 si no existe
        conn.execute("""
            INSERT OR IGNORE INTO propiedades (id, portal, url, titulo, telefono) 
            VALUES (0, 'sistema', 'http://sistema.test', '🤖 SISTEMA (Pruebas)', ?)
        """, (test_phone,))
        
        # Siempre actualizamos el teléfono de la propiedad 0 con el que se puso ahora
        conn.execute("UPDATE propiedades SET telefono = ? WHERE id = 0", (test_phone,))
        conn.commit()
    except Exception as e:
        print(f"Error gestionando propiedad de sistema: {e}")
        conn.rollback()
    finally:
        conn.close()

    mensaje = "¡Hola! Si estás leyendo esto, tu bridge de WhatsApp está funcionando correctamente. 🦾🏠"
    
    # Encolar el mensaje para la propiedad 0
    comm_data = {
        'propiedad_id': 0,
        'tipo': 'whatsapp',
        'mensaje': mensaje,
        'estado': 'pendiente',
        'paso': 0
    }
    db.insert_comunicacion(comm_data)
    
    return jsonify({
        'status': 'success', 
        'message': f'¡Listo! Mensaje encolado para {test_phone}. Verificá la ventana del Bridge.'
    })

@captacion_outreach_bp.route('/test_full_cycle')
@login_required
def test_full_cycle():
    """Prueba instantánea: IA + Cola sobre la propiedad más reciente (evita timeout de scrapeo)."""
    busquedas = db.get_busquedas()
    activa = next((b for b in busquedas if b['activa']), None)
    
    if not activa:
        return jsonify({'status': 'error', 'message': 'No hay búsquedas activas. Configurá una en "Búsquedas".'})
    
    # 1. Intentar buscar una propiedad reciente que NO haya sido contactada (Deduplicación 8 dígitos)
    conn = db.get_db()
    query = """
    SELECT p.* FROM propiedades p
    WHERE p.telefono IS NOT NULL AND LENGTH(p.telefono) >= 8
    AND p.id > 0 -- Saltar propiedad de sistema
    AND NOT EXISTS (
        SELECT 1 FROM comunicaciones c
        JOIN propiedades p2 ON c.propiedad_id = p2.id
        WHERE SUBSTR(p2.telefono, -8) = SUBSTR(p.telefono, -8)
    )
    ORDER BY p.id DESC LIMIT 1
    """
    prop = conn.execute(query).fetchone()
    conn.close()
    
    # Si no hay propiedades, avisar
    if not prop: 
        return jsonify({
            'status': 'error', 
            'message': 'No encontré propiedades nuevas en tu base. Por favor, ejecutá el Scraper manualmente una vez o esperá a que el bot encuentre algo nuevo.'
        })
    
    prop = dict(prop)
    print(f"Iniciando prueba de ciclo con propiedad existente: {prop['titulo']}")
    
    # 2. Generar mensaje con IA (Rotación aleatoria para la prueba)
    estrategia = random.choice(['marketing', 'red_ferrari'])
    mensaje = generar_mensaje_ia(prop, estrategia)
    
    if mensaje.startswith("Error"):
        return jsonify({'status': 'error', 'message': f'Error en Gemini: {mensaje}'})
    
    # 3. Meter en la cola
    comm_data = {
        'propiedad_id': prop['id'],
        'tipo': 'whatsapp',
        'mensaje': mensaje,
        'estado': 'pendiente',
        'paso': 1,
        'estrategia_usada': estrategia
    }
    db.insert_comunicacion(comm_data)
    
    return jsonify({
        'status': 'success', 
        'message': f'¡Prueba exitosa! Usando propiedad: "{prop["titulo"][:35]}...". Estrategia: {estrategia}.',
        'preview': mensaje
    })

# --- Scraper Control ---

@captacion_outreach_bp.route('/ejecutar_scraper/<int:bid>')
@login_required
@superadmin_required
def ejecutar_scraper(bid):
    """Ejecutar un scraper específico a través del motor remoto."""
    busqueda = next((b for b in db.get_busquedas() if b['id'] == bid), None)
    if not busqueda:
        return "Búsqueda no encontrada", 404

    # Disparar búsqueda asíncrona hacia el motor centralizado
    job_uuid = ScraperClient.trigger_async_search({
        'portal': busqueda.get('portal', 'zonaprop'),
        'zona': busqueda.get('zona', 'CABA'),
        'url_busqueda': busqueda.get('url_busqueda', '')
    }, max_pages=4)

    if job_uuid:
        flash(f"Scraping delegado al motor central de scraping (Job: {job_uuid[:8]}). Las propiedades se sincronizarán en minutos.", "success")
    else:
        flash("La petición fue enviada al motor de scraping. Verificá que el servidor esté activo en Configuración.", "info")

    return redirect(url_for('captacion_outreach.busquedas'))

@captacion_outreach_bp.route('/limpiar_inactivas/<int:bid>')
@login_required
@superadmin_required
def limpiar_inactivas(bid):
    """Ejecuta el job en segundo plano para verificar links caídos en una búsqueda dada."""
    try:
        from lib.link_validator import validar_links_inactivos
        inactivas, activas = validar_links_inactivos(busqueda_id=bid, limit=20)
        flash(f"Análisis de inactivas completo: {inactivas} marcadas como vendidas. ({activas} confirmadas activas).", "info")
    except Exception as e:
        flash(f"Error al analizar inactivas: {str(e)}", "danger")
        
    return redirect(url_for('captacion_outreach.busquedas'))

@captacion_outreach_bp.route('/busqueda/<int:bid>/limpiar', methods=['GET', 'POST'])
@login_required
@superadmin_required
def limpiar_busqueda(bid):
    """Borrar todos los resultados de una búsqueda."""
    db.delete_propiedades_by_busqueda(bid)
    flash("Se eliminaron todos los resultados de la búsqueda", "warning")
    return redirect(url_for('captacion_outreach.busquedas'))

@captacion_outreach_bp.route('/propiedad/borrar/<int:pid>', methods=['GET', 'POST'])
@login_required
@superadmin_required
def borrar_propiedad(pid):
    """Borrar una propiedad individual."""
    db.delete_propiedad(pid)
    flash("Propiedad eliminada", "warning")
    return redirect(request.referrer or url_for('captacion_outreach.propiedades_view'))

@captacion_outreach_bp.route('/propiedades/borrar_bulk', methods=['POST'])
@login_required
@superadmin_required
def borrar_propiedades_bulk():
    """Borrar múltiples propiedades seleccionadas."""
    prop_ids = request.form.getlist('prop_ids')
    if prop_ids:
        # Convert to int list
        prop_ids = [int(pid) for pid in prop_ids]
        db.delete_propiedades_bulk(prop_ids)
        flash(f"Se eliminaron {len(prop_ids)} propiedades", "warning")
    else:
        flash("No seleccionaste ninguna propiedad", "info")
    return redirect(url_for('captacion_outreach.propiedades_view'))

@captacion_outreach_bp.route('/enviar_lote_5')
@privilege_required('accion', 'enviar_lote_5')
def enviar_lote_5():
    """Lanzar un ciclo completo: Captación (Scraping) + 5 nuevos + 5 seguimientos."""
    # Load the 10-week planner messages upfront
    planificador = db.get_planificador()
    plan_por_semana = {s['semana']: s for s in planificador}
    
    def obtener_mensaje_planificador(propiedad, paso):
        """Get the planner message for a given week/step, with placeholder replacement.
        Returns the message string or None if no planner message is configured."""
        semana = plan_por_semana.get(paso)
        if semana and semana.get('habilitado') and semana.get('mensaje', '').strip():
            msg = semana['mensaje']
            from lib.utils import extraer_nombre_pila
            
            raw_nombre = propiedad.get('nombre_contacto') or 'propietario'
            nombre_limpio = extraer_nombre_pila(raw_nombre) if raw_nombre.lower() != 'propietario' else 'propietario'
            
            # Replace placeholders
            placeholders = {
                'nombre': nombre_limpio,
                'direccion': propiedad.get('direccion') or propiedad.get('titulo', 'tu propiedad'),
                'barrio': propiedad.get('barrio') or '',
                'portal': (propiedad.get('portal') or '').capitalize(),
            }
            try:
                return msg.format(**placeholders)
            except (KeyError, ValueError):
                # If placeholder replacement fails, return the raw message
                return msg
        return None
    
    # 1. Propiedades para enviar en automatización
    nuevas_para_enviar = db.get_ready_for_step1(5)
    enviados_nuevos = 0
    for p in nuevas_para_enviar:
        # Priority 1: Use planner message for week 1
        mensaje = obtener_mensaje_planificador(p, 1)
        estrategia = 'planificador_semana_1'
        
        # Priority 2: Fall back to Gemini IA
        if not mensaje:
            estrategia = random.choice(['marketing', 'red_ferrari'])
            mensaje = generar_mensaje_ia(p, estrategia)
        
        if mensaje and not mensaje.startswith("Error"):
            comm_data = {
                'propiedad_id': p['id'],
                'tipo': 'whatsapp',
                'mensaje': mensaje,
                'estado': 'pendiente',
                'paso': 1,
                'estrategia_usada': estrategia
            }
            db.insert_comunicacion(comm_data)
            db.update_propiedad_estado(p['id'], 'contactada')
            enviados_nuevos += 1
            
    # 3. Seguimientos DISTRIBUIDOS (5 por semana, Drip Marketing hasta Semana 10)
    seguimientos = db.get_ready_for_next_step(limit=45, limit_per_week=5)
    enviados_seguimientos = 0
    semanas_enviadas = []
    for p in seguimientos:
        paso = p['siguiente_paso']
        
        # Priority 1: Use planner message for this week
        mensaje = obtener_mensaje_planificador(p, paso)
        estrategia = f'planificador_semana_{paso}'
        
        # Priority 2: Fall back to Gemini IA
        if not mensaje:
            estrategia = f'followup_semana_{paso}'
            mensaje = generar_mensaje_ia(p, estrategia)
        
        if mensaje and not mensaje.startswith("Error"):
            comm_data = {
                'propiedad_id': p['id'],
                'tipo': 'whatsapp',
                'mensaje': mensaje,
                'estado': 'pendiente',
                'paso': paso,
                'estrategia_usada': estrategia
            }
            db.insert_comunicacion(comm_data)
            # Mark as en_seguimiento (STOP at 10 is handled by marcar_comunicacion_enviada)
            db.update_propiedad_estado(p['id'], 'en_seguimiento')
            enviados_seguimientos += 1
            semanas_enviadas.append(paso)

    # 4. Marcar tarea en el dashboard
    db.update_tarea_diaria('lanzar_lote_5_5', 1)

    # Build summary message
    plan_usado = sum(1 for s in plan_por_semana.values() if s.get('habilitado') and s.get('mensaje', '').strip())
    total = enviados_nuevos + enviados_seguimientos
    semanas_str = ', '.join([f'S{s}' for s in semanas_enviadas]) if semanas_enviadas else 'ninguna'
    msg = f"Ciclo completado: {nuevas_captadas} captadas, {total} encolados ({enviados_nuevos} nuevos + {enviados_seguimientos} seguimientos: {semanas_str}). Planificador: {plan_usado}/10 semanas activas."
    flash(msg, "success")
    
    return redirect(url_for('index'))

@captacion_outreach_bp.route('/lanzar_automatizacion')
@privilege_required('accion', 'lanzar_automatizacion')
def lanzar_automatizacion():
    """Run one cycle of the automation worker synchronously."""
    try:
        from lib.automation_worker import procesar_automatizacion
        result = procesar_automatizacion()
        if result:
            flash(f"Automatización: {result}", "success")
        else:
            flash("Automatización ejecutada correctamente.", "success")
    except Exception as e:
        flash(f"Error en automatización: {str(e)}", "danger")
    return redirect(url_for('index'))

@captacion_outreach_bp.route('/update_daily_task', methods=['POST'])
@login_required
def update_daily_task():
    """Update a specific daily task from the dashboard."""
    campo = request.form.get('campo')
    valor = int(request.form.get('valor', 0))
    db.update_tarea_diaria(campo, valor)
    return jsonify({'status': 'success'})
