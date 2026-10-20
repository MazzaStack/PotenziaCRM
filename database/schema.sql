-- Captador de Propiedades - Database Schema

CREATE TABLE IF NOT EXISTS propiedades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portal TEXT NOT NULL,               -- zonaprop, argenprop, mercadolibre
    url TEXT NOT NULL UNIQUE,
    titulo TEXT,
    precio REAL,
    moneda TEXT DEFAULT 'USD',          -- USD, ARS
    direccion TEXT,
    barrio TEXT,
    ciudad TEXT,
    m2_total REAL,
    m2_cubiertos REAL,
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
    fecha_captacion TEXT DEFAULT (datetime('now', 'localtime')),
    estado TEXT DEFAULT 'nueva',        -- nueva, contactada, en_seguimiento, captada, descartada
    notas TEXT,
    puntaje INTEGER DEFAULT 0,           -- 0-5 prioridad manual del agente
    busqueda_id INTEGER REFERENCES busquedas(id), -- link a la búsqueda de origen
    lat REAL,                           -- Latitud para mapas
    lng REAL                            -- Longitud para mapas
);

CREATE TABLE IF NOT EXISTS comunicaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    propiedad_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,                 -- email, whatsapp, llamada
    mensaje TEXT,
    asunto TEXT,                        -- solo para emails
    fecha_programada TEXT,
    fecha_enviada TEXT,
    estado TEXT DEFAULT 'pendiente',    -- pendiente, enviada, respondida
    paso INTEGER DEFAULT 1,            -- 1=primer contacto, 2=follow-up, 3=ultimo intento
    FOREIGN KEY (propiedad_id) REFERENCES propiedades(id)
);

CREATE TABLE IF NOT EXISTS busquedas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    portal TEXT NOT NULL,               -- zonaprop, argenprop, mercadolibre
    url_busqueda TEXT NOT NULL,          -- URL prearmada del portal con filtros
    activa INTEGER DEFAULT 1,
    frecuencia_minutos INTEGER DEFAULT 60,
    ultima_ejecucion TEXT,
    propiedades_encontradas INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

