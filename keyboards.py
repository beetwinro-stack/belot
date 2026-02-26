"""
Keyboard builders for Belot bot inline buttons.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from cards import Suit, Card
from game import BelotGame, GameState


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🃏 Создать игру", callback_data="create_game")],
        [InlineKeyboardButton("🔗 Войти в игру", callback_data="join_game_prompt")],
        [InlineKeyboardButton("📖 Правила", callback_data="show_rules")],
    ])


def suit_keyboard(prefix: str, exclude_suit: Suit = None):
    """Keyboard for choosing trump suit."""
    suits = [s for s in Suit if s != exclude_suit]
    buttons = [
        InlineKeyboardButton(s.value + " " + s.name.capitalize(), callback_data=f"{prefix}:{s.name}")
        for s in suits
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("⏭ Пас", callback_data=f"{prefix}:pass")])
    return InlineKeyboardMarkup(rows)


def bidding_keyboard_round1(proposed_suit: Suit):
    """Round 1: take proposed suit or pass."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ Взять {proposed_suit.value} {proposed_suit.name.capitalize()}",
            callback_data=f"bid_take:proposed"
        )],
        [InlineKeyboardButton("⏭ Пас", callback_data="bid_pass")],
    ])


def bidding_keyboard_round2(exclude_suit: Suit):
    """Round 2: choose any other suit or pass."""
    suits = [s for s in Suit if s != exclude_suit]
    buttons = [
        InlineKeyboardButton(
            f"{s.value} {s.name.capitalize()}",
            callback_data=f"bid_take:{s.name}"
        )
        for s in suits
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("⏭ Пас", callback_data="bid_pass")])
    return InlineKeyboardMarkup(rows)


def hand_keyboard(hand: list, valid_cards: list, game_id: str):
    """Show player's hand with valid cards highlighted."""
    buttons = []
    for i, card in enumerate(hand):
        is_valid = card in valid_cards
        label = card.emoji() if is_valid else f"🚫{card.emoji()}"
        cb = f"play:{game_id}:{i}" if is_valid else f"invalid_card:{i}"
        buttons.append(InlineKeyboardButton(label, callback_data=cb))
    
    # 2 cards per row
    rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
    return InlineKeyboardMarkup(rows)


def declarations_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 Показать комбинации", callback_data="show_declarations")],
    ])


def next_round_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Следующий раунд", callback_data="next_round")],
    ])


def format_hand(hand: list, valid_cards: list = None) -> str:
    """Format hand as text."""
    if valid_cards is None:
        return " ".join(c.emoji() for c in hand)
    parts = []
    for c in hand:
        if c in valid_cards:
            parts.append(f"**{c.emoji()}**")
        else:
            parts.append(f"~~{c.emoji()}~~")
    return " ".join(parts)


def format_trick(trick: list) -> str:
    """Format current trick."""
    return " | ".join(f"{name}: {card.emoji()}" for name, card in trick)


def format_scores(game: BelotGame) -> str:
    p = game.players
    names = game.player_names
    t0 = f"{names.get(p[0], '?')} & {names.get(p[2], '?')}" if len(p) > 2 else "Команда 1"
    t1 = f"{names.get(p[1], '?')} & {names.get(p[3], '?')}" if len(p) > 3 else "Команда 2"
    return (
        f"🏆 Счёт игры:\n"
        f"🔵 {t0}: **{game.scores[0]}**\n"
        f"🔴 {t1}: **{game.scores[1]}**"
    )
