import os
import sqlite3
import asyncio
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from playwright.async_api import async_playwright

TOKEN = os.getenv("TELEGRAM_TOKEN")

db = sqlite3.connect("data.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    site TEXT,
    keyword TEXT,
    min_price INTEGER,
    max_price INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS seen (
    chat_id INTEGER,
    link TEXT
)
""")
db.commit()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["Set Site", "Set Keyword"],
        ["Set Price", "Show Config"]
    ]
    await update.message.reply_text(
        "Bot activ. Alege o opțiune:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    chat_id = update.message.chat_id

    cursor.execute(
        "INSERT OR IGNORE INTO users (chat_id, min_price, max_price) VALUES (?, 0, 999999999)",
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
        _, minp, maxp = text.split()
        cursor.execute(
            "UPDATE users SET min_price=?, max_price=? WHERE chat_id=?",
            (int(minp), int(maxp), chat_id)
        )
        db.commit()
        await update.message.reply_text("Interval preț salvat ✔")

    elif text == "Show Config":
        cursor.execute(
            "SELECT site, keyword, min_price, max_price FROM users WHERE chat_id=?",
            (chat_id,)
        )
        data = cursor.fetchone()
        await update.message.reply_text(
            f"Config:\nSite: {data[0]}\nKeyword: {data[1]}\nMin: {data[2]}\nMax: {data[3]}"
        )


def parse_price(text):
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


async def monitor():
    while True:
        await asyncio.sleep(30)

        cursor.execute("SELECT chat_id, site, keyword, min_price, max_price FROM users")
        users = cursor.fetchall()

        if not users:
            continue

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            for chat_id, site, keyword, min_price, max_price in users:
                if not site:
                    continue

                try:
                    page = await browser.new_page()
                    await page.goto(site, timeout=60000)
                    await page.wait_for_timeout(5000)

                    links = await page.query_selector_all("a")

                    for link in links:
                        title = (await link.inner_text()).lower()
                        href = await link.get_attribute("href")

                        if not href or not href.startswith("http"):
                            continue

                        if keyword and keyword.lower() not in title:
                            continue

                        parent_text = await link.evaluate("el => el.parentElement.innerText")
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

                            await page.close()

                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=f"OFERTĂ NOUĂ\n{title}\nPreț: {price}\n{href}"
                            )
                            break

                    await page.close()

                except Exception as e:
                    print("Eroare:", e)

            await browser.close()


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

async def on_startup(app):
    asyncio.create_task(monitor())

app.post_init = on_startup
app.run_polling()
