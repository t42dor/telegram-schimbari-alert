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
    if row and row[0]:
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
    print(f"DEBUG: get_user_sites pentru {chat_id} → găsit {len(rows)} site-uri")
    return [row[0] for row in rows]

# ------------------ UTIL ------------------
def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def parse_price(text: str) -> int | None:
    text_clean = text.lower().replace(" ", "").replace(",", "").replace(".", "")
    digits = "".join(c for c in text_clean if c.isdigit())
    if not digits:
        return None
    price = int(digits)
    # Detectăm dacă e preț în mii (ex: 120.000 → 120000)
    if "mii" in text_clean or "k" in text_clean or len(digits) >= 6:
        price = int(digits)  # deja corect
    return price

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
    print(f"DEBUG: User {update.message.chat_id} a apelat /start")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id
    print(f"DEBUG: MESSAGE HANDLER apelat! Mesaj: '{text}' de la {chat_id}")
    print(f"DEBUG: Pending action curent: {context.user_data.get('pending_action')}")

    ensure_user(chat_id)
    migrate_legacy_single_site(chat_id)

    if text == "Add Site":
        print("DEBUG: Intrat pe Add Site")
        context.user_data["pending_action"] = "add_site"
        await update.message.reply_text(
            "Trimite URL-ul paginii de căutare pe care vrei monitorizare. (maxim 5 site-uri)"
        )
        return

    if text == "Remove Site":
        print("DEBUG: Intrat pe Remove Site")
        context.user_data["pending_action"] = "remove_site"
        await update.message.reply_text("Trimite URL-ul exact pe care vrei să îl ștergi.")
        return

    if text == "List Sites":
        print("DEBUG: Intrat pe List Sites")
        context.user_data.pop("pending_action", None)
        sites = get_user_sites(chat_id)
        if not sites:
            await update.message.reply_text("Nu ai site-uri configurate încă.")
            return
        formatted = "\n".join(f"{idx + 1}. {site}" for idx, site in enumerate(sites))
        await update.message.reply_text(f"Site-uri configurate ({len(sites)}/{MAX_SITES_PER_USER}):\n{formatted}")
        return

    if text == "Set Keyword":
        print("DEBUG: Intrat pe Set Keyword")
        context.user_data["pending_action"] = "set_keyword"
        await update.message.reply_text("Trimite keyword-ul (ex: apartament brasov).")
        return

    if text == "Set Price":
        print("DEBUG: Intrat pe Set Price")
        context.user_data["pending_action"] = "set_price"
        await update.message.reply_text("Trimite intervalul de preț: MIN MAX (ex: 30000 150000).\nDacă nu vrei filtru de preț, pune 0 999999999")
        return

    if text == "Stop Alerts":
        print("DEBUG: Intrat pe Stop Alerts")
        context.user_data.pop("pending_action", None)
        cursor.execute("UPDATE users SET active=0 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🔴 Alertele au fost oprite.")
        return

    if text == "Start Alerts":
        print("DEBUG: Intrat pe Start Alerts")
        context.user_data.pop("pending_action", None)
        cursor.execute("UPDATE users SET active=1 WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("🟢 Alertele au fost activate.")
        return

    if text == "Show Config":
        print("DEBUG: Intrat pe Show Config")
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
        print("DEBUG: Intrat pe Reset Config")
        context.user_data.pop("pending_action", None)
        cursor.execute(
            "UPDATE users SET keyword=NULL, min_price=0, max_price=999999999, active=1 WHERE chat_id=?",
            (chat_id,),
        )
        cursor.execute("DELETE FROM user_sites WHERE chat_id=?", (chat_id,))
        cursor.execute("DELETE FROM seen WHERE chat_id=?", (chat_id,))
        db.commit()
        await update.message.reply_text("♻️ Config resetată.")
        return

    pending_action = context.user_data.get("pending_action")
    print(f"DEBUG: Pending action după if-uri principale: {pending_action}")

    if pending_action == "add_site":
        print("DEBUG: Procesare add_site - URL: " + text)
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
            print(f"DEBUG: Site adăugat OK: {text}")
        except sqlite3.IntegrityError:
            await update.message.reply_text("Site-ul există deja în listă.")
        return

    if pending_action == "remove_site":
        print("DEBUG: Procesare remove_site - URL: " + text)
        cursor.execute(
            "DELETE FROM user_sites WHERE chat_id=? AND site=?",
            (chat_id, text),
        )
        deleted = cursor.rowcount
        db.commit()
        if deleted:
            context.user_data.pop("pending_action", None)
            await update.message.reply_text("Site șters ✔")
            print(f"DEBUG: Site șters OK: {text}")
        else:
            await update.message.reply_text("Nu am găsit acest URL în lista ta.")
        return

    if pending_action == "set_keyword":
        print("DEBUG: Procesare set_keyword - keyword: " + text)
        keyword = text.strip()
        cursor.execute("UPDATE users SET keyword=? WHERE chat_id=?", (keyword, chat_id))
        db.commit()
        context.user_data.pop("pending_action", None)
        await update.message.reply_text("Keyword salvat ✔")
        print(f"DEBUG: Keyword salvat: {keyword}")
        return

    if pending_action == "set_price":
        print("DEBUG: Procesare set_price - input: " + text)
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
            print(f"DEBUG: Preț salvat: {min_price} - {max_price}")
        except ValueError:
            await update.message.reply_text("Format corect: 30000 150000\nSau 0 999999999 dacă nu vrei filtru de preț")
        return

    print(f"DEBUG: Handler terminat - mesaj '{text}' nu a fost procesat ca buton sau pending")

# ------------------ MONITOR ------------------
async def monitor(app):
    print("DEBUG: Monitor pornit - buclă infinită")
    while True:
        print("DEBUG: Ciclu monitor nou - verific users active...")
        cursor.execute(
            "SELECT chat_id, keyword, min_price, max_price FROM users WHERE active=1"
        )
        users = cursor.fetchall()
        print(f"DEBUG: {len(users)} user-i activi găsiți")

        try:
            async with async_playwright() as p:
                print("DEBUG: Pornesc browser...")
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                print("DEBUG: Browser pornit")

                for chat_id, keyword, min_price, max_price in users:
                    sites = get_user_sites(chat_id)
                    if not sites:
                        print(f"DEBUG: User {chat_id} nu are site-uri")
                        continue

                    normalized_words = normalize_text(keyword).split() if keyword else []
                    print(f"DEBUG: Caut pentru user {chat_id} - keyword '{keyword}', preț {min_price}-{max_price}")

                    for site in sites:
                        print(f"DEBUG: Accesez: {site}")
                        page = await browser.new_page()
                        try:
                            await page.goto(site, wait_until="domcontentloaded", timeout=60000)
                            await page.wait_for_timeout(10000)  # crescut pentru JS
                            await page.wait_for_load_state('networkidle', timeout=30000)
                            html = await page.content()
                            print(f"DEBUG: HTML încărcat ({len(html)} caractere)")
                        except Exception as e:
                            print(f"DEBUG: Eroare încărcare {site}: {e}")
                            await page.close()
                            continue
                        await page.close()

                        soup = BeautifulSoup(html, "lxml")
                        links = soup.find_all("a")
                        print(f"DEBUG: Găsit {len(links)} tag-uri <a>")

                        for link in links:
                            title_raw = link.get_text(strip=True)
                            href = link.get("href")
                            if not href or not title_raw:
                                continue
                            href = urljoin(site, href)
                            if urlparse(href).scheme not in {"http", "https"}:
                                continue

                            normalized_title = normalize_text(title_raw)
                            parent_text = normalize_text(link.parent.get_text(" ", strip=True))
                            combined_text = f"{normalized_title} {parent_text}"

                            # Verificăm keyword-ul
                            if normalized_words and not all(
                                word in combined_text for word in normalized_words
                            ):
                                continue

                            price = parse_price(parent_text)
                            print(f"DEBUG: Preț detectat: {price} din text: '{parent_text[:80]}...'")

                            # Dacă nu avem interval strict de preț → trimitem chiar dacă prețul lipsește
                            price_ok = True
                            if min_price != 0 or max_price != 999999999:
                                if price is None or not (min_price <= price <= max_price):
                                    price_ok = False

                            if not price_ok:
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

                            price_text = f"💰 Preț: {price}" if price is not None else "💰 Preț: nedetectat"
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=(
                                    "🏠 OFERTĂ NOUĂ\n\n"
                                    f"{title_raw}\n\n"
                                    f"{price_text}\n"
                                    f"🌐 Site: {site}\n"
                                    f"🔗 {href}"
                                ),
                            )
                            print(f"DEBUG: ALERTĂ TRIMISĂ: {title_raw} | Preț: {price} | {href}")
                            break  # oprește după prima alertă pe site (poți scoate break-ul dacă vrei toate)

                await browser.close()
                print("DEBUG: Browser închis")
        except Exception as e:
            print(f"DEBUG: Eroare în monitor: {e}")

        print(f"DEBUG: Ciclu terminat - sleep {ALERT_INTERVAL_SECONDS}s")
        await asyncio.sleep(ALERT_INTERVAL_SECONDS)

# ------------------ START APP ------------------
print("DEBUG: Construiesc Application...")
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

async def on_startup(app):
    print("DEBUG: ON_STARTUP - creez monitor...")
    asyncio.create_task(monitor(app))
    print("DEBUG: Task monitor creat")

app.post_init = on_startup

print("DEBUG: Pornesc polling-ul...")
app.run_polling()
print("DEBUG: run_polling terminat (nu ar trebui să ajungem aici)")
