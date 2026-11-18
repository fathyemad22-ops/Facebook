"""Write Facebook posts with Claude (Anthropic Messages API, structured JSON output)."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from .config import Config
from .store import Card, Post, decide_image, new_post_id, now_utc, plan_pillars

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept the server-side `fallbacks` parameter.
_FALLBACK_MODEL_PREFIXES = ("claude-opus-5", "claude-fable-5", "claude-mythos-5", "claude-sonnet-5-5")

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF‍️⭐⬆↔-↪]+"
)


class GenerationError(RuntimeError):
    pass


class _GeneratedPost(BaseModel):
    pillar: str
    topic: str
    text: str
    hashtags: list[str]
    card_headline: str
    card_body: str


def _schema(pillar_ids: list[str]) -> dict[str, Any]:
    post = {
        "type": "object",
        "properties": {
            "pillar": {"type": "string", "enum": pillar_ids},
            "topic": {
                "type": "string",
                "description": "One short line naming the exact subject, used to avoid repeats.",
            },
            "text": {"type": "string", "description": "The full Facebook post body, without hashtags."},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "card_headline": {"type": "string"},
            "card_body": {"type": "string"},
        },
        "required": ["pillar", "topic", "text", "hashtags", "card_headline", "card_body"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"posts": {"type": "array", "items": post}},
        "required": ["posts"],
        "additionalProperties": False,
    }


def build_system_prompt(cfg: Config) -> str:
    n = cfg.niche
    pillars = "\n".join(f"- `{p.id}` ({p.name}): {p.description.strip()}" for p in n.pillars)
    rules = "\n".join(f"- {r}" for r in n.rules) or "- (none)"
    tags = " ".join(n.hashtags) or "(none)"
    return f"""You write every post for the Facebook Page "{cfg.page.name}" ({n.title}).

## Audience
{n.audience.strip()}

## Voice
{n.voice.strip()}

## Language
Write in {n.language}. Write the way people actually type on Facebook in Egypt, not formal
Modern Standard Arabic, unless the language line above says otherwise.

## Content pillars
Every post belongs to exactly one pillar:
{pillars}

## How a good post for this Page reads
- The first line is the hook. Facebook cuts the post off after about two lines behind
  "See more", so the first line alone has to make someone stop scrolling: a surprising
  claim, a relatable problem, or a concrete promise. Never open with a greeting.
- Short paragraphs of one or two lines with blank lines between them. Easy to read on a phone.
- A few emojis as visual bullets or accents (about 2 to 5). Not one on every line.
- Between 60 and 180 words. Give real substance: an example, steps, or a before and after.
- Close with one natural question or invitation that people actually want to answer from
  their own experience.
- No engagement bait. Never write "like if", "share if", "type yes", "tag a friend who",
  or anything that begs for reactions. Facebook demotes posts that do this.
- No external links in the post body (they cut reach), and no phone numbers.
- Do not mention that the post was written by AI, and do not sign it.

## Accuracy
Write only what you are highly confident is true and will stay true. If you are not sure of
a fact, figure, or name, choose a different angle instead of guessing. Never invent
statistics, studies, quotes, or news. No medical, legal, or financial advice for individuals.

## Page rules
{rules}

## Hashtags
Give 3 to 5 hashtags per post. Include one or two of the Page's standard tags: {tags}
The rest should be specific to the post.

## Image card
Each post may go out with an image card. Provide:
- `card_headline`: at most 8 words, the core idea, the strongest phrase in the post.
- `card_body`: at most 28 words, one supporting line or a mini summary. It can be empty.
No emojis, hashtags, or quotation marks on the card. It is rendered as plain text.

