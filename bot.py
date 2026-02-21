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
ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))
MAX_SITES_PER_USER = 5

if not TOKEN:
    print("DEBUG: EROARE CRITICĂ - TELEGRAM_TOKEN nu este setat!")
    raise RuntimeError("Missing TELEGRAM_TOKEN environment variable")

print(f"DEBUG: Token încărcat (primele 10 caractere): {TOKEN[:10]}...")

print(f"DEBUG: Interval alerte: {ALERT_INTERVAL_SECONDS} secunde")
print(f"DEBUG: Max site-uri per user: {MAX_SITES_PER_USER}")

print("DEBUG: Conectare la baza de date SQLite...")
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
print("DEBUG: Tabele DB create/verificat cu succes")

# ------------------ DB UTIL ------------------
def ensure_user(chat_id: int) -> None:
    cursor.execute(
        "INSERT OR IGNORE INTO users (chat_id, min_price, max_price, active) VALUES (?, 0, 999999999, 1)",
        (chat_id,),
    )
    db.commit()

def migrate_legacy_single_site(chat_id: int) -> None:
    cursor.execute("SELECT site FROM users WHERE chat_id=?", (chat_id,))
    row = cursor.fetchone()
    if not row or not row[0]:
        return
    cursor.execute(
        "INSERT OR IGNORE INTO user_sites (chat_id, site) VALUES (?, ?)",
        (chat_id, row[0]),
    )
    cursor.execute("UPDATE users SET site=NULL WHERE chat_id=?", (chat_id,))
    db.commit()

def get_user_sites(chat_id: int) -> list[str]:
    cursor.execute(
        "SELECT site FROM user_sites WHERE chat_id=? ORDER BY rowid ASC", (chat_id,)
    )
    rows = cursor.fetchall()
    sites = [row[0] for row in rows]
    print(f"DEBUG: get_user_sites pentru {chat_id} → {len(sites)} site-uri: {sites}")
    return sites

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
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_text(
        "Bot activ. Configurează până la 5 site-uri:",
        reply_markup=reply_markup,
    )
    print(f"DEBUG: /start trimis meniu către {update.message.chat_id}")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        print("DEBUG: WARNING - update.message is None!")
        return

    text = update.message.text.strip() if update.message.text else ""
    chat_id = update.message.chat_id

    print(f"DEBUG: MESSAGE HANDLER apelat! Chat ID: {chat_id} | Text brut: '{text}' | Update: {update.to_dict()}")

    if not text:
        print("DEBUG: Mesaj fără text - ignor")
        return

    ensure_user(chat_id)
    migrate_legacy_single_site(chat_id)

    async def safe_send(text_to_send: str):
        try:
            await update.message.reply_text(text_to_send)
            print(f"DEBUG: reply_text trimis cu succes: '{text_to_send[:50]}...'")
        except Exception as e:
            print(f"DEBUG: Eroare la reply_text: {str(e)}")
            try:
                await context.bot.send_message(chat_id=chat_id, text=text_to_send)
                print("DEBUG: Fallback cu bot.send_message OK")
            except Exception as e2:
                print(f"DEBUG: Fallback eșuat: {str(e2)}")

    if text == "Add Site":
        print("DEBUG: Buton Add Site apăsat")
        context.user_data["pending_action"] = "add_site"
        await safe_send("Trimite URL-ul paginii de căutare pe care vrei monitorizare. (maxim 5 site-uri)")
        return

    if text == "Remove Site":
        print("DEBUG: Buton Remove Site apăsat")
        context.user_data["pending_action"] = "remove_site"
        await safe_send("Trimite URL-ul exact pe care vrei să îl ștergi.")
        return

    # ... adaugă la fel print("DEBUG: Buton X apăsat") pentru fiecare buton ...

    if text == "List Sites":
        print("DEBUG: Buton List Sites apăsat")
        context.user_data.pop("pending_action", None)
        sites = get_user_sites(chat_id)
        if not sites:
            await safe_send("Nu ai site-uri configurate încă.")
            return
        formatted = "\n".join(f"{idx + 1}. {site}" for idx, site in enumerate(sites))
        await safe_send(f"Site-uri configurate ({len(sites)}/{MAX_SITES_PER_USER}):\n{formatted}")
        return

    # ... restul butoanelor cu print și safe_send ...

    pending_action = context.user_data.get("pending_action")
    print(f"DEBUG: Pending action după verificări butoane: {pending_action}")

    # ... restul logicii pentru pending_action (add_site, set_keyword etc.) cu safe_send în loc de reply_text ...

    print(f"DEBUG: Mesaj '{text}' procesat, dar nu a intrat pe niciun handler specific")

# ------------------ MONITOR (la fel ca înainte, cu wait 10000ms) ------------------
async def monitor(app):
    print("DEBUG: Monitor pornit")
    while True:
        # ... codul tău de monitor cu await page.wait_for_timeout(10000) și wait_for_load_state ...
        await asyncio.sleep(ALERT_INTERVAL_SECONDS)

# ------------------ APP ------------------
print("DEBUG: Construiesc ApplicationBuilder...")
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

async def on_startup(app):
    print("DEBUG: ON_STARTUP - creez monitor...")
    asyncio.create_task(monitor(app))

app.post_init = on_startup

print("DEBUG: Pornesc polling-ul...")
app.run_polling()
print("DEBUG: Polling pornit")
