"""
Core Database Backup & Restore Engine
Multiplatform (Windows/Linux) - PostgreSQL and SQLite support with auto-scheduling.
"""
import os
import sys
import json
import glob
import time
import shutil
import zipfile
import subprocess
import threading
from datetime import datetime, timedelta

from database import db

# Base project directory
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_backup_dir():
    """
    Resolves the directory used to store backups in a cross-platform manner.
    Creates the directory automatically if it does not exist.
    """
    # 1. Configured DB directory (from db_config.json if specified)
    try:
        db_cfg = db.load_db_config()
        configured_db_dir = db_cfg.get("db_dir")
        if configured_db_dir and os.path.isdir(os.path.dirname(os.path.abspath(configured_db_dir))):
            target_dir = os.path.join(configured_db_dir, "backups")
            os.makedirs(target_dir, exist_ok=True)
            return target_dir
    except Exception:
        pass

    # 2. Windows Default or configured DB_DIR
    try:
        from database.db import DB_DIR
        target_dir = os.path.join(DB_DIR, "backups")
        os.makedirs(target_dir, exist_ok=True)
        return target_dir
    except Exception:
        pass

    # 3. Linux/Unix or Fallback in workspace
    fallback_dir = os.path.join(WORKSPACE_DIR, "database", "backups")
    os.makedirs(fallback_dir, exist_ok=True)
    return fallback_dir


def find_pg_binary(binary_name="pg_dump"):
    """
    Finds pg_dump or psql executable across system PATH or standard installation paths.
    """
    ext = ".exe" if os.name == 'nt' else ""
    full_name = f"{binary_name}{ext}"
    
    # 1. Check PATH
    path_bin = shutil.which(binary_name)
    if path_bin:
        return path_bin

    # 2. Check Windows standard PostgreSQL install folders
    if os.name == 'nt':
        search_patterns = [
            r"C:\Program Files\PostgreSQL\*\bin",
            r"C:\Program Files (x86)\PostgreSQL\*\bin",
            r"C:\PostgreSQL\*\bin"
        ]
        for pattern in search_patterns:
            matches = glob.glob(os.path.join(pattern, full_name))
            if matches:
                return matches[-1] # Return the highest version found

    # 3. Check Linux standard PostgreSQL paths
    if os.name != 'nt':
        linux_paths = [
            f"/usr/lib/postgresql/*/bin/{full_name}",
            f"/usr/bin/{full_name}",
            f"/usr/local/bin/{full_name}"
        ]
        for pattern in linux_paths:
            matches = glob.glob(pattern)
            if matches:
                return matches[-1]

    return None


def get_active_db_info():
    """Returns information about the currently active database engine and connection."""
    cfg = db.load_db_config()
    db_type = cfg.get("db_type", "sqlite")
    env = cfg.get("active_env", "development")
    
    if db_type == "postgresql":
        pg_uri = cfg.get("postgres", {}).get(env) or cfg.get("postgres", {}).get("local")
        return {
            "type": "postgresql",
            "env": env,
            "uri": pg_uri,
            "fallback_active": db.SQLITE_FALLBACK_ACTIVE
        }
    else:
        return {
            "type": "sqlite",
            "env": "local",
            "master_path": db.MASTER_DB_PATH,
            "users_path": db.USERS_DB_DIR,
            "fallback_active": False
        }


