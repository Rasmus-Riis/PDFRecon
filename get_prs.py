import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

url = "https://api.github.com/repos/Rasmus-Riis/PDFRecon/pulls?state=open&per_page=50"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())
        for pr in data:
            print(f"[{pr['number']}] {pr['title']}")
except Exception as e:
    print(f"Error: {e}")
