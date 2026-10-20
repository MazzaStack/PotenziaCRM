"""
Database queries for properties, communications, saved searches and scrapers queue
"""
import sqlite3
from datetime import datetime, timedelta
from database.db import get_db, MASTER_DB_PATH

def asegurar_descripcion_propiedad(data):
    """Garantiza que toda propiedad insertada en la base de datos tenga siempre una descripción completa y profesional."""
    desc = str(data.get('descripcion') or '').strip()
    if desc and desc.lower() not in ['none', 'null', 'ver detalles en link...', 'ver detalles en link', 'detalles disponibles en el portal...'] and len(desc) >= 25:
        return desc
        
    titulo = str(data.get('titulo') or '').strip()
    tipo = str(data.get('tipo_propiedad') or 'Inmueble').capitalize()
    op = str(data.get('tipo_operacion') or 'Venta').capitalize()
    barrio = str(data.get('barrio') or data.get('direccion') or 'excelente ubicación').title()
    m2_tot = data.get('m2_total')
    m2_cub = data.get('m2_cubiertos')
    amb = data.get('ambientes')
    dorm = data.get('dormitorios')
    cocheras = data.get('cocheras')
    
    parts = []
    if titulo and len(titulo) > 15:
        parts.append(titulo + ".")
    else:
        parts.append(f"Excelente oportunidad de {tipo} en {op} situado en {barrio}.")
        
    if amb:
        parts.append(f"Cuenta con {amb} ambiente{'s' if amb > 1 else ''} muy funcionales con óptima distribución y luz natural.")
    if dorm:
        parts.append(f"Dispone de {dorm} dormitorio{'s' if dorm > 1 else ''}.")
    if m2_tot or m2_cub:
        sup = f"Superficie total de {m2_tot} m²" if m2_tot else ""
        if m2_cub and m2_cub != m2_tot:
            sup += f" ({m2_cub} m² cubiertos)"
        parts.append(f"{sup}.")
    if cocheras:
        parts.append(f"Incluye {cocheras} cochera(s).")
        
    parts.append("Ubicado en entorno residencial destacado con excelente accesibilidad, oferta comercial y transporte.")
    return " ".join(parts)

def enriquecer_descripciones_existentes():
    """Actualiza en masa las propiedades de la base de datos que tengan descripciones nulas o stub."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT id, portal, url, titulo, precio, moneda, direccion, barrio, 
                   m2_total, m2_cubiertos, ambientes, dormitorios, cocheras, 
                   tipo_propiedad, tipo_operacion, descripcion 
            FROM propiedades 
            WHERE descripcion IS NULL 
               OR descripcion = '' 
               OR LOWER(descripcion) IN ('none', 'null', 'ver detalles en link...', 'detalles disponibles en el portal...')
               OR LENGTH(descripcion) < 25
        """).fetchall()
        
        updated_count = 0
        for r in rows:
            data = dict(r)
            nueva_desc = asegurar_descripcion_propiedad(data)
            conn.execute("UPDATE propiedades SET descripcion = ? WHERE id = ?", (nueva_desc, r['id']))
            updated_count += 1
            
        if updated_count > 0:
            conn.commit()
            print(f"[DB Scrapers] Enriquecidas {updated_count} propiedades existentes en la base de datos con descripciones completas.")
    except Exception as e:
        print(f"[DB Scrapers] Error enriqueciendo descripciones existentes: {e}")
    finally:
        conn.close()

