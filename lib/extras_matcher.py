"""
Módulo de validación y matching inteligente de extras y comodidades inmobiliarias.
Evita falsos positivos como:
- Cochera: 'sin cochera', 'posibilidad de cochera en alquiler', 'cochera optativa'
- Pileta: 'pileta de cocina', 'pileta de lavar', 'pileta lavadero', 'pileta bacha', 'sin pileta'
- Jardín / Patio: 'Jardín Botánico', 'Jardín Japonés', 'jardín de infantes', 'vista al jardín común', 'sin patio'
- Parrilla: 'restaurantes y parrillas', 'polo gastronómico de parrillas', 'sin parrilla'
- Balcón: 'balcón francés', 'sin balcón'
- Terraza: 'sin terraza'
"""
import re

def normalizar_texto(t):
    if not t:
        return ""
    from unicodedata import normalize
    clean = re.sub(r"([^n\u0300-\u036f]|n(?!\u0303(?![\u0300-\u036f])))[\u0300-\u036f]+", r"\1", 
                   normalize("NFD", str(t)), 0, re.I)
    return clean.lower()


def tiene_cochera(p, text_corpus=None):
    """
    Determina si una propiedad posee cochera/garage propio o incluido.
    """
    if not isinstance(p, dict):
        p = {}

    coch_val = p.get('cocheras')
    if coch_val is not None:
        try:
            num = int(coch_val)
            if num > 0:
                desc_check = normalizar_texto(str(p.get('descripcion') or '') + ' ' + str(p.get('titulo') or ''))
                if re.search(r'\b(?:esta unidad no posee cochera|propiedad sin cochera|sin cochera propia)\b', desc_check):
                    return False
                return True
            elif num == 0:
                return False
        except (ValueError, TypeError):
            pass

    corpus_parts = []
    if text_corpus:
        corpus_parts.append(str(text_corpus))
    for k in ('titulo', 'descripcion', 'caracteristicas', 'features_text', 'direccion', 'notas'):
        val = p.get(k)
        if val:
            corpus_parts.append(str(val))

    full_text = normalizar_texto(" ".join(corpus_parts))
    if not full_text:
        return False

    negative_patterns = [
        r'\b(?:sin|no\s+posee|no\s+cuenta\s+con|no\s+tiene|no\s+incluye)\s+(?:cochera|cocheras|garage|garaje|espacio\s+guardacoche|guardacoche|lugar\s+para\s+auto)\b',
        r'\b(?:propiedad|unidad|departamento|depto|ph|casa)\s+sin\s+cochera\b',
        r'\bcochera[s]?\s+(?:no\s+incluida[s]?|no\s+incluye|optativa[s]?|a\s+la\s+vuelta|en\s+alquiler|disponible\s+para\s+alquilar|de\s+cortesia|opcional(?:es)?)\b',
        r'\bposibilidad\s+de\s+(?:alquilar|comprar|alquiler\s+de)\s+cochera\b',
        r'\bopcion\s+(?:de\s+|a\s+)?cochera\b',
        r'\b0\s+cochera[s]?\b',
        r'\b0\s+coch\b',
        r'\bno\s+posee\s+cochera\b',
        r'\bno\s+tiene\s+cochera\b'
    ]

    for neg_pat in negative_patterns:
        if re.search(neg_pat, full_text):
            if not re.search(r'\b(?:incluye|posee|cuenta\s+con)\s+(?:\d+\s+)?(?:cochera[s]?|garage|garaje|espacio\s+guardacoche)\s+(?:fija|cubierta|propia|descubierta|doble|subterranea|escriturada)\b', full_text):
                return False

    positive_patterns = [
        r'\b\d+\s*(?:cochera[s]?|coch[.]?|garage[s]?|garaje[s]?|guardacoche[s]?|espacio[s]?\s+guardacoche)\b',
        r'\b(?:con|incluye|posee|cuenta\s+con|mas)\s+(?:\d+\s+)?(?:cochera[s]?|coch[.]?|garage[s]?|garaje[s]?|guardacoche[s]?|espacio\s+guardacoche|lugar\s+para\s+auto|entrada\s+de\s+auto|entrada\s+para\s+auto)\b',
        r'\bcochera[s]?\s+(?:fija[s]?|cubierta[s]?|descubierta[s]?|doble[s]?|propia[s]?|en\s+subsuelo|subterranea[s]?|movil|semi[\s-]?cubierta[s]?|incluida[s]?|escriturada[s]?)\b',
        r'\b(?:espacio\s+guardacoche|guardacoche[s]?|entrada\s+para\s+auto|lugar\s+para\s+auto|espacio\s+guarda\s+coche)\b',
        r'\bcomoda\s+cochera\b',
        r'\bexcelente\s+cochera\b',
        r'\bgran\s+cochera\b',
        r'\bc\/cochera\b',
        r'\bc\/coch\b',
        r'\bc\/garage\b',
        r'\bcon\s+cochera\b',
        r'\bcon\s+garage\b',
        r'\bgarage\s+(?:cubierto|descubierto|doble|propio|para\s+\d+\s+auto[s]?)\b'
    ]

    for pos_pat in positive_patterns:
        if re.search(pos_pat, full_text):
            return True

    return False