-- Configuración por defecto
INSERT OR IGNORE INTO configuracion (clave, valor) VALUES
    ('agente_nombre', 'Tu Nombre'),
    ('agente_telefono', '+54 11 1234-5678'),
    ('agente_email', 'tu@email.com'),
    ('agente_inmobiliaria', 'Tu Inmobiliaria'),
    ('smtp_host', 'smtp.gmail.com'),
    ('smtp_port', '587'),
    ('smtp_user', ''),
    ('smtp_password', ''),
    ('followup_dias_1', '3'),
    ('followup_dias_2', '8'),
    ('template_email_1', 'Hola {nombre},

Vi tu publicación en {portal} de la propiedad en {direccion}.
Soy {agente_nombre}, agente inmobiliario de {agente_inmobiliaria}.

Trabajo con compradores activos en la zona de {barrio} y tu propiedad podría interesarle a varios de mis clientes.

¿Te gustaría que coordinemos una visita sin compromiso? Puedo ofrecerte una tasación gratuita del mercado actual.

Saludos,
{agente_nombre}
{agente_telefono}'),
    ('template_email_asunto_1', '{nombre}, vi tu propiedad en {barrio}'),
    ('template_whatsapp_1', 'Hola {nombre}! 👋 Vi tu propiedad en {direccion} publicada en {portal}. Soy {agente_nombre}, agente inmobiliario. Tengo compradores interesados en {barrio}. ¿Te puedo ayudar con la venta? Sin compromiso 🏠'),
    ('template_email_2', 'Hola {nombre},

Te escribí hace unos días sobre tu propiedad en {direccion}.
Entiendo que estés ocupado/a. Solo quería confirmar si seguís interesado/a en recibir una propuesta.

Tengo experiencia vendiendo propiedades en {barrio} y puedo compartirte un análisis comparativo de precios de la zona sin costo.

Quedo a disposición,
{agente_nombre}
{agente_telefono}'),
    ('template_email_asunto_2', 'Re: {nombre}, tu propiedad en {barrio}'),
    ('template_whatsapp_2', 'Hola {nombre}, te escribí hace unos días por tu propiedad en {direccion}. ¿Pudiste ver mi mensaje? Quedo a disposición para cualquier consulta 😊'),
    ('template_email_3', 'Hola {nombre},

Último mensaje, no quiero ser insistente. Te ofrezco una tasación 100% gratuita de tu propiedad en {direccion} basada en ventas recientes de la zona.

Sin compromiso, me sirve para conocer más propiedades y a vos te puede servir para saber el valor real de mercado.

Si en algún momento necesitás ayuda, acá estoy.

Saludos,
{agente_nombre}
{agente_telefono}'),
    ('template_email_asunto_3', 'Tasación gratuita para tu propiedad en {barrio}'),
    ('template_whatsapp_3', 'Hola {nombre}, te ofrezco una tasación gratuita de tu propiedad en {direccion}. Sin compromiso, solo para que conozcas el valor real de mercado de tu propiedad. Cualquier cosa estoy a disposición 🏡');

CREATE INDEX IF NOT EXISTS idx_propiedades_estado ON propiedades(estado);
CREATE INDEX IF NOT EXISTS idx_propiedades_portal ON propiedades(portal);
CREATE INDEX IF NOT EXISTS idx_comunicaciones_propiedad ON comunicaciones(propiedad_id);
CREATE INDEX IF NOT EXISTS idx_comunicaciones_estado ON comunicaciones(estado);

-- ==========================================
-- AUTOMATIZACIÓN E IA
-- ==========================================

-- Tabla para gestionar la cola de mensajes automáticos y alertas directas
CREATE TABLE IF NOT EXISTS cola_mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    propiedad_id INTEGER,
    telefono TEXT,
    mensaje TEXT,
    tipo TEXT NOT NULL DEFAULT 'whatsapp',
    estrategia TEXT,
    fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
    fecha_programada TEXT DEFAULT (datetime('now', 'localtime')),
    estado TEXT DEFAULT 'pendiente',    -- pendiente, enviado, error
    error_log TEXT,
    FOREIGN KEY (propiedad_id) REFERENCES propiedades(id)
);

-- Tabla para medir éxito de las estrategias de IA
CREATE TABLE IF NOT EXISTS estadisticas_ia (
    estrategia TEXT PRIMARY KEY,        -- marketing, red_ferrari
    enviados INTEGER DEFAULT 0,
    respuestas INTEGER DEFAULT 0
);

-- Inicializar estadísticas
INSERT OR IGNORE INTO estadisticas_ia (estrategia) VALUES ('marketing'), ('red_ferrari');

-- ==========================================
-- CRM: OFICINAS, CONTACTOS Y SEGURIDAD
-- ==========================================

-- Tabla de Oficinas (Multi-tenant)
CREATE TABLE IF NOT EXISTS oficinas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    direccion TEXT,
    telefono TEXT,
    logo_url TEXT,
    color_primario TEXT DEFAULT '#0d6efd',
    color_secundario TEXT DEFAULT '#1a1a2e',
    es_portal_clientes INTEGER DEFAULT 0, -- 1 si es la única oficina con Portal Clientes activo
    activa INTEGER DEFAULT 1,
    fecha_creacion TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Oficina principal por defecto
INSERT OR IGNORE INTO oficinas (id, nombre, slug, es_portal_clientes, activa) 
VALUES (1, 'Oficina Central Ferrari', 'oficina-central', 1, 1);

-- Tabla de usuarios para el Login
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    nombre_display TEXT,
    rol TEXT DEFAULT 'agente',        -- admin, broker, agente, finanzas
    db_file TEXT,                    -- Archivo sqlite individual (ej: agente_pedro.db)
    oficina_id INTEGER REFERENCES oficinas(id), -- NULL = Agente Suelto
    fecha_creacion TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Tabla para archivos compartidos entre admin/broker y agentes
CREATE TABLE IF NOT EXISTS archivos_asignados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_archivo TEXT NOT NULL,
    ruta_archivo TEXT NOT NULL,
    asignado_a INTEGER REFERENCES usuarios(id),
    asignado_por INTEGER REFERENCES usuarios(id),
    fecha_asignado TEXT DEFAULT (datetime('now', 'localtime')),
    leido INTEGER DEFAULT 0
);

-- Tabla de contactos profesionales (Ferrari Propiedades) con fidelización e IA
CREATE TABLE IF NOT EXISTS contactos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT,
    apellido TEXT,
    calificacion INTEGER DEFAULT 0,    -- 1 a 5 estrellas
    categoria TEXT DEFAULT 'C',       -- A, B, C, D (German's Request)
    ultimo_contacto TEXT,             -- Fecha YYYY-MM-DD
    fecha_nacimiento TEXT,            -- Fecha YYYY-MM-DD
    aniversario_casa TEXT,            -- Fecha YYYY-MM-DD
    rol TEXT,                         -- Comprador, Vendedor, Colega, Otros
    referente TEXT,                   -- Quién lo recomendó
    notas TEXT,                       -- Comentarios/Historial
    telefono TEXT UNIQUE,             -- Para WhatsApp directo
    email TEXT,
    busqueda_activa INTEGER DEFAULT 0, -- 1 = Si
    filtros_busqueda_json TEXT,       -- Para "Búsqueda Inversa" con IA
    estado_seguimiento TEXT DEFAULT 'activo',
    fecha_recarga TEXT DEFAULT (datetime('now', 'localtime')),
    campos_personalizados_json TEXT,  -- Para columnas elásticas del agente
    mac INTEGER DEFAULT 0,            -- 1 si viene del Meta AI Chatbot
    intencion_ia TEXT,                -- Resumen de la intención detectada por la IA
    recordatorio_activo INTEGER DEFAULT 0,
    recordatorio_dias INTEGER,
    recordatorio_fecha TEXT
);

-- Tabla para persistir estado de tareas diarias
CREATE TABLE IF NOT EXISTS tareas_diarias_estado (
    fecha TEXT PRIMARY KEY,           -- YYYY-MM-DD
    historias_ig_wa INTEGER DEFAULT 0,
    lanzar_lote_5_5 INTEGER DEFAULT 0,
    automatizacion_diaria INTEGER DEFAULT 0,
    mantenimiento_base INTEGER DEFAULT 0
);

-- Historial de Tasaciones Rápidas generadas
CREATE TABLE IF NOT EXISTS tasaciones_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_operacion TEXT, -- alquiler, venta, temporal
    tipo_propiedad TEXT, -- casa, depto, etc
    metros_cubiertos REAL,
    metros_totales REAL,
    ambientes INTEGER,
    habitaciones INTEGER,
    zona TEXT,
    precio_bajo REAL,
    precio_medio REAL,
    precio_alto REAL,
    fecha DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Inicializar usuario SuperAdmin principal con credenciales cifradas (scrypt)
INSERT OR IGNORE INTO usuarios (usuario, password_hash, nombre_display) 
VALUES ('GermanMazza', 'scrypt:32768:8:1$YIMczrvNunbUCRp0$b32e08cc82a02df43423c399531c1db65e07b36f25d20cd8d78fd69778f96f51a113c8017c804e0feee24a961d094a4a376035a39eb16732d0d3ad7ed46ee60b', 'German Mazza');

-- ==========================================
-- PLANIFICADOR DE MENSAJES (10 SEMANAS)
-- ==========================================
CREATE TABLE IF NOT EXISTS planificador_mensajes (
    semana INTEGER PRIMARY KEY,
    mensaje TEXT,
    habilitado INTEGER DEFAULT 0
);

-- Inicializar 10 semanas
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (1, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (2, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (3, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (4, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (5, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (6, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (7, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (8, '', 0);
INSERT OR IGNORE INTO planificador_mensajes (semana, mensaje, habilitado) VALUES (9, '', 0);
-- ==========================================
-- SISTEMA BROKER Y FINANZAS
-- ==========================================

CREATE TABLE IF NOT EXISTS seguimiento_operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agente_id INTEGER NOT NULL REFERENCES usuarios(id),
    comision_rendida INTEGER DEFAULT 0,
    iva_rendido INTEGER DEFAULT 0,
    doc_rendida INTEGER DEFAULT 0,
    domicilio TEXT,
    juris TEXT,
    puntas TEXT,
    porcentaje REAL,
    cierre TEXT,
    bruto REAL,
    neto REAL,
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
    fecha_registro TEXT DEFAULT (datetime('now', 'localtime')),
    modificado_por TEXT DEFAULT 'usuario'
);

CREATE TABLE IF NOT EXISTS finanzas_deudas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agente_id INTEGER NOT NULL REFERENCES usuarios(id),
    descripcion TEXT,
    monto REAL,
    moneda TEXT DEFAULT 'USD',
    fecha_vencimiento TEXT,
    estado TEXT DEFAULT 'falta',
    tipo TEXT DEFAULT 'mensual', -- mensual, puntual
    fecha_registro TEXT DEFAULT (datetime('now', 'localtime')),
    modificado_por TEXT DEFAULT 'usuario'
);

CREATE TABLE IF NOT EXISTS config_deudas_agentes (
    agente_id INTEGER PRIMARY KEY REFERENCES usuarios(id),
    monto_oficina REAL DEFAULT 80,
    moneda_oficina TEXT DEFAULT 'USD',
    otros_gastos_json TEXT -- Para otros gastos configurables
);

-- Cajas, Bancos y Tesorería por Oficina (Multi-tenant)
CREATE TABLE IF NOT EXISTS finanzas_cajas_bancos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id),
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'caja_efectivo', -- caja_efectivo, cuenta_bancaria, billetera_virtual
    moneda TEXT NOT NULL DEFAULT 'USD',         -- USD, ARS
    saldo_inicial REAL DEFAULT 0.0,
    activa INTEGER DEFAULT 1,
    fecha_creacion TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Proveedores y Cuentas por Pagar (Multi-tenant)
CREATE TABLE IF NOT EXISTS finanzas_proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id),
    nombre TEXT NOT NULL,
    cuit_rut TEXT,
    rubro TEXT,                                 -- Portales, Marketing, Infraestructura, etc.
    contacto TEXT,
    telefono TEXT,
    email TEXT,
    fecha_creacion TEXT DEFAULT (datetime('now', 'localtime'))
);

-- Gastos Operativos (OPEX) y Facturas
CREATE TABLE IF NOT EXISTS finanzas_gastos_opex (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id),
    proveedor_id INTEGER REFERENCES finanzas_proveedores(id),
    descripcion TEXT NOT NULL,
    categoria TEXT DEFAULT 'operativo',         -- portales, marketing, infraestructura, servicios, impuestos, otros
    monto REAL NOT NULL DEFAULT 0.0,
    moneda TEXT DEFAULT 'ARS',                  -- ARS, USD
    tipo_cambio REAL DEFAULT 1.0,
    fecha_emision TEXT,
    fecha_vencimiento TEXT,
    fecha_pago TEXT,
    estado TEXT DEFAULT 'pendiente',            -- pendiente, pagado, cancelado
    caja_id INTEGER REFERENCES finanzas_cajas_bancos(id),
    comprobante_url TEXT,
    notas TEXT,
    fecha_registro TEXT DEFAULT (datetime('now', 'localtime')),
    modificado_por TEXT DEFAULT 'usuario'
);

-- Libro Diario de Movimientos de Caja / Tesorería
CREATE TABLE IF NOT EXISTS finanzas_movimientos_caja (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oficina_id INTEGER NOT NULL REFERENCES oficinas(id),
    caja_id INTEGER NOT NULL REFERENCES finanzas_cajas_bancos(id),
    tipo_movimiento TEXT NOT NULL,              -- ingreso, egreso, transferencia
    origen TEXT,                                -- deuda_agente, comision_oficina, gasto_opex, ajuste_manual, transferencia
    origen_id INTEGER,
    monto REAL NOT NULL,
    moneda TEXT NOT NULL,
    descripcion TEXT,
    fecha_movimiento TEXT DEFAULT (datetime('now', 'localtime')),
    modificado_por TEXT DEFAULT 'usuario'
);

-- ==========================================
-- CONTROL DE ACCESO (MATRIZ DE PRIVILEGIOS)
-- ==========================================
CREATE TABLE IF NOT EXISTS privilegios_acceso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo_entidad TEXT NOT NULL,          -- 'rol' o 'usuario'
    entidad_id TEXT NOT NULL,            -- e.g. 'agente', 'broker', o 'GermanMazza'
    tipo_objeto TEXT NOT NULL,           -- 'plugin', 'menu_item', 'accion'
    objeto_id TEXT NOT NULL,             -- e.g. 'finanzas', 'tasador', 'ejecutar_scraper'
    permitido INTEGER DEFAULT 1,         -- 1 = Permitido, 0 = Denegado
    UNIQUE(tipo_entidad, entidad_id, tipo_objeto, objeto_id)
);

-- ==========================================
-- HISTORIAS / STATUS REDES SOCIALES
-- ==========================================
CREATE TABLE IF NOT EXISTS historias_redes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_programada DATE NOT NULL,
    archivo_path TEXT NOT NULL,
    orden INTEGER NOT NULL,
    estado TEXT DEFAULT 'pendiente',        -- pendiente, completado, error:*
    fecha_publicacion DATETIME,
    error_log TEXT,
    reintentos INTEGER DEFAULT 0,
    plataforma TEXT DEFAULT 'whatsapp',     -- Legacy column (kept for compatibility)
    whatsapp INTEGER DEFAULT 1,             -- 1 = publicar en WhatsApp Status (ON por defecto)
    instagram INTEGER DEFAULT 0,            -- 1 = publicar en Instagram Stories (OFF por defecto)
    agente_id INTEGER REFERENCES usuarios(id) -- NULL = historia del agente logueado; set by admin for scheduling
);

