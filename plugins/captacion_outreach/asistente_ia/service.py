"""
Service Module for Asistente IA Plugin.
Powered by Groq (openai/gpt-oss-20b) with automatic fallback.
Generates high-impact Birthday/Anniversary greetings and Daily Morning Briefings.
"""
import os
import re
from datetime import datetime
from lib.gemini_service import _generar_con_ia, _generar_con_groq, _generar_con_gemini

def _invocar_llm(prompt, etiqueta="AsistenteIA"):
    """Llama al LLM (Groq como primario por velocidad) con fallback seguro."""
    try:
        return _generar_con_ia(prompt, etiqueta=etiqueta)
    except Exception as e:
        print(f"[{etiqueta}] Error general con LLM: {e}")
        return None

def generar_saludo_cumpleanios(contacto, agente_nombre="German"):
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
    
    res = _invocar_llm(prompt, etiqueta="CumpleañosIA")
    if res:
        return res.strip().strip('"')
    
    # Fallback determinista
    return f"¡Hola {nombre}! 🎂 Muy feliz cumpleaños 🎉 Te deseo un día excelente y un gran año por delante junto a tu familia y seres queridos. ¡Un saludo grande! {agente_nombre}."

def generar_saludo_aniversario(contacto, agente_nombre="German"):
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

    res = _invocar_llm(prompt, etiqueta="AniversarioIA")
    if res:
        return res.strip().strip('"')

    # Fallback determinista
    tiempo_frase = f"se cumple un año más" if not anios_texto else f"{anios_texto} diste el paso a tu nuevo hogar"
    return f"¡Hola {nombre}! 🏡 Hoy recordaba que {tiempo_frase}. Espero que sigas disfrutando muchísimo de tu casa. Cualquier consulta sobre el mercado o si tenés algún amigo o familiar que necesite asesoramiento, sabés que contás conmigo. ¡Un abrazo grande! {agente_nombre}."

def generar_morning_briefing(agente_nombre, recordatorios_hoy, cumples_hoy, aniversarios_hoy, cold_count, tareas_pendientes=None):
    """
    Genera el resumen matutino (Morning Briefing) para el WhatsApp del agente.
    """
    resumen_recordatorios = []
    for r in (recordatorios_hoy or [])[:4]:
        nom = f"{r.get('nombre', '')} {r.get('apellido', '')}".strip()
        notas = (r.get('notas') or '').replace('\n', ' ')[:60]
        resumen_recordatorios.append(f"- {nom}: {notas if notas else 'Seguimiento agendado'}")

    resumen_cumples = [f"{c.get('nombre', '')} {c.get('apellido', '')}".strip() for c in (cumples_hoy or [])]
    resumen_aniversarios = [f"{a.get('nombre', '')} {a.get('apellido', '')}".strip() for a in (aniversarios_hoy or [])]

    prompt = f"""
    Sos el Asistente Ejecutivo Inteligente del CRM Inmobiliario para el agente inmobiliario {agente_nombre}.
    Son las 8:30 AM y le estás enviando su "Morning Briefing" diario a su WhatsApp para que arranque el día enfocado y motivado.
    
    DATOS DEL DÍA PARA {agente_nombre.upper()}:
    - Recordatorios prioritarios de hoy ({len(recordatorios_hoy)} pendientes):
      {chr(10).join(resumen_recordatorios) if resumen_recordatorios else "Sin recordatorios agendados para hoy."}
    - Cumpleaños de clientes hoy ({len(resumen_cumples)}):
      {', '.join(resumen_cumples) if resumen_cumples else "Ninguno hoy."}
    - Aniversarios de compra de casa hoy ({len(resumen_aniversarios)}):
      {', '.join(resumen_aniversarios) if resumen_aniversarios else "Ninguno hoy."}
    - Contactos fríos (>30 días sin hablar): {cold_count} contactos en su base.
    
    REGLAS DE FORMATO:
    1. Empezá con un saludo matutino con energía: ej "☕ *Buenos días, {agente_nombre}! Aquí tu plan de acción para hoy:*"
    2. Usá negritas en WhatsApp (*texto*) para los títulos de sección.
    3. Usá viñetas claras con emojis (🎯 para recordatorios, 🎂 para cumpleaños, 🏡 para aniversarios, ❄️ para reactivación).
    4. Si hay cumpleaños o aniversarios, recordale que puede enviarles el saludo con 1 clic desde el CRM.
    5. Cerrá con una frase corta de enfoque comercial / cierre de captaciones.
    6. Máximo 600 caracteres. Formato WhatsApp puro.
    
    Respondé ÚNICAMENTE con el texto final del briefing.
    """

    res = _invocar_llm(prompt, etiqueta="MorningBriefingIA")
    if res:
        return res.strip()

    # Fallback estructurado
    lineas = [
        f"☕ *¡Buenos días, {agente_nombre}! Aquí tu Morning Briefing de hoy:*",
        ""
    ]
    if recordatorios_hoy:
        lineas.append("🎯 *Recordatorios clave de hoy:*")
        for r in recordatorios_hoy[:3]:
            nom = f"{r.get('nombre', '')} {r.get('apellido', '')}".strip()
            lineas.append(f"  • {nom} ({r.get('telefono') or 'Sin tel'})")
        lineas.append("")

    if cumples_hoy:
        lineas.append(f"🎂 *Cumpleaños hoy:* {', '.join(resumen_cumples)} (¡Mandales saludo desde el CRM!)")
        lineas.append("")

    if aniversarios_hoy:
        lineas.append(f"🏡 *Aniversarios de compra:* {', '.join(resumen_aniversarios)}")
        lineas.append("")

    if cold_count > 0:
        lineas.append(f"❄️ *Oportunidad:* Tenés {cold_count} contactos sin seguimiento hace +30 días para reactivar.")
        lineas.append("")

    lineas.append("🚀 *¡A romperla hoy con las captaciones y ventas!*")
    return "\n".join(lineas)
