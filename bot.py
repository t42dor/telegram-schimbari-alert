import os
import json
from pathlib import Path
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from playwright.async_api import async_playwright

TOKEN = os.environ["TELEGRAM_TOKEN"]

DATA_FILE = Path("users.json")

# -----------------------
# STORAGE
# -----------------------

def load_users():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {}

def save_users(users):
    DATA_FILE.write_text(json.dumps(users))

# -----------------------
# MENU
# -----------------------

def main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Set Price", callback_data="set_price")],
        [InlineKeyboardButton("🔎 Set Keyword", callback_data="set_keyword")],
        [InlineKeyboardButton("🔔 Toggle Alert", callback_data="toggle_alert")],
    ]
    return InlineKeyboardMarkup(keyboard)

# -----------------------
# START
# -----------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)

    users = load_users()
    if chat_id not in users:
        users[chat_id] = {
            "min": 0,
            "max": 999999999,
            "keyword": "",
            "alerts_enabled": True,
            "state": None,
        }
        save_users(users)

    await update.message.reply_text(
        "🤖 Bot pornit.\nAlege o opțiune:",
        reply_markup=main_menu(),
    )

# -----------------------
# BUTTON HANDLER
# -----------------------

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = str(query.message.chat.id)
    users = load_users()

    data = query.data

    if data == "set_price":
        users[chat_id]["state"] = "awaiting_price"
        save_users(users)
        await query.edit_message_text("Introdu: min max (ex: 1000 5000)")

    elif data == "set_keyword":
        users[chat_id]["state"] = "awaiting_keyword"
        save_users(users)
        await query.edit_message_text("Introdu cuvânt cheie:")

    elif data == "toggle_alert":
        users[chat_id]["alerts_enabled"] = not users[chat_id]["alerts_enabled"]
        save_users(users)
        status = "ACTIVĂ" if users[chat_id]["alerts_enabled"] else "OPRITĂ"
        await query.edit_message_text(
            f"Alerta este acum: {status}",
            reply_markup=main_menu(),
        )

# -----------------------
# TEXT INPUT HANDLER
# -----------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    users = load_users()

    if chat_id not in users:
        return

    state = users[chat_id].get("state")

    if state == "awaiting_price":
        try:
            parts = update.message.text.split()
            users[chat_id]["min"] = int(parts[0])
            users[chat_id]["max"] = int(parts[1])
            users[chat_id]["state"] = None
            save_users(users)
            await update.message.reply_text(
                f"Preț setat: {parts[0]} - {parts[1]}",
                reply_markup=main_menu(),
            )
        except:
            await update.message.reply_text("Format invalid. Exemplu: 1000 5000")

    elif state == "awaiting_keyword":
        users[chat_id]["keyword"] = update.message.text.lower()
        users[chat_id]["state"] = None
        save_users(users)
        await update.message.reply_text(
            f"Cuvânt cheie setat: {update.message.text}",
            reply_markup=main_menu(),
        )

# -----------------------
# SCHEDULED CHECK (DEMO)
# -----------------------

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://example.com")
        await browser.close()

    for chat_id, config in users.items():
        if config["alerts_enabled"]:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⏰ Test alert automată (Playwright funcționează)",
            )

# -----------------------
# MAIN
# -----------------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.job_queue.run_repeating(scheduled_check, interval=60, first=10)

    print("=== BOT CU PLAYWRIGHT MULTI-USER PORNIT ===")

    app.run_polling()

if __name__ == "__main__":
    main()
