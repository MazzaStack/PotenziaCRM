import os
import re
import json
import pandas as pd
from flask import Blueprint, request, render_template, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from database import db
from datetime import datetime, timedelta

lotes_excel_bp = Blueprint('lotes_excel', __name__)

def get_lotes_db_conn():
    """Returns a connection to the database. We use MASTER_DB_PATH to share lots across agents."""
    return db.get_db(db.MASTER_DB_PATH)

def get_agent_config_for_user(username, clave, default=None):
    """Retrieves custom agent/branding configurations from DB based on username, supporting PG and isolated SQLite databases."""
    if not username:
        return default
    from database.db_auth import get_usuario
    user = get_usuario(username)
    if not user:
        return default
        
    db_type = db._pg_config.get("db_type", "sqlite")
    # Execute a lightweight dummy call to get_db to initialize fallback if PG is down
    try:
        conn_test = db.get_db()
        conn_test.close()
    except:
        pass
        
    use_sqlite = (db_type == "sqlite" or db.SQLITE_FALLBACK_ACTIVE)
    if use_sqlite:
        import sqlite3
        db_file = user.get('db_file')
        user_db_path = db.get_user_db_path(db_file)
        if os.path.exists(user_db_path):
            try:
                conn = sqlite3.connect(user_db_path)
                conn.row_factory = sqlite3.Row
                # 1. Try bare key
                row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
                if row and row['valor']:
                    val = row['valor']
                    conn.close()
                    return val
                # 2. Try scoped key as fallback
                scoped_key = f"{clave}_{user['id']}"
                row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (scoped_key,)).fetchone()
                if row and row['valor']:
                    val = row['valor']
                    conn.close()
                    return val
                conn.close()
            except Exception:
                pass
    else:
        # PostgreSQL
        user_id = user['id']
        scoped_key = f"{clave}_{user_id}"
        conn = db.get_db(db.MASTER_DB_PATH)
        try:
            row = conn.execute("SELECT valor FROM configuracion WHERE clave = ?", (scoped_key,)).fetchone()
            if row and row['valor']:
                val = row['valor']
                conn.close()
                return val
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except:
                pass
                
    # Final fallback to standard config lookup
    return db.get_config(clave) or default

LISTA_TIPOLOGIAS = [
    'Al Golf',
    'Amarra',
    'Bosque',
    'Espacio Verde',
    'Interno',
    'Laguna',
    'Lindero Interno',
    'Perimetral',
    'Rio'
]

LISTA_ORIENTACIONES = [
    'N',
    'S',
    'E',
    'O',
    'NO',
    'NE',
    'SO',
    'SE'
]

def clean_lote_field(val, field_name=None):
    """Normalizes known typographic, encoding issues and unifies names for real estate lotes."""
    if not val:
        return val
    val = re.sub(r'\s+', ' ', str(val)).strip()
    
    # Common UTF-8 / latin-1 decoding fixes
    replacements = {
        'BelA©n': 'Belén',
        'BelA(c)n': 'Belén',
        'CantÃ³n': 'Cantón',
        'CantÃ³': 'Cantón',
        'CantÃ': 'Cantón',
        'Cantan': 'Cantón',
        'Cantán': 'Cantón',
        'SebastiÃ¡n': 'San Sebastián',
        'SebastiÃ': 'San Sebastián',
        'Sebastián': 'San Sebastián',
        'Sebastian': 'San Sebastián',
        'RÃ³': 'Rio',
        'RÃo': 'Rio',
        'Río': 'Rio',
        'RÃO': 'Rio',
        'RÃƒO': 'Rio',
        'RAO': 'Rio',
        'RÃƒo': 'Rio',
        'RÃ£o': 'Rio',
        'Rao': 'Rio',
    }
    for bad, good in replacements.items():
        if bad in val:
            val = val.replace(bad, good)
            
    # Clean double prefixes / extra spaces
    if 'San San Sebastián' in val:
        val = val.replace('San San Sebastián', 'San Sebastián')

    # Known canonical mappings (case & accent insensitive)
    CANONICAL_NAMES = {
        'belen': 'Belén',
        'belen de escobar': 'Belén de Escobar',
        'ing maschwitz': 'Ing. Maschwitz',
        'ing. maschwitz': 'Ing. Maschwitz',
        'maschwitz': 'Ing. Maschwitz',
        'san sebastian': 'San Sebastián',
        'san sebastián': 'San Sebastián',
        'canton': 'Cantón',
        'el canton': 'Cantón',
        'el cantón': 'Cantón',
        'san matias': 'San Matías',
        'san matías': 'San Matías',
        'puertos del lago': 'Puertos del Lago',
        'puertos': 'Puertos del Lago',
        'el cazador': 'El Cazador',
        'el cazal': 'El Cazal',
        'el cardal': 'El Cardal',
        'campo cardales': 'Campo Cardales',
        'santa isabel': 'Santa Isabel',
        'santa ana': 'Santa Ana',
        'el naudir': 'El Naudir',
        'naudir': 'Naudir',
        'zelaya': 'Zelaya',
        'villanueva': 'Villanueva',
        'nordelta': 'Nordelta',
        'pilar': 'Pilar',
        'escobar': 'Escobar',
        'tigre': 'Tigre',
        'campana': 'Campana',
        'cardales': 'Cardales'
    }

    # Normalize location names (partido, localidad, barrio)
    if field_name in ('partido', 'localidad', 'barrio'):
        val_clean = val.lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
        if val.lower() in CANONICAL_NAMES:
            val = CANONICAL_NAMES[val.lower()]
        elif val_clean in CANONICAL_NAMES:
            val = CANONICAL_NAMES[val_clean]
        else:
            # Smart Title Case respecting Spanish prepositions / articles
            LOWER_WORDS = {'de', 'del', 'y', 'en', 'al'}
            words = val.split(' ')
            result = []
            for i, w in enumerate(words):
                lw = w.lower()
                if i > 0 and lw in LOWER_WORDS:
                    result.append(lw)
                elif lw.startswith('ing.') or lw == 'ing':
                    result.append('Ing.')
                elif lw.startswith('dr.') or lw == 'dr':
                    result.append('Dr.')
                elif lw.startswith('sta.') or lw == 'sta':
                    result.append('Santa')
                elif lw.startswith('sto.') or lw == 'sto':
                    result.append('Santo')
                elif lw.startswith('b°') or lw == 'bº':
                    result.append('B°')
                else:
                    result.append(w.capitalize())
            val = ' '.join(result)
            
    # Tipología fixed canonical normalizer
    if field_name == 'tipologia':
        val_clean = val.lower().strip()
        tip_map = {
            'al golf': 'Al Golf',
            'golf': 'Al Golf',
            'amarra': 'Amarra',
            'amarras': 'Amarra',
            'bosque': 'Bosque',
            'espacio verde': 'Espacio Verde',
            'espacio_verde': 'Espacio Verde',
            'espacios verdes': 'Espacio Verde',
            'verde': 'Espacio Verde',
            'interno': 'Interno',
            'laguna': 'Laguna',
            'lindero interno': 'Lindero Interno',
            'lindero': 'Lindero Interno',
            'perim interno': 'Lindero Interno',
            'perímetro interno': 'Lindero Interno',
            'perimetro interno': 'Lindero Interno',
            'perim. interno': 'Lindero Interno',
            'perim_interno': 'Lindero Interno',
            'perimetral': 'Perimetral',
            'rio': 'Rio',
            'río': 'Rio',
            'rão': 'Rio',
            'rao': 'Rio'
        }
        if val_clean in tip_map:
            return tip_map[val_clean]
        for canon in LISTA_TIPOLOGIAS:
            if val_clean == canon.lower():
                return canon
        return val

    # Orientación fixed canonical normalizer
    if field_name == 'orientacion':
        val_upper = val.upper().strip()
        ori_map = {
            'N': 'N', 'NORTE': 'N',
            'S': 'S', 'SUR': 'S',
            'E': 'E', 'ESTE': 'E',
            'O': 'O', 'OESTE': 'O', 'W': 'O', 'WEST': 'O',
            'NO': 'NO', 'NOROESTE': 'NO', 'NW': 'NO',
            'NE': 'NE', 'NORESTE': 'NE',
            'SO': 'SO', 'SUDOESTE': 'SO', 'SUROESTE': 'SO', 'SW': 'SO',
            'SE': 'SE', 'SUDESTE': 'SE', 'SURESTE': 'SE'
        }
        if val_upper in ori_map:
            return ori_map[val_upper]
        return val
            
    return val

