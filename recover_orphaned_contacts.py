import sys
import os

# Ensure we can import from database
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import db

def main():
    print("====================================================")
    # Load config to print active database type and environment
    cfg = db.load_db_config()
    db_type = cfg.get("db_type", "sqlite")
    env = cfg.get("active_env", "development")
    
    print(f"Buscando base de datos activa...")
    print(f"Tipo de base de datos: {db_type.upper()}")
    if db_type == "postgresql":
        print(f"Entorno: {env.upper()}")
    print("====================================================\n")

    conn = db.get_db()
    try:
        # 1. List users
        print("Buscando usuarios registrados...")
        users_rows = conn.execute("SELECT id, usuario, nombre_display, rol FROM usuarios ORDER BY id").fetchall()
        users = [dict(r) for r in users_rows]
        
        if not users:
            print("No se encontraron usuarios en la base de datos.")
            return
            
        print("Usuarios disponibles:")
        for u in users:
            print(f"  ID: {u['id']} | Usuario: {u['usuario']} | Nombre: {u['nombre_display']} | Rol: {u['rol']}")
        print()
        
        # 2. Check AlondraBloise
        alondra = next((u for u in users if u['usuario'].lower() == 'alondrabloise'), None)
        if alondra:
            print(f"Se detectó al usuario 'AlondraBloise' con ID: {alondra['id']}")
            target_id = alondra['id']
            target_username = alondra['usuario']
        else:
            print("AVISO: No se encontró exactamente el usuario 'AlondraBloise'.")
            ans = input("Ingresa el ID del usuario al que deseas asignar los contactos huérfanos: ").strip()
            try:
                target_id = int(ans)
                selected_user = next((u for u in users if u['id'] == target_id), None)
                if not selected_user:
                    print("ID de usuario no válido.")
                    return
                target_username = selected_user['usuario']
            except ValueError:
                print("Entrada no válida.")
                return
                
        # 3. Count contacts with NULL agente_id
        print("\nBuscando contactos con agente_id nulo (sin asignar)...")
        
        try:
            count_row = conn.execute("SELECT COUNT(*) as count FROM contactos WHERE agente_id IS NULL").fetchone()
            orphan_count = count_row['count'] if count_row else 0
        except Exception as e:
            print(f"Error al buscar contactos con agente_id nulo: {e}")
            print("Es posible que la tabla 'contactos' no tenga la columna 'agente_id' en este entorno.")
            return

        print(f"Se encontraron {orphan_count} contactos huérfanos (agente_id = NULL).")
        
        if orphan_count == 0:
            print("No hay contactos huérfanos para asignar.")
            return
            
        # 4. Ask for confirmation
        confirm = input(f"\n¿Deseas asignar los {orphan_count} contactos huérfanos al usuario '{target_username}' (ID: {target_id})? (s/n): ").strip().lower()
        if confirm == 's':
            print("Actualizando base de datos...")
            cursor = conn.execute("UPDATE contactos SET agente_id = ? WHERE agente_id IS NULL", (target_id,))
            conn.commit()
            print("¡Actualización exitosa!")
            print(f"Se asignaron {orphan_count} contactos a '{target_username}'. Ahora podrá verlos en su CRM.")
        else:
            print("Operación cancelada por el usuario.")
            
    except Exception as e:
        print(f"Ocurrió un error: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    main()
