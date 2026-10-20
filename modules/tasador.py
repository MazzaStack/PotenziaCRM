"""
CRM Module for Property Valuation (Tasador)
"""
import os
import json
import re
from datetime import datetime
from flask import Blueprint, request, render_template, jsonify
from flask_login import login_required
from database import db

tasador_bp = Blueprint('tasador', __name__)

def log_fallback_error(error_message):
    """Logs error message to logs/fallback_debug.log at most once per calendar day."""
    try:
        log_dir = os.path.join(db.DB_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "fallback_debug.log")
        
        already_logged_today = False
        if os.path.exists(log_file):
            try:
                mtime = os.path.getmtime(log_file)
                mdate = datetime.fromtimestamp(mtime).date()
                if mdate == datetime.now().date():
                    already_logged_today = True
            except Exception as e:
                print(f"Error checking fallback log date: {e}")
                
        if not already_logged_today:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error_message}\n")
    except Exception as e:
        print(f"Error writing fallback log: {e}")

@tasador_bp.route('/tasador', methods=['GET', 'POST'])
@login_required
def tasador():
    """Smart Valuation Tool with Map Support and Persistency."""
    resultado = None
    if request.method == 'POST':
        zona = request.form.get('zona', '')
        tipo = request.form.get('tipo_propiedad')
        metros_str = request.form.get('metros', '0')
        metros = float(metros_str) if metros_str else 0
        
        # New parameters
        metodo_metros = request.form.get('metodo_metros', 'totales')
        metros_cubiertos_str = request.form.get('metros_cubiertos', '')
        metros_cubiertos = float(metros_cubiertos_str) if metros_cubiertos_str else None
        descartar_mal_cargados = True if request.form.get('descartar_mal_cargados') == '1' else False
        solo_geolocalizadas = True if request.form.get('solo_geolocalizadas') == '1' else False
        filtro_estricto_barrio = True if request.form.get('filtro_estricto_barrio') == '1' else False
        
        rango_negativo_str = request.form.get('rango_negativo', '25')
        rango_positivo_str = request.form.get('rango_positivo', '25')
        try:
            rango_negativo = float(rango_negativo_str) / 100.0 if rango_negativo_str else 0.25
        except ValueError:
            rango_negativo = 0.25
            
        try:
            rango_positivo = float(rango_positivo_str) / 100.0 if rango_positivo_str else 0.25
        except ValueError:
            rango_positivo = 0.25
        
        ambientes = request.form.getlist('ambientes')
        if request.form.get('ambientes_cualquier') == '1':
            ambientes = []
            
        lat_str = request.form.get('lat')
        lng_str = request.form.get('lng')
        radio = float(request.form.get('radio', 1.0))
        min_m2_usd = float(request.form.get('min_m2_usd', 0)) if request.form.get('min_m2_usd') else 0
        
        modo_busqueda = request.form.get('modo_busqueda', 'zona')
        if modo_busqueda == 'zona':
            lat = None
            lng = None
        else:
            lat = float(lat_str) if lat_str and lat_str.strip() else None
            lng = float(lng_str) if lng_str and lng_str.strip() else None
        
        tasador_estado_activo = request.form.get('tasador_estado_activo') == '1'
        estado_propiedad = request.form.get('estado_propiedad', 'bueno')
        country_activo = request.form.get('country_activo') == '1'
        country_ubicacion = request.form.get('country_ubicacion', 'interno')
        tokko_activo = request.form.get('tokko_activo') == '1'
        tokko_antiguedad = int(request.form.get('tokko_antiguedad', 60))
        tokko_ignorar_fuera = request.form.get('tokko_ignorar_fuera') == '1'
        
        # Calculate dynamic target surface for final pricing multiplier
        metros_calc = metros
        if metodo_metros == 'cubiertos' and metros_cubiertos:
            metros_calc = metros_cubiertos
        elif metodo_metros == 'homogeneizados' and metros_cubiertos is not None:
            descubiertos = max(0.0, metros - metros_cubiertos)
            metros_calc = metros_cubiertos + descubiertos * 0.2
            
        # LIVE SEARCH Integration (User switch: ON = Live Probe to Portals, OFF = 100% Local DB)
        forzar_live_search = True if request.form.get('forzar_live_search') == '1' else False
        is_fallback = False
        live_results = []
        if zona and forzar_live_search:
            try:
                print(f"[Tasador Agentes] Sondeo en tiempo real (Live Search) ACTIVADO para '{zona}' ({tipo}). Consultando al Servidor de Scraping vía API...")
                min_m2 = metros_calc * (1.0 - rango_negativo) if metros_calc > 0 else None
                max_m2 = metros_calc * (1.0 + rango_positivo) if metros_calc > 0 else None
                
                from lib.scraper_client import ScraperClient
                ext_props, total_found = ScraperClient.search_properties({
                    'zona': zona,
                    'tipo_propiedad': tipo,
                    'ambientes': ambientes
                }, limit=15)
                live_results = ext_props
            except Exception as e:
                is_fallback = True
                log_fallback_error(f"LiveProber exception for {zona}: {str(e)}")
        elif zona and not forzar_live_search:
            print(f"[Tasador Agentes] Sondeo en tiempo real (Live Search) DESACTIVADO para '{zona}' ({tipo}). Cálculo instantáneo sobre base local.")
            
        precios = None
        if tokko_activo:
            from plugins.tokko.tokko_matcher import get_tasacion_tokko
            precios = get_tasacion_tokko(
                zona,
                tipo,
                tipo_operacion="venta",
                metros=metros,
                ambientes=ambientes,
                max_antiguedad_meses=tokko_antiguedad / 30.0,
                ignore_out_of_market=tokko_ignorar_fuera,
                min_m2_usd=min_m2_usd,
                metodo_metros=metodo_metros,
                metros_cubiertos=metros_cubiertos,
                descartar_mal_cargados=descartar_mal_cargados,
                rango_negativo=rango_negativo,
                rango_positivo=rango_positivo,
                filtro_estricto_barrio=filtro_estricto_barrio
            )
        elif lat is not None and lng is not None:
            precios = db.get_tasacion_geografica(
                lat, lng, radio, tipo, metros=metros, ambientes=ambientes, 
                live_results=live_results, zona_name=zona, min_m2_usd=min_m2_usd,
                metodo_metros=metodo_metros, metros_cubiertos=metros_cubiertos,
                descartar_mal_cargados=descartar_mal_cargados,
                rango_negativo=rango_negativo, rango_positivo=rango_positivo,
                solo_geolocalizadas=solo_geolocalizadas,
                filtro_estricto_barrio=filtro_estricto_barrio
            )
            if not precios and zona:
                print(f"  DEBUG: Fallback a búsqueda por zona para '{zona}'")
                precios = db.get_tasacion_zona(
                    zona, tipo, metros=metros, live_results=live_results, 
                    ambientes=ambientes, min_m2_usd=min_m2_usd,
                    metodo_metros=metodo_metros, metros_cubiertos=metros_cubiertos,
                    descartar_mal_cargados=descartar_mal_cargados,
                    rango_negativo=rango_negativo, rango_positivo=rango_positivo,
                    filtro_estricto_barrio=filtro_estricto_barrio
                )
        elif zona:
            precios = db.get_tasacion_zona(
                zona, tipo, metros=metros, live_results=live_results, 
                ambientes=ambientes, min_m2_usd=min_m2_usd,
                metodo_metros=metodo_metros, metros_cubiertos=metros_cubiertos,
                descartar_mal_cargados=descartar_mal_cargados,
                rango_negativo=rango_negativo, rango_positivo=rango_positivo,
                filtro_estricto_barrio=filtro_estricto_barrio
            )
            
        resultado = {
            'zona': zona,
            'tipo': tipo,
            'metros': metros_str,
            'metros_cubiertos': metros_cubiertos_str if metros_cubiertos_str else '',
            'metodo_metros': metodo_metros,
            'descartar_mal_cargados': descartar_mal_cargados,
            'solo_geolocalizadas': solo_geolocalizadas,
            'filtro_estricto_barrio': filtro_estricto_barrio,
            'forzar_live_search': forzar_live_search,
            'ambientes': ambientes,
            'lat': lat if lat is not None else '',
            'lng': lng if lng is not None else '',
            'radio': radio,
            'rango_negativo': int(rango_negativo * 100),
            'rango_positivo': int(rango_positivo * 100),
            'estado_propiedad': estado_propiedad,
            'tasador_estado_activo': tasador_estado_activo,
            'country_activo': country_activo,
            'country_ubicacion': country_ubicacion,
            'tokko_activo': tokko_activo,
            'tokko_antiguedad': tokko_antiguedad,
            'tokko_ignorar_fuera': tokko_ignorar_fuera,
            'has_data': False,
            'is_fallback': is_fallback,
            'modo_busqueda': modo_busqueda
        }
        
        if precios:
            multiplier = (metros_calc if precios['usa_m2'] else 1)
            final_bajo = precios['bajo'] * multiplier
            final_medio = precios['medio'] * multiplier
            final_alto = precios['alto'] * multiplier
            
            # Apply base market offset from Configuration
            base_offset_str = db.get_config('tasador_ajuste_base', '0')
            try:
                base_offset_pct = float(base_offset_str) / 100.0
            except ValueError:
                base_offset_pct = 0.0
                
            final_bajo = final_bajo * (1.0 + base_offset_pct)
            final_medio = final_medio * (1.0 + base_offset_pct)
            final_alto = final_alto * (1.0 + base_offset_pct)
            
            # State Adjusted Price Calculation
            ajuste_pct = 0.0
            if tasador_estado_activo:
                if estado_propiedad == 'estrenar':
                    ajuste_pct = float(db.get_config('tasador_ajuste_estrenar') or 15) / 100.0
                elif estado_propiedad == 'muybueno':
                    ajuste_pct = float(db.get_config('tasador_ajuste_muybueno') or 10) / 100.0
                elif estado_propiedad == 'refaccionar':
                    ajuste_pct = -float(db.get_config('tasador_ajuste_refaccionar') or 15) / 100.0
                elif estado_propiedad == 'malo':
                    ajuste_pct = -float(db.get_config('tasador_ajuste_malo') or 35) / 100.0
            
            medio_ajustado = final_medio * (1.0 + ajuste_pct)
            
            # Country / Barrio Cerrado adjustment
            country_ajuste_pct = 0.0
            country_label = ''
            if country_activo:
                if country_ubicacion == 'laguna':
                    country_ajuste_pct = float(db.get_config('tasador_country_laguna', '10')) / 100.0
                    country_label = 'Salida a Laguna'
                elif country_ubicacion == 'perimetral':
                    country_ajuste_pct = -float(db.get_config('tasador_country_perimetral', '10')) / 100.0
                    country_label = 'Perimetral'
                else:
                    country_ajuste_pct = 0.0
                    country_label = 'Interno'
            
            medio_country = final_medio * (1.0 + country_ajuste_pct)
            m2_medio_ajustado = final_medio / metros_calc if metros_calc > 0 else (precios.get('m2_medio', 0) * (1.0 + base_offset_pct))
            
            resultado.update({
                'has_data': True,
                'bajo': final_bajo,
                'medio': final_medio,
                'alto': final_alto,
                'medio_ajustado': medio_ajustado,
                'bajo_m2': final_bajo / metros_calc if metros_calc > 0 else 0,
                'medio_m2': final_medio / metros_calc if metros_calc > 0 else 0,
                'alto_m2': final_alto / metros_calc if metros_calc > 0 else 0,
                'm2_medio': m2_medio_ajustado,
                'muestra': precios.get('muestra', 0),
                'area_filtrada': precios.get('area_filtrada', False),
                'has_live': precios.get('has_live', False),
                'comparables': precios.get('comparables', []),
                'country_ajuste_pct': country_ajuste_pct,
                'medio_country': medio_country,
                'base_offset_pct': base_offset_pct,
            })
            
    return render_template('tasador.html', resultado=resultado, config=db.get_all_config())

