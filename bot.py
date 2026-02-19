import os
import sqlite3
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
    max_price INTEGER
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


app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
app.run_polling()
