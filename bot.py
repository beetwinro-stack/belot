"""
Belot Telegram Bot - Moldova rules (belot.md)
4 players, 2 teams, 32 cards
"""
import logging
import os
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler
)
from game_manager import GameManager
from handlers import (
    start_handler, create_game_handler, join_game_handler,
    callback_handler, help_handler
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global game manager
game_manager = GameManager()


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    app = Application.builder().token(token).build()

    # Pass game_manager to handlers via bot_data
    app.bot_data["game_manager"] = game_manager

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("newgame", create_game_handler))
    app.add_handler(CommandHandler("join", join_game_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Belot bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