def tiene_pileta(p, text_corpus=None):
    """
    Determina si una propiedad tiene pileta/piscina de natación o amenities de piscina.
    Descarta explícitamente piletas de cocina, piletas de lavar, piletas bacha y negativos.
    """
    corpus_parts = []
    if text_corpus:
        corpus_parts.append(str(text_corpus))
    for k in ('titulo', 'descripcion', 'caracteristicas', 'features_text'):
        val = p.get(k)
        if val:
            corpus_parts.append(str(val))

    full_text = normalizar_texto(" ".join(corpus_parts))
    if not full_text:
        return False

    # 1. Chequeo de piscina / natatorio / jacuzzi (términos no ambiguos)
    if re.search(r'\b(?:piscina|piscinas|natatorio|natatorios|jacuzzi|hidromasaje|mini\s+piscina)\b', full_text):
        if not re.search(r'\b(?:sin|no\s+posee|no\s+cuenta\s+con|no\s+tiene)\s+(?:piscina|natatorio)\b', full_text):
            return True

    # 2. Si sólo dice "pileta", verificar que NO sea pileta de cocina/lavadero ni negativo
    # Limpiar falsos positivos de lavadero/cocina
    text_limpio = re.sub(r'\bpileta\s+(?:de\s+)?(?:cocina|lavar|lavadero|patio|acero|acero\s+inoxidable|johnson|bacha|doble\s+bacha)\b', '', full_text)
    text_limpio = re.sub(r'\bpileta\s+lavadero\b', '', text_limpio)
    text_limpio = re.sub(r'\b(?:sin|no\s+posee|no\s+cuenta\s+con|no\s+tiene)\s+pileta\b', '', text_limpio)

    if re.search(r'\b(?:pileta|piletas|solarium\s+con\s+pileta|pileta\s+climatizada|pileta\s+propia|pileta\s+olimpica|con\s+pileta|posee\s+pileta|cuenta\s+con\s+pileta|sector\s+pileta|amenities\s+con\s+pileta)\b', text_limpio):
        return True

    return False


def tiene_patio_jardin(p, text_corpus=None):
    """
    Determina si una propiedad tiene patio o jardín propio.
    Descarta 'Jardín Botánico', 'Jardín Japonés', 'jardín de infantes', etc.
    """
    corpus_parts = []
    if text_corpus:
        corpus_parts.append(str(text_corpus))
    for k in ('titulo', 'descripcion', 'caracteristicas', 'features_text'):
        val = p.get(k)
        if val:
            corpus_parts.append(str(val))

    full_text = normalizar_texto(" ".join(corpus_parts))
    if not full_text:
        return False

    # Descartar 'jardin botanico', 'jardin japones', 'jardin de infantes', etc.
    text_limpio = re.sub(r'\bjardin\s+(?:botanico|japones|de\s+infantes|maternal|infantil)\b', '', full_text)
    text_limpio = re.sub(r'\b(?:sin|no\s+posee|no\s+cuenta\s+con|no\s+tiene)\s+(?:patio|jardin)\b', '', text_limpio)

    # Positivos de patio / jardín
    if re.search(r'\b(?:patio|patios|jardin|jardines|parquizado|parque|fondo\s+libre|fondo\s+con\s+verde|espacio\s+verde|patio\s+propio|jardin\s+propio|patio\s+con\s+parrilla|patio\s+al\s+frente|patio\s+trasero|con\s+patio|con\s+jardin|posee\s+patio|posee\s+jardin|c\/patio|c\/jardin)\b', text_limpio):
        return True

    return False


def tiene_parrilla(p, text_corpus=None):
    """
    Determina si una propiedad tiene parrilla o quincho.
    Descarta restaurantes, polos gastronómicos y negativos.
    """
    corpus_parts = []
    if text_corpus:
        corpus_parts.append(str(text_corpus))
    for k in ('titulo', 'descripcion', 'caracteristicas', 'features_text'):
        val = p.get(k)
        if val:
            corpus_parts.append(str(val))

    full_text = normalizar_texto(" ".join(corpus_parts))
    if not full_text:
        return False

    # Descartar restaurantes gastronómicos
    text_limpio = re.sub(r'\b(?:restaurantes?\s*(?:y|,)\s*parrillas?|polo\s+gastronomico|parrilla\s+don\s+julio|parrilla\s+restaurante)\b', '', full_text)
    text_limpio = re.sub(r'\b(?:sin|no\s+posee|no\s+cuenta\s+con|no\s+tiene)\s+(?:parrilla|quincho|asador)\b', '', text_limpio)

    if re.search(r'\b(?:parrilla|parrillas|quincho|quinchos|asador|asadores|parrillero|parrilleros|con\s+parrilla|posee\s+parrilla|cuenta\s+con\s+parrilla|parrilla\s+propia|parrilla\s+individual|parrilla\s+en\s+balcon|parrilla\s+en\s+terraza|sector\s+parrillas?|quincho\s+con\s+parrilla|c\/parrilla)\b', text_limpio):
        return True

    return False