def run_db_lotes_encoding_cleanup():
    """Runs on database startup and view load to clean up all records and ensure full uniformity across database."""
    conn = get_lotes_db_conn()
    try:
        # 1. Full sweep normalization on all existing rows in lotes table
        rows = conn.execute("SELECT id, partido, localidad, barrio, tipologia, orientacion FROM lotes").fetchall()
        for r in rows:
            r_id, partido, localidad, barrio, tipologia, orientacion = r[0], r[1], r[2], r[3], r[4], r[5]
            new_p = clean_lote_field(partido, 'partido')
            new_l = clean_lote_field(localidad, 'localidad')
            new_b = clean_lote_field(barrio, 'barrio')
            new_t = clean_lote_field(tipologia, 'tipologia') if tipologia else tipologia
            new_o = clean_lote_field(orientacion, 'orientacion') if orientacion else orientacion
            if (new_p != partido or new_l != localidad or new_b != barrio or new_t != tipologia or new_o != orientacion):
                conn.execute("""
                    UPDATE lotes SET partido=?, localidad=?, barrio=?, tipologia=?, orientacion=? WHERE id=?
                """, (new_p, new_l, new_b, new_t, new_o, r_id))

        # 2. Normalize overrides in lotes_detalles_manuales
        try:
            ov_rows = conn.execute("SELECT clave_natural, tipologia_override, orientacion_override FROM lotes_detalles_manuales").fetchall()
            for r in ov_rows:
                key, tip, ori = r[0], r[1], r[2]
                new_tip = clean_lote_field(tip, 'tipologia') if tip else tip
                new_ori = clean_lote_field(ori, 'orientacion') if ori else ori
                if (new_tip != tip or new_ori != ori):
                    conn.execute("UPDATE lotes_detalles_manuales SET tipologia_override=?, orientacion_override=? WHERE clave_natural=?", (new_tip, new_ori, key))
        except Exception:
            pass
            
        # 3. Explicit byte-by-byte fix for Latin1/UTF-8 corrupted characters
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, tipologia FROM lotes")
            for row in cursor.fetchall():
                row_id, val = row[0], row[1]
                if val:
                    char_codes = [ord(c) for c in val]
                    if char_codes == [82, 195, 173, 111] or 'R\xad' in val or '\xc3' in val or 'RÃ' in val or 'RÃO' in val or 'RÃo' in val:
                        conn.execute("UPDATE lotes SET tipologia = 'Rio' WHERE id = ?", (row_id,))
        except Exception as ex:
            print(f"[Lotes Clean] Byte cleanup error: {ex}")
            
        # 4. Fix empty or missing dateadd values so days_in_market calculation works
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("UPDATE lotes SET dateadd = ? WHERE dateadd IS NULL OR dateadd = '' OR dateadd = 'nan'", (now_str,))
        
        conn.commit()
    except Exception as e:
        print(f"[Lotes Clean] Error running db lotes cleanup: {e}")
    finally:
        conn.close()

def init_lotes_table():
    """Initializes the lotes and override tables, ensuring multi-tenant office columns exist."""
    conn = get_lotes_db_conn()
    try:
        # Create primary table with is_manual column
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partido TEXT,
                localidad TEXT,
                barrio TEXT,
                area TEXT,
                numero TEXT,
                tipologia TEXT,
                orientacion TEXT,
                metros TEXT,
                valor REAL,
                cuotas INTEGER,
                colega INTEGER,
                usuario TEXT,
                estado INTEGER,
                dateadd TEXT,
                is_manual INTEGER DEFAULT 0,
                link_plano TEXT,
                oficina_id INTEGER
            )
        """)
        
        # Add new columns to lotes if they do not exist
        for col in ('is_manual', 'link_plano', 'link_plano2', 'nombre_colega', 'observaciones', 'oficina_id'):
            try:
                conn.execute(f"ALTER TABLE lotes ADD COLUMN {col} TEXT" if col != 'oficina_id' else f"ALTER TABLE lotes ADD COLUMN {col} INTEGER")
            except Exception:
                pass
                
        # Set default for is_manual if newly created
        try:
            conn.execute("UPDATE lotes SET is_manual = 0 WHERE is_manual IS NULL")
        except:
            pass
            
        # Backfill existing lotes with default oficina_id = 1 if unassigned
        try:
            conn.execute("UPDATE lotes SET oficina_id = 1 WHERE oficina_id IS NULL")
        except:
            pass
            
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lotes_detalles_manuales (
                clave_natural TEXT PRIMARY KEY,
                detalles_financiacion TEXT,
                valor_override REAL,
                estado_override INTEGER,
                tipologia_override TEXT,
                orientacion_override TEXT,
                metros_override TEXT,
                area_override TEXT,
                usuario_override TEXT,
                colega_override INTEGER,
                cuotas_override INTEGER,
                link_plano_override TEXT,
                oficina_id INTEGER
            )
        """)
        
        # Add new columns to lotes_detalles_manuales if they do not exist
        for col in ('link_plano_override', 'link_plano2_override', 'nombre_colega_override', 'observaciones_override', 'oficina_id'):
            try:
                conn.execute(f"ALTER TABLE lotes_detalles_manuales ADD COLUMN {col} TEXT" if col != 'oficina_id' else f"ALTER TABLE lotes_detalles_manuales ADD COLUMN {col} INTEGER")
            except Exception:
                pass
                
        # Backfill existing overrides with default oficina_id = 1 if unassigned
        try:
            conn.execute("UPDATE lotes_detalles_manuales SET oficina_id = 1 WHERE oficina_id IS NULL")
        except:
            pass
                
        conn.commit()
        
        # Run encoding and typo cleanup on DB startup/table initialization
        run_db_lotes_encoding_cleanup()
    except Exception as e:
        print(f"Error creating/altering tables: {e}")
    finally:
        conn.close()

# Initialize tables
init_lotes_table()

from modules.auth import privilege_required

