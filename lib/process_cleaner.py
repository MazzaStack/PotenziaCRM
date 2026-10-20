"""
process_cleaner.py - Limpiador quirúrgico de procesos zombis del CRM.

Garantiza que NUNCA se toquen procesos de Claudia, ngrok, VSCode, PostgreSQL
ni ninguna otra aplicación ajena al CRM.
"""

import os
import sys
import subprocess
import json
import logging

logger = logging.getLogger("process_cleaner")

# Palabras clave PROHIBIDAS (si la línea de comando tiene alguna de estas, JAMÁS SE TOCA)
PROTECTED_KEYWORDS = [
    'claudia', 'claude', 'ngrok', 'antigravity', 'gemini', 'cursor', 
    'vscode', 'postgres', 'pg_', 'ollama', 'code.exe', 'powershell', 'cmd.exe'
]

# Palabras clave que identifican procesos huérfanos del CRM
CRM_KEYWORDS = [
    'whatsapp_node',
    'wa_linker.js',
    'ephemeral_sender.js',
    'wwebjs_sender.js',
    'whatsapp_sender.py'
]

def purge_crm_zombie_processes(exclude_current=True, kill_workers_only=False):
    """
    Inspecciona todos los procesos node.exe y python.exe del sistema y
    elimina quirúrgicamente ÚNICAMENTE los procesos que pertenecen al CRM.
    
    Retorna una lista de dicts con info de los procesos eliminados.
    """
    if os.name != 'nt':
        return []

    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, 'getppid') else None
    
    crm_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..')).lower()

    # Comando PowerShell para obtener procesos node.exe y python.exe con su CommandLine
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name = 'node.exe' or Name = 'python.exe'\" "
        "| Select-Object ProcessId, Name, CommandLine | ConvertTo-Json -Compress"
    )
    
    killed = []

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=0x08000000
        )
        
        raw_json = res.stdout.strip()
        if not raw_json:
            return []
            
        try:
            data = json.loads(raw_json)
        except Exception:
            return []

        if isinstance(data, dict):
            processes = [data]
        elif isinstance(data, list):
            processes = data
        else:
            processes = []

        for proc in processes:
            pid = proc.get('ProcessId')
            name = (proc.get('Name') or '').lower()
            cmdline = (proc.get('CommandLine') or '').lower()

            if not pid or not cmdline:
                continue

            # 1. No matar el proceso actual de Flask ni su padre
            if exclude_current and (pid == current_pid or pid == parent_pid):
                continue

            # 2. PROTECCIÓN ESTRICTA: Si contiene alguna palabra protegida (Claudia, ngrok, etc.), SALTAR
            if any(prot in cmdline for prot in PROTECTED_KEYWORDS):
                continue

            # 3. Detectar si es un proceso del CRM
            is_crm_target = False
            target_reason = ""

            # Caso A: Subprocesos de WhatsApp Node
            if name == 'node.exe' and any(kw in cmdline for kw in ['whatsapp_node', 'wa_linker.js', 'ephemeral_sender.js', 'wwebjs_sender.js']):
                is_crm_target = True
                target_reason = "WhatsApp Node Subprocess"

            # Caso B: Worker de WhatsApp Python
            elif name == 'python.exe' and 'whatsapp_sender.py' in cmdline:
                is_crm_target = True
                target_reason = "WhatsApp Python Worker"

            # Caso C: Instancias viejas de app.py corriendo desde esta misma carpeta del CRM
            elif not kill_workers_only and name == 'python.exe' and 'app.py' in cmdline and crm_root in cmdline:
                is_crm_target = True
                target_reason = "Stale Flask Instance"

            if is_crm_target:
                try:
                    # Matar quirúrgicamente solo este PID
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=4, creationflags=0x08000000)
                    killed.append({
                        "pid": pid,
                        "name": name,
                        "reason": target_reason,
                        "cmd": cmdline[:120]
                    })
                    logger.info(f"[ProcessCleaner] Purgado {name} PID {pid} ({target_reason})")
                except Exception as e:
                    logger.warning(f"[ProcessCleaner] Error al matar PID {pid}: {e}")

    except Exception as e:
        logger.error(f"[ProcessCleaner] Error general en escaneo de procesos: {e}")

    return killed

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print("Ejecutando limpieza quirúrgica de prueba...")
    res = purge_crm_zombie_processes(exclude_current=True)
    print(f"Procesos purgados: {len(res)}")
    for r in res:
        print(f" - PID {r['pid']} ({r['name']}): {r['reason']}")
