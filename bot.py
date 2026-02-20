import os
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

# ---------------- MENU ----------------

def main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Set Price", callback_data="set_price")],
        [InlineKeyboardButton("🔎 Set Keyword", callback_data="set_keyword")],
        [InlineKeyboardButton("🔔 Toggle Alert", callback_data="toggle_alert")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault("min", 0)
    context.user_data.setdefault("max", 999999999)
    context.user_data.setdefault("keyword", "")
    context.user_data.setdefault("alerts_enabled", True)
    context.user_data.setdefault("state", None)

    await update.message.reply_text(
        "🤖 Bot pornit.\nAlege o opțiune:",
        reply_markup=main_menu(),
    )

# ---------------- BUTTONS ----------------

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "set_price":
        context.user_data["state"] = "awaiting_price"
        await query.edit_message_text("Introdu: min max (ex: 1000 5000)")

    elif data == "set_keyword":
        context.user_data["state"] = "awaiting_keyword"
        await query.edit_message_text("Introdu cuvânt cheie:")

    elif data == "toggle_alert":
        current = context.user_data.get("alerts_enabled", True)
        context.user_data["alerts_enabled"] = not current
        status = "ACTIVĂ" if not current else "OPRITĂ"

        await query.edit_message_text(
            f"Alerta este acum: {status}",
            reply_markup=main_menu(),
        )

# ---------------- TEXT INPUT ----------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")

    if state == "awaiting_price":
        try:
            parts = update.message.text.split()
            context.user_data["min"] = int(parts[0])
            context.user_data["max"] = int(parts[1])
            context.user_data["state"] = None

            await update.message.reply_text(
                f"Preț setat: {parts[0]} - {parts[1]}",
                reply_markup=main_menu(),
            )
        except:
            await update.message.reply_text("Format invalid. Exemplu: 1000 5000")

    elif state == "awaiting_keyword":
        context.user_data["keyword"] = update.message.text.lower()
        context.user_data["state"] = None

        await update.message.reply_text(
            f"Cuvânt cheie setat: {update.message.text}",
            reply_markup=main_menu(),
        )

# ---------------- PLAYWRIGHT CHECK ----------------

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    print("=== RUNNING PLAYWRIGHT CHECK ===")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://example.com")
            await browser.close()
    except Exception as e:
        print("PLAYWRIGHT ERROR:", e)
        return

    for chat_id in context.application.chat_data:
        # demonstrativ — aici va fi logica reală
        pass

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduler safe
    app.job_queue.run_repeating(scheduled_check, interval=60, first=15)

    print("=== BOT COMPLET PORNIT ===")

    app.run_polling()

if __name__ == "__main__":
    main()
