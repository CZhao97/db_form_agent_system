import requests
import re

url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC10545370/pdf/"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")
    print(f"URL: {response.url}")
    
    if "text/html" in response.headers.get("Content-Type", ""):
        print("Content (first 1000 chars):")
        print(response.text[:1000])
        
        # Look for PDF links
        pdf_links = re.findall(r'href="([^"]+\.pdf)"', response.text)
        print(f"Found PDF links: {pdf_links}")
except Exception as e:
    print(f"Error: {e}")
