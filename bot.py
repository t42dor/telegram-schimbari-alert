import os
import logging
import json
from pathlib import Path
from typing import Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from playwright.async_api import async_playwright

# ---------------- CONFIG ----------------

TOKEN = os.environ["TELEGRAM_TOKEN"]
DATA_FILE = Path("users.json")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- DATA LAYER ----------------


def load_users() -> Dict[str, Any]:
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_users(data: Dict[str, Any]) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_user(chat_id: int) -> Dict[str, Any]:
    users = load_users()
    cid = str(chat_id)

    if cid not in users:
        users[cid] = {
            "keyword": "",
            "min": 0,
            "max": 999999999,
            "sites": [],
            "alerts_enabled": True,
            "seen": [],
        }
        save_users(users)

    return users[cid]


def update_user(chat_id: int, data: Dict[str, Any]) -> None:
    users = load_users()
    users[str(chat_id)] = data
    save_users(users)


# ---------------- MENU ----------------

def main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("Set Keyword", callback_data="set_keyword")],
        [InlineKeyboardButton("Set Price Range", callback_data="set_price")],
        [InlineKeyboardButton("Add Site", callback_data="add_site")],
        [InlineKeyboardButton("View Settings", callback_data="view_settings")],
        [InlineKeyboardButton("Toggle Alerts", callback_data="toggle_alerts")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ---------------- COMMANDS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    del context
    if update.effective_message:
        await update.effective_message.reply_text("Bot activ.", reply_markup=main_menu())


# ---------------- CALLBACK HANDLER ----------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()

    chat = update.effective_chat
    if not chat:
        return

    chat_id = chat.id
    user = get_user(chat_id)

    if query.data == "set_keyword":
        context.user_data["state"] = "waiting_keyword"
        await query.message.reply_text("Trimite keyword:")

    elif query.data == "set_price":
        context.user_data["state"] = "waiting_price"
        await query.message.reply_text("Trimite min și max separate prin spațiu (ex: 1000 5000):")

    elif query.data == "add_site":
        if len(user["sites"]) >= 5:
            await query.message.reply_text("Ai deja 5 site-uri.")
        else:
            context.user_data["state"] = "waiting_site"
            await query.message.reply_text("Trimite URL site:")

    elif query.data == "view_settings":
        msg = (
            f"Keyword: {user['keyword']}\n"
            f"Min: {user['min']}\n"
            f"Max: {user['max']}\n"
            f"Sites: {user['sites']}\n"
            f"Alerts: {user['alerts_enabled']}"
        )
        await query.message.reply_text(msg)

    elif query.data == "toggle_alerts":
        user["alerts_enabled"] = not user["alerts_enabled"]
        update_user(chat_id, user)
        await query.message.reply_text(f"Alerts: {user['alerts_enabled']}")

    if query.message:
        await query.message.reply_text("Alege o opțiune:", reply_markup=main_menu())


# ---------------- MESSAGE HANDLER ----------------

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    state = context.user_data.get("state")

    if state == "waiting_keyword":
        user["keyword"] = update.effective_message.text.lower()
        update_user(chat_id, user)
        context.user_data["state"] = None
        await update.effective_message.reply_text("Keyword set.", reply_markup=main_menu())

    elif state == "waiting_price":
        try:
            parts = update.effective_message.text.split()
            if len(parts) != 2:
                raise ValueError("Expected exactly two values")

            minimum = int(parts[0])
            maximum = int(parts[1])
            if minimum > maximum:
                raise ValueError("Minimum must not exceed maximum")

            user["min"] = minimum
            user["max"] = maximum
            update_user(chat_id, user)
            await update.effective_message.reply_text("Price range set.", reply_markup=main_menu())
        except ValueError:
            await update.effective_message.reply_text(
                "Format invalid. Exemplu corect: 1000 5000", reply_markup=main_menu()
            )
        context.user_data["state"] = None

    elif state == "waiting_site":
        user["sites"].append(update.effective_message.text.strip())
        update_user(chat_id, user)
        context.user_data["state"] = None
        await update.effective_message.reply_text("Site added.", reply_markup=main_menu())


# ---------------- SCRAPER ----------------

async def check_user_sites(chat_id: int, user: Dict[str, Any], app):
    if not user["alerts_enabled"] or not user["sites"]:
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for site in user["sites"]:
            try:
                page = await browser.new_page()
                await page.goto(site, timeout=60000)
                content = await page.content()

                if user["keyword"] and user["keyword"] in content.lower():
                    await app.bot.send_message(chat_id, f"Keyword găsit pe {site}")

                await page.close()
            except Exception as e:
                logger.warning("Eroare site %s: %s", site, e)

        await browser.close()


# ---------------- SCHEDULER ----------------

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    for chat_id_str, user in users.items():
        try:
            await check_user_sites(int(chat_id_str), user, context.application)
        except Exception as e:
            logger.warning("Eroare user %s: %s", chat_id_str, e)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception for update %s", update, exc_info=context.error)


# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    app.job_queue.run_repeating(scheduled_check, interval=60, first=10)

    print("=== BOT COMPLET PORNIT ===")
    app.run_polling()


if __name__ == "__main__":
    main()
