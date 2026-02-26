"""
Keyboard builders for Belot bot inline buttons.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from cards import Suit, Card, Rank
from game import BelotGame, GameState


SUIT_NAMES_RU = {
    Suit.CLUBS: "Трефы",
    Suit.DIAMONDS: "Бубны",
    Suit.HEARTS: "Червы",
    Suit.SPADES: "Пики",
}


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 Создать игру", callback_data="create_game_prompt")],
        [InlineKeyboardButton("🔗 Войти в игру", callback_data="join_game_prompt")],
        [InlineKeyboardButton("📖 Правила", callback_data="show_rules")],
    ])


def mode_select_keyboard():
    """Choose 3 or 4 player mode."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤👤👤  На 3 игрока", callback_data="create_game:3")],
        [InlineKeyboardButton("👤👤👤👤  На 4 игрока", callback_data="create_game:4")],
    ])


def bidding_keyboard_round1(proposed_suit: Suit):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ Взять {proposed_suit.value} {SUIT_NAMES_RU[proposed_suit]}",
            callback_data="bid_take:proposed"
        )],
        [InlineKeyboardButton("⏭ Пас", callback_data="bid_pass")],
    ])


def bidding_keyboard_round2(exclude_suit: Suit):
    suits = [s for s in Suit if s != exclude_suit]
    buttons = [
        InlineKeyboardButton(f"{s.value} {SUIT_NAMES_RU[s]}", callback_data=f"bid_take:{s.name}")
        for s in suits
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("⏭ Пас", callback_data="bid_pass")])
    return InlineKeyboardMarkup(rows)


def hand_keyboard(hand: list, valid_cards: list, game_id: str):
    buttons = []
    for i, card in enumerate(hand):
        is_valid = card in valid_cards
        label = card.emoji() if is_valid else f"·{card.emoji()}·"
        cb = f"play:{game_id}:{i}" if is_valid else f"invalid_card:{i}"
        buttons.append(InlineKeyboardButton(label, callback_data=cb))
    rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
    return InlineKeyboardMarkup(rows)


def discard_keyboard(hand: list, selected: list, game_id: str):
    """Keyboard for taker to select 2 cards to discard (3-player mode)."""
    buttons = []
    for i, card in enumerate(hand):
        is_selected = i in selected
        label = f"☑️{card.emoji()}" if is_selected else card.emoji()
        buttons.append(InlineKeyboardButton(label, callback_data=f"discard_toggle:{game_id}:{i}"))
    rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
    if len(selected) == 2:
        rows.append([InlineKeyboardButton("🗑 Сбросить выбранные (2)", callback_data=f"discard_confirm:{game_id}")])
    else:
        rows.append([InlineKeyboardButton(f"Выберите ещё {2 - len(selected)} карту...", callback_data="noop")])
    return InlineKeyboardMarkup(rows)


def next_round_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Следующий раунд", callback_data="next_round")],
    ])


def score_bar(score: int, target: int = 151) -> str:
    filled = min(10, round(score / target * 10))
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {score}/{target}"


def format_scores_full(game: BelotGame) -> str:
    p = game.players
    names = game.player_names
    s0 = game.scores[0]
    s1 = game.scores[1]

    if game.max_players == 4:
        if len(p) < 4:
            return ""
        t0 = f"{names.get(p[0], '?')} & {names.get(p[2], '?')}"
        t1 = f"{names.get(p[1], '?')} & {names.get(p[3], '?')}"
    else:
        if game.taker_idx is not None:
            taker_id = p[game.taker_idx]
            others = [pid for pid in p if pid != taker_id]
            t0 = f"🗡 {names.get(taker_id, '?')} (один)"
            t1 = " & ".join(names.get(pid, '?') for pid in others)
        else:
            t0 = names.get(p[0], '?') if p else "?"
            t1 = " & ".join(names.get(pid, '?') for pid in p[1:]) if len(p) > 1 else "?"

    return (
        f"🔵 {t0}\n"
        f"   {score_bar(s0)}\n"
        f"🔴 {t1}\n"
        f"   {score_bar(s1)}"
    )


def format_scores(game: BelotGame) -> str:
    return format_scores_full(game)


def format_hand_grouped(hand: list, valid_cards: list = None, trump_suit=None) -> str:
    by_suit = {}
    for card in hand:
        by_suit.setdefault(card.suit, []).append(card)
    suit_order = [s for s in Suit if s != trump_suit] + ([trump_suit] if trump_suit else [])
    lines = []
    for suit in suit_order:
        cards = by_suit.get(suit, [])
        if not cards:
            continue
        prefix = f"★{suit.value}" if suit == trump_suit else suit.value
        card_strs = []
        for c in cards:
            emoji = c.emoji()
            if valid_cards is not None and c not in valid_cards:
                emoji = f"~{c.rank.value}~"
            card_strs.append(emoji)
        lines.append(f"{prefix} {' '.join(card_strs)}")
    return "\n".join(lines)


def format_trick_table(trick: list, player_names: dict) -> str:
    if not trick:
        return ""
    return "\n".join(f"  {card.emoji()}  {player_names.get(pid, '?')}" for pid, card in trick)
