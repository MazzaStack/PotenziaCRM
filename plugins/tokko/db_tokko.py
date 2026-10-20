"""
Tokko DB - Funciones de base de datos específicas del plugin Tokko Broker.
Maneja las tablas tokko_propiedades y tokko_productores.
"""
import json
from datetime import datetime
from database import db


# ─────────────────────────────────────────────
# MIGRACIÓN / INICIALIZACIÓN DE TABLAS
# ─────────────────────────────────────────────

def init_tokko_tables():
    """Crea las tablas de Tokko si no existen (migración en caliente)."""
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tokko_propiedades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tokko_id TEXT UNIQUE NOT NULL,
                titulo TEXT,
                tipo_operacion TEXT,
                tipo_propiedad TEXT,
                precio REAL,
                moneda TEXT DEFAULT 'USD',
                superficie_total REAL DEFAULT 0,
                superficie_cubierta REAL DEFAULT 0,
                ambientes INTEGER DEFAULT 0,
                dormitorios INTEGER DEFAULT 0,
                banos INTEGER DEFAULT 0,
                cocheras INTEGER DEFAULT 0,
                barrio TEXT,
                localidad TEXT,
                zona TEXT,
                lat REAL DEFAULT 0,
                lon REAL DEFAULT 0,
                productor_nombre TEXT,
                productor_tokko_id TEXT,
                url_ficha TEXT,
                foto_principal TEXT,
                fotos_json TEXT,
                descripcion TEXT,
                activa INTEGER DEFAULT 1,
                ultima_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tokko_tipo_op ON tokko_propiedades(tipo_operacion);
            CREATE INDEX IF NOT EXISTS idx_tokko_tipo_prop ON tokko_propiedades(tipo_propiedad);
            CREATE INDEX IF NOT EXISTS idx_tokko_activa ON tokko_propiedades(activa);
            CREATE INDEX IF NOT EXISTS idx_tokko_productor ON tokko_propiedades(productor_nombre);

            CREATE TABLE IF NOT EXISTS tokko_productores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT UNIQUE NOT NULL,
                tokko_id TEXT,
                cantidad_propiedades INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tokko_comparables_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tokko_id TEXT UNIQUE NOT NULL,
                titulo TEXT,
                tipo_operacion TEXT,
                tipo_propiedad TEXT,
                precio REAL,
                moneda TEXT DEFAULT 'USD',
                superficie_total REAL DEFAULT 0,
                superficie_cubierta REAL DEFAULT 0,
                ambientes INTEGER DEFAULT 0,
                dormitorios INTEGER DEFAULT 0,
                banos INTEGER DEFAULT 0,
                cocheras INTEGER DEFAULT 0,
                barrio TEXT,
                localidad TEXT,
                zona TEXT,
                lat REAL DEFAULT 0,
                lon REAL DEFAULT 0,
                url_ficha TEXT,
                foto_principal TEXT,
                fotos_json TEXT,
                descripcion TEXT,
                estado_tokko TEXT DEFAULT 'activo', -- 'activo', 'reservado', 'vendido', 'alquilado', 'suspendido'
                fecha_publicacion TEXT, -- Date when it was published/updated in Tokko
                ultima_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tokko_comp_tipo_op ON tokko_comparables_cache(tipo_operacion);
            CREATE INDEX IF NOT EXISTS idx_tokko_comp_tipo_prop ON tokko_comparables_cache(tipo_propiedad);
            CREATE INDEX IF NOT EXISTS idx_tokko_comp_estado ON tokko_comparables_cache(estado_tokko);
        """)
        
        # Hot migrations for existing databases
        import sqlite3
        try:
            conn.execute("ALTER TABLE tokko_propiedades ADD COLUMN banos INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE tokko_propiedades ADD COLUMN cocheras INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
            
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────
# UPSERT DE PROPIEDADES
# ─────────────────────────────────────────────

def upsert_propiedad(prop: dict) -> str:
    """
    Inserta o actualiza una propiedad de Tokko.
    Devuelve 'inserted', 'updated' o 'skipped'.
    """
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        existing = conn.execute(
            "SELECT id FROM tokko_propiedades WHERE tokko_id = ?",
            (prop["tokko_id"],)
        ).fetchone()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if existing:
            conn.execute("""
                UPDATE tokko_propiedades SET
                    titulo = ?, tipo_operacion = ?, tipo_propiedad = ?,
                    precio = ?, moneda = ?, superficie_total = ?, superficie_cubierta = ?,
                    ambientes = ?, dormitorios = ?, banos = ?, cocheras = ?, barrio = ?, localidad = ?, zona = ?,
                    lat = ?, lon = ?, productor_nombre = ?, productor_tokko_id = ?,
                    url_ficha = ?, foto_principal = ?, fotos_json = ?, descripcion = ?,
                    activa = 1, ultima_sync = ?
                WHERE tokko_id = ?
            """, (
                prop.get("titulo"), prop.get("tipo_operacion"), prop.get("tipo_propiedad"),
                prop.get("precio"), prop.get("moneda"), prop.get("superficie_total"),
                prop.get("superficie_cubierta"), prop.get("ambientes"), prop.get("dormitorios"),
                prop.get("banos"), prop.get("cocheras"),
                prop.get("barrio"), prop.get("localidad"), prop.get("zona"),
                prop.get("lat"), prop.get("lon"), prop.get("productor_nombre"),
                prop.get("productor_tokko_id"), prop.get("url_ficha"),
                prop.get("foto_principal"), prop.get("fotos_json"), prop.get("descripcion"),
                now, prop["tokko_id"]
            ))
            conn.commit()
            return "updated"
        else:
            conn.execute("""
                INSERT INTO tokko_propiedades (
                    tokko_id, titulo, tipo_operacion, tipo_propiedad, precio, moneda,
                    superficie_total, superficie_cubierta, ambientes, dormitorios, banos, cocheras,
                    barrio, localidad, zona, lat, lon, productor_nombre, productor_tokko_id,
                    url_ficha, foto_principal, fotos_json, descripcion, activa, ultima_sync
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """, (
                prop["tokko_id"], prop.get("titulo"), prop.get("tipo_operacion"),
                prop.get("tipo_propiedad"), prop.get("precio"), prop.get("moneda"),
                prop.get("superficie_total"), prop.get("superficie_cubierta"),
                prop.get("ambientes"), prop.get("dormitorios"), prop.get("banos"), prop.get("cocheras"),
                prop.get("barrio"), prop.get("localidad"), prop.get("zona"),
                prop.get("lat"), prop.get("lon"), prop.get("productor_nombre"),
                prop.get("productor_tokko_id"), prop.get("url_ficha"),
                prop.get("foto_principal"), prop.get("fotos_json"), prop.get("descripcion"),
                now
            ))
            conn.commit()
            return "inserted"
    finally:
        conn.close()


def upsert_tokko_comparable(prop: dict) -> str:
    """
    Inserta o actualiza una propiedad en la cache de comparables de Tokko.
    Devuelve 'inserted' o 'updated'.
    """
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        existing = conn.execute(
            "SELECT id FROM tokko_comparables_cache WHERE tokko_id = ?",
            (prop["tokko_id"],)
        ).fetchone()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if existing:
            conn.execute("""
                UPDATE tokko_comparables_cache SET
                    titulo = ?, tipo_operacion = ?, tipo_propiedad = ?,
                    precio = ?, moneda = ?, superficie_total = ?, superficie_cubierta = ?,
                    ambientes = ?, dormitorios = ?, banos = ?, cocheras = ?,
                    barrio = ?, localidad = ?, zona = ?, lat = ?, lon = ?,
                    url_ficha = ?, foto_principal = ?, fotos_json = ?, descripcion = ?,
                    estado_tokko = ?, fecha_publicacion = ?, ultima_sync = ?
                WHERE tokko_id = ?
            """, (
                prop.get("titulo"), prop.get("tipo_operacion"), prop.get("tipo_propiedad"),
                prop.get("precio"), prop.get("moneda", "USD"), prop.get("superficie_total", 0),
                prop.get("superficie_cubierta", 0), prop.get("ambientes", 0), prop.get("dormitorios", 0),
                prop.get("banos", 0), prop.get("cocheras", 0), prop.get("barrio"), prop.get("localidad"),
                prop.get("zona"), prop.get("lat", 0), prop.get("lon", 0), prop.get("url_ficha"),
                prop.get("foto_principal"), prop.get("fotos_json"), prop.get("descripcion"),
                prop.get("estado_tokko", "activo"), prop.get("fecha_publicacion"), now,
                prop["tokko_id"]
            ))
            conn.commit()
            return "updated"
        else:
            conn.execute("""
                INSERT INTO tokko_comparables_cache (
                    tokko_id, titulo, tipo_operacion, tipo_propiedad, precio, moneda,
                    superficie_total, superficie_cubierta, ambientes, dormitorios, banos, cocheras,
                    barrio, localidad, zona, lat, lon, url_ficha, foto_principal, fotos_json,
                    descripcion, estado_tokko, fecha_publicacion, ultima_sync
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prop["tokko_id"], prop.get("titulo"), prop.get("tipo_operacion"),
                prop.get("tipo_propiedad"), prop.get("precio"), prop.get("moneda", "USD"),
                prop.get("superficie_total", 0), prop.get("superficie_cubierta", 0),
                prop.get("ambientes", 0), prop.get("dormitorios", 0), prop.get("banos", 0), prop.get("cocheras", 0),
                prop.get("barrio"), prop.get("localidad"), prop.get("zona"),
                prop.get("lat", 0), prop.get("lon", 0), prop.get("url_ficha"),
                prop.get("foto_principal"), prop.get("fotos_json"), prop.get("descripcion"),
                prop.get("estado_tokko", "activo"), prop.get("fecha_publicacion"), now
            ))
            conn.commit()
            return "inserted"
    finally:
        conn.close()


