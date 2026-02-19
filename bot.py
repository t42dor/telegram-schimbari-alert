import os
import sqlite3
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")

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

    if text.startswith("http"):
        cursor.execute("UPDATE users SET site=? WHERE chat_id=?", (text, chat_id))
        db.commit()
        await update.message.reply_text("Site salvat ✔")

    elif text.lower().startswith("keyword"):
        keyword = text.split(" ", 1)[1]
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
        except:
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


# ------------------ MONITOR ------------------

def parse_price(text):
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


async def monitor(app):
    while True:
        await asyncio.sleep(30)

        cursor.execute("SELECT chat_id, site, keyword, min_price, max_price, active FROM users")
        users = cursor.fetchall()

        for chat_id, site, keyword, min_price, max_price, active in users:

            if active == 0:
                continue

            if not site:
                continue

            try:
                headers = {"User-Agent": "Mozilla/5.0"}
                r = requests.get(site, headers=headers, timeout=10)
                soup = BeautifulSoup(r.text, "lxml")

                links = soup.find_all("a")

                for link in links:
                    title = link.get_text(strip=True).lower()
                    href = link.get("href")

                    if not href or not href.startswith("http"):
                        continue

                    if keyword and keyword.lower() not in title:
                        continue

                    parent_text = link.parent.get_text(" ", strip=True)
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
                                 f"{title}\n\n"
                                 f"💰 Preț: {price}\n"
                                 f"🔗 {href}"
                        )
                        break

            except Exception as e:
                print("Eroare monitor:", e)


# ------------------ APP START ------------------

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))


async def on_startup(app):
    asyncio.create_task(monitor(app))


app.post_init = on_startup
app.run_polling()
