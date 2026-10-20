"""
Database module for Growth Marketing Canvas.
Handles persistence, project management, and funnels for the SuperAdmin Growth Canvas.
"""
import json
import uuid
from datetime import datetime
from database.db import get_db, MASTER_DB_PATH

DEFAULT_CANVAS_DATA = {
    "targetAudience": "",
    "valueProposition": "",
    "oneMetricThatMatters": "",
    "awareness": [],
    "acquisition": [],
    "activation": [],
    "retention": [],
    "revenue": [],
    "referral": []
}

def check_and_add_growth_canvas_table(db_path=None):
    """Ensures growth_canvas_projects table exists and seeds default project if empty."""
    conn = None
    try:
        conn = get_db(db_path or MASTER_DB_PATH)
        create_sql = """
        CREATE TABLE IF NOT EXISTS growth_canvas_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            empresa TEXT,
            data TEXT NOT NULL,
            fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
            fecha_actualizacion TEXT DEFAULT (datetime('now', 'localtime'))
        );
        """
        conn.execute(create_sql)
        conn.commit()

        # Check if table is empty
        cursor = conn.execute("SELECT COUNT(*) FROM growth_canvas_projects")
        row = cursor.fetchone()
        count = row[0] if row else 0

        if count == 0:
            init_json = json.dumps(DEFAULT_CANVAS_DATA)
            conn.execute(
                "INSERT INTO growth_canvas_projects (nombre, empresa, data) VALUES (?, ?, ?)",
                ("Test", "ideas", init_json)
            )
            conn.commit()
            print("[Growth Canvas] Created default project 'Test' (ideas)")
    except Exception as e:
        print(f"[Growth Canvas] Error initializing table: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_growth_canvas_projects():
    """Returns a list of all growth canvas projects: id, nombre, empresa, fecha_actualizacion."""
    check_and_add_growth_canvas_table()
    conn = None
    try:
        conn = get_db()
        cursor = conn.execute(
            "SELECT id, nombre, empresa, fecha_creacion, fecha_actualizacion FROM growth_canvas_projects ORDER BY id ASC"
        )
        rows = cursor.fetchall()
        projects = []
        for r in rows:
            projects.append({
                "id": r[0] if not hasattr(r, '__getitem__') or isinstance(r, (list, tuple)) else r['id'],
                "nombre": r[1] if not hasattr(r, '__getitem__') or isinstance(r, (list, tuple)) else r['nombre'],
                "empresa": (r[2] if not hasattr(r, '__getitem__') or isinstance(r, (list, tuple)) else r['empresa']) or "",
                "fecha_creacion": str(r[3] if not hasattr(r, '__getitem__') or isinstance(r, (list, tuple)) else r['fecha_creacion']),
                "fecha_actualizacion": str(r[4] if not hasattr(r, '__getitem__') or isinstance(r, (list, tuple)) else r['fecha_actualizacion'])
            })
        return projects
    except Exception as e:
        print(f"[Growth Canvas] Error getting projects: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_growth_canvas_project(project_id):
    """Returns a specific project with its parsed data payload."""
    check_and_add_growth_canvas_table()
    conn = None
    try:
        conn = get_db()
        cursor = conn.execute(
            "SELECT id, nombre, empresa, data, fecha_creacion, fecha_actualizacion FROM growth_canvas_projects WHERE id = ?",
            (project_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        p_id = row[0] if not hasattr(row, '__getitem__') or isinstance(row, (list, tuple)) else row['id']
        p_nombre = row[1] if not hasattr(row, '__getitem__') or isinstance(row, (list, tuple)) else row['nombre']
        p_empresa = row[2] if not hasattr(row, '__getitem__') or isinstance(row, (list, tuple)) else row['empresa']
        raw_data = row[3] if not hasattr(row, '__getitem__') or isinstance(row, (list, tuple)) else row['data']
        p_creacion = row[4] if not hasattr(row, '__getitem__') or isinstance(row, (list, tuple)) else row['fecha_creacion']
        p_actualizacion = row[5] if not hasattr(row, '__getitem__') or isinstance(row, (list, tuple)) else row['fecha_actualizacion']

        parsed_data = {}
        if raw_data:
            try:
                parsed_data = json.loads(raw_data)
            except Exception:
                parsed_data = DEFAULT_CANVAS_DATA.copy()
        else:
            parsed_data = DEFAULT_CANVAS_DATA.copy()

        # Ensure all expected keys exist
        for k, v in DEFAULT_CANVAS_DATA.items():
            if k not in parsed_data:
                parsed_data[k] = type(v)()

        return {
            "id": p_id,
            "nombre": p_nombre,
            "empresa": p_empresa or "",
            "data": parsed_data,
            "fecha_creacion": str(p_creacion),
            "fecha_actualizacion": str(p_actualizacion)
        }
    except Exception as e:
        print(f"[Growth Canvas] Error getting project {project_id}: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def save_growth_canvas_project(project_id, nombre=None, empresa=None, data_dict=None):
    """Updates the project name, company and/or JSON data payload."""
    conn = None
    try:
        conn = get_db()
        current = get_growth_canvas_project(project_id)
        if not current:
            return False

        new_nombre = nombre if nombre is not None else current["nombre"]
        new_empresa = empresa if empresa is not None else current["empresa"]
        new_data = json.dumps(data_dict if data_dict is not None else current["data"], ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """
            UPDATE growth_canvas_projects 
            SET nombre = ?, empresa = ?, data = ?, fecha_actualizacion = ?
            WHERE id = ?
            """,
            (new_nombre, new_empresa, new_data, now_str, project_id)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"[Growth Canvas] Error saving project {project_id}: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def create_growth_canvas_project(nombre, empresa=""):
    """Creates a new project and returns its ID."""
    conn = None
    try:
        conn = get_db()
        init_json = json.dumps(DEFAULT_CANVAS_DATA, ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            """
            INSERT INTO growth_canvas_projects (nombre, empresa, data, fecha_creacion, fecha_actualizacion)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nombre or "Nuevo Canvas", empresa or "", init_json, now_str, now_str)
        )
        conn.commit()
        # Retrieve the new ID
        new_id = getattr(cursor, 'lastrowid', None)
        if not new_id:
            c2 = conn.execute("SELECT MAX(id) FROM growth_canvas_projects")
            r2 = c2.fetchone()
            new_id = r2[0] if r2 else None
        return new_id
    except Exception as e:
        print(f"[Growth Canvas] Error creating project: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def delete_growth_canvas_project(project_id):
    """Deletes a project by ID."""
    conn = None
    try:
        conn = get_db()
        conn.execute("DELETE FROM growth_canvas_projects WHERE id = ?", (project_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"[Growth Canvas] Error deleting project {project_id}: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
