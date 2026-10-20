"""
Market Thermometer & Days on Market (DOM) Evaluation Engine
Calcula la inteligencia de mercado para una propiedad inmobiliaria:
- Badges comerciales transparentes y persuasivos para el Portal Cliente y Fichas Compartidas.
- Métricas duras de antigüedad, caídas de precio y alertas de negociación para el Asesor CRM.
"""
from datetime import datetime


def calcular_dias_en_mercado(prop):
    """
    Calcula de forma segura los días que lleva la propiedad en el mercado.
    Prioridad:
    1. prop['dias_publicado'] (extraído directamente del portal).
    2. Diferencia de días entre hoy y prop['primera_deteccion'] / prop['fecha_captacion'] / prop['created_at'].
    3. Fallback: 0 si es recién creada.
    """
    if not prop or not isinstance(prop, dict):
        return 0

    # 1. Si ya tiene el campo numérico del portal
    dias_raw = prop.get('dias_publicado')
    if dias_raw is not None and str(dias_raw).strip() != '':
        try:
            val = int(dias_raw)
            if val >= 0:
                return val
        except (ValueError, TypeError):
            pass

    # 2. Si tiene fecha de primera detección o captación histórica
    fecha_ref_str = (
        prop.get('primera_deteccion') or
        prop.get('fecha_publicacion_portal') or
        prop.get('fecha_captacion') or
        prop.get('created_at')
    )
    if fecha_ref_str:
        try:
            # Soportar ISO o formatos comunes YYYY-MM-DD HH:MM:SS
            f_str = str(fecha_ref_str).strip().replace('T', ' ')
            if len(f_str) >= 10:
                dt_ref = datetime.strptime(f_str[:10], "%Y-%m-%d")
                delta = (datetime.now() - dt_ref).days
                return max(delta, 0)
        except Exception:
            pass

    return 0


def evaluar_oportunidad_mercado(prop):
    """
    Evalúa integralmente la propiedad y devuelve un diccionario con:
    - dias_en_mercado (int)
    - hay_rebaja (bool)
    - rebaja_monto (float)
    - rebaja_pct (float)
    - badge_tipo ('rebaja' | 'nuevo' | 'negociable' | 'estandar')
    - badge_color ('danger' | 'success' | 'warning' | 'primary')
    - badge_icono ('bi-graph-down-arrow' | 'bi-stars' | 'bi-tag-fill' | 'bi-check2-circle')
    - badge_texto_cliente (str)
    - badge_subtexto_cliente (str)
    - badge_texto_agente (str)
    """
    if not prop or not isinstance(prop, dict):
        return {
            'dias_en_mercado': 0,
            'hay_rebaja': False,
            'rebaja_monto': 0,
            'rebaja_pct': 0,
            'badge_tipo': 'estandar',
            'badge_color': 'primary',
            'badge_icono': 'bi-check2-circle',
            'badge_texto_cliente': 'VALOR DE MERCADO',
            'badge_subtexto_cliente': 'Inmueble en período activo de visitas.',
            'badge_texto_agente': '🔵 Propiedad en mercado'
        }

    dias = calcular_dias_en_mercado(prop)
    moneda = str(prop.get('moneda') or 'USD').upper()

    def safe_float(v):
        try:
            return float(v) if v is not None and str(v).strip() != '' else None
        except:
            return None

    precio_actual = safe_float(prop.get('precio'))
    precio_ant = safe_float(prop.get('precio_anterior'))

    hay_rebaja = False
    rebaja_monto = 0.0
    rebaja_pct = 0.0

    if precio_actual is not None and precio_ant is not None and precio_actual < precio_ant:
        rebaja_monto = precio_ant - precio_actual
        if precio_ant > 0:
            rebaja_pct = round((rebaja_monto / precio_ant) * 100, 1)
            # Consideramos rebaja significativa si es >= 2% o >= USD 1,000
            if rebaja_pct >= 2.0 or rebaja_monto >= 1000:
                hay_rebaja = True

    # -------------------------------------------------------------
    # 1. CASO REBAJA DE PRECIO (Prioridad comercial máxima)
    # -------------------------------------------------------------
    if hay_rebaja:
        monto_str = f"{rebaja_monto:,.0f}".replace(',', '.')
        return {
            'dias_en_mercado': dias,
            'hay_rebaja': True,
            'rebaja_monto': rebaja_monto,
            'rebaja_pct': rebaja_pct,
            'precio_anterior': precio_ant,
            'badge_tipo': 'rebaja',
            'badge_color': 'danger',
            'badge_icono': 'bi-graph-down-arrow',
            'badge_texto_cliente': f"OPORTUNIDAD · Bajó {moneda} {monto_str} (-{rebaja_pct:.0f}%)",
            'badge_subtexto_cliente': "Readecuación de precio reciente por debajo de la media de la zona.",
            'badge_texto_agente': f"📉 Bajó {moneda} {monto_str} (-{rebaja_pct:.0f}%) · {dias}d en mercado"
        }

    # -------------------------------------------------------------
    # 2. CASO NUEVO INGRESO (0 a 15 días)
    # -------------------------------------------------------------
    if dias <= 15:
        if dias == 0:
            texto_dias = "Publicado hoy"
        elif dias == 1:
            texto_dias = "Hace 1 día"
        else:
            texto_dias = f"Hace {dias} días"

        return {
            'dias_en_mercado': dias,
            'hay_rebaja': False,
            'rebaja_monto': 0,
            'rebaja_pct': 0,
            'badge_tipo': 'nuevo',
            'badge_color': 'success',
            'badge_icono': 'bi-stars',
            'badge_texto_cliente': f"NUEVO INGRESO · {texto_dias}",
            'badge_subtexto_cliente': "Propiedad recién entrada al mercado. Recomendamos coordinar visita pronto.",
            'badge_texto_agente': f"🟢 Nuevo Ingreso ({dias}d) · Alta prioridad de contacto"
        }

    # -------------------------------------------------------------
    # 3. CASO PRECIO NEGOCIABLE / TIEMPO EN MERCADO (+90 días)
    # -------------------------------------------------------------
    if dias >= 90:
        meses = round(dias / 30)
        return {
            'dias_en_mercado': dias,
            'hay_rebaja': False,
            'rebaja_monto': 0,
            'rebaja_pct': 0,
            'badge_tipo': 'negociable',
            'badge_color': 'warning',
            'badge_icono': 'bi-tag-fill',
            'badge_texto_cliente': "PRECIO NEGOCIABLE · Oportunidad para contraoferta",
            'badge_subtexto_cliente': "Inmueble con excelente disposición a evaluar propuestas y contraofertas.",
            'badge_texto_agente': f"⏳ {dias}d en mercado (~{meses} meses) · Vendedor motivado para ofertar a la baja"
        }

    # -------------------------------------------------------------
    # 4. CASO ESTÁNDAR / EN VALOR DE MERCADO (16 a 89 días)
    # -------------------------------------------------------------
    return {
        'dias_en_mercado': dias,
        'hay_rebaja': False,
        'rebaja_monto': 0,
        'rebaja_pct': 0,
        'badge_tipo': 'estandar',
        'badge_color': 'primary',
        'badge_icono': 'bi-check2-circle',
        'badge_texto_cliente': "VALOR DE MERCADO",
        'badge_subtexto_cliente': "Inmueble en período estándar de visitas y negociación activa.",
        'badge_texto_agente': f"🔵 {dias}d en mercado · En absorción estándar"
    }
