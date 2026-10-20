"""
Premium Finance and Operations Blueprint Plugin - AI-Ready & Decoupled
"""
import os
import json
import pandas as pd
from datetime import datetime
from flask import Blueprint, request, render_template, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import db
import database.db_finanzas as db_finanzas
from modules.auth import finanzas_required

finanzas_plugin_bp = Blueprint('finanzas_plugin', __name__)

# --- AUTOMATIC DATABASE MIGRATIONS ON INITIALIZATION ---
def run_migrations():
    """Migrates SQLite tables to add audit columns for AI tracking if not present."""
    conn = db.get_db()
    try:
        conn.execute("ALTER TABLE seguimiento_operaciones ADD COLUMN modificado_por TEXT DEFAULT 'usuario'")
        conn.commit()
    except Exception:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE finanzas_deudas ADD COLUMN modificado_por TEXT DEFAULT 'usuario'")
        conn.commit()
    except Exception:
        pass  # Column already exists
    conn.close()

# Execute migrations on startup
run_migrations()

# --- HELPER LEDGER CALCULATION ---
def calcular_balance_ledger(uid):
    """Calculates details, credits, debits, and balance for an agent ledger."""
    try:
        uid = int(uid)
    except (ValueError, TypeError):
        return None
        
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        # Fetch user
        user = conn.execute("SELECT id, usuario, nombre_display, rol FROM usuarios WHERE id = ?", (uid,)).fetchone()
        if not user:
            return None
            
        # Fetch operations (credits)
        ops = conn.execute("SELECT * FROM seguimiento_operaciones WHERE agente_id = ? ORDER BY fecha_registro DESC", (uid,)).fetchall()
        # Fetch debts (debits)
        deudas = conn.execute("SELECT * FROM finanzas_deudas WHERE agente_id = ? ORDER BY fecha_vencimiento DESC", (uid,)).fetchall()
        
        # Calculations strictly separated by currency
        tot_bruto = sum(float(o['bruto'] or 0.0) for o in ops)
        tot_neto_usd = sum(float(o['neto'] or 0.0) for o in ops)
        com_rendidas_usd = sum(float(o['neto'] or 0.0) for o in ops if o['comision_rendida'] == 1)
        com_pendientes_usd = sum(float(o['neto'] or 0.0) for o in ops if o['comision_rendida'] == 0)
        
        # Debts separated by currency
        deudas_totales_usd = sum(float(d['monto'] or 0.0) for d in deudas if d.get('moneda', 'USD') == 'USD')
        deudas_totales_ars = sum(float(d['monto'] or 0.0) for d in deudas if d.get('moneda') == 'ARS')
        
        deudas_canceladas_usd = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'cancelada' and d.get('moneda', 'USD') == 'USD')
        deudas_canceladas_ars = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'cancelada' and d.get('moneda') == 'ARS')
        
        deudas_pendientes_usd = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'falta' and d.get('moneda', 'USD') == 'USD')
        deudas_pendientes_ars = sum(float(d['monto'] or 0.0) for d in deudas if d['estado'] == 'falta' and d.get('moneda') == 'ARS')
        
        # Saldo Neto Separado por Moneda
        saldo_neto_usd = com_pendientes_usd - deudas_pendientes_usd
        saldo_neto_ars = -deudas_pendientes_ars
        
        return {
            'agente': {
                'id': user['id'],
                'usuario': user['usuario'],
                'nombre_display': user['nombre_display'] or user['usuario'],
                'rol': user['rol']
            },
            'resumen': {
                'comisiones_totales_brutas': tot_bruto,
                'comisiones_totales_netas': tot_neto_usd,
                'comisiones_rendidas': com_rendidas_usd,
                'comisiones_pendientes': com_pendientes_usd,
                'deudas_totales_usd': deudas_totales_usd,
                'deudas_totales_ars': deudas_totales_ars,
                'deudas_canceladas_usd': deudas_canceladas_usd,
                'deudas_canceladas_ars': deudas_canceladas_ars,
                'deudas_pendientes_usd': deudas_pendientes_usd,
                'deudas_pendientes_ars': deudas_pendientes_ars,
                'saldo_neto_usd': saldo_neto_usd,
                'saldo_neto_ars': saldo_neto_ars,
                # Legacy compatibility keys
                'deudas_totales': deudas_totales_usd,
                'deudas_canceladas': deudas_canceladas_usd,
                'deudas_pendientes': deudas_pendientes_usd,
                'saldo_neto': saldo_neto_usd
            },
            'operaciones': [dict(o) for o in ops],
            'deudas': [dict(d) for d in deudas]
        }
    finally:
        conn.close()

