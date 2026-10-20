from scrapers.live_probes import LiveProber
import json

def debug_search():
    prober = LiveProber()
    zona = "Palermo"
    tipo = "departamento"
    
    print(f"--- Probando Búsqueda: {zona} | {tipo} ---")
    
    print("\n[Zonaprop]")
    res_zp = prober.search_zonaprop(zona, tipo, ambientes=2)
    print(f"Resultados encontrados: {len(res_zp)}")
    if res_zp:
        print(f"Muestra: {res_zp[0]['titulo']} - {res_zp[0]['precio']} {res_zp[0]['moneda']}")
    
    print("\n[MercadoLibre]")
    res_ml = prober.search_mercadolibre(zona, tipo, ambientes=2)
    print(f"Resultados encontrados: {len(res_ml)}")
    if res_ml:
        print(f"Muestra: {res_ml[0]['titulo']} - {res_ml[0]['precio']} {res_ml[0]['moneda']}")

if __name__ == "__main__":
    debug_search()
