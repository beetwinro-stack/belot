"""
Simple async web server to serve the Telegram Mini App.
Runs alongside the bot in the same process.
"""
import asyncio
import base64
import json
import os
import logging
from pathlib import Path
from aiohttp import web

logger = logging.getLogger(__name__)

WEBAPP_DIR = Path(__file__).parent
PORT = int(os.environ.get("PORT", os.environ.get("WEBAPP_PORT", 8080)))

# Reference to game_manager — injected from bot.py after startup
_game_manager = None
_bot_notify_callback = None  # async fn(game) called when game starts via webapp


def set_game_manager(gm):
    global _game_manager
    _game_manager = gm


def set_bot_notify_callback(fn):
    global _bot_notify_callback
    _bot_notify_callback = fn


async def serve_app(request):
    html_path = WEBAPP_DIR / "webapp.html"
    if not html_path.exists():
        return web.Response(status=404, text="webapp.html not found")
    content = html_path.read_text(encoding="utf-8")
    return web.Response(content_type="text/html", text=content)


async def health(request):
    return web.Response(text="ok")


async def api_lobby(request):
    """Return list of open (waiting) games as JSON."""
    if not _game_manager:
        return web.json_response({"games": []})

    from game import GameState
    games = []
    for game_id, game in _game_manager.games.items():
        if game.state == GameState.WAITING:
            games.append({
                "game_id": game_id,
                "players": list(game.player_names.values()),
                "slots_taken": len(game.players),
                "slots_total": game.max_players,
                "mode": f"{game.max_players} игрока",
            })

    return web.json_response({"games": games}, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache",
    })


