"""
Standalone test server for webapp UI.
Run: python test_server.py
Then open: http://localhost:8080
No Telegram token needed — fake player IDs are used.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from aiohttp import web
from game_manager import GameManager
from webapp_server import (
    serve_app, health, api_lobby, api_join_lobby,
    api_leave_lobby, api_create_game, set_game_manager
)

game_manager = GameManager()
set_game_manager(game_manager)

# Pre-populate with some test games so the lobby isn't empty
def seed_test_games():
    g1 = game_manager.create_game(1001, "Иван", max_players=4)
    game_manager.join_game(g1.game_id, 1002, "Мария")

    g2 = game_manager.create_game(2001, "Пётр", max_players=3)

    g3 = game_manager.create_game(3001, "Анна", max_players=4)
    game_manager.join_game(g3.game_id, 3002, "Дима")
    game_manager.join_game(g3.game_id, 3003, "Оля")

    print(f"  Seeded 3 test games: {g1.game_id}, {g2.game_id}, {g3.game_id}")


async def main():
    seed_test_games()

    app = web.Application()
    app.router.add_get("/", serve_app)
    app.router.add_get("/app", serve_app)
    app.router.add_get("/health", health)
    app.router.add_get("/api/lobby", api_lobby)
    app.router.add_post("/api/join_lobby", api_join_lobby)
    app.router.add_post("/api/leave_lobby", api_leave_lobby)
    app.router.add_post("/api/create_game", api_create_game)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    print("\n" + "="*50)
    print("  🃏 Белот — тестовый сервер запущен!")
    print("  Открой в браузере: http://localhost:8080")
    print("="*50)
    print("\n  Тестовые команды:")
    print("  GET  /api/lobby          — список столов")
    print("  POST /api/create_game    — создать стол")
    print("  POST /api/join_lobby     — войти в стол")
    print("  POST /api/leave_lobby    — выйти из стола")
    print("\n  Ctrl+C для остановки\n")

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
