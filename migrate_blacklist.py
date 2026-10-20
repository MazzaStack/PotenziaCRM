import sqlite3
import os

def migrate():
    db_path = os.path.join('database', 'captador.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Creando tabla lista_negra...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lista_negra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telefono TEXT UNIQUE NOT NULL,
            motivo TEXT,
            fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    print("Migración completada exitosamente.")

if __name__ == "__main__":
    migrate()