# --- WEB HTML ROUTES ---

from modules.auth import privilege_required

@finanzas_plugin_bp.route('/seguimiento_prop')
@login_required
@privilege_required('menu_item', 'seguimiento_prop')
def seguimiento_prop():
    """Sección consolidada de seguimiento de operaciones (Ventas)."""
    if current_user.usuario == 'GermanMazza':
        operaciones = db.get_operaciones()
        agentes = db.get_all_usuarios()
    elif current_user.rol in ['admin', 'broker', 'finanzas'] and getattr(current_user, 'oficina_id', None):
        operaciones = db.get_operaciones(oficina_id=current_user.oficina_id)
        agentes = db.get_all_usuarios(oficina_id=current_user.oficina_id)
    else:
        operaciones = db.get_operaciones(agente_id=current_user.id)
        agentes = []
        
    return render_template('seguimiento_operaciones.html', operaciones=operaciones, agentes=agentes)

@finanzas_plugin_bp.route('/operaciones/guardar', methods=['POST'])
@login_required
def guardar_operacion():
    """Crea o edita una operación de venta."""
    data = request.form.to_dict()
    
    if current_user.rol == 'agente':
        data['agente_id'] = current_user.id
    elif not data.get('agente_id'):
        data['agente_id'] = current_user.id
        
    data['comision_rendida'] = 1 if 'comision_rendida' in request.form else 0
    data['iva_rendido'] = 1 if 'iva_rendido' in request.form else 0
    data['doc_rendida'] = 1 if 'doc_rendida' in request.form else 0
    data['modificado_por'] = current_user.usuario
    
    db.save_operacion(data)
    flash("Operación guardada correctamente.", "success")
    return redirect(url_for('finanzas_plugin.seguimiento_prop'))

@finanzas_plugin_bp.route('/operaciones/borrar/<int:oid>', methods=['POST'])
@login_required
def borrar_operacion(oid):
    """Borra una operación. Agentes solo las suyas."""
    agente_id = current_user.id if current_user.rol == 'agente' else None
    db.delete_operacion(oid, agente_id)
    flash("Operación eliminada.", "info")
    return redirect(url_for('finanzas_plugin.seguimiento_prop'))

@finanzas_plugin_bp.route('/operaciones/importar', methods=['POST'])
@login_required
def importar_operaciones():
    """Step 1: Permite al agente subir su Excel de seguimiento y ver el mapeador de columnas."""
    if 'excel_file' not in request.files:
        flash("No se subió ningún archivo.", "error")
        return redirect(url_for('finanzas_plugin.seguimiento_prop'))
        
    file = request.files['excel_file']
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        flash("Formato no soportado. Debe ser .xlsx, .xls o .csv", "danger")
        return redirect(url_for('finanzas_plugin.seguimiento_prop'))
        
    import secrets
    from flask import current_app
    
    temp_filename = f"fin_import_{current_user.id}_{secrets.token_hex(4)}_{file.filename}"
    temp_path = os.path.join(current_app.root_path, 'scratch', temp_filename)
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    file.save(temp_path)
    
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(temp_path, nrows=0)
        else:
            df = pd.read_excel(temp_path, nrows=0)
            
        headers = df.columns.tolist()
        return render_template('finanzas_importador.html', headers=headers, temp_filename=temp_filename)
        
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        flash(f"Error al leer el archivo: {e}", "danger")
        return redirect(url_for('finanzas_plugin.seguimiento_prop'))

