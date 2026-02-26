"""
Card image renderer for Belot bot.
Generates a hand image showing all cards with valid ones highlighted.
"""
from PIL import Image, ImageDraw, ImageFont
import io
import os

# Card dimensions
CARD_W = 80
CARD_H = 120
CARD_RADIUS = 10
GAP = 6           # gap between cards
PADDING = 12      # outer padding
TRUMP_GLOW = 4    # border thickness for trump cards

# Colors
WHITE = (255, 255, 255)
BLACK = (20, 20, 20)
RED = (210, 30, 30)
DARK_RED = (160, 20, 20)
GRAY_BG = (180, 180, 185)
GRAY_TEXT = (120, 120, 120)
GOLD = (220, 170, 0)
GOLD_LIGHT = (255, 215, 60)
BLUE_TINT = (230, 240, 255)
DIM_OVERLAY = (200, 200, 200, 160)   # RGBA semi-transparent for invalid cards
SHADOW = (0, 0, 0, 60)

# Suit colors
SUIT_COLORS = {
    "♣": BLACK,
    "♦": RED,
    "♥": RED,
    "♠": BLACK,
}

FONT_PATH_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Full rank display names for center of card
RANK_CENTER = {
    "7": "7", "8": "8", "9": "9", "10": "10",
    "J": "В", "Q": "Д", "K": "К", "A": "Т",
}

# Large suit symbols for center
SUIT_BIG = {
    "♣": "♣", "♦": "♦", "♥": "♥", "♠": "♠",
}


def load_fonts():
    try:
        f_big = ImageFont.truetype(FONT_PATH_BOLD, 28)
        f_rank = ImageFont.truetype(FONT_PATH_BOLD, 22)
        f_suit = ImageFont.truetype(FONT_PATH, 26)
        f_small = ImageFont.truetype(FONT_PATH_BOLD, 16)
        f_tiny = ImageFont.truetype(FONT_PATH, 13)
        f_label = ImageFont.truetype(FONT_PATH_BOLD, 15)
    except Exception:
        f_big = f_rank = f_suit = f_small = f_tiny = f_label = ImageFont.load_default()
    return f_big, f_rank, f_suit, f_small, f_tiny, f_label


def rounded_rectangle(draw, xy, radius, fill, outline=None, outline_width=2):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill,
                            outline=outline, width=outline_width)


