"""Content queue (one JSON file per pending post) and the posting history log."""

from __future__ import annotations

import json
import random
import re
import secrets
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .config import Config, Niche


class Card(BaseModel):
    """Short text rendered onto the post image."""

    headline: str
    body: str = ""


class Post(BaseModel):
    id: str
    created_at: str
    pillar: str
    topic: str
    text: str
    hashtags: list[str] = Field(default_factory=list)
    card: Card | None = None
    with_image: bool = True
    approved: bool = False
    source: str = "claude-api"
    # Optional ISO-8601 time; the post is skipped until this moment has passed.
    not_before: str | None = None

    def full_text(self) -> str:
        tags = " ".join(h if h.startswith("#") else f"#{h}" for h in self.hashtags if h.strip())
        body = self.text.strip()
        return f"{body}\n\n{tags}" if tags else body


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def new_post_id(pillar: str, when: datetime | None = None) -> str:
    when = when or now_utc()
    slug = re.sub(r"[^a-z0-9_]+", "", pillar.lower())[:24] or "post"
    return f"{when:%Y%m%d-%H%M%S}-{slug}-{secrets.token_hex(2)}"


class Store:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.queue_dir: Path = cfg.queue_dir
        self.history_file: Path = cfg.history_file
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- queue
    def queued(self) -> list[Post]:
        posts = []
        for path in sorted(self.queue_dir.glob("*.json")):
            posts.append(Post.model_validate_json(path.read_text(encoding="utf-8")))
        return posts

    def path_for(self, post: Post) -> Path:
        return self.queue_dir / f"{post.id}.json"

    def image_path_for(self, post: Post) -> Path:
        return self.queue_dir / f"{post.id}.png"

    def add(self, post: Post) -> Path:
        path = self.path_for(post)
        path.write_text(
            json.dumps(post.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return path

    def remove(self, post: Post) -> None:
        self.path_for(post).unlink(missing_ok=True)
        self.image_path_for(post).unlink(missing_ok=True)

    def next_ready(self, require_approval: bool, at: datetime | None = None) -> Post | None:
        at = at or now_utc()
        for post in self.queued():
            if require_approval and not post.approved:
                continue
            if post.not_before and _parse_time(post.not_before) > at:
                continue
            return post
        return None

    # -------------------------------------------------------------- history
    def history(self) -> list[dict]:
        if not self.history_file.exists():
            return []
        rows = []
        for line in self.history_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows

    def record_published(self, post: Post, fb_id: str, permalink: str | None = None) -> dict:
        row = post.model_dump()
        row.update({"fb_id": fb_id, "permalink": permalink, "posted_at": now_utc().isoformat()})
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with self.history_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.remove(post)
        return row

    # ----------------------------------------------------- content planning
    def recent_topics(self, limit: int = 60) -> list[str]:
        """Topics already posted or queued, newest last, so Claude can avoid repeats."""
        topics = [row.get("topic", "") for row in self.history()[-limit:]]
        topics += [p.topic for p in self.queued()]
        return [t for t in topics if t]

    def recent_pillars(self, limit: int = 40) -> list[str]:
        pillars = [row.get("pillar", "") for row in self.history()[-limit:]]
        pillars += [p.pillar for p in self.queued()]
        return [p for p in pillars if p]


def plan_pillars(niche: Niche, recent: list[str], count: int) -> list[str]:
    """Pick pillars for the next `count` posts so the mix tracks the configured weights.

    Each slot goes to the pillar furthest below its target share, never repeating the
    previous slot's pillar when another option exists.
    """
    weights = {p.id: max(p.weight, 0.0) for p in niche.pillars}
    total_weight = sum(weights.values()) or 1.0
    counts = Counter(p for p in recent if p in weights)
    history_len = sum(counts.values())
    last = recent[-1] if recent else None
    chosen: list[str] = []
    for i in range(count):
        n = history_len + i + 1
        ranked = sorted(
            weights,
            key=lambda pid: (counts[pid] - n * weights[pid] / total_weight, -weights[pid]),
        )
        pick = next((pid for pid in ranked if pid != last and weights[pid] > 0), ranked[0])
        chosen.append(pick)
        counts[pick] += 1
        last = pick
    return chosen


def decide_image(cfg: Config, pillar_id: str, post_id: str) -> bool:
    pillar = next((p for p in cfg.niche.pillars if p.id == pillar_id), None)
    if pillar is not None and not pillar.image:
        return False
    return random.Random(post_id).random() < cfg.image_ratio
