"""
Reset historias_redes que fallaron para que el bot las reintente con el código nuevo.
Ejecutar: python reset_historias.py
"""
import sqlite3
from datetime import datetime

conn = sqlite3.connect('database/captador.db')
conn.row_factory = sqlite3.Row

# Mostrar estado actual
print("=== Estado actual de historias_redes ===")
rows = conn.execute("SELECT id, estado, reintentos, plataforma, archivo_path FROM historias_redes ORDER BY id").fetchall()
for r in rows:
    print(f"  ID {r['id']} | estado={r['estado']} | reintentos={r['reintentos']} | {r['archivo_path']}")

# Resetear las que fallaron (estado 'error' o reintentos >= 3)
result = conn.execute("""
    UPDATE historias_redes 
    SET estado = 'pendiente', 
        reintentos = 0, 
        fecha_programada = datetime('now')
    WHERE estado LIKE 'error%' OR reintentos >= 3
""")
conn.commit()
print(f"\n✅ Historias reseteadas a 'pendiente': {result.rowcount}")

# Mostrar nuevo estado
print("\n=== Estado después del reset ===")
rows = conn.execute("SELECT id, estado, reintentos, fecha_programada FROM historias_redes ORDER BY id").fetchall()
for r in rows:
    print(f"  ID {r['id']} | estado={r['estado']} | reintentos={r['reintentos']} | programada={r['fecha_programada']}")

conn.close()
print("\nListo. Podés reiniciar el bridge ahora.")
