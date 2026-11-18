"""Render the Page's profile picture and cover photo in the brand style."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .cards import _font, _hex, _Writer
from .config import Config


def _gradient(cfg: Config, w: int, h: int) -> Image.Image:
    top, bottom = _hex(cfg.brand.background), _hex(cfg.brand.background_2)
    col = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return col.resize((w, h)).convert("RGBA")


def _split_name(name: str) -> tuple[str, str]:
    """'AI بالمصري' -> ('AI', 'بالمصري'): first word big, the rest underneath."""
    parts = name.split(maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (name, "")


def render_profile(cfg: Config, out: Path, size: int = 1080) -> Path:
    img = _gradient(cfg, size, size)
    d = ImageDraw.Draw(img)
    w = _Writer(d)
    c = size / 2
    accent, text = _hex(cfg.brand.accent), _hex(cfg.brand.text)
    # Facebook crops profile pictures to a circle: keep everything inside it.
    d.ellipse((c - 430, c - 430, c + 430, c + 430), outline=_hex(cfg.brand.accent, 110), width=10)
    big, small = _split_name(cfg.page.name)
    f_big = _font(cfg, "Black", 360)
    d.text((c, c - 40), big, font=f_big, fill=accent, anchor="mm", **w._opts(big))
    if small:
        f_small = _font(cfg, "Bold", 150)
        d.text((c, c + 215), small, font=f_small, fill=text, anchor="mm", **w._opts(small))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out


def render_cover(cfg: Config, out: Path, tagline: str, points: list[str], w: int = 1640, h: int = 624) -> Path:
    img = _gradient(cfg, w, h)
    deco = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    dd.ellipse((-260, -320, 380, 320), fill=_hex(cfg.brand.accent, 30))
    dd.ellipse((w - 300, h - 220, w + 200, h + 280), fill=_hex(cfg.brand.accent, 26))
    img = Image.alpha_composite(img, deco)
    d = ImageDraw.Draw(img)
    wr = _Writer(d)
    cx = w / 2
    accent, text, muted = _hex(cfg.brand.accent), _hex(cfg.brand.text), _hex(cfg.brand.muted)
    # Mobile shows roughly the middle 1100px, so everything stays centred.
    name = cfg.page.name
    f_name = _font(cfg, "Black", 132)
    d.text((cx, 205), name, font=f_name, fill=text, anchor="mm", **wr._opts(name))
    d.rounded_rectangle((cx - 70, 318, cx + 70, 328), radius=5, fill=accent)
    f_tag = _font(cfg, "Bold", 56)
    d.text((cx, 398), tagline, font=f_tag, fill=accent, anchor="mm", **wr._opts(tagline))
    if points:
        line = "  •  ".join(points)
        f_pts = _font(cfg, "Regular", 40)
        d.text((cx, 480), line, font=f_pts, fill=muted, anchor="mm", **wr._opts(line))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out
