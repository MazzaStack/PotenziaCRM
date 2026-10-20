import os
import json
import re
from database.db import get_config

# ── Gemini ──────────────────────────────────────────────────────────────────
def get_gemini_client(agente_id=None):
    """Initializes and returns the Gemini client using the API key from config."""
    api_key = None
    if agente_id:
        api_key = get_config(f'gemini_api_key_{agente_id}')
    if not api_key:
        api_key = get_config('gemini_api_key')
    if not api_key:
        api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        try:
            from database.db import get_db
            conn = get_db()
            row = conn.execute("SELECT valor FROM configuracion WHERE clave LIKE 'gemini_api_key%' AND valor IS NOT NULL AND LENGTH(valor) > 10 LIMIT 1").fetchone()
            conn.close()
            if row:
                api_key = row['valor']
        except Exception:
            pass
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        print(f"Error inicializando cliente Gemini: {e}")
        return None

# ── Groq ─────────────────────────────────────────────────────────────────────
def get_groq_client(agente_id=None):
    """Initializes and returns the Groq client using the API key from config."""
    api_key = None
    if agente_id:
        api_key = get_config(f'groq_api_key_{agente_id}')
    if not api_key:
        api_key = get_config('groq_api_key')
    if not api_key:
        api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        try:
            from database.db import get_db
            conn = get_db()
            row = conn.execute("SELECT valor FROM configuracion WHERE clave LIKE 'groq_api_key%' AND valor IS NOT NULL AND LENGTH(valor) > 10 LIMIT 1").fetchone()
            conn.close()
            if row:
                api_key = row['valor']
        except Exception:
            pass
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except ImportError:
        print("Groq library not installed. Run: pip install groq")
        return None
    except Exception as e:
        print(f"Error inicializando cliente Groq: {e}")
        return None

def _groq_modelo(agente_id=None):
    """Returns the configured Groq model (default: openai/gpt-oss-20b), mapping deprecated models."""
    m = None
    if agente_id:
        m = get_config(f'groq_model_{agente_id}')
    if not m:
        m = get_config('groq_model')
    deprecated_map = {
        'llama-3.1-8b-instant': 'openai/gpt-oss-20b',
        'llama-3.3-70b-versatile': 'openai/gpt-oss-120b',
        'llama-3.1-70b-versatile': 'openai/gpt-oss-120b',
        'llama3-70b-8192': 'openai/gpt-oss-120b',
        'llama3-8b-8192': 'openai/gpt-oss-20b',
        'mixtral-8x7b-32768': 'openai/gpt-oss-120b'
    }
    if not m or m in deprecated_map:
        return deprecated_map.get(m, 'openai/gpt-oss-20b')
    return m

def _is_groq_primary(agente_id=None):
    """Returns True if Groq is set as the primary AI provider."""
    p = None
    if agente_id:
        p = get_config(f'ia_provider_primario_{agente_id}')
    if not p:
        p = get_config('ia_provider_primario')
    return p == 'groq'

# ── Generación de mensajes ──────────────────────────────────────────────────
def _generar_con_gemini(prompt, agente_id=None):
    """Attempt to generate content using Gemini. Returns text or raises."""
    client = get_gemini_client(agente_id=agente_id)
    if not client:
        raise RuntimeError("Gemini API Key no configurada.")
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt
    )
    if response and response.text:
        return response.text.strip()
    raise RuntimeError("Gemini devolvió respuesta vacía.")

