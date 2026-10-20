import pandas as pd
import os
import sys

# Ensure we can import from the current directory (database)
sys.path.append(os.getcwd())
from database import db

def run_import():
    xl_path = 'base_temp.xlsx'
    if not os.path.exists(xl_path):
        print(f"Error: {xl_path} not found")
        return
        
    df = pd.read_excel(xl_path)
    cols = df.columns.tolist()
    
    # Refining mapping for German's specific Excel
    mapping = {
        'nombre': next((c for c in cols if 'nombre' in c.lower()), None),
        'apellido': next((c for c in cols if 'apellido' in c.lower()), None),
        'calificacion': next((c for c in cols if 'punti' in c.lower() or 'calific' in c.lower()), None),
        'categoria': next((c for c in cols if 'califica' in c.lower()), None),
        'ultimo_contacto': next((c for c in cols if 'ultimo' in c.lower() or 'contacto 12m' in c.lower()), None),
        'fecha_nacimiento': next((c for c in cols if 'cumple' in c.lower()), None),
        'rol': next((c for c in cols if 'rol' in c.lower() or 'perfil' in c.lower()), None),
        'referente': next((c for c in cols if 'refer' in c.lower()), None),
        'notas': next((c for c in cols if 'nota' in c.lower() or 'coment' in c.lower()), None),
        'telefono': next((c for c in cols if 'tel' in c.lower() or 'cel' in c.lower() or 'wapp' in c.lower()), None),
        'email': next((c for c in cols if 'mail' in c.lower()), None)
    }
    
    print(f"Detected mapping: {mapping}")
    
    count = 0
    for _, row in df.iterrows():
        # Get name and surname, if none, skip
        nom = str(row[mapping['nombre']]).strip() if mapping['nombre'] and pd.notnull(row[mapping['nombre']]) else ''
        ape = str(row[mapping['apellido']]).strip() if mapping['apellido'] and pd.notnull(row[mapping['apellido']]) else ''
        
        if not nom and not ape:
            continue

        # Phone handling
        tel = str(row[mapping['telefono']]) if mapping['telefono'] and pd.notnull(row[mapping['telefono']]) else None
        
        # Date handling (Timestamp to string)
        u_con = row[mapping['ultimo_contacto']] if mapping['ultimo_contacto'] and pd.notnull(row[mapping['ultimo_contacto']]) else None
        if hasattr(u_con, 'strftime'): u_con = u_con.strftime('%Y-%m-%d')
        elif isinstance(u_con, str) and ' ' in u_con: u_con = u_con.split(' ')[0]
        
        f_nac = row[mapping['fecha_nacimiento']] if mapping['fecha_nacimiento'] and pd.notnull(row[mapping['fecha_nacimiento']]) else None
        if hasattr(f_nac, 'strftime'): f_nac = f_nac.strftime('%Y-%m-%d')
        elif isinstance(f_nac, str) and ' ' in f_nac: f_nac = f_nac.split(' ')[0]

        # Categorization Handling
        cat_val = str(row[mapping['categoria']]).upper() if mapping['categoria'] and pd.notnull(row[mapping['categoria']]) else 'C'
        # If calificacion is the same as category (letters), reset it to 0
        cal_raw = row[mapping['calificacion']] if mapping['calificacion'] and pd.notnull(row[mapping['calificacion']]) else 0
        try:
            cal_val = int(cal_raw)
        except:
            cal_val = 0 # Default if its a letter like 'A' or 'B'

        data = {
            'nombre': nom,
            'apellido': ape,
            'calificacion': cal_val,
            'categoria': cat_val,
            'ultimo_contacto': u_con,
            'fecha_nacimiento': f_nac,
            'rol': str(row[mapping['rol']]) if mapping['rol'] and pd.notnull(row[mapping['rol']]) else '',
            'referente': str(row[mapping['referente']]) if mapping['referente'] and pd.notnull(row[mapping['referente']]) else '',
            'notas': str(row[mapping['notas']]) if mapping['notas'] and pd.notnull(row[mapping['notas']]) else '',
            'telefono': tel,
            'email': str(row[mapping['email']]) if mapping['email'] and pd.notnull(row[mapping['email']]) else ''
        }
        
        try:
            if db.insert_contacto(data):
                count += 1
                if count % 20 == 0:
                    print(f"Progress: {count} contacts...")
        except Exception as e:
            print(f"Row error: {e}")
                
    print(f"Synchronization complete! {count} contacts processed.")

if __name__ == "__main__":
    run_import()
