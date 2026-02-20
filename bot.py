import os
import sqlite3
import asyncio
import requests
import unicodedata
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")
ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))

if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is missing. Set it in environment variables.")

db = sqlite3.connect("data.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    site TEXT,
    keyword TEXT,
    min_price INTEGER DEFAULT 0,
    max_price INTEGER DEFAULT 999999999,
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


def parse_sites_input(text):
    separators = [",", "\n", ";", " "]
    normalized = text

    for separator in separators:
        normalized = normalized.replace(separator, "\n")

    sites = []
    for site in normalized.split("\n"):
        clean_site = site.strip()
        if not clean_site:
            continue
        if clean_site.startswith("http") and clean_site not in sites:
            sites.append(clean_site)

    return sites


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


async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Chat ID-ul tău este: {update.effective_chat.id}")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id

    cursor.execute(
        "INSERT OR IGNORE INTO users (chat_id) VALUES (?)",
        (chat_id,)
    )
    db.commit()

    pending_action = context.user_data.get("pending_action")

    if pending_action == "set_site":
        sites = parse_sites_input(text)
        if not sites:
            await update.message.reply_text(
                "Trimite unul sau mai multe URL-uri complete (ex: https://...), separate prin spațiu, virgulă sau rând nou."
            )
            return

        cursor.execute("UPDATE users SET site=? WHERE chat_id=?", ("\n".join(sites), chat_id))
        db.commit()
        context.user_data.pop("pending_action", None)
        await update.message.reply_text(f"{len(sites)} site-uri salvate ✔")
        return

    if pending_action == "set_keyword":
        cursor.execute("UPDATE users SET keyword=? WHERE chat_id=?", (text, chat_id))
        db.commit()
        context.user_data.pop("pending_action", None)
        await update.message.reply_text("Keyword salvat ✔")
        return

    if pending_action == "set_price":
        try:
            minp, maxp = text.split()
            cursor.execute(
                "UPDATE users SET min_price=?, max_price=? WHERE chat_id=?",
                (int(minp), int(maxp), chat_id)
            )
            db.commit()
            context.user_data.pop("pending_action", None)
            await update.message.reply_text("Interval preț salvat ✔")
        except ValueError:
            await update.message.reply_text("Format corect: 0 150000")
        return

    if text == "Set Site":
        context.user_data["pending_action"] = "set_site"
        await update.message.reply_text(
            "Trimite unul sau mai multe URL-uri de monitorizat (separate prin spațiu, virgulă sau rând nou)."
        )
        return

    if text == "Set Keyword":
        context.user_data["pending_action"] = "set_keyword"
        await update.message.reply_text("Trimite keyword-ul (ex: apartament brasov).")
        return

    if text == "Set Price":
        context.user_data["pending_action"] = "set_price"
        await update.message.reply_text("Trimite intervalul: MIN MAX")
        return

    if text == "Stop Alerts":
        cursor.execute("UPDATE users SET active=0 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🔴 Alertele au fost oprite.")
        return

    if text == "Start Alerts":
        cursor.execute("UPDATE users SET active=1 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🟢 Alertele au fost activate.")
        return

    if text == "Show Config":
        cursor.execute(
            "SELECT site, keyword, min_price, max_price, active FROM users WHERE chat_id=?",
            (chat_id,)
        )
        data = cursor.fetchone()
        if not data:
            await update.message.reply_text("Nu există configurație.")
            return

        status = "🟢 Active" if data[4] == 1 else "🔴 Oprite"

        sites_display = data[0].replace("\n", "\n- ") if data[0] else "-"

        await update.message.reply_text(
            f"Config:\n"
            f"Status: {status}\n"
            f"Site-uri:\n- {sites_display}\n"
            f"Keyword: {data[1]}\n"
            f"Min: {data[2]}\n"
            f"Max: {data[3]}"
        )


# ------------------ MONITOR ------------------

async def monitor(app):
    while True:
        cursor.execute("SELECT chat_id, site, keyword, min_price, max_price, active FROM users")
        users = cursor.fetchall()

        for chat_id, site, keyword, min_price, max_price, active in users:

            if active == 0 or not site:
                continue

            sites = parse_sites_input(site)

            for site_url in sites:
                try:
                    headers = {"User-Agent": "Mozilla/5.0"}
                    r = requests.get(site_url, headers=headers, timeout=10)
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, "lxml")

                    links = soup.find_all("a")

                    for link in links:
                        title_raw = link.get_text(strip=True)
                        href = link.get("href")

                        if not href:
                            continue

                        href = urljoin(site_url, href)
                        scheme = urlparse(href).scheme
                        if scheme not in {"http", "https"}:
                            continue

                        title = normalize_text(title_raw)

                        if keyword:
                            words = normalize_text(keyword).split()
                            if not all(word in title for word in words):
                                continue

                        parent_text = normalize_text(link.parent.get_text(" ", strip=True))
                        price = parse_price(parent_text)

                        if price is not None and not (min_price <= price <= max_price):
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

                        price_text = str(price) if price is not None else "necunoscut"
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=f"🏠 OFERTĂ NOUĂ\n\n"
                                 f"{title_raw}\n\n"
                                 f"💰 Preț: {price_text}\n"
                                 f"🔗 {href}"
                        )
                        break

                except Exception as e:
                    print(f"Eroare monitor pentru {site_url}:", e)

        await asyncio.sleep(ALERT_INTERVAL_SECONDS)


# ------------------ START APP ------------------

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("id", show_id))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))


async def on_startup(app):
    asyncio.create_task(monitor(app))


app.post_init = on_startup
app.run_polling()
