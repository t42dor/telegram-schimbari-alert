import os
import logging
import json
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

DATA_FILE = Path("users.json")


TOKEN = os.environ["TELEGRAM_TOKEN"]

# ---------------- MENU ----------------

def main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Set Price", callback_data="price")],
        [InlineKeyboardButton("🔎 Set Keyword", callback_data="keyword")],
        [InlineKeyboardButton("🔔 Toggle Alert", callback_data="alert")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    context.user_data["min"] = 0
    context.user_data["max"] = 999999999
    context.user_data["keyword"] = ""
    context.user_data["alerts_enabled"] = True
    context.user_data["state"] = None

    await update.message.reply_text(
        "Bot pornit. Alege:",
        reply_markup=main_menu()
    )

# ---------------- BUTTON HANDLER ----------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "price":
        context.user_data["state"] = "awaiting_price"
        await query.edit_message_text("Introdu: min max (ex: 1000 5000)")

    elif data == "keyword":
        context.user_data["state"] = "awaiting_keyword"
        await query.edit_message_text("Introdu cuvânt cheie:")

    elif data == "alert":
        current = context.user_data.get("alerts_enabled", True)
        context.user_data["alerts_enabled"] = not current

        status = "ACTIVĂ" if context.user_data["alerts_enabled"] else "OPRITĂ"

        await query.edit_message_text(
            f"Alerta este acum: {status}",
            reply_markup=main_menu()
        )

# ---------------- TEXT HANDLER ----------------

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")

    if state == "awaiting_price":
        try:
            parts = update.message.text.split()
            min_price = int(parts[0])
            max_price = int(parts[1])

            context.user_data["min"] = min_price
            context.user_data["max"] = max_price
            context.user_data["state"] = None

            await update.message.reply_text(
                f"Preț setat: {min_price} - {max_price}",
                reply_markup=main_menu()
            )
        except:
            await update.message.reply_text(
                "Format invalid. Exemplu: 1000 5000"
            )

    elif state == "awaiting_keyword":
        keyword = update.message.text.strip().lower()

        context.user_data["keyword"] = keyword
        context.user_data["state"] = None

        await update.message.reply_text(
            f"Cuvânt cheie setat: {keyword}",
            reply_markup=main_menu()
        )

    else:
        await update.message.reply_text(
            "Nu sunt în modul de setare. Folosește butoanele.",
            reply_markup=main_menu()
        )

def load_users():
    if not DATA_FILE.exists():
        return {}

    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users(data):
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_user(chat_id):
    users = load_users()
    if str(chat_id) not in users:
        users[str(chat_id)] = {
            "keyword": "",
            "min": 0,
            "max": 999999999,
            "sites": [],
            "alerts_enabled": True,
            "seen": []
        }
        save_users(users)
    return users[str(chat_id)]

def update_user(chat_id, user_data):
    users = load_users()
    users[str(chat_id)] = user_data
    save_users(users)

# ---------------- SCHEDULER ----------------

from playwright.async_api import async_playwright

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    print("=== PORNESC PLAYWRIGHT ===")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto("https://example.com", timeout=60000)

            title = await page.title()
            print("Titlu pagină:", title)

            await browser.close()

    except Exception as e:
        print("EROARE PLAYWRIGHT:", e)


# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    # Scheduler la fiecare 60 sec
    app.job_queue.run_repeating(scheduled_check, interval=60, first=15)

    print("=== BOT CU STATE + SCHEDULER ===")

    app.run_polling()

if __name__ == "__main__":
    main()
