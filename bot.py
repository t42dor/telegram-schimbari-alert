import logging
import re
import os
import sqlite3
import requests
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Database cleanup function
def clean_database():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    # Implement cleanup queries here
    cursor.execute("DELETE FROM your_table WHERE some_column < DATE('now', '-30 days')") # Example query
    conn.commit()
    conn.close()
    logger.info('Database cleaned up.')

# URL validation function
def is_valid_url(url):
    regex = r'^(http|https)://[^\s/$.?#].[^\s]*$'
    return re.match(regex, url) is not None

# Start command handler
def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Hello! This is your Telegram bot.')
    logger.info('Start command issued by user: %s', update.message.from_user.username)

# Function to handle the URL checking
def check_url(update: Update, context: CallbackContext) -> None:
    url = context.args[0] if context.args else None
    if url and is_valid_url(url):
        update.message.reply_text(f'URL is valid: {url}')
        logger.info('Valid URL provided: %s', url)
    else:
        update.message.reply_text('Invalid URL or no URL provided.')
        logger.error('Invalid URL attempt by %s: %s', update.message.from_user.username, url)

# Main function to start the bot
def main() -> None:
    # Cleanup the database on startup
    clean_database()
    # Create Updater and pass it your bot's token
    updater = Updater(os.getenv('TELEGRAM_TOKEN'))
    dispatcher = updater.dispatcher

    # Register command handlers
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('checkurl', check_url))

    # Start the Bot
    updater.start_polling()
    logging.info('Bot started successfully.')
    updater.idle()

if __name__ == '__main__':
    main()
