"""
Morning Briefing Worker for Asistente IA Plugin.
Dispatches automated daily morning briefing to real estate agents via WhatsApp Portal Clientes session.
Runs every day at 8:30 AM without blocking or interfering with client portal tasks.
"""
import os
import sys
import time
import json
import subprocess
import threading
from datetime import datetime
from database import db
from plugins.asistente_ia.service import generar_morning_briefing

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WA_NODE_DIR = os.path.join(WORKSPACE_DIR, 'lib', 'whatsapp_node')
SENDER_SCRIPT = os.path.join(WA_NODE_DIR, 'ephemeral_sender.js')

def _enviar_whatsapp_portal(telefono, mensaje):
    """
    Envía un mensaje usando la sesión de WhatsApp del Portal de Clientes (--scope portal).
    No interfiere con las tareas de los clientes web ni bloquea la ejecución.
    """
    if not telefono:
        return False, "Teléfono vacío"
        
    clean_phone = str(telefono).replace(" ", "").replace("-", "").replace("+", "")
    if len(clean_phone) < 8:
        return False, f"Teléfono inválido: {telefono}"
        
    try:
        node_bin = os.path.join(WA_NODE_DIR, 'bin', 'node.exe')
        node_cmd = node_bin if os.path.exists(node_bin) else "node"
        
        cmd = [
            node_cmd, SENDER_SCRIPT,
            '--scope', 'portal',
            '--user', 'admin',
            '--action', 'message',
            '--phone', clean_phone,
            '--text', mensaje
        ]
        
        creationflags = 0x08000000 if os.name == 'nt' else 0
        from database.db import DB_DIR
        log_dir = os.path.join(DB_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "wa_morning_briefing.log")
        
        print(f"[MorningBriefing] Conectando a WhatsApp Portal y enviando a {clean_phone}...")
        result = subprocess.run(
            cmd,
            cwd=WA_NODE_DIR,
            capture_output=True,
            text=True,
            timeout=45,
            creationflags=creationflags
        )
        
        with open(log_file_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Envío a {clean_phone} (Exit: {result.returncode}):\n{result.stdout}\n{result.stderr}\n")

        if result.returncode == 0:
            print(f"[MorningBriefing] [OK] Enviado exitosamente a {clean_phone}")
            return True, "Enviado exitosamente vía WhatsApp Portal"
        else:
            err_details = result.stderr or result.stdout or f"Exit code {result.returncode}"
            print(f"[MorningBriefing] [ERROR] Falló envío a {clean_phone}: {err_details}")
            return False, f"Error en envío de WhatsApp: {err_details}"
    except subprocess.TimeoutExpired:
        return False, "Timeout esperando respuesta del servicio de WhatsApp"
    except Exception as e:
        err_msg = f"Error ejecutando sender portal: {e}"
        print(f"[MorningBriefing] {err_msg}")
        return False, err_msg

def recopilar_datos_agente(agente_id, agente_usuario=None):
    """
    Obtiene las tareas, recordatorios, cumpleaños, aniversarios y contactos fríos del agente.
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_md = datetime.now().strftime('%m-%d')
    conn = db.get_db()
    try:
        is_super = (agente_usuario == 'GermanMazza') or (agente_id is None)
        
        # 1. Recordatorios pendientes para hoy o antes
        if is_super:
            rec_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, recordatorio_fecha, notas 
                FROM contactos 
                WHERE recordatorio_activo = 1 
                  AND recordatorio_fecha IS NOT NULL 
                  AND recordatorio_fecha <= ?
                ORDER BY recordatorio_fecha ASC
            """, (today_str,)).fetchall()
        else:
            rec_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, recordatorio_fecha, notas 
                FROM contactos 
                WHERE recordatorio_activo = 1 
                  AND recordatorio_fecha IS NOT NULL 
                  AND recordatorio_fecha <= ? 
                  AND agente_id = ?
                ORDER BY recordatorio_fecha ASC
            """, (today_str, agente_id)).fetchall()
        recordatorios_hoy = [dict(r) for r in rec_rows]

        # 2. Cumpleaños y Aniversarios hoy (compatible SQLite y Postgres)
        if is_super:
            cumple_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, fecha_nacimiento, categoria, rol, notas 
                FROM contactos 
                WHERE fecha_nacimiento LIKE ? OR SUBSTR(fecha_nacimiento, 6, 5) = ?
            """, (f"%{today_md}%", today_md)).fetchall()
            
            aniv_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, aniversario_casa, categoria, rol, notas 
                FROM contactos 
                WHERE aniversario_casa LIKE ? OR SUBSTR(aniversario_casa, 6, 5) = ?
            """, (f"%{today_md}%", today_md)).fetchall()
        else:
            cumple_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, fecha_nacimiento, categoria, rol, notas 
                FROM contactos 
                WHERE (fecha_nacimiento LIKE ? OR SUBSTR(fecha_nacimiento, 6, 5) = ?) AND agente_id = ?
            """, (f"%{today_md}%", today_md, agente_id)).fetchall()
            
            aniv_rows = conn.execute("""
                SELECT id, nombre, apellido, telefono, aniversario_casa, categoria, rol, notas 
                FROM contactos 
                WHERE (aniversario_casa LIKE ? OR SUBSTR(aniversario_casa, 6, 5) = ?) AND agente_id = ?
            """, (f"%{today_md}%", today_md, agente_id)).fetchall()

        cumples_hoy = [dict(r) for r in cumple_rows]
        aniversarios_hoy = [dict(r) for r in aniv_rows]

        # 3. Contactos fríos (>30 días)
        from datetime import timedelta
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if is_super:
            cold_row = conn.execute("""
                SELECT COUNT(*) as cant FROM contactos 
                WHERE (ultimo_contacto < ? OR ultimo_contacto IS NULL OR ultimo_contacto = '') 
                  AND estado_seguimiento = 'activo'
            """, (thirty_days_ago,)).fetchone()
        else:
            cold_row = conn.execute("""
                SELECT COUNT(*) as cant FROM contactos 
                WHERE (ultimo_contacto < ? OR ultimo_contacto IS NULL OR ultimo_contacto = '') 
                  AND estado_seguimiento = 'activo' 
                  AND agente_id = ?
            """, (thirty_days_ago, agente_id)).fetchone()
            
        cold_count = cold_row['cant'] if cold_row else 0

        return {
            'recordatorios_hoy': recordatorios_hoy,
            'cumples_hoy': cumples_hoy,
            'aniversarios_hoy': aniversarios_hoy,
            'cold_count': cold_count
        }
    finally:
        conn.close()

