import re
import json
from curl_cffi import requests
from bs4 import BeautifulSoup

def inspect_zp_jsonld():
    url = "https://www.zonaprop.com.ar/departamentos-venta-palermo.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    print(f"Fetching ZP: {url}")
    resp = requests.get(url, impersonate='chrome', headers=headers)
    if resp.status_code != 200:
        print(f"Error {resp.status_code}")
        return
        
    soup = BeautifulSoup(resp.text, 'lxml')
    # Search for all scripts of type ld+json
    ld_scripts = soup.find_all('script', type='application/ld+json')
    print(f"Found {len(ld_scripts)} ld+json scripts")
    for i, script in enumerate(ld_scripts):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                # Usually it's a list of ItemList or similar
                for item in data:
                    print(f"Script {i} item type: {item.get('@type')}")
                    if item.get('@type') == 'ItemList':
                        elements = item.get('itemListElement', [])
                        if elements:
                            first = elements[0].get('item', {})
                            print(f"First item keys: {first.keys()}")
                            print(f"Geolocation in JSON-LD? {first.get('geo')}")
            else:
                print(f"Script {i} type: {data.get('@type')}")
        except Exception as e:
            print(f"Error parsing script {i}: {e}")

if __name__ == "__main__":
    inspect_zp_jsonld()
