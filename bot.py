import os
import sqlite3
import asyncio
import requests
import unicodedata
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))

db = sqlite3.connect("data.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    site TEXT,
    keyword TEXT,
    min_price INTEGER,
    max_price INTEGER,
    active INTEGER DEFAULT 1
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS seen (
    chat_id INTEGER,
    link TEXT
)
""")

db.commit()


# ------------------ UTIL ------------------

def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    return text


def parse_price(text):
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


# ------------------ TELEGRAM UI ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Set Site", "Set Keyword"],
        ["Set Price", "Show Config"],
        ["Start Alerts", "Stop Alerts"]
    ]
    await update.message.reply_text(
        "Bot activ. Alege o opțiune:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id

    cursor.execute(
        "INSERT OR IGNORE INTO users (chat_id, min_price, max_price, active) VALUES (?, 0, 999999999, 1)",
        (chat_id,)
    )
    db.commit()

    if text == "Set Site":
        await update.message.reply_text("Trimite link-ul complet al site-ului (ex: https://site.ro/cautare)")

    elif text == "Set Keyword":
        await update.message.reply_text("Trimite: keyword apartament 2 camere")

    elif text == "Set Price":
        await update.message.reply_text("Trimite: price 0 100000")

    elif text.startswith("http"):
        cursor.execute("UPDATE users SET site=? WHERE chat_id=?", (text, chat_id))
        db.commit()
        await update.message.reply_text("Site salvat ✔")

    elif text.lower().startswith("keyword"):
        parts = text.split(" ", 1)
        if len(parts) < 2 or not parts[1].strip():
            await update.message.reply_text("Format corect: keyword apartament 2 camere")
            return
        keyword = parts[1].strip()
        cursor.execute("UPDATE users SET keyword=? WHERE chat_id=?", (keyword, chat_id))
        db.commit()
        await update.message.reply_text("Keyword salvat ✔")

    elif text.lower().startswith("price"):
        try:
            _, minp, maxp = text.split()
            cursor.execute(
                "UPDATE users SET min_price=?, max_price=? WHERE chat_id=?",
                (int(minp), int(maxp), chat_id)
            )
            db.commit()
            await update.message.reply_text("Interval preț salvat ✔")
        except ValueError:
            await update.message.reply_text("Format corect: price 0 100000")

    elif text == "Stop Alerts":
        cursor.execute("UPDATE users SET active=0 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🔴 Alertele au fost oprite.")

    elif text == "Start Alerts":
        cursor.execute("UPDATE users SET active=1 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🟢 Alertele au fost activate.")

    elif text == "Show Config":
        cursor.execute(
            "SELECT site, keyword, min_price, max_price, active FROM users WHERE chat_id=?",
            (chat_id,)
        )
        data = cursor.fetchone()

        status = "🟢 Active" if data[4] == 1 else "🔴 Oprite"

        await update.message.reply_text(
            f"Config:\n"
            f"Status: {status}\n"
            f"Site: {data[0]}\n"
            f"Keyword: {data[1]}\n"
            f"Min: {data[2]}\n"
            f"Max: {data[3]}"
        )

    else:
        await update.message.reply_text(
            "Comandă necunoscută. Folosește butoanele sau trimite: 'keyword ...', 'price min max', ori un link."
        )


# ------------------ MONITOR ------------------

async def monitor(app):
    while True:
        cursor.execute("SELECT chat_id, site, keyword, min_price, max_price, active FROM users")
        users = cursor.fetchall()

        for chat_id, site, keyword, min_price, max_price, active in users:

            if active == 0 or not site:
                continue

            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                r = requests.get(site, headers=headers, timeout=10)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")

                links = soup.find_all("a")

                for link in links:
                    title_raw = link.get_text(strip=True)
                    href = link.get("href")

                    if not href or not href.startswith("http"):
                        continue

                    title = normalize_text(title_raw)

                    if keyword:
                        words = normalize_text(keyword).split()
                        if not all(word in title for word in words):
                            continue

                    parent_text = normalize_text(link.parent.get_text(" ", strip=True))
                    price = parse_price(parent_text)

                    if price and min_price <= price <= max_price:
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
                            text=f"🏠 OFERTĂ NOUĂ\n\n"
                                 f"{title_raw}\n\n"
                                 f"💰 Preț: {price}\n"
                                 f"🔗 {href}"
                        )
                        break

            except Exception as e:
                print("Eroare monitor:", e)

        await asyncio.sleep(ALERT_INTERVAL_SECONDS)


# ------------------ START APP ------------------

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))


async def on_startup(app):
    asyncio.create_task(monitor(app))


app.post_init = on_startup
app.run_polling()
