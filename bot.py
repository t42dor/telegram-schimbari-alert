import os
import sqlite3
import asyncio
import unicodedata
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

TOKEN = os.getenv("TELEGRAM_TOKEN")
ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN environment variable")

db = sqlite3.connect("data.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute(
    "CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, site TEXT, keyword TEXT, min_price INTEGER, max_price INTEGER, active INTEGER DEFAULT 1)"
)

cursor.execute(
    "CREATE TABLE IF NOT EXISTS seen (chat_id INTEGER, link TEXT)"
)

db.commit()


# ------------------ UTIL ------------------

def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def parse_price(text):
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


# ------------------ TELEGRAM UI ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Set Site", "Set Keyword"],
        ["Set Price", "Show Config"],
        ["Start Alerts", "Stop Alerts"],
        ["Reset Config"],
    ]
    await update.message.reply_text(
        "Bot activ. Alege o opțiune:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id

    cursor.execute(
        "INSERT OR IGNORE INTO users (chat_id, min_price, max_price, active) VALUES (?, 0, 999999999, 1)",
        (chat_id,),
    )
    db.commit()

    # Always let keyboard actions override any pending input state.
    # This avoids getting "stuck" in one flow (ex: set_site) where every next
    # button press is interpreted as plain text for the previous action.
    if text == "Set Site":
        context.user_data["pending_action"] = "set_site"
        await update.message.reply_text(
            "Trimite URL-ul paginii pe care vrei monitorizare (ideal pagina de căutare, nu homepage)."
        )
        return

    if text == "Set Keyword":
        context.user_data["pending_action"] = "set_keyword"
        await update.message.reply_text("Trimite keyword-ul (ex: apartament brasov).")
        return

    if text == "Set Price":
        context.user_data["pending_action"] = "set_price"
        await update.message.reply_text("Trimite intervalul de preț: MIN MAX (ex: 0 150000).")
        return

    if text == "Stop Alerts":
        context.user_data.pop("pending_action", None)
        cursor.execute("UPDATE users SET active=0 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🔴 Alertele au fost oprite.")
        return

    if text == "Start Alerts":
        context.user_data.pop("pending_action", None)
        cursor.execute("UPDATE users SET active=1 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🟢 Alertele au fost activate.")
        return

    if text == "Show Config":
        context.user_data.pop("pending_action", None)
        cursor.execute(
            "SELECT site, keyword, min_price, max_price, active FROM users WHERE chat_id=?",
            (chat_id,),
        )
        data = cursor.fetchone()

        status = "🟢 Active" if data and data[4] == 1 else "🔴 Oprite"

        if not data:
            await update.message.reply_text("Nu există configurare încă.")
            return

        await update.message.reply_text(
            f"Config:\n"
            f"Status: {status}\n"
            f"Site: {data[0]}\n"
            f"Keyword: {data[1]}\n"
            f"Min: {data[2]}\n"
            f"Max: {data[3]}"
        )
        return

    if text == "Reset Config":
        context.user_data.pop("pending_action", None)
        cursor.execute(
            "UPDATE users SET site=NULL, keyword=NULL, min_price=0, max_price=999999999, active=1 WHERE chat_id=?",
            (chat_id,),
        )
        cursor.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("♻️ Config resetată.")
        return

    pending_action = context.user_data.get("pending_action")
    if pending_action == "set_site":
        if not text.startswith("http"):
            await update.message.reply_text("Trimite un URL complet (ex: https://www.imobiliare.ro/...)")
            return
        cursor.execute("UPDATE users SET site=? WHERE chat_id=?", (text, chat_id))
        db.commit()
        context.user_data.pop("pending_action", None)
        await update.message.reply_text("Site salvat ✔")
        return

    if pending_action == "set_keyword":
        keyword = text.strip()
        if not keyword:
            await update.message.reply_text("Trimite un keyword valid (ex: apartament brasov)")
            return
        cursor.execute("UPDATE users SET keyword=? WHERE chat_id=?", (keyword, chat_id))
        db.commit()
        context.user_data.pop("pending_action", None)
        await update.message.reply_text("Keyword salvat ✔")
        return

    if pending_action == "set_price":
        try:
            minp, maxp = text.split()
            cursor.execute(
                "UPDATE users SET min_price=?, max_price=? WHERE chat_id=?",
                (int(minp), int(maxp), chat_id),
            )
            db.commit()
            context.user_data.pop("pending_action", None)
            await update.message.reply_text("Interval preț salvat ✔")
        except ValueError:
            await update.message.reply_text("Format corect: 0 150000")
        return

    if text.startswith("http"):
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
                (int(minp), int(maxp), chat_id),
            )
            db.commit()
            await update.message.reply_text("Interval preț salvat ✔")
        except ValueError:
            await update.message.reply_text("Format corect: price 0 100000")

# ------------------ MONITOR ------------------

async def monitor(app):
    while True:
        cursor.execute("SELECT chat_id, site, keyword, min_price, max_price, active FROM users")
        users = cursor.fetchall()

        for chat_id, site, keyword, min_price, max_price, active in users:
            if active == 0 or not site:
                continue

            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                    page = await browser.new_page()
                    await page.goto(site, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(2500)
                    html = await page.content()
                    await page.close()
                    await browser.close()

                soup = BeautifulSoup(html, "lxml")
                links = soup.find_all("a")

                for link in links:
                    title_raw = link.get_text(strip=True)
                    href = link.get("href")

                    if not href:
                        continue

                    href = urljoin(site, href)
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

                    if price is not None and min_price <= price <= max_price:
                        cursor.execute(
                            "SELECT 1 FROM seen WHERE chat_id=? AND link=?",
                            (chat_id, href),
                        )
                        if cursor.fetchone():
                            continue

                        cursor.execute(
                            "INSERT INTO seen (chat_id, link) VALUES (?, ?)",
                            (chat_id, href),
                        )
                        db.commit()

                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=f"🏠 OFERTĂ NOUĂ\n\n"
                            f"{title_raw}\n\n"
                            f"💰 Preț: {price}\n"
                            f"🔗 {href}",
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
