"""
Service Module for Asistente IA Plugin.
Powered by Groq (openai/gpt-oss-20b) with automatic fallback.
Generates high-impact Birthday/Anniversary greetings and Daily Morning Briefings.
"""
import os
import re
from datetime import datetime
from lib.gemini_service import _generar_con_ia, _generar_con_groq, _generar_con_gemini

def _invocar_llm(prompt, etiqueta="AsistenteIA", agente_id=None):
    """Llama al LLM (Groq como primario por velocidad) con fallback seguro."""
    try:
        return _generar_con_ia(prompt, etiqueta=etiqueta, agente_id=agente_id)
    except Exception as e:
        print(f"[{etiqueta}] Error general con LLM: {e}")
        return None

def generar_saludo_cumpleanios(contacto, agente_nombre="German", agente_id=None):
    """
    Genera un saludo de cumpleaños personalizado, cálido y no invasivo para WhatsApp.
    Incluye un toque humano y un sutil reenganche.
    """
    nombre = contacto.get('nombre', 'estimado/a').strip()
    categoria = contacto.get('categoria', 'C')
    rol = contacto.get('rol', 'Cliente')
    notas = (contacto.get('notas') or '')[:150]

    prompt = f"""
    Sos {agente_nombre}, un asesor inmobiliario profesional, empático y cercano.
    Hoy es el CUMPLEAÑOS de tu cliente/contacto.
    
    DATOS DEL CONTACTO:
    - Nombre: {nombre}
    - Rol/Vínculo: {rol}
    - Categoría en CRM: {categoria}
    {f"- Notas previas: {notas}" if notas else ""}
    
    TAREA:
    Escribí un mensaje de felicitación de cumpleaños por WhatsApp que sea:
    1. Muy natural, cálido y humano (NO debe sonar a plantilla corporativa genérica).
    2. Corto (2 o 3 párrafos breves, máximo 350 caracteres).
    3. Usá 2 o 3 emojis festivos adecuados (ej: 🎂, 🎉, 🥂).
    4. Un cierre cordial deseándole que disfrute el día con los suyos y un saludo afectuoso de {agente_nombre}.
    
    Respondé ÚNICAMENTE con el texto final del mensaje, sin comillas ni explicaciones adicionales.
    """
    
    res = _invocar_llm(prompt, etiqueta="CumpleañosIA", agente_id=agente_id)
    if res:
        return res.strip().strip('"')
    
    # Fallback determinista
    return f"¡Hola {nombre}! 🎂 Muy feliz cumpleaños 🎉 Te deseo un día excelente y un gran año por delante junto a tu familia y seres queridos. ¡Un saludo grande! {agente_nombre}."

def generar_saludo_aniversario(contacto, agente_nombre="German", agente_id=None):
    """
    Genera un saludo por el aniversario de compra/mudanza de su casa o departamento.
    Calcula los años si la fecha contiene año y deja la puerta abierta para referidos o consultas.
    """
    nombre = contacto.get('nombre', 'estimado/a').strip()
    aniversario = contacto.get('aniversario_casa') or ''
    
    anios_texto = ""
    if aniversario and len(aniversario) >= 4 and aniversario[:4].isdigit():
        try:
            anio_compra = int(aniversario[:4])
            anio_actual = datetime.now().year
            diff = anio_actual - anio_compra
            if diff == 1:
                anios_texto = "hace exactamente 1 año"
            elif diff > 1:
                anios_texto = f"hace ya {diff} años"
        except Exception:
            pass

    prompt = f"""
    Sos {agente_nombre}, el asesor inmobiliario que ayudó a {nombre} a concretar la compra/mudanza de su propiedad.
    Hoy se cumple un ANIVERSARIO de ese momento especial ({anios_texto if anios_texto else 'aniversario de su hogar'}).
    
    TAREA:
    Escribí un mensaje cálido por WhatsApp que:
    1. Le recuerde afectuosamente la fecha y celebre ese hito en su hogar.
    2. Sea genuino, breve y profesional (máximo 380 caracteres).
    3. Incluya un gancho sutil y elegante de fidelización: si alguna vez necesita una tasación actualizada o asesorar a algún conocido/amigo que quiera mudarse, recordarle que siempre contás con vos.
    4. Cierre con un abrazo/saludo de {agente_nombre}.
    
    Respondé ÚNICAMENTE con el texto final del mensaje, sin comillas ni encabezados.
    """

    res = _invocar_llm(prompt, etiqueta="AniversarioIA", agente_id=agente_id)
    if res:
        return res.strip().strip('"')

    # Fallback determinista
    tiempo_frase = f"se cumple un año más" if not anios_texto else f"{anios_texto} diste el paso a tu nuevo hogar"
    return f"¡Hola {nombre}! 🏡 Hoy recordaba que {tiempo_frase}. Espero que sigas disfrutando muchísimo de tu casa. Cualquier consulta sobre el mercado o si tenés algún amigo o familiar que necesite asesoramiento, sabés que contás conmigo. ¡Un abrazo grande! {agente_nombre}."

