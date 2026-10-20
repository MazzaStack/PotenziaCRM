import time
from datetime import datetime, timedelta
import random
from database.db import get_db, insert_comunicacion, update_propiedad_estado
from lib.gemini_service import generar_mensaje_ia
from lib.utils import clean_phone_argentina

def get_next_property_to_contact():
    """
    Finds the next property to contact based on German's rules:
    - Status 'nueva'
    - Has phone
    - Not contacted before
    - Rotates strategy (A/B)
    """
    conn = get_db()
    # Find a property that doesn't have communications yet
    # AND whose phone (last 8 digits) hasn't been contacted in ANY other property
    query = """
    SELECT p.* FROM propiedades p
    WHERE p.estado = 'nueva' 
    AND p.telefono IS NOT NULL AND LENGTH(p.telefono) >= 8
    AND NOT EXISTS (
        SELECT 1 FROM comunicaciones c
        JOIN propiedades p2 ON c.propiedad_id = p2.id
        WHERE SUBSTR(p2.telefono, -8) = SUBSTR(p.telefono, -8)
    )
    AND NOT EXISTS (
        SELECT 1 FROM lista_negra ln
        WHERE SUBSTR(ln.telefono, -8) = SUBSTR(p.telefono, -8)
    )
    ORDER BY p.fecha_captacion ASC
    LIMIT 1
    """
    row = conn.execute(query).fetchone()
    
    # Determine next strategy by counting strategy uses
    stats = conn.execute("SELECT estrategia, enviados FROM estadisticas_ia").fetchall()
    stats_dict = {r['estrategia']: r['enviados'] for r in stats}
    
    # Rotate: Pick the one with fewer sends, or random if equal
    if stats_dict.get('marketing', 0) <= stats_dict.get('red_ferrari', 0):
        estrategia = 'marketing'
    else:
        estrategia = 'red_ferrari'
        
    conn.close()
    return dict(row) if row else None, estrategia

def can_send_now():
    """
    Checks if it's currently between 10:00 and 18:00 (Mon-Fri)
    and if at least 2 hours have passed since the last sent message.
    """
    now = datetime.now()
    # 1. Check window (10:00 - 18:00)
    if not (10 <= now.hour < 18):
        # Outside window
        return False, "Fuera de horario comercial (10:00 - 18:00)"
    
    # 2. Check Day (Mon=0, Fri=4)
    if now.weekday() > 4:
        return False, "Fin de semana (Lunes a Viernes solamente)"

    # 3. Check daily limit for safety (max 100 per day to avoid Meta bans)
    conn = get_db()
    today_str = now.strftime('%Y-%m-%d')
    count = conn.execute(
        "SELECT COUNT(*) FROM comunicaciones WHERE tipo = 'whatsapp' AND date(fecha_programada) = ?", 
        (today_str,)
    ).fetchone()[0]
    conn.close()

    if count >= 100:
        return False, f"Límite diario de seguridad alcanzado (100 envíos por día)"

    return True, "OK"

def get_daily_step_counts():
    """Returns a dictionary of {paso: count} for today's scheduled messages."""
    conn = get_db()
    today_str = datetime.now().strftime('%Y-%m-%d')
    rows = conn.execute(
        "SELECT paso, COUNT(*) as cnt FROM comunicaciones WHERE tipo = 'whatsapp' AND date(fecha_programada) = ? GROUP BY paso", 
        (today_str,)
    ).fetchall()
    conn.close()
    return {r['paso']: r['cnt'] for r in rows}

def get_prioritized_candidate():
    """
    Finds the next property to contact with strict quota rules:
    - Max 10 messages per step (week).
    - Checks priority from Week 10 down to Week 1.
    """
    counts = get_daily_step_counts()
    
    from database.db import get_ready_for_next_step
    # Fetch all ready follow-ups to evaluate in memory
    ready = get_ready_for_next_step(limit=500, limit_per_week=0)
    
    # Priority: Follow-ups Week 10 down to Week 2
    for paso in range(10, 1, -1):
        if counts.get(paso, 0) < 10:
            candidate = next((p for p in ready if p['siguiente_paso'] == paso), None)
            if candidate:
                return candidate, paso, f'followup_semana_{paso}'
                
    # Priority: Week 1 (New properties)
    if counts.get(1, 0) < 10:
        prop, est = get_next_property_to_contact()
        if prop:
            return prop, 1, est
            
    return None, None, None