@finanzas_plugin_bp.route('/operaciones/importar/procesar', methods=['POST'])
@login_required
def procesar_importacion_operaciones():
    """Step 2: Procesa el archivo Excel completo usando el mapeo de columnas del formulario."""
    from flask import current_app
    temp_filename = request.form.get('temp_filename')
    temp_path = os.path.join(current_app.root_path, 'scratch', temp_filename)
    
    if not os.path.exists(temp_path):
        flash("El archivo temporal expiró o no existe.", "danger")
        return redirect(url_for('finanzas_plugin.seguimiento_prop'))
        
    # Get mapped fields from POST
    mapping = {
        'domicilio': request.form.get('mapping_domicilio'),
        'juris': request.form.get('mapping_juris'),
        'puntas': request.form.get('mapping_puntas'),
        'porcentaje': request.form.get('mapping_porcentaje'),
        'mes': request.form.get('mapping_mes'),
        'colaborador': request.form.get('mapping_colaborador'),
        'cierre': request.form.get('mapping_cierre'),
        'bruto': request.form.get('mapping_bruto'),
        'neto': request.form.get('mapping_neto'),
        'pago': request.form.get('mapping_pago'),
        'informes': request.form.get('mapping_informes'),
        'estado_parc': request.form.get('mapping_estado_parc'),
        'refuerzo': request.form.get('mapping_refuerzo'),
        'sucesion': request.form.get('mapping_sucesion'),
        'doc_escribania': request.form.get('mapping_doc_escribania'),
        'proforma': request.form.get('mapping_proforma'),
        'ad_ref_comp': request.form.get('mapping_ad_ref_comp'),
        'ad_ref_vend': request.form.get('mapping_ad_ref_vend'),
        'fecha_reserva': request.form.get('mapping_fecha_reserva'),
        'fecha_firma': request.form.get('mapping_fecha_firma'),
        'particularidades': request.form.get('mapping_particularidades'),
        'estado': request.form.get('mapping_estado')
    }
    
    try:
        if temp_filename.endswith('.csv'):
            df = pd.read_csv(temp_path)
        else:
            df = pd.read_excel(temp_path)
            
        count = 0
        for _, row in df.iterrows():
            dom_col = mapping.get('domicilio')
            if not dom_col or pd.isnull(row.get(dom_col)):
                continue
                
            domicilio = str(row.get(dom_col, '')).strip()
            if not domicilio or domicilio.lower() in ['nan', '', 'domicilio', 'elegir', 'elegir...', 'seleccionar'] or len(domicilio) < 5:
                continue
                
            item = {
                'agente_id': current_user.id,
                'modificado_por': current_user.usuario
            }
            
            for db_col, excel_col in mapping.items():
                if excel_col and excel_col in df.columns:
                    val = row[excel_col]
                    if hasattr(val, 'isoformat') and pd.notna(val):
                        val = str(val.isoformat())[:10] if len(str(val)) > 10 else str(val.isoformat())
                    
                    if db_col in ['bruto', 'neto', 'porcentaje'] and pd.notna(val):
                        try:
                            val_str = str(val).replace('$', '').replace(',', '').replace(' ', '').strip()
                            val = float(val_str) if val_str else 0.0
                        except:
                            val = 0.0
                    
                    if db_col in ['puntas', 'refuerzo'] and pd.notna(val):
                        val = str(val).strip()
                        
                    item[db_col] = val if pd.notna(val) else None
                    
            db.save_operacion(item)
            count += 1
            
        os.remove(temp_path)
        flash(f"Se importaron {count} operaciones con éxito.", "success")
        
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        flash(f"Error al procesar la importación: {e}", "danger")
        
    return redirect(url_for('finanzas_plugin.seguimiento_prop'))

