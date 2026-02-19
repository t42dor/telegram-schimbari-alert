import os
import requests
from bs4 import BeautifulSoup
import json

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

URL = "https://www.olx.ro/imobiliare/vanzare-apartamente/brasov/?search%5Bfilter_float_price%3Ato%5D=100000"
KEYWORD = "apartament"
MIN_PRICE = 0
MAX_PRICE = 100000

DATA_FILE = "seen.json"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHAT_ID, "text": text})

def load_seen():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_seen(seen):
    with open(DATA_FILE, "w") as f:
        json.dump(seen, f)

def parse_price(text):
    digits = ''.join(c for c in text if c.isdigit())
    return int(digits) if digits else None

def check():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    seen = load_seen()

    for a in soup.find_all("a"):
        link = a.get("href")
        if not link or "olx.ro" not in link:
            continue

        title = a.get_text().lower()
        if KEYWORD.lower() not in title:
            continue

        price = parse_price(a.parent.get_text())
        if price and MIN_PRICE <= price <= MAX_PRICE:
            if link not in seen:
                msg = f"OFERTĂ NOUĂ\n{title}\nPreț: {price} €\n{link}"
                send_telegram(msg)
                seen.append(link)

    save_seen(seen)

if __name__ == "__main__":
    check()

