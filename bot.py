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

TOKEN = os.getenv("TELEGRAM_TOKEN")
ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "60"))
MAX_SITES_PER_USER = 5

if not TOKEN:
    raise RuntimeError("Missing TELEGRAM_TOKEN environment variable")


db = sqlite3.connect("data.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute(
    "CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, site TEXT, keyword TEXT, min_price INTEGER, max_price INTEGER, active INTEGER DEFAULT 1)"
)
cursor.execute("CREATE TABLE IF NOT EXISTS seen (chat_id INTEGER, link TEXT)")
cursor.execute(
    "CREATE TABLE IF NOT EXISTS user_sites (chat_id INTEGER, site TEXT, UNIQUE(chat_id, site))"
)

db.commit()


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


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    ensure_user(chat_id)
    migrate_legacy_single_site(chat_id)

    if text == "Add Site":
        context.user_data["pending_action"] = "add_site"
        await update.message.reply_text(
            "Trimite URL-ul paginii de căutare pe care vrei monitorizare. (maxim 5 site-uri)"
        )
        return

    if text == "Remove Site":
        context.user_data["pending_action"] = "remove_site"
        await update.message.reply_text("Trimite URL-ul exact pe care vrei să îl ștergi.")
        return

    if text == "List Sites":
        context.user_data.pop("pending_action", None)
        sites = get_user_sites(chat_id)
        if not sites:
            await update.message.reply_text("Nu ai site-uri configurate încă.")
            return

        formatted = "\n".join(f"{idx + 1}. {site}" for idx, site in enumerate(sites))
        await update.message.reply_text(f"Site-uri configurate ({len(sites)}/{MAX_SITES_PER_USER}):\n{formatted}")
        return

    if text == "Set Keyword":
        context.user_data["pending_action"] = "set_keyword"
        await update.message.reply_text("Trimite keyword-ul (ex: apartament 2 camere brasov).")
        return

    if text == "Set Price":
        context.user_data["pending_action"] = "set_price"
        await update.message.reply_text("Trimite intervalul de preț: MIN MAX (ex: 30000 150000).")
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
            "SELECT keyword, min_price, max_price, active FROM users WHERE chat_id=?",
            (chat_id,),
        )
        data = cursor.fetchone()
        sites = get_user_sites(chat_id)

        status = "🟢 Active" if data and data[3] == 1 else "🔴 Oprite"
        sites_text = "\n".join(f"- {site}" for site in sites) if sites else "(niciun site)"

        await update.message.reply_text(
            f"Config:\n"
            f"Status: {status}\n"
            f"Site-uri ({len(sites)}/{MAX_SITES_PER_USER}):\n{sites_text}\n"
            f"Keyword: {data[0] if data and data[0] else '(gol)'}\n"
            f"Min: {data[1] if data else 0}\n"
            f"Max: {data[2] if data else 999999999}"
        )
        return

    if text == "Reset Config":
        context.user_data.pop("pending_action", None)
        cursor.execute(
            "UPDATE users SET site=NULL, keyword=NULL, min_price=0, max_price=999999999, active=1 WHERE chat_id=?",
            (chat_id,),
        )
        cursor.execute("DELETE FROM user_sites WHERE chat_id=?", (chat_id,))
        cursor.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("♻️ Config resetată.")
        return

    pending_action = context.user_data.get("pending_action")

    if pending_action == "add_site":
        if not text.startswith("http"):
            await update.message.reply_text("Trimite un URL complet (ex: https://site.ro/cautare).")
            return

        sites = get_user_sites(chat_id)
        if len(sites) >= MAX_SITES_PER_USER:
            await update.message.reply_text("Ai atins limita de 5 site-uri. Șterge unul înainte să adaugi altul.")
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
            await update.message.reply_text("Site-ul există deja în listă.")
        return

    if pending_action == "remove_site":
        cursor.execute(
            "DELETE FROM user_sites WHERE chat_id=? AND site=?",
            (chat_id, text),
        )
        deleted = cursor.rowcount
        db.commit()

        if deleted:
            context.user_data.pop("pending_action", None)
            await update.message.reply_text("Site șters ✔")
        else:
            await update.message.reply_text("Nu am găsit acest URL în lista ta.")
        return

    if pending_action == "set_keyword":
        keyword = text.strip()
        cursor.execute("UPDATE users SET keyword=? WHERE chat_id=?", (keyword, chat_id))
        db.commit()
        context.user_data.pop("pending_action", None)
        await update.message.reply_text("Keyword salvat ✔")
        return

    if pending_action == "set_price":
        try:
            min_price_str, max_price_str = text.split()
            min_price = int(min_price_str)
            max_price = int(max_price_str)
            if min_price > max_price:
                await update.message.reply_text("MIN trebuie să fie <= MAX.")
                return

            cursor.execute(
                "UPDATE users SET min_price=?, max_price=? WHERE chat_id=?",
                (min_price, max_price, chat_id),
            )
            db.commit()
            context.user_data.pop("pending_action", None)
            await update.message.reply_text("Interval preț salvat ✔")
        except ValueError:
            await update.message.reply_text("Format corect: 30000 150000")
        return


# ------------------ MONITOR ------------------

async def monitor(app):
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
                    sites = get_user_sites(chat_id)[:MAX_SITES_PER_USER]
                    if not sites:
                        continue

                    normalized_words = normalize_text(keyword).split() if keyword else []

                    for site in sites:
                        page = await browser.new_page()
                        try:
                            await page.goto(site, wait_until="domcontentloaded", timeout=60000)
                            await page.wait_for_timeout(2500)
                            html = await page.content()
                        except Exception as e:
                            print(f"Eroare la încărcarea site-ului {site}: {e}")
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
                            scheme = urlparse(href).scheme
                            if scheme not in {"http", "https"}:
                                continue

                            normalized_title = normalize_text(title_raw)
                            parent_text = normalize_text(link.parent.get_text(" ", strip=True))

                            if normalized_words and not all(
                                word in f"{normalized_title} {parent_text}" for word in normalized_words
                            ):
                                continue

                            price = parse_price(parent_text)
                            if price is None or not (min_price <= price <= max_price):
                                continue

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
                                text=(
                                    "🏠 OFERTĂ NOUĂ\n\n"
                                    f"{title_raw}\n\n"
                                    f"💰 Preț: {price}\n"
                                    f"🌐 Site: {site}\n"
                                    f"🔗 {href}"
                                ),
                            )
                            break

                await browser.close()
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