@finanzas_plugin_bp.route('/finanzas')
@login_required
@privilege_required('menu_item', 'finanzas_oficina')
def finanzas_oficina():
    """Panel de deudas y pagos de oficina."""
    # Solo agents are blocked from office finances
    if not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza':
        flash("El módulo de Finanzas de Oficina está disponible únicamente para oficinas y equipos habilitados.", "warning")
        return redirect(url_for('index'))
        
    if current_user.usuario == 'GermanMazza':
        deudas = db.get_deudas()
        usuarios = db.get_all_usuarios()
    elif current_user.rol in ['admin', 'broker', 'finanzas'] and getattr(current_user, 'oficina_id', None):
        deudas = db.get_deudas(oficina_id=current_user.oficina_id)
        usuarios = db.get_all_usuarios(oficina_id=current_user.oficina_id)
    else:
        deudas = db.get_deudas(agente_id=current_user.id)
        usuarios = []
    
    configs = {}
    if current_user.rol in ['admin', 'broker', 'finanzas'] or current_user.usuario == 'GermanMazza':
        for u in usuarios:
            c = db.get_config_deuda_agente(u['id'])
            c['conceptos'] = json.loads(c.get('otros_gastos_json', '[]'))
            configs[u['id']] = c
            
    return render_template('finanzas_oficina.html', deudas=deudas, usuarios=usuarios, configs=configs)

@finanzas_plugin_bp.route('/finanzas/config_agente', methods=['POST'])
@finanzas_required
def guardar_config_finanzas():
    """Guarda los conceptos recurrentes de un agente (JSON)."""
    nombres = request.form.getlist('concepto[]')
    montos = request.form.getlist('monto[]')
    monedas = request.form.getlist('moneda[]')
    
    conceptos = []
    for i in range(len(nombres)):
        if nombres[i] and montos[i]:
            conceptos.append({
                'nombre': nombres[i],
                'monto': float(montos[i]),
                'moneda': monedas[i]
            })
    
    data = {
        'agente_id': request.form.get('agente_id'),
        'monto_oficina': 0,
        'moneda_oficina': 'USD',
        'otros_gastos_json': json.dumps(conceptos) 
    }
    db.save_config_deuda_agente(data)
    flash("Configuración de gastos fijos actualizada.", "success")
    return redirect(url_for('finanzas_plugin.finanzas_oficina'))

@finanzas_plugin_bp.route('/finanzas/generar_mes/<int:uid>', methods=['POST'])
@finanzas_required
def generar_mes_agente(uid):
    """Genera las deudas recurrentes para el mes actual para un agente específico."""
    config = db.get_config_deuda_agente(uid)
    conceptos = json.loads(config.get('otros_gastos_json', '[]'))
    
    if not conceptos:
        flash("El agente no tiene conceptos recurrentes configurados.", "warning")
        return redirect(url_for('finanzas_plugin.finanzas_oficina'))
        
    now = datetime.now()
    mes_anio = now.strftime('%m-%Y')
    count = 0
    
    for c in conceptos:
        descripcion = f"{c['nombre']} - {mes_anio}"
        
        existentes = db.get_deudas(uid)
        if not any(d['descripcion'] == descripcion for d in existentes):
            db.save_deuda({
                'agente_id': uid,
                'descripcion': descripcion,
                'monto': c['monto'],
                'moneda': c['moneda'],
                'fecha_vencimiento': now.strftime('%Y-%m-%d'),
                'estado': 'falta',
                'tipo': 'mensual',
                'modificado_por': current_user.usuario
            })
            count += 1
            
    if count > 0:
        flash(f"Se generaron {count} cargos para el mes {mes_anio}.", "success")
    else:
        flash("Los cargos para este mes ya estaban generados.", "info")
        
    return redirect(url_for('finanzas_plugin.finanzas_oficina'))

@finanzas_plugin_bp.route('/finanzas/asignar_puntual', methods=['POST'])
@finanzas_required
def asignar_deuda_puntual():
    """Asigna una deuda única (ej: Fondo de publicidad)."""
    data = {
        'agente_id': request.form.get('agente_id'),
        'descripcion': request.form.get('descripcion'),
        'monto': request.form.get('monto'),
        'moneda': request.form.get('moneda'),
        'fecha_vencimiento': request.form.get('fecha_vencimiento'),
        'estado': 'falta',
        'tipo': 'puntual',
        'modificado_por': current_user.usuario
    }
    db.save_deuda(data)
    flash("Deuda puntual asignada con éxito.", "success")
    return redirect(url_for('finanzas_plugin.finanzas_oficina'))

