"""
lib/photo_sanitizer.py - Módulo para detección y filtrado de logos de inmobiliarias y QR de AFIP
"""
import re
import io
import urllib.request
from PIL import Image

# ─────────────────────────────────────────────────────────────
# 1. EXPRESIONES REGULARES DE URLs DESCARTABLES (AFIP, QR, JUNK)
# ─────────────────────────────────────────────────────────────

JUNK_URL_PATTERNS = [
    re.compile(r'qr[-_]registro', re.IGNORECASE),
    re.compile(r'data[-_]fiscal', re.IGNORECASE),
    re.compile(r'naventcdn\.com/.*/qr', re.IGNORECASE),
    re.compile(r'qr[-_]code', re.IGNORECASE),
    re.compile(r'/qr\.(png|jpg|jpeg|webp)', re.IGNORECASE),
    re.compile(r'form_datafiscal', re.IGNORECASE),
    re.compile(r'afip[-_]', re.IGNORECASE),
    re.compile(r'[-_]afip\.', re.IGNORECASE),
    re.compile(r'placeholder', re.IGNORECASE),
    re.compile(r'sin[-_]foto', re.IGNORECASE),
    re.compile(r'no[-_]photo', re.IGNORECASE),
    re.compile(r'logo[-_]inmobiliaria', re.IGNORECASE),
]

# ─────────────────────────────────────────────────────────────
# 2. HUELLAS DIGITALES (dHash) DE LOGOS E IMÁGENES CONOCIDAS
# ─────────────────────────────────────────────────────────────

KNOWN_LOGO_DHASHES = {
    '0e6262663226e666': 'Salaya Romera Logo',
    '909312181b0ca4b3': 'Braun Logo',
    '9a4b2b332782dcae': 'AFIP QR Registro',
}

def is_junk_url(url):
    """Devuelve True si la URL corresponde a un QR de AFIP, logo descartable o placeholder."""
    if not url or not isinstance(url, str):
        return True
    clean = url.strip()
    if len(clean) < 10:
        return True
    for pat in JUNK_URL_PATTERNS:
        if pat.search(clean):
            return True
    return False

def compute_dhash(image, hash_size=8):
    """Calcula el Difference Hash (dHash) de 64 bits usando únicamente Pillow."""
    try:
        resized = image.convert('L').resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
        # Compatible con Pillow 10+
        if hasattr(resized, 'get_flattened_data'):
            pixels = list(resized.get_flattened_data())
        else:
            pixels = list(resized.getdata())
            
        diff = []
        for row in range(hash_size):
            for col in range(hash_size):
                pixel_left = pixels[row * (hash_size + 1) + col]
                pixel_right = pixels[row * (hash_size + 1) + col + 1]
                diff.append(pixel_left > pixel_right)
                
        decimal_val = 0
        hex_str = []
        for index, value in enumerate(diff):
            if value:
                decimal_val += 2 ** (index % 8)
            if (index % 8) == 7:
                hex_str.append(hex(decimal_val)[2:].rjust(2, '0'))
                decimal_val = 0
        return ''.join(hex_str)
    except Exception:
        return None

def hamming_distance(h1, h2):
    """Calcula la distancia de Hamming entre dos hashes hexadecimales."""
    if not h1 or not h2 or len(h1) != len(h2):
        return 999
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count('1')
    except Exception:
        return 999

def matches_known_logo(dhash_val, max_distance=6):
    """Verifica si el hash coincide con algún logo registrado."""
    if not dhash_val:
        return None
    for known_hash, name in KNOWN_LOGO_DHASHES.items():
        if hamming_distance(dhash_val, known_hash) <= max_distance:
            return name
    return None

def is_solid_color_banner(image):
    """
    Analiza si la imagen es un banner/logo publicitario con fondo sólido uniforme.
    """
    try:
        w, h = image.size
        cw, ch = max(2, int(w * 0.05)), max(2, int(h * 0.05))
        img_rgb = image.convert('RGB')
        
        corners = [
            img_rgb.crop((0, 0, cw, ch)),
            img_rgb.crop((w - cw, 0, w, ch)),
            img_rgb.crop((0, h - ch, cw, h)),
            img_rgb.crop((w - cw, h - ch, w, h))
        ]
        
        corner_colors = []
        for c in corners:
            stat = c.resize((1, 1)).getpixel((0, 0))
            corner_colors.append(stat)
            
        max_diff = 0
        for i in range(len(corner_colors)):
            for j in range(i + 1, len(corner_colors)):
                c1, c2 = corner_colors[i], corner_colors[j]
                diff = sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5
                if diff > max_diff:
                    max_diff = diff
                    
        if max_diff < 15.0:
            return True
            
        return False
    except Exception:
        return False

def check_image_url_is_logo(url, timeout=4):
    """Descarga y analiza si la URL corresponde a un logo de inmobiliaria o banner."""
    if is_junk_url(url):
        return True, "Junk URL (AFIP/Placeholder)"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        img = Image.open(io.BytesIO(data))
        
        dh = compute_dhash(img)
        logo_name = matches_known_logo(dh)
        if logo_name:
            return True, f"Known Logo ({logo_name})"
            
        if is_solid_color_banner(img):
            return True, "Solid Background Banner"
            
        return False, None
    except Exception as e:
        return False, None

# ─────────────────────────────────────────────────────────────
# 3. FUNCIÓN MAESTRA DE SANITIZACIÓN DE GALERÍA
# ─────────────────────────────────────────────────────────────

def sanitize_property_photos(foto_url, fotos_list, check_cover_content=False):
    """
    Sanitiza la foto principal y la galería de una propiedad.
    - Remueve URLs descartables (AFIP, QR, placeholders).
    - Si la foto principal es descartable o coincide con un logo, promueve la siguiente foto real.
    
    Retorna: (clean_foto_url, clean_fotos_list, changed)
    """
    changed = False
    
    # 1. Limpiar lista de fotos
    clean_list = []
    if fotos_list:
        for u in fotos_list:
            if isinstance(u, str) and u.strip() and not is_junk_url(u):
                clean_list.append(u.strip())
            else:
                changed = True
                
    # 2. Evaluar foto principal
    clean_cover = foto_url.strip() if (foto_url and isinstance(foto_url, str)) else None
    
    if clean_cover and is_junk_url(clean_cover):
        clean_cover = None
        changed = True
        
    # Si se pide chequear contenido visual (en lotes o batch)
    if check_cover_content and clean_cover:
        is_logo, _ = check_image_url_is_logo(clean_cover)
        if is_logo:
            if clean_cover in clean_list:
                clean_list.remove(clean_cover)
            clean_cover = None
            changed = True
            
    # Si la portada quedó vacía o nula, promover la primera foto limpia de la lista
    if not clean_cover and clean_list:
        clean_cover = clean_list[0]
        changed = True
        
    # Asegurar que la portada esté al inicio de clean_list
    if clean_cover and clean_cover not in clean_list:
        clean_list.insert(0, clean_cover)
        changed = True
        
    return clean_cover, clean_list, changed
