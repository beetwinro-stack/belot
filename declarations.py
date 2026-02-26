"""
Declarations (combinations) for Belot Moldova rules
- Sequence (терц): 3+ consecutive cards in same suit = 20/50/100/150/200pts
- Four of a kind (каре): 4 cards same rank = 100/150/200pts
- Belot: K+Q of trump = 20pts (announced during play)

8888 (four 8s) cancels all declarations except Belot and 7777
7777 (four 7s) cancels the round
"""
from cards import Card, Suit, Rank, NON_TRUMP_ORDER, TRUMP_ORDER


# Sequence order for declarations (7 to A, no special trump order)
DECL_ORDER = [Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.TEN,
              Rank.JACK, Rank.QUEEN, Rank.KING, Rank.ACE]


def find_sequences(hand: list, trump_suit: Suit) -> list:
    """Find all sequences (терц, 50, 100, 150, 200) in hand."""
    declarations = []
    
    # Group by suit
    by_suit = {suit: [] for suit in Suit}
    for card in hand:
        by_suit[card.suit].append(card)
    
    for suit, cards in by_suit.items():
        if len(cards) < 3:
            continue
        # Sort by declaration order
        ranks = sorted([DECL_ORDER.index(c.rank) for c in cards])
        
        # Find consecutive sequences
        i = 0
        while i < len(ranks):
            j = i + 1
            while j < len(ranks) and ranks[j] == ranks[j-1] + 1:
                j += 1
            length = j - i
            if length >= 3:
                # Get the highest rank in sequence
                top_rank = DECL_ORDER[ranks[j-1]]
                score = seq_score(length)
                declarations.append({
                    'type': 'sequence',
                    'length': length,
                    'top_rank': top_rank,
                    'suit': suit,
                    'score': score,
                    'is_trump': suit == trump_suit,
                    'name': seq_name(length),
                })
            i = j
    
    return declarations


def seq_score(length: int) -> int:
    if length == 3: return 20
    if length == 4: return 50
    if length == 5: return 100
    if length == 6: return 150
    if length == 7: return 200  # (rare)
    if length >= 8: return 500
    return 0


def seq_name(length: int) -> str:
    if length == 3: return "Терц (20)"
    if length == 4: return "Cinquante (50)"
    if length == 5: return "Сто (100)"
    if length >= 6: return f"Sekvens-{length}"
    return ""


def find_four_of_kind(hand: list) -> list:
    """Find four of a kind declarations."""
    declarations = []
    by_rank = {}
    for card in hand:
        by_rank.setdefault(card.rank, []).append(card)
    
    for rank, cards in by_rank.items():
        if len(cards) == 4:
            score = four_score(rank)
            if score > 0:
                declarations.append({
                    'type': 'four',
                    'rank': rank,
                    'score': score,
                    'name': f"Каре {rank.value} ({score})",
                })
    
    return declarations


def four_score(rank: Rank) -> int:
    scores = {
        Rank.ACE: 100,
        Rank.KING: 100,
        Rank.QUEEN: 100,
        Rank.JACK: 200,
        Rank.TEN: 100,
        Rank.NINE: 150,
        Rank.EIGHT: 0,   # 8888 cancels all (special rule)
        Rank.SEVEN: 0,   # 7777 cancels round (special rule)
    }
    return scores.get(rank, 0)


def get_all_declarations(hand: list, trump_suit: Suit) -> list:
    """Get all declarations for a hand."""
    decls = []
    decls.extend(find_sequences(hand, trump_suit))
    decls.extend(find_four_of_kind(hand))
    return decls


def has_8888(hand: list) -> bool:
    by_rank = {}
    for card in hand:
        by_rank.setdefault(card.rank, 0)
        by_rank[card.rank] += 1
    return by_rank.get(Rank.EIGHT, 0) == 4


def has_7777(hand: list) -> bool:
    by_rank = {}
    for card in hand:
        by_rank.setdefault(card.rank, 0)
        by_rank[card.rank] += 1
    return by_rank.get(Rank.SEVEN, 0) == 4


def compare_declarations(decls_list: list) -> tuple:
    """
    Given list of (player_idx, declarations) pairs,
    determine which team's declarations count.
    Returns winning_decls_by_player dict and total scores.
    
    Rules:
    - Four of kind > Sequence
    - Longer sequence > shorter
    - Higher top card > lower
    - Trump sequences beat same-length/same-top non-trump
    """
    # Flatten with player info
    all_decls = []
    for player_idx, decls in decls_list:
        for d in decls:
            d['player'] = player_idx
            all_decls.append(d)
    
    if not all_decls:
        return {}

    # Find the "best" declaration overall
    def decl_key(d):
        if d['type'] == 'four':
            return (2, d['score'], 0, 0)
        else:
            return (1, d['score'], DECL_ORDER.index(d['top_rank']), 1 if d['is_trump'] else 0)
    
    all_decls.sort(key=decl_key, reverse=True)
    best = all_decls[0]
    
    # All players with declarations of the same or lower value on losing team get 0
    # Winner's team gets all their declarations
    return best['player']


def check_belot(hand: list, trump_suit: Suit) -> bool:
    """Check if player has K+Q of trump (Belot combination)."""
    has_king = any(c.suit == trump_suit and c.rank == Rank.KING for c in hand)
    has_queen = any(c.suit == trump_suit and c.rank == Rank.QUEEN for c in hand)
    return has_king and has_queen
