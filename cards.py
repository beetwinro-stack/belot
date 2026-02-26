"""
Cards and Deck for Belot (Moldova rules)
32-card deck: 7, 8, 9, 10, J, Q, K, A in 4 suits
"""
import random
from enum import Enum


class Suit(Enum):
    CLUBS = "♣"
    DIAMONDS = "♦"
    HEARTS = "♥"
    SPADES = "♠"


class Rank(Enum):
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"


# Points for non-trump cards
NON_TRUMP_POINTS = {
    Rank.SEVEN: 0,
    Rank.EIGHT: 0,
    Rank.NINE: 0,
    Rank.TEN: 10,
    Rank.JACK: 2,
    Rank.QUEEN: 3,
    Rank.KING: 4,
    Rank.ACE: 11,
}

# Points for trump cards (J and 9 change value)
TRUMP_POINTS = {
    Rank.SEVEN: 0,
    Rank.EIGHT: 0,
    Rank.NINE: 14,   # "Manele" - 14 points
    Rank.TEN: 10,
    Rank.JACK: 20,   # Highest trump
    Rank.QUEEN: 3,
    Rank.KING: 4,
    Rank.ACE: 11,
}

# Rank order for non-trump (higher index = stronger)
NON_TRUMP_ORDER = [
    Rank.SEVEN, Rank.EIGHT, Rank.NINE,
    Rank.JACK, Rank.QUEEN, Rank.KING, Rank.TEN, Rank.ACE
]

# Rank order for trump
TRUMP_ORDER = [
    Rank.SEVEN, Rank.EIGHT, Rank.QUEEN,
    Rank.KING, Rank.TEN, Rank.ACE, Rank.NINE, Rank.JACK
]


class Card:
    def __init__(self, suit: Suit, rank: Rank):
        self.suit = suit
        self.rank = rank

    def points(self, trump_suit: Suit) -> int:
        if self.suit == trump_suit:
            return TRUMP_POINTS[self.rank]
        return NON_TRUMP_POINTS[self.rank]

    def trump_order(self) -> int:
        return TRUMP_ORDER.index(self.rank)

    def non_trump_order(self) -> int:
        return NON_TRUMP_ORDER.index(self.rank)

    def beats(self, other: 'Card', trump_suit: Suit, lead_suit: Suit) -> bool:
        """Does this card beat the other card?"""
        # Trump beats non-trump
        if self.suit == trump_suit and other.suit != trump_suit:
            return True
        if self.suit != trump_suit and other.suit == trump_suit:
            return False
        # Both trump
        if self.suit == trump_suit and other.suit == trump_suit:
            return self.trump_order() > other.trump_order()
        # Both non-trump
        if self.suit == lead_suit and other.suit != lead_suit:
            return True
        if self.suit != lead_suit and other.suit == lead_suit:
            return False
        if self.suit == other.suit:
            return self.non_trump_order() > other.non_trump_order()
        return False

    def emoji(self) -> str:
        return f"{self.rank.value}{self.suit.value}"

    def __repr__(self):
        return self.emoji()

    def __eq__(self, other):
        return isinstance(other, Card) and self.suit == other.suit and self.rank == other.rank

    def __hash__(self):
        return hash((self.suit, self.rank))


class Deck:
    def __init__(self):
        self.cards = [Card(suit, rank) for suit in Suit for rank in Rank]

    def shuffle(self):
        random.shuffle(self.cards)

    def deal(self, num: int) -> list:
        hand = self.cards[:num]
        self.cards = self.cards[num:]
        return hand

    def top_card(self) -> Card:
        return self.cards[0] if self.cards else None
