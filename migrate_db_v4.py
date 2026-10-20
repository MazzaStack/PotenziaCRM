import sqlite3
import os
import sys

# Ensure database path resolved correctly
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(WORKSPACE_DIR)

from database.db import MASTER_DB_PATH, USERS_DB_DIR

def migrate_db(db_path):
    print(f"Migrating database: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Create busquedas_clientes table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS busquedas_clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            tipo_operacion TEXT NOT NULL DEFAULT 'venta',
            tipo_propiedad TEXT NOT NULL DEFAULT 'departamento',
            zona TEXT NOT NULL,
            ambientes INTEGER,
            dormitorios INTEGER,
            min_precio REAL,
            max_precio REAL,
            min_m2 REAL,
            max_m2 REAL,
            extras TEXT,
            keyword TEXT,
            agente_id INTEGER,
            fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
            ultima_ejecucion TEXT,
            propiedades_vistas TEXT DEFAULT '[]',
            FOREIGN KEY (cliente_id) REFERENCES contactos(id),
            FOREIGN KEY (agente_id) REFERENCES usuarios(id)
        );
        """)
        
        # Create cola_correos_clientes table
        conn.execute("""
        CREATE TABLE IF NOT EXISTS cola_correos_clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_dest TEXT NOT NULL,
            asunto TEXT NOT NULL,
            cuerpo_html TEXT NOT NULL,
            fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
            estado TEXT DEFAULT 'pendiente',
            fecha_enviado TEXT,
            error_log TEXT
        );
        """)
        conn.commit()
        print(f"Successfully migrated {db_path}")
    except Exception as e:
        print(f"Error migrating {db_path}: {e}")
    finally:
        conn.close()

def main():
    # Migrate Master DB
    migrate_db(MASTER_DB_PATH)
    
    # Migrate any agent databases if folder exists
    if os.path.exists(USERS_DB_DIR):
        for f in os.listdir(USERS_DB_DIR):
            if f.endswith('.db'):
                migrate_db(os.path.join(USERS_DB_DIR, f))

if __name__ == '__main__':
    main()
