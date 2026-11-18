"""Render a branded 1080x1350 image card for a post (Arabic-aware, via Pillow + libraqm)."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

from .config import Config
from .store import Post

W, H = 1080, 1350
MARGIN = 96
_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LATIN = re.compile(r"[A-Za-z]")
_HAS_RAQM = features.check("raqm")

if not _HAS_RAQM:  # pragma: no cover - depends on system libs
    warnings.warn(
        "Pillow was built without libraqm/fribidi; Arabic text on cards will render incorrectly. "
        "On Ubuntu: sudo apt-get install -y libfribidi0 libraqm0",
        RuntimeWarning,
        stacklevel=1,
    )


def _hex(color: str, alpha: int | None = None) -> tuple[int, ...]:
    color = color.lstrip("#")
    rgb = tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))
    return rgb + ((alpha,) if alpha is not None else ())


def _is_rtl(text: str) -> bool:
    return len(_ARABIC.findall(text)) >= len(_LATIN.findall(text))


def _font(cfg: Config, weight: str, size: int) -> ImageFont.FreeTypeFont:
    path = cfg.fonts_dir / f"Cairo-{weight}.ttf"
    engine = ImageFont.Layout.RAQM if _HAS_RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(str(path), size, layout_engine=engine)


class _Writer:
    def __init__(self, draw: ImageDraw.ImageDraw):
        self.draw = draw

    def _opts(self, text: str) -> dict:
        if not _HAS_RAQM:
            return {}
        return {"direction": "rtl", "language": "ar"} if _is_rtl(text) else {"direction": "ltr"}

    def width(self, text: str, font: ImageFont.FreeTypeFont) -> float:
        return self.draw.textlength(text, font=font, **self._opts(text))

    def wrap(self, text: str, font: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            words = paragraph.split()
            line = ""
            for word in words:
                candidate = f"{line} {word}".strip()
                if not line or self.width(candidate, font) <= max_width:
                    line = candidate
                else:
                    lines.append(line)
                    line = word
            if line:
                lines.append(line)
        return lines

    def line(self, xy_right: tuple[float, float], text: str, font: ImageFont.FreeTypeFont, fill, rtl: bool) -> None:
        x_right, y = xy_right
        if rtl:
            self.draw.text((x_right, y), text, font=font, fill=fill, anchor="ra", **self._opts(text))
        else:
            self.draw.text((MARGIN, y), text, font=font, fill=fill, anchor="la", **self._opts(text))


def _fit(writer: _Writer, cfg: Config, text: str, weight: str, sizes: range, max_width: float, max_lines: int):
    for size in sizes:
        font = _font(cfg, weight, size)
        lines = writer.wrap(text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    font = _font(cfg, weight, sizes[-1])
    lines = writer.wrap(text, font, max_width)[:max_lines]
    if lines:
        lines[-1] = lines[-1].rstrip(" .،") + "…"
    return font, lines


def _background(cfg: Config) -> Image.Image:
    top, bottom = _hex(cfg.brand.background), _hex(cfg.brand.background_2)
    gradient = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        gradient.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = gradient.resize((W, H)).convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(deco)
    accent = cfg.brand.accent
    d.ellipse((-320, -320, 300, 300), fill=_hex(accent, 30))
    d.ellipse((-120, H - 120, 120, H + 120), fill=_hex(accent, 40))
    return Image.alpha_composite(img, deco)


def render_card(cfg: Config, post: Post, out_path: Path, pillar_label: str | None = None) -> Path:
    if post.card is None or not post.card.headline.strip():
        raise ValueError(f"post {post.id} has no card text")
    img = _background(cfg)
    draw = ImageDraw.Draw(img)
    w = _Writer(draw)
    right = W - MARGIN
    max_w = W - 2 * MARGIN
    text_color = _hex(cfg.brand.text)
    muted = _hex(cfg.brand.muted)
    accent = _hex(cfg.brand.accent)
    dark = _hex(cfg.brand.background)

    # Pillar label pill (top, right-aligned).
    label = pillar_label or next((p.name for p in cfg.niche.pillars if p.id == post.pillar), "")
    if label:
        f_label = _font(cfg, "Bold", 38)
        lw = w.width(label, f_label)
        pad_x, pill_h, top = 34, 74, 120
        draw.rounded_rectangle((right - lw - 2 * pad_x, top, right, top + pill_h), radius=pill_h // 2, fill=accent)
        draw.text((right - pad_x, top + pill_h / 2), label, font=f_label, fill=dark, anchor="rm", **w._opts(label))

    # Headline + body, vertically centred in the space between the pill and the footer.
    headline = post.card.headline.strip()
    body = post.card.body.strip()
    rtl = _is_rtl(headline + " " + body)
    f_head, head_lines = _fit(w, cfg, headline, "Black", range(96, 63, -4), max_w, 3)
    if len(head_lines) == 3 and head_lines[-1].endswith("…"):
        f_head, head_lines = _fit(w, cfg, headline, "Black", range(72, 55, -4), max_w, 4)
    head_lh = int(f_head.size * 1.45)
    f_body, body_lines = (None, [])
    if body:
        f_body, body_lines = _fit(w, cfg, body, "Regular", range(50, 33, -2), max_w, 6)
    body_lh = int(f_body.size * 1.6) if f_body else 0
    gap_before_bar = int(f_head.size * 0.45) if body_lines else 0
    gap_after_bar = 44 if body_lines else 0
    block_h = len(head_lines) * head_lh + gap_before_bar + 10 + gap_after_bar + len(body_lines) * body_lh
    area_top, area_bottom = 250, H - 200
    y = area_top + max(0, (area_bottom - area_top - block_h) // 2)

    for ln in head_lines:
        w.line((right, y), ln, f_head, text_color, rtl)
        y += head_lh
    if body_lines:
        y += gap_before_bar
        bar_w = 120
        if rtl:
            draw.rounded_rectangle((right - bar_w, y, right, y + 10), radius=5, fill=accent)
        else:
            draw.rounded_rectangle((MARGIN, y, MARGIN + bar_w, y + 10), radius=5, fill=accent)
        y += 10 + gap_after_bar
        for ln in body_lines:
            w.line((right, y), ln, f_body, muted, rtl)
            y += body_lh

    # Footer: divider + page name (+ handle).
    fy = H - 150
    draw.line((MARGIN, fy, W - MARGIN, fy), fill=_hex(cfg.brand.muted, 90), width=2)
    f_name = _font(cfg, "Bold", 40)
    name = cfg.page.name.strip()
    draw.ellipse((right - 22, fy + 52, right, fy + 74), fill=accent)
    draw.text((right - 40, fy + 63), name, font=f_name, fill=text_color, anchor="rm", **w._opts(name))
    if cfg.page.handle.strip():
        handle = cfg.page.handle.strip()
        f_handle = _font(cfg, "Regular", 34)
        draw.text((MARGIN, fy + 63), handle, font=f_handle, fill=muted, anchor="lm", **w._opts(handle))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "PNG", optimize=True)
    return out_path
