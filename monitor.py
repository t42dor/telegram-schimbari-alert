import json
import os
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

CONFIG_FILE = Path("config.json")
SEEN_FILE = Path("seen.json")

DEFAULT_CONFIG = {
    "sites": [],
    "keyword": "",
    "min": 0,
    "max": 999_999_999,
}


def send_telegram(text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text},
        timeout=20,
    )


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_CONFIG.copy()

    config = DEFAULT_CONFIG.copy()
    config.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    return config


def load_seen() -> list[str]:
    try:
        with SEEN_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_seen(seen: list[str]) -> None:
    with SEEN_FILE.open("w", encoding="utf-8") as f:
        json.dump(seen, f)


def parse_price(text: str) -> int | None:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


def check_site(url: str, keyword: str, min_price: int, max_price: int, seen: list[str], playwright) -> None:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url, timeout=60000)
    page.wait_for_timeout(5000)

    ads = page.query_selector_all("a")

    for ad in ads:
        title = (ad.inner_text() or "").strip().lower()
        link = ad.get_attribute("href")

        if not link or "http" not in link:
            continue

        if keyword and keyword not in title:
            continue

        parent_text = ad.evaluate("el => el.parentElement ? el.parentElement.innerText : ''")
        price = parse_price(parent_text)

        if price is not None and min_price <= price <= max_price and link not in seen:
            msg = f"OFERTĂ NOUĂ\n{title}\nPreț: {price}\n{link}"
            send_telegram(msg)
            seen.append(link)

    browser.close()


def main() -> None:
    config = load_config()
    if not config["sites"]:
        return

    seen = load_seen()

    with sync_playwright() as p:
        for site in config["sites"][:5]:
            try:
                check_site(site, config["keyword"], int(config["min"]), int(config["max"]), seen, p)
            except Exception:
                continue

    save_seen(seen)


if __name__ == "__main__":
    main()
