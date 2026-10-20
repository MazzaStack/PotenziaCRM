import re
import json
from curl_cffi import requests
from bs4 import BeautifulSoup

def inspect_zp():
    url = "https://www.zonaprop.com.ar/departamentos-venta-palermo.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    resp = requests.get(url, impersonate='chrome', headers=headers)
    if resp.status_code != 200:
        print("Error fetching")
        return
        
    soup = BeautifulSoup(resp.text, 'lxml')
    script = soup.find('script', string=re.compile(r'window\.__INITIAL_STATE__\s*='))
    if script:
        json_text = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', script.string, re.DOTALL).group(1)
        state = json.loads(json_text)
        postings = state.get('listStore', {}).get('listPostings', [])
        if postings:
            p = postings[0]
            print(f"Keys in posting: {p.keys()}")
            print(f"Address info: {p.get('address', {})}")
            print(f"Main Features: {p.get('mainFeatures', {})}")
            # Try to find geolocation
            print(f"Geolocation: {p.get('location', {}).get('postingGeolocation', {})}")
            # Check for bedrooms
            print(f"Bedrooms in posting? {p.get('mainFeatures', {}).get('bedrooms')}")

if __name__ == "__main__":
    inspect_zp()
