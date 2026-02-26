"""
Core Belot game state and logic (Moldova / belot.md rules)

Supports 3-player and 4-player modes.

4-player: 2 fixed teams (0+2 vs 1+3), 8 cards each, 8 tricks
3-player: dynamic teams — taker (alone) vs other two, 10 cards each, 10 tricks
  - Deal 10 cards each (30 total), 2 extra go to taker after bidding
  - Taker must discard 2 cards before declarations
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
    DISCARDING = "discarding"     # 3-player only: taker picks 2 cards to discard
    DECLARATIONS = "declarations"
    PLAYING = "playing"
    ROUND_END = "round_end"
    GAME_END = "game_end"


class BelotGame:
    def __init__(self, game_id: str, max_players: int = 4):
        self.game_id = game_id
        self.max_players = max_players   # 3 or 4
        self.players = []
        self.player_names = {}
        self.state = GameState.WAITING

        self.scores = [0, 0]
        self.round_scores = [0, 0]

        self.hands = {}
        self.deck = None

        # Bidding
        self.proposed_card = None
        self.trump_suit = None
        self.bidding_round = 1
        self.current_bidder_idx = 0
        self.taker_idx = None
        self.auto_trump = False

        # 3-player: extra cards for taker
        self.extra_cards = []          # 2 cards dealt to taker in 3p mode

        # Declarations
        self.all_declarations = {}
        self.declaration_scores = [0, 0]
        self.declarations_done = set()
        self.belot_announced = {}
        self.belot_score_given = {}

        # Tricks
        self.current_trick = []
        self.trick_winner_idx = None
        self.tricks_won = [0, 0]
        self.tricks_history = []
        self.current_player_idx = 0

        # Special rules
        self.eight_eight_eight_eight = False
        self.seven_seven_seven_seven = False

        self.round_num = 0
        self.dealer_idx = 0

    @property
    def num_players(self):
        return len(self.players)

    @property
    def total_tricks(self):
        """Number of tricks in a round."""
        return 10 if self.max_players == 3 else 8

    def team_of(self, player_id) -> int:
        """
        4-player: teams are fixed (positions 0+2 vs 1+3).
        3-player: taker = team 0, others = team 1. Dynamic after bidding.
        """
        idx = self.players.index(player_id)
        return self.team_of_idx(idx)

    def team_of_idx(self, idx) -> int:
        if self.max_players == 4:
            return idx % 2
        # 3-player: taker_idx is team 0
        if self.taker_idx is None:
            return idx % 2   # fallback before bidding resolved
        return 0 if idx == self.taker_idx else 1

    def partner_of(self, player_id):
        """4-player only."""
        idx = self.players.index(player_id)
        return self.players[(idx + 2) % 4]

    def add_player(self, player_id: int, name: str) -> bool:
        if player_id in self.players or len(self.players) >= self.max_players:
            return False
        self.players.append(player_id)
        self.player_names[player_id] = name
        return True

    def is_full(self) -> bool:
        return len(self.players) == self.max_players

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
        self.extra_cards = []

        self.deck = Deck()
        self.deck.shuffle()
        self.hands = {}

        if self.max_players == 3:
            # Deal 10 cards each, 2 extra stay in deck for taker
            for p in self.players:
                self.hands[p] = self.deck.deal(10)
            # Store 2 extra cards (will go to taker after bidding)
            self.extra_cards = self.deck.deal(2)
        else:
            # 4-player: deal 5 cards each
            for p in self.players:
                self.hands[p] = self.deck.deal(5)

        self.proposed_card = self.deck.top_card()
        self.current_bidder_idx = (self.dealer_idx + 1) % self.max_players

        # Special rule: Valet flipped → auto take
        if self.proposed_card and self.proposed_card.rank == Rank.JACK:
            self.auto_trump = True
            self.trump_suit = self.proposed_card.suit
            self.taker_idx = self.current_bidder_idx
            if self.max_players == 4:
                self._deal_remaining_4p()
                self.state = GameState.DECLARATIONS
            else:
                # 3p: taker gets extra cards, must discard
                taker_id = self.players[self.taker_idx]
                self.hands[taker_id].extend(self.extra_cards)
                self.extra_cards = []
                self.state = GameState.DISCARDING
            self.current_player_idx = (self.dealer_idx + 1) % self.max_players

    def bid_take(self, player_id: int, suit: Suit = None) -> dict:
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

        if self.max_players == 4:
            self._deal_remaining_4p()
            self.state = GameState.DECLARATIONS
        else:
            # 3-player: give taker the 2 extra cards, then they discard 2
            taker_id = self.players[self.taker_idx]
            self.hands[taker_id].extend(self.extra_cards)
            self.extra_cards = []
            self.state = GameState.DISCARDING

        self.current_player_idx = (self.dealer_idx + 1) % self.max_players
        return {"ok": True, "trump": self.trump_suit}

    def bid_pass(self, player_id: int) -> dict:
        player_idx = self.players.index(player_id)
        if player_idx != self.current_bidder_idx:
            return {"ok": False, "error": "Not your turn to bid"}

        next_idx = (self.current_bidder_idx + 1) % self.max_players

        if next_idx == (self.dealer_idx + 1) % self.max_players:
            if self.bidding_round == 1:
                self.bidding_round = 2
                self.current_bidder_idx = (self.dealer_idx + 1) % self.max_players
                return {"ok": True, "round2": True}
            else:
                self.dealer_idx = (self.dealer_idx + 1) % self.max_players
                return {"ok": True, "redeal": True}
        else:
            self.current_bidder_idx = next_idx
            return {"ok": True}

    def discard_cards(self, player_id: int, indices: list) -> dict:
        """3-player only: taker discards exactly 2 cards."""
        if self.state != GameState.DISCARDING:
            return {"ok": False, "error": "Not in discarding phase"}
        taker_id = self.players[self.taker_idx]
        if player_id != taker_id:
            return {"ok": False, "error": "Only the taker discards"}
        if len(indices) != 2:
            return {"ok": False, "error": "Must discard exactly 2 cards"}

        hand = self.hands[player_id]
        if any(i >= len(hand) for i in indices):
            return {"ok": False, "error": "Invalid card index"}

        # Remove by index (highest first to not shift)
        for i in sorted(set(indices), reverse=True):
            hand.pop(i)

        self.state = GameState.DECLARATIONS
        return {"ok": True}

    def _deal_remaining_4p(self):
        """Deal 3 more cards to each player (4-player mode)."""
        for p in self.players:
            self.hands[p].extend(self.deck.deal(3))

    def submit_declarations(self, player_id: int) -> dict:
        if player_id in self.declarations_done:
            return {"ok": False, "error": "Already submitted"}

        decls = get_all_declarations(self.hands[player_id], self.trump_suit)

        if has_8888(self.hands[player_id]):
            self.eight_eight_eight_eight = True
        if has_7777(self.hands[player_id]):
            self.seven_seven_seven_seven = True

        self.all_declarations[player_id] = decls
        self.declarations_done.add(player_id)
        self.belot_announced[player_id] = check_belot(self.hands[player_id], self.trump_suit)

        if len(self.declarations_done) == self.max_players:
            self._resolve_declarations()
            self.state = GameState.PLAYING
            return {"ok": True, "all_done": True, "scores": self.declaration_scores}

        return {"ok": True, "waiting": self.max_players - len(self.declarations_done)}

    def _resolve_declarations(self):
        if self.eight_eight_eight_eight:
            for pid in self.players:
                self.all_declarations[pid] = [
                    d for d in self.all_declarations.get(pid, [])
                    if d['type'] == 'belot'
                ]

        decls_list = [(self.players.index(pid), decls)
                      for pid, decls in self.all_declarations.items() if decls]

        if decls_list:
            best_player_idx = compare_declarations(decls_list)
            winning_team = self.team_of_idx(best_player_idx)
            for pid in self.players:
                pidx = self.players.index(pid)
                if self.team_of_idx(pidx) == winning_team:
                    for d in self.all_declarations.get(pid, []):
                        self.declaration_scores[winning_team] += d['score']

        for pid in self.players:
            self.belot_score_given[pid] = False

    def get_valid_cards(self, player_id: int) -> list:
        hand = self.hands[player_id]
        if not self.current_trick:
            return hand[:]

        lead_card = self.current_trick[0][1]
        lead_suit = lead_card.suit
        trump = self.trump_suit

        winning_card = self.current_trick[0][1]
        winning_player_idx = self.players.index(self.current_trick[0][0])
        for pid, card in self.current_trick[1:]:
            if card.beats(winning_card, trump, lead_suit):
                winning_card = card
                winning_player_idx = self.players.index(pid)

        player_idx = self.players.index(player_id)
        partner_winning = (winning_player_idx % 2 == player_idx % 2) if self.max_players == 4 else \
                          (self.team_of_idx(winning_player_idx) == self.team_of_idx(player_idx))

        lead_cards = [c for c in hand if c.suit == lead_suit]
        trump_cards = [c for c in hand if c.suit == trump]

        if lead_cards:
            if lead_suit == trump:
                higher = [c for c in lead_cards if c.trump_order() > winning_card.trump_order()]
                return higher if higher else lead_cards
            return lead_cards

        if partner_winning:
            return hand[:]

        if trump_cards:
            if winning_card.suit == trump:
                higher = [c for c in trump_cards if c.trump_order() > winning_card.trump_order()]
                return higher if higher else trump_cards
            return trump_cards

        return hand[:]

    def play_card(self, player_id: int, card: Card) -> dict:
        if self.state != GameState.PLAYING:
            return {"ok": False, "error": "Not in playing phase"}

        player_idx = self.players.index(player_id)
        if player_idx != self.current_player_idx:
            return {"ok": False, "error": "Not your turn"}

        valid = self.get_valid_cards(player_id)
        if card not in valid:
            return {"ok": False, "error": "Invalid card (rule violation)"}

        if self.belot_announced.get(player_id) and not self.belot_score_given.get(player_id):
            if card.suit == self.trump_suit and card.rank in (Rank.KING, Rank.QUEEN):
                team = self.team_of(player_id)
                self.declaration_scores[team] += 20
                self.belot_score_given[player_id] = True

        self.hands[player_id].remove(card)
        self.current_trick.append((player_id, card))

        result = {"ok": True, "card": card}

        if len(self.current_trick) == self.max_players:
            result.update(self._resolve_trick())
        else:
            self.current_player_idx = (self.current_player_idx + 1) % self.max_players

        return result

    def _resolve_trick(self) -> dict:
        lead_suit = self.current_trick[0][1].suit
        trump = self.trump_suit

        best_pid, best_card = self.current_trick[0]
        for pid, card in self.current_trick[1:]:
            if card.beats(best_card, trump, lead_suit):
                best_card = card
                best_pid = pid

        winner_idx = self.players.index(best_pid)
        winning_team = self.team_of_idx(winner_idx)
        self.tricks_won[winning_team] += 1

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

        if sum(self.tricks_won) == self.total_tricks:
            result.update(self._end_round())

        return result

    def _end_round(self) -> dict:
        self.state = GameState.ROUND_END
        trump = self.trump_suit

        last_winner = self.tricks_history[-1]["winner"]
        last_team = self.team_of(last_winner)
        self.round_scores[last_team] += 10

        for team in [0, 1]:
            if self.tricks_won[team] == self.total_tricks:
                self.round_scores[team] += 90

        for team in [0, 1]:
            self.round_scores[team] += self.declaration_scores[team]

        if self.seven_seven_seven_seven:
            self.dealer_idx = (self.dealer_idx + 1) % self.max_players
            return {"round_cancelled": True, "reason": "7777 — четыре семёрки!"}

        taker_team = self.taker_idx % 2 if self.max_players == 4 else 0
        opponent_team = 1 - taker_team

        taker_pts = self.round_scores[taker_team]
        opp_pts = self.round_scores[opponent_team]

        outcome = ""
        if taker_pts > opp_pts:
            self.scores[taker_team] += taker_pts
            self.scores[opponent_team] += opp_pts
            outcome = "taker_wins"
        elif taker_pts == opp_pts:
            self.scores[opponent_team] += opp_pts
            outcome = "tie"
        else:
            total = taker_pts + opp_pts
            self.scores[opponent_team] += total
            outcome = "taker_failed"

        self.dealer_idx = (self.dealer_idx + 1) % self.max_players

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
            "max_players": self.max_players,
            "current_player": self.players[self.current_player_idx] if self.state == GameState.PLAYING else None,
        }