@lotes_excel_bp.route('/lotes', methods=['GET'])
@login_required
@privilege_required('menu_item', 'lotes_excel')
def lotes():
    """Visor principal y filtros interactivos de lotes, con aislamiento total por oficina."""
    is_solo_agent = not bool(getattr(current_user, 'oficina_id', None)) and current_user.usuario != 'GermanMazza'
    
    if is_solo_agent:
        return render_template('lotes_excel.html',
                               lotes=[],
                               total_count=0,
                               avg_price=0,
                               page=1,
                               total_pages=1,
                               partidos=[],
                               localidades=[],
                               barrios=[],
                               tipologias=[],
                               orientaciones=[],
                               usuarios=[],
                               usuarios_options=[],
                               search='',
                               partido_f='',
                               localidad_f='',
                               barrio_f='',
                               tipologia_f='',
                               orientacion_f='',
                               cuotas_f='',
                               colega_f='',
                               usuario_f='',
                               origen_f='',
                               estado_f='',
                               dias_mercado='',
                               min_valor='',
                               max_valor='',
                               min_metros='',
                               max_metros='',
                               sort_col='',
                               sort_order='asc',
                               orphan_count=0,
                               is_solo_agent=True)

    init_lotes_table()
    
    # Get parameters
    search = request.args.get('search', '').strip()
    partido_f = request.args.get('partido', '')
    localidad_f = request.args.get('localidad', '')
    barrio_f = request.args.get('barrio', '')
    tipologia_f = request.args.get('tipologia', '')
    orientacion_f = request.args.get('orientacion', '')
    cuotas_f = request.args.get('cuotas', '')
    colega_f = request.args.get('colega', '')
    usuario_f = request.args.get('usuario', '')
    origen_f = request.args.get('origen', '')
    estado_f = request.args.get('estado', '')
    dias_mercado = request.args.get('dias_mercado', '')
    
    min_valor = request.args.get('min_valor', '')
    max_valor = request.args.get('max_valor', '')
    min_metros = request.args.get('min_metros', '')
    max_metros = request.args.get('max_metros', '')

    # Pagination parameters
    try:
        page = int(request.args.get('page', 1))
        if page < 1: page = 1
    except:
        page = 1
        
    limit = 500
    offset = (page - 1) * limit

    conn = get_lotes_db_conn()
    try:
        # Multi-tenant office isolation
        target_oficina_id = getattr(current_user, 'oficina_id', None) or 1
        office_sql = " AND (l.oficina_id = ? OR (l.oficina_id IS NULL AND 1 = ?))"
        office_params = [target_oficina_id, target_oficina_id]

        # Fetch distinct values based on merged overrides within user's office
        partidos = [r[0] for r in conn.execute(f"SELECT DISTINCT l.partido FROM lotes l WHERE l.partido != '' AND l.partido IS NOT NULL AND l.eliminado_el IS NULL {office_sql} ORDER BY l.partido", office_params).fetchall()]
        localidades = [r[0] for r in conn.execute(f"SELECT DISTINCT l.localidad FROM lotes l WHERE l.localidad != '' AND l.localidad IS NOT NULL AND l.eliminado_el IS NULL {office_sql} ORDER BY l.localidad", office_params).fetchall()]
        barrios = [r[0] for r in conn.execute(f"SELECT DISTINCT l.barrio FROM lotes l WHERE l.barrio != '' AND l.barrio IS NOT NULL AND l.eliminado_el IS NULL {office_sql} ORDER BY l.barrio", office_params).fetchall()]
        
        # Fixed canonical tipologias and orientaciones
        tipologias = LISTA_TIPOLOGIAS
        orientaciones = LISTA_ORIENTACIONES
        
        # Fetch active users strictly belonging to this office (never solo agents or other offices)
        raw_users = db.get_all_usuarios(oficina_id=target_oficina_id)
        usuarios_options = [u for u in raw_users if u.get('oficina_id') == target_oficina_id]

        usuarios = sorted(list(set(
            [u['usuario'] for u in usuarios_options if u.get('usuario')]
        )))

        # Build SQL condition string
        filter_sql = office_sql + " AND l.eliminado_el IS NULL "
        params = list(office_params)

        if search:
            filter_sql += " AND (l.barrio LIKE ? OR l.localidad LIKE ? OR l.partido LIKE ? OR COALESCE(m.area_override, l.area) LIKE ? OR l.numero LIKE ?)"
            lk = f"%{search}%"
            params.extend([lk, lk, lk, lk, lk])
            
        if partido_f:
            filter_sql += " AND l.partido = ?"
            params.append(partido_f)
        if localidad_f:
            filter_sql += " AND l.localidad = ?"
            params.append(localidad_f)
        if barrio_f:
            filter_sql += " AND l.barrio = ?"
            params.append(barrio_f)
        if tipologia_f:
            filter_sql += " AND COALESCE(m.tipologia_override, l.tipologia) = ?"
            params.append(tipologia_f)
        if orientacion_f:
            filter_sql += " AND COALESCE(m.orientacion_override, l.orientacion) = ?"
            params.append(orientacion_f)
        if cuotas_f:
            filter_sql += " AND COALESCE(m.cuotas_override, l.cuotas) = ?"
            params.append(int(cuotas_f))
        if colega_f:
            filter_sql += " AND COALESCE(m.colega_override, l.colega) = ?"
            params.append(int(colega_f))
        if usuario_f:
            filter_sql += " AND COALESCE(m.usuario_override, l.usuario) = ?"
            params.append(usuario_f)
        if estado_f:
            filter_sql += " AND COALESCE(m.estado_override, l.estado) = ?"
            params.append(int(estado_f))
            
        if dias_mercado:
            now_dt = datetime.now()
            if dias_mercado == '30_plus':
                threshold = (now_dt - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                filter_sql += " AND l.dateadd <= ?"
                params.append(threshold)
            elif dias_mercado == '60_plus':
                threshold = (now_dt - timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S')
                filter_sql += " AND l.dateadd <= ?"
                params.append(threshold)
            elif dias_mercado == 'under_30':
                threshold = (now_dt - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
                filter_sql += " AND l.dateadd > ?"
                params.append(threshold)
            elif dias_mercado == 'under_60':
                threshold = (now_dt - timedelta(days=60)).strftime('%Y-%m-%d %H:%M:%S')
                filter_sql += " AND l.dateadd > ?"
                params.append(threshold)
            
        if origen_f == 'manual':
            filter_sql += " AND l.is_manual = 1"
        elif origen_f == 'excel':
            filter_sql += " AND l.is_manual = 0"
            
        if min_valor:
            filter_sql += " AND COALESCE(m.valor_override, l.valor) >= ?"
            params.append(float(min_valor))
        if max_valor:
            filter_sql += " AND COALESCE(m.valor_override, l.valor) <= ?"
            params.append(float(max_valor))
            
        if min_metros:
            filter_sql += " AND CAST(COALESCE(m.metros_override, l.metros) AS REAL) >= ?"
            params.append(float(min_metros))
        if max_metros:
            filter_sql += " AND CAST(COALESCE(m.metros_override, l.metros) AS REAL) <= ?"
            params.append(float(max_metros))

        # 1. Total matching count for pagination calculations
        count_query = """
            SELECT COUNT(*) 
            FROM lotes l
            LEFT JOIN lotes_detalles_manuales m 
              ON (l.partido || '|' || l.localidad || '|' || l.barrio || '|' || l.numero) = m.clave_natural
            WHERE 1=1
        """ + filter_sql
        total_count = conn.execute(count_query, params).fetchone()[0]

        # 2. Avg price calculations
        avg_query = """
            SELECT COALESCE(AVG(COALESCE(m.valor_override, l.valor)), 0)
            FROM lotes l
            LEFT JOIN lotes_detalles_manuales m 
              ON (l.partido || '|' || l.localidad || '|' || l.barrio || '|' || l.numero) = m.clave_natural
            WHERE 1=1
        """ + filter_sql
        avg_price = conn.execute(avg_query, params).fetchone()[0]

        sort_col = request.args.get('sort', '').strip()
        sort_order = request.args.get('order', 'asc').strip().lower()
        if sort_order not in ('asc', 'desc'):
            sort_order = 'asc'

        # Map frontend sortable keys to SQL expressions
        # (coalescing overrides to sort correctly by current actual values shown in the table)
        sort_map = {
            'partido': 'l.partido',
            'localidad': 'l.localidad',
            'barrio': 'l.barrio',
            'numero': 'CAST(l.numero AS INTEGER)',
            'tipologia': 'COALESCE(m.tipologia_override, l.tipologia)',
            'orientacion': 'COALESCE(m.orientacion_override, l.orientacion)',
            'metros': 'CAST(COALESCE(m.metros_override, l.metros) AS REAL)',
            'antiguedad': 'l.dateadd',
            'valor': 'COALESCE(m.valor_override, l.valor)',
            'usuario': 'COALESCE(m.usuario_override, l.usuario)',
            'estado': 'COALESCE(m.estado_override, l.estado)'
        }

        order_sql = "ORDER BY l.id DESC"
        if sort_col in sort_map:
            order_sql = f"ORDER BY {sort_map[sort_col]} {sort_order.upper()}, l.id DESC"

        # 3. Paginated rows query
        query = """
            SELECT l.*, 
                   m.detalles_financiacion,
                   m.valor_override,
                   m.estado_override,
                   m.tipologia_override,
                   m.orientacion_override,
                   m.metros_override,
                   m.area_override,
                   m.usuario_override,
                   m.colega_override,
                   m.cuotas_override,
                   m.link_plano_override,
                   m.link_plano2_override,
                   m.nombre_colega_override,
                   m.observaciones_override
            FROM lotes l
            LEFT JOIN lotes_detalles_manuales m 
              ON (l.partido || '|' || l.localidad || '|' || l.barrio || '|' || l.numero) = m.clave_natural
            WHERE 1=1
        """ + filter_sql + f" {order_sql} LIMIT ? OFFSET ?"
        
        rows = conn.execute(query, params + [limit, offset]).fetchall()
        
        # Merge Overrides into list
        lotes_list = []
        for r in rows:
            ld = dict(r)
            if ld['valor_override'] is not None: ld['valor'] = ld['valor_override']
            if ld['estado_override'] is not None: ld['estado'] = ld['estado_override']
            if ld['tipologia_override'] is not None: ld['tipologia'] = ld['tipologia_override']
            if ld['orientacion_override'] is not None: ld['orientacion'] = ld['orientacion_override']
            if ld['metros_override'] is not None: ld['metros'] = ld['metros_override']
            if ld['area_override'] is not None: ld['area'] = ld['area_override']
            if ld['usuario_override'] is not None: ld['usuario'] = ld['usuario_override']
            if ld['colega_override'] is not None: ld['colega'] = ld['colega_override']
            if ld['cuotas_override'] is not None: ld['cuotas'] = ld['cuotas_override']
            if ld.get('link_plano_override') is not None: ld['link_plano'] = ld['link_plano_override']
            if ld.get('link_plano2_override') is not None: ld['link_plano2'] = ld['link_plano2_override']
            if ld.get('nombre_colega_override') is not None: ld['nombre_colega'] = ld['nombre_colega_override']
            if ld.get('observaciones_override') is not None: ld['observaciones'] = ld['observaciones_override']
            
            # Calculate days in market based on dateadd
            days_in_market = 0
            if ld.get('dateadd'):
                try:
                    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y'):
                        try:
                            dt = datetime.strptime(ld['dateadd'], fmt)
                            days_in_market = (datetime.now() - dt).days
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass
            ld['days_in_market'] = max(0, days_in_market)
            lotes_list.append(ld)
            
        # Count orphans (for admin/broker information within office)
        orphan_count = 0
        if current_user.rol in ('admin', 'broker'):
            active_keys = [f"{ld['partido']}|{ld['localidad']}|{ld['barrio']}|{ld['numero']}" for ld in lotes_list]
            if current_user.usuario == 'GermanMazza':
                override_keys = [row[0] for row in conn.execute("SELECT clave_natural FROM lotes_detalles_manuales").fetchall()]
            else:
                override_keys = [row[0] for row in conn.execute("SELECT clave_natural FROM lotes_detalles_manuales WHERE oficina_id = ? OR (oficina_id IS NULL AND 1 = ?)", [current_user.oficina_id, current_user.oficina_id]).fetchall()]
            orphan_count = len([k for k in override_keys if k not in active_keys])

        total_pages = (total_count + limit - 1) // limit

    finally:
        conn.close()

    return render_template('lotes_excel.html',
                           lotes=lotes_list,
                           total_count=total_count,
                           avg_price=avg_price,
                           page=page,
                           total_pages=total_pages,
                           partidos=partidos,
                           localidades=localidades,
                           barrios=barrios,
                           tipologias=tipologias,
                           orientaciones=orientaciones,
                           usuarios=usuarios,
                           usuarios_options=usuarios_options,
                           search=search,
                           partido_f=partido_f,
                           localidad_f=localidad_f,
                           barrio_f=barrio_f,
                           tipologia_f=tipologia_f,
                           orientacion_f=orientacion_f,
                           cuotas_f=cuotas_f,
                           colega_f=colega_f,
                           usuario_f=usuario_f,
                           origen_f=origen_f,
                           estado_f=estado_f,
                           dias_mercado=dias_mercado,
                           min_valor=min_valor,
                           max_valor=max_valor,
                           min_metros=min_metros,
                           max_metros=max_metros,
                           sort_col=sort_col,
                           sort_order=sort_order,
                           orphan_count=orphan_count,
                           is_solo_agent=False)

@lotes_excel_bp.route('/lotes/delete/<int:lote_id>', methods=['POST'])
@login_required
def delete_lote(lote_id):
    """Lot deletion route (Admins, Brokers of the same office, or the owner agent)."""
    conn = get_lotes_db_conn()
    try:
        # Fetch lot details to get key for override deletion
        lote = conn.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
        if not lote:
            flash("Lote no encontrado.", "danger")
            return redirect(url_for('lotes_excel.lotes'))
            
        lote = dict(lote)
        
        # Check permissions: GermanMazza can delete all.
        # Admins and Brokers can delete any lot belonging to their office.
        # Agents can only delete their own managed lot within their office.
        lote_user = (lote.get('usuario') or '').strip().lower()
        curr_user = (current_user.usuario or '').strip().lower()
        lote_office = lote.get('oficina_id') or 1
        user_office = getattr(current_user, 'oficina_id', None) or 1
        
        has_perm = False
        if current_user.usuario == 'GermanMazza':
            has_perm = True
        elif current_user.rol in ('admin', 'broker'):
            if lote_office == user_office:
                has_perm = True
        elif current_user.rol == 'agente':
            if lote_office == user_office and lote_user == curr_user:
                has_perm = True

        if not has_perm:
            flash("Permiso denegado. Solo podés borrar lotes correspondientes a tu oficina y tus permisos.", "danger")
            return redirect(url_for('lotes_excel.lotes'))
            
        from database.db_papelera import soft_delete_record
        soft_delete_record('lotes', lote_id, deleted_by=current_user.nombre_display or current_user.usuario)
        
        flash(f"Lote #{lote['numero']} enviado a la Papelera de Reciclaje.", "info")
    except Exception as e:
        flash(f"Error al eliminar lote: {e}", "danger")
    finally:
        conn.close()
        
    return redirect(url_for('lotes_excel.lotes'))

@lotes_excel_bp.route('/lotes/add', methods=['POST'])
@login_required
def add_lote():
    """Manually add a new lot assigned to current user's office."""
    target_oficina_id = getattr(current_user, 'oficina_id', None) or 1

    partido = clean_lote_field(request.form.get('partido', ''), 'partido')
    localidad = clean_lote_field(request.form.get('localidad', ''), 'localidad')
    barrio = clean_lote_field(request.form.get('barrio', ''), 'barrio')
    area = request.form.get('area', '').strip()
    numero = request.form.get('numero', '').strip()
    tipologia = clean_lote_field(request.form.get('tipologia', ''), 'tipologia')
    orientacion = request.form.get('orientacion', '').strip()
    metros = request.form.get('metros', '').strip()
    usuario = request.form.get('usuario', '').strip() or current_user.usuario
    link_plano = request.form.get('link_plano', '').strip()
    link_plano2 = request.form.get('link_plano2', '').strip()
    nombre_colega = request.form.get('nombre_colega', '').strip()
    observaciones = request.form.get('observaciones', '').strip()
    
    try:
        valor = float(request.form.get('valor', 0))
    except:
        valor = 0.0
        
    try:
        cuotas = int(request.form.get('cuotas', 1))
    except:
        cuotas = 1
        
    try:
        colega = int(request.form.get('colega', 0))
    except:
        colega = 0
        
    try:
        estado = int(request.form.get('estado', 1))
    except:
        estado = 1

    detalles_financiacion = request.form.get('detalles_financiacion', '').strip()

    if not partido or not localidad or not barrio or not numero:
        flash("Partido, Localidad, Barrio y Número son campos obligatorios.", "danger")
        return redirect(url_for('lotes_excel.lotes'))

    conn = get_lotes_db_conn()
    try:
        # Check if already exists in active lotes in this office
        dup = conn.execute("SELECT id FROM lotes WHERE partido=? AND localidad=? AND barrio=? AND numero=? AND (oficina_id=? OR (oficina_id IS NULL AND 1=?))", (partido, localidad, barrio, numero, target_oficina_id, target_oficina_id)).fetchone()
        if dup:
            flash(f"El lote #{numero} en {barrio} ({localidad}) ya existe en esta oficina. Usá la opción de editar en su lugar.", "warning")
            return redirect(url_for('lotes_excel.lotes'))

        # Insert manual lot with oficina_id
        import datetime
        dateadd = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        conn.execute("""
            INSERT INTO lotes (partido, localidad, barrio, area, numero, tipologia, orientacion, metros, valor, cuotas, colega, usuario, estado, dateadd, is_manual, link_plano, link_plano2, nombre_colega, observaciones, oficina_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        """, (partido, localidad, barrio, area, numero, tipologia, orientacion, metros, valor, cuotas, colega, usuario, estado, dateadd, link_plano, link_plano2, nombre_colega, observaciones, target_oficina_id))
        
        # Save overrides if manual changes are provided
        clave_natural = f"{partido}|{localidad}|{barrio}|{numero}"
        conn.execute("""
            INSERT OR REPLACE INTO lotes_detalles_manuales (
                clave_natural, detalles_financiacion, valor_override, estado_override,
                tipologia_override, orientacion_override, metros_override, area_override,
                usuario_override, colega_override, cuotas_override, link_plano_override,
                link_plano2_override, nombre_colega_override, observaciones_override, oficina_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (clave_natural, detalles_financiacion, valor, estado, tipologia, orientacion, metros, area, usuario, colega, cuotas, link_plano, link_plano2, nombre_colega, observaciones, target_oficina_id))
            
        conn.commit()
        flash("Lote manual agregado correctamente.", "success")
    except Exception as e:
        flash(f"Error al agregar lote manual: {e}", "danger")
    finally:
        conn.close()
        
    return redirect(url_for('lotes_excel.lotes'))

@lotes_excel_bp.route('/lotes/edit/<int:lote_id>', methods=['POST'])
@login_required
def edit_lote(lote_id):
    """Edit fields and financing details of a lot (Admins, Brokers of the office, or owner agent)."""
    conn = get_lotes_db_conn()
    try:
        # Retrieve active lot
        lote = conn.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
        if not lote:
            flash("Lote no encontrado.", "danger")
            return redirect(url_for('lotes_excel.lotes'))
            
        lote = dict(lote)
        
        # Check permissions: GermanMazza can edit all.
        # Admins and Brokers can edit any lot in their office.
        # Agents can only edit their own managed lot within their office.
        lote_user = (lote.get('usuario') or '').strip().lower()
        curr_user = (current_user.usuario or '').strip().lower()
        lote_office = lote.get('oficina_id') or 1
        user_office = getattr(current_user, 'oficina_id', None) or 1
        
        has_perm = False
        if current_user.usuario == 'GermanMazza':
            has_perm = True
        elif current_user.rol in ('admin', 'broker'):
            if lote_office == user_office:
                has_perm = True
        elif current_user.rol == 'agente':
            if lote_office == user_office and lote_user == curr_user:
                has_perm = True

        if not has_perm:
            flash("Permiso denegado. Solo podés editar lotes correspondientes a tu oficina.", "danger")
            return redirect(url_for('lotes_excel.lotes'))
            
        old_clave_natural = f"{lote['partido']}|{lote['localidad']}|{lote['barrio']}|{lote['numero']}"

        # Fields to edit
        partido = clean_lote_field(request.form.get('partido', lote['partido']), 'partido')
        localidad = clean_lote_field(request.form.get('localidad', lote['localidad']), 'localidad')
        barrio = clean_lote_field(request.form.get('barrio', lote['barrio']), 'barrio')
        numero = (request.form.get('numero') or lote['numero']).strip()
        area = request.form.get('area', '').strip()
        tipologia = clean_lote_field(request.form.get('tipologia', ''), 'tipologia')
        orientacion = clean_lote_field(request.form.get('orientacion', ''), 'orientacion')
        metros = request.form.get('metros', '').strip()
        usuario = request.form.get('usuario', '').strip()
        detalles_financiacion = request.form.get('detalles_financiacion', '').strip()
        link_plano = request.form.get('link_plano', '').strip()
        link_plano2 = request.form.get('link_plano2', '').strip()
        nombre_colega = request.form.get('nombre_colega', '').strip()
        observaciones = request.form.get('observaciones', '').strip()

        try:
            valor = float(request.form.get('valor', 0))
        except:
            valor = 0.0
            
        try:
            cuotas = int(request.form.get('cuotas', 1))
        except:
            cuotas = 1
            
        try:
            colega = int(request.form.get('colega', 0))
        except:
            colega = 0
            
        try:
            estado = int(request.form.get('estado', 1))
        except:
            estado = 1

        new_clave_natural = f"{partido}|{localidad}|{barrio}|{numero}"

        # If natural key changed, check for duplicate conflicts and clean old key
        if old_clave_natural != new_clave_natural:
            dup = conn.execute("SELECT id FROM lotes WHERE partido=? AND localidad=? AND barrio=? AND numero=? AND id != ? AND (oficina_id=? OR (oficina_id IS NULL AND 1=?)) AND eliminado_el IS NULL", (partido, localidad, barrio, numero, lote_id, lote_office, lote_office)).fetchone()
            if dup:
                flash(f"El lote #{numero} en {barrio} ({localidad}) ya existe en esta oficina.", "danger")
                return redirect(url_for('lotes_excel.lotes'))
            conn.execute("DELETE FROM lotes_detalles_manuales WHERE clave_natural = ?", (old_clave_natural,))

        # Update lotes table for all lots
        conn.execute("""
            UPDATE lotes SET 
                partido=?, localidad=?, barrio=?, numero=?,
                tipologia=?, orientacion=?, metros=?, area=?, usuario=?,
                valor=?, cuotas=?, colega=?, estado=?, link_plano=?,
                link_plano2=?, nombre_colega=?, observaciones=?
            WHERE id=?
        """, (partido, localidad, barrio, numero, tipologia, orientacion, metros, area, usuario, valor, cuotas, colega, estado, link_plano, link_plano2, nombre_colega, observaciones, lote_id))

        # Store in lotes_detalles_manuales with new_clave_natural
        conn.execute("""
            INSERT OR REPLACE INTO lotes_detalles_manuales (
                clave_natural, detalles_financiacion, valor_override, estado_override,
                tipologia_override, orientacion_override, metros_override, area_override,
                usuario_override, colega_override, cuotas_override, link_plano_override,
                link_plano2_override, nombre_colega_override, observaciones_override, oficina_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_clave_natural, detalles_financiacion, valor, estado, tipologia, orientacion, metros, area, usuario, colega, cuotas, link_plano, link_plano2, nombre_colega, observaciones, lote_office))

        conn.commit()
        flash(f"Lote #{numero} ({barrio}) actualizado con éxito.", "success")
    except Exception as e:
        flash(f"Error al editar lote: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for('lotes_excel.lotes'))

@lotes_excel_bp.route('/lotes/upload', methods=['POST'])
@login_required
def upload_lotes():
    """Handles Excel/TSV files parsing, keeping manual lots and override records intact within office."""
    target_oficina_id = getattr(current_user, 'oficina_id', None) or 1

    file = request.files.get('file')
    if not file or file.filename == '':
        flash("No se seleccionó ningún archivo.", "danger")
        return redirect(url_for('lotes_excel.lotes'))

    temp_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'scratch', f"temp_upload_lotes_{current_user.id}_{file.filename}")
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    file.save(temp_path)

    try:
        is_tsv = False
        with open(temp_path, "rb") as f:
            head = f.read(100)
            if b"\t" in head or b"partido\t" in head:
                is_tsv = True

        if is_tsv:
            df = pd.read_csv(temp_path, sep='\t')
        else:
            df = pd.read_excel(temp_path)

        df.columns = [str(c).strip().lower() for c in df.columns]

        # Define flexible column mappings
        mappings = {
            'partido': ['partido'],
            'localidad': ['localidad'],
            'barrio': ['barrio'],
            'area': ['area', 'área', 'area/sub-barrio/etapa', 'sub-barrio', 'etapa'],
            'numero': ['numero', 'número', 'nro lote', 'nro_lote', 'nrolote', 'lote nro', 'numero lote', 'numero_lote'],
            'tipologia': ['tipologia', 'tipología'],
            'orientacion': ['orientacion', 'orientación'],
            'metros': ['metros', 'metros2', 'm2', 'superficie', 'superficie m2', 'superficie_m2'],
            'valor': ['valor', 'precio', 'valor usd', 'valor u$d'],
            'cuotas': ['cuotas', 'financiación', 'financiacion'],
            'colega': ['colega', 'comision colega', 'comisión colega'],
            'usuario': ['usuario', 'productor', 'rbs', 'usuario / rbs'],
            'estado': ['estado'],
            'link_plano': ['link_plano', 'linkbarrio', 'link al plano', 'link plano', 'plano', 'link_plano_override'],
            'dateadd': ['dateadd', 'fecha', 'fecha_carga', 'fecha carga', 'creado', 'date_add']
        }

        def get_val(row_dict, db_col, default=''):
            aliases = mappings.get(db_col, [])
            for alias in aliases:
                if alias in row_dict:
                    val = row_dict[alias]
                    if pd.isna(val):
                        return default
                    return val
            return default

        conn = get_lotes_db_conn()
        try:
            # We ONLY delete imported lots (is_manual = 0) of the current user's office!
            if current_user.usuario == 'GermanMazza':
                conn.execute("DELETE FROM lotes WHERE is_manual = 0")
            else:
                conn.execute("DELETE FROM lotes WHERE is_manual = 0 AND (oficina_id = ? OR (oficina_id IS NULL AND 1 = ?))", (target_oficina_id, target_oficina_id))
            conn.commit()
            
            # Insert new rows
            count = 0
            for _, row in df.iterrows():
                row_dict = row.to_dict()
                partido = clean_lote_field(get_val(row_dict, 'partido', ''), 'partido')
                localidad = clean_lote_field(get_val(row_dict, 'localidad', ''), 'localidad')
                barrio = clean_lote_field(get_val(row_dict, 'barrio', ''), 'barrio')
                area = str(get_val(row_dict, 'area', '')).strip()
                numero = str(get_val(row_dict, 'numero', '')).strip()
                tipologia = clean_lote_field(get_val(row_dict, 'tipologia', ''), 'tipologia')
                orientacion = str(get_val(row_dict, 'orientacion', '')).strip()
                metros = str(get_val(row_dict, 'metros', '')).strip()
                link_plano = str(get_val(row_dict, 'link_plano', '')).strip()
                
                try:
                    valor = float(get_val(row_dict, 'valor', 0))
                except:
                    valor = 0.0
                    
                try:
                    cuotas = int(float(get_val(row_dict, 'cuotas', 0)))
                except:
                    cuotas = 0
                    
                try:
                    colega = int(float(get_val(row_dict, 'colega', 0)))
                except:
                    colega = 0
                    
                usuario = str(get_val(row_dict, 'usuario', '')).strip()
                
                try:
                    estado = int(float(get_val(row_dict, 'estado', 1)))
                except:
                    estado = 1
                    
                # Normalize dateadd to YYYY-MM-DD HH:MM:SS
                dateadd_val = get_val(row_dict, 'dateadd', '')
                if not dateadd_val or str(dateadd_val).strip().lower() == 'nan':
                    dateadd = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                else:
                    if isinstance(dateadd_val, (datetime, pd.Timestamp)):
                        dateadd = dateadd_val.strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        dateadd_str = str(dateadd_val).strip()
                        try:
                            parsed_dt = None
                            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y'):
                                try:
                                    parsed_dt = datetime.strptime(dateadd_str, fmt)
                                    break
                                except ValueError:
                                    continue
                            if parsed_dt:
                                dateadd = parsed_dt.strftime('%Y-%m-%d %H:%M:%S')
                            else:
                                dateadd = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            dateadd = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                if partido.lower() == 'nan': partido = ''
                if localidad.lower() == 'nan': localidad = ''
                if barrio.lower() == 'nan': barrio = ''
                if area.lower() == 'nan': area = ''
                if numero.lower() == 'nan': numero = ''
                if tipologia.lower() == 'nan': tipologia = ''
                if orientacion.lower() == 'nan': orientacion = ''
                if metros.lower() == 'nan': metros = ''
                if usuario.lower() == 'nan': usuario = ''
                if link_plano.lower() == 'nan': link_plano = ''

                # Check if this lot naturally clashes with an existing manually created lot in this office.
                # If so, the Excel version is ignored or manual wins. We prefer manual.
                dup = conn.execute("SELECT id FROM lotes WHERE partido=? AND localidad=? AND barrio=? AND numero=? AND is_manual=1 AND (oficina_id=? OR (oficina_id IS NULL AND 1=?))", (partido, localidad, barrio, numero, target_oficina_id, target_oficina_id)).fetchone()
                if dup:
                    continue

                conn.execute("""
                    INSERT INTO lotes (partido, localidad, barrio, area, numero, tipologia, orientacion, metros, valor, cuotas, colega, usuario, estado, dateadd, is_manual, link_plano, oficina_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """, (partido, localidad, barrio, area, numero, tipologia, orientacion, metros, valor, cuotas, colega, usuario, estado, dateadd, link_plano, target_oficina_id))
                count += 1
                
            conn.commit()
            flash(f"Se cargaron exitosamente {count} lotes desde la planilla. Los lotes manuales y detalles personalizados no se modificaron.", "success")
        finally:
            conn.close()

    except Exception as e:
        flash(f"Error procesando el archivo: {e}", "danger")
        print(f"Error importing lots: {e}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

    return redirect(url_for('lotes_excel.lotes'))

@lotes_excel_bp.route('/lotes/cleanup', methods=['POST'])
@login_required
def cleanup_orphans():
    """Manual cleanup tool for orphan manual details within office."""
    target_oficina_id = getattr(current_user, 'oficina_id', None) or 1
    conn = get_lotes_db_conn()
    try:
        if current_user.usuario == 'GermanMazza':
            active_rows = conn.execute("SELECT partido, localidad, barrio, numero FROM lotes").fetchall()
            override_rows = conn.execute("SELECT clave_natural FROM lotes_detalles_manuales").fetchall()
        else:
            active_rows = conn.execute("SELECT partido, localidad, barrio, numero FROM lotes WHERE oficina_id = ? OR (oficina_id IS NULL AND 1 = ?)", (target_oficina_id, target_oficina_id)).fetchall()
            override_rows = conn.execute("SELECT clave_natural FROM lotes_detalles_manuales WHERE oficina_id = ? OR (oficina_id IS NULL AND 1 = ?)", (target_oficina_id, target_oficina_id)).fetchall()

        active_keys = [f"{r['partido']}|{r['localidad']}|{r['barrio']}|{r['numero']}" for r in active_rows]
        override_keys = [row[0] for row in override_rows]
        
        orphans = [k for k in override_keys if k not in active_keys]
        
        deleted_count = 0
        for o in orphans:
            if current_user.usuario == 'GermanMazza':
                conn.execute("DELETE FROM lotes_detalles_manuales WHERE clave_natural = ?", (o,))
            else:
                conn.execute("DELETE FROM lotes_detalles_manuales WHERE clave_natural = ? AND (oficina_id = ? OR (oficina_id IS NULL AND 1 = ?))", (o, target_oficina_id, target_oficina_id))
            deleted_count += 1
            
        conn.commit()
        flash(f"Limpieza finalizada. Se eliminaron {deleted_count} registros huérfanos de la oficina.", "success")
    except Exception as e:
        flash(f"Error al limpiar huérfanos: {e}", "danger")
    finally:
        conn.close()
        
    return redirect(url_for('lotes_excel.lotes'))

@lotes_excel_bp.route('/lotes/sync_external', methods=['POST'])
@login_required
def sync_external():
    """Disabled synchronization."""
    flash("La sincronización automática con CandaosaProp ha sido desactivada.", "warning")
    return redirect(url_for('lotes_excel.lotes'))

@lotes_excel_bp.route('/lotes/clear', methods=['POST'])
@login_required
def clear_lotes():
    """Deletes all lotes from database for the user's office."""
    if current_user.rol not in ('admin', 'broker'):
        flash("Permiso denegado. Solo administradores o brokers pueden vaciar la base de datos de su oficina.", "danger")
        return redirect(url_for('lotes_excel.lotes'))

    target_oficina_id = getattr(current_user, 'oficina_id', None) or 1
    conn = get_lotes_db_conn()
    try:
        if current_user.usuario == 'GermanMazza':
            conn.execute("DELETE FROM lotes")
        else:
            conn.execute("DELETE FROM lotes WHERE oficina_id = ? OR (oficina_id IS NULL AND 1 = ?)", (target_oficina_id, target_oficina_id))
        conn.commit()
        flash("Se eliminaron los lotes de tu oficina. Los detalles personalizados se mantuvieron.", "info")
    except Exception as e:
        flash(f"Error al vaciar los lotes: {e}", "danger")
    finally:
        conn.close()
    return redirect(url_for('lotes_excel.lotes'))

@lotes_excel_bp.route('/lotes/download_excel', methods=['GET'])
@login_required
def download_excel():
    """Generates an Excel spreadsheet containing lotes of user's office merged with overrides."""
    import io
    target_oficina_id = getattr(current_user, 'oficina_id', None) or 1
    conn = get_lotes_db_conn()
    try:
        office_sql = ""
        office_params = []
        if current_user.usuario != 'GermanMazza':
            office_sql = " WHERE (l.oficina_id = ? OR (l.oficina_id IS NULL AND 1 = ?))"
            office_params = [target_oficina_id, target_oficina_id]

        query = f"""
            SELECT l.*, 
                   m.detalles_financiacion,
                   m.valor_override,
                   m.estado_override,
                   m.tipologia_override,
                   m.orientacion_override,
                   m.metros_override,
                   m.area_override,
                   m.usuario_override,
                   m.colega_override,
                   m.cuotas_override,
                   m.link_plano_override
            FROM lotes l
            LEFT JOIN lotes_detalles_manuales m 
              ON (l.partido || '|' || l.localidad || '|' || l.barrio || '|' || l.numero) = m.clave_natural
            {office_sql}
            ORDER BY l.id ASC
        """
        rows = conn.execute(query, office_params).fetchall()
        
        # Merge Overrides into dictionary format
        data = []
        for r in rows:
            ld = dict(r)
            if ld['valor_override'] is not None: ld['valor'] = ld['valor_override']
            if ld['estado_override'] is not None: ld['estado'] = ld['estado_override']
            if ld['tipologia_override'] is not None: ld['tipologia'] = ld['tipologia_override']
            if ld['orientacion_override'] is not None: ld['orientacion'] = ld['orientacion_override']
            if ld['metros_override'] is not None: ld['metros'] = ld['metros_override']
            if ld['area_override'] is not None: ld['area'] = ld['area_override']
            if ld['usuario_override'] is not None: ld['usuario'] = ld['usuario_override']
            if ld['colega_override'] is not None: ld['colega'] = ld['colega_override']
            if ld['cuotas_override'] is not None: ld['cuotas'] = ld['cuotas_override']
            if ld.get('link_plano_override') is not None: ld['link_plano'] = ld['link_plano_override']
            
            data.append({
                'PARTIDO': ld.get('partido', ''),
                'LOCALIDAD': ld.get('localidad', ''),
                'BARRIO': ld.get('barrio', ''),
                'AREA': ld.get('area', ''),
                'NUMERO': ld.get('numero', ''),
                'TIPOLOGIA': ld.get('tipologia', ''),
                'ORIENTACION': ld.get('orientacion', ''),
                'METROS': ld.get('metros', ''),
                'VALOR': ld.get('valor', 0.0),
                'CUOTAS': ld.get('cuotas', 1),
                'COLEGA': ld.get('colega', 0),
                'USUARIO': ld.get('usuario', ''),
                'ESTADO': ld.get('estado', 1),
                'LINK AL PLANO': ld.get('link_plano', '')
            })
            
        # Create Excel using Pandas
        df = pd.DataFrame(data)
        
        # Save to BytesIO
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='lotes', index=False)
            
        output.seek(0)
        
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="base_lotes_completa.xlsx"
        )
    except Exception as e:
        flash(f"Error generando descarga de Excel: {e}", "danger")
        return redirect(url_for('lotes_excel.lotes'))
    finally:
        conn.close()

@lotes_excel_bp.route('/lotes/export_pdf', methods=['POST'])
@login_required
def export_pdf():
    """Generates a professional PDF containing details for selected lotes."""
    lote_ids = request.form.getlist('selected_lotes')
    if not lote_ids:
        flash("No seleccionaste ningún lote para exportar.", "warning")
        return redirect(url_for('lotes_excel.lotes'))
        
    if len(lote_ids) > 100:
        flash("Solo podés exportar hasta 100 lotes juntos a la vez.", "warning")
        return redirect(url_for('lotes_excel.lotes'))
        
    # Query details for the selected lotes ensuring office isolation
    target_oficina_id = getattr(current_user, 'oficina_id', None) or 1
    conn = get_lotes_db_conn()
    try:
        office_filter = ""
        office_params = []
        if current_user.usuario != 'GermanMazza':
            office_filter = " AND (l.oficina_id = ? OR (l.oficina_id IS NULL AND 1 = ?))"
            office_params = [target_oficina_id, target_oficina_id]

        placeholders = ','.join('?' for _ in lote_ids)
        query = f"""
            SELECT l.*, 
                   m.detalles_financiacion,
                   m.valor_override,
                   m.estado_override,
                   m.tipologia_override,
                   m.orientacion_override,
                   m.metros_override,
                   m.area_override,
                   m.usuario_override,
                   m.colega_override,
                   m.cuotas_override,
                   m.link_plano_override,
                   m.link_plano2_override,
                   m.nombre_colega_override,
                   m.observaciones_override
            FROM lotes l
            LEFT JOIN lotes_detalles_manuales m 
              ON (l.partido || '|' || l.localidad || '|' || l.barrio || '|' || l.numero) = m.clave_natural
            WHERE l.id IN ({placeholders}) {office_filter}
            ORDER BY l.id ASC
        """
        rows = conn.execute(query, [int(x) for x in lote_ids] + office_params).fetchall()
        
        # Merge overrides
        lotes_data = []
        for r in rows:
            ld = dict(r)
            if ld['valor_override'] is not None: ld['valor'] = ld['valor_override']
            if ld['estado_override'] is not None: ld['estado'] = ld['estado_override']
            if ld['tipologia_override'] is not None: ld['tipologia'] = ld['tipologia_override']
            if ld['orientacion_override'] is not None: ld['orientacion'] = ld['orientacion_override']
            if ld['metros_override'] is not None: ld['metros'] = ld['metros_override']
            if ld['area_override'] is not None: ld['area'] = ld['area_override']
            if ld['usuario_override'] is not None: ld['usuario'] = ld['usuario_override']
            if ld['colega_override'] is not None: ld['colega'] = ld['colega_override']
            if ld['cuotas_override'] is not None: ld['cuotas'] = ld['cuotas_override']
            if ld.get('link_plano_override') is not None: ld['link_plano'] = ld['link_plano_override']
            if ld.get('link_plano2_override') is not None: ld['link_plano2'] = ld['link_plano2_override']
            if ld.get('nombre_colega_override') is not None: ld['nombre_colega'] = ld['nombre_colega_override']
            if ld.get('observaciones_override') is not None: ld['observaciones'] = ld['observaciones_override']
            lotes_data.append(ld)
            
        if not lotes_data:
            flash("No se encontraron lotes con los IDs proporcionados.", "danger")
            return redirect(url_for('lotes_excel.lotes'))
            
        # Read agent/branding config from database
        # Find the first non-empty usuario from the selected lotes
        agent_username = None
        for ld in lotes_data:
            if ld.get('usuario') and str(ld['usuario']).strip():
                agent_username = str(ld['usuario']).strip()
                break
        if not agent_username:
            agent_username = current_user.usuario

        agent_name = (get_agent_config_for_user(agent_username, 'agente_nombre') or "").strip()
        agent_phone = (get_agent_config_for_user(agent_username, 'agente_telefono') or "").strip()
        ag_settings = db.get_agency_settings()
        agent_email = get_agent_config_for_user(agent_username, 'agente_email') or ag_settings.get('email', 'contacto@inmobiliaria.com')
        agent_company = get_agent_config_for_user(agent_username, 'agente_inmobiliaria') or ag_settings.get('nombre', 'Inmobiliaria')
        if not agent_company or agent_company.strip() == "" or "tu inmobiliaria" in agent_company.lower():
            agent_company = ag_settings.get('nombre', 'Inmobiliaria')
            
        logo_relative = db.get_config('company_logo_path')
        logo_path = None
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if logo_relative:
            logo_path = os.path.join(root_dir, logo_relative.lstrip('/'))
            
        if not logo_path or not os.path.exists(logo_path):
            # Fallback scan uploads folder for any company_logo file
            uploads_dir = os.path.join(root_dir, 'static', 'uploads')
            if os.path.exists(uploads_dir):
                for f in os.listdir(uploads_dir):
                    if f.startswith('company_logo'):
                        logo_path = os.path.join(uploads_dir, f)
                        break
                        
        # Generate the PDF
        from fpdf import FPDF
        
        class LotesPDF(FPDF):
            def __init__(self, agent_name, agent_phone, agent_email, agent_company, logo_path=None):
                super().__init__()
                self.agent_name = (agent_name or '').strip()
                self.agent_phone = (agent_phone or '').strip()
                self.agent_email = (agent_email or '').strip()
                self.agent_company = (agent_company or '').strip()
                self.logo_path = logo_path
                
            def header(self):
                # Light cream/gray background
                self.set_fill_color(248, 249, 250)
                self.rect(0, 0, 210, 297, 'F')
                
                # Header Dark Blue Banner
                self.set_fill_color(18, 30, 49) # Deep corporate blue
                self.rect(0, 0, 210, 32, 'F')
                
                # Header Red accent line
                self.set_fill_color(186, 45, 37) # Crimson red
                self.rect(0, 32, 210, 2, 'F')
                
                # Draw logo if exists (positioned on the left)
                has_logo = False
                if self.logo_path:
                    try:
                        self.image(self.logo_path, 15, 5, h=22)
                        has_logo = True
                    except:
                        pass
                
                # Header text - Centered in the available space to the right of the logo
                self.set_text_color(255, 255, 255)
                
                title_text = f"{self.agent_company.upper()} - LOTES SELECCIONADOS" if self.agent_company else "LOTES SELECCIONADOS"
                if has_logo:
                    # Available space is from X=60 to X=175. That is 115mm.
                    # We use a smaller font size (11) if the name is too long to prevent overlaps.
                    font_size = 11 if len(title_text) > 35 else 12
                    self.set_font('helvetica', 'B', font_size)
                    self.set_xy(58, 11)
                    self.cell(115, 10, title_text, border=0, ln=0, align='C')
                else:
                    self.set_font('helvetica', 'B', 12)
                    self.set_xy(15, 11)
                    self.cell(160, 10, title_text, border=0, ln=0, align='C')
                
                self.set_font('helvetica', 'I', 9)
                self.set_xy(178, 11)
                self.cell(20, 10, datetime.now().strftime('%d/%m/%Y'), border=0, ln=0, align='R')
                
            def footer(self):
                self.set_y(-20)
                self.set_fill_color(18, 30, 49)
                self.rect(0, 297-18, 210, 18, 'F')
                
                # Bottom Red Accent line
                self.set_fill_color(186, 45, 37)
                self.rect(0, 297-18, 210, 1.5, 'F')
                
                self.set_text_color(255, 255, 255)
                self.set_font('helvetica', 'B', 7)
                
                # Dynamic contact info formatting (graceful fallback if name or phone not configured)
                left_parts = []
                if self.agent_name:
                    left_parts.append(f"Contacto: {self.agent_name}")
                if self.agent_phone:
                    left_parts.append(f"Tel: {self.agent_phone}")
                left_text = "  |  ".join(left_parts)
                
                right_parts = []
                if self.agent_email:
                    right_parts.append(f"Email: {self.agent_email}")
                if self.agent_company:
                    right_parts.append(self.agent_company)
                right_text = "  |  ".join(right_parts)
                
                if left_text:
                    self.text(12, 297-10, left_text)
                if right_text:
                    self.text(115, 297-10, right_text)
                
        pdf = LotesPDF(agent_name, agent_phone, agent_email, agent_company, logo_path)
        pdf.set_margins(15, 45, 15)
        pdf.set_auto_page_break(False) # Manual page break handling for perfect grid layouts
        pdf.add_page()
        pdf.set_y(45) # Force pointer below the header
        
        pdf.set_font("helvetica", "B", 13)
        pdf.set_text_color(33, 37, 41)
        pdf.cell(0, 8, "LOTES SELECCIONADOS PARA EVALUACIÓN", ln=True, align="L")
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(108, 117, 125)
        pdf.cell(0, 4, "A continuación se presentan los detalles técnicos y comerciales de las propiedades seleccionadas.", ln=True, align="L")
        pdf.ln(6)
        
        # Columns definition
        cols = [
            {"title": "Localidad", "width": 23, "align": "L"},
            {"title": "Barrio", "width": 28, "align": "L"},
            {"title": "Area", "width": 22, "align": "L"},
            {"title": "Lote Nro", "width": 13, "align": "C"},
            {"title": "Tipología", "width": 18, "align": "L"},
            {"title": "Or", "width": 8, "align": "C"},
            {"title": "Mts", "width": 12, "align": "C"},
            {"title": "Valor", "width": 23, "align": "R"},
            {"title": "Fin", "width": 13, "align": "C"},
            {"title": "Estado", "width": 20, "align": "C"}
        ]
        
        def draw_table_header(pdf):
            pdf.set_fill_color(18, 30, 49) # Deep corporate blue
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('helvetica', 'B', 8)
            for c in cols:
                pdf.cell(c['width'], 8, c['title'], border=1, ln=0, align=c['align'], fill=True)
            pdf.ln(8)
            
        draw_table_header(pdf)
        
        def truncate_str(s, max_len):
            s = str(s or '').strip()
            return s[:max_len] + '..' if len(s) > max_len else s
            
        for i, lote in enumerate(lotes_data):
            # Row height is 7.5mm. Page height limit is 262mm before overlapping the footer
            if pdf.get_y() + 7.5 > 262:
                pdf.add_page()
                pdf.set_y(45)
                draw_table_header(pdf)
                
            # Zebra striping
            if i % 2 == 0:
                pdf.set_fill_color(248, 249, 250)
            else:
                pdf.set_fill_color(255, 255, 255)
                
            pdf.set_text_color(33, 37, 41)
            pdf.set_font('helvetica', '', 7.5)
            pdf.set_draw_color(222, 226, 230)
            
            # Print row cells
            # 1. Localidad
            pdf.cell(23, 7.5, truncate_str(lote['localidad'], 13), border=1, ln=0, align='L', fill=True)
            # 2. Barrio
            pdf.cell(28, 7.5, truncate_str(lote['barrio'], 16), border=1, ln=0, align='L', fill=True)
            # 3. Area
            pdf.cell(22, 7.5, truncate_str(lote['area'] or 'N/A', 12), border=1, ln=0, align='L', fill=True)
            # 4. Lote Nro
            pdf.cell(13, 7.5, truncate_str(lote['numero'], 7), border=1, ln=0, align='C', fill=True)
            # 5. Tipología
            pdf.cell(18, 7.5, truncate_str(lote['tipologia'] or 'N/A', 10), border=1, ln=0, align='L', fill=True)
            # 6. Or (Orientacion)
            pdf.cell(8, 7.5, truncate_str(lote['orientacion'] or '-', 4), border=1, ln=0, align='C', fill=True)
            # 7. Mts (Superficie)
            pdf.cell(12, 7.5, truncate_str(lote['metros'] or '-', 6), border=1, ln=0, align='C', fill=True)
            
            # 8. Valor (Formatted to Argentine thousand dot separator)
            try:
                val_num = float(lote['valor'] or 0)
                val_str = f"U$D {val_num:,.0f}".replace(',', '.')
            except:
                val_str = str(lote['valor'] or '0')
            pdf.cell(23, 7.5, val_str, border=1, ln=0, align='R', fill=True)
            
            # 9. Fin (Si / No)
            fin_txt = "Si" if (lote['cuotas'] == 2 or lote.get('detalles_financiacion')) else "No"
            pdf.cell(13, 7.5, fin_txt, border=1, ln=0, align='C', fill=True)
            
            # 10. Estado (With bold and state color-coding)
            estado_lbls = {1: "Disponible", 2: "Reservado", 3: "Vendido", 4: "Res por Des"}
            estado_txt = estado_lbls.get(lote['estado'], "Disponible")
            
            if lote['estado'] == 1:
                pdf.set_text_color(40, 167, 69) # Green
            elif lote['estado'] == 2:
                pdf.set_text_color(220, 120, 0) # Orange
            elif lote['estado'] == 3:
                pdf.set_text_color(220, 53, 69) # Red
            else:
                pdf.set_text_color(111, 66, 193) # Purple
                
            pdf.set_font('helvetica', 'B', 7.5)
            pdf.cell(20, 7.5, estado_txt, border=1, ln=1, align='C', fill=True)
            
        import io
        pdf_output = io.BytesIO()
        pdf_bytes = pdf.output()
        pdf_output.write(pdf_bytes)
        pdf_output.seek(0)
        
        return send_file(
            pdf_output,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"lotes_seleccionados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
    except Exception as e:
        flash(f"Error generando exportación PDF: {e}", "danger")
        return redirect(url_for('lotes_excel.lotes'))
    finally:
        conn.close()
