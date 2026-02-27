"""
Belot Telegram Bot - Moldova rules
4 players or 3 players, 2 teams, 32 cards
"""
import logging
import os
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
from game_manager import GameManager
from handlers import (
    start_handler, create_game_handler, join_game_handler,
    callback_handler, help_handler, webapp_data_handler
)
from webapp_server import start_server

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

game_manager = GameManager()


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable not set!")

    webapp_url = os.environ.get("WEBAPP_URL", "")
    if not webapp_url:
        logger.warning("WEBAPP_URL not set! Mini App buttons will not work.")

    app = Application.builder().token(token).build()

    app.bot_data["game_manager"] = game_manager
    app.bot_data["webapp_url"] = webapp_url

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("newgame", create_game_handler))
    app.add_handler(CommandHandler("join", join_game_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_data_handler))

    async def post_init(application):
        # Pass game_manager so the web server can serve the lobby API
        runner = await start_server(game_manager=game_manager)
        application.bot_data["webapp_runner"] = runner
        port = os.environ.get('PORT', os.environ.get('WEBAPP_PORT', 8080))
        logger.info(f"WebApp serving at port {port}")

        # Set Menu Button so players can open lobby from bottom menu in Telegram
        if webapp_url:
            try:
                from telegram import MenuButtonWebApp, WebAppInfo
                await application.bot.set_chat_menu_button(
                    menu_button=MenuButtonWebApp(
                        text="🎮 Лобби",
                        web_app=WebAppInfo(url=webapp_url)
                    )
                )
                logger.info("Menu button set to webapp lobby")
            except Exception as e:
                logger.warning(f"Could not set menu button: {e}")

    app.post_init = post_init

    logger.info("Belot bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