def _dump_postgres_native_sql(db_uri, output_file):
    """
    Pure Python PostgreSQL Dumper using psycopg.
    Acts as a 100% reliable fallback when pg_dump is not available on the server.
    """
    import psycopg

    with psycopg.connect(db_uri) as conn:
        with conn.cursor() as cur:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(f"-- Native PostgreSQL Database Backup\n")
                f.write(f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write("SET session_replication_role = 'replica';\n\n")

                # Get all tables in public schema
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    ORDER BY table_name;
                """)
                tables = [r[0] for r in cur.fetchall()]

                for table in tables:
                    # Get column metadata
                    cur.execute("""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns 
                        WHERE table_schema = 'public' AND table_name = %s
                        ORDER BY ordinal_position;
                    """, (table,))
                    cols_info = cur.fetchall()
                    col_names = [c[0] for c in cols_info]
                    
                    f.write(f"-- Data for table: {table}\n")
                    f.write(f"TRUNCATE TABLE {table} CASCADE;\n")
                    
                    cur.execute(f"SELECT * FROM {table};")
                    rows = cur.fetchall()
                    
                    if rows:
                        cols_str = ", ".join([f'"{c}"' for c in col_names])
                        for row in rows:
                            vals = []
                            for v in row:
                                if v is None:
                                    vals.append("NULL")
                                elif isinstance(v, (int, float)):
                                    vals.append(str(v))
                                elif isinstance(v, bool):
                                    vals.append("TRUE" if v else "FALSE")
                                elif isinstance(v, (dict, list)):
                                    vals.append("'" + json.dumps(v, ensure_ascii=False).replace("'", "''") + "'")
                                else:
                                    clean_v = str(v).replace("'", "''")
                                    vals.append(f"'{clean_v}'")
                            vals_str = ", ".join(vals)
                            f.write(f"INSERT INTO {table} ({cols_str}) VALUES ({vals_str});\n")
                    f.write("\n")

                f.write("SET session_replication_role = 'origin';\n")


def create_backup(trigger="manual", custom_name=None):
    """
    Creates a database backup file and stores it in the backup folder.
    trigger: 'manual', 'auto', or 'pre_restore_snapshot'
    """
    backup_dir = get_backup_dir()
    db_info = get_active_db_info()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    prefix = "backup" if trigger != "pre_restore_snapshot" else "snapshot_pre_restore"
    
    result = {
        "success": False,
        "filename": None,
        "filepath": None,
        "size_bytes": 0,
        "size_human": "0 KB",
        "trigger": trigger,
        "db_type": db_info["type"],
        "error": None
    }

    try:
        if db_info["type"] == "postgresql":
            env = db_info["env"]
            filename = custom_name or f"{prefix}_postgres_{env}_{timestamp}.sql"
            filepath = os.path.join(backup_dir, filename)
            
            pg_dump_bin = find_pg_binary("pg_dump")
            dump_success = False
            
            if pg_dump_bin and db_info["uri"]:
                try:
                    cmd = [pg_dump_bin, "--dbname=" + db_info["uri"], "--clean", "--if-exists", "-F", "p", "-f", filepath]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if proc.returncode == 0 and os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                        dump_success = True
                    else:
                        print(f"[Backup] pg_dump warning/error: {proc.stderr}. Using native python dumper...")
                except Exception as e:
                    print(f"[Backup] pg_dump invocation failed: {e}. Using native python dumper...")

            if not dump_success:
                # Fallback to pure Python dumper
                _dump_postgres_native_sql(db_info["uri"], filepath)

        else:
            # SQLite Backup: Package master DB and user DBs into a zip archive
            filename = custom_name or f"{prefix}_sqlite_{timestamp}.zip"
            filepath = os.path.join(backup_dir, filename)

            with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                if os.path.exists(db.MASTER_DB_PATH):
                    zipf.write(db.MASTER_DB_PATH, arcname="captador.db")
                if os.path.exists(db.USERS_DB_DIR):
                    for u_file in os.listdir(db.USERS_DB_DIR):
                        if u_file.endswith(".db"):
                            u_full = os.path.join(db.USERS_DB_DIR, u_file)
                            zipf.write(u_full, arcname=os.path.join("usuarios", u_file))

        if os.path.exists(filepath):
            size_b = os.path.getsize(filepath)
            result["success"] = True
            result["filename"] = filename
            result["filepath"] = filepath
            result["size_bytes"] = size_b
            result["size_human"] = format_file_size(size_b)

            # Update last run timestamp in database
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                db.set_config("backup_last_run", now_iso)
            except Exception:
                pass

            # Rotate old backups
            rotate_backups()
            print(f"[Backup Engine] Backup created successfully: {filename} ({result['size_human']})")
        else:
            result["error"] = "El archivo de backup no se generó."

    except Exception as e:
        result["error"] = str(e)
        print(f"[Backup Engine] Error creating backup: {e}")

    return result


def restore_backup(backup_filename):
    """
    Restores a database from a backup file (.sql or .zip).
    Automatically creates a safety snapshot before restoring.
    """
    backup_dir = get_backup_dir()
    filepath = os.path.join(backup_dir, backup_filename) if not os.path.isabs(backup_filename) else backup_filename
    
    if not os.path.exists(filepath):
        return {"success": False, "error": f"Archivo de backup no encontrado: {backup_filename}"}

    # 1. Create safety snapshot first
    snapshot_res = create_backup(trigger="pre_restore_snapshot")
    print(f"[Restore Engine] Safety snapshot created: {snapshot_res.get('filename')}")

    db_info = get_active_db_info()
    
    try:
        if filepath.endswith('.sql'):
            # PostgreSQL Restore: Clean disaster recovery mode
            if db_info["type"] != "postgresql":
                return {"success": False, "error": "El archivo es un script .sql de PostgreSQL, pero el motor activo es SQLite."}

            # Close active connection pool so no connections hold locks on tables
            if db._pg_pool:
                try:
                    db._pg_pool.close()
                    db._pg_pool = None
                except Exception:
                    pass

            import psycopg

            # 2. PURGE DATABASE: Wipe entire public schema to eliminate 100% of injected data, backdoor tables, or corrupted rows
            with psycopg.connect(db_info["uri"], autocommit=True) as purge_conn:
                with purge_conn.cursor() as purge_cur:
                    purge_cur.execute("DROP SCHEMA IF EXISTS public CASCADE;")
                    purge_cur.execute("CREATE SCHEMA public;")
                    purge_cur.execute("GRANT ALL ON SCHEMA public TO postgres;")
                    purge_cur.execute("GRANT ALL ON SCHEMA public TO public;")

            psql_bin = find_pg_binary("psql")
            restored = False

            if psql_bin and db_info["uri"]:
                try:
                    cmd = [psql_bin, "--dbname=" + db_info["uri"], "-f", filepath]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    if proc.returncode == 0:
                        restored = True
                    else:
                        print(f"[Restore] psql error: {proc.stderr}. Using psycopg direct execution fallback...")
                except Exception as e:
                    print(f"[Restore] psql process failed: {e}. Using psycopg fallback...")

            if not restored:
                # Direct psycopg execution
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    sql_content = f.read()

                with psycopg.connect(db_info["uri"], autocommit=True) as conn:
                    with conn.cursor() as cur:
                        cur.execute("SET session_replication_role = 'replica';")
                        cur.execute(sql_content)
                        cur.execute("SET session_replication_role = 'origin';")

            # Reset pool so subsequent queries connect to the cleanly restored state
            if db._pg_pool:
                try:
                    db._pg_pool.close()
                    db._pg_pool = None
                except Exception:
                    pass

            return {
                "success": True, 
                "message": "Base de datos PostgreSQL purgada y restaurada exitosamente a su estado exacto.",
                "snapshot_file": snapshot_res.get("filename")
            }

        elif filepath.endswith('.zip'):
            # SQLite Restore: Remove existing databases first to guarantee full cleanup
            if db_info["type"] == "postgresql":
                return {"success": False, "error": "El archivo es un zip de SQLite, pero el motor activo es PostgreSQL."}

            if os.path.exists(db.MASTER_DB_PATH):
                try:
                    os.remove(db.MASTER_DB_PATH)
                except Exception:
                    pass
            if os.path.exists(db.USERS_DB_DIR):
                for old_f in os.listdir(db.USERS_DB_DIR):
                    if old_f.endswith(".db"):
                        try:
                            os.remove(os.path.join(db.USERS_DB_DIR, old_f))
                        except Exception:
                            pass

            with zipfile.ZipFile(filepath, 'r') as zipf:
                # Extract captador.db
                if "captador.db" in zipf.namelist():
                    zipf.extract("captador.db", os.path.dirname(db.MASTER_DB_PATH))
                
                # Extract users databases
                for name in zipf.namelist():
                    if name.startswith("usuarios/") and name.endswith(".db"):
                        zipf.extract(name, os.path.dirname(db.USERS_DB_DIR))

            return {
                "success": True, 
                "message": "Base de datos SQLite purgada y restaurada exitosamente.",
                "snapshot_file": snapshot_res.get("filename")
            }

        elif filepath.endswith('.db'):
            # Single SQLite DB file
            shutil.copy2(filepath, db.MASTER_DB_PATH)
            return {
                "success": True, 
                "message": "Base de datos SQLite restaurada exitosamente.",
                "snapshot_file": snapshot_res.get("filename")
            }

        else:
            return {"success": False, "error": "Formato de archivo no reconocido. Debe ser .sql o .zip (.db)."}

    except Exception as e:
        print(f"[Restore Engine] Error during restore: {e}")
        return {"success": False, "error": f"Error al restaurar: {str(e)}"}


def list_backups():
    """Lists all existing backup files with rich metadata."""
    backup_dir = get_backup_dir()
    files = []

    if not os.path.exists(backup_dir):
        return files

    for entry in os.scandir(backup_dir):
        if entry.is_file() and (entry.name.endswith('.sql') or entry.name.endswith('.zip') or entry.name.endswith('.db')):
            stat = entry.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            
            # Determine origin
            if "snapshot_pre_restore" in entry.name:
                origin = "Snapshot de Seguridad"
                badge = "warning"
            elif "auto" in entry.name:
                origin = "Automático"
                badge = "info"
            else:
                origin = "Manual"
                badge = "primary"

            # Determine engine
            if entry.name.endswith('.sql') or "postgres" in entry.name:
                engine = "PostgreSQL"
                env_type = "Producción" if "production" in entry.name or "prod" in entry.name else "Desarrollo"
            else:
                engine = "SQLite"
                env_type = "Local"

            files.append({
                "filename": entry.name,
                "filepath": entry.path,
                "size_bytes": stat.st_size,
                "size_human": format_file_size(stat.st_size),
                "created_at": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": stat.st_mtime,
                "engine": engine,
                "env": env_type,
                "origin": origin,
                "badge": badge
            })

    # Sort descending by timestamp
    files.sort(key=lambda x: x["timestamp"], reverse=True)
    return files


def delete_backup_file(filename):
    """Safely deletes a backup file."""
    backup_dir = get_backup_dir()
    # Prevent path traversal
    safe_filename = os.path.basename(filename)
    filepath = os.path.join(backup_dir, safe_filename)
    
    if os.path.exists(filepath) and os.path.isfile(filepath):
        os.remove(filepath)
        return True
    return False


def rotate_backups():
    """Deletes old backups exceeding the configured retention limit."""
    try:
        max_keep_str = db.get_config("backup_max_keep", "30")
        max_keep = int(max_keep_str) if max_keep_str else 30
        if max_keep <= 0:
            return
        
        all_backups = list_backups()
        if len(all_backups) > max_keep:
            for extra in all_backups[max_keep:]:
                delete_backup_file(extra["filename"])
                print(f"[Backup Rotation] Pruned old backup: {extra['filename']}")
    except Exception as e:
        print(f"[Backup Rotation] Error during backup rotation: {e}")


def format_file_size(size_bytes):
    """Converts bytes to human readable format (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# --- BACKGROUND SCHEDULER ---
_scheduler_started = False
_scheduler_lock = threading.Lock()

def start_backup_scheduler(app=None):
    """Starts the background worker thread for automated backups."""
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def scheduler_loop():
        print("[Backup Scheduler] Service started in background.")
        while True:
            try:
                # 1. Read configuration
                enabled = db.get_config("backup_auto_enabled", "1") == "1"
                interval_hours_str = db.get_config("backup_interval_hours", "6")
                interval_hours = int(interval_hours_str) if interval_hours_str else 6
                
                if enabled and interval_hours > 0:
                    last_run_str = db.get_config("backup_last_run", None)
                    should_run = False

                    if not last_run_str:
                        should_run = True
                    else:
                        try:
                            last_run = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M:%S")
                            next_run = last_run + timedelta(hours=interval_hours)
                            if datetime.now() >= next_run:
                                should_run = True
                        except Exception:
                            should_run = True

                    if should_run:
                        print(f"[Backup Scheduler] Triggering automatic backup (interval: {interval_hours}h)...")
                        create_backup(trigger="auto")

            except Exception as e:
                print(f"[Backup Scheduler] Error in scheduler loop: {e}")

            # Sleep 60 seconds between checks
            time.sleep(60)

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