@finanzas_plugin_bp.route('/finanzas/toggle_estado/<int:did>', methods=['POST'])
@finanzas_required
def toggle_estado_deuda(did):
    """Cambia entre 'falta' y 'cancelada'."""
    deudas = db.get_deudas()
    deuda = next((d for d in deudas if d['id'] == did), None)
    if deuda:
        nuevo_estado = 'cancelada' if deuda['estado'] == 'falta' else 'falta'
        deuda['estado'] = nuevo_estado
        deuda['modificado_por'] = current_user.usuario
        db.save_deuda(deuda)
        return jsonify({'success': True, 'nuevo_estado': nuevo_estado})
    return jsonify({'success': False}), 404

@finanzas_plugin_bp.route('/finanzas/operacion/toggle_control/<int:oid>/<string:campo>', methods=['POST'])
@finanzas_required
def toggle_control_operacion(oid, campo):
    """Toggles comision_rendida, iva_rendido, or doc_rendida status for an operation."""
    if campo not in ['comision_rendida', 'iva_rendido', 'doc_rendida']:
        return jsonify({'success': False, 'error': 'Campo no válido'}), 400
        
    conn = db.get_db(db.MASTER_DB_PATH)
    try:
        op = conn.execute("SELECT * FROM seguimiento_operaciones WHERE id = ?", (oid,)).fetchone()
        if not op:
            return jsonify({'success': False, 'error': 'Operación no encontrada'}), 404
            
        current_val = op[campo]
        nuevo_val = 1 if current_val == 0 else 0
        
        conn.execute(
            f"UPDATE seguimiento_operaciones SET {campo} = ?, modificado_por = ? WHERE id = ?",
            (nuevo_val, current_user.usuario, oid)
        )
        conn.commit()
        return jsonify({'success': True, 'nuevo_valor': nuevo_val})
    finally:
        conn.close()


# --- LIBRO DE FINANZAS & ERP MULTI-SUCURSAL (PROFESIONAL) ---

@finanzas_plugin_bp.route('/finanzas/libro')
@login_required
@privilege_required('menu_item', 'libro_finanzas')
def libro_finanzas():
    """
    Panel ERP Financiero Profesional de Sucursal (Defontana-Style).
    Incluye P&L, Cuentas Corrientes, Cajas/Bancos y Cuentas por Pagar (OPEX).
    """
    # 1. Regla de Aislamiento Estricto: Agentes Sueltos NO tienen acceso
    if not getattr(current_user, 'oficina_id', None) and current_user.usuario != 'GermanMazza':
        flash("El Libro de Finanzas está reservado para Administradores de Oficina y SuperAdmin.", "warning")
        return redirect(url_for('index'))

    # 2. Determinar oficina objetivo
    if current_user.usuario == 'GermanMazza':
        oficinas = db.get_all_oficinas()
        target_oficina_id = request.args.get('oficina_id', current_user.oficina_id or (oficinas[0]['id'] if oficinas else 1))
        try:
            target_oficina_id = int(target_oficina_id)
        except (ValueError, TypeError):
            target_oficina_id = 1
    else:
        oficinas = []
        target_oficina_id = current_user.oficina_id

    # 3. Calcular Balance General y P&L de la Oficina
    balance_oficina = db_finanzas.calcular_balance_oficina(target_oficina_id)

    # 4. Obtener Cajas, Proveedores, Gastos OPEX y Movimientos
    cajas = db_finanzas.get_cajas_bancos(target_oficina_id)
    proveedores = db_finanzas.get_proveedores(target_oficina_id)
    gastos_opex = db_finanzas.get_gastos_opex(target_oficina_id)
    movimientos_caja = db_finanzas.get_movimientos_caja(target_oficina_id, limit=50)

    # 5. Cuentas Corrientes de Agentes (Sub-módulo)
    usuarios_oficina = db.get_all_usuarios(oficina_id=target_oficina_id) if target_oficina_id else []
    target_agente_id = request.args.get('agente_id')
    if not target_agente_id and usuarios_oficina:
        target_agente_id = usuarios_oficina[0]['id']
    elif not target_agente_id:
        target_agente_id = current_user.id

    try:
        target_agente_id = int(target_agente_id)
    except (ValueError, TypeError):
        target_agente_id = current_user.id

    balance_agente = calcular_balance_ledger(target_agente_id)

    return render_template(
        'libro_finanzas.html',
        balance_oficina=balance_oficina,
        cajas=cajas,
        proveedores=proveedores,
        gastos_opex=gastos_opex,
        movimientos_caja=movimientos_caja,
        usuarios=usuarios_oficina,
        balance_agente=balance_agente,
        target_agente_id=target_agente_id,
        target_oficina_id=target_oficina_id,
        oficinas=oficinas,
        active_tab=request.args.get('tab', 'pnl')
    )

