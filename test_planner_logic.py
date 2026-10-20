import sys
import os
from datetime import datetime, timedelta

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.db import get_db, insert_propiedad, get_ready_for_next_step, update_planificador_semana, get_planificador
import lib.automation_worker as worker
from lib.automation_worker import procesar_automatizacion

# Mock can_send_now to bypass time restrictions during test
worker.can_send_now = lambda: (True, "OK_TEST")

def test_10_week_logic():
    print("--- START TEST ---")
    
    conn = get_db()
    # Clean
    conn.execute("DELETE FROM comunicaciones WHERE propiedad_id IN (SELECT id FROM propiedades WHERE titulo = 'TEST_PROP_PLANNER')")
    conn.execute("DELETE FROM propiedades WHERE titulo = 'TEST_PROP_PLANNER'")
    conn.commit()
    
    prop_id = insert_propiedad({
        'portal': 'test',
        'url': 'http://test.com/planner',
        'titulo': 'TEST_PROP_PLANNER',
        'telefono': '1122334455'
    })
    conn.execute("UPDATE propiedades SET estado = 'contactada' WHERE id = ?", (prop_id,))
    conn.commit()
    
    # Step 1 sent 8 days ago
    eight_days_ago = (datetime.now() - timedelta(days=8)).strftime('%Y-%m-%d %H:%M:%S')
    conn.execute("""
        INSERT INTO comunicaciones (propiedad_id, tipo, mensaje, fecha_enviada, estado, paso)
        VALUES (?, 'whatsapp', 'Hello!', ?, 'enviada', 1)
    """, (prop_id, eight_days_ago))
    conn.commit()
    
    # 3. Check if ready for step 2
    ready = get_ready_for_next_step(limit=10)
    found = [p for p in ready if p['id'] == prop_id]
    if found:
        print("OK: Propiedad detectada para el paso: " + str(found[0]['siguiente_paso']))
    else:
        print("FAIL: Propiedad NO detectada para seguimiento.")
        conn.close()
        return

    # 4. Test Fixed Message Logic
    print("--- Testing Fixed Message ---")
    msg_fijo = "ESTO ES UN MENSAJE FIJO SEMANA 2 TEST_PLANNER"
    update_planificador_semana(2, msg_fijo, 1) # Enable fixed
    
    procesar_automatizacion()
    
    last_comm = conn.execute("SELECT * FROM comunicaciones WHERE propiedad_id = ? ORDER BY id DESC LIMIT 1", (prop_id,)).fetchone()
    if last_comm['mensaje'] == msg_fijo:
        print("OK: El worker uso el mensaje FIJO.")
    else:
        print("FAIL: El worker uso: " + str(last_comm['mensaje']))

    # 5. Test IA Logic
    print("--- Testing IA Fallback ---")
    update_planificador_semana(2, msg_fijo, 0) # Disable
    
    # Ready for Step 3
    conn.execute("""
        INSERT INTO comunicaciones (propiedad_id, tipo, mensaje, fecha_enviada, estado, paso)
        VALUES (?, 'whatsapp', 'Step 2 sent', ?, 'enviada', 2)
    """, (prop_id, eight_days_ago))
    conn.commit()
    
    procesar_automatizacion()
    
    last_comm = conn.execute("SELECT * FROM comunicaciones WHERE propiedad_id = ? ORDER BY id DESC LIMIT 1", (prop_id,)).fetchone()
    if msg_fijo not in (last_comm['mensaje'] or ""):
         print("OK: El worker uso IA (Gemini).")
    else:
         print("FAIL: Seguia usando el mensaje fijo.")

    conn.close()
    print("--- END TEST ---")

if __name__ == "__main__":
    test_10_week_logic()
