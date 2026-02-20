import json
import logging
import os
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
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
SEEN_FILE = Path("seen.json")

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


# ---------------- CONFIG HELPERS ----------------

def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Config invalid. Using default.")
        return DEFAULT_CONFIG.copy()

    merged = DEFAULT_CONFIG.copy()
    merged.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    merged["sites"] = list(merged.get("sites", []))
    merged["alerts_enabled"] = bool(merged.get("alerts_enabled", True))
    return merged


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def clear_runtime_files() -> None:
    save_config(DEFAULT_CONFIG.copy())
    if SEEN_FILE.exists():
        SEEN_FILE.unlink()


def config_message(config: dict[str, Any]) -> str:
    sites = "\n".join(f"- {site}" for site in config["sites"]) or "(niciun site setat)"
    status = "Pornite" if config.get("alerts_enabled", True) else "Oprite"
    return (
        "Setări curente:\n"
        f"Site-uri:\n{sites}\n"
        f"Keyword: {config['keyword'] or '(gol)'}\n"
        f"Min: {config['min']}\n"
        f"Max: {config['max']}\n"
        f"Alerte: {status}"
    )


# ---------------- HANDLERS ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat:
        logger.info(f"START from chat_id: {update.effective_chat.id}")

    context.user_data["awaiting"] = None

    if update.message:
        await update.message.reply_text(
            "Salut! Configurează din butoanele de mai jos sau cu comenzile clasice."
            "\nPoți folosi și /showconfig, /resetconfig.",
            reply_markup=MAIN_KEYBOARD,
        )

        await update.message.reply_text(
            "Ai și buton de resetare rapidă:",
            reply_markup=RESET_INLINE_KEYBOARD,
        )


async def show_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    config = load_config()
    await update.message.reply_text(
        config_message(config),
        reply_markup=RESET_INLINE_KEYBOARD,
    )


async def reset_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_runtime_files()
    context.user_data["awaiting"] = None

    if update.callback_query:
        await update.callback_query.answer("Setările au fost șterse.")
        await update.callback_query.edit_message_text("✅ Setările au fost șterse.")
    elif update.message:
        await update.message.reply_text("✅ Setările au fost șterse.", reply_markup=MAIN_KEYBOARD)


async def handle_reset_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query and update.callback_query.data == "reset_config":
        await reset_config(update, context)


async def handle_button_and_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    if update.effective_chat:
        logger.info(f"MESSAGE from chat_id: {update.effective_chat.id}")

    text = (update.message.text or "").strip().lower()

    config = load_config()

    if text == "show config":
        await show_config(update, context)
        return

    if text == "reset config":
        await reset_config(update, context)
        return

    if text == "start alerts":
        config["alerts_enabled"] = True
        save_config(config)
        await update.message.reply_text("✅ Alertele au fost pornite.")
        return

    if text == "stop alerts":
        config["alerts_enabled"] = False
        save_config(config)
        await update.message.reply_text("⏸️ Alertele au fost oprite.")
        return

    await update.message.reply_text(
        "Comandă necunoscută. Folosește butoanele sau /start.",
        reply_markup=MAIN_KEYBOARD,
    )


# ---------------- MAIN ----------------

def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Lipsește TELEGRAM_TOKEN.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("showconfig", show_config))
    app.add_handler(CommandHandler("resetconfig", reset_config))
    app.add_handler(CallbackQueryHandler(handle_reset_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_and_input))

    logger.info("Botul pornește...")
    app.run_polling()


if __name__ == "__main__":
    main()