def enviar_morning_briefing_agente(agente_id=None, agente_usuario=None, agente_nombre=None, telefono_override=None, force=False):
    """
    Genera y envía el briefing matutino a un agente específico.
    """
    # Resolver datos del usuario si falta alguno
    if agente_id and (not agente_usuario or not agente_nombre):
        try:
            conn = db.get_db()
            u_row = conn.execute("SELECT id, usuario, nombre_display FROM usuarios WHERE id = ?", (agente_id,)).fetchone()
            conn.close()
            if u_row:
                if not agente_usuario:
                    agente_usuario = u_row['usuario']
                if not agente_nombre:
                    agente_nombre = u_row['nombre_display'] or u_row['usuario']
        except Exception:
            pass
    elif not agente_id and agente_usuario:
        try:
            conn = db.get_db()
            u_row = conn.execute("SELECT id, usuario, nombre_display FROM usuarios WHERE usuario = ?", (agente_usuario,)).fetchone()
            conn.close()
            if u_row:
                agente_id = u_row['id']
                if not agente_nombre:
                    agente_nombre = u_row['nombre_display'] or u_row['usuario']
        except Exception:
            pass

    nombre = agente_nombre or agente_usuario or "Agente"

    # 1. Verificar si el agente tiene el Morning Briefing habilitado por configuración
    if agente_id:
        habilitado_cfg = db.get_config(f'morning_briefing_habilitado_{agente_id}')
        if habilitado_cfg in ('0', 'false', 'False', False) and not force:
            return False, f"El Morning Briefing está deshabilitado para {nombre} en la configuración."

    # 2. Obtener teléfono configurado ESTRICTAMENTE para este agente (sin fallbacks cruzados)
    telefono = telefono_override
    if not telefono:
        if agente_id:
            telefono = db.get_config(f'agente_telefono_{agente_id}')
        if not telefono and (agente_usuario == 'GermanMazza' or agente_id == 4):
            telefono = os.environ.get("SUPERADMIN_PHONE", "+5491161114414")

    # Si no tiene teléfono propio, omitir limpiamente
    if not telefono or not str(telefono).strip():
        return False, f"El agente {nombre} no tiene número de WhatsApp configurado en su perfil."

    # 3. Verificar si ya se envió hoy (a menos que sea forzado / prueba)
    today_str = datetime.now().strftime('%Y-%m-%d')
    cfg_key = f"morning_briefing_last_sent_{agente_id or 'admin'}"
    if not force:
        last_sent = db.get_config(cfg_key)
        if last_sent == today_str:
            return True, f"El briefing de hoy ya fue enviado a {nombre} ({telefono})."

    # Recopilar datos
    datos = recopilar_datos_agente(agente_id, agente_usuario)
    
    # Generar texto con Groq (openai/gpt-oss-20b)
    mensaje = generar_morning_briefing(
        agente_nombre=nombre,
        recordatorios_hoy=datos['recordatorios_hoy'],
        cumples_hoy=datos['cumples_hoy'],
        aniversarios_hoy=datos['aniversarios_hoy'],
        cold_count=datos['cold_count'],
        agente_id=agente_id
    )

    # Disparar envío vía Portal WhatsApp
    success, msg = _enviar_whatsapp_portal(telefono, mensaje)
    if success:
        db.set_config(cfg_key, today_str)
        return True, f"Briefing enviado a {nombre} ({telefono})"
    else:
        return False, msg

