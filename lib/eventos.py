"""
Módulo de Eventos y Calendario de Efemérides de la República Argentina y Clientes CRM.
Calcula fechas festivas, días patrios, feriados (fijos y móviles) y eventos de fidelización
(cumpleaños y aniversarios de compra de inmuebles) para el Dashboard y Asistente IA.
"""
import re
from datetime import date, datetime, timedelta

def easter_date(year: int) -> date:
    """Calcula la fecha del Domingo de Pascua para un año dado usando el algoritmo de Butcher."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)

def get_nth_sunday(year: int, month: int, n: int = 3) -> date:
    """Calcula el n-ésimo domingo de un mes y año específico."""
    first_day = date(year, month, 1)
    first_sunday = first_day + timedelta(days=(6 - first_day.weekday()) % 7)
    return first_sunday + timedelta(weeks=n - 1)

def parse_date_flexible(val):
    """
    Parsea fechas en diversos formatos comunes (ISO YYYY-MM-DD, DD/MM/YYYY, MM-DD, etc.)
    Retorna (year, month, day). Year puede ser None si solo se especificó mes-día.
    """
    if not val:
        return None, None, None
    val = str(val).strip()
    
    # ISO: YYYY-MM-DD o YYYY/MM/DD
    m = re.match(r'^(\d{4})[-/](\d{1,2})[-/](\d{1,2})', val)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
        
    # Latam: DD/MM/YYYY o DD-MM-YYYY
    m = re.match(r'^(\d{1,2})[-/](\d{1,2})[-/](\d{4})', val)
    if m:
        return int(m.group(3)), int(m.group(2)), int(m.group(1))
        
    # Mes-Día: MM-DD o --MM-DD o MM/DD
    m = re.match(r'^(?:--)?(\d{1,2})[-/](\d{1,2})$', val)
    if m:
        return None, int(m.group(1)), int(m.group(2))
        
    return None, None, None

def make_safe_date(year: int, month: int, day: int):
    """Construye un objeto date manejando casos como 29 de febrero en años no bisiestos."""
    try:
        return date(year, month, day)
    except ValueError:
        if month == 2 and day == 29:
            return date(year, 2, 28)
        return None

# Lista exhaustiva de efemérides, feriados nacionales y días patrios de la República Argentina
EFEMERIDES_FIJAS_ARGENTINA = [
    ('01-01', 'Año Nuevo', 'Feriado Nacional', 'feriado', '🎆'),
    ('01-06', 'Día de Reyes', 'Festivo', 'festivo', '👑'),
    ('02-14', 'Día de los Enamorados / San Valentín', 'Festivo', 'festivo', '❤️'),
    ('02-15', 'Día del Redactor Publicitario', 'Efeméride Profesional', 'profesional', '✍️'),
    ('03-08', 'Día Internacional de la Mujer', 'Festivo Internacional', 'festivo', '💐'),
    ('03-24', 'Día de la Memoria por la Verdad y la Justicia', 'Feriado Nacional / Día Patrio', 'patrio', '🕊️'),
    ('04-02', 'Día del Veterano y Caídos en Malvinas', 'Feriado Nacional / Día Patrio', 'patrio', '🇦🇷'),
    ('04-13', 'Día del Kinesiólogo', 'Efeméride Profesional', 'profesional', '🩺'),
    ('04-23', 'Día del Agrimensor', 'Efeméride Inmobiliaria', 'profesional', '📐'),
    ('04-29', 'Día del Animal', 'Festivo', 'festivo', '🐾'),
    ('05-01', 'Día Internacional del Trabajador', 'Feriado Nacional', 'feriado', '👷'),
    ('05-12', 'Día de la Enfermería', 'Efeméride Profesional', 'profesional', '🏥'),
    ('05-18', 'Día de la Escarapela Nacional', 'Día Patrio', 'patrio', '🇦🇷'),
    ('05-25', 'Día de la Revolución de Mayo', 'Feriado Nacional / Día Patrio', 'patrio', '🇦🇷'),
    ('05-28', 'Día de la Maestra Jardinera', 'Efeméride', 'profesional', '🧸'),
    ('06-02', 'Día del Graduado en Cs. Económicas', 'Efeméride Profesional', 'profesional', '💼'),
    ('06-02', 'Día Nacional del Bombero Voluntario', 'Efeméride', 'profesional', '🚒'),
    ('06-06', 'Día de la Ingeniería Argentina', 'Efeméride Profesional', 'profesional', '🏗️'),
    ('06-07', 'Día del Periodista', 'Efeméride Profesional', 'profesional', '📰'),
    ('06-15', 'Día del Libro en Argentina', 'Efeméride Cultural', 'festivo', '📖'),
    ('06-16', 'Día del Ingeniero', 'Efeméride Profesional', 'profesional', '⚙️'),
    ('06-17', 'Paso a la Inmortalidad del Gral. Güemes', 'Feriado Nacional / Día Patrio', 'patrio', '⚔️'),
    ('06-20', 'Día de la Bandera (Gral. Belgrano)', 'Feriado Nacional / Día Patrio', 'patrio', '🇦🇷'),
    ('07-01', 'Día del Arquitecto en Argentina', 'Efeméride Inmobiliaria', 'profesional', '🏛️'),
    ('07-03', 'Día del Locutor', 'Efeméride Profesional', 'profesional', '🎙️'),
    ('07-09', 'Día de la Independencia Argentina', 'Feriado Nacional / Día Patrio', 'patrio', '🇦🇷'),
    ('07-10', 'Día del Comerciante', 'Efeméride Profesional', 'profesional', '🏪'),
    ('07-20', 'Día del Amigo', 'Festivo', 'festivo', '🤝'),
    ('07-26', 'Día de los Abuelos', 'Festivo', 'festivo', '👵👴'),
    ('08-06', 'Día del Veterinario', 'Efeméride Profesional', 'profesional', '🐾'),
    ('08-10', 'Día de la Fuerza Aérea Argentina', 'Efeméride Nacional', 'patrio', '✈️'),
    ('08-17', 'Paso a la Inmortalidad del Gral. San Martín', 'Feriado Nacional / Día Patrio', 'patrio', '⚔️'),
    ('08-29', 'Día del Abogado en Argentina', 'Efeméride Profesional (en honor a Alberdi)', 'profesional', '⚖️'),
    ('09-04', 'Día de la Secretaria y del Inmigrante', 'Efeméride Profesional', 'profesional', '💼'),
    ('09-11', 'Día del Maestro (Sarmiento)', 'Efeméride Nacional / Día Educativo', 'patrio', '📚'),
    ('09-13', 'Día del Bibliotecario', 'Efeméride Profesional', 'profesional', '📖'),
    ('09-17', 'Día del Profesor', 'Efeméride Profesional', 'profesional', '👨‍🏫'),
    ('09-21', 'Día de la Primavera y del Estudiante', 'Festivo', 'festivo', '🌸'),
    ('09-21', 'Día del Economista', 'Efeméride Profesional', 'profesional', '📊'),
    ('09-21', 'Día de la Sanidad', 'Efeméride Profesional', 'profesional', '🩺'),
    ('09-26', 'Día del Empleado de Comercio', 'Feriado / Día del Gremio', 'feriado', '🏢'),
    ('10-02', 'Día del Escribano y del Notariado', 'Efeméride Notarial e Inmobiliaria', 'profesional', '📜'),
    ('10-03', 'Día del Odontólogo', 'Efeméride Profesional', 'profesional', '🦷'),
    ('10-11', 'Día del Martillero y Corredor Inmobiliario', 'Efeméride Principal del Rubro Inmobiliario', 'profesional', '🏢'),
    ('10-12', 'Día del Respeto a la Diversidad Cultural', 'Feriado Nacional', 'feriado', '🌎'),
    ('11-06', 'Día del Bancario', 'Efeméride / Feriado Bancario', 'feriado', '🏦'),
    ('11-10', 'Día de la Tradición (José Hernández)', 'Día Patrio y Cultural', 'patrio', '🧉'),
    ('11-20', 'Día de la Soberanía Nacional (Vuelta de Obligado)', 'Feriado Nacional / Día Patrio', 'patrio', '🇦🇷'),
    ('12-03', 'Día del Médico', 'Efeméride Profesional', 'profesional', '🩺'),
    ('12-04', 'Día de la Publicidad', 'Efeméride Profesional', 'profesional', '📢'),
    ('12-08', 'Día de la Inmaculada Concepción de María', 'Feriado Nacional', 'feriado', '✨'),
    ('12-17', 'Día del Contador Público', 'Efeméride Profesional', 'profesional', '📊'),
    ('12-24', 'Nochebuena', 'Festivo', 'festivo', '🌟'),
    ('12-25', 'Navidad', 'Feriado Nacional', 'feriado', '🎄'),
    ('12-31', 'Fin de Año', 'Festivo', 'festivo', '🥂')
]

def get_proximos_eventos(agente_id=None, limit=6, dt=None, is_superadmin=False):
    """
    Retorna los próximos eventos más cercanos a partir de hoy (ordenados cronológicamente).
    Combina:
    1. Feriados nacionales, días patrios y fechas festivas argentinas (fijas y móviles).
    2. Cumpleaños de clientes del CRM.
    3. Aniversarios de compra/mudanza (cumplido 1 año o más) de clientes del CRM.
    """
    if dt is None:
        today = date.today()
    elif isinstance(dt, datetime):
        today = dt.date()
    else:
        today = dt

    candidates = []

    # ─────────────────────────────────────────────────────────────
    # 1. Efemérides y Feriados Fijos de Argentina
    # ─────────────────────────────────────────────────────────────
    for mm_dd, titulo, subtitulo, tipo, icono in EFEMERIDES_FIJAS_ARGENTINA:
        m, d = int(mm_dd[:2]), int(mm_dd[3:])
        # Buscar ocurrencia en el año actual y en el siguiente
        for y in [today.year, today.year + 1]:
            ev_date = make_safe_date(y, m, d)
            if ev_date and ev_date >= today:
                diff = (ev_date - today).days
                badge = 'bg-danger text-white' if tipo == 'patrio' else ('bg-info text-dark' if tipo == 'feriado' else ('bg-primary-subtle text-primary border border-primary' if tipo == 'profesional' else 'bg-light text-dark border'))
                candidates.append({
                    'id': f'feriado_{mm_dd}_{y}',
                    'titulo': titulo,
                    'subtitulo': subtitulo,
                    'tipo': tipo,
                    'categoria_grupo': 'argentina',
                    'icono': icono,
                    'badge_class': badge,
                    'fecha': ev_date,
                    'dias_faltantes': diff,
                    'es_hoy': (diff == 0),
                    'contacto_id': None,
                    'telefono': None,
                    'accion_tipo': 'placa'
                })
                break

    # ─────────────────────────────────────────────────────────────
    # 2. Fechas Móviles de Argentina (Carnaval, Semana Santa, Días móviles)
    # ─────────────────────────────────────────────────────────────
    for y in [today.year, today.year + 1]:
        pascuas = easter_date(y)
        carnaval_lunes = pascuas - timedelta(days=48)
        carnaval_martes = pascuas - timedelta(days=47)
        jueves_santo = pascuas - timedelta(days=3)
        viernes_santo = pascuas - timedelta(days=2)
        dia_padre = get_nth_sunday(y, 6, 3)
        dia_nino = get_nth_sunday(y, 8, 3)
        dia_madre = get_nth_sunday(y, 10, 3)

        movables = [
            (carnaval_lunes, 'Carnaval (Lunes)', 'Feriado Nacional', 'feriado', '🎭', 'bg-info text-dark'),
            (carnaval_martes, 'Carnaval (Martes)', 'Feriado Nacional', 'feriado', '🎭', 'bg-info text-dark'),
            (jueves_santo, 'Jueves Santo', 'Día No Laborable', 'feriado', '🕊️', 'bg-info text-dark'),
            (viernes_santo, 'Viernes Santo', 'Feriado Nacional', 'feriado', '🕊️', 'bg-info text-dark'),
            (pascuas, 'Pascuas de Resurrección', 'Festivo', 'festivo', '🐣', 'bg-warning-subtle text-warning border border-warning'),
            (dia_padre, 'Día del Padre en Argentina', 'Festivo Móvil (3er domingo de Junio)', 'festivo', '👨', 'bg-primary-subtle text-primary border border-primary'),
            (dia_nino, 'Día de las Infancias / Día del Niño', 'Festivo Móvil (3er domingo de Agosto)', 'festivo', '🧸', 'bg-info-subtle text-info border border-info'),
            (dia_madre, 'Día de la Madre en Argentina', 'Festivo Móvil (3er domingo de Octubre)', 'festivo', '💐', 'bg-danger-subtle text-danger border border-danger')
        ]
        for ev_date, titulo, subtitulo, tipo, icono, badge in movables:
            if ev_date >= today:
                diff = (ev_date - today).days
                candidates.append({
                    'id': f'movable_{titulo}_{y}',
                    'titulo': titulo,
                    'subtitulo': subtitulo,
                    'tipo': tipo,
                    'categoria_grupo': 'argentina',
                    'icono': icono,
                    'badge_class': badge,
                    'fecha': ev_date,
                    'dias_faltantes': diff,
                    'es_hoy': (diff == 0),
                    'contacto_id': None,
                    'telefono': None,
                    'accion_tipo': 'placa'
                })

    # ─────────────────────────────────────────────────────────────
    # 3. Eventos de Clientes (Cumpleaños y Aniversarios de Compra)
    # ─────────────────────────────────────────────────────────────
    try:
        from database.db import get_db
        conn = get_db()
        try:
            if is_superadmin or agente_id is None:
                rows = conn.execute("""
                    SELECT id, nombre, apellido, telefono, fecha_nacimiento, aniversario_casa, rol, categoria 
                    FROM contactos 
                    WHERE (fecha_nacimiento IS NOT NULL AND fecha_nacimiento != '') 
                       OR (aniversario_casa IS NOT NULL AND aniversario_casa != '')
                """).fetchall()
            else:
                rows = conn.execute("""
                    SELECT id, nombre, apellido, telefono, fecha_nacimiento, aniversario_casa, rol, categoria 
                    FROM contactos 
                    WHERE (agente_id = ? OR agente_id IS NULL)
                      AND ((fecha_nacimiento IS NOT NULL AND fecha_nacimiento != '') 
                           OR (aniversario_casa IS NOT NULL AND aniversario_casa != ''))
                """, (agente_id,)).fetchall()
                
            for r in rows:
                nom = (r['nombre'] or '').strip()
                ape = (r['apellido'] or '').strip()
                nombre_completo = f"{nom} {ape}".strip() or 'Cliente'
                tel = (r['telefono'] or '').strip()

                # Cumpleaños
                if r['fecha_nacimiento']:
                    by, bm, bd = parse_date_flexible(r['fecha_nacimiento'])
                    if bm and bd:
                        for y in [today.year, today.year + 1]:
                            ev_date = make_safe_date(y, bm, bd)
                            if ev_date and ev_date >= today:
                                diff = (ev_date - today).days
                                edad_txt = f" ({y - by} años)" if by and (y - by) > 0 else ""
                                candidates.append({
                                    'id': f"cumple_{r['id']}_{y}",
                                    'titulo': nombre_completo,
                                    'subtitulo': f"Cumpleaños de cliente{edad_txt}",
                                    'tipo': 'cumpleanios',
                                    'categoria_grupo': 'cliente',
                                    'icono': '🎂',
                                    'badge_class': 'bg-warning text-dark border border-warning',
                                    'fecha': ev_date,
                                    'dias_faltantes': diff,
                                    'es_hoy': (diff == 0),
                                    'contacto_id': r['id'],
                                    'telefono': tel,
                                    'accion_tipo': 'saludo_cumple'
                                })
                                break

                # Aniversario de compra (cumplido 1 año o más)
                if r['aniversario_casa']:
                    py, pm, pd = parse_date_flexible(r['aniversario_casa'])
                    if pm and pd:
                        for y in [today.year, today.year + 1]:
                            ev_date = make_safe_date(y, pm, pd)
                            if ev_date and ev_date >= today:
                                diff = (ev_date - today).days
                                anios = (y - py) if py else None
                                if anios is not None and anios >= 1:
                                    anio_txt = f" ({anios} {'año' if anios == 1 else 'años'} desde que compró su propiedad)"
                                else:
                                    anio_txt = " (Aniversario de su propiedad)"
                                candidates.append({
                                    'id': f"aniv_{r['id']}_{y}",
                                    'titulo': nombre_completo,
                                    'subtitulo': f"Aniversario de compra{anio_txt}",
                                    'tipo': 'aniversario',
                                    'categoria_grupo': 'cliente',
                                    'icono': '🏡',
                                    'badge_class': 'bg-primary text-white border border-primary',
                                    'fecha': ev_date,
                                    'dias_faltantes': diff,
                                    'es_hoy': (diff == 0),
                                    'contacto_id': r['id'],
                                    'telefono': tel,
                                    'accion_tipo': 'saludo_aniv'
                                })
                                break
        finally:
            conn.close()
    except Exception as e_db:
        print(f"[Eventos] Error consultando eventos de clientes en DB: {e_db}")

    # ─────────────────────────────────────────────────────────────
    # 4. Ordenamiento y Deduplicación
    # ─────────────────────────────────────────────────────────────
    type_priority = {
        'patrio': 1,
        'feriado': 2,
        'cumpleanios': 3,
        'aniversario': 4,
        'profesional': 5,
        'festivo': 6
    }
    
    candidates.sort(key=lambda x: (x['dias_faltantes'], type_priority.get(x['tipo'], 10), x['titulo']))

    # Formateo de etiquetas legibles en español
    meses_es = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    dias_semana_es = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']

    for c in candidates:
        ev_d = c['fecha']
        c['fecha_formateada'] = f"{ev_d.day} {meses_es[ev_d.month - 1]}"
        c['fecha_completa'] = f"{ev_d.day:02d}/{ev_d.month:02d}/{ev_d.year}"
        c['dia_semana'] = dias_semana_es[ev_d.weekday()]
        
        if c['dias_faltantes'] == 0:
            c['tiempo_relativo'] = '¡Hoy!'
            c['urgencia_badge'] = 'bg-danger text-white fw-bold shadow-sm'
        elif c['dias_faltantes'] == 1:
            c['tiempo_relativo'] = 'Mañana'
            c['urgencia_badge'] = 'bg-warning text-dark fw-bold'
        elif c['dias_faltantes'] <= 7:
            c['tiempo_relativo'] = f"En {c['dias_faltantes']} días"
            c['urgencia_badge'] = 'bg-info-subtle text-info border border-info'
        else:
            c['tiempo_relativo'] = f"En {c['dias_faltantes']} días"
            c['urgencia_badge'] = 'bg-secondary-subtle text-secondary border'

    return candidates[:limit]
