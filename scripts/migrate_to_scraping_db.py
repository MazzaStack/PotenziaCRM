"""
Script de Migración Masiva e Idempotente: CRM DB -> Scraping DB
Traslada todas las propiedades históricas a la nueva base de datos dedicada de scraping sin duplicados.
"""
import os
import sys
import json
import time
import argparse

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from database.db import get_db, load_db_config, MASTER_DB_PATH
from database.db_scraping import (
    init_scraping_db,
    get_scraping_db,
    insert_or_update_scraped_property,
    load_config as load_scraping_config
)

def run_migration(env=None, batch_size=200, progress_callback=None):
    """
    Ejecuta la migración de propiedades de forma segura y por lotes.
    Retorna un diccionario con las estadísticas del proceso.
    """
    print(f"=== INICIANDO MIGRACIÓN DE PROPIEDADES A SCRAPING DB (Entorno: {env or 'Default'}) ===")
    t_start = time.time()
    
    # Si se especificó env, asegurar que db.py use ese entorno para el origen
    import database.db as db_mod
    if env:
        db_mod.load_db_config()
        db_mod._pg_config['active_env'] = env
        if db_mod._pg_pool:
            try:
                db_mod._pg_pool.close()
            except Exception:
                pass
            db_mod._pg_pool = None

    # 1. Asegurar que scraping_db y sus tablas existan
    try:
        init_scraping_db(env)
    except Exception as e:
        print(f"[Migrador] Advertencia inicializando scraping_db: {e}")

    # 2. Conectar a la base de origen (CRM)
    conn_origin = db_mod.get_db()
    total_origin = 0
    try:
        row_cnt = conn_origin.execute("SELECT COUNT(*) as cnt FROM propiedades").fetchone()
        total_origin = row_cnt['cnt'] if row_cnt else 0
    except Exception as e:
        print(f"[Migrador] Error leyendo conteo de base de origen: {e}")
        return {'status': 'error', 'error': str(e)}

    print(f"[Migrador] Total de propiedades encontradas en CRM DB: {total_origin}")
    if total_origin == 0:
        conn_origin.close()
        return {'status': 'completed', 'total': 0, 'inserted': 0, 'updated': 0, 'errors': 0}

    # 3. Procesar por lotes
    offset = 0
    total_inserted = 0
    total_updated = 0
    total_errors = 0
    
    conn_dest = get_scraping_db(env)

    try:
        while offset < total_origin:
            rows = conn_origin.execute(f"""
                SELECT id, portal, url, titulo, precio, moneda, direccion, barrio, ciudad,
                       m2_total, m2_cubiertos, ambientes, dormitorios, banos, toilettes, cocheras,
                       antiguedad, orientacion, disposicion, estado_conservacion,
                       tipo_propiedad, tipo_operacion, nombre_contacto, telefono, email_contacto,
                       descripcion, foto_url, fotos_json, fecha_publicacion, fecha_captacion,
                       lat, lng
                FROM propiedades
                ORDER BY id ASC
                LIMIT {batch_size} OFFSET {offset}
            """).fetchall()

            if not rows:
                break

            for r in rows:
                r_dict = dict(r)
                try:
                    # Parsear fotos_json si venía como string
                    fotos = []
                    if r_dict.get('fotos_json'):
                        try:
                            fotos = json.loads(r_dict['fotos_json'])
                        except:
                            pass
                    if not fotos and r_dict.get('foto_url'):
                        fotos = [r_dict['foto_url']]
                    r_dict['fotos'] = fotos

                    # Mapear nombre_contacto a anunciante_nombre
                    if not r_dict.get('anunciante_nombre') and r_dict.get('nombre_contacto'):
                        r_dict['anunciante_nombre'] = r_dict['nombre_contacto']

                    prop_id, is_new = insert_or_update_scraped_property(r_dict, conn=conn_dest)
                    if prop_id is not None:
                        if is_new:
                            total_inserted += 1
                        else:
                            total_updated += 1
                    else:
                        total_errors += 1
                except Exception as ex_item:
                    total_errors += 1
                    print(f"  [Error fila {r_dict.get('id')}]: {ex_item}")

            offset += len(rows)
            pct = round((offset / total_origin) * 100, 1)
            print(f"[Migrador] Progreso: {offset}/{total_origin} ({pct}%) - Nuevas: {total_inserted} | Existentes/Actualizadas: {total_updated}")

            if progress_callback:
                progress_callback({
                    'total': total_origin,
                    'processed': offset,
                    'pct': pct,
                    'inserted': total_inserted,
                    'updated': total_updated,
                    'errors': total_errors
                })

    finally:
        conn_origin.close()
        conn_dest.close()

    elapsed = round(time.time() - t_start, 2)
    print("=" * 65)
    print(f"=== MIGRACIÓN FINALIZADA EN {elapsed}s ===")
    print(f"  • Total procesadas: {offset}")
    print(f"  • Nuevas insertadas: {total_inserted}")
    print(f"  • Existentes actualizadas (sin duplicar): {total_updated}")
    print(f"  • Errores omitidos: {total_errors}")
    print("=" * 65)

    return {
        'status': 'completed',
        'elapsed_seconds': elapsed,
        'total': total_origin,
        'processed': offset,
        'inserted': total_inserted,
        'updated': total_updated,
        'errors': total_errors
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Migrador masivo de propiedades a Scraping DB")
    parser.add_argument('--env', type=str, default=None, help="Entorno: 'development' o 'production'")
    parser.add_argument('--batch-size', type=int, default=200, help="Tamaño de lote (default: 200)")
    args = parser.parse_args()

    run_migration(env=args.env, batch_size=args.batch_size)