def obtener_mensaje_planificador(propiedad, paso, planner):
    """Get the planner message for a given week/step, with placeholder replacement.
    Returns the message string or None if no planner message is configured."""
    week_config = next((w for w in planner if w['semana'] == paso), None)
    if week_config and week_config.get('habilitado') and week_config.get('mensaje', '').strip():
        msg = week_config['mensaje']
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
            return msg
    return None

def procesar_automatizacion():
    """
    Main loop for background automation.
    Returns a status message string.
    """
    print(f"[{datetime.now()}] Iniciando ciclo de automatizacion...")
    
    can_send, reason = can_send_now()
    if not can_send:
        print(f"  PAUSA: {reason}")
        return f"Pausa: {reason}"

    # Get next candidate using the strict tier-based priority logic (10 down to 1)
    prop, paso, estrategia = get_prioritized_candidate()

    if not prop:
        print("  INFO: Cuota de envíos diarios llena o no hay contactos listos para hoy.")
        return "Cuota de envíos diarios llena o no hay contactos listos."

    print(f"  PROCESANDO: {prop['titulo']} ({prop['id']})")
    print(f"  ESTRATEGIA: {estrategia} (Paso {paso})")

    # 1. Determine Message: Fixed from Planner OR IA (Gemini)
    from database.db import get_planificador
    planner = get_planificador()
    
    mensaje = obtener_mensaje_planificador(prop, paso, planner)
    if mensaje:
        print(f"  INFO: Usando mensaje del planificador para semana {paso}")
        estrategia = f'planificador_semana_{paso}'
    else:
        print(f"  INFO: Generando mensaje con IA (Gemini) para estrategia {estrategia}")
        mensaje = generar_mensaje_ia(prop, estrategia)

    if not mensaje or mensaje.startswith("Error"):
        print(f"  ERROR IA/PLANNER: {mensaje}")
        return f"Error generando mensaje: {mensaje}"

    # 2. Add to communications
    comm_data = {
        'propiedad_id': prop['id'],
        'tipo': 'whatsapp',
        'mensaje': mensaje,
        'fecha_programada': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'estado': 'pendiente',
        'paso': paso,
        'estrategia_usada': estrategia
    }
    
    comm_id = insert_comunicacion(comm_data)
    
    # Update strategy stats (for reporting)
    if paso == 1:
        conn = get_db()
        # Initial strategies rotate marketing/red_ferrari
        if estrategia in ['marketing', 'red_ferrari']:
            conn.execute("UPDATE estadisticas_ia SET enviados = enviados + 1 WHERE estrategia = ?", (estrategia,))
        conn.execute("UPDATE comunicaciones SET estrategia_usada = ? WHERE id = ?", (estrategia, comm_id))
        conn.commit()
        conn.close()
    
    # Transition property status
    if paso == 1:
        update_propiedad_estado(prop['id'], 'contactada')
    elif paso >= 10:
        # STOP TOTAL after week 10 (also handled by marcar_comunicacion_enviada)
        update_propiedad_estado(prop['id'], 'finalizada_10s')
    elif paso > 1:
        # Keep track that it's in follow-up
        update_propiedad_estado(prop['id'], 'en_seguimiento')
    
    result_msg = f"Mensaje encolado para '{prop['titulo'][:40]}...' - Semana {paso} ({estrategia})"
    print(f"  LISTO: {result_msg}")
    return result_msg

if __name__ == "__main__":
    import time
    import argparse
    parser = argparse.ArgumentParser(description="AI Message Worker")
    parser.add_argument('--db', type=str, help="Custom database file path")
    args, unknown = parser.parse_known_args()
    
    if args.db:
        import database.db
        database.db.MASTER_DB_PATH = args.db
        print(f">>>> CONTEXTO: Redirigiendo base de datos a: {args.db}")

    print(">>> Iniciando worker de Inteligencia Artificial en SEGUNDO PLANO.")
    print(">>> Este proceso revisará la base continuamente para contactar dueños.")
    while True:
        try:
            procesar_automatizacion()
        except Exception as e:
            print(f"Error crítico en el worker: {e}")
        # Descansa un par de minutos antes del próximo ciclo para simular ritmo humano
        time.sleep(150)
