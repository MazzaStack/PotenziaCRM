-- Captador de Propiedades - PostgreSQL Database Schema

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS oficinas (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    direccion TEXT,
    telefono TEXT,
    logo_url TEXT,
    color_primario TEXT DEFAULT '#0d6efd',
    color_secundario TEXT DEFAULT '#1a1a2e',
    es_portal_clientes INTEGER DEFAULT 0,
    activa INTEGER DEFAULT 1,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    usuario TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    nombre_display TEXT,
    rol TEXT DEFAULT 'agente',          -- admin, broker, agente, finanzas
    db_file TEXT,                       -- Archivo sqlite (legacy)
    oficina_id INTEGER REFERENCES oficinas(id) ON DELETE SET NULL,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS busquedas (
    id SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL,
    portal TEXT NOT NULL,               -- zonaprop, argenprop, mercadolibre
    url_busqueda TEXT NOT NULL,         -- URL prearmada del portal con filtros
    activa INTEGER DEFAULT 1,
    frecuencia_minutos INTEGER DEFAULT 60,
    ultima_ejecucion TIMESTAMP,
    propiedades_encontradas INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS propiedades (
    id SERIAL PRIMARY KEY,
    portal TEXT NOT NULL,               -- zonaprop, argenprop, mercadolibre
    url TEXT NOT NULL UNIQUE,
    titulo TEXT,
    precio DOUBLE PRECISION,
    moneda TEXT DEFAULT 'USD',          -- USD, ARS
    direccion TEXT,
    barrio TEXT,
    ciudad TEXT,
    m2_total DOUBLE PRECISION,
    m2_cubiertos DOUBLE PRECISION,
    ambientes INTEGER,
    dormitorios INTEGER,
    banos INTEGER,
    tipo_propiedad TEXT,                -- departamento, casa, ph, terreno, local, oficina
    tipo_operacion TEXT DEFAULT 'venta', -- venta, alquiler
    nombre_contacto TEXT,
    telefono TEXT,
    email_contacto TEXT,
    descripcion TEXT,
    foto_url TEXT,
    fecha_publicacion TEXT,
    fecha_captacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    estado TEXT DEFAULT 'nueva',        -- nueva, contactada, en_seguimiento, captada, descartada
    notas TEXT,
    puntaje INTEGER DEFAULT 0,          -- 0-5 prioridad manual del agente
    busqueda_id INTEGER REFERENCES busquedas(id) ON DELETE SET NULL,
    lat DOUBLE PRECISION,               -- Latitud para mapas
    lng DOUBLE PRECISION,               -- Longitud para mapas
    antiguedad INTEGER,
    cocheras INTEGER DEFAULT 0,
    toilettes INTEGER DEFAULT 0,
    orientacion TEXT,
    disposicion TEXT,
    estado_conservacion TEXT,
    fotos_json TEXT,
    agente_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS comunicaciones (
    id SERIAL PRIMARY KEY,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,                 -- email, whatsapp, llamada
    mensaje TEXT,
    asunto TEXT,                        -- solo para emails
    fecha_programada TEXT,
    fecha_enviada TEXT,
    estado TEXT DEFAULT 'pendiente',    -- pendiente, enviada, respondida
    paso INTEGER DEFAULT 1,
    estrategia_usada TEXT
);

-- ==========================================
-- AUTOMATIZACIÓN E IA
-- ==========================================

CREATE TABLE IF NOT EXISTS cola_mensajes (
    id SERIAL PRIMARY KEY,
    propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL DEFAULT 'whatsapp',
    estrategia TEXT NOT NULL,           -- marketing, red_ferrari
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    estado TEXT DEFAULT 'pendiente',    -- pendiente, enviado, error
    error_log TEXT
);

CREATE TABLE IF NOT EXISTS estadisticas_ia (
    estrategia TEXT PRIMARY KEY,        -- marketing, red_ferrari
    enviados INTEGER DEFAULT 0,
    respuestas INTEGER DEFAULT 0
);

-- ==========================================
-- CRM: CONTACTOS Y SEGURIDAD
-- ==========================================

CREATE TABLE IF NOT EXISTS archivos_asignados (
    id SERIAL PRIMARY KEY,
    nombre_archivo TEXT NOT NULL,
    ruta_archivo TEXT NOT NULL,
    asignado_a INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    asignado_por INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    fecha_asignado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    leido INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contactos (
    id SERIAL PRIMARY KEY,
    nombre TEXT,
    apellido TEXT,
    calificacion INTEGER DEFAULT 0,            -- 1 a 5 estrellas
    categoria TEXT DEFAULT 'C',          -- A, B, C, D
    ultimo_contacto TEXT,              -- Fecha YYYY-MM-DD
    fecha_nacimiento TEXT,             -- Fecha YYYY-MM-DD
    aniversario_casa TEXT,             -- Fecha YYYY-MM-DD
    rol TEXT,                          -- Comprador, Vendedor, Colega, Otros
    referente TEXT,                    -- Quién lo recomendó
    notas TEXT,                                -- Comentarios/Historial
    notes TEXT,                        -- Legacy note field (compatibility)
    telefono TEXT UNIQUE,              -- Para WhatsApp directo
    email TEXT,
    busqueda_activa INTEGER DEFAULT 0,         -- 1 = Si
    filtros_busqueda_json TEXT,                -- Para "Búsqueda Inversa" con IA
    estado_seguimiento TEXT DEFAULT 'activo',
    fecha_recarga TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    campos_personalizados_json TEXT,           -- Para columnas elásticas del agente
    mac INTEGER DEFAULT 0,                     -- 1 si viene del Meta AI Chatbot
    intencion_ia TEXT,                 -- Resumen de la intención detectada por la IA
    recordatorio_activo INTEGER DEFAULT 0,
    recordatorio_dias INTEGER,
    recordatorio_fecha TEXT,
    agente_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS lista_negra (
    id SERIAL PRIMARY KEY,
    telefono TEXT UNIQUE NOT NULL,
    motivo TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tareas_diarias_estado (
    fecha TEXT NOT NULL,                -- YYYY-MM-DD
    agente_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    historias_ig_wa INTEGER DEFAULT 0,
    lanzar_lote_5_5 INTEGER DEFAULT 0,
    automatizacion_diaria INTEGER DEFAULT 0,
    mantenimiento_base INTEGER DEFAULT 0,
    historias_posteadas INTEGER DEFAULT 0,
    lote_enviado INTEGER DEFAULT 0,
    PRIMARY KEY (fecha, agente_id)
);

CREATE TABLE IF NOT EXISTS tasaciones_logs (
    id SERIAL PRIMARY KEY,
    tipo_operacion TEXT,                -- alquiler, venta, temporal
    tipo_propiedad TEXT,                -- casa, depto, etc
    metros_cubiertos DOUBLE PRECISION,
    metros_totales DOUBLE PRECISION,
    ambientes INTEGER,
    habitaciones INTEGER,
    zona TEXT,
    precio_bajo DOUBLE PRECISION,
    precio_medio DOUBLE PRECISION,
    precio_alto DOUBLE PRECISION,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS planificador_mensajes (
    semana INTEGER PRIMARY KEY,
    mensaje TEXT,
    habilitado INTEGER DEFAULT 0
);

-- ==========================================
-- SISTEMA BROKER Y FINANZAS
-- ==========================================

CREATE TABLE IF NOT EXISTS seguimiento_operaciones (
    id SERIAL PRIMARY KEY,
    agente_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    comision_rendida INTEGER DEFAULT 0,
    iva_rendido INTEGER DEFAULT 0,
    doc_rendida INTEGER DEFAULT 0,
    domicilio TEXT,
    juris TEXT,
    puntas TEXT,
    porcentaje DOUBLE PRECISION,
    cierre TEXT,
    bruto DOUBLE PRECISION,
    neto DOUBLE PRECISION,
    pago TEXT,
    informes TEXT,
    estado_parc TEXT,
    refuerzo TEXT,
    sucesion TEXT,
    doc_escribania TEXT,
    proforma TEXT,
    ad_ref_comp TEXT,
    ad_ref_vend TEXT,
    fecha_reserva TEXT,
    fecha_firma TEXT,
    particularidades TEXT,
    estado TEXT,
    mes TEXT,
    colaborador TEXT,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modificado_por TEXT DEFAULT 'usuario'
);

CREATE TABLE IF NOT EXISTS finanzas_deudas (
    id SERIAL PRIMARY KEY,
    agente_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    descripcion TEXT,
    monto DOUBLE PRECISION,
    moneda TEXT DEFAULT 'USD',
    fecha_vencimiento TEXT,
    estado TEXT DEFAULT 'falta',
    tipo TEXT DEFAULT 'mensual',        -- mensual, puntual
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modificado_por TEXT DEFAULT 'usuario'
);

CREATE TABLE IF NOT EXISTS config_deudas_agentes (
    agente_id INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    monto_oficina DOUBLE PRECISION DEFAULT 80,
    moneda_oficina TEXT DEFAULT 'USD',
    otros_gastos_json TEXT
);

-- Cajas, Bancos y Tesorería por Oficina (Multi-tenant)
CREATE TABLE IF NOT EXISTS finanzas_cajas_bancos (
    id SERIAL PRIMARY KEY,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'caja_efectivo', -- caja_efectivo, cuenta_bancaria, billetera_virtual
    moneda TEXT NOT NULL DEFAULT 'USD',         -- USD, ARS
    saldo_inicial DOUBLE PRECISION DEFAULT 0.0,
    activa INTEGER DEFAULT 1,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Proveedores y Cuentas por Pagar (Multi-tenant)
CREATE TABLE IF NOT EXISTS finanzas_proveedores (
    id SERIAL PRIMARY KEY,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    cuit_rut TEXT,
    rubro TEXT,                                 -- Portales, Marketing, Infraestructura, etc.
    contacto TEXT,
    telefono TEXT,
    email TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Gastos Operativos (OPEX) y Facturas
CREATE TABLE IF NOT EXISTS finanzas_gastos_opex (
    id SERIAL PRIMARY KEY,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id) ON DELETE CASCADE,
    proveedor_id INTEGER REFERENCES finanzas_proveedores(id) ON DELETE SET NULL,
    descripcion TEXT NOT NULL,
    categoria TEXT DEFAULT 'operativo',         -- portales, marketing, infraestructura, servicios, impuestos, otros
    monto DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    moneda TEXT DEFAULT 'ARS',                  -- ARS, USD
    tipo_cambio DOUBLE PRECISION DEFAULT 1.0,
    fecha_emision TEXT,
    fecha_vencimiento TEXT,
    fecha_pago TEXT,
    estado TEXT DEFAULT 'pendiente',            -- pendiente, pagado, cancelado
    caja_id INTEGER REFERENCES finanzas_cajas_bancos(id) ON DELETE SET NULL,
    comprobante_url TEXT,
    notas TEXT,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modificado_por TEXT DEFAULT 'usuario'
);

-- Libro Diario de Movimientos de Caja / Tesorería
CREATE TABLE IF NOT EXISTS finanzas_movimientos_caja (
    id SERIAL PRIMARY KEY,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id) ON DELETE CASCADE,
    caja_id INTEGER NOT NULL REFERENCES finanzas_cajas_bancos(id) ON DELETE CASCADE,
    tipo_movimiento TEXT NOT NULL,              -- ingreso, egreso, transferencia
    origen TEXT,                                -- deuda_agente, comision_oficina, gasto_opex, ajuste_manual, transferencia
    origen_id INTEGER,
    monto DOUBLE PRECISION NOT NULL,
    moneda TEXT NOT NULL,
    descripcion TEXT,
    fecha_movimiento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modificado_por TEXT DEFAULT 'usuario'
);

CREATE TABLE IF NOT EXISTS privilegios_acceso (
    id SERIAL PRIMARY KEY,
    tipo_entidad TEXT NOT NULL,         -- 'rol' o 'usuario'
    entidad_id TEXT NOT NULL,          -- e.g. 'agente', 'broker'
    tipo_objeto TEXT NOT NULL,          -- 'plugin', 'menu_item', 'accion'
    objeto_id TEXT NOT NULL,
    permitido INTEGER DEFAULT 1,
    UNIQUE(tipo_entidad, entidad_id, tipo_objeto, objeto_id)
);

CREATE TABLE IF NOT EXISTS historias_redes (
    id SERIAL PRIMARY KEY,
    fecha_programada TEXT NOT NULL,
    archivo_path TEXT NOT NULL,
    orden INTEGER NOT NULL,
    estado TEXT DEFAULT 'pendiente',    -- pendiente, completado, error:*
    fecha_publicacion TIMESTAMP,
    error_log TEXT,
    reintentos INTEGER DEFAULT 0,
    plataforma TEXT DEFAULT 'whatsapp',
    whatsapp INTEGER DEFAULT 1,
    instagram INTEGER DEFAULT 0,
    agente_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agentes_contactos_copia (
    id SERIAL PRIMARY KEY,
    agente_usuario TEXT NOT NULL,
    nombre TEXT,
    telefono TEXT,
    email TEXT,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agente_usuario, telefono)
);

CREATE TABLE IF NOT EXISTS busquedas_clientes (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES contactos(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    tipo_operacion TEXT NOT NULL DEFAULT 'venta',
    tipo_propiedad TEXT NOT NULL DEFAULT 'departamento',
    zona TEXT NOT NULL,
    ambientes TEXT,
    dormitorios TEXT,
    min_precio DOUBLE PRECISION,
    max_precio DOUBLE PRECISION,
    min_m2 DOUBLE PRECISION,
    max_m2 DOUBLE PRECISION,
    extras TEXT,
    keyword TEXT,
    agente_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultima_ejecucion TEXT,
    propiedades_vistas TEXT DEFAULT '[]',
    modo_busqueda TEXT NOT NULL DEFAULT 'completa'
);

CREATE TABLE IF NOT EXISTS cola_correos_clientes (
    id SERIAL PRIMARY KEY,
    email_dest TEXT NOT NULL,
    asunto TEXT NOT NULL,
    cuerpo_html TEXT NOT NULL,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    estado TEXT DEFAULT 'pendiente',
    fecha_enviado TIMESTAMP,
    error_log TEXT
);

-- ==========================================
-- MULTI-MARCA / MULTI-TENANT (FUTURO)
-- ==========================================

CREATE TABLE IF NOT EXISTS marcas (
    id SERIAL PRIMARY KEY,
    nombre TEXT UNIQUE NOT NULL,
    subdominio TEXT UNIQUE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Inserciones iniciales
INSERT INTO configuracion (clave, valor) VALUES
    ('agente_nombre', 'Tu Nombre'),
    ('agente_telefono', '+54 11 1234-5678'),
    ('agente_email', 'tu@email.com'),
    ('agente_inmobiliaria', 'Tu Inmobiliaria'),
    ('smtp_host', 'smtp.gmail.com'),
    ('smtp_port', '587'),
    ('smtp_user', ''),
    ('smtp_password', ''),
    ('followup_dias_1', '3'),
    ('followup_dias_2', '8')
ON CONFLICT (clave) DO NOTHING;

INSERT INTO estadisticas_ia (estrategia) VALUES ('marketing'), ('red_ferrari') ON CONFLICT DO NOTHING;

INSERT INTO usuarios (usuario, password_hash, nombre_display, rol) 
VALUES ('GermanMazza', 'scrypt:32768:8:1$YIMczrvNunbUCRp0$b32e08cc82a02df43423c399531c1db65e07b36f25d20cd8d78fd69778f96f51a113c8017c804e0feee24a961d094a4a376035a39eb16732d0d3ad7ed46ee60b', 'German Mazza', 'admin') 
ON CONFLICT (usuario) DO NOTHING;

INSERT INTO planificador_mensajes (semana, mensaje, habilitado) VALUES 
(1, '', 0), (2, '', 0), (3, '', 0), (4, '', 0), (5, '', 0),
(6, '', 0), (7, '', 0), (8, '', 0), (9, '', 0)
ON CONFLICT (semana) DO NOTHING;