def mark_inactive_not_in(tokko_ids: list[str]) -> int:
    """Marca como inactivas todas las propiedades que no están en la lista."""
    if not tokko_ids:
        return 0
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        placeholders = ",".join(["?"] * len(tokko_ids))
        cursor = conn.execute(
            f"UPDATE tokko_propiedades SET activa = 0 WHERE tokko_id NOT IN ({placeholders}) AND activa = 1",
            tokko_ids
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def save_productores(producers: list[dict]):
    """Guarda/actualiza la lista de productores extraída del sync."""
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        for p in producers:
            conn.execute("""
                INSERT INTO tokko_productores (nombre, tokko_id, cantidad_propiedades)
                VALUES (?, ?, ?)
                ON CONFLICT(nombre) DO UPDATE SET
                    tokko_id = excluded.tokko_id,
                    cantidad_propiedades = excluded.cantidad_propiedades
            """, (p["nombre"], p.get("tokko_id", ""), p.get("cantidad", 0)))
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────
# QUERIES DE LECTURA
# ─────────────────────────────────────────────

def get_propiedades_cartera(tipo_operacion=None, tipo_propiedad=None,
                             precio_min=None, precio_max=None,
                             zona=None, page=1, per_page=12) -> tuple[list, int]:
    """Devuelve propiedades activas paginadas con filtros opcionales."""
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        conditions = ["activa = 1"]
        params = []

        if tipo_operacion:
            conditions.append("LOWER(tipo_operacion) LIKE ?")
            params.append(f"%{tipo_operacion.lower()}%")
        if tipo_propiedad:
            # Normalize single string into list if it's 'lote' or 'terreno' to merge them
            tp_list = []
            if isinstance(tipo_propiedad, list):
                tp_list = tipo_propiedad
            else:
                tp_list = [tipo_propiedad]

            # Enforce Lote/Terreno equivalence
            expanded_types = []
            for tp in tp_list:
                tp_lower = tp.lower()
                if tp_lower in ('lote', 'terreno'):
                    if 'lote' not in expanded_types: expanded_types.append('lote')
                    if 'terreno' not in expanded_types: expanded_types.append('terreno')
                else:
                    expanded_types.append(tp_lower)

            type_conds = []
            for tp in expanded_types:
                type_conds.append("LOWER(tipo_propiedad) LIKE ?")
                params.append(f"%{tp}%")
            conditions.append(f"({' OR '.join(type_conds)})")
        if precio_min:
            conditions.append("precio >= ?")
            params.append(float(precio_min))
        if precio_max:
            conditions.append("precio <= ?")
            params.append(float(precio_max))
        if zona:
            conditions.append("(LOWER(zona) LIKE ? OR LOWER(barrio) LIKE ? OR LOWER(localidad) LIKE ?)")
            z = f"%{zona.lower()}%"
            params.extend([z, z, z])

        where = " AND ".join(conditions)
        
        total = conn.execute(
            f"SELECT COUNT(*) FROM tokko_propiedades WHERE {where}", params
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""SELECT * FROM tokko_propiedades
                WHERE {where}
                ORDER BY precio DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset]
        ).fetchall()

        return [dict(r) for r in rows], total
    finally:
        conn.close()


