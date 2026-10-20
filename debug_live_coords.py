from scrapers.live_probes import LiveProber
import json

prober = LiveProber()
# Use a known zone and type
zona = "Villa Pueyrredón, CABA"
tipo = "PH"
ambientes = "3"

print(f"Probing {zona} for {tipo} ({ambientes} amb)...")
results = prober.probe_all(zona, tipo, ambientes)

print(f"Found {len(results)} results.")
coords_count = 0
for r in results:
    if r.get('lat') and r.get('lng'):
        coords_count += 1
        # print(f"  Result: {r.get('lat')}, {r.get('lng')}")

print(f"Results with coordinates: {coords_count}")
if results:
    print("Sample result keys:", results[0].keys())
