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
    hand_keyboard, format_scores, next_round_keyboard, declarations_keyboard
)


def get_gm(context):
    return context.bot_data["game_manager"]


def player_name(update: Update) -> str:
    u = update.effective_user
    return u.full_name or u.username or f"Player{u.id}"


# ─── /start ────────────────────────────────────────────────────────────────
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if args:
        # Deep link: /start join_GAMEID
        code = args[0]
        if code.startswith("join_"):
            game_id = code[5:]
            await _do_join(update, context, game_id)
            return

    await update.message.reply_text(
        "🃏 *Белот — Молдавские правила*\n\n"
        "Добро пожаловать! Это карточная игра Белот для 4 игроков (2 команды).\n\n"
        "Выберите действие:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard()
    )


# ─── /help ─────────────────────────────────────────────────────────────────
async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Правила Белота (belot.md)*\n\n"
        "👥 4 игрока, 2 команды (сидящие напротив — партнёры)\n"
        "🃏 32 карты (7–Туз, 4 масти)\n\n"
        "*Козырь:*\n"
        "• Валет козырной масти = 20 очков\n"
        "• Девятка козырной = 14 очков\n"
        "• Остальные козыри по-обычному\n\n"
        "*Комбинации:*\n"
        "• Терц (3 подряд) = 20 очков\n"
        "• Cinquante (4 подряд) = 50 очков\n"
        "• Сто (5 подряд) = 100 очков\n"
        "• Каре тузов/королей/дам/10-ок = 100 очков\n"
        "• Каре девяток = 150 очков\n"
        "• Каре валетов = 200 очков\n"
        "• Белот (K+Q козырной) = 20 очков\n\n"
        "*Особые правила:*\n"
        "• 8888 — аннулирует все комбинации (кроме Белота и 7777)\n"
        "• 7777 — аннулирует весь раунд\n"
        "• Если перевёрнутая карта — Валет, следующий игрок берёт автоматически\n"
        "• Все взятки = +90 бонус\n"
        "• Последняя взятка = +10 очков\n\n"
        "🏆 *Игра до 151 очка*\n\n"
        "Команды: 0 и 2, 1 и 3 по порядку рассадки."
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
        f"🃏 *Игра создана!*\n\n"
        f"Код игры: `{game.game_id}`\n\n"
        f"Пригласите 3 друзей по ссылке:\n{join_link}\n\n"
        f"Или пусть напишут `/join {game.game_id}`\n\n"
        f"Игроки (1/4): {name}",
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

    players_text = "\n".join(
        f"{'🔵' if i % 2 == 0 else '🔴'} {game.player_names[p]}"
        for i, p in enumerate(game.players)
    )

    if game.is_full():
        # Game started! Notify all players
        await update.message.reply_text(
            f"✅ {name} присоединился! Игра начинается!\n\n{players_text}",
        )
        await _notify_bidding_start(context, game)
    else:
        count = len(game.players)
        await update.message.reply_text(
            f"✅ Вы вошли в игру `{game_id}`!\n\n"
            f"Игроки ({count}/4):\n{players_text}\n\n"
            f"Ожидаем ещё {4 - count} игрока...",
            parse_mode=ParseMode.MARKDOWN
        )
        # Notify existing players
        for existing_pid in game.players:
            if existing_pid != pid:
                try:
                    await context.bot.send_message(
                        chat_id=existing_pid,
                        text=f"👋 {name} присоединился к игре!\nИгроков: {count}/4"
                    )
                except Exception:
                    pass


