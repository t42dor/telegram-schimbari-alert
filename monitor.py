import os
import json
import requests
from playwright.sync_api import sync_playwright

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

DATA_FILE = "seen.json"


def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text}
    )


def get_config_from_telegram():
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    data = requests.get(url).json()

    if not data["result"]:
        return None

    last_message = data["result"][-1]["message"]["text"]
    lines = last_message.split("\n")

    config = {
        "sites": [],
        "keyword": "",
        "min": 0,
        "max": 999999999
    }

    for line in lines:
        if line.startswith("SITE"):
            config["sites"].append(line.split("=", 1)[1].strip())
        elif line.startswith("KEYWORD="):
            config["keyword"] = line.split("=", 1)[1].strip().lower()
        elif line.startswith("MIN="):
            config["min"] = int(line.split("=", 1)[1])
        elif line.startswith("MAX="):
            config["max"] = int(line.split("=", 1)[1])

    return config


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
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


def check_site(url, keyword, min_price, max_price, seen, playwright):
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url, timeout=60000)
    page.wait_for_timeout(5000)

    ads = page.query_selector_all("a")

    for ad in ads:
        title = ad.inner_text().lower()
        link = ad.get_attribute("href")

        if not link or "http" not in link:
            continue

        if keyword and keyword not in title:
            continue

        parent_text = ad.evaluate("el => el.parentElement.innerText")
        price = parse_price(parent_text)

        if price and min_price <= price <= max_price:
            if link not in seen:
                msg = f"OFERTĂ NOUĂ\n{title}\nPreț: {price}\n{link}"
                send_telegram(msg)
                seen.append(link)

    browser.close()


def main():
    config = get_config_from_telegram()
    if not config:
        return

    seen = load_seen()

    with sync_playwright() as p:
        for site in config["sites"][:5]:
            try:
                check_site(site, config["keyword"], config["min"], config["max"], seen, p)
            except:
                pass

    save_seen(seen)


if __name__ == "__main__":
    main()
