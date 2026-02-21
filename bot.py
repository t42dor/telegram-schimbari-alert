import asyncio
import os
import sqlite3
import unicodedata
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

print("DEBUG: Script pornit - începem încărcarea mediului...")

TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8080))
ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))
MAX_SITES_PER_USER = 5

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN environment variable")

if not WEBHOOK_URL:
    raise RuntimeError("Missing WEBHOOK_URL environment variable")

print(f"DEBUG: PORT = {PORT}")
print(f"DEBUG: WEBHOOK_URL = {WEBHOOK_URL}")

# ------------------ DATABASE ------------------

db = sqlite3.connect("data.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute(
    "CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, keyword TEXT, min_price INTEGER DEFAULT 0, max_price INTEGER DEFAULT 999999999, active INTEGER DEFAULT 1)"
)
cursor.execute("CREATE TABLE IF NOT EXISTS seen (chat_id INTEGER, link TEXT)")
cursor.execute(
    "CREATE TABLE IF NOT EXISTS user_sites (chat_id INTEGER, site TEXT, UNIQUE(chat_id, site))"
)
db.commit()

def ensure_user(chat_id: int) -> None:
    cursor.execute(
        "INSERT OR IGNORE INTO users (chat_id, min_price, max_price, active) VALUES (?, 0, 999999999, 1)",
        (chat_id,),
    )
    db.commit()

def get_user_sites(chat_id: int) -> list[str]:
    cursor.execute(
        "SELECT site FROM user_sites WHERE chat_id=? ORDER BY rowid ASC", (chat_id,)
    )
    return [row[0] for row in cursor.fetchall()]

# ------------------ UTIL ------------------

def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def parse_price(text: str) -> int | None:
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None

# ------------------ TELEGRAM UI ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Add Site", "Remove Site"],
        ["List Sites", "Set Keyword"],
        ["Set Price", "Show Config"],
        ["Start Alerts", "Stop Alerts"],
        ["Reset Config"],
    ]
    await update.message.reply_text(
        "Bot activ. Configurează până la 5 site-uri:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    print(f"DEBUG: /start de la {update.message.chat_id}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    print(f"DEBUG: Mesaj primit: {text} de la {chat_id}")

    ensure_user(chat_id)

    if text == "Add Site":
        context.user_data["pending_action"] = "add_site"
        await update.message.reply_text("Trimite URL complet.")
        return

    pending_action = context.user_data.get("pending_action")

    if pending_action == "add_site":
        if not text.startswith("http"):
            await update.message.reply_text("Trimite un URL valid.")
            return
        try:
            cursor.execute(
                "INSERT INTO user_sites (chat_id, site) VALUES (?, ?)",
                (chat_id, text),
            )
            db.commit()
            context.user_data.pop("pending_action", None)
            await update.message.reply_text("Site adăugat ✔")
        except sqlite3.IntegrityError:
            await update.message.reply_text("Site deja existent.")
        return

# ------------------ MONITOR ------------------

async def monitor(app):
    print("DEBUG: Monitor pornit")
    while True:
        cursor.execute(
            "SELECT chat_id, keyword, min_price, max_price FROM users WHERE active=1"
        )
        users = cursor.fetchall()

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )

                for chat_id, keyword, min_price, max_price in users:
                    sites = get_user_sites(chat_id)

                    for site in sites:
                        page = await browser.new_page()
                        try:
                            await page.goto(site, wait_until="domcontentloaded", timeout=60000)
                            await page.wait_for_load_state('networkidle', timeout=30000)
                            html = await page.content()
                        except Exception as e:
                            print("Eroare site:", e)
                            await page.close()
                            continue
                        await page.close()

                        soup = BeautifulSoup(html, "lxml")
                        links = soup.find_all("a")

                        for link in links:
                            title_raw = link.get_text(strip=True)
                            href = link.get("href")
                            if not href or not title_raw:
                                continue

                            href = urljoin(site, href)
                            price = parse_price(link.parent.get_text(" ", strip=True))
                            if not price:
                                continue

                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=f"🏠 {title_raw}\n💰 {price}\n🔗 {href}",
                            )
                            break

                await browser.close()
        except Exception as e:
            print("Monitor error:", e)

        await asyncio.sleep(ALERT_INTERVAL_SECONDS)

# ------------------ START WEBHOOK ------------------

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

async def on_startup(app):
    print("DEBUG: ON_STARTUP WEBHOOK")
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    asyncio.create_task(monitor(app))

app.post_init = on_startup

print("DEBUG: Pornesc run_webhook...")
app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path="webhook",
    webhook_url=f"{WEBHOOK_URL}/webhook",
)