@tasador_bp.route('/crm/acm_report', methods=['POST'])
@login_required
def acm_report():
    """Generates a high-fidelity Market Comparative Analysis report."""
    data = request.form
    if request.is_json:
        data = request.json
        
    # Calculate covered and uncovered meters
    metros_tot = 0.0
    metros_cub = 0.0
    try:
        metros_tot = float(data.get('metros', 0) or 0)
    except:
        pass
    
    metros_cub_str = data.get('metros_cubiertos', '')
    try:
        metros_cub = float(metros_cub_str) if metros_cub_str else metros_tot
    except:
        metros_cub = metros_tot
        
    metros_desc = max(0.0, metros_tot - metros_cub)
    
    def fmt_val(v):
        if v == int(v):
            return str(int(v))
        return f"{v:.1f}"
        
    report_data = {
        'zona': data.get('zona'),
        'tipo': data.get('tipo'),
        'metros': data.get('metros'),
        'metros_cubiertos': fmt_val(metros_cub) if metros_cub > 0 else fmt_val(metros_tot),
        'metros_descubiertos': fmt_val(metros_desc),
        'metodo_metros': data.get('metodo_metros', 'totales'),
        'bajo': float(data.get('bajo', 0)),
        'medio': float(data.get('medio', 0)),
        'alto': float(data.get('alto', 0)),
        'm2_medio': float(data.get('m2_medio', 0)),
        'muestra': data.get('muestra'),
        'comparables': json.loads(data.get('comparables_json', '[]')),
        'lat': data.get('lat'),
        'lng': data.get('lng'),
        'agente_nombre': data.get('agente_nombre', 'Germán Mazzaferro'),
        'agente_firma': data.get('agente_firma', ''),
        'estado_propiedad': data.get('estado_propiedad', ''),
        'medio_ajustado': data.get('medio_ajustado', ''),
        'tasador_estado_activo': data.get('tasador_estado_activo') == '1',
        'tokko_activo': data.get('tokko_activo') == '1',
        'tokko_antiguedad': data.get('tokko_antiguedad', '60'),
        'tokko_ignorar_fuera': data.get('tokko_ignorar_fuera') == '1',
        'modo_busqueda': data.get('modo_busqueda', 'zona')
    }
    
    return render_template('acm_report.html', r=report_data)

