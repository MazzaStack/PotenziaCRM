"""
Módulo de Analítica y Rendimiento para Agentes y Broker / Inmobiliaria.
Proporciona KPIs, embudos de conversión, rendimiento individual y métricas consolidadas.
"""
from datetime import datetime, timedelta
import json
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from database import db

analitica_bp = Blueprint('analitica', __name__, url_prefix='/analitica')


def _safe_float(val, default=0.0):
    try:
        if val is None or val == '':
            return default
        if isinstance(val, str):
            clean = val.replace('$', '').replace('USD', '').replace('ARS', '').replace('.', '').replace(',', '.').strip()
            return float(clean)
        return float(val)
    except Exception:
        return default


def calcular_metricas_analitica(agente_id=None, oficina_id=None):
    """
    Calcula todas las métricas de rendimiento para la inmobiliaria o un agente específico.
    Si agente_id es None, calcula el consolidado de la oficina (si oficina_id está definido) o global (si oficina_id es None).
    """
    conn = db.get_db()
    
    try:
        # ─────────────────────────────────────────────────────────────
        # 1. PROPIEDADES EN CARTERA
        # ─────────────────────────────────────────────────────────────
        if agente_id is not None:
            prop_where = "WHERE agente_id = ?"
            prop_params = (agente_id,)
        elif oficina_id is not None:
            prop_where = "WHERE agente_id IN (SELECT id FROM usuarios WHERE oficina_id = ?)"
            prop_params = (oficina_id,)
        else:
            prop_where = ""
            prop_params = ()
        
        q_props = f"SELECT COUNT(*), COALESCE(tipo_operacion, 'venta') as operacion, COALESCE(tipo_propiedad, 'departamento') as tipo, COALESCE(barrio, 'Sin especificar') as barrio, precio, moneda FROM propiedades {prop_where} GROUP BY tipo_operacion, tipo_propiedad, barrio, precio, moneda"
        rows_props = conn.execute(q_props, prop_params).fetchall()
        
        total_propiedades = 0
        props_venta = 0
        props_alquiler = 0
        props_por_tipo = {}
        props_por_barrio = {}
        precios_venta = []
        
        for r in rows_props:
            count = r[0]
            op = str(r[1]).lower()
            tipo = str(r[2]).capitalize()
            barrio = str(r[3]).strip()
            precio = _safe_float(r[4])
            moneda = str(r[5] or 'USD').upper()
            
            total_propiedades += count
            if 'alquiler' in op:
                props_alquiler += count
            else:
                props_venta += count
                if precio > 5000 and moneda == 'USD':
                    precios_venta.append(precio)
                    
            props_por_tipo[tipo] = props_por_tipo.get(tipo, 0) + count
            if barrio and barrio != 'Sin especificar':
                props_por_barrio[barrio] = props_por_barrio.get(barrio, 0) + count

        top_barrios = sorted(props_por_barrio.items(), key=lambda x: x[1], reverse=True)[:6]
        ticket_promedio_venta = round(sum(precios_venta) / len(precios_venta), 0) if precios_venta else 0

        # ─────────────────────────────────────────────────────────────
        # 2. CONTACTOS Y CLIENTES
        # ─────────────────────────────────────────────────────────────
        if agente_id is not None:
            cont_where = "WHERE agente_id = ?"
            cont_params = (agente_id,)
        elif oficina_id is not None:
            cont_where = "WHERE agente_id IN (SELECT id FROM usuarios WHERE oficina_id = ?)"
            cont_params = (oficina_id,)
        else:
            cont_where = ""
            cont_params = ()
        
        q_contactos = f"SELECT id, calificacion, busqueda_activa, recordatorio_activo, ultimo_contacto, rol, categoria FROM contactos {cont_where}"
        rows_contactos = conn.execute(q_contactos, cont_params).fetchall()
        
        total_contactos = len(rows_contactos)
        contactos_calificados = 0
        contactos_busqueda_activa = 0
        contactos_recordatorio = 0
        contactos_frios = 0
        contactos_por_rol = {}
        
        now = datetime.now()
        for c in rows_contactos:
            calif = c['calificacion'] or 0
            if calif >= 4:
                contactos_calificados += 1
            if c['busqueda_activa']:
                contactos_busqueda_activa += 1
            if c['recordatorio_activo']:
                contactos_recordatorio += 1
                
            rol = str(c['rol'] or 'Cliente').capitalize()
            contactos_por_rol[rol] = contactos_por_rol.get(rol, 0) + 1
            
            ult = c['ultimo_contacto']
            if ult:
                try:
                    ult_str = str(ult)[:10]
                    ult_date = datetime.strptime(ult_str, '%Y-%m-%d')
                    if (now - ult_date).days > 30:
                        contactos_frios += 1
                except Exception:
                    pass
            else:
                contactos_frios += 1

        # ─────────────────────────────────────────────────────────────
        # 3. FICHAS PARA CLIENTES Y VISUALIZACIONES (TRAFFIC & ENGAGEMENT)
        # ─────────────────────────────────────────────────────────────
        if agente_id is not None:
            fichas_where = "WHERE agente_id = ?"
            fichas_params = (agente_id,)
        elif oficina_id is not None:
            fichas_where = "WHERE agente_id IN (SELECT id FROM usuarios WHERE oficina_id = ?)"
            fichas_params = (oficina_id,)
        else:
            fichas_where = ""
            fichas_params = ()
        
        q_fichas = f"SELECT id, titulo, vistas_count, created_at, activo FROM enlaces_fichas_clientes {fichas_where} ORDER BY vistas_count DESC"
        rows_fichas = conn.execute(q_fichas, fichas_params).fetchall()
        
        total_fichas_creadas = len(rows_fichas)
        total_visualizaciones = sum(r['vistas_count'] or 0 for r in rows_fichas)
        top_fichas = [
            {
                'id': r['id'],
                'titulo': r['titulo'] or 'Propiedad Exclusiva',
                'vistas': r['vistas_count'] or 0,
                'fecha': str(r['created_at'])[:10] if r['created_at'] else ''
            }
            for r in rows_fichas[:5]
        ]

        # ─────────────────────────────────────────────────────────────
        # 4. BÚSQUEDAS DE CLIENTES GUARDADAS
        # ─────────────────────────────────────────────────────────────
        if agente_id is not None:
            busq_where = "WHERE agente_id = ?"
            busq_params = (agente_id,)
        elif oficina_id is not None:
            busq_where = "WHERE agente_id IN (SELECT id FROM usuarios WHERE oficina_id = ?)"
            busq_params = (oficina_id,)
        else:
            busq_where = ""
            busq_params = ()
        q_busq = f"SELECT COUNT(*) FROM busquedas_clientes {busq_where}"
        total_busquedas_guardadas = conn.execute(q_busq, busq_params).fetchone()[0] or 0

        # ─────────────────────────────────────────────────────────────
        # 5. OPERACIONES / FINANZAS & CONVERSIÓN
        # ─────────────────────────────────────────────────────────────
        if agente_id is not None:
            ops_where = "WHERE agente_id = ?"
            ops_params = (agente_id,)
        elif oficina_id is not None:
            ops_where = "WHERE agente_id IN (SELECT id FROM usuarios WHERE oficina_id = ?)"
            ops_params = (oficina_id,)
        else:
            ops_where = ""
            ops_params = ()
        
        q_ops = f"SELECT id, estado, bruto, neto, cierre, comision_rendida, fecha_firma, fecha_reserva, domicilio FROM seguimiento_operaciones {ops_where}"
        rows_ops = conn.execute(q_ops, ops_params).fetchall()
        
        total_operaciones = len(rows_ops)
        ops_cerradas = 0
        ops_en_reserva = 0
        ops_en_negociacion = 0
        volumen_ventas_cerradas = 0.0
        comisiones_generadas = 0.0
        
        for op in rows_ops:
            est = str(op['estado'] or '').lower()
            cierre_monto = _safe_float(op['cierre'])
            bruto_monto = _safe_float(op['bruto'])
            comis_monto = _safe_float(op['comision_rendida']) or (bruto_monto * 0.03 if bruto_monto else 0)
            
            if any(k in est for k in ['cerrad', 'escritur', 'firmad', 'ganad', 'complet']):
                ops_cerradas += 1
                volumen_ventas_cerradas += cierre_monto if cierre_monto > 0 else bruto_monto
                comisiones_generadas += comis_monto
            elif any(k in est for k in ['reserva', 'refuerzo', 'seña']):
                ops_en_reserva += 1
            else:
                ops_en_negociacion += 1

        # Embudo de Conversión (Funnel)
        funnel = [
            {'etapa': 'Leads y Contactos', 'cantidad': total_contactos, 'color': '#0d6efd'},
            {'etapa': 'Búsquedas Activas', 'cantidad': contactos_busqueda_activa or total_busquedas_guardadas, 'color': '#0dcaf0'},
            {'etapa': 'Fichas Compartidas', 'cantidad': total_fichas_creadas, 'color': '#ffc107'},
            {'etapa': 'Operaciones / Reservas', 'cantidad': ops_en_reserva + ops_cerradas, 'color': '#fd7e14'},
            {'etapa': 'Cierres Efectivos', 'cantidad': ops_cerradas, 'color': '#198754'}
        ]

        # ─────────────────────────────────────────────────────────────
        # 6. LEADERBOARD / RENDIMIENTO COMPARATIVO POR ASESOR
        # ─────────────────────────────────────────────────────────────
        ranking_asesores = []
        if oficina_id is not None:
            usuarios = db.get_all_usuarios(oficina_id=oficina_id)
        else:
            usuarios = db.get_all_usuarios()
        
        for u in usuarios:
            uid = u['id']
            unombre = u['nombre_display'] or u['usuario']
            urol = u['rol']
            
            # Contactos del agente
            u_conts = conn.execute("SELECT COUNT(*) FROM contactos WHERE agente_id = ?", (uid,)).fetchone()[0] or 0
            # Propiedades captadas
            u_props = conn.execute("SELECT COUNT(*) FROM propiedades WHERE agente_id = ?", (uid,)).fetchone()[0] or 0
            # Fichas y vistas
            r_vf = conn.execute("SELECT COUNT(*), COALESCE(SUM(vistas_count), 0) FROM enlaces_fichas_clientes WHERE agente_id = ?", (uid,)).fetchone()
            u_fichas = r_vf[0] or 0
            u_vistas = r_vf[1] or 0
            # Operaciones
            r_uops = conn.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN LOWER(estado) LIKE '%cerrad%' OR LOWER(estado) LIKE '%escritur%' OR LOWER(estado) LIKE '%firmad%' THEN 1 ELSE 0 END), 0), COALESCE(SUM(bruto), 0) FROM seguimiento_operaciones WHERE agente_id = ?", (uid,)).fetchone()
            u_ops_total = r_uops[0] or 0
            u_ops_cerradas = r_uops[1] or 0
            u_bruto = r_uops[2] or 0.0
            
            tasa_conv = round((u_ops_cerradas / u_conts * 100), 1) if u_conts > 0 else 0.0
            
            ranking_asesores.append({
                'id': uid,
                'nombre': unombre,
                'usuario': u['usuario'],
                'rol': urol,
                'contactos': u_conts,
                'propiedades': u_props,
                'fichas': u_fichas,
                'vistas': u_vistas,
                'operaciones_total': u_ops_total,
                'operaciones_cerradas': u_ops_cerradas,
                'volumen_bruto': u_bruto,
                'tasa_conversion': tasa_conv
            })

        ranking_asesores.sort(key=lambda x: (x['operaciones_cerradas'], x['contactos'], x['vistas']), reverse=True)

        return {
            'resumen': {
                'total_propiedades': total_propiedades,
                'props_venta': props_venta,
                'props_alquiler': props_alquiler,
                'ticket_promedio_venta': ticket_promedio_venta,
                'total_contactos': total_contactos,
                'contactos_calificados': contactos_calificados,
                'contactos_busqueda_activa': contactos_busqueda_activa,
                'contactos_frios': contactos_frios,
                'total_fichas_creadas': total_fichas_creadas,
                'total_visualizaciones': total_visualizaciones,
                'total_operaciones': total_operaciones,
                'ops_cerradas': ops_cerradas,
                'ops_en_reserva': ops_en_reserva,
                'ops_en_negociacion': ops_en_negociacion,
                'volumen_ventas_cerradas': volumen_ventas_cerradas,
                'comisiones_generadas': comisiones_generadas,
                'tasa_conversion_global': round((ops_cerradas / total_contactos * 100), 1) if total_contactos > 0 else 0.0
            },
            'distribucion_tipos': props_por_tipo,
            'top_barrios': dict(top_barrios),
            'funnel': funnel,
            'top_fichas': top_fichas,
            'ranking_asesores': ranking_asesores,
            'contactos_por_rol': contactos_por_rol
        }
        
    finally:
        conn.close()


