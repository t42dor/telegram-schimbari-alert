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

# ---------------- CONFIG ----------------

TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", 8080))

ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))
MAX_SITES_PER_USER = 5

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN")

if not WEBHOOK_URL:
    raise RuntimeError("Missing WEBHOOK_URL")

# ---------------- DATABASE ----------------

db = sqlite3.connect("data.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    keyword TEXT,
    min_price INTEGER DEFAULT 0,
    max_price INTEGER DEFAULT 999999999,
    active INTEGER DEFAULT 1
)
""")

cursor.execute("CREATE TABLE IF NOT EXISTS seen (chat_id INTEGER, link TEXT)")
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_sites (
    chat_id INTEGER,
    site TEXT,
    UNIQUE(chat_id, site)
)
""")

db.commit()

# ---------------- UTIL ----------------

def ensure_user(chat_id: int):
    cursor.execute(
        "INSERT OR IGNORE INTO users (chat_id) VALUES (?)",
        (chat_id,)
    )
    db.commit()


def get_user_sites(chat_id: int):
    cursor.execute(
        "SELECT site FROM user_sites WHERE chat_id=?",
        (chat_id,)
    )
    return [row[0] for row in cursor.fetchall()]


def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def parse_price(text):
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None

# ---------------- TELEGRAM UI ----------------

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


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    ensure_user(chat_id)

    # -------- BUTTONS --------

    if text == "Add Site":
        context.user_data["pending"] = "add_site"
        await update.message.reply_text("Trimite URL complet.")
        return

    if text == "Remove Site":
        context.user_data["pending"] = "remove_site"
        await update.message.reply_text("Trimite URL exact pentru ștergere.")
        return

    if text == "List Sites":
        sites = get_user_sites(chat_id)
        if not sites:
            await update.message.reply_text("Nu ai site-uri.")
            return
        await update.message.reply_text("\n".join(sites))
        return

    if text == "Set Keyword":
        context.user_data["pending"] = "set_keyword"
        await update.message.reply_text("Trimite keyword.")
        return

    if text == "Set Price":
        context.user_data["pending"] = "set_price"
        await update.message.reply_text("Format: MIN MAX")
        return

    if text == "Start Alerts":
        cursor.execute("UPDATE users SET active=1 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🟢 Alerte pornite.")
        return

    if text == "Stop Alerts":
        cursor.execute("UPDATE users SET active=0 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🔴 Alerte oprite.")
        return

    if text == "Reset Config":
        cursor.execute("DELETE FROM user_sites WHERE chat_id=?", (chat_id,))
        cursor.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
        cursor.execute(
            "UPDATE users SET keyword=NULL, min_price=0, max_price=999999999 WHERE chat_id=?",
            (chat_id,)
        )
        db.commit()
        await update.message.reply_text("♻ Config resetat.")
        return

    if text == "Show Config":
        cursor.execute(
            "SELECT keyword, min_price, max_price, active FROM users WHERE chat_id=?",
            (chat_id,)
        )
        data = cursor.fetchone()
        sites = get_user_sites(chat_id)

        await update.message.reply_text(
            f"Status: {'Active' if data[3]==1 else 'Stopped'}\n"
            f"Sites: {len(sites)}\n"
            f"Keyword: {data[0]}\n"
            f"Min: {data[1]}\n"
            f"Max: {data[2]}"
        )
        return

    # -------- PENDING ACTIONS --------

    pending = context.user_data.get("pending")

    if pending == "add_site":
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            await update.message.reply_text("URL invalid. Folosește format complet, ex: https://site.ro")
            return

        current_sites = get_user_sites(chat_id)
        if len(current_sites) >= MAX_SITES_PER_USER:
            context.user_data.pop("pending")
            await update.message.reply_text(f"Ai atins limita de {MAX_SITES_PER_USER} site-uri.")
            return

        cursor.execute(
            "INSERT OR IGNORE INTO user_sites (chat_id, site) VALUES (?, ?)",
            (chat_id, text)
        )
        db.commit()
        context.user_data.pop("pending")
        await update.message.reply_text("Site adăugat ✔")
        return

    if pending == "remove_site":
        cursor.execute(
            "DELETE FROM user_sites WHERE chat_id=? AND site=?",
            (chat_id, text)
        )
        db.commit()
        context.user_data.pop("pending")
        await update.message.reply_text("Site șters ✔")
        return

    if pending == "set_keyword":
        cursor.execute("UPDATE users SET keyword=? WHERE chat_id=?", (text, chat_id))
        db.commit()
        context.user_data.pop("pending")
        await update.message.reply_text("Keyword salvat ✔")
        return

    if pending == "set_price":
        try:
            min_p, max_p = map(int, text.split())
            cursor.execute(
                "UPDATE users SET min_price=?, max_price=? WHERE chat_id=?",
                (min_p, max_p, chat_id)
            )
            db.commit()
            context.user_data.pop("pending")
            await update.message.reply_text("Preț salvat ✔")
        except:
            await update.message.reply_text("Format greșit.")
        return


# ---------------- MONITOR ----------------

async def monitor(app):
    while True:
        cursor.execute(
            "SELECT chat_id, keyword, min_price, max_price FROM users WHERE active=1"
        )
        users = cursor.fetchall()

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)

                for chat_id, keyword, min_price, max_price in users:
                    sites = get_user_sites(chat_id)
                    for site in sites:
                        page = await browser.new_page()
                        try:
                            await page.goto(site, timeout=60000)
                            html = await page.content()
                        except:
                            await page.close()
                            continue
                        await page.close()

                        soup = BeautifulSoup(html, "lxml")
                        links = soup.find_all("a")

                        for link in links:
                            title = link.get_text(strip=True)
                            href = link.get("href")
                            if not title or not href:
                                continue

                            href = urljoin(site, href)
                            price = parse_price(link.parent.get_text())

                            if not price or not (min_price <= price <= max_price):
                                continue

                            cursor.execute(
                                "SELECT 1 FROM seen WHERE chat_id=? AND link=?",
                                (chat_id, href)
                            )
                            if cursor.fetchone():
                                continue

                            cursor.execute(
                                "INSERT INTO seen (chat_id, link) VALUES (?, ?)",
                                (chat_id, href)
                            )
                            db.commit()

                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=f"🏠 {title}\n💰 {price}\n🔗 {href}"
                            )
                            break

                await browser.close()
        except Exception as e:
            print("Monitor error:", e)

        await asyncio.sleep(ALERT_INTERVAL_SECONDS)


# ---------------- START APP ----------------

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))


async def on_startup(app):
    await app.bot.delete_webhook(drop_pending_updates=True)
    await app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
    asyncio.create_task(monitor(app))


app.post_init = on_startup

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path="webhook",
    webhook_url=f"{WEBHOOK_URL}/webhook",
)
