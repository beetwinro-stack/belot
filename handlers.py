"""
Telegram handlers for Belot bot.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from game import GameState
from cards import Suit, Rank
from keyboards import (
    main_menu_keyboard, mode_select_keyboard,
    bidding_keyboard_round1, bidding_keyboard_round2,
    hand_keyboard, discard_keyboard,
    format_scores_full, next_round_keyboard,
    format_hand_grouped, format_trick_table, score_bar, SUIT_NAMES_RU
)
from card_renderer import render_hand, render_trick, cards_to_render_data, trick_to_render_data

DIV = "─" * 24

# Per-user discard selection state: user_id -> list of selected indices
_discard_selection = {}


def get_gm(context):
    return context.bot_data["game_manager"]


def player_name(update: Update) -> str:
    u = update.effective_user
    return u.full_name or u.username or f"Player{u.id}"


def team_line(game) -> str:
    p = game.players
    n = game.player_names
    if game.max_players == 4:
        if len(p) < 4:
            return ""
        return (
            f"🔵 Команда 1: {n[p[0]]} & {n[p[2]]}\n"
            f"🔴 Команда 2: {n[p[1]]} & {n[p[3]]}"
        )
    else:
        # 3-player: show all, teams clarify after bidding
        lines = [f"{'🔵🔴🟡'[i]} {n[p[i]]}" for i in range(len(p))]
        return "\n".join(lines)


def team_result_lines(game) -> tuple:
    """Return (team0_label, team1_label) for round/game result messages."""
    p = game.players
    n = game.player_names
    if game.max_players == 4:
        t0 = f"{n[p[0]]} & {n[p[2]]}"
        t1 = f"{n[p[1]]} & {n[p[3]]}"
    else:
        taker_id = p[game.taker_idx] if game.taker_idx is not None else p[0]
        others = [pid for pid in p if pid != taker_id]
        t0 = f"🗡 {n[taker_id]} (один)"
        t1 = " & ".join(n[pid] for pid in others)
    return t0, t1


# ─── /start ────────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        code = args[0]
        if code.startswith("join_"):
            await _do_join(update, context, code[5:])
            return

    await update.message.reply_text(
        "🃏 *Белот — Молдавские правила*\n\n"
        "Карточная игра для 3 или 4 игроков.\n"
        "Первый до 151 очка — победитель!\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard()
    )


# ─── /help ─────────────────────────────────────────────────────────────────
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        f"📖 *Правила Белота*\n"
        f"{DIV}\n"
        f"👥 3 или 4 игрока · 🏆 Игра до *151 очка*\n\n"
        f"*4 игрока:* 2 фиксированные команды (1+3 vs 2+4)\n"
        f"*3 игрока:* тот кто берёт козырь — играет один против двух\n"
        f"  Берущий получает 2 лишние карты из колоды и сбрасывает 2\n\n"
        f"*Козыри:*\n"
        f"  ★В (Валет) = 20 · ★9 = 14 · ★Т = 11 · ★10 = 10 · ★К = 4 · ★Д = 3\n\n"
        f"*Обычные карты:* Т=11, 10=10, К=4, Д=3, В=2, 9/8/7=0\n\n"
        f"*Комбинации:*\n"
        f"  Терц (3 подряд) = 20 · Cinquante (4) = 50 · Сто (5) = 100\n"
        f"  Каре Т/К/Д/10 = 100 · Каре 9 = 150 · Каре В = 200\n"
        f"  💍 Белот К+Д козырной = 20\n\n"
        f"*Особые:* 8888 — аннулирует комбинации · 7777 — аннулирует раунд\n"
        f"Все взятки = +90 · Последняя взятка = +10"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ─── /newgame ──────────────────────────────────────────────────────────────
async def create_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🃏 *Создать игру*\n\n"
        "Выберите количество игроков:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=mode_select_keyboard()
    )


# ─── /join ─────────────────────────────────────────────────────────────────
async def join_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Укажите код игры: `/join XXXXXXXX`",
            parse_mode=ParseMode.MARKDOWN
        )
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
    slots_icons = ["🔵", "🔴", "🔵", "🔴"]
    player_lines = []
    for i, p in enumerate(game.players):
        player_lines.append(f"{slots_icons[i % 4]} {game.player_names[p]}")
    for i in range(len(game.players), max_p):
        player_lines.append(f"⬜️ ожидаем...")
    players_text = "\n".join(player_lines)

    if game.is_full():
        await update.message.reply_text(
            f"✅ *{name}* вошёл в игру!\n"
            f"{DIV}\n{players_text}\n\n"
            f"🚀 Все {max_p} игрока — начинаем!",
            parse_mode=ParseMode.MARKDOWN
        )
        await _notify_bidding_start(context, game)
    else:
        count = len(game.players)
        await update.message.reply_text(
            f"✅ Вы вошли в игру `{game_id}`!\n"
            f"{DIV}\n{players_text}\n\n"
            f"⏳ Ждём ещё {max_p - count}...",
            parse_mode=ParseMode.MARKDOWN
        )
        for existing_pid in game.players:
            if existing_pid != pid:
                try:
                    await context.bot.send_message(
                        chat_id=existing_pid,
                        text=f"👋 *{name}* присоединился!\n{players_text}\n⏳ Ждём ещё {max_p - count}...",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass


# ─── Bidding start ──────────────────────────────────────────────────────────
async def _notify_bidding_start(context, game):
    trump = game.trump_suit
    proposed = game.proposed_card
    teams = team_line(game)

    if game.auto_trump:
        taker = game.players[game.taker_idx]
        taker_name = game.player_names[taker]
        for pid in game.players:
            render_data = cards_to_render_data(game.hands[pid], None, trump)
            label = f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}"
            hand_img = render_hand(render_data, label=label)
            await context.bot.send_photo(
                chat_id=pid,
                photo=hand_img,
                caption=(
                    f"🃏 *Раунд {game.round_num}*\n{DIV}\n{teams}\n{DIV}\n"
                    f"⚡ Перевёрнут *Валет {proposed.suit.value}* — {taker_name} берёт автоматически!\n"
                    f"★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        if game.max_players == 3:
            await _ask_discard(context, game)
        else:
            await _start_declarations(context, game)
    else:
        for pid in game.players:
            render_data = cards_to_render_data(game.hands[pid], None, None)
            label = f"Перевёрнутая карта: {proposed.emoji()}"
            hand_img = render_hand(render_data, label=label)
            await context.bot.send_photo(
                chat_id=pid,
                photo=hand_img,
                caption=(
                    f"🃏 *Раунд {game.round_num}*\n{DIV}\n{teams}\n{DIV}\n"
                    f"Предложенный козырь: *{proposed.emoji()}*"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        await _ask_bid(context, game)


async def _ask_bid(context, game):
    bidder_id = game.players[game.current_bidder_idx]
    proposed = game.proposed_card

    if game.bidding_round == 1:
        text = (
            f"🎴 *Торги — Круг 1*\n{DIV}\n"
            f"Предложен козырь: *{proposed.emoji()}* — {SUIT_NAMES_RU[proposed.suit]}\n\n"
            f"Взять или пас?"
        )
        kb = bidding_keyboard_round1(proposed.suit)
    else:
        text = (
            f"🎴 *Торги — Круг 2*\n{DIV}\n"
            f"Все спасовали. Выберите любую масть (кроме {proposed.suit.value}) или пас:"
        )
        kb = bidding_keyboard_round2(proposed.suit)

    await context.bot.send_message(
        chat_id=bidder_id, text=text,
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb
    )
    for pid in game.players:
        if pid != bidder_id:
            await context.bot.send_message(
                chat_id=pid,
                text=f"⏳ Торгует *{game.player_names[bidder_id]}*...",
                parse_mode=ParseMode.MARKDOWN
            )


# ─── 3-player: discard phase ────────────────────────────────────────────────
async def _ask_discard(context, game):
    """Ask the taker to discard 2 cards (3-player mode)."""
    taker_id = game.players[game.taker_idx]
    trump = game.trump_suit
    _discard_selection[taker_id] = []

    hand = game.hands[taker_id]
    render_data = cards_to_render_data(hand, None, trump)
    label = f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}  |  Сбросьте 2 карты"
    hand_img = render_hand(render_data, label=label)

    await context.bot.send_photo(
        chat_id=taker_id,
        photo=hand_img,
        caption=(
            f"🗑 *Сброс карт*\n{DIV}\n"
            f"У вас {len(hand)} карт (включая 2 из колоды).\n"
            f"Выберите *2 карты для сброса*:"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=discard_keyboard(hand, [], game.game_id)
    )

    for pid in game.players:
        if pid != taker_id:
            await context.bot.send_message(
                chat_id=pid,
                text=f"⏳ *{game.player_names[taker_id]}* выбирает карты для сброса...",
                parse_mode=ParseMode.MARKDOWN
            )


# ─── Declarations ───────────────────────────────────────────────────────────
async def _start_declarations(context, game):
    trump = game.trump_suit

    for pid in game.players:
        hand = game.hands[pid]
        from declarations import get_all_declarations, check_belot
        decls = get_all_declarations(hand, trump)
        belot = check_belot(hand, trump)

        decl_text = ""
        if decls:
            decl_text = "\n\n🃏 *Ваши комбинации:*\n" + "\n".join(f"  📌 {d['name']}" for d in decls)
        if belot:
            decl_text += "\n  💍 Белот К+Д козырной = 20 (объявите во время игры)"
        if not decls and not belot:
            decl_text = "\n\n_(комбинаций нет)_"

        render_data = cards_to_render_data(hand, None, trump)
        label = f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}"
        hand_img = render_hand(render_data, label=label)

        await context.bot.send_photo(
            chat_id=pid,
            photo=hand_img,
            caption=(
                f"★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*\n"
                f"{DIV}{decl_text}\n\nНажмите кнопку чтобы заявить комбинации:"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📣 Заявить комбинации", callback_data=f"declare:{game.game_id}")]
            ])
        )


# ─── Send hand ──────────────────────────────────────────────────────────────
async def _send_hand(context, game, player_id):
    hand = game.hands[player_id]
    valid = game.get_valid_cards(player_id)
    trump = game.trump_suit
    scores_text = format_scores_full(game)
    label = f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}   Взятки: 🔵{game.tricks_won[0]}  🔴{game.tricks_won[1]}"

    render_data = cards_to_render_data(hand, valid, trump)
    hand_img = render_hand(render_data, label=label)

    if game.current_trick:
        trick_data, trick_labels = trick_to_render_data(game.current_trick, trump, game.player_names)
        trick_img = render_trick(trick_data, trick_labels)
        await context.bot.send_photo(
            chat_id=player_id, photo=trick_img,
            caption="🃏 *На столе:*", parse_mode=ParseMode.MARKDOWN
        )

    await context.bot.send_photo(
        chat_id=player_id,
        photo=hand_img,
        caption=(
            f"🎮 *Ваш ход!*\n{DIV}\n{scores_text}\n{DIV}\n"
            f"👇 Нажмите на карту чтобы сыграть:\n_(серые — нельзя по правилам)_"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=hand_keyboard(hand, valid, game.game_id)
    )


# ─── Main callback handler ───────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    pid = update.effective_user.id
    gm = get_gm(context)

    # ── No-op button ──
    if data == "noop":
        return

    # ── Create game prompt ──
    if data == "create_game_prompt":
        await query.edit_message_text(
            "🃏 *Создать игру*\n\nВыберите количество игроков:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=mode_select_keyboard()
        )
        return

    # ── Create game with mode ──
    if data.startswith("create_game:"):
        max_p = int(data.split(":")[1])
        name = player_name(update)
        existing = gm.get_game_by_player(pid)
        if existing and existing.state == GameState.WAITING:
            await query.edit_message_text(
                f"У вас уже есть игра: `{existing.game_id}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        game = gm.create_game(pid, name, max_players=max_p)
        bot = context.bot
        bot_username = (await bot.get_me()).username
        join_link = f"https://t.me/{bot_username}?start=join_{game.game_id}"

        mode_label = "3 игрока (1 vs 2)" if max_p == 3 else "4 игрока (2 vs 2)"
        await query.edit_message_text(
            f"🃏 *Игра создана!* — {mode_label}\n{DIV}\n"
            f"Код: `{game.game_id}`\n\n"
            f"Пригласительная ссылка:\n{join_link}\n\n"
            f"Или друзья пишут: `/join {game.game_id}`\n\n"
            f"👤 1/{max_p} · {name} ✅\n"
            f"⬜️ Ожидаем ещё {max_p - 1}...",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── Join prompt ──
    if data == "join_game_prompt":
        await query.edit_message_text(
            "Введите команду:\n`/join КОД_ИГРЫ`\n\nКод получите у создателя игры.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── Rules ──
    if data == "show_rules":
        await query.edit_message_text("📖 Напишите /help для просмотра правил.")
        return

    # ── All in-game actions ──
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
                    await context.bot.send_message(chat_id=p, text="🔄 Все спасовали — перераздача!")
            game.start_round()
            await _notify_bidding_start(context, game)
        elif result.get("round2"):
            await query.edit_message_text("⏭ Пас. Начинается второй круг торгов!")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏭ *{game.player_names[pid]}* спасовал. Второй круг торгов!",
                        parse_mode=ParseMode.MARKDOWN
                    )
            await _ask_bid(context, game)
        else:
            await query.edit_message_text("⏭ Пас.")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏭ *{game.player_names[pid]}* спасовал.",
                        parse_mode=ParseMode.MARKDOWN
                    )
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
        await query.edit_message_text(
            f"✅ Вы берёте!\n★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*",
            parse_mode=ParseMode.MARKDOWN
        )
        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p,
                    text=f"✅ *{game.player_names[pid]}* берёт козырь!\n★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*",
                    parse_mode=ParseMode.MARKDOWN
                )

        if game.max_players == 3:
            await _ask_discard(context, game)
        else:
            await _start_declarations(context, game)
        return

    # ── Discard toggle (3-player) ──
    if data.startswith("discard_toggle:"):
        parts = data.split(":")
        card_idx = int(parts[2])
        selected = _discard_selection.get(pid, [])

        if card_idx in selected:
            selected.remove(card_idx)
        elif len(selected) < 2:
            selected.append(card_idx)
        else:
            await query.answer("Уже выбрано 2 карты. Снимите выбор с одной.", show_alert=True)
            return

        _discard_selection[pid] = selected
        hand = game.hands[pid]

        # Re-render hand image with selected cards highlighted
        render_data = cards_to_render_data(hand, None, game.trump_suit)
        trump = game.trump_suit
        label = f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}  |  Выбрано: {len(selected)}/2"
        hand_img = render_hand(render_data, label=label)

        selected_names = [hand[i].emoji() for i in selected]
        sel_text = " и ".join(selected_names) if selected_names else "ничего"

        # Send new photo message and delete old (edit_message_caption for photos)
        try:
            await query.edit_message_caption(
                caption=(
                    f"🗑 *Сброс карт*\n{DIV}\n"
                    f"Выбрано для сброса: *{sel_text}*\n"
                    f"{'Нажмите подтверждение ниже!' if len(selected) == 2 else f'Выберите ещё {2 - len(selected)} карту.'}"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=discard_keyboard(hand, selected, game.game_id)
            )
        except Exception:
            pass
        return

    # ── Discard confirm (3-player) ──
    if data.startswith("discard_confirm:"):
        selected = _discard_selection.get(pid, [])
        if len(selected) != 2:
            await query.answer("Выберите ровно 2 карты!", show_alert=True)
            return

        hand = game.hands[pid]
        discarded = [hand[i].emoji() for i in selected]
        result = game.discard_cards(pid, selected)
        if not result["ok"]:
            await query.answer(result["error"], show_alert=True)
            return

        _discard_selection.pop(pid, None)
        await query.edit_message_caption(
            caption=f"🗑 Сброшено: {' и '.join(discarded)}\n✅ Начинаем объявление комбинаций!"
        )

        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p,
                    text=f"✅ *{game.player_names[pid]}* сбросил карты. Объявляем комбинации!",
                    parse_mode=ParseMode.MARKDOWN
                )
        await _start_declarations(context, game)
        return

    # ── Declarations ──
    if data.startswith("declare:"):
        result = game.submit_declarations(pid)
        if not result["ok"]:
            await query.answer(result["error"], show_alert=True)
            return

        try:
            await query.edit_message_caption(caption="✅ Комбинации заявлены!")
        except Exception:
            await query.edit_message_text("✅ Комбинации заявлены!")

        if result.get("all_done"):
            scores = result["scores"]
            t0, t1 = team_result_lines(game)
            bonus_0 = f"+{scores[0]}" if scores[0] else "0"
            bonus_1 = f"+{scores[1]}" if scores[1] else "0"
            decl_msg = (
                f"📊 *Комбинации объявлены*\n{DIV}\n"
                f"🔵 {t0}: {bonus_0} очков\n"
                f"🔴 {t1}: {bonus_1} очков\n{DIV}\n"
                f"🎮 Игра начинается!"
            )
            for p in game.players:
                await context.bot.send_message(
                    chat_id=p, text=decl_msg, parse_mode=ParseMode.MARKDOWN
                )
            first_pid = game.players[game.current_player_idx]
            await _send_hand(context, game, first_pid)
            for p in game.players:
                if p != first_pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏳ Ход у *{game.player_names[first_pid]}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
        else:
            waiting = result["waiting"]
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"📣 *{game.player_names[pid]}* заявил комбинации. Ждём ещё {waiting}...",
                        parse_mode=ParseMode.MARKDOWN
                    )
        return

    # ── Play card ──
    if data.startswith("play:"):
        parts = data.split(":")
        card_idx = int(parts[2])

        if game.state != GameState.PLAYING:
            await query.answer("Сейчас не фаза игры.", show_alert=True)
            return
        if game.players[game.current_player_idx] != pid:
            await query.answer("Сейчас не ваш ход!", show_alert=True)
            return

        hand = game.hands[pid]
        if card_idx >= len(hand):
            await query.answer("Неверная карта.", show_alert=True)
            return

        card = hand[card_idx]
        result = game.play_card(pid, card)
        if not result["ok"]:
            await query.answer(result["error"], show_alert=True)
            return

        try:
            await query.edit_message_caption(
                caption=f"✅ Вы сыграли: *{card.emoji()}*",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            await query.edit_message_text(f"✅ Вы сыграли: *{card.emoji()}*", parse_mode=ParseMode.MARKDOWN)

        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p,
                    text=f"🃏 *{game.player_names[pid]}* сыграл: {card.emoji()}",
                    parse_mode=ParseMode.MARKDOWN
                )

        if result.get("trick_done"):
            winner = result["winner"]
            trick_pts = result["trick_pts"]
            winner_team = result["winner_team"]
            team_icon = "🔵" if winner_team == 0 else "🔴"
            trick_msg = (
                f"🏅 Взятку берёт {team_icon} *{game.player_names[winner]}*"
                + (f" (+{trick_pts})" if trick_pts else " (+0)") + "\n"
            )

            if result.get("round_done"):
                round_scores = result["round_scores"]
                total = result["total_scores"]
                t0, t1 = team_result_lines(game)
                outcome_map = {
                    "taker_wins": "✅ Взявший выполнил контракт!",
                    "taker_failed": "❌ Взявший провалил контракт!\n   Все очки достаются противнику.",
                    "tie": "⚖️ Ничья! Очки взявшего переходят на следующий раунд.",
                }
                outcome_text = outcome_map.get(result.get("outcome"), "")

                round_msg = (
                    f"{trick_msg}{DIV}\n🏁 *Раунд завершён!*\n\n{outcome_text}\n\n"
                    f"Очки раунда:\n"
                    f"  🔵 {t0}: *{round_scores[0]}*\n"
                    f"  🔴 {t1}: *{round_scores[1]}*\n"
                    f"{DIV}\nОбщий счёт:\n"
                    f"  🔵 {score_bar(total[0])}\n"
                    f"  🔴 {score_bar(total[1])}"
                )

                if result.get("game_over"):
                    wt = result["winner_team"]
                    win_label = t0 if wt == 0 else t1
                    win_icon = "🔵" if wt == 0 else "🔴"
                    game_msg = (
                        f"{round_msg}\n\n{DIV}\n"
                        f"🎉 *ИГРА ОКОНЧЕНА!*\n"
                        f"🏆 Победители: {win_icon} *{win_label}* 🏆"
                    )
                    for pl in game.players:
                        await context.bot.send_message(
                            chat_id=pl, text=game_msg, parse_mode=ParseMode.MARKDOWN
                        )
                    gm.remove_game(game.game_id)
                else:
                    for pl in game.players:
                        await context.bot.send_message(
                            chat_id=pl, text=round_msg,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=next_round_keyboard() if pl == game.players[0] else None
                        )
            else:
                for pl in game.players:
                    await context.bot.send_message(
                        chat_id=pl, text=trick_msg, parse_mode=ParseMode.MARKDOWN
                    )
                next_pid = game.players[game.current_player_idx]
                await _send_hand(context, game, next_pid)
                for pl in game.players:
                    if pl != next_pid:
                        await context.bot.send_message(
                            chat_id=pl,
                            text=f"⏳ Ход у *{game.player_names[next_pid]}*",
                            parse_mode=ParseMode.MARKDOWN
                        )
        else:
            next_pid = game.players[game.current_player_idx]
            await _send_hand(context, game, next_pid)
            for pl in game.players:
                if pl != next_pid:
                    await context.bot.send_message(
                        chat_id=pl,
                        text=f"⏳ Ход у *{game.player_names[next_pid]}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
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

    if data.startswith("invalid_card:"):
        await query.answer("❌ Эту карту нельзя сыграть по правилам!", show_alert=True)
        return
