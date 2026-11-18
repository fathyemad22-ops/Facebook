"""Render a short vertical reel (1080x1920 MP4) from a list of text slides."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from .cards import _fit, _font, _hex, _is_rtl, _Writer
from .config import Config

W, H = 1080, 1920
FPS = 30
MARGIN = 100


@dataclass
class Slide:
    headline: str
    body: str = ""
    label: str = ""
    seconds: float = 4.0


def _background(cfg: Config) -> Image.Image:
    top, bottom = _hex(cfg.brand.background), _hex(cfg.brand.background_2)
    col = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        col.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = col.resize((W, H)).convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(deco)
    d.ellipse((-350, -350, 350, 350), fill=_hex(cfg.brand.accent, 30))
    d.ellipse((W - 250, H - 250, W + 250, H + 250), fill=_hex(cfg.brand.accent, 36))
    img = Image.alpha_composite(img, deco)
    # Footer with the page name.
    d = ImageDraw.Draw(img)
    w = _Writer(d)
    name = cfg.page.name
    d.line((MARGIN, H - 230, W - MARGIN, H - 230), fill=_hex(cfg.brand.muted, 90), width=2)
    d.ellipse((W - MARGIN - 24, H - 168, W - MARGIN, H - 144), fill=_hex(cfg.brand.accent))
    d.text((W - MARGIN - 44, H - 156), name, font=_font(cfg, "Bold", 46),
           fill=_hex(cfg.brand.text), anchor="rm", **w._opts(name))
    return img


def _text_layer(cfg: Config, slide: Slide) -> Image.Image:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w = _Writer(d)
    right, max_w = W - MARGIN, W - 2 * MARGIN
    accent, text, muted, dark = (_hex(cfg.brand.accent), _hex(cfg.brand.text),
                                 _hex(cfg.brand.muted), _hex(cfg.brand.background))
    rtl = _is_rtl(slide.headline + " " + slide.body)
    f_head, head = _fit(w, cfg, slide.headline, "Black", range(120, 63, -4), max_w, 5)
    head_lh = int(f_head.size * 1.4)
    f_body, body = (None, [])
    if slide.body:
        f_body, body = _fit(w, cfg, slide.body, "Bold", range(62, 39, -2), max_w, 8)
    body_lh = int(f_body.size * 1.55) if f_body else 0
    label_h = 130 if slide.label else 0
    gap = int(f_head.size * 0.5) + 60 if body else 0
    block = label_h + len(head) * head_lh + gap + len(body) * body_lh
    y = max(260, (H - 260 - block) // 2)
    if slide.label:
        f_l = _font(cfg, "Bold", 46)
        lw = w.width(slide.label, f_l)
        d.rounded_rectangle((right - lw - 80, y, right, y + 90), radius=45, fill=accent)
        d.text((right - 40, y + 45), slide.label, font=f_l, fill=dark, anchor="rm", **w._opts(slide.label))
        y += label_h
    for ln in head:
        w.line((right, y), ln, f_head, text, rtl)
        y += head_lh
    if body:
        y += int(f_head.size * 0.6)
        d.rounded_rectangle((right - 140, y, right, y + 12), radius=6, fill=accent)
        y += 12 + 60
        for ln in body:
            w.line((right, y), ln, f_body, muted, rtl)
            y += body_lh
    return layer


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def render_reel(cfg: Config, slides: list[Slide], out: Path, ffmpeg: str | None = None) -> Path:
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to render reels")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    bg = _background(cfg)
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
         "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    try:
        for slide in slides:
            layer = _text_layer(cfg, slide)
            frames = int(slide.seconds * FPS)
            intro, outro = int(0.5 * FPS), int(0.3 * FPS)
            for i in range(frames):
                if i < intro:
                    a, dy = _ease(i / intro), int(60 * (1 - _ease(i / intro)))
                elif i >= frames - outro:
                    a, dy = 1 - (i - (frames - outro)) / outro, 0
                else:
                    a, dy = 1.0, 0
                frame = bg.copy()
                if a > 0:
                    moved = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    moved.paste(layer, (0, dy))
                    if a < 1:
                        moved.putalpha(moved.getchannel("A").point(lambda v: int(v * a)))
                    frame = Image.alpha_composite(frame, moved)
                proc.stdin.write(frame.convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed to encode the reel")
    return out