async def api_join_lobby(request):
    """
    Called from webapp when player taps Join on a lobby table.
    Expects JSON: { "game_id": "XXXX", "player_id": 12345, "player_name": "Иван" }
    """
    if not _game_manager:
        return web.json_response({"ok": False, "error": "Server not ready"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    game_id = body.get("game_id", "").strip().upper()
    player_id = body.get("player_id")
    player_name = body.get("player_name", "Игрок")

    if not game_id or not player_id:
        return web.json_response({"ok": False, "error": "Missing game_id or player_id"}, status=400)

    from game import GameState

    # Check if already in THIS game (rejoin case)
    existing = _game_manager.get_game_by_player(int(player_id))
    if existing and existing.game_id == game_id:
        state = make_game_state(existing, int(player_id))
        return web.json_response({"ok": True, "game_id": game_id, "state": state,
                                  "rejoined": True}, headers={"Access-Control-Allow-Origin": "*"})

    game, error = _game_manager.join_game(game_id, int(player_id), player_name)
    if error:
        return web.json_response({"ok": False, "error": error})

    state = make_game_state(game, int(player_id))

    # If game just started — trigger bot notification for all OTHER players
    if game.state != GameState.WAITING and _bot_notify_callback:
        import asyncio
        asyncio.create_task(_bot_notify_callback(game))

    return web.json_response({"ok": True, "game_id": game_id, "state": state}, headers={
        "Access-Control-Allow-Origin": "*",
    })


async def api_action(request):
    """
    Handle a game action from the webapp.
    POST /api/action
    Body: { "player_id": 12345, "action": "play", "data": "3" }
    """
    if not _game_manager:
        return web.json_response({"ok": False, "error": "Server not ready"})
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    player_id = body.get("player_id")
    action = body.get("action")
    data = body.get("data")

    if not player_id or not action:
        return web.json_response({"ok": False, "error": "Missing player_id or action"}, status=400)

    player_id = int(player_id)
    game = _game_manager.get_game_by_player(player_id)
    if not game:
        return web.json_response({"ok": False, "error": "Не в игре"})

    from game import GameState
    from cards import Suit as SuitEnum

    result_msg = None
    error = None

    try:
        if action == "bid_pass":
            res = game.bid_pass(player_id)
            if not res["ok"]:
                error = res["error"]
            else:
                result_msg = "Пас"
                if res.get("redeal"):
                    game.start_round()
                    if _bot_notify_callback:
                        import asyncio
                        asyncio.create_task(_bot_notify_callback(game))

        elif action == "bid_take":
            suit = None
            if data and data != "proposed":
                suit = next((s for s in SuitEnum if s.value == data), None)
            res = game.bid_take(player_id, suit)
            if not res["ok"]:
                error = res["error"]
            else:
                trump = game.trump_suit
                result_msg = f"Козырь: {trump.value}"
                if _bot_notify_callback:
                    import asyncio
                    asyncio.create_task(_bot_notify_callback(game))

        elif action == "discard":
            indices = [int(x) for x in str(data).split(",") if x.strip().isdigit()]
            res = game.discard_cards(player_id, indices)
            if not res["ok"]:
                error = res["error"]
            else:
                result_msg = "Карты сброшены"

        elif action == "declare":
            res = game.submit_declarations(player_id)
            if not res["ok"]:
                error = res["error"]
            else:
                result_msg = "Комбинации заявлены"
                if res.get("all_done") and _bot_notify_callback:
                    import asyncio
                    asyncio.create_task(_bot_notify_callback(game))

        elif action == "play":
            card_idx = int(data)
            hand = game.hands.get(player_id, [])
            if card_idx >= len(hand):
                error = "Неверный индекс карты"
            else:
                card = hand[card_idx]
                res = game.play_card(player_id, card)
                if not res["ok"]:
                    error = res["error"]
                else:
                    result_msg = f"Сыграно: {card.emoji()}"
                    # Notify via bot for trick/round results
                    if _bot_notify_callback and (res.get("trick_done") or res.get("round_done")):
                        import asyncio
                        asyncio.create_task(_bot_notify_callback(game, res))
        else:
            error = f"Unknown action: {action}"

    except Exception as e:
        import traceback
        traceback.print_exc()
        error = str(e)

    if error:
        return web.json_response({"ok": False, "error": error},
                                 headers={"Access-Control-Allow-Origin": "*"})

    # Return updated game state
    state = make_game_state(game, player_id)
    return web.json_response({"ok": True, "message": result_msg, "state": state},
                             headers={"Access-Control-Allow-Origin": "*"})


async def api_game_state(request):
    """
    Poll current game state for a player.
    GET /api/game_state?player_id=12345
    Used by waiting room to detect when game starts.
    """
    if not _game_manager:
        return web.json_response({"ok": False, "error": "Server not ready"})

    player_id = request.rel_url.query.get("player_id")
    if not player_id:
        return web.json_response({"ok": False, "error": "Missing player_id"})

    game = _game_manager.get_game_by_player(int(player_id))
    if not game:
        return web.json_response({"ok": False, "error": "Not in a game"})

    state = make_game_state(game, int(player_id))
    return web.json_response({"ok": True, "state": state}, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache",
    })


async def api_create_game(request):
    """
    Create a new game from the webapp.
    Expects JSON: { "player_id": 12345, "player_name": "Иван", "max_players": 4 }
    """
    if not _game_manager:
        return web.json_response({"ok": False, "error": "Server not ready"}, status=503)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    player_id = body.get("player_id")
    player_name = body.get("player_name", "Игрок")
    max_players = int(body.get("max_players", 4))

    if not player_id:
        return web.json_response({"ok": False, "error": "Missing player_id"}, status=400)

    from game import GameState

    # If already in any game — handle gracefully
    existing = _game_manager.get_game_by_player(int(player_id))
    if existing:
        if existing.state == GameState.WAITING:
            # Leave the waiting game silently, then create new
            _game_manager.leave_game(int(player_id))
        else:
            # Already in active game — return its current state instead of error
            state = make_game_state(existing, int(player_id))
            return web.json_response({"ok": True, "game_id": existing.game_id, "state": state,
                                      "rejoined": True}, headers={"Access-Control-Allow-Origin": "*"})

    game = _game_manager.create_game(int(player_id), player_name, max_players=max_players)
    state = make_game_state(game, int(player_id))
    return web.json_response({"ok": True, "game_id": game.game_id, "state": state}, headers={
        "Access-Control-Allow-Origin": "*",
    })


async def api_leave_lobby(request):
    """
    Called from webapp when player taps Leave/Close on their table.
    Expects JSON: { "player_id": 12345 }
    """
    if not _game_manager:
        return web.json_response({"ok": False, "error": "Server not ready"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    player_id = body.get("player_id")
    if not player_id:
        return web.json_response({"ok": False, "error": "Missing player_id"}, status=400)

    result = _game_manager.leave_game(int(player_id))
    return web.json_response(result, headers={"Access-Control-Allow-Origin": "*"})


def make_game_state(game, player_id) -> dict:
    player_id = int(player_id)  # ensure int — JSON may send string
    p = game.players
    n = game.player_names
    trump = game.trump_suit

    if game.max_players == 4:
        t0 = f"{n.get(p[0], '?')} & {n.get(p[2], '?')}" if len(p) > 2 else "Команда 1"
        t1 = f"{n.get(p[1], '?')} & {n.get(p[3], '?')}" if len(p) > 3 else "Команда 2"
    else:
        if game.taker_idx is not None:
            tid = p[game.taker_idx]
            others = [pid for pid in p if pid != tid]
            t0 = f"🗡 {n.get(tid, '?')} (один)"
            t1 = " & ".join(n.get(pid, '?') for pid in others)
        else:
            t0 = n.get(p[0], '?') if p else '?'
            t1 = " & ".join(n.get(pid, '?') for pid in p[1:]) if len(p) > 1 else '?'

    player_names = {str(pid): n.get(pid, '?') for pid in p}
    trick = [
        [str(pid), card.rank.value, card.suit.value]
        for pid, card in game.current_trick
    ]
    hand = None
    valid_indices = None
    if player_id in game.hands:
        hand = [[c.rank.value, c.suit.value] for c in game.hands[player_id]]

    from game import GameState
    phase = game.state

    if phase == GameState.WAITING:
        return {
            "phase": "lobby_waiting",
            "my_id": str(player_id),
            "game_id": game.game_id,
            "is_creator": (getattr(game, "creator_id", None) == player_id),
            "players": list(n.values()),
            "slots_taken": len(p),
            "slots_total": game.max_players,
            "team0_name": t0,
            "team1_name": t1,
            "player_names": player_names,
            "scores": game.scores[:],
            "tricks": game.tricks_won[:],
        }

    if phase == GameState.BIDDING:
        is_my_turn = (p[game.current_bidder_idx] == player_id)
        waiting_for = n.get(p[game.current_bidder_idx], '?') if not is_my_turn else None
        proposed = game.proposed_card
        state_phase = 'bid1' if game.bidding_round == 1 else 'bid2'
        return {
            "phase": state_phase,
            "my_id": str(player_id),
            "round": game.round_num,
            "trump": proposed.suit.value if proposed else '?',
            "trump_name": _suit_name(proposed.suit) if proposed else '',
            "proposed_suit": proposed.suit.value if proposed else None,
            "scores": game.scores[:],
            "tricks": game.tricks_won[:],
            "team0_name": t0,
            "team1_name": t1,
            "player_names": player_names,
            "trick": trick,
            "hand": hand,
            "is_my_turn": is_my_turn,
            "waiting_for": waiting_for,
        }

    if phase == GameState.DISCARDING:
        taker_id = p[game.taker_idx]
        is_my_turn = (player_id == taker_id)
        return {
            "phase": "discard" if is_my_turn else "waiting_discard",
            "my_id": str(player_id),
            "round": game.round_num,
            "trump": trump.value if trump else '?',
            "trump_name": _suit_name(trump) if trump else '',
            "scores": game.scores[:],
            "tricks": game.tricks_won[:],
            "team0_name": t0,
            "team1_name": t1,
            "player_names": player_names,
            "trick": trick,
            "hand": hand,
            "is_my_turn": is_my_turn,
            "waiting_for": n.get(taker_id, '?') if not is_my_turn else None,
            "message": "Выберите 2 карты для сброса" if is_my_turn else f"Ждём пока {n.get(taker_id, '?')} сбрасывает карты",
        }

    if phase == GameState.DECLARATIONS:
        from declarations import get_all_declarations, check_belot
        decls = get_all_declarations(game.hands.get(player_id, []), trump) if player_id in game.hands else []
        belot = check_belot(game.hands.get(player_id, []), trump) if player_id in game.hands else False
        decl_names = [d['name'] for d in decls]
        if belot:
            decl_names.append("💍 Белот К+Д козырной = 20")
        already_done = player_id in game.declarations_done
        return {
            "phase": "declare",
            "my_id": str(player_id),
            "round": game.round_num,
            "trump": trump.value if trump else '?',
            "trump_name": _suit_name(trump) if trump else '',
            "scores": game.scores[:],
            "tricks": game.tricks_won[:],
            "team0_name": t0,
            "team1_name": t1,
            "player_names": player_names,
            "trick": trick,
            "hand": hand,
            "declarations": decl_names,
            "already_declared": already_done,
            "is_my_turn": not already_done,
            "waiting_for": None,
        }

    if phase == GameState.PLAYING:
        is_my_turn = (p[game.current_player_idx] == player_id)
        if is_my_turn and player_id in game.hands:
            valid = game.get_valid_cards(player_id)
            hand_list = game.hands[player_id]
            valid_indices = [hand_list.index(c) for c in valid if c in hand_list]
        waiting_for = n.get(p[game.current_player_idx], '?') if not is_my_turn else None
        return {
            "phase": "play",
            "my_id": str(player_id),
            "round": game.round_num,
            "trump": trump.value if trump else '?',
            "trump_name": _suit_name(trump) if trump else '',
            "scores": game.scores[:],
            "tricks": game.tricks_won[:],
            "team0_name": t0,
            "team1_name": t1,
            "player_names": player_names,
            "trick": trick,
            "hand": hand,
            "valid_indices": valid_indices,
            "is_my_turn": is_my_turn,
            "waiting_for": waiting_for,
        }

    return {
        "phase": "waiting",
        "my_id": str(player_id),
        "message": "Ожидаем...",
        "scores": game.scores[:],
        "team0_name": t0,
        "team1_name": t1,
        "player_names": player_names,
    }


def state_to_url(webapp_url: str, game, player_id: int) -> str:
    state = make_game_state(game, player_id)
    encoded = base64.b64encode(json.dumps(state, ensure_ascii=False).encode()).decode()
    return f"{webapp_url.rstrip('/')}/#" + encoded


def _suit_name(suit) -> str:
    from cards import Suit
    names = {Suit.CLUBS: "Трефы", Suit.DIAMONDS: "Бубны",
             Suit.HEARTS: "Червы", Suit.SPADES: "Пики"}
    return names.get(suit, "")


async def start_server(game_manager=None):
    """Start the aiohttp web server."""
    if game_manager:
        set_game_manager(game_manager)

    app = web.Application()
    app.router.add_get("/", serve_app)
    app.router.add_get("/app", serve_app)
    app.router.add_get("/health", health)
    app.router.add_get("/api/lobby", api_lobby)
    app.router.add_post("/api/join_lobby", api_join_lobby)
    app.router.add_post("/api/create_game", api_create_game)
    app.router.add_get("/api/game_state", api_game_state)
    app.router.add_post("/api/action", api_action)
    app.router.add_post("/api/leave_lobby", api_leave_lobby)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"WebApp server started on port {PORT}")
    return runner
