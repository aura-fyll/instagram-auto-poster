"""PIL frame renderer — every scene is a pixel-perfect 1080x1920 PNG.

Layout rules (clean-minimal design system):
  * strict 72px side margins, one 936px text column
  * content vertically balanced inside the 220–1580 safe zone
  * max 3 text blocks per frame, generous whitespace
  * one accent color, ink/muted grays only otherwise
  * rounded pills + code chips, no gradients, no emoji soup
  * shared footer row (handle left, EP counter right) anchors the bottom
"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import config as C

Image.MAX_IMAGE_PIXELS = None

# ---------------------------------------------------------------- helpers ---


@lru_cache(maxsize=32)
def font(key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(C.FONT_FILES[key]), size)


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont,
         max_w: int) -> list[str]:
    """Greedy word-wrap that never breaks a word mid-syllable."""
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=f) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


def draw_text_block(draw, xy: tuple[int, int], text: str, key: str, size: int,
                    color: tuple, leading: float = 1.16,
                    max_w: int = None) -> int:
    """Draw wrapped text; returns the y coordinate BELOW the block."""
    x, y = xy
    max_w = max_w or C.CONTENT_W
    f = font(key, size)
    lh = int(size * leading)
    for line in wrap(draw, text, f, max_w):
        draw.text((x, y), line, font=f, fill=color)
        y += lh
    return y


def pill(img: Image.Image, text: str, xy: tuple[int, int], fg: tuple,
         bg: tuple, key: str = "mono_sb", size: int = 26,
         pad_x: int = 26, pad_y: int = 13) -> tuple[int, int]:
    """Rounded pill with caps label. Returns (width, height) drawn."""
    draw = ImageDraw.Draw(img)
    f = font(key, size)
    tw = int(draw.textlength(text, font=f))
    asc, desc = f.getmetrics()
    th = asc + desc
    x, y = xy
    x2, y2 = x + tw + 2 * pad_x, y + th + 2 * pad_y
    draw.rounded_rectangle([x, y, x2, y2], radius=(y2 - y) // 2, fill=bg)
    draw.text((x + pad_x, y + pad_y - 1), text, font=f, fill=fg)
    return (x2 - x, y2 - y)


def code_chip(img: Image.Image, code: str, y: int) -> int:
    """Rounded gray chip with monospace code; auto-shrinks to fit 936px.
    Returns the y coordinate BELOW the chip."""
    draw = ImageDraw.Draw(img)
    size = 31
    while size >= 22:
        f = font("mono_m", size)
        lines = _wrap_code(draw, code, f, C.CONTENT_W - 2 * 34)
        if all(draw.textlength(ln, font=f) <= C.CONTENT_W - 2 * 34
               for ln in lines):
            break
        size -= 1
    pad_x, pad_y = 34, 26
    lh = int(size * 1.42)
    chip_h = 2 * pad_y + lh * len(lines)
    draw.rounded_rectangle(
        [C.MARGIN, y, C.MARGIN + C.CONTENT_W, y + chip_h],
        radius=22, fill=C.CARD,
    )
    ty = y + pad_y
    for ln in lines:
        draw.text((C.MARGIN + pad_x, ty), ln, font=f, fill=C.INK)
        ty += lh
    return y + chip_h


def _wrap_code(draw, text: str, f, max_w: int) -> list[str]:
    """Code wraps on separators, keeping syntax readable."""
    if draw.textlength(text, font=f) <= max_w:
        return [text]
    lines: list[str] = []
    cur = ""
    for tok in text.replace("(", " ( ").replace(")", " ) ").split():
        trial = f"{cur} {tok}".strip()
        if draw.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    return lines


def footer(img: Image.Image, handle: str, ep_n: int, ep_total: int) -> None:
    """Anchors the bottom of white frames: handle left, EP counter right."""
    draw = ImageDraw.Draw(img)
    f_l = font("regular", 30)
    f_r = font("mono_sb", 26)
    draw.text((C.MARGIN, 1560), handle, font=f_l, fill=C.MUTED)
    counter = f"EP {ep_n:02d} / {ep_total}"
    cw = draw.textlength(counter, font=f_r)
    draw.text((C.W - C.MARGIN - cw, 1564), counter, font=f_r, fill=C.MUTED)


def new_canvas(bg: tuple = C.BG) -> Image.Image:
    return Image.new("RGB", (C.W, C.H), bg)


# ----------------------------------------------------------------- frames ---


def hook_frame(episode: dict, brand_pill: str, handle: str,
               cover: bool = False) -> Image.Image:
    """Scene 1 — pill + big headline + accent bar, vertically balanced."""
    img = new_canvas()
    draw = ImageDraw.Draw(img)

    label = brand_pill if not cover else f"{brand_pill} · TIP {episode['n']:02d}"
    pill(img, label, (C.MARGIN, 440), C.ACCENT, C.ACCENT_TINT)

    y = 586
    y = draw_text_block(draw, (C.MARGIN, y), episode["hook"]["text"],
                        "display_xb", 96, C.INK, leading=1.08)
    draw.rounded_rectangle(
        [C.MARGIN, y + 44, C.MARGIN + 150, y + 58], radius=7, fill=C.ACCENT,
    )
    draw_text_block(draw, (C.MARGIN, y + 106), "One tip · every single day",
                    "medium", 40, C.MUTED)
    footer(img, handle, episode["n"], episode.get("total", 30))
    return img


def tip_frame(idx: int, tip: dict, episode: dict, handle: str) -> Image.Image:
    """Scenes 2-4 — giant accent number + title + body + code chip."""
    img = new_canvas()
    draw = ImageDraw.Draw(img)

    num_font = font("display_xb", 168)
    draw.text((C.MARGIN - 6, 316), f"{idx:02d}", font=num_font, fill=C.ACCENT)

    y = 596
    y = draw_text_block(draw, (C.MARGIN, y), tip["title"],
                        "semibold", 68, C.INK, leading=1.12)
    y += 34
    y = draw_text_block(draw, (C.MARGIN, y), tip["body"],
                        "medium", 43, C.MUTED, leading=1.24)
    if tip.get("chip"):
        y += 66
        code_chip(img, tip["chip"], y)
    footer(img, handle, episode["n"], episode.get("total", 30))
    return img


def cta_frame(episode: dict, brand_pill: str, handle: str) -> Image.Image:
    """Scene 5 — inverted accent closer, fully centered composition."""
    img = new_canvas(C.ACCENT)
    draw = ImageDraw.Draw(img)

    f_label = font("mono_sb", 26)
    tw = draw.textlength(brand_pill, font=f_label)
    draw.text(((C.W - tw) / 2, 372), brand_pill, font=f_label,
              fill=(226, 224, 255))

    y = 648
    y = draw_text_block(draw, (C.MARGIN, y), episode["cta"]["text"],
                        "display_b", 92, C.WHITE, leading=1.1)

    f_h = font("display_b", 50)
    hw = draw.textlength(handle, font=f_h)
    asc, desc = f_h.getmetrics()
    ph_h = asc + desc + 2 * 22
    ph_w = hw + 2 * 40
    px = (C.W - ph_w) / 2
    py = y + 88
    draw.rounded_rectangle([px, py, px + ph_w, py + ph_h],
                           radius=ph_h // 2, fill=C.WHITE)
    draw.text((px + 40, py + 22 - 2), handle, font=f_h, fill=C.ACCENT)

    sub = "A new tip drops every day."
    f_s = font("medium", 38)
    sw = draw.textlength(sub, font=f_s)
    draw.text(((C.W - sw) / 2, py + ph_h + 66), sub, font=f_s,
              fill=(226, 224, 255))
    return img


def progress_fill() -> Image.Image:
    return Image.new("RGB", (C.W, 10), C.ACCENT)