def draw_single_card(rank_str: str, suit_str: str, is_trump: bool,
                     is_valid: bool, fonts) -> Image.Image:
    """Draw a single playing card and return as Image."""
    f_big, f_rank, f_suit, f_small, f_tiny, f_label = fonts

    # Create card with transparent background
    img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    suit_color = SUIT_COLORS.get(suit_str, BLACK)

    # Shadow
    shadow_img = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_img)
    rounded_rectangle(shadow_draw, [3, 3, CARD_W - 1, CARD_H - 1],
                       CARD_RADIUS, fill=(0, 0, 0, 50))
    img = Image.alpha_composite(img, shadow_img)
    draw = ImageDraw.Draw(img)

    # Card background
    if not is_valid:
        bg_color = (210, 210, 210)
    elif is_trump:
        bg_color = (255, 252, 235)  # warm cream for trump
    else:
        bg_color = WHITE

    rounded_rectangle(draw, [0, 0, CARD_W - 3, CARD_H - 3],
                       CARD_RADIUS, fill=bg_color,
                       outline=GOLD if is_trump else (180, 180, 180),
                       outline_width=3 if is_trump else 1)

    # Trump glow border (inner)
    if is_trump and is_valid:
        rounded_rectangle(draw, [3, 3, CARD_W - 6, CARD_H - 6],
                           CARD_RADIUS - 2, fill=None,
                           outline=GOLD_LIGHT, outline_width=1)

    text_color = suit_color if is_valid else (160, 160, 160)

    # Top-left rank + suit
    rank_display = RANK_CENTER.get(rank_str, rank_str)
    draw.text((6, 4), rank_display, font=f_small, fill=text_color)
    draw.text((6, 22), suit_str, font=f_tiny, fill=text_color)

    # Bottom-right rank + suit (rotated 180°)
    # We'll just draw it flipped manually
    br_rank = rank_display
    br_suit = suit_str
    # measure text
    bbox_r = draw.textbbox((0, 0), br_rank, font=f_small)
    bbox_s = draw.textbbox((0, 0), br_suit, font=f_tiny)
    r_w = bbox_r[2] - bbox_r[0]
    s_w = bbox_s[2] - bbox_s[0]
    draw.text((CARD_W - 4 - r_w - 3, CARD_H - 4 - 32), br_rank, font=f_small, fill=text_color)
    draw.text((CARD_W - 4 - s_w - 3, CARD_H - 4 - 17), br_suit, font=f_tiny, fill=text_color)

    # Center: big suit symbol
    center_suit = suit_str
    bbox_cs = draw.textbbox((0, 0), center_suit, font=f_suit)
    cs_w = bbox_cs[2] - bbox_cs[0]
    cs_h = bbox_cs[3] - bbox_cs[1]

    center_rank = rank_display
    bbox_cr = draw.textbbox((0, 0), center_rank, font=f_rank)
    cr_w = bbox_cr[2] - bbox_cr[0]

    total_h = cs_h + 4 + (bbox_cr[3] - bbox_cr[1])
    start_y = (CARD_H - 3 - total_h) // 2

    draw.text(((CARD_W - 3 - cs_w) // 2, start_y), center_suit,
              font=f_suit, fill=text_color)
    draw.text(((CARD_W - 3 - cr_w) // 2, start_y + cs_h + 4), center_rank,
              font=f_rank, fill=text_color)

    # Trump star indicator
    if is_trump and is_valid:
        draw.text((CARD_W - 18, 4), "★", font=f_tiny, fill=GOLD)

    # Dimming overlay for invalid cards
    if not is_valid:
        overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        rounded_rectangle(ov_draw, [0, 0, CARD_W - 3, CARD_H - 3],
                           CARD_RADIUS, fill=(150, 150, 150, 80))
        img = Image.alpha_composite(img, overlay)

    return img


def render_hand(cards_data: list, label: str = "") -> io.BytesIO:
    """
    Render a hand of cards as an image.
    cards_data: list of (rank_str, suit_str, is_trump, is_valid)
    Returns BytesIO PNG.
    """
    fonts = load_fonts()
    n = len(cards_data)
    if n == 0:
        n = 1

    label_h = 30 if label else 0
    img_w = PADDING * 2 + n * CARD_W + (n - 1) * GAP
    img_h = PADDING * 2 + CARD_H + label_h + 4

    # Background gradient-ish
    bg = Image.new("RGBA", (img_w, img_h), (45, 95, 55, 255))  # dark green felt
    draw_bg = ImageDraw.Draw(bg)

    # Subtle felt texture lines
    for y in range(0, img_h, 8):
        draw_bg.line([(0, y), (img_w, y)], fill=(50, 100, 60, 40), width=1)

    f_big, f_rank, f_suit, f_small, f_tiny, f_label = fonts

    # Label at top
    if label:
        label_bbox = draw_bg.textbbox((0, 0), label, font=f_label)
        lw = label_bbox[2] - label_bbox[0]
        draw_bg.text(((img_w - lw) // 2, 8), label,
                     font=f_label, fill=(220, 220, 200))

    # Draw each card
    for i, (rank_str, suit_str, is_trump, is_valid) in enumerate(cards_data):
        card_img = draw_single_card(rank_str, suit_str, is_trump, is_valid, fonts)
        x = PADDING + i * (CARD_W + GAP)
        y = PADDING + label_h
        bg.paste(card_img, (x, y), card_img)

    # Convert to bytes
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_trick(cards_data: list, player_labels: list) -> io.BytesIO:
    """
    Render cards on the table (current trick).
    cards_data: list of (rank_str, suit_str, is_trump)
    player_labels: list of player names matching cards_data
    """
    fonts = load_fonts()
    f_big, f_rank, f_suit, f_small, f_tiny, f_label = fonts

    n = len(cards_data)
    if n == 0:
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), (45, 95, 55)).save(buf, "PNG")
        buf.seek(0)
        return buf

    name_h = 20
    img_w = PADDING * 2 + n * CARD_W + (n - 1) * GAP
    img_h = PADDING * 2 + CARD_H + name_h + 10

    bg = Image.new("RGBA", (img_w, img_h), (40, 85, 50, 255))
    draw_bg = ImageDraw.Draw(bg)

    # Title
    title = "🃏 На столе:"
    draw_bg.text((PADDING, 6), "На столе:", font=f_label, fill=(220, 220, 180))

    for i, (rank_str, suit_str, is_trump) in enumerate(cards_data):
        card_img = draw_single_card(rank_str, suit_str, is_trump, True, fonts)
        x = PADDING + i * (CARD_W + GAP)
        y = PADDING + name_h
        bg.paste(card_img, (x, y), card_img)

        # Player name below card
        name = player_labels[i] if i < len(player_labels) else ""
        name_bbox = draw_bg.textbbox((0, 0), name, font=f_tiny)
        nw = name_bbox[2] - name_bbox[0]
        draw_bg.text((x + (CARD_W - nw) // 2, y + CARD_H + 3),
                     name, font=f_tiny, fill=(200, 220, 200))

    buf = io.BytesIO()
    bg.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def cards_to_render_data(hand, valid_cards, trump_suit):
    """Convert game Card objects to render tuples."""
    data = []
    for card in hand:
        is_trump = (card.suit == trump_suit)
        is_valid = (valid_cards is None or card in valid_cards)
        data.append((card.rank.value, card.suit.value, is_trump, is_valid))
    return data


def trick_to_render_data(trick, trump_suit, player_names):
    """Convert current trick to render tuples."""
    cards_data = []
    labels = []
    for pid, card in trick:
        is_trump = (card.suit == trump_suit)
        cards_data.append((card.rank.value, card.suit.value, is_trump))
        labels.append(player_names.get(pid, "?"))
    return cards_data, labels
