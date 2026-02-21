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

print(f"DEBUG: Token încărcat (primele 10 caractere vizibile): {TOKEN[:10]}... (restul ascuns)")

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
    print(f"DEBUG: User {update.message.chat_id} a apelat /start și a primit meniu")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id
   
    print(f"DEBUG: MESSAGE HANDLER apelat! Mesaj primit: '{text}' de la user {chat_id}")
    print(f"DEBUG: Pending action curent: {context.user_data.get('pending_action')}")

    ensure_user(chat_id)
    migrate_legacy_single_site(chat_id)

    if text == "Add Site":
        print("DEBUG: Intrat pe buton Add Site")
        context.user_data["pending_action"] = "add_site"
        await update.message.reply_text(
            "Trimite URL-ul paginii de căutare pe care vrei monitorizare. (maxim 5 site-uri)"
        )
        return

    # ... restul if-urilor pentru butoane exact ca în codul tău original ...

    pending_action = context.user_data.get("pending_action")
    print(f"DEBUG: Pending action după if-uri principale: {pending_action}")

    if pending_action == "add_site":
        print("DEBUG: Procesare add_site - URL primit: " + text)
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
            print(f"DEBUG: Site adăugat cu succes: {text} pentru user {chat_id}")
        except sqlite3.IntegrityError:
            await update.message.reply_text("Site-ul există deja în listă.")
        return

    # ... restul pending_action la fel ca în codul tău ...

    print(f"DEBUG: Handler terminat - mesaj '{text}' nu a fost procesat ca buton sau pending action")

# ------------------ MONITOR ------------------
async def monitor(app):
    print("DEBUG: Funcția monitor a început - buclă infinită pornită")
    while True:
        print("DEBUG: Ciclu monitor nou - verific users active...")
        cursor.execute(
            "SELECT chat_id, keyword, min_price, max_price FROM users WHERE active=1"
        )
        users = cursor.fetchall()
        print(f"DEBUG: {len(users)} user-i activi găsiți")

        try:
            async with async_playwright() as p:
                print("DEBUG: Pornesc browser Chromium headless...")
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                print("DEBUG: Browser pornit cu succes")

                for chat_id, keyword, min_price, max_price in users:
                    sites = get_user_sites(chat_id)[:MAX_SITES_PER_USER]
                    if not sites:
                        print(f"DEBUG: User {chat_id} nu are site-uri configurate, sar peste")
                        continue

                    normalized_words = normalize_text(keyword).split() if keyword else []
                    print(f"DEBUG: Caut pentru user {chat_id} - keyword '{keyword}', preț {min_price}-{max_price}")

                    for site in sites:
                        print(f"DEBUG: Accesez site: {site}")
                        page = await browser.new_page()
                        try:
                            await page.goto(site, wait_until="domcontentloaded", timeout=60000)
                            await page.wait_for_timeout(10000)  # <--- AICI E DIFERENȚA: 10 secunde
                            await page.wait_for_load_state('networkidle', timeout=30000)
                            html = await page.content()
                            print(f"DEBUG: HTML încărcat de pe {site} (lungime: {len(html)} caractere)")
                        except Exception as e:
                            print(f"DEBUG: Eroare la încărcarea site-ului {site}: {e}")
                            await page.close()
                            continue
                        await page.close()

                        soup = BeautifulSoup(html, "lxml")
                        links = soup.find_all("a")
                        print(f"DEBUG: Găsit {len(links)} tag-uri <a> pe pagină")

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

                            print(f"DEBUG: OFERTĂ NOUĂ DETECTATĂ pentru user {chat_id} - {title_raw} | Preț: {price} | Link: {href}")

                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    "🏠 OFERTĂ NOUĂ\n\n"
                                    f"{title_raw}\n\n"
                                    f"💰 Preț: {price if price is not None else 'nedetectat'}\n"
                                    f"🌐 Site: {site}\n"
                                    f"🔗 {href}"
                                ),
                            )
                            break

                await browser.close()
                print("DEBUG: Browser închis după ciclu")
        except Exception as e:
            print(f"DEBUG: Eroare majoră în monitor loop: {e}")

        print(f"DEBUG: Ciclu terminat - sleep {ALERT_INTERVAL_SECONDS} secunde")
        await asyncio.sleep(ALERT_INTERVAL_SECONDS)

# ------------------ START APP ------------------
print("DEBUG: Construiesc ApplicationBuilder...")
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

async def on_startup(app):
    print("DEBUG: ON_STARTUP apelat - creez task pentru monitor...")
    asyncio.create_task(monitor(app))
    print("DEBUG: Task monitor creat cu succes")

app.post_init = on_startup

print("DEBUG: Încep polling-ul Telegram acum...")
app.run_polling()
print("DEBUG: run_polling a terminat neașteptat (nu ar trebui să ajungem aici)")