-- ==========================================
-- COPIA EXTRA DE CONTACTOS DE AGENTES
-- ==========================================
CREATE TABLE IF NOT EXISTS agentes_contactos_copia (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agente_usuario TEXT NOT NULL,
    nombre TEXT,
    telefono TEXT,
    email TEXT,
    fecha_registro TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(agente_usuario, telefono)
);

-- ==========================================
-- BUSQUEDAS DE CLIENTES Y COLA DE CORREOS
-- ==========================================

CREATE TABLE IF NOT EXISTS busquedas_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    tipo_operacion TEXT NOT NULL DEFAULT 'venta',
    tipo_propiedad TEXT NOT NULL DEFAULT 'departamento',
    zona TEXT NOT NULL,
    ambientes INTEGER,
    dormitorios INTEGER,
    min_precio REAL,
    max_precio REAL,
    min_m2 REAL,
    max_m2 REAL,
    extras TEXT,
    keyword TEXT,
    agente_id INTEGER,
    fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
    ultima_ejecucion TEXT,
    propiedades_vistas TEXT DEFAULT '[]',
    modo_busqueda TEXT NOT NULL DEFAULT 'completa',
    FOREIGN KEY (cliente_id) REFERENCES contactos(id),
    FOREIGN KEY (agente_id) REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS cola_correos_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_dest TEXT NOT NULL,
    asunto TEXT NOT NULL,
    cuerpo_html TEXT NOT NULL,
    fecha_creacion TEXT DEFAULT (datetime('now', 'localtime')),
    estado TEXT DEFAULT 'pendiente',
    fecha_enviado TEXT,
    error_log TEXT
);