def get_propiedades_by_productor(productor_nombre: str) -> list[dict]:
    """Devuelve propiedades activas del productor especificado."""
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT * FROM tokko_propiedades WHERE LOWER(productor_nombre) = LOWER(?) AND activa = 1 ORDER BY precio DESC",
            (productor_nombre,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_productores() -> list[dict]:
    """Devuelve todos los productores registrados."""
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT * FROM tokko_productores ORDER BY cantidad_propiedades DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_zonas_unicas() -> list[str]:
    """Devuelve lista de zonas/barrios únicos para autocomplete."""
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT DISTINCT barrio FROM tokko_propiedades WHERE activa = 1 AND barrio IS NOT NULL AND barrio != '' ORDER BY barrio"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def get_tokko_stats() -> dict:
    """Retorna estadísticas rápidas del catálogo."""
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        total = conn.execute("SELECT COUNT(*) FROM tokko_propiedades WHERE activa = 1").fetchone()[0]
        ventas = conn.execute(
            "SELECT COUNT(*) FROM tokko_propiedades WHERE activa = 1 AND LOWER(tipo_operacion) LIKE '%venta%'"
        ).fetchone()[0]
        alquileres = conn.execute(
            "SELECT COUNT(*) FROM tokko_propiedades WHERE activa = 1 AND LOWER(tipo_operacion) LIKE '%alquiler%'"
        ).fetchone()[0]
        return {"total": total, "ventas": ventas, "alquileres": alquileres}
    finally:
        conn.close()
