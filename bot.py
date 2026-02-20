import json
import logging
import os
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
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
}


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Config file invalid. Falling back to default config.")
        return DEFAULT_CONFIG.copy()

    merged = DEFAULT_CONFIG.copy()
    merged.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    merged["sites"] = list(merged.get("sites", []))
    return merged


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def clear_runtime_files() -> None:
    save_config(DEFAULT_CONFIG.copy())
    if SEEN_FILE.exists():
        SEEN_FILE.unlink()


def parse_config_message(text: str) -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        upper = line.upper()

        if upper.startswith("SITE="):
            config["sites"].append(line.split("=", 1)[1].strip())
        elif upper.startswith("KEYWORD="):
            config["keyword"] = line.split("=", 1)[1].strip().lower()
        elif upper.startswith("MIN="):
            config["min"] = int(line.split("=", 1)[1].strip())
        elif upper.startswith("MAX="):
            config["max"] = int(line.split("=", 1)[1].strip())

    if config["min"] > config["max"]:
        raise ValueError("MIN nu poate fi mai mare decât MAX.")

    return config


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("🧹 Șterge setările actuale", callback_data="reset_config")]]
    await update.message.reply_text(
        "Salut!\n"
        "Folosește /setconfig cu formatul:\n"
        "SITE=https://exemplu1.ro\n"
        "SITE=https://exemplu2.ro\n"
        "KEYWORD=iphone\n"
        "MIN=500\n"
        "MAX=2500\n\n"
        "Folosește /showconfig ca să vezi setările curente.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def set_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await update.message.reply_text(
            "Trimite configurația după comandă, cu linii separate prin ENTER.\n"
            "Exemplu:\n"
            "/setconfig SITE=https://site.ro\nKEYWORD=masina\nMIN=1000\nMAX=5000"
        )
        return

    try:
        config = parse_config_message(text)
    except ValueError as exc:
        await update.message.reply_text(f"Config invalid: {exc}")
        return

    save_config(config)
    await update.message.reply_text("✅ Setările au fost salvate.")


async def show_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = load_config()
    sites = "\n".join(f"- {site}" for site in config["sites"]) or "(niciun site setat)"

    keyboard = [[InlineKeyboardButton("🧹 Șterge setările actuale", callback_data="reset_config")]]
    await update.message.reply_text(
        "Setări curente:\n"
        f"Site-uri:\n{sites}\n"
        f"Keyword: {config['keyword'] or '(gol)'}\n"
        f"Min: {config['min']}\n"
        f"Max: {config['max']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def reset_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_runtime_files()

    if update.callback_query:
        await update.callback_query.answer("Setările au fost șterse.")
        await update.callback_query.edit_message_text("✅ Setările actuale au fost șterse.")
    elif update.message:
        await update.message.reply_text("✅ Setările actuale au fost șterse.")


async def handle_reset_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query and update.callback_query.data == "reset_config":
        await reset_config(update, context)


def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Lipsește TELEGRAM_TOKEN din variabilele de mediu.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setconfig", set_config))
    app.add_handler(CommandHandler("showconfig", show_config))
    app.add_handler(CommandHandler("resetconfig", reset_config))
    app.add_handler(CallbackQueryHandler(handle_reset_button))

    logger.info("Botul pornește...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
