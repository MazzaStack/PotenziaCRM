import sqlite3
import os
from werkzeug.security import generate_password_hash

db_path = r'c:\Users\Germa\OneDrive\Trabajo\Captador de propiedades\database\captador.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

def add_column(table, col_name, col_type):
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
        print(f"Added {col_name} to {table}")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            print(f"Column {col_name} already exists in {table}")
        else:
            print(f"Error adding {col_name} to {table}: {e}")

# New Contacts fields
add_column('contactos', 'categoria', "TEXT DEFAULT 'C'")
add_column('contactos', 'fecha_nacimiento', "TEXT")
add_column('contactos', 'aniversario_casa', "TEXT")
add_column('contactos', 'busqueda_activa', "INTEGER DEFAULT 0")
add_column('contactos', 'filtros_busqueda_json', "TEXT")

# Tasaciones table
c.execute('''
    CREATE TABLE IF NOT EXISTS tasaciones_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo_operacion TEXT,
        tipo_propiedad TEXT,
        metros_cubiertos REAL,
        metros_totales REAL,
        ambientes INTEGER,
        habitaciones INTEGER,
        zona TEXT,
        precio_bajo REAL,
        precio_medio REAL,
        precio_alto REAL,
        fecha DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')

# Update admin user if necessary
# First check if GermanMazza exists
c.execute("SELECT 1 FROM usuarios WHERE usuario = 'GermanMazza'")
if not c.fetchone():
    h = generate_password_hash('casa@5544')
    c.execute("INSERT OR IGNORE INTO usuarios (usuario, password_hash, nombre_display) VALUES (?, ?, ?)", 
              ('GermanMazza', h, 'German Mazza'))
    print("User GermanMazza created")

conn.commit()
conn.close()
print("Migration completed successfully")