EFEMERIDES_FIJAS_ARGENTINA = {
    "01-01": "🎆 Año Nuevo",
    "02-14": "❤️ Día de los Enamorados / San Valentín",
    "02-15": "✍️ Día del Redactor Publicitario en Argentina",
    "03-08": "💐 Día Internacional de la Mujer",
    "03-24": "🕊️ Día Nacional de la Memoria por la Verdad y la Justicia (Feriado Nacional)",
    "04-02": "🇦🇷 Día del Veterano y de los Caídos en la Guerra de Malvinas (Feriado Nacional)",
    "04-13": "🩺 Día del Kinesiólogo en Argentina",
    "04-23": "📐 Día del Agrimensor en Argentina",
    "05-01": "👷 Día del Trabajador (Feriado Nacional)",
    "05-12": "🏥 Día de la Enfermería",
    "05-25": "🇦🇷 Día de la Revolución de Mayo (Feriado Nacional)",
    "06-02": "💼 Día del Graduado en Ciencias Económicas en Argentina",
    "06-06": "🏗️ Día de la Ingeniería Argentina",
    "06-07": "📰 Día del Periodista en Argentina",
    "06-16": "⚙️ Día del Ingeniero en Argentina",
    "06-20": "🇦🇷 Día de la Bandera - Paso a la Inmortalidad de Belgrano (Feriado Nacional)",
    "07-01": "🏛️ Día del Arquitecto en Argentina",
    "07-09": "🇦🇷 Día de la Independencia Argentina (Feriado Nacional)",
    "07-10": "🏪 Día del Comerciante en Argentina",
    "07-20": "🤝 Día del Amigo en Argentina",
    "08-06": "🐾 Día del Veterinario en Argentina",
    "08-17": "⚔️ Paso a la Inmortalidad del Gral. José de San Martín (Feriado Nacional)",
    "08-29": "⚖️ Día del Abogado en Argentina (en honor a J. B. Alberdi)",
    "09-11": "📚 Día del Maestro en Argentina (en honor a Sarmiento)",
    "09-13": "📖 Día del Bibliotecario en Argentina",
    "09-21": "🌸 Día de la Primavera, del Estudiante y del Economista en Argentina",
    "10-02": "📜 Día del Escribano y del Notariado en Argentina",
    "10-03": "🦷 Día del Odontólogo en Argentina",
    "10-11": "🏢 Día del Martillero y Corredor Inmobiliario en Argentina",
    "10-12": "🌎 Día del Respeto a la Diversidad Cultural (Feriado Nacional)",
    "11-20": "🇦🇷 Día de la Soberanía Nacional (Feriado Nacional)",
    "12-03": "🩺 Día del Médico en Argentina",
    "12-04": "📢 Día de la Publicidad",
    "12-08": "✨ Día de la Inmaculada Concepción de María (Feriado Nacional)",
    "12-17": "📊 Día del Contador Público en Argentina",
    "12-25": "🎄 Navidad (Feriado Nacional)",
    "12-31": "🥂 Fin de Año"
}