def _bucle_cron_morning():
    """
    Bucle en segundo plano que revisa periódicamente la hora.
    A partir de las 08:30 AM, dispara el briefing diario de forma ESCALONADA
    a cada agente inmobiliario comercial activo con pausas de 30 a 60 segundos entre cada uno.
    """
    import random
    print("[MorningBriefing] Iniciando scheduler diario escalonado (8:30 AM)...")
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')
            
            # Chequear si son las 08:30 o posterior (hasta las 09:30) y aún no corrió la ronda global de hoy
            if now.hour == 8 and now.minute >= 30:
                last_global_run = db.get_config('morning_briefing_global_run_date')
                if last_global_run != today_str:
                    print(f"\n[MorningBriefing] ⏰ 8:30 AM detectado. Iniciando ronda escalonada de envíos ({today_str})...")
                    conn = db.get_db()
                    try:
                        # Filtrar roles comerciales y directivos activos, excluyendo finanzas y cuentas de sistema
                        users = conn.execute("""
                            SELECT id, usuario, nombre_display, rol 
                            FROM usuarios 
                            WHERE rol IN ('agente', 'broker', 'admin')
                            ORDER BY id ASC
                        """).fetchall()
                    except Exception:
                        users = []
                    finally:
                        conn.close()

                    if not users:
                        users = [{'id': 4, 'usuario': 'GermanMazza', 'nombre_display': 'German Mazza'}]

                    total_agentes = len(users)
                    print(f"[MorningBriefing] Se evaluarán {total_agentes} agentes comerciales de forma escalonada.")

                    for idx, u in enumerate(users):
                        u_dict = dict(u)
                        u_id = u_dict.get('id')
                        u_name = u_dict.get('nombre_display') or u_dict.get('usuario')
                        try:
                            print(f"\n[MorningBriefing] [{idx + 1}/{total_agentes}] Procesando a {u_name}...")
                            ok, msg = enviar_morning_briefing_agente(
                                agente_id=u_id,
                                agente_usuario=u_dict.get('usuario'),
                                agente_nombre=u_name,
                                force=False
                            )
                            if ok:
                                print(f"[MorningBriefing] [OK] {u_name}: {msg}")
                            else:
                                print(f"[MorningBriefing] [OMITIDO] {u_name}: {msg}")
                        except Exception as e_agent:
                            print(f"[MorningBriefing] [ERROR] Procesando agente {u_name}: {e_agent}")

                        # Pausa escalonada entre agentes solo si fue un envío efectivo
                        if idx < total_agentes - 1:
                            pausa = random.randint(30, 60)
                            time.sleep(pausa)

                    db.set_config('morning_briefing_global_run_date', today_str)
                    print(f"[MorningBriefing] [✓] Ronda escalonada de las 8:30 AM completada con éxito.")

        except Exception as e:
            print(f"[MorningBriefing] Excepción en cron loop: {e}")
            
        time.sleep(30)

_scheduler_iniciado = False
def start_morning_briefing_scheduler():
    """Inicia el hilo del scheduler una sola vez."""
    global _scheduler_iniciado
    if _scheduler_iniciado:
        return
    _scheduler_iniciado = True
    t = threading.Thread(target=_bucle_cron_morning, daemon=True, name="MorningBriefingScheduler")
    t.start()
    print("[MorningBriefing] Thread del scheduler iniciado.")
