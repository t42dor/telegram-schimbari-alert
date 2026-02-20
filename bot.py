import os
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

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
    await update.message.reply_text(
        "Bot pornit. Alege:",
        reply_markup=main_menu()
    )

# ---------------- BUTTON HANDLER ----------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # FOARTE IMPORTANT

    data = query.data

    if data == "price":
        await query.edit_message_text("Ai apăsat Set Price")

    elif data == "keyword":
        await query.edit_message_text("Ai apăsat Set Keyword")

    elif data == "alert":
        await query.edit_message_text("Ai apăsat Toggle Alert")

# ---------------- TEXT HANDLER ----------------

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Am primit: " + update.message.text)

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("=== BOT MINIMAL PORNIT ===")

    app.run_polling()

if __name__ == "__main__":
    main()