# ─── Notify start of bidding ────────────────────────────────────────────────
async def _notify_bidding_start(context, game):
    """Send hands to all players and start bidding."""
    trump = game.trump_suit
    proposed = game.proposed_card

    team_text = (
        f"🔵 Команда 1: {game.player_names[game.players[0]]} & {game.player_names[game.players[2]]}\n"
        f"🔴 Команда 2: {game.player_names[game.players[1]]} & {game.player_names[game.players[3]]}"
    )

    if game.auto_trump:
        # Auto take because Valet was flipped
        taker = game.players[game.taker_idx]
        for pid in game.players:
            hand = game.hands[pid]
            hand_text = " ".join(c.emoji() for c in hand)
            await context.bot.send_message(
                chat_id=pid,
                text=(
                    f"🃏 *Раунд {game.round_num} начался!*\n\n"
                    f"{team_text}\n\n"
                    f"⚡ Перевёрнута карта *Валет {proposed.suit.value}* — "
                    f"{game.player_names[taker]} берёт автоматически!\n"
                    f"Козырь: {trump.value} {trump.name.capitalize()}\n\n"
                    f"Ваши карты: {hand_text}"
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        await _start_declarations(context, game)
    else:
        # Normal bidding
        for pid in game.players:
            hand = game.hands[pid]
            hand_text = " ".join(c.emoji() for c in hand)
            await context.bot.send_message(
                chat_id=pid,
                text=(
                    f"🃏 *Раунд {game.round_num} начался!*\n\n"
                    f"{team_text}\n\n"
                    f"Перевёрнутая карта: *{proposed.emoji()}*\n\n"
                    f"Ваши карты: {hand_text}"
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
            f"🎴 *Торги — Раунд 1*\n\n"
            f"Предложенный козырь: *{proposed.emoji()}* ({proposed.suit.name.capitalize()})\n\n"
            f"Взять этот козырь или пас?"
        )
        kb = bidding_keyboard_round1(proposed.suit)
    else:
        text = (
            f"🎴 *Торги — Раунд 2*\n\n"
            f"Все спасовали. Выберите любую масть (кроме {proposed.suit.value}) или пас:"
        )
        kb = bidding_keyboard_round2(proposed.suit)

    await context.bot.send_message(
        chat_id=bidder_id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

    # Notify others it's not their turn
    for pid in game.players:
        if pid != bidder_id:
            await context.bot.send_message(
                chat_id=pid,
                text=f"⏳ Ход торгов у *{game.player_names[bidder_id]}*",
                parse_mode=ParseMode.MARKDOWN
            )


async def _start_declarations(context, game):
    """Ask all players to submit declarations."""
    trump = game.trump_suit
    for pid in game.players:
        hand = game.hands[pid]
        hand_text = " ".join(c.emoji() for c in hand)

        from declarations import get_all_declarations, check_belot
        decls = get_all_declarations(hand, trump)
        belot = check_belot(hand, trump)

        decl_text = ""
        if decls:
            decl_text = "\n🃏 Ваши комбинации:\n" + "\n".join(f"  • {d['name']}" for d in decls)
        if belot:
            decl_text += "\n  • 💍 Белот (K+Q козырной) = 20 очков (объявите во время игры)"

        await context.bot.send_message(
            chat_id=pid,
            text=(
                f"🎯 Козырь определён: *{trump.value} {trump.name.capitalize()}*\n\n"
                f"Ваши карты: {hand_text}"
                f"{decl_text}\n\n"
                f"Нажмите кнопку чтобы заявить комбинации и начать игру:"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📣 Заявить комбинации", callback_data=f"declare:{game.game_id}")]
            ])
        )


async def _send_hand(context, game, player_id):
    """Send player their hand with valid cards marked."""
    hand = game.hands[player_id]
    valid = game.get_valid_cards(player_id)
    trump = game.trump_suit

    hand_text = " ".join(
        f"[{c.emoji()}]" if c in valid else c.emoji()
        for c in hand
    )
    trick_text = ""
    if game.current_trick:
        trick_text = "\n\nСтол: " + " | ".join(
            f"{game.player_names[p]}: {card.emoji()}"
            for p, card in game.current_trick
        )

    kb = hand_keyboard(hand, valid, game.game_id)

    await context.bot.send_message(
        chat_id=player_id,
        text=(
            f"🎮 *Ваш ход!*\n"
            f"Козырь: {trump.value} {trump.name.capitalize()}\n\n"
            f"Ваши карты ({len(hand)}):\n{hand_text}"
            f"{trick_text}\n\n"
            f"Выберите карту:"
        ),
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
            f"🃏 *Игра создана!*\n\n"
            f"Код: `{game.game_id}`\n\n"
            f"Пригласительная ссылка:\n{join_link}\n\n"
            f"Или друзья пишут: `/join {game.game_id}`\n\n"
            f"Ожидаем игроков (1/4)...",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── Join game prompt ──
    if data == "join_game_prompt":
        await query.edit_message_text(
            "Введите команду: `/join КОД_ИГРЫ`\n\nКод получите у создателя игры.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # ── Rules ──
    if data == "show_rules":
        await query.edit_message_text(
            "📖 Напишите /help для просмотра правил.",
        )
        return

    # ── Bidding ──
    game = gm.get_game_by_player(pid)
    if not game:
        await query.answer("Вы не в игре.", show_alert=True)
        return

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
            await query.edit_message_text("⏭ Пас. Начинается второй круг торгов.")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏭ {game.player_names[pid]} спасовал. Второй круг торгов."
                    )
            await _ask_bid(context, game)
        else:
            await query.edit_message_text(f"⏭ Пас.")
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏭ {game.player_names[pid]} спасовал."
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
            f"✅ Вы берёте! Козырь: {trump.value} {trump.name.capitalize()}"
        )
        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p,
                    text=f"✅ {game.player_names[pid]} берёт козырь: {trump.value} {trump.name.capitalize()}"
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
            t0 = game.player_names[game.players[0]]
            t2 = game.player_names[game.players[2]]
            t1 = game.player_names[game.players[1]]
            t3 = game.player_names[game.players[3]]
            decl_msg = (
                f"📊 *Комбинации подсчитаны:*\n"
                f"🔵 {t0} & {t2}: +{scores[0]} очков\n"
                f"🔴 {t1} & {t3}: +{scores[1]} очков\n\n"
                f"🎮 Игра начинается!"
            )
            for p in game.players:
                await context.bot.send_message(
                    chat_id=p, text=decl_msg, parse_mode=ParseMode.MARKDOWN
                )
            # Send hand to first player
            first_player = game.players[game.current_player_idx]
            await _send_hand(context, game, first_player)
            for p in game.players:
                if p != first_player:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏳ Ожидаем хода *{game.player_names[first_player]}*",
                        parse_mode=ParseMode.MARKDOWN
                    )
        else:
            waiting = result["waiting"]
            for p in game.players:
                if p != pid:
                    await context.bot.send_message(
                        chat_id=p,
                        text=f"⏳ {game.player_names[pid]} заявил комбинации. Ждём ещё {waiting}..."
                    )
        return

    # ── Playing cards ──
    if data.startswith("play:"):
        parts = data.split(":")
        game_id = parts[1]
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

        await query.edit_message_text(f"✅ Вы сыграли: {card.emoji()}")

        # Notify others
        for p in game.players:
            if p != pid:
                await context.bot.send_message(
                    chat_id=p,
                    text=f"🃏 {game.player_names[pid]} сыграл: {card.emoji()}"
                )

        if result.get("trick_done"):
            winner = result["winner"]
            trick_pts = result["trick_pts"]
            trick_msg = (
                f"🏅 Взятку забирает *{game.player_names[winner]}* (+{trick_pts} очков)\n"
            )

            if result.get("round_done"):
                round_scores = result["round_scores"]
                total = result["total_scores"]
                outcome_map = {
                    "taker_wins": "✅ Команда взявшего выполнила контракт!",
                    "taker_failed": "❌ Команда взявшего не выполнила контракт! Все очки противнику.",
                    "tie": "⚖️ Ничья! Очки взявшего переходят на следующий раунд.",
                }
                outcome_text = outcome_map.get(result.get("outcome"), "")
                p0 = game.player_names[game.players[0]]
                p2 = game.player_names[game.players[2]]
                p1 = game.player_names[game.players[1]]
                p3 = game.player_names[game.players[3]]

                round_msg = (
                    f"{trick_msg}\n"
                    f"🏁 *Раунд завершён!*\n\n"
                    f"{outcome_text}\n\n"
                    f"Очки раунда:\n"
                    f"🔵 {p0} & {p2}: {round_scores[0]}\n"
                    f"🔴 {p1} & {p3}: {round_scores[1]}\n\n"
                    f"Общий счёт:\n"
                    f"🔵 {p0} & {p2}: *{total[0]}* / 151\n"
                    f"🔴 {p1} & {p3}: *{total[1]}* / 151"
                )

                if result.get("game_over"):
                    wt = result["winner_team"]
                    if wt == 0:
                        win_names = f"{p0} & {p2}"
                    else:
                        win_names = f"{p1} & {p3}"
                    game_msg = (
                        f"{round_msg}\n\n"
                        f"🎉 *ИГРА ОКОНЧЕНА!*\n"
                        f"Победители: {'🔵' if wt == 0 else '🔴'} *{win_names}* 🏆"
                    )
                    for p in game.players:
                        await context.bot.send_message(
                            chat_id=p, text=game_msg, parse_mode=ParseMode.MARKDOWN
                        )
                    gm.remove_game(game.game_id)
                else:
                    for p in game.players:
                        await context.bot.send_message(
                            chat_id=p,
                            text=round_msg,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=next_round_keyboard() if p == game.players[0] else None
                        )
            else:
                for p in game.players:
                    await context.bot.send_message(
                        chat_id=p, text=trick_msg, parse_mode=ParseMode.MARKDOWN
                    )
                # Next player's turn
                next_pid = game.players[game.current_player_idx]
                await _send_hand(context, game, next_pid)
                for p in game.players:
                    if p != next_pid:
                        await context.bot.send_message(
                            chat_id=p,
                            text=f"⏳ Ход у *{game.player_names[next_pid]}*",
                            parse_mode=ParseMode.MARKDOWN
                        )
        else:
            # Continue trick
            next_pid = game.players[game.current_player_idx]
            await _send_hand(context, game, next_pid)
            for p in game.players:
                if p != next_pid:
                    await context.bot.send_message(
                        chat_id=p,
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