def insert_propiedad(data):
    """Insert a new scraped property, keeping existing manual status if already exists."""
    conn = get_db()
    try:
        url_raw = str(data.get('url') or '')
        # Clean tracking query parameters from URL for proper deduplication
        url_clean = url_raw.split('?')[0].strip() if url_raw else url_raw
        data['url'] = url_clean

        # Check if already exists (deduplication)
        row = conn.execute("SELECT id, estado FROM propiedades WHERE url = ? OR url = ?", (url_clean, url_raw)).fetchone()
        if row:
            # Skip updating state if it is not 'nueva'
            return row['id']
            
        import json
        from lib.photo_sanitizer import sanitize_property_photos
        fotos_list = data.get('fotos') or []
        if not fotos_list and data.get('foto_url'):
            fotos_list = [data['foto_url']]
        
        clean_cover, clean_fotos, _ = sanitize_property_photos(data.get('foto_url'), fotos_list, check_cover_content=True)
        data['foto_url'] = clean_cover
        fotos_json_val = json.dumps(clean_fotos) if clean_fotos else None
        
        # Sum toilettes and banos as requested
        banos_val = data.get('banos')
        toilettes_val = data.get('toilettes')
        try:
            banos_int = int(banos_val) if banos_val is not None else 0
        except:
            banos_int = 0
        try:
            toilettes_int = int(toilettes_val) if toilettes_val is not None else 0
        except:
            toilettes_int = 0
        
        # If banos_int was parsed and we have toilettes, sum them. Otherwise if we only have toilettes, make it toilettes_int.
        summed_banos = banos_int + toilettes_int if (banos_int or toilettes_int) else None
        desc_val = data.get('descripcion')
        if not desc_val:
            desc_val = asegurar_descripcion_propiedad(data)

        cursor = conn.execute("""
            INSERT OR IGNORE INTO propiedades (
                portal, url, titulo, precio, moneda, direccion, barrio, ciudad,
                m2_total, m2_cubiertos, ambientes, dormitorios, banos,
                tipo_propiedad, tipo_operacion, nombre_contacto, telefono,
                email_contacto, descripcion, foto_url, fecha_publicacion, lat, lng, notas,
                antiguedad, cocheras, toilettes, orientacion, disposicion, estado_conservacion, fotos_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['portal'], data['url'], data.get('titulo'), data.get('precio'),
            data.get('moneda', 'USD'), data.get('direccion'), data.get('barrio'),
            data.get('ciudad'), data.get('m2_total'), data.get('m2_cubiertos'),
            data.get('ambientes'), data.get('dormitorios'), summed_banos,
            data.get('tipo_propiedad'), data.get('tipo_operacion', 'venta'),
            data.get('nombre_contacto'), data.get('telefono'), data.get('email_contacto'),
            desc_val, data.get('foto_url'), data.get('fecha_publicacion'),
            data.get('lat'), data.get('lng'), data.get('notas'),
            data.get('antiguedad'), data.get('cocheras'), data.get('toilettes'),
            data.get('orientacion'), data.get('disposicion'), data.get('estado_conservacion'),
            fotos_json_val
        ))
        conn.commit()
        last_id = cursor.lastrowid


        return last_id
    finally:
        conn.close()

def get_propiedades(estado=None, portal=None, telefono=None, limit=50, offset=0, min_fecha=None):
    """Get properties with optional state, portal, phone, date filters and pagination."""
    conn = get_db()
    try:
        query = """
            SELECT *, 
                   (SELECT COUNT(*) FROM comunicaciones WHERE propiedad_id = propiedades.id AND estado = 'enviada') as contactos_count 
            FROM propiedades 
            WHERE 1=1
        """
        params = []
        
        # Check current user to filter by agent if role is agente, or by office if office admin/broker
        try:
            from flask import has_request_context
            from flask_login import current_user
            if has_request_context() and current_user and current_user.is_authenticated:
                if current_user.rol == 'agente':
                    query += " AND agente_id = ?"
                    params.append(current_user.id)
                elif current_user.usuario != 'GermanMazza' and getattr(current_user, 'oficina_id', None):
                    query += " AND agente_id IN (SELECT id FROM usuarios WHERE oficina_id = ?)"
                    params.append(current_user.oficina_id)
        except Exception as e:
            pass
            
        if estado:
            query += " AND estado = ?"
            params.append(estado)
        if portal:
            query += " AND portal = ?"
            params.append(portal)
        if telefono:
            query += " AND telefono = ?"
            params.append(telefono)
        if min_fecha:
            query += " AND fecha_captacion >= ?"
            params.append(str(min_fecha))
            
        query += " ORDER BY fecha_captacion DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_propiedad(prop_id):
    """Get a single property by its ID."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM propiedades WHERE id = ?", (prop_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def update_propiedad_estado(prop_id, estado, notas=None):
    """Update status and optionally append notes to a property."""
    conn = get_db()
    try:
        if notas:
            # Append notes
            row = conn.execute("SELECT notas FROM propiedades WHERE id = ?", (prop_id,)).fetchone()
            current_notes = row['notas'] if row and row['notas'] else ""
            new_notes = f"{current_notes}\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {notas}".strip()
            conn.execute("UPDATE propiedades SET estado = ?, notas = ? WHERE id = ?", (estado, new_notes, prop_id))
        else:
            conn.execute("UPDATE propiedades SET estado = ? WHERE id = ?", (estado, prop_id))
        conn.commit()
    finally:
        conn.close()

def delete_propiedad(prop_id):
    """Delete a property and its communication logs."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM comunicaciones WHERE propiedad_id = ?", (prop_id,))
        conn.execute("DELETE FROM propiedades WHERE id = ?", (prop_id,))
        conn.commit()
    finally:
        conn.close()

def delete_propiedades_bulk(prop_ids):
    """Delete multiple properties in a single transaction."""
    if not prop_ids: return
    conn = get_db()
    try:
        placeholders = ",".join(["?"] * len(prop_ids))
        conn.execute(f"DELETE FROM comunicaciones WHERE propiedad_id IN ({placeholders})", prop_ids)
        conn.execute(f"DELETE FROM propiedades WHERE id IN ({placeholders})", prop_ids)
        conn.commit()
    finally:
        conn.close()

def delete_propiedades_by_busqueda(busqueda_id):
    """Delete all properties belonging to a search ID."""
    conn = get_db()
    try:
        conn.execute("""
            DELETE FROM comunicaciones 
            WHERE propiedad_id IN (SELECT id FROM propiedades WHERE busqueda_id = ?)
        """, (busqueda_id,))
        conn.execute("DELETE FROM propiedades WHERE busqueda_id = ?", (busqueda_id,))
        conn.commit()
    finally:
        conn.close()

def insert_comunicacion(data):
    """Insert a new communication log (drip steps)."""
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO comunicaciones (
                propiedad_id, tipo, mensaje, asunto, fecha_programada, paso, estado
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data['propiedad_id'], data['tipo'], data.get('mensaje'), data.get('asunto'),
            data.get('fecha_programada', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            data.get('paso', 1), data.get('estado', 'pendiente')
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def get_comunicaciones(propiedad_id=None, estado=None):
    """Get communication logs with optional filters."""
    conn = get_db()
    try:
        query = """
            SELECT c.*, p.titulo, p.portal, p.url, p.nombre_contacto, p.telefono 
            FROM comunicaciones c
            JOIN propiedades p ON c.propiedad_id = p.id
            WHERE 1=1
        """
        params = []
        if propiedad_id:
            query += " AND c.propiedad_id = ?"
            params.append(propiedad_id)
        if estado:
            query += " AND c.estado = ?"
            params.append(estado)
            
        query += " ORDER BY c.fecha_programada DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def marcar_comunicacion_enviada(com_id):
    """Mark a communication log as sent, scheduling future follow-ups if enabled."""
    conn = get_db()
    try:
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("UPDATE comunicaciones SET estado = 'enviada', fecha_enviada = ? WHERE id = ?", (now_str, com_id))
        
        # Get communication detail
        row = conn.execute("SELECT * FROM comunicaciones WHERE id = ?", (com_id,)).fetchone()
        if row:
            pid = row['propiedad_id']
            paso = row['paso']
            
            # If step 3 is sent, mark property as desestimada (end of drip sequence)
            if paso >= 3:
                conn.execute("UPDATE propiedades SET estado = 'descartada', notas = 'Drip completado sin respuesta.' WHERE id = ?", (pid,))
                
        conn.commit()
    finally:
        conn.close()

def marcar_comunicacion_respondida(com_id):
    """Mark a communication as answered, stopping further drip automated steps."""
    conn = get_db()
    try:
        conn.execute("UPDATE comunicaciones SET estado = 'respondida' WHERE id = ?", (com_id,))
        # Update property to en_seguimiento or similar, meaning humans are in charge
        row = conn.execute("SELECT propiedad_id FROM comunicaciones WHERE id = ?", (com_id,)).fetchone()
        if row:
            conn.execute("UPDATE propiedades SET estado = 'en_seguimiento' WHERE id = ?", (row['propiedad_id'],))
        conn.commit()
    finally:
        conn.close()

def update_comunicacion_estado(com_id, estado):
    """Update generic communication status."""
    conn = get_db()
    try:
        conn.execute("UPDATE comunicaciones SET estado = ? WHERE id = ?", (estado, com_id))
        conn.commit()
    finally:
        conn.close()

def delete_comunicacion(com_id):
    """Delete a communication log."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM comunicaciones WHERE id = ?", (com_id,))
        conn.commit()
    finally:
        conn.close()

def get_ready_for_step1(limit=5):
    """Find properties that are 'nueva' and ready for first contact (Step 1)."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT * FROM propiedades 
            WHERE estado = 'nueva' 
              AND nombre_contacto IS NOT NULL 
              AND nombre_contacto != ''
              AND telefono IS NOT NULL 
              AND telefono != ''
            ORDER BY fecha_captacion DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_ready_for_next_step(limit=50, limit_per_week=0):
    """
    Find properties in 'contactada' or 'en_seguimiento' that need follow-up (Steps 2 or 3).
    Follow-up times are configurable: Paso 2 (3 days delay), Paso 3 (8 days delay).
    """
    conn = get_db()
    try:
        now = datetime.now()
        thirty_days_ago = (now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
        
        # We fetch communications that were sent, are step 1 or 2, and are older than threshold
        q = """
            SELECT c.propiedad_id, MAX(c.paso) as max_paso, MAX(c.fecha_enviada) as ultima_fecha
            FROM comunicaciones c
            JOIN propiedades p ON c.propiedad_id = p.id
            WHERE c.estado = 'enviada' 
              AND p.estado IN ('contactada', 'en_seguimiento')
              AND c.fecha_enviada > ?
            GROUP BY c.propiedad_id
        """
        rows = conn.execute(q, (thirty_days_ago,)).fetchall()
        
        ready_properties = []
        
        # Load followup delays configurations
        days_step2 = int(conn.execute("SELECT valor FROM configuracion WHERE clave = 'followup_dias_1'").fetchone()['valor'] or 3)
        days_step3 = int(conn.execute("SELECT valor FROM configuracion WHERE clave = 'followup_dias_2'").fetchone()['valor'] or 8)
        
        for r in rows:
            pid = r['propiedad_id']
            max_paso = r['max_paso']
            ultima_fecha_str = r['ultima_fecha']
            
            if not ultima_fecha_str: continue
            
            try:
                ultima_fecha = datetime.strptime(ultima_fecha_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                try:
                    ultima_fecha = datetime.strptime(ultima_fecha_str, '%Y-%m-%d %H:%M')
                except ValueError:
                    continue
            
            # Check if already has a pending communication (don't duplicate)
            pending = conn.execute("""
                SELECT id FROM comunicaciones 
                WHERE propiedad_id = ? AND estado = 'pendiente'
            """, (pid,)).fetchone()
            if pending: continue
            
            siguiente = max_paso + 1
            if siguiente > 3: continue # Max 3 drip steps
            
            delay_days = days_step2 if siguiente == 2 else days_step3
            target_date = ultima_fecha + timedelta(days=delay_days)
            
            if now >= target_date:
                prop = conn.execute("SELECT * FROM propiedades WHERE id = ?", (pid,)).fetchone()
                if prop:
                    p_dict = dict(prop)
                    p_dict['siguiente_paso'] = siguiente
                    ready_properties.append(p_dict)
                    
        return ready_properties[:limit]
    finally:
        conn.close()

def get_estadisticas():
    """Generates KPI metrics for the CRM Dashboard."""
    stats = {
        'total': 0, 'nuevas': 0, 'contactadas': 0, 'en_seguimiento': 0, 
        'captadas': 0, 'descartadas': 0,
        'mensajes_hoy': 0, 'mensajes_historico': 0,
        'semana2_listas': 0, 'tasa_conversion': 0,
        'ia_stats': []
    }
    
    conn = get_db()
    try:
        # Properties counts
        rows_props = conn.execute("SELECT estado, COUNT(*) as cnt FROM propiedades GROUP BY estado").fetchall()
        for r in rows_props:
            stats['total'] += r['cnt']
            if r['estado'] == 'nueva': stats['nuevas'] = r['cnt']
            elif r['estado'] == 'contactada': stats['contactadas'] = r['cnt']
            elif r['estado'] == 'en_seguimiento': stats['en_seguimiento'] = r['cnt']
            elif r['estado'] == 'captada': stats['captadas'] = r['cnt']
            elif r['estado'] == 'descartada': stats['descartadas'] = r['cnt']
            
        # Message counts
        today_start = datetime.now().strftime('%Y-%m-%d 00:00:00')
        row_hoy = conn.execute("SELECT COUNT(*) as cnt FROM comunicaciones WHERE estado = 'enviada' AND fecha_enviada >= ?", (today_start,)).fetchone()
        stats['mensajes_hoy'] = row_hoy['cnt']
        
        row_hist = conn.execute("SELECT COUNT(*) as cnt FROM comunicaciones WHERE estado = 'enviada'").fetchone()
        stats['mensajes_historico'] = row_hist['cnt']
        
        # Ready for week 2 count
        threshold = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        row_w2 = conn.execute("""
            SELECT COUNT(DISTINCT p.id) as cnt
            FROM propiedades p
            JOIN comunicaciones c ON p.id = c.propiedad_id
            WHERE p.estado = 'contactada' 
            AND c.estado = 'enviada' AND c.paso = 1
            AND c.fecha_enviada < ?
            AND NOT EXISTS (
                SELECT 1 FROM comunicaciones c2 
                WHERE c2.propiedad_id = p.id AND c2.paso = 2
            )
        """, (threshold,)).fetchone()
        stats['semana2_listas'] = row_w2['cnt']
        
        # Conversion rate
        stats['tasa_conversion'] = (
            round(stats['captadas'] / stats['total'] * 100, 1) if stats['total'] > 0 else 0
        )
        
        # AI Stats
        rows_ia = conn.execute("SELECT * FROM estadisticas_ia").fetchall()
        stats['ia_stats'] = [dict(row) for row in rows_ia]
        
        return stats
    finally:
        conn.close()

def incrementar_respuesta_ia(estrategia):
    """Incrementa en 1 el contador de respuestas (éxito) para la estrategia IA usada."""
    if not estrategia:
        return
    conn = get_db()
    try:
        conn.execute(
            "UPDATE estadisticas_ia SET respuestas = respuestas + 1 WHERE estrategia = ?",
            (estrategia,)
        )
        conn.commit()
    finally:
        conn.close()

def get_busquedas():
    """Get all saved searches."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM busquedas ORDER BY id").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def insert_busqueda(data):
    """Insert a new search."""
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO busquedas (nombre, portal, url_busqueda, frecuencia_minutos)
            VALUES (?, ?, ?, ?)
        """, (data['nombre'], data['portal'], data['url_busqueda'], data.get('frecuencia_minutos', 60)))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def toggle_busqueda(busqueda_id):
    """Toggle a search active/inactive."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE busquedas SET activa = CASE WHEN activa = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (busqueda_id,)
        )
        conn.commit()
    finally:
        conn.close()

