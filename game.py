"""
Core Belot game state and logic (Moldova / belot.md rules)

Game flow:
1. 4 players, 2 teams (0+2 vs 1+3)
2. Deal 5 cards each, flip top card → propose as trump
3. Bidding: each player can "take" or "pass" (round 1: only proposed suit)
4. If all pass → round 2: any suit or "pass"
5. If Valet is flipped → next player MUST take, trump = valet's suit
6. After trump chosen → deal 3 more cards each (total 8 per player)
7. Declarations announced before first trick
8. 8 tricks played, score counted
9. Game to 151+ points
"""
import random
from cards import Card, Suit, Rank, Deck
from declarations import (
    get_all_declarations, check_belot, has_8888, has_7777,
    compare_declarations
)


class GameState:
    WAITING = "waiting"
    BIDDING = "bidding"
    DECLARATIONS = "declarations"
    PLAYING = "playing"
    ROUND_END = "round_end"
    GAME_END = "game_end"


class BelotGame:
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.players = []          # list of player_ids (Telegram user IDs)
        self.player_names = {}     # player_id -> display name
        self.state = GameState.WAITING

        # Teams: team 0 = players[0] + players[2], team 1 = players[1] + players[3]
        self.scores = [0, 0]       # total game score per team
        self.round_scores = [0, 0] # current round score

        # Deck and hands
        self.hands = {}            # player_id -> list of Card
        self.deck = None

        # Bidding
        self.proposed_card = None  # The flipped card in round 1
        self.trump_suit = None
        self.bidding_round = 1     # 1 or 2
        self.current_bidder_idx = 0  # index into self.players
        self.taker_idx = None      # index of player who took trump
        self.auto_trump = False    # True if Valet was flipped

        # Declarations
        self.all_declarations = {} # player_id -> list of decl dicts
        self.declaration_scores = [0, 0]  # bonus from declarations
        self.declarations_done = set()    # player_ids who submitted
        self.belot_announced = {}  # player_id -> bool (K+Q of trump)
        self.belot_score_given = {} # player_id -> bool

        # Tricks
        self.current_trick = []    # list of (player_id, Card)
        self.trick_winner_idx = None
        self.tricks_won = [0, 0]   # per team
        self.tricks_history = []
        self.current_player_idx = 0  # index into players for current turn

        # Special rules
        self.eight_eight_eight_eight = False  # 8888 found
        self.seven_seven_seven_seven = False  # 7777 found

        # Round number
        self.round_num = 0
        self.dealer_idx = 0

    @property
    def num_players(self):
        return len(self.players)

    def team_of(self, player_id) -> int:
        idx = self.players.index(player_id)
        return idx % 2

    def team_of_idx(self, idx) -> int:
        return idx % 2

    def partner_of(self, player_id):
        idx = self.players.index(player_id)
        return self.players[(idx + 2) % 4]

    def add_player(self, player_id: int, name: str) -> bool:
        if player_id in self.players or len(self.players) >= 4:
            return False
        self.players.append(player_id)
        self.player_names[player_id] = name
        return True

    def is_full(self) -> bool:
        return len(self.players) == 4

    def start_round(self):
        """Deal cards and start bidding."""
        self.round_num += 1
        self.state = GameState.BIDDING
        self.trump_suit = None
        self.taker_idx = None
        self.auto_trump = False
        self.round_scores = [0, 0]
        self.all_declarations = {}
        self.declaration_scores = [0, 0]
        self.declarations_done = set()
        self.belot_announced = {}
        self.belot_score_given = {}
        self.current_trick = []
        self.tricks_won = [0, 0]
        self.tricks_history = []
        self.eight_eight_eight_eight = False
        self.seven_seven_seven_seven = False
        self.bidding_round = 1

        # Deal 5 cards each
        self.deck = Deck()
        self.deck.shuffle()
        self.hands = {}
        for p in self.players:
            self.hands[p] = self.deck.deal(5)

        # Flip top card
        self.proposed_card = self.deck.top_card()

        # Next player after dealer starts bidding
        self.current_bidder_idx = (self.dealer_idx + 1) % 4

        # Special rule: if proposed card is Valet → auto take
        if self.proposed_card.rank == Rank.JACK:
            self.auto_trump = True
            self.trump_suit = self.proposed_card.suit
            self.taker_idx = self.current_bidder_idx
            self._deal_remaining()
            self.state = GameState.DECLARATIONS
            self.current_player_idx = (self.dealer_idx + 1) % 4

    def bid_take(self, player_id: int, suit: Suit = None) -> dict:
        """Player takes trump. suit=None in round 1 (takes proposed suit)."""
        player_idx = self.players.index(player_id)
        if player_idx != self.current_bidder_idx:
            return {"ok": False, "error": "Not your turn to bid"}

        if self.bidding_round == 1:
            self.trump_suit = self.proposed_card.suit
        else:
            if suit is None:
                return {"ok": False, "error": "Must choose a suit in round 2"}
            if suit == self.proposed_card.suit:
                return {"ok": False, "error": "Cannot choose same suit as proposed in round 2"}
            self.trump_suit = suit

        self.taker_idx = player_idx
        self._deal_remaining()
        self.state = GameState.DECLARATIONS
        self.current_player_idx = (self.dealer_idx + 1) % 4
        return {"ok": True, "trump": self.trump_suit}

    def bid_pass(self, player_id: int) -> dict:
        """Player passes."""
        player_idx = self.players.index(player_id)
        if player_idx != self.current_bidder_idx:
            return {"ok": False, "error": "Not your turn to bid"}

        next_idx = (self.current_bidder_idx + 1) % 4

        # Check if we've gone around
        if next_idx == (self.dealer_idx + 1) % 4:
            # Completed a round of bidding
            if self.bidding_round == 1:
                self.bidding_round = 2
                self.current_bidder_idx = (self.dealer_idx + 1) % 4
                return {"ok": True, "round2": True}
            else:
                # Everyone passed twice → redeal
                self.dealer_idx = (self.dealer_idx + 1) % 4
                return {"ok": True, "redeal": True}
        else:
            self.current_bidder_idx = next_idx
            return {"ok": True}

    def _deal_remaining(self):
        """Deal 3 more cards to each player after trump is chosen."""
        for p in self.players:
            self.hands[p].extend(self.deck.deal(3))

    def submit_declarations(self, player_id: int) -> dict:
        """Player submits (or skips) declarations."""
        if player_id in self.declarations_done:
            return {"ok": False, "error": "Already submitted"}

        decls = get_all_declarations(self.hands[player_id], self.trump_suit)

        # Check special cards
        if has_8888(self.hands[player_id]):
            self.eight_eight_eight_eight = True
        if has_7777(self.hands[player_id]):
            self.seven_seven_seven_seven = True

        self.all_declarations[player_id] = decls
        self.declarations_done.add(player_id)
        self.belot_announced[player_id] = check_belot(self.hands[player_id], self.trump_suit)

        if len(self.declarations_done) == 4:
            self._resolve_declarations()
            self.state = GameState.PLAYING
            return {"ok": True, "all_done": True, "scores": self.declaration_scores}

        return {"ok": True, "waiting": 4 - len(self.declarations_done)}

    def _resolve_declarations(self):
        """Calculate declaration scores."""
        # 8888 cancels all except Belot and 7777
        if self.eight_eight_eight_eight:
            for pid in self.players:
                self.all_declarations[pid] = [
                    d for d in self.all_declarations.get(pid, [])
                    if d['type'] == 'belot'
                ]
            # 8888 holder gets their declarations back
            # (8888 itself scores nothing per rules)

        # Find which player has the best declaration
        decls_list = [(self.players.index(pid), decls)
                      for pid, decls in self.all_declarations.items() if decls]
        
        if decls_list:
            best_player_idx = compare_declarations(decls_list)
            winning_team = self.team_of_idx(best_player_idx)
            
            # Only the winning team gets their declaration points
            for pid in self.players:
                pidx = self.players.index(pid)
                if self.team_of_idx(pidx) == winning_team:
                    for d in self.all_declarations.get(pid, []):
                        self.declaration_scores[winning_team] += d['score']

        # Belot (K+Q of trump) - always counted regardless, announced during play
        for pid in self.players:
            self.belot_score_given[pid] = False

    def get_valid_cards(self, player_id: int) -> list:
        """Get list of cards the player can legally play."""
        hand = self.hands[player_id]
        if not self.current_trick:
            return hand[:]  # Lead: any card

        lead_card = self.current_trick[0][1]
        lead_suit = lead_card.suit
        trump = self.trump_suit

        # Find current winning card
        winning_card = self.current_trick[0][1]
        winning_player_idx = self.players.index(self.current_trick[0][0])
        for pid, card in self.current_trick[1:]:
            if card.beats(winning_card, trump, lead_suit):
                winning_card = card
                winning_player_idx = self.players.index(pid)

        player_idx = self.players.index(player_id)
        partner_winning = (winning_player_idx % 2 == player_idx % 2)

        # Cards of lead suit in hand
        lead_cards = [c for c in hand if c.suit == lead_suit]
        trump_cards = [c for c in hand if c.suit == trump]
        
        # Must follow suit if possible
        if lead_cards:
            if lead_suit == trump:
                # Trump was led - must play higher trump if possible
                higher = [c for c in lead_cards if c.trump_order() > winning_card.trump_order()]
                return higher if higher else lead_cards
            return lead_cards

        # Can't follow suit
        if partner_winning:
            # Partner is winning → not obliged to cut
            return hand[:]
        
        # Must cut (play trump) if possible
        if trump_cards:
            # Must play higher trump if possible
            if winning_card.suit == trump:
                higher = [c for c in trump_cards if c.trump_order() > winning_card.trump_order()]
                return higher if higher else trump_cards
            return trump_cards

        # Can't cut either → any card
        return hand[:]

    def play_card(self, player_id: int, card: Card) -> dict:
        """Player plays a card."""
        if self.state != GameState.PLAYING:
            return {"ok": False, "error": "Not in playing phase"}

        player_idx = self.players.index(player_id)
        if player_idx != self.current_player_idx:
            return {"ok": False, "error": "Not your turn"}

        valid = self.get_valid_cards(player_id)
        if card not in valid:
            return {"ok": False, "error": "Invalid card (rule violation)"}

        # Check Belot announcement (K or Q of trump)
        if self.belot_announced.get(player_id) and not self.belot_score_given.get(player_id):
            if card.suit == self.trump_suit and card.rank in (Rank.KING, Rank.QUEEN):
                team = self.team_of(player_id)
                self.declaration_scores[team] += 20
                self.belot_score_given[player_id] = True

        # Remove card from hand
        self.hands[player_id].remove(card)
        self.current_trick.append((player_id, card))

        result = {"ok": True, "card": card}

        if len(self.current_trick) == 4:
            # Resolve trick
            result.update(self._resolve_trick())
        else:
            self.current_player_idx = (self.current_player_idx + 1) % 4

        return result

    def _resolve_trick(self) -> dict:
        """Determine trick winner, add points, prepare for next trick."""
        lead_suit = self.current_trick[0][1].suit
        trump = self.trump_suit

        best_pid, best_card = self.current_trick[0]
        for pid, card in self.current_trick[1:]:
            if card.beats(best_card, trump, lead_suit):
                best_card = card
                best_pid = pid

        winner_idx = self.players.index(best_pid)
        winning_team = winner_idx % 2
        self.tricks_won[winning_team] += 1

        # Add card points
        trick_pts = sum(card.points(trump) for _, card in self.current_trick)
        self.round_scores[winning_team] += trick_pts

        self.tricks_history.append({
            "cards": self.current_trick[:],
            "winner": best_pid,
            "points": trick_pts,
        })
        self.current_trick = []
        self.current_player_idx = winner_idx

        result = {
            "trick_done": True,
            "winner": best_pid,
            "winner_team": winning_team,
            "trick_pts": trick_pts,
        }

        # Check if round is done (all 8 tricks played)
        if sum(self.tricks_won) == 8:
            result.update(self._end_round())

        return result

    def _end_round(self) -> dict:
        """Calculate round scores and update game scores."""
        self.state = GameState.ROUND_END
        trump = self.trump_suit

        # Last trick bonus = 10 points
        last_winner = self.tricks_history[-1]["winner"]
        last_team = self.team_of(last_winner)
        self.round_scores[last_team] += 10

        # Все взятки = "белот" (match bonus) = extra 90 pts → total 252
        for team in [0, 1]:
            if self.tricks_won[team] == 8:
                self.round_scores[team] += 90

        # Add declaration bonuses
        for team in [0, 1]:
            self.round_scores[team] += self.declaration_scores[team]

        # 7777 check: cancel the round
        if self.seven_seven_seven_seven:
            self.dealer_idx = (self.dealer_idx + 1) % 4
            return {"round_cancelled": True, "reason": "7777 - четыре семёрки!"}

        # Determine if taker's team made contract
        taker_team = self.taker_idx % 2
        opponent_team = 1 - taker_team

        taker_pts = self.round_scores[taker_team]
        opp_pts = self.round_scores[opponent_team]

        outcome = ""
        if taker_pts > opp_pts:
            # Normal: each team keeps their points
            self.scores[taker_team] += taker_pts
            self.scores[opponent_team] += opp_pts
            outcome = "taker_wins"
        elif taker_pts == opp_pts:
            # Tie: taker gets 0, opponent gets their points + taker's reserved for next round
            self.scores[opponent_team] += opp_pts
            # taker_pts are suspended (not added this round - simplified: add to next)
            outcome = "tie"
        else:
            # Taker failed: ALL points go to opponent
            total = taker_pts + opp_pts
            self.scores[opponent_team] += total
            outcome = "taker_failed"

        self.dealer_idx = (self.dealer_idx + 1) % 4

        # Check game end (151+)
        game_over = False
        winner_team = None
        for team in [0, 1]:
            if self.scores[team] >= 151:
                game_over = True
                winner_team = team
                self.state = GameState.GAME_END

        if not game_over:
            self.state = GameState.ROUND_END

        return {
            "round_done": True,
            "round_scores": self.round_scores[:],
            "total_scores": self.scores[:],
            "outcome": outcome,
            "game_over": game_over,
            "winner_team": winner_team,
            "taker_team": taker_team,
        }

    def get_status(self) -> dict:
        return {
            "game_id": self.game_id,
            "state": self.state,
            "players": [(pid, self.player_names[pid]) for pid in self.players],
            "scores": self.scores[:],
            "round_num": self.round_num,
            "trump": self.trump_suit.value if self.trump_suit else None,
            "current_player": self.players[self.current_player_idx] if self.state == GameState.PLAYING else None,
        }
