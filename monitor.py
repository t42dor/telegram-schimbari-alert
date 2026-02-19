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
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []

def save_seen(seen):
    with open(DATA_FILE, "w") as f:
        json.dump(seen, f)

def parse_price(price_text):
    digits = ''.join(c for c in price_text if c.isdigit())
    if digits:
        return int(digits)
    return None

def check_site():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(URL, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")

    seen = load_seen()

    for ad in soup.find_all("a"):
        link = ad.get("href")
        if not link or "olx.ro" not in link:
            continue

        title = ad.get_text().lower()
        if KEYWORD.lower() not in title:
            continue

        parent = ad.find_parent()
        if not parent:
            continue

        price_text = parent.get_text()
        price = parse_price(price_text)

        if price and MIN_PRICE <= price <= MAX_PRICE:
            if link not in seen:
                message = f"Oferta nouă:\n{title}\nPreț: {price} €\n{link}"
                send_telegram(message)
                seen.append(link)

    save_seen(seen)

if __name__ == "__main__":
    check_site()
