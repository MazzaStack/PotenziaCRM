"""
SCRIPT DE PRUEBA DE CAMPO - Publicador de Historias
======================================================
Inserta una historia de prueba con horario YA PASADO de hoy
para que el worker la publique en el próximo ciclo (15 segundos).

USO:
  python test_publicador.py insert    → inserta la placa de prueba
  python test_publicador.py status    → muestra estado actual en la DB
  python test_publicador.py clean     → borra la placa de prueba
"""

import sys
import os
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, r'C:\Users\Germa\OneDrive\Trabajo\CRM')
from database import db

MARKER = 'TEST_PRUEBA_PUBLICADOR'

def find_test_image():
    """Busca cualquier imagen .jpg en static/historias para usar como prueba."""
    base = r'C:\Users\Germa\OneDrive\Trabajo\CRM\static\historias'
    if not os.path.exists(base):
        return None
    for root, dirs, files in os.walk(base):
        for f in files:
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                full = os.path.join(root, f)
                # Convertir a ruta relativa tipo /static/historias/...
                rel = full.replace(r'C:\Users\Germa\OneDrive\Trabajo\CRM', '').replace('\\', '/')
                return rel
    return None

def cmd_insert():
    conn = db.get_db()
    
    # Verificar si ya existe una prueba activa
    existing = conn.execute(
        "SELECT id, estado FROM historias_redes WHERE error_log = ?", (MARKER,)
    ).fetchone()
    if existing:
        print(f"[!] Ya existe una placa de prueba (ID {existing['id']}, estado: {existing['estado']})")
        print("    Usá: python test_publicador.py status  para ver su estado")
        conn.close()
        return

    # Buscar imagen existente
    imagen = find_test_image()
    if not imagen:
        print("[!] No se encontró ninguna imagen en static/historias/")
        print("    Subí cualquier placa desde el CRM primero.")
        conn.close()
        return

    # Programar para HOY, hace 5 minutos (ya pasó el horario → publica en el próximo ciclo)
    now = datetime.now()
    hace_5min = (now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    today = now.strftime('%Y-%m-%d')

    conn.execute("""
        INSERT INTO historias_redes 
        (archivo_path, fecha_programada, orden, estado, whatsapp, instagram, reintentos, error_log)
        VALUES (?, ?, 6, 'pendiente', 1, 0, 0, ?)
    """, (imagen, today, MARKER))
    conn.commit()

    # Buscar el ID recién insertado
    new_row = conn.execute(
        "SELECT id FROM historias_redes WHERE error_log = ?", (MARKER,)
    ).fetchone()
    conn.close()

    print(f"")
    print(f"✅ PLACA DE PRUEBA INSERTADA")
    print(f"   ID: {new_row['id']}")
    print(f"   Imagen: {imagen}")
    print(f"   Fecha: {today} (hoy)")
    print(f"   Orden: 6 (sin horario base → publica en cualquier momento)")
    print(f"")
    print(f"⏳ El worker la detectará en el próximo ciclo (máx. 15 segundos).")
    print(f"   Ejecutá:  python test_publicador.py status")
    print(f"   O mirá el log:  C:\\FerrariDB\\logs\\whatsapp_worker_console.log")

def cmd_status():
    conn = db.get_db()
    rows = conn.execute("""
        SELECT id, estado, fecha_programada, orden, whatsapp, instagram, 
               fecha_publicacion, reintentos, archivo_path
        FROM historias_redes 
        WHERE error_log = ? OR estado IN ('pendiente', 'publicando', 'completado')
        ORDER BY id DESC LIMIT 15
    """, (MARKER,)).fetchall()

    print(f"\n{'ID':>4}  {'ESTADO':<30}  {'FECHA PROG.':<20}  {'PUBLICADO EN'}")
    print("-" * 85)
    for r in rows:
        marker = " ← PRUEBA" if r.get('error_log') == MARKER else ""
        pub = r['fecha_publicacion'] or '-'
        print(f"{r['id']:>4}  {r['estado']:<30}  {str(r['fecha_programada']):<20}  {pub}{marker}")
    conn.close()

def cmd_clean():
    conn = db.get_db()
    row = conn.execute(
        "SELECT id, estado FROM historias_redes WHERE error_log = ?", (MARKER,)
    ).fetchone()
    if not row:
        print("[i] No hay placa de prueba para limpiar.")
        conn.close()
        return
    conn.execute("DELETE FROM historias_redes WHERE error_log = ?", (MARKER,))
    conn.commit()
    conn.close()
    print(f"✅ Placa de prueba ID {row['id']} eliminada.")

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if cmd == 'insert':
        cmd_insert()
    elif cmd == 'status':
        cmd_status()
    elif cmd == 'clean':
        cmd_clean()
    else:
        print(__doc__)