def _generar_con_groq(prompt, agente_id=None):
    """Attempt to generate content using Groq. Returns text or raises."""
    client = get_groq_client(agente_id=agente_id)
    if not client:
        raise RuntimeError("Groq API Key no configurada.")
    modelo = _groq_modelo(agente_id=agente_id)
    completion = client.chat.completions.create(
        model=modelo,
        messages=[
            {"role": "system", "content": "Sos un asistente inmobiliario experto. Respondé directamente con el texto solicitado sin introducciones ni explicaciones accesorias."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=2048,
        timeout=35
    )
    if completion and completion.choices:
        msg = completion.choices[0].message
        if msg.content and msg.content.strip():
            return msg.content.strip()
        # Fallback si el modelo de razonamiento emitió la respuesta en reasoning
        reasoning = getattr(msg, 'reasoning', None)
        if reasoning and reasoning.strip():
            lines = [l.strip() for l in reasoning.strip().split('\n') if l.strip()]
            if lines:
                return lines[-1].strip('"').strip("'")
    raise RuntimeError("Groq devolvió respuesta vacía.")

def _generar_con_ia(prompt, etiqueta="IA", agente_id=None):
    """
    Smart router: uses primary provider, falls back to secondary.
    Returns text result or raises if both fail.
    """
    groq_primario = _is_groq_primary(agente_id=agente_id)

    if groq_primario:
        proveedores = [('Groq', lambda p: _generar_con_groq(p, agente_id=agente_id)), ('Gemini', lambda p: _generar_con_gemini(p, agente_id=agente_id))]
    else:
        proveedores = [('Groq', lambda p: _generar_con_groq(p, agente_id=agente_id)), ('Gemini', lambda p: _generar_con_gemini(p, agente_id=agente_id))]

    last_error = None
    for nombre, fn in proveedores:
        try:
            print(f"[{etiqueta}] Intentando con {nombre}...")
            resultado = fn(prompt)
            print(f"[{etiqueta}] OK: Exito con {nombre}")
            return resultado
        except Exception as e:
            print(f"[{etiqueta}] FAILED: {nombre} fallo: {e}")
            last_error = e

    raise RuntimeError(f"Ambos proveedores de IA fallaron. Último error: {last_error}")

def generar_mensaje_ia(propiedad, estrategia):
    """
    Generates a personalized message using AI based on the selected strategy.
    Uses primary provider with automatic fallback.
    """
    agente_nombre = get_config('agente_nombre') or "Asesor"
    barrio = propiedad.get('barrio', 'la zona')
    titulo = propiedad.get('titulo', '')
    descripcion = propiedad.get('descripcion', '')

    contexto_agente = f"""
    Tu nombre es {agente_nombre}. Sos Especialista en Comercialización de Propiedades y Estratega de Marketing Inmobiliario.
    Tu objetivo es la CAPTACIÓN de la propiedad. Querés que el dueño te elija para vender su propiedad por él.
    NO menciones a ninguna franquicia ni marca corporativa. Presentate como un profesional especializado en herramientas de alta tecnología.
    No digas que tenés clientes buscando ya, decí que tenés la estrategia técnica necesaria para encontrar al comprador real.
    
    Tu propuesta de valor estrella se basa en la "Máxima Exposición Digital":
    - Publicación en 15 portales inmobiliarios simultáneamente.
    - Campañas de Publicidad Paga (Ads) segmentadas en Facebook e Instagram.
    - Uso de "Superdestacados" para estar siempre en las primeras posiciones.
    - Sistema de red colaborativa con más de 3000 colegas locales para acelerar la venta.
    """

    prompts = {
        'marketing': f"""
            {contexto_agente}
            ESTRATEGIA: El Estratega Digital.
            ENFOQUE: Empezar directo con el valor: "Publicar en portales hoy no alcanza". Explicar brevemente tu plan de anuncios pagos en redes sociales para atraer demanda real.
            DATOS PROPIEDAD: Título: {titulo}. Descripción: {descripcion}. Barrio: {barrio}.
            TAREA: Escribí un mensaje corto (máximo 400 caracteres) para WhatsApp que sea profesional, disruptivo y que empiece con el beneficio directo para el dueño.
        """,
        'red_ferrari': f"""
            {contexto_agente}
            ESTRATEGIA: Potencia de Red Colaborativa Inmobiliaria.
            ENFOQUE: Empezar con la escala: "Tu propiedad merece ser vista por los 3000 agentes de la zona". Explicar que compartís la comisión para acelerar la venta. Velocidad y alcance.
            DATOS PROPIEDAD: Título: {titulo}. Descripción: {descripcion}. Barrio: {barrio}.
            TAREA: Escribí un mensaje corto (máximo 400 caracteres) para WhatsApp que muestre fuerza de venta, profesionalismo y velocidad.
        """,
        'red_inmobiliaria': f"""
            {contexto_agente}
            ESTRATEGIA: Potencia de Red Colaborativa Inmobiliaria.
            ENFOQUE: Empezar con la escala: "Tu propiedad merece ser vista por los 3000 agentes de la zona". Explicar que compartís la comisión para acelerar la venta. Velocidad y alcance.
            DATOS PROPIEDAD: Título: {titulo}. Descripción: {descripcion}. Barrio: {barrio}.
            TAREA: Escribí un mensaje corto (máximo 400 caracteres) para WhatsApp que muestre fuerza de venta, profesionalismo y velocidad.
        """,
        'followup_valor': f"""
            {contexto_agente}
            ESTRATEGIA: El Consultor de Valor (Seguimiento).
            ESCENARIO: Ya le enviaste un mensaje inicial y no respondió. 
            ENFOQUE: No preguntes "si vio tu mensaje". Aporta un dato técnico (fotos, precio, segmentación) que le sirva para mejorar su publicación actual. Mostrate como un consultor experto y desinteresado.
            DATOS PROPIEDAD: Título: {titulo}. Descripción: {descripcion}. Barrio: {barrio}.
            TAREA: Escribí un segundo mensaje para WhatsApp (máximo 400 caracteres) que sea útil y levante su curiosidad sobre tu método de trabajo.
        """
    }

    prompt = prompts.get(estrategia)
    if not prompt:
        if estrategia.startswith('followup_semana_'):
            prompt = prompts['followup_valor']
        else:
            prompt = prompts['marketing']

    try:
        return _generar_con_ia(prompt, etiqueta="MensajeIA")
    except Exception as e:
        return f"Error generando mensaje: {str(e)}"

def resumir_propiedad_ia(titulo, descripcion):
    """
    Generates a structured summary of a property for reports.
    Returns a dict with 'nuevo_titulo' and 'resumen_ejecutivo', or raw text on fallback.
    Uses primary AI provider with automatic fallback to secondary.
    If both fail, returns a graceful degraded response.
    """
    prompt = f"""
    Como experto asesor inmobiliario, mejorá y resumí la siguiente propiedad para un reporte de cliente.
    
    TÍTULO ORIGINAL: {titulo}
    DESCRIPCIÓN ORIGINAL: {descripcion}
    
    TAREA:
    1. Creá un NUEVO TÍTULO atractivo y comercial para la propiedad (máximo 60 caracteres). No repitas la fuente.
    2. Escribí un resumen ejecutivo atractivo (aprox. 3 líneas) seguido de una lista de 3 a 5 "Bullets" con las características técnicas clave (empezando con emojis).
    
    FORMATO OBLIGATORIO: Respondé ÚNICAMENTE con un objeto JSON válido con la siguiente estructura exacta:
    {{
        "nuevo_titulo": "El título comercial que creaste",
        "resumen_ejecutivo": "El resumen atractivo y vendedor\\n\\n- 🛏️ Bullet 1\\n- 📐 Bullet 2"
    }}
    """

    try:
        text = _generar_con_ia(prompt, etiqueta="ResumenIA")
        text_clean = text.strip()
        # Robust cleanup of markdown wrappers or conversational intro/outro text
        json_match = re.search(r'\{.*\}', text_clean, re.DOTALL)
        if json_match:
            text_clean = json_match.group(0)
            
        try:
            parsed = json.loads(text_clean)
            if isinstance(parsed, dict) and ('nuevo_titulo' in parsed or 'resumen_ejecutivo' in parsed):
                return {
                    'nuevo_titulo': parsed.get('nuevo_titulo') or titulo[:60],
                    'resumen_ejecutivo': parsed.get('resumen_ejecutivo') or (descripcion[:400] if descripcion else 'Sin descripción.')
                }
        except json.JSONDecodeError:
            pass

        if text.strip():
            # If we still have raw conversational text, attempt to isolate the fields manually
            # or return it formatted cleanly
            return {
                'nuevo_titulo': titulo[:60] if titulo else 'Propiedad',
                'resumen_ejecutivo': text.strip()
            }
    except Exception as e:
        print(f"[ResumenIA] Ambos proveedores fallaron, usando fallback sin IA: {e}")

    return {
        'nuevo_titulo': titulo[:60] if titulo else 'Propiedad en venta',
        'resumen_ejecutivo': descripcion[:400] if descripcion else 'Sin descripción disponible.'
    }


def generar_propuestas_prospeccion_ia(agente_nombre="Agente", context_summary=""):
    """
    Genera 6 propuestas o estrategias diarias de prospección inmobiliaria con la IA.
    Utiliza Gemini como proveedor primario y Groq como fallback.
    """
    prompt = f"""
    Sos el consultor estratégico de ventas inmobiliarias de {agente_nombre}.
    Tu objetivo es sugerirle hoy 6 acciones concretas y creativas para PROSPECTAR y CAPTAR nuevos clientes o propiedades.

    CONTEXTO ACTUAL DEL CRM:
    {context_summary or 'Inmobiliaria activa en Argentina, enfocada en captación de propiedades, seguimiento de contactos y venta residencial.'}

    REGLAS:
    - Generá exactamente 6 propuestas accionables, cortas y directas.
    - Usá emojis al inicio de cada propuesta.
    - Cada propuesta debe incluir: Título en negrita, Breve explicación (máximo 2 oraciones) y una Acción Recomendada inmediata.
    - Enfocate en técnicas de prospección moderna: reactivación de contactos fríos, publicaciones estratégicas en IG/WhatsApp, seguimiento de tasaciones o propiedades sin movimiento, alianzas/referidos y clientes compradores.

    FORMATO DE SALIDA (JSON VÁLIDO):
    [
        {{
            "titulo": "🎯 Nombre de la estrategia 1",
            "descripcion": "Explicación corta de la oportunidad.",
            "accion": "Paso concreto a ejecutar hoy"
        }}
    ]
    Respondé ÚNICAMENTE con la matriz JSON de 6 elementos.
    """
    try:
        raw_text = _generar_con_ia(prompt, etiqueta="ProspeccionIA")
        text_clean = raw_text.strip()
        json_match = re.search(r'\[.*\]', text_clean, re.DOTALL)
        if json_match:
            text_clean = json_match.group(0)
        parsed = json.loads(text_clean)
        if isinstance(parsed, list) and len(parsed) >= 2:
            return parsed
    except Exception as e:
        print(f"[ProspeccionIA] Error generando propuestas de prospección: {e}")

    # Fallback default 6 ideas if LLM returns non-JSON or offline
    return [
        {
            "titulo": "🔥 Contactar Prospectos Fríos (+30 días)",
            "descripcion": "Tenés contactos en la base que no registran interacción hace más de un mes.",
            "accion": "Enviar mensaje corto de reactivación a los 5 primeros contactos de la lista."
        },
        {
            "titulo": "📱 Historia de Oportunidad en Redes",
            "descripcion": "Subir una foto atractiva de una propiedad destacada a Instagram Stories y WhatsApp Status.",
            "accion": "Programar 2 placas para publicar hoy desde la agenda de redes."
        },
        {
            "titulo": "🏠 Seguimiento de Tasaciones Pendientes",
            "descripcion": "Revisar clientes que recibieron una tasación en los últimos 60 días sin cerrar captación.",
            "accion": "Ofrecer un reporte actualizado del mercado para reabrir conversación."
        },
        {
            "titulo": "🤝 Red Colaborativa de Colegas",
            "descripcion": "Contactar a 3 colegas inmobiliarios de la zona para compartir fichas activas y cruzar compradores.",
            "accion": "Proponer cruce de búsquedas activas con 2 agentes de confianza."
        },
        {
            "titulo": "📊 Actualización de ACM en Zona Clave",
            "descripcion": "Identificar propiedades que llevan más de 60 días en portales sin ofertas firmes.",
            "accion": "Preparar informe con datos comparativos de cierre de precio reales."
        },
        {
            "titulo": "🎯 Micro-Campaña de Anuncios Segmentados",
            "descripcion": "Lanzar promoción digital de la mejor captación de la semana en redes sociales.",
            "accion": "Definir presupuesto diario mínimo en Meta Ads para la propiedad estrella."
        }
    ]

