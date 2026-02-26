"""
Telegram handlers for Belot bot.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from game import GameState
from cards import Suit, Rank
from keyboards import (
    main_menu_keyboard, bidding_keyboard_round1, bidding_keyboard_round2,
    hand_keyboard, format_scores_full, next_round_keyboard, declarations_keyboard,
    format_hand_grouped, format_trick_table, score_bar, SUIT_NAMES_RU
)
from card_renderer import render_hand, render_trick, cards_to_render_data, trick_to_render_data

DIV = "─" * 24


def get_gm(context):
    return context.bot_data["game_manager"]


def player_name(update: Update) -> str:
    u = update.effective_user
    return u.full_name or u.username or f"Player{u.id}"


def team_line(game, short=False) -> str:
    p = game.players
    n = game.player_names
    if len(p) < 4:
        return ""
    if short:
        return (
            f"🔵 {n[p[0]]} & {n[p[2]]}  vs  🔴 {n[p[1]]} & {n[p[3]]}"
        )
    return (
        f"🔵 Команда 1: {n[p[0]]} & {n[p[2]]}\n"
        f"🔴 Команда 2: {n[p[1]]} & {n[p[3]]}"
    )


# ─── /start ────────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        code = args[0]
        if code.startswith("join_"):
            game_id = code[5:]
            await _do_join(update, context, game_id)
            return

    await update.message.reply_text(
        "🃏 *Белот — Молдавские правила*\n\n"
        "Карточная игра для 4 игроков (2 команды).\n"
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
        f"👥 4 игрока · 2 команды (сидящие напротив — партнёры)\n"
        f"🃏 32 карты (7–Туз, 4 масти)\n"
        f"🏆 Игра до *151 очка*\n\n"
        f"*Козыри:*\n"
        f"  ★В (Валет) = 20 очков — самый сильный\n"
        f"  ★9 (Девятка) = 14 очков\n"
        f"  ★Т (Туз) = 11, ★10 = 10, ★К = 4, ★Д = 3\n\n"
        f"*Обычные карты:*\n"
        f"  Т=11, 10=10, К=4, Д=3, В=2, 9/8/7=0\n\n"
        f"*Комбинации (объявляются в начале):*\n"
        f"  Терц  (3 подряд) = 20 очков\n"
        f"  Cinquante (4 подряд) = 50 очков\n"
        f"  Сто (5 подряд) = 100 очков\n"
        f"  Каре Т/К/Д/10 = 100 · Каре 9 = 150 · Каре В = 200\n"
        f"  💍 Белот К+Д козырной = 20 (объявить во время игры)\n\n"
        f"*Особые правила:*\n"
        f"  8888 — аннулирует все комбинации\n"
        f"  7777 — аннулирует раунд\n"
        f"  Перевёрнут Валет → следующий берёт авто\n"
        f"  Все 8 взяток = +90 бонус · Последняя = +10\n\n"
        f"*Команды:* позиции 1+3 vs 2+4 по порядку входа"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ─── /newgame ──────────────────────────────────────────────────────────────
async def create_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gm = get_gm(context)
    pid = update.effective_user.id
    name = player_name(update)

    existing = gm.get_game_by_player(pid)
    if existing and existing.state == GameState.WAITING:
        await update.message.reply_text(
            f"У вас уже есть открытая игра: `{existing.game_id}`\n"
            "Поделитесь ссылкой с друзьями!",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    game = gm.create_game(pid, name)
    bot = context.bot
    bot_username = (await bot.get_me()).username
    join_link = f"https://t.me/{bot_username}?start=join_{game.game_id}"

    await update.message.reply_text(
        f"🃏 *Игра создана!*\n"
        f"{DIV}\n"
        f"Код игры: `{game.game_id}`\n\n"
        f"Пригласите 3 друзей по ссылке:\n{join_link}\n\n"
        f"Или пусть напишут:\n`/join {game.game_id}`\n\n"
        f"👤 1/4  ·  {name} ✅",
        parse_mode=ParseMode.MARKDOWN
    )


# ─── /join ─────────────────────────────────────────────────────────────────
async def join_game_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Укажите код игры: `/join XXXXXXXX`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    game_id = context.args[0].upper()
    await _do_join(update, context, game_id)


async def _do_join(update: Update, context: ContextTypes.DEFAULT_TYPE, game_id: str):
    gm = get_gm(context)
    pid = update.effective_user.id
    name = player_name(update)

    game, error = gm.join_game(game_id, pid, name)
    if error:
        await update.message.reply_text(f"❌ {error}")
        return

    # Build player list
    slots = ["⬜️", "⬜️", "⬜️", "⬜️"]
    team_icons = ["🔵", "🔴", "🔵", "🔴"]
    player_lines = []
    for i, p in enumerate(game.players):
        player_lines.append(f"{team_icons[i]} {game.player_names[p]}")
    for i in range(len(game.players), 4):
        player_lines.append(f"⬜️ ожидаем...")

    players_text = "\n".join(player_lines)

    if game.is_full():
        await update.message.reply_text(
            f"✅ *{name}* вошёл в игру!\n"
            f"{DIV}\n"
            f"{players_text}\n\n"
            f"🚀 Все 4 игрока — начинаем!",
            parse_mode=ParseMode.MARKDOWN
        )
        await _notify_bidding_start(context, game)
    else:
        count = len(game.players)
        await update.message.reply_text(
            f"✅ Вы вошли в игру `{game_id}`!\n"
            f"{DIV}\n"
            f"{players_text}\n\n"
            f"⏳ Ждём ещё {4 - count} игрока...",
            parse_mode=ParseMode.MARKDOWN
        )
        for existing_pid in game.players:
            if existing_pid != pid:
                try:
                    await context.bot.send_message(
                        chat_id=existing_pid,
                        text=(
                            f"👋 *{name}* присоединился!\n"
                            f"{players_text}\n"
                            f"⏳ Ждём ещё {4 - count}..."
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass


# ─── Notify start of bidding ────────────────────────────────────────────────
async def _notify_bidding_start(context, game):
    """Send hands to all players and start bidding."""
    trump = game.trump_suit
    proposed = game.proposed_card
    teams = team_line(game)

    if game.auto_trump:
        taker = game.players[game.taker_idx]
        taker_name = game.player_names[taker]
        for pid in game.players:
            hand = game.hands[pid]
            hand_display = format_hand_grouped(hand, trump_suit=trump)
            await context.bot.send_message(
                chat_id=pid,
                text=(
                    f"🃏 *Раунд {game.round_num}*\n"
                    f"{DIV}\n"
                    f"{teams}\n"
                    f"{DIV}\n"
                    f"⚡ Перевёрнут *Валет {proposed.suit.value}* — {taker_name} берёт автоматически!\n"
                    f"★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*\n\n"
                    f"🖐 Ваши карты:\n{hand_display}"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        await _start_declarations(context, game)
    else:
        for pid in game.players:
            hand = game.hands[pid]
            hand_display = format_hand_grouped(hand)
            await context.bot.send_message(
                chat_id=pid,
                text=(
                    f"🃏 *Раунд {game.round_num}*\n"
                    f"{DIV}\n"
                    f"{teams}\n"
                    f"{DIV}\n"
                    f"Перевёрнутая карта: *{proposed.emoji()}*\n\n"
                    f"🖐 Ваши карты:\n{hand_display}"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        await _ask_bid(context, game)


async def _ask_bid(context, game):
    """Ask current bidder to bid."""
    bidder_id = game.players[game.current_bidder_idx]
    proposed = game.proposed_card

    if game.bidding_round == 1:
        text = (
            f"🎴 *Торги — Круг 1*\n"
            f"{DIV}\n"
            f"Предложен козырь: *{proposed.emoji()}* — {SUIT_NAMES_RU[proposed.suit]}\n\n"
            f"Взять этот козырь или пас?"
        )
        kb = bidding_keyboard_round1(proposed.suit)
    else:
        text = (
            f"🎴 *Торги — Круг 2*\n"
            f"{DIV}\n"
            f"Все спасовали.\n"
            f"Выберите любую масть (кроме {proposed.suit.value} {SUIT_NAMES_RU[proposed.suit]}) или пас:"
        )
        kb = bidding_keyboard_round2(proposed.suit)

    await context.bot.send_message(
        chat_id=bidder_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

    for pid in game.players:
        if pid != bidder_id:
            await context.bot.send_message(
                chat_id=pid,
                text=f"⏳ Торгует *{game.player_names[bidder_id]}*...",
                parse_mode=ParseMode.MARKDOWN
            )


async def _start_declarations(context, game):
    """Ask all players to submit declarations."""
    trump = game.trump_suit

    for pid in game.players:
        hand = game.hands[pid]

        from declarations import get_all_declarations, check_belot
        decls = get_all_declarations(hand, trump)
        belot = check_belot(hand, trump)

        decl_text = ""
        if decls:
            decl_lines = "\n".join(f"  📌 {d['name']}" for d in decls)
            decl_text = f"\n\n🃏 *Ваши комбинации:*\n{decl_lines}"
        if belot:
            decl_text += "\n  💍 Белот К+Д козырной = 20 (объявите во время игры)"
        if not decls and not belot:
            decl_text = "\n\n_(комбинаций нет)_"

        # Render full hand image (all cards valid at this point)
        render_data = cards_to_render_data(hand, None, trump)
        label = f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}"
        hand_img = render_hand(render_data, label=label)

        caption = (
            f"★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*\n"
            f"{DIV}"
            f"{decl_text}\n\n"
            f"Нажмите кнопку чтобы заявить комбинации:"
        )

        await context.bot.send_photo(
            chat_id=pid,
            photo=hand_img,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📣 Заявить комбинации", callback_data=f"declare:{game.game_id}")]
            ])
        )


async def _send_hand(context, game, player_id):
    """Send player their hand as a card image with action buttons."""
    hand = game.hands[player_id]
    valid = game.get_valid_cards(player_id)
    trump = game.trump_suit

    scores_text = format_scores_full(game)
    label = f"★ Козырь: {trump.value} {SUIT_NAMES_RU[trump]}   Взятки: 🔵{game.tricks_won[0]}  🔴{game.tricks_won[1]}"

    # Render hand image
    render_data = cards_to_render_data(hand, valid, trump)
    hand_img = render_hand(render_data, label=label)

    kb = hand_keyboard(hand, valid, game.game_id)

    caption = (
        f"🎮 *Ваш ход!*\n"
        f"{DIV}\n"
        f"{scores_text}\n"
        f"{DIV}\n"
        f"👇 Нажмите на карту чтобы сыграть:\n"
        f"_(серые карты нельзя сыграть по правилам)_"
    )

    # If there's a current trick, send trick image first
    if game.current_trick:
        trick_data, trick_labels = trick_to_render_data(
            game.current_trick, trump, game.player_names
        )
        trick_img = render_trick(trick_data, trick_labels)
        await context.bot.send_photo(
            chat_id=player_id,
            photo=trick_img,
            caption="🃏 *На столе:*",
            parse_mode=ParseMode.MARKDOWN
        )

    await context.bot.send_photo(
        chat_id=player_id,
        photo=hand_img,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )


# ─── Main callback handler ───────────────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    pid = update.effective_user.id
    gm = get_gm(context)

    # ── Create game ──
    if data == "create_game":
        name = player_name(update)
        existing = gm.get_game_by_player(pid)
        if existing and existing.state == GameState.WAITING:
            await query.edit_message_text(
                f"У вас уже есть игра: `{existing.game_id}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        game = gm.create_game(pid, name)
        bot = context.bot
        bot_username = (await bot.get_me()).username
        join_link = f"https://t.me/{bot_username}?start=join_{game.game_id}"
        await query.edit_message_text(
            f"🃏 *Игра создана!*\n"
            f"{DIV}\n"
            f"Код: `{game.game_id}`\n\n"
            f"Пригласительная ссылка:\n{join_link}\n\n"
            f"Или друзья пишут: `/join {game.game_id}`\n\n"
            f"👤 1/4 · {name} ✅\n"
            f"⬜️ Ожидаем ещё 3...",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── Join game prompt ──
    if data == "join_game_prompt":
        await query.edit_message_text(
            "Введите команду:\n`/join КОД_ИГРЫ`\n\nКод получите у создателя игры.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── Rules ──
    if data == "show_rules":
        await query.edit_message_text(
            "📖 Напишите /help для просмотра полных правил.",
        )
        return

    # ── All game actions ──
    game = gm.get_game_by_player(pid)
    if not game:
        await query.answer("Вы не в игре.", show_alert=True)
        return

    # ── Bidding ──
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
            await query.edit_message_text(
                f"⏭ Пас.\n🎴 Начинается второй круг торгов — теперь можно выбрать любую масть!"
            )
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=(
                            f"⏭ *{game.player_names[pid]}* спасовал.\n"
                            f"🎴 Второй круг торгов — выбор любой масти!"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
            await _ask_bid(context, game)
        else:
            await query.edit_message_text(f"⏭ Пас.")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏭ *{game.player_names[pid]}* спасовал.",
                        parse_mode=ParseMode.MARKDOWN
                    )
            await _ask_bid(context, game)
        return

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
                    text=(
                        f"✅ *{game.player_names[pid]}* берёт козырь!\n"
                        f"★ Козырь: *{trump.value} {SUIT_NAMES_RU[trump]}*"
                    ),
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

        await query.edit_message_text("✅ Комбинации заявлены!")

        if result.get("all_done"):
            scores = result["scores"]
            p0, p2 = game.player_names[game.players[0]], game.player_names[game.players[2]]
            p1, p3 = game.player_names[game.players[1]], game.player_names[game.players[3]]
            bonus_0 = f"+{scores[0]}" if scores[0] else "0"
            bonus_1 = f"+{scores[1]}" if scores[1] else "0"
            decl_msg = (
                f"📊 *Комбинации объявлены*\n"
                f"{DIV}\n"
                f"🔵 {p0} & {p2}: {bonus_0} очков\n"
                f"🔴 {p1} & {p3}: {bonus_1} очков\n"
                f"{DIV}\n"
                f"🎮 Игра начинается!"
            )
            for p in game.players:
                await context.bot.send_message(
                    chat_id=p, text=decl_msg, parse_mode=ParseMode.MARKDOWN
                )
            first_player = game.players[game.current_player_idx]
            await _send_hand(context, game, first_player)
            for p in game.players:
                if p != first_player:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏳ Ход у *{game.player_names[first_player]}*",
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

    # ── Playing cards ──
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

        await query.edit_message_text(f"✅ Вы сыграли: *{card.emoji()}*", parse_mode=ParseMode.MARKDOWN)

        # Notify others
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
                + (f" (+{trick_pts} очков)" if trick_pts else " (+0)")
                + "\n"
            )

            if result.get("round_done"):
                round_scores = result["round_scores"]
                total = result["total_scores"]
                p = game.players
                n = game.player_names
                outcome_map = {
                    "taker_wins": "✅ Команда взявшего выполнила контракт!",
                    "taker_failed": "❌ Команда взявшего провалила контракт!\n   Все очки достаются противнику.",
                    "tie": "⚖️ Ничья! Очки взявшего переходят на следующий раунд.",
                }
                outcome_text = outcome_map.get(result.get("outcome"), "")

                round_msg = (
                    f"{trick_msg}"
                    f"{DIV}\n"
                    f"🏁 *Раунд завершён!*\n\n"
                    f"{outcome_text}\n\n"
                    f"Очки раунда:\n"
                    f"  🔵 {n[p[0]]} & {n[p[2]]}: *{round_scores[0]}*\n"
                    f"  🔴 {n[p[1]]} & {n[p[3]]}: *{round_scores[1]}*\n"
                    f"{DIV}\n"
                    f"Общий счёт:\n"
                    f"  🔵 {score_bar(total[0])}\n"
                    f"  🔴 {score_bar(total[1])}"
                )

                if result.get("game_over"):
                    wt = result["winner_team"]
                    win_names = f"{n[p[0]]} & {n[p[2]]}" if wt == 0 else f"{n[p[1]]} & {n[p[3]]}"
                    win_icon = "🔵" if wt == 0 else "🔴"
                    game_msg = (
                        f"{round_msg}\n\n"
                        f"{DIV}\n"
                        f"🎉 *ИГРА ОКОНЧЕНА!*\n"
                        f"🏆 Победители: {win_icon} *{win_names}* 🏆"
                    )
                    for pl in game.players:
                        await context.bot.send_message(
                            chat_id=pl, text=game_msg, parse_mode=ParseMode.MARKDOWN
                        )
                    gm.remove_game(game.game_id)
                else:
                    for pl in game.players:
                        await context.bot.send_message(
                            chat_id=pl,
                            text=round_msg,
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
