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
    ],
    resize_keyboard=True,
)

RESET_INLINE_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🧹 Șterge setările actuale", callback_data="reset_config")]]
)


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
    merged["alerts_enabled"] = bool(merged.get("alerts_enabled", True))
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["awaiting"] = None
    await update.message.reply_text(
        "Salut! Configurează din butoanele de mai jos sau cu comenzile clasice."
        "\nPoți folosi și /showconfig, /resetconfig.",
        reply_markup=MAIN_KEYBOARD,
    )
    await update.message.reply_text(
        "Ai și buton de resetare rapidă:",
        reply_markup=RESET_INLINE_KEYBOARD,
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
        parsed = parse_config_message(text)
    except ValueError as exc:
        await update.message.reply_text(f"Config invalid: {exc}")
        return

    current = load_config()
    parsed["alerts_enabled"] = current.get("alerts_enabled", True)
    save_config(parsed)
    await update.message.reply_text("✅ Setările au fost salvate.", reply_markup=MAIN_KEYBOARD)


async def show_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = load_config()
    await update.message.reply_text(config_message(config), reply_markup=RESET_INLINE_KEYBOARD)


async def reset_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_runtime_files()
    context.user_data["awaiting"] = None

    if update.callback_query:
        await update.callback_query.answer("Setările au fost șterse.")
        await update.callback_query.edit_message_text("✅ Setările actuale au fost șterse.")
    elif update.message:
        await update.message.reply_text("✅ Setările actuale au fost șterse.", reply_markup=MAIN_KEYBOARD)


async def handle_reset_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query and update.callback_query.data == "reset_config":
        await reset_config(update, context)


async def handle_button_and_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    lowered = text.lower()
    awaiting = context.user_data.get("awaiting")

    if lowered == "set site":
        context.user_data["awaiting"] = "site"
        await update.message.reply_text(
            "Trimite URL-ul site-ului (ex: https://www.olx.ro).\n"
            "Dacă vrei mai multe, trimite mai multe linii.",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if lowered == "set keyword":
        context.user_data["awaiting"] = "keyword"
        await update.message.reply_text("Trimite keyword-ul dorit.", reply_markup=MAIN_KEYBOARD)
        return

    if lowered == "set price":
        context.user_data["awaiting"] = "price"
        await update.message.reply_text(
            "Trimite intervalul în format: MIN MAX (ex: 500 2500).",
            reply_markup=MAIN_KEYBOARD,
        )
        return

    if lowered == "show config":
        await show_config(update, context)
        return

    if lowered == "start alerts":
        config = load_config()
        config["alerts_enabled"] = True
        save_config(config)
        await update.message.reply_text("✅ Alertele au fost pornite.", reply_markup=MAIN_KEYBOARD)
        return

    if lowered == "stop alerts":
        config = load_config()
        config["alerts_enabled"] = False
        save_config(config)
        await update.message.reply_text("⏸️ Alertele au fost oprite.", reply_markup=MAIN_KEYBOARD)
        return

    if awaiting == "site":
        sites = [line.strip() for line in text.splitlines() if line.strip()]
        if not sites:
            await update.message.reply_text("Nu am primit niciun URL valid.")
            return
        config = load_config()
        config["sites"] = sites
        save_config(config)
        context.user_data["awaiting"] = None
        await update.message.reply_text("✅ Site-urile au fost salvate.", reply_markup=MAIN_KEYBOARD)
        return

    if awaiting == "keyword":
        config = load_config()
        config["keyword"] = text.lower()
        save_config(config)
        context.user_data["awaiting"] = None
        await update.message.reply_text("✅ Keyword-ul a fost salvat.", reply_markup=MAIN_KEYBOARD)
        return

    if awaiting == "price":
        parts = text.replace(",", " ").split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await update.message.reply_text("Format invalid. Folosește: MIN MAX (ex: 500 2500).")
            return

        min_price, max_price = int(parts[0]), int(parts[1])
        if min_price > max_price:
            await update.message.reply_text("MIN nu poate fi mai mare decât MAX.")
            return

        config = load_config()
        config["min"] = min_price
        config["max"] = max_price
        save_config(config)
        context.user_data["awaiting"] = None
        await update.message.reply_text("✅ Intervalul de preț a fost salvat.", reply_markup=MAIN_KEYBOARD)
        return

    await update.message.reply_text(
        "Comandă necunoscută. Folosește butoanele sau /start.",
        reply_markup=MAIN_KEYBOARD,
    )


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_and_input))

    logger.info("Botul pornește...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
