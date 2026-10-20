import sys
import json
sys.path.insert(0, r'c:\Users\Germa\OneDrive\Trabajo\CRM')

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from database import db
from app import app

print("=" * 60)
print("VERIFICACIÓN EN TIEMPO REAL DEL FILTRO DE LOGOS Y AFIP")
print("=" * 60)

conn = db.get_db()

# 1. Chequeo de QR de AFIP en toda la base de datos
r_qr = conn.execute("SELECT COUNT(id) as c FROM propiedades WHERE fotos_json LIKE '%qr-registro%' OR foto_url LIKE '%qr-registro%'").fetchone()
print(f"\n1. Conteo de 'qr-registro' en toda la DB: {r_qr['c']} (antes eran 4.165)")

# 2. Chequeo específico de la propiedad que pasaste (19154)
r_19154 = conn.execute("SELECT id, titulo, foto_url, fotos_json FROM propiedades WHERE id = 19154").fetchone()
fotos_19154 = json.loads(r_19154['fotos_json']) if r_19154['fotos_json'] else []
tiene_qr = any('qr-registro' in f for f in fotos_19154)
print(f"\n2. Propiedad #19154 ({r_19154['titulo']}):")
print(f"   - Total fotos en galería: {len(fotos_19154)}")
print(f"   - ¿Tiene el logo de AFIP en sus fotos?: {tiene_qr}")
print(f"   - Foto de portada: {r_19154['foto_url']}")

# 3. Chequeo de la propiedad de Salaya Romera (#10036)
r_10036 = conn.execute("SELECT id, titulo, foto_url, fotos_json FROM propiedades WHERE id = 10036").fetchone()
fotos_10036 = json.loads(r_10036['fotos_json']) if r_10036['fotos_json'] else []
tiene_logo_salaya = any('1861010174' in f for f in fotos_10036) or ('1861010174' in str(r_10036['foto_url']))
print(f"\n3. Propiedad #10036 (Salaya Romera):")
print(f"   - ¿Tiene el cartel rosa de Salaya Romera?: {tiene_logo_salaya}")
print(f"   - Foto de portada actual: {r_10036['foto_url']}")

# 4. Chequeo de la propiedad de Braun (#18398)
r_18398 = conn.execute("SELECT id, titulo, foto_url, fotos_json FROM propiedades WHERE id = 18398").fetchone()
fotos_18398 = json.loads(r_18398['fotos_json']) if r_18398['fotos_json'] else []
tiene_logo_braun = any('1986705074' in f for f in fotos_18398) or ('1986705074' in str(r_18398['foto_url']))
print(f"\n4. Propiedad #18398 (Braun):")
print(f"   - ¿Tiene el logo negro de Braun?: {tiene_logo_braun}")
print(f"   - Foto de portada actual: {r_18398['foto_url']}")

# 5. Prueba de renderizado HTTP real en Flask
print("\n5. Renderizado web real en Flask:")
with app.test_client() as client:
    # Ficha 19154
    resp_ficha = client.get('/portal/propiedad/19154')
    html_ficha = resp_ficha.get_data(as_text=True)
    qr_en_html = 'qr-registro' in html_ficha
    print(f"   - GET /portal/propiedad/19154: Status {resp_ficha.status_code}, ¿Aparece QR en el HTML?: {qr_en_html}")

    # Catálogo /portal
    resp_portal = client.get('/portal')
    html_portal = resp_portal.get_data(as_text=True)
    salaya_en_portal = '1861010174' in html_portal
    braun_en_portal = '1986705074' in html_portal
    print(f"   - GET /portal: Status {resp_portal.status_code}")
    print(f"   - ¿Aparece logo Salaya en el catálogo?: {salaya_en_portal}")
    print(f"   - ¿Aparece logo Braun en el catálogo?: {braun_en_portal}")

print("\n" + "=" * 60)
print("TODAS LAS PRUEBAS COMPLETADAS")
print("=" * 60)