@analitica_bp.route('/dashboard')
@analitica_bp.route('/')
@login_required
def dashboard():
    """Vista principal del módulo de Analítica y KPIs (Solo Admins de Oficina y SuperAdmin)."""
    es_admin_o_broker = (current_user.rol in ['admin', 'broker'] or current_user.usuario == 'GermanMazza')
    if not es_admin_o_broker:
        flash("El módulo de Analítica y KPIs está reservado para Administradores de Oficina y SuperAdmin.", "warning")
        return redirect(url_for('index'))
    
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else None

    if current_user.usuario == 'GermanMazza':
        usuarios = db.get_all_usuarios()
    elif oficina_id:
        usuarios = db.get_all_usuarios(oficina_id=oficina_id)
    else:
        usuarios = []

    filtro_agente = request.args.get('agente_id', type=int)
    if filtro_agente and oficina_id:
        user_ids = {u['id'] for u in usuarios}
        if filtro_agente not in user_ids:
            filtro_agente = None
        
    metricas = calcular_metricas_analitica(agente_id=filtro_agente, oficina_id=oficina_id)
    
    return render_template(
        'analitica.html',
        metricas=metricas,
        usuarios=usuarios,
        filtro_agente=filtro_agente,
        es_admin_o_broker=es_admin_o_broker,
        is_solo_agent=False
    )


@analitica_bp.route('/api/kpis')
@login_required
def api_kpis():
    """API REST para obtener las métricas en JSON (Solo Admins y SuperAdmin)."""
    es_admin_o_broker = (current_user.rol in ['admin', 'broker'] or current_user.usuario == 'GermanMazza')
    if not es_admin_o_broker:
        return jsonify({'success': False, 'error': 'No autorizado'}), 403

    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else None
    filtro_agente = request.args.get('agente_id', type=int)
    data = calcular_metricas_analitica(agente_id=filtro_agente, oficina_id=oficina_id)
    return jsonify({'success': True, 'data': data})
