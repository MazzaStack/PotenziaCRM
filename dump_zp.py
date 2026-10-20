from scrapers.live_probes import LiveProber
import json
import re

def dump_zonaprop_state():
    prober = LiveProber()
    url = "https://www.zonaprop.com.ar/departamentos-venta-palermo-2-ambientes.html"
    print(f"Fetching {url}")
    soup = prober.fetch(url)
    if not soup:
        print("Failed to fetch soup")
        return

    scripts = soup.find_all('script')
    print(f"Total scripts found: {len(scripts)}")
    
    found_any = False
    for i, s in enumerate(scripts):
        if s.string and 'INITIAL_STATE' in s.string:
            found_any = True
            print(f"\n--- Script {i} contains 'INITIAL_STATE' ---")
            print(f"Length: {len(s.string)}")
            
            # Simple regex to find the first large JSON object
            match = re.search(r'(\{.*\})', s.string, re.DOTALL)
            if match:
                try:
                    # Try to fix truncated or dirty JSON if needed
                    raw_json = match.group(1)
                    # Often window.__INITIAL_STATE__ = { ... }; - we need to strip until final }
                    if raw_json.endswith(';'): raw_json = raw_json[:-1]
                    
                    data = json.loads(raw_json)
                    print(f"Successfully parsed JSON from script {i}")
                    print("Top level keys:", list(data.keys()))
                    
                    if 'listStore' in data:
                        print("Found 'listStore'")
                        ps = data['listStore'].get('listPostings', [])
                        print(f"Postings found: {len(ps)}")
                        if ps:
                            print("Sample posting keys:", list(ps[0].keys()))
                    elif 'searchStore' in data:
                        print("Found 'searchStore' instead of 'listStore'")
                        # Check recursively for postings
                        if 'listPostings' in str(data):
                            print("'listPostings' exists somewhere in data")
                except Exception as e:
                    print(f"Failed to parse JSON from script {i}: {e}")
                    print(f"Snippet: {s.string[:200]}...")

    if not found_any:
        print("No script containing 'INITIAL_STATE' was found.")

if __name__ == "__main__":
    dump_zonaprop_state()
