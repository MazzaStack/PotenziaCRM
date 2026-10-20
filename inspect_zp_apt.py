import re
import json
from curl_cffi import requests
from bs4 import BeautifulSoup

def inspect_zp_apartment():
    url = "https://www.zonaprop.com.ar/departamentos-venta-palermo.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    resp = requests.get(url, impersonate='chrome', headers=headers)
    soup = BeautifulSoup(resp.text, 'lxml')
    ld = soup.find('script', type='application/ld+json', string=re.compile(r'"@type":\s*"Apartment"'))
    if ld:
        data = json.loads(ld.string)
        print(json.dumps(data, indent=2))
    else:
        print("Apartment JSON-LD not found")

if __name__ == "__main__":
    inspect_zp_apartment()
