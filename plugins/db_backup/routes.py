"""
Routes for Database Backup & Restore Plugin
Protected exclusively for Administrator users.
"""
import os
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from database import db
from modules.auth import admin_required
from .backup_engine import (
    create_backup,
    restore_backup,
    list_backups,
    delete_backup_file,
    get_backup_dir,
    get_active_db_info,
    format_file_size
)

db_backup_bp = Blueprint('db_backup', __name__)

ALLOWED_EXTENSIONS = {'.sql', '.zip', '.db'}

def is_allowed_file(filename):
    _, ext = os.path.splitext(filename)
    return ext.lower() in ALLOWED_EXTENSIONS


@db_backup_bp.route('/admin/backups', methods=['GET'])
@login_required
@admin_required
def admin_backups():
    """Renders the main database backups and restoration dashboard."""
    backups = list_backups()
    db_info = get_active_db_info()
    backup_dir = get_backup_dir()
    
    # Configuration options
    auto_enabled = db.get_config('backup_auto_enabled', '1') == '1'
    interval_hours = int(db.get_config('backup_interval_hours', '6'))
    max_keep = int(db.get_config('backup_max_keep', '30'))
    last_run_str = db.get_config('backup_last_run', None)
    
    # Calculate next scheduled run
    next_run_str = "No programado"
    if auto_enabled and interval_hours > 0:
        if last_run_str:
            try:
                last_dt = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M:%S")
                next_dt = last_dt + timedelta(hours=interval_hours)
                if next_dt < datetime.now():
                    next_run_str = "Pendiente (próximo ciclo)"
                else:
                    next_run_str = next_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                next_run_str = f"En {interval_hours} horas"
        else:
            next_run_str = "Próximo ciclo"

    # Total storage calculation
    total_size_bytes = sum(b['size_bytes'] for b in backups)
    total_size_human = format_file_size(total_size_bytes)

    return render_template(
        'backup_admin.html',
        backups=backups,
        db_info=db_info,
        backup_dir=backup_dir,
        auto_enabled=auto_enabled,
        interval_hours=interval_hours,
        max_keep=max_keep,
        last_run=last_run_str or "Ninguno aún",
        next_run=next_run_str,
        total_backups=len(backups),
        total_size_human=total_size_human
    )


@db_backup_bp.route('/admin/backups/create', methods=['POST'])
@login_required
@admin_required
def manual_backup():
    """Generates an immediate manual backup of the active database."""
    result = create_backup(trigger="manual")
    if result.get("success"):
        flash(f"¡Backup creado con éxito! Archivo: {result['filename']} ({result['size_human']})", "success")
    else:
        flash(f"Error al generar backup: {result.get('error', 'Error desconocido')}", "danger")
    return redirect(url_for('db_backup.admin_backups'))


@db_backup_bp.route('/admin/backups/schedule/save', methods=['POST'])
@login_required
@admin_required
def save_schedule_config():
    """Saves backup schedule periodicity and retention settings."""
    auto_enabled = "1" if request.form.get("backup_auto_enabled") in ["1", "on", "true"] else "0"
    
    interval_hours = request.form.get("backup_interval_hours", "6")
    try:
        interval_hours = str(max(1, int(interval_hours)))
    except (ValueError, TypeError):
        interval_hours = "6"

    max_keep = request.form.get("backup_max_keep", "30")
    try:
        max_keep = str(max(1, int(max_keep)))
    except (ValueError, TypeError):
        max_keep = "30"

    try:
        db.set_config("backup_auto_enabled", auto_enabled)
        db.set_config("backup_interval_hours", interval_hours)
        db.set_config("backup_max_keep", max_keep)
        flash("Configuración de programación de backups guardada correctamente.", "success")
    except Exception as e:
        flash(f"Error al guardar la configuración: {e}", "danger")

    return redirect(url_for('db_backup.admin_backups'))


@db_backup_bp.route('/admin/backups/restore/<path:filename>', methods=['POST'])
@login_required
@admin_required
def restore_backup_route(filename):
    """Triggers database restoration from an existing backup file."""
    safe_name = os.path.basename(filename)
    result = restore_backup(safe_name)
    
    if result.get("success"):
        msg = f"¡Restauración completada con éxito! Se creó un snapshot previo de seguridad ({result.get('snapshot_file')})."
        flash(msg, "success")
    else:
        flash(f"Error al restaurar base de datos: {result.get('error')}", "danger")

    return redirect(url_for('db_backup.admin_backups'))


@db_backup_bp.route('/admin/backups/upload', methods=['POST'])
@login_required
@admin_required
def upload_backup():
    """Uploads an external backup file (.sql or .zip) and optionally restores it."""
    if 'backup_file' not in request.files:
        flash("No se seleccionó ningún archivo.", "warning")
        return redirect(url_for('db_backup.admin_backups'))

    file = request.files['backup_file']
    if file.filename == '':
        flash("El nombre de archivo está vacío.", "warning")
        return redirect(url_for('db_backup.admin_backups'))

    if file and is_allowed_file(file.filename):
        filename = secure_filename(file.filename)
        backup_dir = get_backup_dir()
        target_path = os.path.join(backup_dir, filename)
        
        try:
            file.save(target_path)
            restore_now = request.form.get("restore_immediately") == "1"
            
            if restore_now:
                result = restore_backup(filename)
                if result.get("success"):
                    flash(f"Archivo '{filename}' subido y restaurado exitosamente.", "success")
                else:
                    flash(f"Archivo subido, pero falló la restauración: {result.get('error')}", "danger")
            else:
                flash(f"Archivo de backup '{filename}' subido correctamente al repositorio.", "success")
        except Exception as e:
            flash(f"Error al guardar el archivo: {e}", "danger")
    else:
        flash("Tipo de archivo inválido. Solo se permiten archivos .sql, .zip o .db", "danger")

    return redirect(url_for('db_backup.admin_backups'))


@db_backup_bp.route('/admin/backups/download/<path:filename>')
@login_required
@admin_required
def download_backup(filename):
    """Downloads a backup file to the local client machine."""
    safe_name = os.path.basename(filename)
    backup_dir = get_backup_dir()
    file_path = os.path.join(backup_dir, safe_name)
    
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_file(file_path, as_attachment=True, download_name=safe_name)
    else:
        flash("El archivo solicitado no existe en el servidor.", "danger")
        return redirect(url_for('db_backup.admin_backups'))


@db_backup_bp.route('/admin/backups/delete/<path:filename>', methods=['POST'])
@login_required
@admin_required
def delete_backup(filename):
    """Deletes a backup file from storage."""
    safe_name = os.path.basename(filename)
    if delete_backup_file(safe_name):
        flash(f"Backup '{safe_name}' eliminado correctamente.", "info")
    else:
        flash(f"No se pudo eliminar el backup '{safe_name}'.", "danger")
    return redirect(url_for('db_backup.admin_backups'))


@db_backup_bp.route('/admin/backups/api/status')
@login_required
@admin_required
def api_status():
    """JSON API to fetch live backup metrics."""
    backups = list_backups()
    db_info = get_active_db_info()
    return jsonify({
        "status": "ok",
        "total_backups": len(backups),
        "db_engine": db_info["type"],
        "active_env": db_info.get("env", "local"),
        "last_run": db.get_config("backup_last_run", None),
        "auto_enabled": db.get_config("backup_auto_enabled", "1") == "1",
        "interval_hours": int(db.get_config("backup_interval_hours", "6"))
    })
