import json
import logging
import os
from pathlib import Path
from typing import Any

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

CONFIG_FILE = Path("config.json")

DEFAULT_CONFIG = {
    "sites": [],
    "keyword": "",
    "min": 0,
    "max": 999_999_999,
    "alerts_enabled": True,
}

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["Set Site", "Set Keyword"],
        ["Set Price", "Show Config"],
        ["Start Alerts", "Stop Alerts"],
        ["Reset Config"],
    ],
    resize_keyboard=True,
)

RESET_INLINE_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🧹 Șterge setările actuale", callback_data="reset_config")]]
)


# ================= CONFIG ================= #

def load_all_configs():
    if not CONFIG_FILE.exists():
        return {}
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_all_configs(configs):
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(configs, f, ensure_ascii=False, indent=2)


def get_user_config(chat_id: str):
    configs = load_all_configs()
    if chat_id not in configs:
        configs[chat_id] = DEFAULT_CONFIG.copy()
        save_all_configs(configs)
    return configs[chat_id]


def update_user_config(chat_id: str, new_config):
    configs = load_all_configs()
    configs[chat_id] = new_config
    save_all_configs(configs)


def config_message(config: dict[str, Any]) -> str:
    sites = "\n".join(f"- {s}" for s in config["sites"]) or "(niciun site)"
    status = "Pornite" if config.get("alerts_enabled", True) else "Oprite"
    return (
        "Setări curente:\n"
        f"Site-uri:\n{sites}\n"
        f"Keyword: {config['keyword'] or '(gol)'}\n"
        f"Min: {config['min']}\n"
        f"Max: {config['max']}\n"
        f"Alerte: {status}"
    )


# ================= ALERT JOB ================= #

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    configs = load_all_configs()

    for chat_id, user_config in configs.items():
        if not user_config.get("alerts_enabled", True):
            continue

        await context.bot.send_message(
            chat_id=int(chat_id),
            text="⏰ Test alert automată (rulează la 60 secunde)"
        )


# ================= HANDLERS ================= #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)

    get_user_config(chat_id)

    context.user_data["awaiting"] = None

    await update.message.reply_text(
        "Salut! Configurează din butoanele de mai jos.",
        reply_markup=MAIN_KEYBOARD,
    )

    await update.message.reply_text(
        "Ai și buton de resetare rapidă:",
        reply_markup=RESET_INLINE_KEYBOARD,
    )


async def show_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)
    config = get_user_config(chat_id)
    await update.message.reply_text(config_message(config))


async def reset_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = str(update.effective_chat.id)

    update_user_config(chat_id, DEFAULT_CONFIG.copy())
    context.user_data["awaiting"] = None

    if update.callback_query:
        await update.callback_query.answer("Setările au fost șterse.")
        await update.callback_query.edit_message_text("✅ Setările au fost șterse.")
    else:
        await update.message.reply_text("✅ Setările au fost șterse.", reply_markup=MAIN_KEYBOARD)


async def handle_reset_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query and update.callback_query.data == "reset_config":
        await reset_config(update, context)


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    chat_id = str(update.effective_chat.id)
    config = get_user_config(chat_id)

    text = update.message.text.strip()
    lowered = text.lower()
    awaiting = context.user_data.get("awaiting")

    if lowered == "set site":
        context.user_data["awaiting"] = "site"
        await update.message.reply_text("Trimite URL-ul site-ului.")
        return

    if lowered == "set keyword":
        context.user_data["awaiting"] = "keyword"
        await update.message.reply_text("Trimite keyword-ul dorit.")
        return

    if lowered == "set price":
        context.user_data["awaiting"] = "price"
        await update.message.reply_text("Trimite intervalul: MIN MAX")
        return

    if lowered == "show config":
        await show_config(update, context)
        return

    if lowered == "reset config":
        await reset_config(update, context)
        return

    if lowered == "start alerts":
        config["alerts_enabled"] = True
        update_user_config(chat_id, config)
        await update.message.reply_text("✅ Alertele au fost pornite.")
        return

    if lowered == "stop alerts":
        config["alerts_enabled"] = False
        update_user_config(chat_id, config)
        await update.message.reply_text("⏸️ Alertele au fost oprite.")
        return

    if awaiting == "site":
        config["sites"] = [text]
        update_user_config(chat_id, config)
        context.user_data["awaiting"] = None
        await update.message.reply_text("✅ Site salvat.")
        return

    if awaiting == "keyword":
        config["keyword"] = text.lower()
        update_user_config(chat_id, config)
        context.user_data["awaiting"] = None
        await update.message.reply_text("✅ Keyword salvat.")
        return

    if awaiting == "price":
        parts = text.split()
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            await update.message.reply_text("Format invalid. Folosește: MIN MAX")
            return

        min_price, max_price = int(parts[0]), int(parts[1])

        if min_price > max_price:
            await update.message.reply_text("MIN nu poate fi mai mare decât MAX.")
            return

        config["min"] = min_price
        config["max"] = max_price
        update_user_config(chat_id, config)
        context.user_data["awaiting"] = None
        await update.message.reply_text("✅ Interval salvat.")
        return

    await update.message.reply_text("Comandă necunoscută.")


# ================= MAIN ================= #

def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")

    if not token:
        raise RuntimeError("Lipsește TELEGRAM_TOKEN din variabilele de mediu.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("showconfig", show_config))
    app.add_handler(CommandHandler("resetconfig", reset_config))
    app.add_handler(CallbackQueryHandler(handle_reset_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

    # PORNIM JOB AUTOMAT LA 60 SECUNDE
    job_queue = app.job_queue
    job_queue.run_repeating(scheduled_check, interval=60, first=10)

    logger.info("=== BOT MULTI-USER CU ALERTA AUTOMATA PORNIT ===")
    app.run_polling()


if __name__ == "__main__":
    main()
