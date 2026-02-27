"""
Telegram handlers for Belot bot.
Uses Telegram Mini App (WebApp) for card display.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
import json
import logging

from game import GameState
from cards import Suit, Rank
from keyboards import (
    main_menu_keyboard, mode_select_keyboard,
    bidding_keyboard_round1, bidding_keyboard_round2,
    next_round_keyboard, SUIT_NAMES_RU
)
from webapp_server import state_to_url, make_game_state

logger = logging.getLogger(__name__)
DIV = "─" * 24

# discard selection per user
_discard_selection = {}


def get_gm(context):
    return context.bot_data["game_manager"]


def get_webapp_url(context) -> str:
    return context.bot_data.get("webapp_url", "")


def player_name(update: Update) -> str:
    u = update.effective_user
    return u.full_name or u.username or f"Player{u.id}"


def webapp_button(label: str, url: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, web_app=WebAppInfo(url=url))
    ]])


def team_result_lines(game):
    p = game.players
    n = game.player_names
    if game.max_players == 4:
        t0 = f"{n.get(p[0],'?')} & {n.get(p[2],'?')}"
        t1 = f"{n.get(p[1],'?')} & {n.get(p[3],'?')}"
    else:
        taker_id = p[game.taker_idx] if game.taker_idx is not None else p[0]
        others = [pid for pid in p if pid != taker_id]
        t0 = f"🗡 {n.get(taker_id,'?')} (один)"
        t1 = " & ".join(n.get(pid,'?') for pid in others)
    return t0, t1


def score_bar(score, target=151):
    filled = min(10, round(score / target * 10))
    return "█" * filled + "░" * (10 - filled) + f" {score}/{target}"


# ─── /start ────────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args and args[0].startswith("join_"):
        await _do_join(update, context, args[0][5:])
        return

    webapp_url = get_webapp_url(context)
    if webapp_url:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Открыть лобби", web_app=WebAppInfo(url=webapp_url))],
            [InlineKeyboardButton("🃏 Создать игру", callback_data="create_game_prompt")],
            [InlineKeyboardButton("🔗 Войти по коду", callback_data="join_game_prompt")],
            [InlineKeyboardButton("📖 Правила", callback_data="show_rules")],
        ])
    else:
        kb = main_menu_keyboard()

    await update.message.reply_text(
        "🃏 *Белот — Молдавские правила*\n\n"
        "Карточная игра для 3 или 4 игроков.\n"
        "Первый до 151 очка — победитель!\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )


# ─── /help ─────────────────────────────────────────────────────────────────
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📖 *Правила Белота*\n{DIV}\n"
        f"*4 игрока:* 2 команды (1+3 vs 2+4)\n"
        f"*3 игрока:* берущий козырь — один против двух\n\n"
        f"★В = 20 · ★9 = 14 · Т = 11 · 10 = 10 · К = 4 · Д = 3\n\n"
        f"*Комбинации:* Терц=20 · 50 · 100 · Каре=100-200\n"
        f"Белот К+Д козырной = 20\n\n"
        f"8888 — аннулирует комбинации · 7777 — аннулирует раунд\n"
        f"Все взятки = +90 · Последняя = +10\n\n"
        f"🏆 Игра до *151 очка*",
        parse_mode=ParseMode.MARKDOWN
    )


# ─── /newgame ──────────────────────────────────────────────────────────────
async def create_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🃏 *Создать игру*\n\nВыберите количество игроков:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=mode_select_keyboard()
    )


# ─── /join ─────────────────────────────────────────────────────────────────
async def join_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите код: `/join XXXXXXXX`", parse_mode=ParseMode.MARKDOWN)
        return
    await _do_join(update, context, context.args[0].upper())


async def _do_join(update: Update, context: ContextTypes.DEFAULT_TYPE, game_id: str):
    gm = get_gm(context)
    pid = update.effective_user.id
    name = player_name(update)

    game, error = gm.join_game(game_id, pid, name)
    if error:
        await update.message.reply_text(f"❌ {error}")
        return

    max_p = game.max_players
    icons = ["🔵", "🔴", "🔵", "🔴"]
    lines = [f"{icons[i%4]} {game.player_names[p]}" for i, p in enumerate(game.players)]
    lines += ["⬜️ ожидаем..."] * (max_p - len(game.players))
    players_text = "\n".join(lines)

    if game.is_full():
        await update.message.reply_text(
            f"✅ {name} вошёл!\n{DIV}\n{players_text}\n\n🚀 Все {max_p} — начинаем!"
        )
        try:
            await _notify_bidding_start(context, game)
        except Exception as e:
            logger.error(f"_notify_bidding_start error: {e}", exc_info=True)
            for p in game.players:
                try:
                    await context.bot.send_message(chat_id=p, text=f"❌ Ошибка запуска: {e}")
                except Exception:
                    pass
    else:
        count = len(game.players)
        await update.message.reply_text(
            f"✅ Вы вошли в `{game_id}`!\n{DIV}\n{players_text}\n\n⏳ Ждём ещё {max_p - count}...",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_waiting_room_keyboard(game, pid)
        )
        for existing_pid in game.players:
            if existing_pid != pid:
                try:
                    await context.bot.send_message(
                        chat_id=existing_pid,
                        text=f"👋 {name} присоединился!\n{players_text}\n⏳ Ждём ещё {max_p - count}...",
                        reply_markup=_waiting_room_keyboard(game, existing_pid)
                    )
                except Exception:
                    pass


# ─── Bidding start ──────────────────────────────────────────────────────────
async def _notify_bidding_start(context, game):
    webapp_url = get_webapp_url(context)
    proposed = game.proposed_card
    trump = game.trump_suit
    taker_name = game.player_names.get(game.players[game.taker_idx], '?') if game.taker_idx is not None else '?'

    for pid in game.players:
        url = state_to_url(webapp_url, game, pid)
        if game.auto_trump:
            text = (
                f"🃏 *Раунд {game.round_num}*\n"
                f"⚡ Перевёрнут Валет — {taker_name} берёт автоматически!\n"
                f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}"
            )
        else:
            text = (
                f"🃏 *Раунд {game.round_num}*\n"
                f"Предложенный козырь: {proposed.emoji()}\n"
                f"{'Ваш ход в торгах!' if game.players[game.current_bidder_idx] == pid else 'Ждём торгов...'}"
            )
        try:
            await context.bot.send_message(
                chat_id=pid, text=text, parse_mode=ParseMode.MARKDOWN,
                reply_markup=webapp_button("🃏 Открыть игру", url)
            )
        except Exception as e:
            logger.error(f"send to {pid}: {e}")

    if game.auto_trump:
        if game.max_players == 3:
            await _ask_discard(context, game)
        else:
            await _start_declarations(context, game)
    else:
        await _ask_bid(context, game)


async def _ask_bid(context, game):
    webapp_url = get_webapp_url(context)
    bidder_id = game.players[game.current_bidder_idx]
    proposed = game.proposed_card

    # Send bidding UI to bidder via webapp
    url = state_to_url(webapp_url, game, bidder_id)
    if game.bidding_round == 1:
        text = f"🎴 *Торги — Круг 1*\nПредложен: {proposed.emoji()} {SUIT_NAMES_RU[proposed.suit]}\nВзять или пас?"
        kb = bidding_keyboard_round1(proposed.suit)
    else:
        text = f"🎴 *Торги — Круг 2*\nВыберите масть (кроме {proposed.suit.value}) или пас:"
        kb = bidding_keyboard_round2(proposed.suit)

    # Add webapp button to bidding keyboard
    kb_rows = kb.inline_keyboard + [[InlineKeyboardButton("🃏 Посмотреть карты", web_app=WebAppInfo(url=url))]]
    kb = InlineKeyboardMarkup(kb_rows)

    await context.bot.send_message(
        chat_id=bidder_id, text=text,
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb
    )
    for pid in game.players:
        if pid != bidder_id:
            url2 = state_to_url(webapp_url, game, pid)
            await context.bot.send_message(
                chat_id=pid,
                text=f"⏳ Торгует {game.player_names[bidder_id]}...",
                reply_markup=webapp_button("🃏 Посмотреть карты", url2)
            )


async def _ask_discard(context, game):
    webapp_url = get_webapp_url(context)
    taker_id = game.players[game.taker_idx]
    url = state_to_url(webapp_url, game, taker_id)

    await context.bot.send_message(
        chat_id=taker_id,
        text=(
            f"🗑 *Сброс карт*\n"
            f"У вас {len(game.hands[taker_id])} карт.\n"
            f"Выберите 2 карты для сброса в мини-приложении:"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=webapp_button("🗑 Выбрать карты для сброса", url)
    )
    for pid in game.players:
        if pid != taker_id:
            url2 = state_to_url(webapp_url, game, pid)
            await context.bot.send_message(
                chat_id=pid,
                text=f"⏳ {game.player_names[taker_id]} сбрасывает карты...",
                reply_markup=webapp_button("🃏 Посмотреть карты", url2)
            )


async def _start_declarations(context, game):
    webapp_url = get_webapp_url(context)
    trump = game.trump_suit

    for pid in game.players:
        from declarations import get_all_declarations, check_belot
        decls = get_all_declarations(game.hands.get(pid, []), trump)
        belot = check_belot(game.hands.get(pid, []), trump)

        decl_text = ""
        if decls:
            decl_text = "\n" + "\n".join(f"  📌 {d['name']}" for d in decls)
        if belot:
            decl_text += "\n  💍 Белот К+Д = 20"
        if not decls and not belot:
            decl_text = "\n  _(комбинаций нет)_"

        url = state_to_url(webapp_url, game, pid)
        await context.bot.send_message(
            chat_id=pid,
            text=(
                f"★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*"
                f"{decl_text}\n\n"
                f"Нажмите кнопку чтобы заявить комбинации:"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🃏 Открыть игру и заявить", web_app=WebAppInfo(url=url))]
            ])
        )


async def _send_play_prompt(context, game, player_id):
    webapp_url = get_webapp_url(context)
    url = state_to_url(webapp_url, game, player_id)
    trump = game.trump_suit
    tricks = game.tricks_won
    await context.bot.send_message(
        chat_id=player_id,
        text=(
            f"🎮 *Ваш ход!*\n"
            f"★ {trump.value} {SUIT_NAMES_RU[trump]}  "
            f"· Взятки: 🔵{tricks[0]} 🔴{tricks[1]}"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=webapp_button("🃏 Сыграть карту", url)
    )


async def _send_watch(context, game, player_id, next_player_name):
    webapp_url = get_webapp_url(context)
    url = state_to_url(webapp_url, game, player_id)
    await context.bot.send_message(
        chat_id=player_id,
        text=f"⏳ Ход у {next_player_name}",
        reply_markup=webapp_button("🃏 Смотреть игру", url)
    )


# ─── Waiting room keyboard ───────────────────────────────────────────────────
def _waiting_room_keyboard(game, player_id):
    """Keyboard shown in the waiting room with leave/close button."""
    from telegram import WebAppInfo
    is_creator = (getattr(game, "creator_id", None) == player_id)
    btn_label = "🚫 Закрыть стол" if is_creator else "🚪 Выйти из стола"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn_label, callback_data="leave_table")],
    ])


# ─── Main callback handler ───────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    pid = update.effective_user.id
    gm = get_gm(context)

    if data == "noop":
        return

    if data == "create_game_prompt":
        await query.edit_message_text(
            "🃏 *Создать игру*\n\nВыберите количество игроков:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=mode_select_keyboard()
        )
        return

    if data.startswith("create_game:"):
        max_p = int(data.split(":")[1])
        name = player_name(update)
        existing = gm.get_game_by_player(pid)
        if existing and existing.state == GameState.WAITING:
            await query.edit_message_text(f"У вас уже есть игра: `{existing.game_id}`", parse_mode=ParseMode.MARKDOWN)
            return
        game = gm.create_game(pid, name, max_players=max_p)
        bot = context.bot
        bot_username = (await bot.get_me()).username
        join_link = f"https://t.me/{bot_username}?start=join_{game.game_id}"
        mode_label = "3 игрока (1 vs 2)" if max_p == 3 else "4 игрока (2 vs 2)"
        await query.edit_message_text(
            f"🃏 *Игра создана!* — {mode_label}\n{DIV}\n"
            f"Код: `{game.game_id}`\n\n"
            f"{join_link}\n\n"
            f"Или: `/join {game.game_id}`\n\n"
            f"👤 1/{max_p} · {name} ✅\n⬜️ Ждём ещё {max_p - 1}...",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_waiting_room_keyboard(game, pid)
        )
        return

    if data == "join_game_prompt":
        await query.edit_message_text("Введите:\n`/join КОД_ИГРЫ`", parse_mode=ParseMode.MARKDOWN)
        return

    if data == "show_rules":
        await query.edit_message_text("📖 Напишите /help для правил.")
        return

    # ── Leave / close table ──
    if data == "leave_table":
        result = gm.leave_game(pid)
        if not result["ok"]:
            await query.answer(result["error"], show_alert=True)
            return
        if result["closed"]:
            if result["was_creator"]:
                await query.edit_message_text("🚫 Вы закрыли стол. Все игроки уведомлены.")
                for other_pid in result["remaining_players"]:
                    try:
                        await context.bot.send_message(
                            chat_id=other_pid,
                            text=f"🚫 Создатель закрыл стол {result['game_id']}. Стол удалён."
                        )
                    except Exception:
                        pass
            else:
                await query.edit_message_text("👋 Стол пуст — удалён.")
        else:
            game_left = result["game"]
            pname = result["player_name"]
            remaining = result["remaining_players"]
            await query.edit_message_text(f"👋 Вы вышли из стола {result['game_id']}.")
            # Notify remaining players
            slots_text = f"{len(remaining)}/{game_left.max_players}"
            for other_pid in remaining:
                try:
                    await context.bot.send_message(
                        chat_id=other_pid,
                        text=f"👋 {pname} покинул стол.\n⏳ Игроков: {slots_text}",
                        reply_markup=_waiting_room_keyboard(game_left, other_pid)
                    )
                except Exception:
                    pass
        return

    game = gm.get_game_by_player(pid)
    if not game:
        await query.answer("Вы не в игре.", show_alert=True)
        return

    # ── Bid pass ──
    if data == "bid_pass":
        result = game.bid_pass(pid)
        if not result["ok"]:
            await query.answer(result["error"], show_alert=True)
            return
        if result.get("redeal"):
            await query.edit_message_text("🔄 Все спасовали дважды — перераздача!")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(chat_id=p, text="🔄 Перераздача!")
            game.start_round()
            await _notify_bidding_start(context, game)
        elif result.get("round2"):
            await query.edit_message_text("⏭ Пас. Второй круг торгов!")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(chat_id=p, text=f"⏭ {game.player_names[pid]} спасовал. Круг 2!")
            await _ask_bid(context, game)
        else:
            await query.edit_message_text("⏭ Пас.")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(chat_id=p, text=f"⏭ {game.player_names[pid]} спасовал.")
            await _ask_bid(context, game)
        return

    # ── Bid take ──
    if data.startswith("bid_take:"):
        suit_name = data.split(":")[1]
        suit = None if suit_name == "proposed" else Suit[suit_name]
        result = game.bid_take(pid, suit)
        if not result["ok"]:
            await query.answer(result["error"], show_alert=True)
            return
        trump = game.trump_suit
        await query.edit_message_text(f"✅ Берёте! ★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}")
        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p,
                    text=f"✅ {game.player_names[pid]} берёт! ★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}"
                )
        if game.max_players == 3:
            await _ask_discard(context, game)
        else:
            await _start_declarations(context, game)
        return

    # ── Next round ──
    if data == "next_round":
        if game.state != GameState.ROUND_END:
            await query.answer("Раунд ещё не завершён.", show_alert=True)
            return
        game.start_round()
        await query.edit_message_text("▶️ Начинаем новый раунд!")
        await _notify_bidding_start(context, game)
        return


# ─── WebApp data handler ─────────────────────────────────────────────────────
async def webapp_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle data sent from the Mini App via sendData()."""
    if not update.effective_message or not update.effective_message.web_app_data:
        return

    pid = update.effective_user.id
    gm = get_gm(context)
    game = gm.get_game_by_player(pid)

    if not game:
        await update.effective_message.reply_text("❌ Вы не в игре.")
        return

    try:
        payload = json.loads(update.effective_message.web_app_data.data)
    except Exception:
        await update.effective_message.reply_text("❌ Ошибка данных.")
        return

    action = payload.get("action")
    data = payload.get("data")
    webapp_url = get_webapp_url(context)

    # ── Bid ──
    if action == "bid_pass":
        result = game.bid_pass(pid)
        if not result["ok"]:
            await update.effective_message.reply_text(f"❌ {result['error']}")
            return
        await update.effective_message.reply_text("⏭ Пас.")
        for p in game.players:
            if p != pid:
                await context.bot.send_message(chat_id=p, text=f"⏭ {game.player_names[pid]} спасовал.")
        if result.get("redeal"):
            game.start_round()
            await _notify_bidding_start(context, game)
        elif result.get("round2"):
            await _ask_bid(context, game)
        else:
            await _ask_bid(context, game)

    elif action == "bid_take":
        suit_str = data
        # data is suit symbol like "♥" or "proposed"
        suit = None
        if suit_str and suit_str != "proposed":
            from cards import Suit as SuitEnum
            suit = next((s for s in SuitEnum if s.value == suit_str), None)
        result = game.bid_take(pid, suit)
        if not result["ok"]:
            await update.effective_message.reply_text(f"❌ {result['error']}")
            return
        trump = game.trump_suit
        await update.effective_message.reply_text(f"✅ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}")
        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p, text=f"✅ {game.player_names[pid]} берёт! ★ {trump.value} {SUIT_NAMES_RU[trump]}"
                )
        if game.max_players == 3:
            await _ask_discard(context, game)
        else:
            await _start_declarations(context, game)

    # ── Discard ──
    elif action == "discard":
        indices = [int(x) for x in data.split(",") if x.strip().isdigit()]
        hand = game.hands.get(pid, [])
        discarded = [hand[i].emoji() for i in indices if i < len(hand)]
        result = game.discard_cards(pid, indices)
        if not result["ok"]:
            await update.effective_message.reply_text(f"❌ {result['error']}")
            return
        await update.effective_message.reply_text(f"🗑 Сброшено: {' и '.join(discarded)}")
        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p, text=f"✅ {game.player_names[pid]} сбросил карты."
                )
        await _start_declarations(context, game)

    # ── Declare ──
    elif action == "declare":
        result = game.submit_declarations(pid)
        if not result["ok"]:
            await update.effective_message.reply_text(f"❌ {result['error']}")
            return
        await update.effective_message.reply_text("✅ Комбинации заявлены!")
        if result.get("all_done"):
            scores = result["scores"]
            t0, t1 = team_result_lines(game)
            msg = (
                f"📊 *Комбинации объявлены*\n{DIV}\n"
                f"🔵 {t0}: +{scores[0]}\n"
                f"🔴 {t1}: +{scores[1]}\n{DIV}\n🎮 Игра начинается!"
            )
            for p in game.players:
                await context.bot.send_message(chat_id=p, text=msg, parse_mode=ParseMode.MARKDOWN)
            first_pid = game.players[game.current_player_idx]
            await _send_play_prompt(context, game, first_pid)
            for p in game.players:
                if p != first_pid:
                    await _send_watch(context, game, p, game.player_names[first_pid])
        else:
            waiting = result["waiting"]
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p, text=f"📣 {game.player_names[pid]} заявил. Ждём ещё {waiting}..."
                    )

    # ── Play card ──
    elif action == "play":
        card_idx = int(data)
        hand = game.hands.get(pid, [])
        if card_idx >= len(hand):
            await update.effective_message.reply_text("❌ Неверная карта.")
            return

        card = hand[card_idx]
        result = game.play_card(pid, card)
        if not result["ok"]:
            await update.effective_message.reply_text(f"❌ {result['error']}")
            return

        await update.effective_message.reply_text(f"✅ Сыграно: {card.emoji()}")
        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p, text=f"🃏 {game.player_names[pid]} сыграл: {card.emoji()}"
                )

        if result.get("trick_done"):
            winner = result["winner"]
            trick_pts = result["trick_pts"]
            winner_team = result["winner_team"]
            icon = "🔵" if winner_team == 0 else "🔴"
            trick_msg = f"🏅 Взятку берёт {icon} {game.player_names[winner]}" + (f" (+{trick_pts})" if trick_pts else "")

            if result.get("round_done"):
                rs = result["round_scores"]
                total = result["total_scores"]
                t0, t1 = team_result_lines(game)
                outcome_map = {
                    "taker_wins": "✅ Взявший выполнил контракт!",
                    "taker_failed": "❌ Взявший провалил контракт! Все очки противнику.",
                    "tie": "⚖️ Ничья! Очки переходят на следующий раунд.",
                }
                outcome = outcome_map.get(result.get("outcome"), "")
                round_msg = (
                    f"{trick_msg}\n{DIV}\n🏁 *Раунд завершён!*\n\n{outcome}\n\n"
                    f"Очки раунда:\n  🔵 {t0}: *{rs[0]}*\n  🔴 {t1}: *{rs[1]}*\n{DIV}\n"
                    f"Общий счёт:\n  🔵 {score_bar(total[0])}\n  🔴 {score_bar(total[1])}"
                )
                if result.get("game_over"):
                    wt = result["winner_team"]
                    win = t0 if wt == 0 else t1
                    win_icon = "🔵" if wt == 0 else "🔴"
                    game_msg = f"{round_msg}\n\n{DIV}\n🎉 *ИГРА ОКОНЧЕНА!*\n🏆 {win_icon} *{win}* 🏆"
                    for p in game.players:
                        await context.bot.send_message(chat_id=p, text=game_msg, parse_mode=ParseMode.MARKDOWN)
                    gm.remove_game(game.game_id)
                else:
                    for p in game.players:
                        await context.bot.send_message(
                            chat_id=p, text=round_msg, parse_mode=ParseMode.MARKDOWN,
                            reply_markup=next_round_keyboard() if p == game.players[0] else None
                        )
            else:
                for p in game.players:
                    await context.bot.send_message(chat_id=p, text=trick_msg)
                next_pid = game.players[game.current_player_idx]
                await _send_play_prompt(context, game, next_pid)
                for p in game.players:
                    if p != next_pid:
                        await _send_watch(context, game, p, game.player_names[next_pid])
        else:
            next_pid = game.players[game.current_player_idx]
            await _send_play_prompt(context, game, next_pid)
            for p in game.players:
                if p != next_pid:
                    await _send_watch(context, game, p, game.player_names[next_pid])