@tasador_bp.route('/crm/reporte_tasacion', methods=['POST'])
@login_required
def reporte_tasacion():
    """Generate professional WA report for valuation."""
    data = request.json
    
    zona = data.get('zona', 'la zona indicada')
    tipo = data.get('tipo', 'propiedad')
    metros = data.get('metros', '?')
    bajo = data.get('bajo', '?')
    medio = data.get('medio', '?')
    alto = data.get('alto', '?')
    m2_medio = data.get('m2_medio', '')
    estado_propiedad = data.get('estado_propiedad', '')
    medio_ajustado = data.get('medio_ajustado', '')
    
    # Textual representation of property state
    estado_map = {
        'estrenar': 'A Estrenar / Nuevo',
        'muybueno': 'Muy Bueno / Reciclado',
        'refaccionar': 'A Refaccionar / Regular',
        'malo': 'Malo / Crítico',
        'bueno': 'Bueno / Estándar'
    }
    estado_texto = estado_map.get(estado_propiedad, '')
    
    # Build fallback message
    fallback = f"Hola! Te comparto el análisis de mercado que preparé para tu {tipo} en {zona} ({metros}m²).\n\n"
    if estado_texto and medio_ajustado:
        # User specified not explaining the math, just outputting the direct adjusted sentence
        fallback += f"Considerando el estado de conservación {estado_texto}, el valor de mercado sugerido se ajusta a USD {float(medio_ajustado):,.0f}\n\n"
    else:
        fallback += (
            f"Valores detectados en la zona:\n"
            f"  Piso de Mercado: USD {bajo}\n"
            f"  Valor Competitivo: USD {medio}\n"
            f"  Techo Premium: USD {alto}\n"
        )
    if m2_medio:
        fallback += f"El valor promedio por m² en la zona es de USD {m2_medio}/m².\n"
    fallback += (
        f"\nEstos valores surgen de un análisis comparativo con propiedades similares publicadas actualmente.\n\n"
        f"Si te interesa, podemos coordinar una visita para hacer una tasación presencial más precisa. Quedá a disposición!"
    )
    
    try:
        from lib.gemini_service import get_gemini_client
        client = get_gemini_client()
        
        prompt = f"""
        Generá un mensaje profesional de WhatsApp para un cliente inmobiliario. 
        German realizó una tasación rápida para una propiedad tipo {tipo} en {zona} de {metros}m2.
        Valores detectados en mercado:
        - Rango Base: USD {bajo}
        - Valor Competitivo: USD {medio}
        - Rango Premium: USD {alto}
        {'- Valor promedio por m2: USD ' + str(m2_medio) if m2_medio else ''}
        """
        
        if estado_texto and medio_ajustado:
            prompt += f"\n- NOTA IMPORTANTE: Debes incluir la siguiente frase exacta en el mensaje: 'Considerando el estado de conservación {estado_texto}, el valor de mercado sugerido se ajusta a USD {float(medio_ajustado):,.0f}'. No des explicaciones matemáticas sobre el ajuste, solo menciona la frase de manera natural en el cuerpo del mensaje.\n"
            
        prompt += """
        El mensaje debe ser cordial, experto y terminar invitando a una tasación presencial para ajustar detalles.
        NO menciones pertenecer a ninguna inmobiliaria en particular a menos que se indique expresamente.
        Máximo 500 caracteres.
        """
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        if response and response.text:
            return jsonify({'mensaje': response.text.strip()})
        else:
            return jsonify({'mensaje': fallback})
    except Exception as e:
        print(f"[Tasador] Gemini error: {e}")
        return jsonify({'mensaje': fallback})
