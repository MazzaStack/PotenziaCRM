import sqlite3
import os
import glob

def migrate_db(db_path):
    print(f"Migrando {db_path}...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column exists before adding
        cursor.execute("PRAGMA table_info(contactos)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'mac' not in columns:
            cursor.execute("ALTER TABLE contactos ADD COLUMN mac INTEGER DEFAULT 0")
            print("  - Added 'mac' column")
            
        if 'intencion_ia' not in columns:
            cursor.execute("ALTER TABLE contactos ADD COLUMN intencion_ia TEXT")
            print("  - Added 'intencion_ia' column")
            
        if 'recordatorio_activo' not in columns:
            cursor.execute("ALTER TABLE contactos ADD COLUMN recordatorio_activo INTEGER DEFAULT 0")
            print("  - Added 'recordatorio_activo' column")
            
        if 'recordatorio_dias' not in columns:
            cursor.execute("ALTER TABLE contactos ADD COLUMN recordatorio_dias INTEGER")
            print("  - Added 'recordatorio_dias' column")
            
        if 'recordatorio_fecha' not in columns:
            cursor.execute("ALTER TABLE contactos ADD COLUMN recordatorio_fecha TEXT")
            print("  - Added 'recordatorio_fecha' column")
            
        conn.commit()
        print("  Migración exitosa.")
    except Exception as e:
        print(f"  Error migrando {db_path}: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Migrate master DB
    master_db = os.path.join(base_dir, 'database', 'captador.db')
    if os.path.exists(master_db):
        migrate_db(master_db)
    else:
        print(f"Master DB no encontrada en: {master_db}")
        
    # Migrate user DBs
    user_dbs_pattern = os.path.join(base_dir, 'database', 'usuarios', '*.db')
    for db_path in glob.glob(user_dbs_pattern):
        migrate_db(db_path)
        
    print("Proceso de migración finalizado.")