def delete_busqueda(busqueda_id):
    """Delete a search."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM busquedas WHERE id = ?", (busqueda_id,))
        conn.commit()
    finally:
        conn.close()

def get_planificador():
    """Get all 10 weeks of the message planner."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM planificador_mensajes ORDER BY semana ASC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def update_planificador_semana(semana, mensaje, habilitado):
    """Update a specific week in the planner."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE planificador_mensajes SET mensaje = ?, habilitado = ? WHERE semana = ?",
            (mensaje, habilitado, semana)
        )
        conn.commit()
    finally:
        conn.close()

def get_tareas_diarias(fecha=None):
    """Get social task statuses for a specific date, scoped to the current user."""
    if not fecha:
        fecha = datetime.now().strftime('%Y-%m-%d')
    # Get current user ID
    agente_id = None
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user and current_user.is_authenticated:
            agente_id = current_user.id
    except Exception:
        pass

    conn = get_db()
    try:
        if agente_id:
            row = conn.execute(
                "SELECT * FROM tareas_diarias_estado WHERE fecha = ? AND agente_id = ?",
                (fecha, agente_id)
            ).fetchone()
            if row:
                return dict(row)
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO tareas_diarias_estado (fecha, agente_id) VALUES (?, ?)",
                    (fecha, agente_id)
                )
                conn.commit()
                return {'fecha': fecha, 'agente_id': agente_id,
                        'historias_ig_wa': 0, 'lanzar_lote_5_5': 0,
                        'automatizacion_diaria': 0, 'mantenimiento_base': 0}
        else:
            # Fallback: no user context (background jobs), return first row for date
            row = conn.execute(
                "SELECT * FROM tareas_diarias_estado WHERE fecha = ?", (fecha,)
            ).fetchone()
            return dict(row) if row else {'fecha': fecha, 'historias_ig_wa': 0, 'lanzar_lote_5_5': 0, 'automatizacion_diaria': 0, 'mantenimiento_base': 0}
    finally:
        conn.close()

def update_tarea_diaria(campo, valor, fecha=None):
    """Update status for a specific daily task, scoped to the current user."""
    if not fecha:
        fecha = datetime.now().strftime('%Y-%m-%d')
    agente_id = None
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user and current_user.is_authenticated:
            agente_id = current_user.id
    except Exception:
        pass

    # Ensure the row exists for today + agent
    get_tareas_diarias(fecha)
    
    allowed_fields = ['historias_ig_wa', 'lanzar_lote_5_5', 'automatizacion_diaria', 'mantenimiento_base']
    if campo not in allowed_fields:
        return

    conn = get_db()
    try:
        if agente_id:
            conn.execute(
                f"UPDATE tareas_diarias_estado SET {campo} = ? WHERE fecha = ? AND agente_id = ?",
                (valor, fecha, agente_id)
            )
        else:
            conn.execute(
                f"UPDATE tareas_diarias_estado SET {campo} = ? WHERE fecha = ?",
                (valor, fecha)
            )
        conn.commit()
    finally:
        conn.close()

def purgar_inmobiliarias():
    """
    Analiza la base de datos de propiedades y descarta automáticamente
    aquellas cuyo nombre de contacto o título coincida con 
    palabras clave de agencias o inmobiliarias.
    """
    conn = get_db()
    agency_name = (get_config('nombre_inmobiliaria') or '').lower().strip()
    keywords = ['inmobiliaria', 'remax', 'century', 'arquitectura', 'desarrollos', 'bienes raices', 'emprendimientos', 'grupo', 'propiedades', 'broker', 'operaciones', 'comercial']
    if agency_name and len(agency_name) > 3 and agency_name not in keywords:
        keywords.append(agency_name)
    
    likes = []
    params = []
    for k in keywords:
        likes.append("(LOWER(nombre_contacto) LIKE ? OR LOWER(titulo) LIKE ?)")
        params.extend([f"%{k}%", f"%{k}%"])
        
    where_clause = " OR ".join(likes)
    
    query = f"""
    UPDATE propiedades 
    SET estado = 'descartada', notas = 'Purgada automáticamente por detector de inmobiliarias',
        puntaje = -1
    WHERE estado IN ('nueva', 'contactada', 'en_seguimiento')
    AND ({where_clause})
    """
    
    try:
        cursor = conn.execute(query, params)
        conn.commit()
        eliminadas = cursor.rowcount
    except Exception as e:
        print(f"Error purgando inmobiliarias: {e}")
        eliminadas = 0
    finally:
        conn.close()
        
    return eliminadas

# ==========================================
# CLIENT SAVED SEARCHES AND EMAIL QUEUE
# ==========================================

def insert_busqueda_cliente(data):
    """Insert a new client saved search."""
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO busquedas_clientes (
                cliente_id, nombre, tipo_operacion, tipo_propiedad, zona, 
                ambientes, dormitorios, min_precio, max_precio, min_m2, max_m2, 
                extras, keyword, agente_id, modo_busqueda, es_publica
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data['cliente_id'], data['nombre'], data.get('tipo_operacion', 'venta'),
            data.get('tipo_propiedad', 'departamento'), data['zona'],
            data.get('ambientes'), data.get('dormitorios'), data.get('min_precio'),
            data.get('max_precio'), data.get('min_m2'), data.get('max_m2'),
            data.get('extras'), data.get('keyword'), data.get('agente_id'),
            data.get('modo_busqueda', 'completa'),
            1 if data.get('es_publica') in (1, '1', True, 'true', 'on') else 0
        ))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def get_busquedas_clientes(agente_id=None):
    """Get client saved searches, optionally filtering by agent, with client and agent details."""
    conn = get_db()
    try:
        query = """
            SELECT bc.*, 
                   c.nombre as cliente_nombre, c.apellido as cliente_apellido, c.email as cliente_email,
                   u.nombre_display as agente_nombre, u.usuario as agente_usuario
            FROM busquedas_clientes bc
            JOIN contactos c ON bc.cliente_id = c.id
            LEFT JOIN usuarios u ON bc.agente_id = u.id
            WHERE bc.eliminado_el IS NULL
        """
        params = []
        if agente_id:
            query += " AND bc.agente_id = ?"
            params.append(agente_id)
        query += " ORDER BY bc.fecha_creacion DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def get_busquedas_publicas_oficina(excluir_agente_id=None, oficina_id=None):
    """Get public searches shared across the office by other agents within the same office."""
    # If a solo agent (oficina_id is None and not superadmin), they have no shared office searches
    try:
        from flask import has_request_context
        from flask_login import current_user
        if has_request_context() and current_user and current_user.is_authenticated:
            if current_user.usuario != 'GermanMazza':
                if not getattr(current_user, 'oficina_id', None):
                    return []
                if not oficina_id:
                    oficina_id = current_user.oficina_id
    except Exception:
        pass

    conn = get_db()
    try:
        query = """
            SELECT bc.*, 
                   c.nombre as cliente_nombre, c.apellido as cliente_apellido, c.email as cliente_email,
                   u.nombre_display as agente_nombre, u.usuario as agente_usuario, u.oficina_id as agente_oficina_id
            FROM busquedas_clientes bc
            JOIN contactos c ON bc.cliente_id = c.id
            LEFT JOIN usuarios u ON bc.agente_id = u.id
            WHERE bc.es_publica = 1 AND bc.eliminado_el IS NULL
        """
        params = []
        if excluir_agente_id:
            query += " AND (bc.agente_id IS NULL OR bc.agente_id != ?)"
            params.append(excluir_agente_id)
        if oficina_id:
            query += " AND u.oficina_id = ?"
            params.append(oficina_id)
            
        query += " ORDER BY bc.fecha_creacion DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        # If column does not exist yet in target database, auto-add it and retry once
        if 'es_publica' in str(e):
            try:
                conn.execute("ALTER TABLE busquedas_clientes ADD COLUMN es_publica INTEGER DEFAULT 0")
                conn.commit()
                rows = conn.execute(query, params).fetchall()
                return [dict(row) for row in rows]
            except Exception:
                pass
        return []
    finally:
        conn.close()

def get_busqueda_cliente(bid):
    """Get a single client saved search by ID with client and agent details."""
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT bc.*, 
                   c.nombre as cliente_nombre, c.apellido as cliente_apellido, c.email as cliente_email,
                   u.nombre_display as agente_nombre, u.usuario as agente_usuario, u.oficina_id as agente_oficina_id
            FROM busquedas_clientes bc
            LEFT JOIN contactos c ON bc.cliente_id = c.id
            LEFT JOIN usuarios u ON bc.agente_id = u.id
            WHERE bc.id = ? AND bc.eliminado_el IS NULL
        """, (bid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def update_busqueda_cliente_cliente(bid, nuevo_cliente_id):
    """Reassign the client for a saved search."""
    conn = get_db()
    try:
        conn.execute("UPDATE busquedas_clientes SET cliente_id = ? WHERE id = ?", (nuevo_cliente_id, bid))
        conn.commit()
    finally:
        conn.close()

def update_busqueda_cliente_vistas(bid, vistas_json):
    """Update properties_vistas JSON for a client search."""
    conn = get_db()
    try:
        conn.execute("UPDATE busquedas_clientes SET propiedades_vistas = ?, ultima_ejecucion = datetime('now', 'localtime') WHERE id = ?", (vistas_json, bid))
        conn.commit()
    finally:
        conn.close()

def delete_busqueda_cliente(bid, deleted_by=None):
    """Delete a client saved search (Soft-Delete)."""
    if not deleted_by:
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                deleted_by = current_user.nombre_display or current_user.usuario
        except Exception:
            deleted_by = "Sistema"
    from database.db_papelera import soft_delete_record
    return soft_delete_record('busquedas_clientes', bid, deleted_by=deleted_by or "Sistema")

def enqueue_correo_cliente(email_dest, asunto, cuerpo_html, agente_id=None):
    """Enqueue an email to be sent staggered.
    
    agente_id: int or None. When set, the email worker will use this agent's
               own SMTP config (smtp_host_<id>, smtp_user_<id>, etc.) to send.
    """
    if agente_id is None:
        try:
            from flask import has_request_context
            from flask_login import current_user
            if has_request_context() and current_user and current_user.is_authenticated:
                agente_id = current_user.id
        except Exception:
            pass

    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO cola_correos_clientes (email_dest, asunto, cuerpo_html, agente_id)
            VALUES (?, ?, ?, ?)
        """, (email_dest, asunto, cuerpo_html, agente_id))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def get_pending_correos_clientes():
    """Get all pending emails from the queue."""
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM cola_correos_clientes WHERE estado = 'pendiente' ORDER BY fecha_creacion ASC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()

def update_correo_cliente_estado(cid, estado, error_log=None):
    """Update status of a queued email."""
    conn = get_db()
    try:
        if estado == 'enviado':
            conn.execute("""
                UPDATE cola_correos_clientes 
                SET estado = 'enviado', fecha_enviado = datetime('now', 'localtime'), error_log = NULL 
                WHERE id = ?
            """, (cid,))
        else:
            conn.execute("""
                UPDATE cola_correos_clientes 
                SET estado = ?, error_log = ? 
                WHERE id = ?
            """, (estado, error_log, cid))
        conn.commit()
    finally:
        conn.close()