# ==========================================
# --- CRUD: GASTOS OPEX (CUENTAS POR PAGAR)
# ==========================================

@finanzas_plugin_bp.route('/finanzas/gasto/guardar', methods=['POST'])
@login_required
@finanzas_required
def guardar_gasto_opex():
    """Crea o edita un gasto operativo (OPEX) para la oficina del usuario."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else request.form.get('oficina_id', current_user.oficina_id or 1)
    
    data = {
        'id': request.form.get('id'),
        'oficina_id': oficina_id,
        'proveedor_id': request.form.get('proveedor_id') or None,
        'descripcion': request.form.get('descripcion'),
        'categoria': request.form.get('categoria', 'operativo'),
        'monto': request.form.get('monto'),
        'moneda': request.form.get('moneda', 'ARS'),
        'tipo_cambio': request.form.get('tipo_cambio', 1.0),
        'fecha_emision': request.form.get('fecha_emision'),
        'fecha_vencimiento': request.form.get('fecha_vencimiento'),
        'estado': request.form.get('estado', 'pendiente'),
        'caja_id': request.form.get('caja_id') or None,
        'notas': request.form.get('notas'),
        'modificado_por': current_user.usuario
    }
    
    gid = db_finanzas.save_gasto_opex(data)
    if gid:
        flash("Gasto operativo registrado con éxito.", "success")
    else:
        flash("Error al registrar el gasto operativo.", "danger")
        
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='opex', oficina_id=oficina_id))

@finanzas_plugin_bp.route('/finanzas/gasto/pagar/<int:gid>', methods=['POST'])
@login_required
@finanzas_required
def pagar_gasto(gid):
    """Marca un gasto como pagado debitando de la caja seleccionada."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else request.form.get('oficina_id', current_user.oficina_id or 1)
    caja_id = request.form.get('caja_id')
    
    if not caja_id:
        flash("Debes seleccionar una cuenta o caja de origen para pagar.", "warning")
        return redirect(url_for('finanzas_plugin.libro_finanzas', tab='opex', oficina_id=oficina_id))
        
    success = db_finanzas.pagar_gasto_opex(gid, caja_id, oficina_id, modificado_por=current_user.usuario)
    if success:
        flash("Factura/Gasto pagado y debitado de caja correctamente.", "success")
    else:
        flash("No se pudo procesar el pago.", "danger")
        
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='opex', oficina_id=oficina_id))

