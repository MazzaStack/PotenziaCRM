"""
scripts/limpiar_logos_y_afip_db.py
Script de limpieza integral para remover logos de inmobiliarias y QR de AFIP
en la base de datos de propiedades de Potenzia CRM.
"""
import sys
import os
import json
import argparse

# Asegurar path raíz del proyecto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from database import db
from lib.photo_sanitizer import (
    is_junk_url,
    sanitize_property_photos,
    KNOWN_LOGO_DHASHES,
    check_image_url_is_logo
)

KNOWN_LOGO_SNIPPETS = [
    '1861010174', # Salaya Romera banner
    '1986705074', # Braun banner
]

def run_cleanup(dry_run=False, check_all_covers=False):
    print("=" * 70)
    print("🧹 INICIANDO LIMPIEZA DE LOGOS DE INMOBILIARIAS Y QR DE AFIP EN LA BASE DE DATOS")
    print(f"Modo: {'DRY-RUN (Simulación sin modificar DB)' if dry_run else 'EJECUCIÓN REAL (Guardando cambios)'}")
    print("=" * 70)

    conn = db.get_db()
    
    # ─────────────────────────────────────────────────────────────
    # PASO 1: LIMPIEZA MASIVA DE QR DE AFIP Y URLs DESCARTABLES
    # ─────────────────────────────────────────────────────────────
    print("\n🔍 Paso 1: Buscando propiedades con QR de AFIP o URLs descartables...")
    
    rows_qr = conn.execute("""
        SELECT id, titulo, foto_url, fotos_json 
        FROM propiedades 
        WHERE fotos_json LIKE '%qr-registro%'
           OR fotos_json LIKE '%data-fiscal%'
           OR fotos_json LIKE '%naventcdn%'
           OR fotos_json LIKE '%afip%'
           OR foto_url LIKE '%qr-registro%'
           OR foto_url LIKE '%data-fiscal%'
    """).fetchall()
    
    print(f"Encontradas {len(rows_qr)} propiedades con QR de AFIP en fotos_json o portada.")
    
    cleaned_qr_count = 0
    batch_updates_qr = []
    
    for r in rows_qr:
        prop_id = r['id']
        foto_url = r['foto_url']
        fotos = []
        if r['fotos_json']:
            try:
                fotos = json.loads(r['fotos_json']) if isinstance(r['fotos_json'], str) else r['fotos_json']
            except Exception:
                fotos = []
                
        clean_cover, clean_fotos, changed = sanitize_property_photos(foto_url, fotos, check_cover_content=False)
        
        if changed:
            cleaned_qr_count += 1
            fotos_json_val = json.dumps(clean_fotos) if clean_fotos else None
            batch_updates_qr.append((clean_cover, fotos_json_val, prop_id))
            
    print(f"Propiedades listas para purgar de QR de AFIP: {cleaned_qr_count}")
    
    if not dry_run and batch_updates_qr:
        print("💾 Aplicando limpieza de QR en la base de datos...")
        for clean_cover, fotos_json_val, prop_id in batch_updates_qr:
            conn.execute("""
                UPDATE propiedades 
                SET foto_url = ?, fotos_json = ? 
                WHERE id = ?
            """, (clean_cover, fotos_json_val, prop_id))
        conn.commit()
        print(f"✅ Se purgaron exitosamente {len(batch_updates_qr)} propiedades.")

    # ─────────────────────────────────────────────────────────────
    # PASO 2: CORRECCIÓN DE PORTADAS CON LOGOS DE INMOBILIARIAS
    # ─────────────────────────────────────────────────────────────
    print("\n🔍 Paso 2: Buscando propiedades con portadas de logos de inmobiliarias (Salaya Romera, Braun, etc.)...")
    
    # Buscar por identificadores conocidos de fotos de logos
    conds = " OR ".join([f"foto_url LIKE '%{snip}%'" for snip in KNOWN_LOGO_SNIPPETS])
    rows_logos = conn.execute(f"""
        SELECT id, titulo, foto_url, fotos_json 
        FROM propiedades 
        WHERE {conds}
    """).fetchall()
    
    print(f"Encontradas {len(rows_logos)} propiedades con coincidencia directa de logo en portada.")
    
    fixed_logo_count = 0
    batch_updates_logos = []
    
    for r in rows_logos:
        prop_id = r['id']
        foto_url = r['foto_url']
        fotos = []
        if r['fotos_json']:
            try:
                fotos = json.loads(r['fotos_json']) if isinstance(r['fotos_json'], str) else r['fotos_json']
            except Exception:
                fotos = []
                
        # Promover la siguiente foto real
        clean_cover, clean_fotos, changed = sanitize_property_photos(foto_url, fotos, check_cover_content=True)
        
        # Si la portada anterior era el logo conocido, asegurarse de pasar a la foto 2
        if any(snip in str(clean_cover) for snip in KNOWN_LOGO_SNIPPETS):
            clean_list_without_logo = [u for u in clean_fotos if not any(snip in str(u) for snip in KNOWN_LOGO_SNIPPETS)]
            clean_cover = clean_list_without_logo[0] if clean_list_without_logo else None
            clean_fotos = clean_list_without_logo
            changed = True
            
        if changed:
            fixed_logo_count += 1
            print(f"  • Propiedad #{prop_id} ('{r['titulo'][:45]}...'): Logo removido de portada. Nueva portada: {clean_cover}")
            fotos_json_val = json.dumps(clean_fotos) if clean_fotos else None
            batch_updates_logos.append((clean_cover, fotos_json_val, prop_id))
            
    if not dry_run and batch_updates_logos:
        print("💾 Aplicando corrección de portadas de logos en la base de datos...")
        for clean_cover, fotos_json_val, prop_id in batch_updates_logos:
            conn.execute("""
                UPDATE propiedades 
                SET foto_url = ?, fotos_json = ? 
                WHERE id = ?
            """, (clean_cover, fotos_json_val, prop_id))
        conn.commit()
        print(f"✅ Se corrigieron exitosamente {len(batch_updates_logos)} portadas con logos.")

    print("\n" + "=" * 70)
    print("🎉 RESUMEN DE LIMPIEZA FINALIZADA:")
    print(f"  - Propiedades limpiadas de QR de AFIP: {cleaned_qr_count}")
    print(f"  - Portadas corregidas (reemplazo de logo por foto real): {fixed_logo_count}")
    print(f"  - Estado en Base de Datos: {'SIMULADO (sin cambios)' if dry_run else 'ACTUALIZADO Y GUARDADO'}")
    print("=" * 70)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Limpiar logos de inmobiliarias y QR de AFIP en DB")
    parser.add_argument('--dry-run', action='store_true', help="Simular sin modificar la base de datos")
    parser.add_argument('--check-all', action='store_true', help="Descargar y verificar portadas con dHash")
    args = parser.parse_args()
    
    run_cleanup(dry_run=args.dry_run, check_all_covers=args.check_all)
