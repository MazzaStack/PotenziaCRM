import re
import json
from curl_cffi import requests
from bs4 import BeautifulSoup

def inspect_zp():
    url = "https://www.zonaprop.com.ar/departamentos-venta-palermo.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
    }
    print(f"Fetching ZP: {url}")
    try:
        resp = requests.get(url, impersonate='chrome', headers=headers, timeout=20)
        print(f"ZP Status: {resp.status_code}")
        if resp.status_code != 200:
            return
            
        soup = BeautifulSoup(resp.text, 'lxml')
        script = soup.find('script', string=re.compile(r'window\.__INITIAL_STATE__\s*='))
        if script:
            print("Found INITIAL_STATE")
            json_text = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', script.string, re.DOTALL).group(1)
            state = json.loads(json_text)
            postings = state.get('listStore', {}).get('listPostings', [])
            if postings:
                p = postings[0]
                # Look for geolocation
                loc = p.get('location', {}).get('postingGeolocation', {})
                print(f"Geolocation: {loc}")
                # Look for bedrooms/rooms
                mf = p.get('mainFeatures', {})
                print(f"Bedrooms: {mf.get('bedrooms', {}).get('value')}")
                print(f"Rooms: {mf.get('rooms', {}).get('value')}")
        else:
            print("INITIAL_STATE NOT FOUND in ZP")
    except Exception as e:
        print(f"ZP Error: {e}")

def inspect_ml():
    url = "https://inmuebles.mercadolibre.com.ar/departamento/venta/palermo"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    print(f"Fetching ML: {url}")
    try:
        resp = requests.get(url, impersonate='chrome', headers=headers, timeout=20)
        print(f"ML Status: {resp.status_code}")
        if resp.status_code != 200:
            return
            
        soup = BeautifulSoup(resp.text, 'lxml')
        # Check if there is any script with data
        scripts = soup.find_all('script')
        for s in scripts:
            if s.string and 'window.__search_data' in s.string:
                print("Found search data in ML")
                break
        
        # Check first card for data attributes
        card = soup.select_one('.ui-search-result__wrapper') or soup.select_one('.poly-card')
        if card:
             print(f"Card snippet: {str(card)[:200]}...")
    except Exception as e:
        print(f"ML Error: {e}")

if __name__ == "__main__":
    inspect_zp()
    print("-" * 30)
    inspect_ml()