@finanzas_plugin_bp.route('/finanzas/gasto/borrar/<int:gid>', methods=['POST'])
@login_required
@finanzas_required
def borrar_gasto(gid):
    """Elimina un gasto operativo."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else None
    db_finanzas.delete_gasto_opex(gid, oficina_id)
    flash("Gasto eliminado.", "info")
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='opex'))

# ==========================================
# --- CRUD: PROVEEDORES
# ==========================================

@finanzas_plugin_bp.route('/finanzas/proveedor/guardar', methods=['POST'])
@login_required
@finanzas_required
def guardar_proveedor():
    """Crea o edita un proveedor para la sucursal."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else request.form.get('oficina_id', current_user.oficina_id or 1)
    data = {
        'id': request.form.get('id'),
        'oficina_id': oficina_id,
        'nombre': request.form.get('nombre'),
        'cuit_rut': request.form.get('cuit_rut'),
        'rubro': request.form.get('rubro', 'General'),
        'contacto': request.form.get('contacto'),
        'telefono': request.form.get('telefono'),
        'email': request.form.get('email')
    }
    pid = db_finanzas.save_proveedor(data)
    if pid:
        flash("Proveedor guardado exitosamente.", "success")
    else:
        flash("Error al guardar proveedor.", "danger")
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='opex', oficina_id=oficina_id))

@finanzas_plugin_bp.route('/finanzas/proveedor/borrar/<int:pid>', methods=['POST'])
@login_required
@finanzas_required
def borrar_proveedor(pid):
    """Elimina un proveedor."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else None
    db_finanzas.delete_proveedor(pid, oficina_id)
    flash("Proveedor eliminado.", "info")
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='opex'))

# ==========================================
# --- CRUD: CAJAS Y BANCOS (TESORERÍA)
# ==========================================

@finanzas_plugin_bp.route('/finanzas/caja/guardar', methods=['POST'])
@login_required
@finanzas_required
def guardar_caja():
    """Crea o edita una caja o cuenta bancaria."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else request.form.get('oficina_id', current_user.oficina_id or 1)
    data = {
        'id': request.form.get('id'),
        'oficina_id': oficina_id,
        'nombre': request.form.get('nombre'),
        'tipo': request.form.get('tipo', 'caja_efectivo'),
        'moneda': request.form.get('moneda', 'USD'),
        'saldo_inicial': request.form.get('saldo_inicial', 0.0),
        'activa': 1
    }
    cid = db_finanzas.save_caja_banco(data)
    if cid:
        flash("Cuenta / Caja registrada correctamente.", "success")
    else:
        flash("Error al registrar cuenta.", "danger")
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='tesoreria', oficina_id=oficina_id))

@finanzas_plugin_bp.route('/finanzas/caja/movimiento', methods=['POST'])
@login_required
@finanzas_required
def registrar_movimiento():
    """Registra un movimiento manual de tesorería (ingreso, egreso, ajuste) con conversión de moneda."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else request.form.get('oficina_id', current_user.oficina_id or 1)
    data = {
        'oficina_id': oficina_id,
        'caja_id': request.form.get('caja_id'),
        'tipo_movimiento': request.form.get('tipo_movimiento', 'ingreso'),
        'origen': 'ajuste_manual',
        'monto': request.form.get('monto'),
        'moneda': request.form.get('moneda', 'USD'),
        'tipo_cambio': request.form.get('tipo_cambio', 1.0),
        'descripcion': request.form.get('descripcion'),
        'modificado_por': current_user.usuario
    }
    mid = db_finanzas.registrar_movimiento_caja(data)
    if mid:
        flash("Movimiento de tesorería registrado correctamente.", "success")
    else:
        flash("Error al registrar movimiento.", "danger")
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='tesoreria', oficina_id=oficina_id))

@finanzas_plugin_bp.route('/finanzas/caja/movimiento/borrar/<int:mid>', methods=['POST'])
@login_required
@finanzas_required
def borrar_movimiento(mid):
    """Elimina un movimiento de tesorería."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else None
    db_finanzas.delete_movimiento_caja(mid, oficina_id)
    flash("Movimiento eliminado de tesorería.", "info")
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='tesoreria'))

@finanzas_plugin_bp.route('/finanzas/caja/borrar/<int:cid>', methods=['POST'])
@login_required
@finanzas_required
def borrar_caja(cid):
    """Desactiva una caja."""
    oficina_id = current_user.oficina_id if current_user.usuario != 'GermanMazza' else None
    db_finanzas.delete_caja_banco(cid, oficina_id)
    flash("Caja desactivada.", "info")
    return redirect(url_for('finanzas_plugin.libro_finanzas', tab='tesoreria'))

