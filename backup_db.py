import os
import sys
import json
import subprocess
from datetime import datetime

def main():
    db_config_path = 'db_config.json'
    if not os.path.exists(db_config_path):
        print("Error: No se encontró db_config.json")
        return
        
    with open(db_config_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
        
    db_type = cfg.get("db_type")
    if db_type != "postgresql":
        print(f"La base de datos activa es {db_type}. Este script es para PostgreSQL.")
        return
        
    env = cfg.get("active_env", "development")
    # Fallback to 'local' if the active environment name is not directly a key in postgres config
    db_uri = cfg.get("postgres", {}).get(env) or cfg.get("postgres", {}).get("local")
    
    if not db_uri:
        print("Error: No se encontró la URI de conexión de PostgreSQL.")
        return
        
    # Crear nombre de archivo con fecha y hora
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup_{env}_{timestamp}.sql"
    
    print(f"Iniciando backup de PostgreSQL ({env})...")
    print(f"Guardando en: {backup_file}")
    
    # Ejecutar pg_dump usando la URI de conexión
    try:
        # pg_dump acepta la URI directamente con el parámetro --dbname
        cmd = ["pg_dump", "--dbname=" + db_uri, "-F", "p", "-f", backup_file]
        
        # Ejecutar proceso
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"¡Backup finalizado con éxito! Archivo creado: {backup_file}")
        else:
            print("Error al ejecutar pg_dump:")
            print(result.stderr)
            print("\nNota: Asegúrate de que PostgreSQL (pg_dump) esté agregado a las variables de entorno (PATH) del servidor.")
    except FileNotFoundError:
        print("Error: No se encontró el comando 'pg_dump' en el sistema.")
        print("Por favor, asegúrate de que PostgreSQL esté instalado y que 'pg_dump' esté disponible en el PATH.")
    except Exception as e:
        print(f"Ocurrió un error inesperado: {e}")

if __name__ == '__main__':
    main()
