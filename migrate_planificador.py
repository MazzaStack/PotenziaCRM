import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database', 'captador.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    try:
        # Create planificador_mensajes table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS planificador_mensajes (
                semana INTEGER PRIMARY KEY,
                mensaje TEXT,
                habilitado INTEGER DEFAULT 0
            )
        """)
        
        # Initialize 10 weeks if not exists
        for i in range(1, 11):
            conn.execute("INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (?, ?, 0)", (i, ""))
            
        conn.commit()
        print("Migración exitosa: Tabla planificador_mensajes creada e inicializada.")
    except Exception as e:
        print(f"Error en migración: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