-- ==========================================
-- FICHAS DE CLIENTES / LINKS MARCA BLANCA
-- ==========================================
CREATE TABLE IF NOT EXISTS enlaces_fichas_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_slug TEXT UNIQUE NOT NULL,
    agente_id INTEGER NOT NULL,
    portal_origen TEXT,
    url_origen TEXT,
    titulo TEXT NOT NULL,
    precio REAL,
    moneda TEXT DEFAULT 'USD',
    expensas REAL DEFAULT 0,
    tipo_operacion TEXT DEFAULT 'venta',
    tipo_propiedad TEXT DEFAULT 'Departamento',
    direccion_mostrada TEXT,
    barrio TEXT,
    ambientes INTEGER DEFAULT 0,
    dormitorios INTEGER DEFAULT 0,
    banos INTEGER DEFAULT 0,
    m2_total REAL DEFAULT 0,
    m2_cubiertos REAL DEFAULT 0,
    cocheras INTEGER DEFAULT 0,
    antiguedad TEXT,
    orientacion TEXT,
    disposicion TEXT,
    caracteristicas_json TEXT DEFAULT '{}',
    descripcion TEXT,
    fotos_json TEXT DEFAULT '[]',
    foto_portada TEXT,
    lat REAL,
    lng REAL,
    agente_nombre TEXT,
    agente_telefono TEXT,
    agente_email TEXT,
    agente_avatar TEXT,
    vistas_count INTEGER DEFAULT 0,
    primer_acceso TEXT,
    ultimo_acceso TEXT,
    logs_accesos_json TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    expires_at TEXT,
    activo INTEGER DEFAULT 1,
    FOREIGN KEY (agente_id) REFERENCES usuarios(id)
);



