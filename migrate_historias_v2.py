"""
migrate_historias_v2.py - Migra la tabla historias_redes para soportar:
  - Toggle individual por red social (instagram, whatsapp)
  - Asociacion con agente (agente_id) para calendarizacion por admin
  
Ejecutar: python migrate_historias_v2.py
"""
import sqlite3
import os
import glob
import json

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(WORKSPACE_DIR, 'db_config.json')
default_db_dir = r"C:\FerrariDB" if os.name == 'nt' else os.path.join(WORKSPACE_DIR, 'database')

DB_DIR = default_db_dir
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f_cfg:
            cfg = json.load(f_cfg)
            if cfg.get('db_dir'):
                DB_DIR = cfg['db_dir']
    except Exception as e:
        print(f"Error reading db_config.json: {e}")

MASTER_DB_PATH = os.path.join(DB_DIR, 'captador.db')
USERS_DB_DIR = os.path.join(DB_DIR, 'usuarios')


def migrate_db(db_path):
    print(f"\nMigrando: {db_path}")
    if not os.path.exists(db_path):
        print(f"  [!] Archivo no encontrado, saltando.")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check if historias_redes table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historias_redes'")
        if not cursor.fetchone():
            print(f"  [!] Tabla historias_redes no existe en esta DB, saltando.")
            conn.close()
            return

        # Get existing columns
        cursor.execute("PRAGMA table_info(historias_redes)")
        existing_columns = [col[1] for col in cursor.fetchall()]

        # Add 'whatsapp' column (default 1 = ON)
        if 'whatsapp' not in existing_columns:
            cursor.execute("ALTER TABLE historias_redes ADD COLUMN whatsapp INTEGER DEFAULT 1")
            print("  [+] Columna 'whatsapp' agregada (default: 1 = activo)")
        else:
            print("  [OK] Columna 'whatsapp' ya existe")

        # Add 'instagram' column (default 0 = OFF)
        if 'instagram' not in existing_columns:
            cursor.execute("ALTER TABLE historias_redes ADD COLUMN instagram INTEGER DEFAULT 0")
            print("  [+] Columna 'instagram' agregada (default: 0 = inactivo)")
        else:
            print("  [OK] Columna 'instagram' ya existe")

        # Add 'agente_id' column (nullable, for admin scheduling)
        if 'agente_id' not in existing_columns:
            cursor.execute("ALTER TABLE historias_redes ADD COLUMN agente_id INTEGER")
            print("  [+] Columna 'agente_id' agregada (nullable)")
        else:
            print("  [OK] Columna 'agente_id' ya existe")

        # Migrate existing 'plataforma' values to new boolean columns
        # plataforma='whatsapp' -> whatsapp=1, instagram=0
        # plataforma='instagram' -> whatsapp=0, instagram=1
        # plataforma='both' -> whatsapp=1, instagram=1
        if 'plataforma' in existing_columns:
            cursor.execute("""
                UPDATE historias_redes 
                SET whatsapp = CASE 
                    WHEN plataforma = 'instagram' THEN 0
                    WHEN plataforma = 'whatsapp' THEN 1
                    WHEN plataforma = 'both' THEN 1
                    ELSE 1
                END,
                instagram = CASE 
                    WHEN plataforma = 'instagram' THEN 1
                    WHEN plataforma = 'whatsapp' THEN 0
                    WHEN plataforma = 'both' THEN 1
                    ELSE 0
                END
            """)
            migrated = cursor.rowcount
            print(f"  [+] Migradas {migrated} filas existentes desde columna 'plataforma' a toggles booleanos")

        conn.commit()
        print(f"  [OK] Migración exitosa en {db_path}")
    except Exception as e:
        print(f"  [ERROR] {e}")
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == '__main__':
    print("=" * 60)
    print("MIGRACIÓN: historias_redes v2 - Multi-platform toggles + agente_id")
    print("=" * 60)

    # Migrate master DB
    print(f"\n[Master DB] {MASTER_DB_PATH}")
    migrate_db(MASTER_DB_PATH)

    # Migrate user DBs
    if os.path.exists(USERS_DB_DIR):
        user_dbs = glob.glob(os.path.join(USERS_DB_DIR, '*.db'))
        if user_dbs:
            print(f"\n[User DBs] Encontradas {len(user_dbs)} bases de datos de agentes")
            for db_path in user_dbs:
                migrate_db(db_path)
        else:
            print(f"\n[User DBs] No se encontraron bases de datos de agentes en {USERS_DB_DIR}")
    else:
        print(f"\n[User DBs] Directorio no encontrado: {USERS_DB_DIR}")

    print("\n" + "=" * 60)
    print("Migración finalizada. Podés reiniciar el servidor Flask.")
    print("=" * 60)