## Variety
Never repeat a topic you are told is already covered, or a close variant of it. Vary hooks,
structures, and closing questions across posts in the same batch.
"""


def build_user_prompt(pillar_plan: list[str], cfg: Config, recent_topics: list[str]) -> str:
    names = {p.id: p.name for p in cfg.niche.pillars}
    slots = "\n".join(f"{i + 1}. pillar `{pid}` ({names.get(pid, pid)})" for i, pid in enumerate(pillar_plan))
    covered = "\n".join(f"- {t}" for t in recent_topics[-60:]) or "- (nothing yet, this is the first batch)"
    return f"""Write {len(pillar_plan)} new posts, in this order:
{slots}

Topics already covered or queued (do not repeat them):
{covered}

Return them in `posts`, one entry per slot, in the same order."""


def _supports_fallbacks(model: str) -> bool:
    return model.startswith(_FALLBACK_MODEL_PREFIXES)


def _final_text(message: Any) -> str:
    """Join text blocks after the last fallback switch point (if a fallback model took over)."""
    parts: list[str] = []
    for block in message.content:
        btype = getattr(block, "type", None)
        if btype == "fallback":
            parts = []
        elif btype == "text":
            parts.append(block.text)
    return "".join(parts)


def _clean_card(text: str) -> str:
    text = _EMOJI_RE.sub("", text)
    text = text.replace('"', "").replace("«", "").replace("»", "")
    text = re.sub(r"#\S+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_hashtags(tags: list[str], limit: int = 5) -> list[str]:
    out: list[str] = []
    for tag in tags:
        tag = tag.strip().replace(" ", "_")
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = f"#{tag}"
        if tag.lower() not in {t.lower() for t in out}:
            out.append(tag)
    return out[:limit]


def call_claude(client: Any, cfg: Config, system: str, user: str, pillar_ids: list[str]) -> list[_GeneratedPost]:
    kwargs: dict[str, Any] = {
        "model": cfg.claude.model,
        "max_tokens": 32000,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {
            "effort": cfg.claude.effort,
            "format": {"type": "json_schema", "schema": _schema(pillar_ids)},
        },
    }
    if _supports_fallbacks(cfg.claude.model):
        # If the main model declines, the API retries on Anthropic's recommended fallback model.
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    with client.beta.messages.stream(**kwargs) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        raise GenerationError(f"Claude declined the request: {details}")
    if message.stop_reason == "max_tokens":
        raise GenerationError("Claude ran out of output tokens; lower claude.batch_size in config.yaml")

    raw = _final_text(message)
    try:
        data = json.loads(raw)
        return [_GeneratedPost.model_validate(p) for p in data["posts"]]
    except (json.JSONDecodeError, KeyError, ValidationError) as exc:
        raise GenerationError(f"Could not parse Claude's response: {exc}\n{raw[:500]}") from exc


def generate_posts(cfg: Config, count: int, recent_pillars: list[str], recent_topics: list[str], client: Any = None) -> list[Post]:
    """Generate `count` posts, in batches of `claude.batch_size`."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    pillar_ids = [p.id for p in cfg.niche.pillars]
    system = build_system_prompt(cfg)
    plan = plan_pillars(cfg.niche, recent_pillars, count)
    topics = list(recent_topics)
    posts: list[Post] = []
    batch = max(1, cfg.claude.batch_size)
    for start in range(0, len(plan), batch):
        chunk = plan[start : start + batch]
        generated = call_claude(client, cfg, system, build_user_prompt(chunk, cfg, topics), pillar_ids)
        for g in generated:
            post_id = new_post_id(g.pillar)
            while any(p.id == post_id for p in posts):
                post_id = new_post_id(g.pillar)
            posts.append(
                Post(
                    id=post_id,
                    created_at=now_utc().isoformat(),
                    pillar=g.pillar,
                    topic=g.topic.strip(),
                    text=g.text.strip(),
                    hashtags=_clean_hashtags(g.hashtags),
                    card=Card(headline=_clean_card(g.card_headline), body=_clean_card(g.card_body)),
                    with_image=decide_image(cfg, g.pillar, post_id),
                    source="claude-api",
                )
            )
            topics.append(g.topic)
    return posts
