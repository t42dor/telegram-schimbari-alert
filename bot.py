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

from playwright.async_api import async_playwright

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


def load_seen():
    if not SEEN_FILE.exists():
        return []
    try:
        with SEEN_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_seen(seen):
    with SEEN_FILE.open("w", encoding="utf-8") as f:
        json.dump(seen, f)


def parse_price(text: str):
    digits = "".join(c for c in text if c.isdigit())
    return int(digits) if digits else None


# ================= SCRAPER JOB ================= #

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    configs = load_all_configs()
    if not configs:
        return

    seen = load_seen()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for chat_id, user_config in configs.items():
            if not user_config.get("alerts_enabled", True):
                continue

            sites = user_config.get("sites", [])
            keyword = user_config.get("keyword", "").lower()
            min_price = int(user_config.get("min", 0))
            max_price = int(user_config.get("max", 999_999_999))

            for site in sites[:5]:
                try:
                    page = await browser.new_page()
                    await page.goto(site, timeout=60000)
                    await page.wait_for_timeout(5000)

                    ads = await page.query_selector_all("a")

                    for ad in ads:
                        title = (await ad.inner_text() or "").strip().lower()
                        link = await ad.get_attribute("href")

                        if not link or "http" not in link:
                            continue

                        if keyword and keyword not in title:
                            continue

                        parent_text = await ad.evaluate(
                            "el => el.parentElement ? el.parentElement.innerText : ''"
                        )

                        price = parse_price(parent_text)

                        if (
                            price is not None
                            and min_price <= price <= max_price
                            and link not in seen
                        ):
                            message = (
                                f"OFERTĂ NOUĂ\n\n"
                                f"{title}\n"
                                f"Preț: {price}\n\n"
                                f"{link}"
                            )

                            await context.bot.send_message(
                                chat_id=int(chat_id),
                                text=message,
                            )

                            seen.append(link)

                    await page.close()

                except Exception as e:
                    logger.error(f"Eroare la site {site}: {e}")
                    continue

        await browser.close()

    save_seen(seen)


# ================= HANDLERS ================= #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    get_user_config(chat_id)

    await update.message.reply_text(
        "Salut! Configurează din butoanele de mai jos.",
        reply_markup=MAIN_KEYBOARD,
    )

    await update.message.reply_text(
        "Ai și buton de resetare rapidă:",
        reply_markup=RESET_INLINE_KEYBOARD,
    )


async def show_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    config = get_user_config(chat_id)
    await update.message.reply_text(str(config))


async def reset_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    update_user_config(chat_id, DEFAULT_CONFIG.copy())
    await update.message.reply_text("Setările au fost resetate.")


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    config = get_user_config(chat_id)

    text = update.message.text.strip().lower()

    if text == "set site":
        await update.message.reply_text("Trimite URL-ul.")
        context.user_data["awaiting"] = "site"
        return

    if context.user_data.get("awaiting") == "site":
        config["sites"].append(update.message.text.strip())
        update_user_config(chat_id, config)
        context.user_data["awaiting"] = None
        await update.message.reply_text("Site adăugat.")
        return


# ================= MAIN ================= #

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Lipsește TELEGRAM_TOKEN")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input))

    job_queue = app.job_queue
    job_queue.run_repeating(scheduled_check, interval=60, first=10)

    logger.info("=== BOT CU PLAYWRIGHT MULTI-USER PORNIT ===")
    app.run_polling()


if __name__ == "__main__":
    main()
