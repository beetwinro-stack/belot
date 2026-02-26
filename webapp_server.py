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
# Railway injects PORT dynamically — must use it, not a hardcoded port
PORT = int(os.environ.get("PORT", os.environ.get("WEBAPP_PORT", 8080)))


async def serve_app(request):
    """Serve the main HTML page."""
    html_path = WEBAPP_DIR / "webapp.html"
    if not html_path.exists():
        return web.Response(status=404, text="webapp.html not found")
    content = html_path.read_text(encoding="utf-8")
    return web.Response(content_type="text/html", text=content)


async def health(request):
    return web.Response(text="ok")


def make_game_state(game, player_id: int) -> dict:
    """
    Serialize game state for a specific player into the webapp state dict.
    """
    p = game.players
    n = game.player_names
    trump = game.trump_suit

    # Team names
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

    # Player names dict (str keys for JSON)
    player_names = {str(pid): n.get(pid, '?') for pid in p}

    # Current trick as list of [pid_str, rank, suit]
    trick = [
        [str(pid), card.rank.value, card.suit.value]
        for pid, card in game.current_trick
    ]

    # Player's hand as list of [rank, suit]
    hand = None
    valid_indices = None
    if player_id in game.hands:
        hand = [[c.rank.value, c.suit.value] for c in game.hands[player_id]]

    # Phase
    from game import GameState
    phase = game.state

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
    """Encode game state as base64 and append to webapp URL as hash."""
    state = make_game_state(game, player_id)
    encoded = base64.b64encode(json.dumps(state, ensure_ascii=False).encode()).decode()
    return f"{webapp_url.rstrip('/')}/#" + encoded


def _suit_name(suit) -> str:
    from cards import Suit
    names = {Suit.CLUBS: "Трефы", Suit.DIAMONDS: "Бубны",
             Suit.HEARTS: "Червы", Suit.SPADES: "Пики"}
    return names.get(suit, "")


async def start_server():
    """Start the aiohttp web server."""
    app = web.Application()
    app.router.add_get("/", serve_app)
    app.router.add_get("/app", serve_app)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"WebApp server started on port {PORT}")
    return runner