def obtener_efemeride_argentina(dt=None):
    """
    Calcula efemérides fijas y móviles de la República Argentina para la fecha dada.
    """
    if dt is None:
        dt = datetime.now()

    dias_semana_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    meses_es = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    dia_nombre = dias_semana_es[dt.weekday()]
    mes_nombre = meses_es[dt.month - 1]
    fecha_texto = f"{dia_nombre} {dt.day} de {mes_nombre} de {dt.year}"
    mm_dd = dt.strftime('%m-%d')

    # 1. Chequear efemérides fijas
    efemeride = EFEMERIDES_FIJAS_ARGENTINA.get(mm_dd)

    # 2. Chequear fechas móviles de Argentina (Domingos específicos)
    if dt.weekday() == 6: # Es domingo
        dia_del_mes = dt.day
        # 3er domingo de Junio -> Día del Padre
        if dt.month == 6 and 15 <= dia_del_mes <= 21:
            efemeride = "👨 Día del Padre en Argentina"
        # 3er domingo de Agosto -> Día de las Infancias / Día del Niño
        elif dt.month == 8 and 15 <= dia_del_mes <= 21:
            efemeride = "🧸 Día de las Infancias / Día del Niño en Argentina"
        # 3er domingo de Octubre -> Día de la Madre
        elif dt.month == 10 and 15 <= dia_del_mes <= 21:
            efemeride = "💐 Día de la Madre en Argentina"

    return {
        'fecha_texto': fecha_texto,
        'efemeride': efemeride,
        'tiene_efemeride': bool(efemeride)
    }