def tiene_balcon(p, text_corpus=None):
    """
    Determina si una propiedad tiene balcón real (excluyendo balcón francés).
    """
    corpus_parts = []
    if text_corpus:
        corpus_parts.append(str(text_corpus))
    for k in ('titulo', 'descripcion', 'caracteristicas', 'features_text'):
        val = p.get(k)
        if val:
            corpus_parts.append(str(val))

    full_text = normalizar_texto(" ".join(corpus_parts))
    if not full_text:
        return False

    # Balcón francés no es un balcón transitable real
    text_limpio = re.sub(r'\bbalcon\s+frances\b', '', full_text)
    text_limpio = re.sub(r'\b(?:sin|no\s+posee|no\s+cuenta\s+con|no\s+tiene)\s+balcon\b', '', text_limpio)

    if re.search(r'\b(?:balcon|balcones|balcon\s+al\s+frente|balcon\s+al\s+contrafrente|balcon\s+corrido|balcon\s+terraza|balcon\s+aterrazado|con\s+balcon|posee\s+balcon|cuenta\s+con\s+balcon|c\/balcon|salida\s+al\s+balcon)\b', text_limpio):
        return True

    return False


def tiene_terraza(p, text_corpus=None):
    """
    Determina si una propiedad tiene terraza.
    """
    corpus_parts = []
    if text_corpus:
        corpus_parts.append(str(text_corpus))
    for k in ('titulo', 'descripcion', 'caracteristicas', 'features_text'):
        val = p.get(k)
        if val:
            corpus_parts.append(str(val))

    full_text = normalizar_texto(" ".join(corpus_parts))
    if not full_text:
        return False

    text_limpio = re.sub(r'\b(?:sin|no\s+posee|no\s+cuenta\s+con|no\s+tiene)\s+terraza\b', '', full_text)

    if re.search(r'\b(?:terraza|terrazas|terraza\s+propia|terraza\s+exclusiva|terraza\s+privada|azotea|azotea\s+transitable|con\s+terraza|posee\s+terraza|cuenta\s+con\s+terraza|c\/terraza|salida\s+a\s+terraza|balcon\s+aterrazado)\b', text_limpio):
        return True

    return False


def tiene_extra(p, extra_name, text_corpus=None):
    """Evalúa un extra individual con su validador específico."""
    ex = normalizar_texto(extra_name).strip()
    if not ex:
        return True

    if ex in ('cochera', 'cocheras', 'garage', 'garaje', 'guardacoche'):
        return tiene_cochera(p, text_corpus)

    if ex in ('pileta', 'piscina', 'natatorio'):
        return tiene_pileta(p, text_corpus)

    if ex in ('patio', 'jardin', 'parque'):
        return tiene_patio_jardin(p, text_corpus)

    if ex in ('parrilla', 'quincho', 'asador'):
        return tiene_parrilla(p, text_corpus)

    if ex in ('balcon', 'balcones'):
        return tiene_balcon(p, text_corpus)

    if ex in ('terraza', 'terrazas'):
        return tiene_terraza(p, text_corpus)

    if ex in ('sum', 'salon'):
        corpus_parts = []
        if text_corpus: corpus_parts.append(str(text_corpus))
        for k in ('titulo', 'descripcion', 'caracteristicas'):
            v = p.get(k)
            if v: corpus_parts.append(str(v))
        full = normalizar_texto(" ".join(corpus_parts))
        return bool(re.search(r'\b(?:sum|salon\s+de\s+usos\s+multiples|salon\s+de\s+fiestas|amenities)\b', full))

    corpus_parts = []
    if text_corpus: corpus_parts.append(str(text_corpus))
    for k in ('titulo', 'descripcion', 'caracteristicas'):
        v = p.get(k)
        if v: corpus_parts.append(str(v))
    full = normalizar_texto(" ".join(corpus_parts))
    return ex in full


def coincide_extras(p, extras, text_corpus=None):
    """
    Verifica que la propiedad cumpla con TODOS los extras solicitados.
    """
    if not extras:
        return True
    if isinstance(extras, str):
        extras = [extras]

    for ex in extras:
        if not ex:
            continue
        if not tiene_extra(p, ex, text_corpus):
            return False
    return True
