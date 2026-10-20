from scrapers.live_probes import LiveProber
import os

def save_scripts():
    prober = LiveProber()
    url = "https://www.zonaprop.com.ar/departamentos-venta-palermo-2-ambientes.html"
    print(f"Fetching {url}")
    soup = prober.fetch(url)
    if not soup:
        print("Failed to fetch soup")
        return

    scripts = soup.find_all('script')
    output_file = "/tmp/zp_scripts.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        for i, s in enumerate(scripts):
            f.write(f"\n\n--- SCRIPT {i} ---\n")
            if s.string:
                f.write(s.string)
            elif s.get('src'):
                f.write(f"External: {s.get('src')}")
    
    print(f"Scripts saved to {output_file}. Search for property prices or keywords there.")

if __name__ == "__main__":
    save_scripts()