def generar_morning_briefing(agente_nombre, recordatorios_hoy, cumples_hoy, aniversarios_hoy, cold_count, tareas_pendientes=None, agente_id=None, dt=None):
    """
    Genera el resumen matutino (Morning Briefing) para el WhatsApp del agente.
    Estructura fija (Opción B) + Efemérides de Argentina + Idea de Prospección del Día.
    """
    info_fecha = obtener_efemeride_argentina(dt)
    fecha_hoy_str = info_fecha['fecha_texto']
    efemeride_hoy = info_fecha['efemeride'] or "Sin efemérides destacadas hoy"

    resumen_recordatorios = []
    for r in (recordatorios_hoy or [])[:4]:
        nom = f"{r.get('nombre', '')} {r.get('apellido', '')}".strip()
        tel = f" ({r.get('telefono')})" if r.get('telefono') else ""
        notas = (r.get('notas') or '').replace('\n', ' ')[:50]
        resumen_recordatorios.append(f"- {nom}{tel}: {notas if notas else 'Seguimiento agendado'}")

    resumen_cumples = [f"{c.get('nombre', '')} {c.get('apellido', '')}".strip() for c in (cumples_hoy or [])]
    resumen_aniversarios = [f"{a.get('nombre', '')} {a.get('apellido', '')}".strip() for a in (aniversarios_hoy or [])]

    agency_info = db.get_agency_settings()
    agency_brand = agency_info.get('nombre', 'la Inmobiliaria')

    prompt = f"""
    Sos el Asistente Ejecutivo Inteligente del CRM de {agency_brand} para el agente inmobiliario {agente_nombre}.
    Son las 8:30 AM en Argentina y le estás enviando su "Morning Briefing" diario a su WhatsApp para que arranque el día organizado y enfocado.
    
    FECHA ACTUAL EN ARGENTINA:
    - Fecha: {fecha_hoy_str}
    - Efeméride / Fecha especial en Argentina: {efemeride_hoy}
    
    DATOS DEL DÍA PARA {agente_nombre.upper()}:
    - Recordatorios hoy ({len(recordatorios_hoy)} pendientes):
      {chr(10).join(resumen_recordatorios) if resumen_recordatorios else "Sin recordatorios agendados para hoy."}
    - Cumpleaños de clientes hoy ({len(resumen_cumples)}):
      {', '.join(resumen_cumples) if resumen_cumples else "Ninguno hoy."}
    - Aniversarios de compra de casa hoy ({len(resumen_aniversarios)}):
      {', '.join(resumen_aniversarios) if resumen_aniversarios else "Ninguno hoy."}
    - Contactos fríos (>30 días sin hablar): {cold_count} contactos en su base.
    
    ESTRUCTURA OBLIGATORIA DEL MENSAJE (WhatsApp):
    1. Saludo inicial: "☕ *Buenos días, {agente_nombre}! Aquí tu plan de acción para hoy:*"
    2. Sección Fecha / Efeméride Argentina: 📅 *Fecha & Efemérides:* ({fecha_hoy_str}. Si hoy es una fecha patria o día profesional como Día del Abogado, Día del Escribano, Día del Niño, etc., mencionalo con entusiasmo como oportunidad para saludar clientes/contactos de ese rubro; si es día estándar poner '{fecha_hoy_str}')
    3. Sección Recordatorios: 🎯 *Recordatorios:* (Listar los del día o 'Sin recordatorios agendados para hoy.')
    4. Sección Cumpleaños: 🎂 *Cumpleaños:* (Listar nombres + '¡Mandales saludo desde el CRM!' o 'Ninguno hoy.')
    5. Sección Aniversarios de compra: 🏡 *Aniversarios de compra:* (Listar nombres o 'Ninguno hoy.')
    6. Sección Contactos fríos: ❄️ *Contactos fríos:* ({cold_count} contactos >30 días sin hablar. Sugerir seleccionar 5 para reactivar.)
    7. Sección Pie Estrella: 💡 *Idea de prospección para hoy:* (Generá 1 tip de ventas inmobiliarias creativo, fresco y accionable para ejecutar hoy en el mercado argentino. Máximo 2 líneas directas.)
    8. Cierre motivador: 🚀 Frase corta de éxito comercial.
    
    REGLAS ESTRICTAS:
    - Todas las fechas y efemérides deben ser 100% EXCLUSIVAS DE LA REPÚBLICA ARGENTINA.
    - Mantené siempre los títulos en negrita con asteriscos (*Título*).
    - Formato WhatsApp limpio, ordenado y visualmente atractivo con emojis.
    - Máximo 750 caracteres.
    
    Respondé ÚNICAMENTE con el texto final del briefing.
    """

    res = _invocar_llm(prompt, etiqueta="MorningBriefingIA", agente_id=agente_id)
    if res:
        return res.strip()

    # Fallback estructurado fijo
    lineas = [
        f"☕ *Buenos días, {agente_nombre}! Aquí tu plan de acción para hoy:*",
        ""
    ]
    lineas.append("📅 *Fecha & Efemérides:*")
    if info_fecha['tiene_efemeride']:
        lineas.append(f"• {fecha_hoy_str} — {info_fecha['efemeride']}")
    else:
        lineas.append(f"• {fecha_hoy_str}")
    lineas.append("")

    lineas.append("🎯 *Recordatorios:*")
    if recordatorios_hoy:
        for r in recordatorios_hoy[:3]:
            nom = f"{r.get('nombre', '')} {r.get('apellido', '')}".strip()
            lineas.append(f"• {nom} ({r.get('telefono') or 'Sin tel'})")
    else:
        lineas.append("Sin recordatorios agendados para hoy.")
    lineas.append("")

    lineas.append("🎂 *Cumpleaños:*")
    if cumples_hoy:
        lineas.append(f"• {', '.join(resumen_cumples)} (¡Mandales saludo con 1 clic desde el CRM!)")
    else:
        lineas.append("Ninguno hoy.")
    lineas.append("")

    lineas.append("🏡 *Aniversarios de compra:*")
    if aniversarios_hoy:
        lineas.append(f"• {', '.join(resumen_aniversarios)} (¡Mandales saludo con 1 clic desde el CRM!)")
    else:
        lineas.append("Ninguno hoy.")
    lineas.append("")

    lineas.append("❄️ *Contactos fríos:*")
    if cold_count > 0:
        lineas.append(f"• {cold_count} contactos >30 días sin hablar. Seleccioná 5 para contactar hoy.")
    else:
        lineas.append("Base al día.")
    lineas.append("")

    lineas.append("💡 *Idea de prospección para hoy:*")
    lineas.append("Subí una historia destacando una oportunidad de tu zona en WhatsApp e Instagram con un llamado a la acción directo.")
    lineas.append("")

    lineas.append("🚀 *¡A romperla hoy con las captaciones y ventas!*")
    return "\n".join(lineas)
