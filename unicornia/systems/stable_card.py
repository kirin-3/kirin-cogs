"""Draws the stable card: the stable background, the coin box and up to ten unicorn tiles. Blocking; run it
in a thread."""

from __future__ import annotations

import functools
import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .stable_system import BREEDS, MAX_LEVEL, MAX_UNICORNS, REGULAR_BREEDS, StableState

ART = Path(__file__).resolve().parent.parent / "data" / "stable"
WIDTH, HEIGHT = 1000, 600
TILE_W, TILE_H, GAP, TOP = 176, 204, 16, 136
LEFT = (WIDTH - 5 * TILE_W - 4 * GAP) // 2
SPRITE = 150
INK = (58, 40, 52)
MUTED = (120, 100, 112)
PANEL = (255, 250, 252, 225)
GOLD = (255, 200, 60)
FONTS = {
    True: (
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ),
    False: (
        "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "arial.ttf",
    ),
}


@functools.cache
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS[bold]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


@functools.cache
def _image(name: str, size: tuple[int, int]) -> Image.Image:
    return Image.open(ART / f"{name}.webp").convert("RGBA").resize(size, Image.Resampling.LANCZOS)


@functools.cache
def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def _fit(
    draw: ImageDraw.ImageDraw, text: str, size: int, width: int, bold: bool = False
) -> tuple[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """The text in the biggest font up to `size` that fits `width`, shortened with … if even 12px doesn't."""
    for px in range(size, 11, -1):
        if draw.textlength(text, font=font(px, bold)) <= width:
            return text, font(px, bold)
    small = font(12, bold)
    while text and draw.textlength(text + "…", font=small) > width:
        text = text[:-1]
    return text + "…", small


def _duration(hours: float) -> str:
    minutes = max(1, round(hours * 60))
    return f"{minutes // 60}h {minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def _star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color) -> None:
    """A four-point star: the sparkle on shiny tiles and the ascension mark in the header."""
    points = []
    for i in range(8):
        angle = i * math.pi / 4
        radius = r if i % 2 == 0 else r * 0.38
        points.append((cx + radius * math.sin(angle), cy - radius * math.cos(angle)))
    draw.polygon(points, fill=color)


def render(state: StableState, owner: str, season: str | None = None) -> io.BytesIO:
    card = _image("background", (WIDTH, HEIGHT)).copy()
    overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Header: owner and earnings on the left, the coin box on the right
    draw.rounded_rectangle((LEFT, 18, WIDTH - LEFT, 118), 18, fill=PANEL)
    title, title_font = _fit(draw, f"{owner}'s Stable", 34, 500, bold=True)
    draw.text((LEFT + 22, 24), title, font=title_font, fill=INK)
    draw.text(
        (LEFT + 22, 64),
        f"{state.per_day:,.0f} a day  ·  {len(state.unicorns)}/{MAX_UNICORNS} unicorns",
        font=font(20),
        fill=MUTED,
    )
    found = f"{state.found}/{len(REGULAR_BREEDS)} breeds found"
    if season is not None:
        found += f"  ·  {BREEDS[season].name} season"
    if state.ascensions:
        _star(draw, LEFT + 29, 101, 8, GOLD)
        count = f"{state.ascensions} ascension{'' if state.ascensions == 1 else 's'}"
        draw.text((LEFT + 42, 92), f"{count}  ·  {found}", font=font(16), fill=MUTED)
    else:
        draw.text((LEFT + 22, 92), found, font=font(16), fill=MUTED)

    bar_x, bar_y, bar_w, bar_h = WIDTH - LEFT - 22 - 330, 58, 330, 24
    draw.text((bar_x, 28), "Coin box", font=font(18, bold=True), fill=INK)
    capacity = state.capacity
    fill = 0.0 if capacity <= 0 else min(state.box / capacity, 1.0)
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), 12, fill=(235, 220, 228, 255))
    if fill > 0:
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + max(int(bar_w * fill), bar_h), bar_y + bar_h), 12, fill=(236, 112, 170, 255)
        )
    amount = f"{int(state.box):,} / {int(capacity):,}"
    draw.text((bar_x + bar_w / 2, bar_y + bar_h / 2), amount, font=font(15, bold=True), fill=INK, anchor="mm")
    if state.per_day <= 0:
        status = "Hatch an egg to start earning"
    elif fill >= 1:
        status = "Full! Collect to keep earning"
    else:
        status = f"Full in {_duration((capacity - state.box) / state.per_day * 24)}  ·  holds {state.box_hours}h"
    draw.text((bar_x + bar_w, 90), status, font=font(15), fill=MUTED, anchor="ra")

    # Tiles, five to a row
    for slot in range(MAX_UNICORNS):
        x = LEFT + (slot % 5) * (TILE_W + GAP)
        y = TOP + (slot // 5) * (TILE_H + GAP)
        if slot >= len(state.unicorns):
            draw.rounded_rectangle((x, y, x + TILE_W, y + TILE_H), 16, fill=(60, 30, 50, 110))
            draw.text((x + TILE_W / 2, y + 88), "+", font=font(54, bold=True), fill=(255, 255, 255, 230), anchor="mm")
            draw.text((x + TILE_W / 2, y + 150), "Empty stall", font=font(16), fill=(255, 255, 255, 240), anchor="mm")
            continue
        unicorn = state.unicorns[slot]
        color = unicorn.rarity.color  # the frame shows the rarity; seasonal breeds have their own colour
        sprite_xy = (x + (TILE_W - SPRITE) // 2, y + 10)
        if unicorn.shiny:
            # A soft gold glow behind the sprite, then the gold frame, sparkles and the star badge
            glow = Image.new("RGBA", (TILE_W + 24, TILE_H + 24), (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle((12, 6, TILE_W + 12, SPRITE + 30), 24, fill=(*GOLD, 190))
            overlay.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9)), (x - 12, y - 12))
            draw.rounded_rectangle((x, y, x + TILE_W, y + TILE_H), 16, fill=PANEL, outline=(*GOLD, 255), width=5)
        else:
            draw.rounded_rectangle((x, y, x + TILE_W, y + TILE_H), 16, fill=PANEL, outline=(*color, 255), width=4)
        overlay.paste(_image(unicorn.breed, (SPRITE, SPRITE)), sprite_xy, _rounded_mask((SPRITE, SPRITE), 12))
        if unicorn.shiny:
            for dx, dy, r in ((8, 16, 7), (SPRITE - 8, 30, 5), (16, SPRITE - 8, 5), (SPRITE - 26, 10, 4)):
                _star(draw, sprite_xy[0] + dx, sprite_xy[1] + dy, r, (255, 240, 190, 255))
            draw.rounded_rectangle((x + TILE_W - 40, y + 8, x + TILE_W - 8, y + 32), 8, fill=(*GOLD, 245))
            _star(draw, x + TILE_W - 24, y + 20, 9, "white")
        draw.rounded_rectangle((x + 8, y + 8, x + 40, y + 30), 8, fill=(*color, 235))
        draw.text((x + 24, y + 19), f"#{slot + 1}", font=font(14, bold=True), fill="white", anchor="mm")
        name, name_font = _fit(draw, unicorn.label, 18, TILE_W - 16, bold=True)
        draw.text((x + TILE_W / 2, y + 172), name, font=name_font, fill=INK, anchor="mm")
        level = "MAX" if unicorn.level >= MAX_LEVEL else str(unicorn.level)
        # A renamed unicorn shows its breed instead of its rarity; the frame still shows the rarity
        kind = BREEDS[unicorn.breed].name if unicorn.name else unicorn.rarity.name
        dark = tuple(int(c * 0.7) for c in color)
        draw.text((x + TILE_W / 2, y + 192), f"Lv {level}  ·  {kind}", font=font(13, bold=True), fill=dark, anchor="mm")

    card.alpha_composite(overlay)
    buffer = io.BytesIO()
    card.convert("RGB").save(buffer, "WEBP", quality=90)
    buffer.seek(0)
    return buffer