# ==========================================
# --- RESTful JSON APIs (AI-READY) ---
# ==========================================

@finanzas_plugin_bp.route('/api/finanzas/libro/<int:agente_id>', methods=['GET'])
@login_required
def api_get_libro(agente_id):
    """API Endpoint to fetch consolidated Ledger for an agent."""
    if current_user.usuario != 'GermanMazza' and current_user.rol not in ('admin', 'broker'):
        return jsonify({'success': False, 'error': 'Unauthorized.'}), 403
        
    balance_data = calcular_balance_ledger(agente_id)
    if not balance_data:
        return jsonify({'success': False, 'error': f'Agent {agente_id} not found.'}), 404
        
    return jsonify({
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'data': balance_data
    })

@finanzas_plugin_bp.route('/api/finanzas/oficina/<int:oficina_id>', methods=['GET'])
@login_required
def api_get_balance_oficina(oficina_id):
    """API Endpoint to fetch office P&L and financial metrics."""
    if current_user.usuario != 'GermanMazza' and current_user.oficina_id != oficina_id:
        return jsonify({'success': False, 'error': 'Unauthorized office access.'}), 403
        
    data = db_finanzas.calcular_balance_oficina(oficina_id)
    return jsonify({
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'oficina_id': oficina_id,
        'data': data
    })

@finanzas_plugin_bp.route('/api/finanzas/operacion/guardar', methods=['POST'])
@login_required
def api_save_operacion():
    """API Endpoint to create or edit a Sales Operation programmatically."""
    if current_user.rol == 'agente':
        target_agent = current_user.id
    else:
        target_agent = request.json.get('agente_id') or current_user.id

    data = {
        'id': request.json.get('id'),
        'agente_id': target_agent,
        'domicilio': request.json.get('domicilio', '').strip(),
        'bruto': float(request.json.get('bruto') or 0.0),
        'neto': float(request.json.get('neto') or 0.0),
        'comision_rendida': int(request.json.get('comision_rendida') or 0),
        'iva_rendido': int(request.json.get('iva_rendido') or 0),
        'doc_rendida': int(request.json.get('doc_rendida') or 0),
        'mes': request.json.get('mes', datetime.now().strftime('%m-%Y')),
        'colaborador': request.json.get('colaborador'),
        'particularidades': request.json.get('particularidades'),
        'estado': request.json.get('estado', 'cierre'),
        'modificado_por': request.json.get('modificado_por', 'AI_Agent')
    }
    
    if not data['domicilio']:
        return jsonify({'success': False, 'error': 'Field \'domicilio\' is required.'}), 400
        
    db_finanzas.save_operacion(data)
    return jsonify({
        'success': True,
        'message': 'Operation saved successfully in ledger.',
        'data': data
    })

@finanzas_plugin_bp.route('/api/finanzas/deuda/guardar', methods=['POST'])
@login_required
def api_save_deuda():
    """API Endpoint to assign or modify a Debt (debit) to an agent."""
    if current_user.rol == 'agente':
        return jsonify({'success': False, 'error': 'Unauthorized.'}), 403
        
    data = {
        'id': request.json.get('id'),
        'agente_id': int(request.json.get('agente_id')),
        'descripcion': request.json.get('descripcion', '').strip(),
        'monto': float(request.json.get('monto') or 0.0),
        'moneda': request.json.get('moneda', 'USD').upper(),
        'fecha_vencimiento': request.json.get('fecha_vencimiento', datetime.now().strftime('%Y-%m-%d')),
        'estado': request.json.get('estado', 'falta'),
        'tipo': request.json.get('tipo', 'puntual'),
        'modificado_por': request.json.get('modificado_por', 'AI_Agent')
    }
    
    if not data['descripcion'] or not data['agente_id']:
        return jsonify({'success': False, 'error': 'Fields \'agente_id\' and \'descripcion\' are required.'}), 400
        
    db_finanzas.save_deuda(data)
    return jsonify({
        'success': True,
        'message': 'Debt registered successfully.',
        'data': data
    })

