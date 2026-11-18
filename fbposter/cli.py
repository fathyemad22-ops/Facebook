"""Command line: python -m fbposter <command>."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .config import ROOT, Config, load_config
from .store import Post, Store


def _load_dotenv(root: Path) -> None:
    """Read KEY=VALUE lines from .env (local use only; GitHub Actions uses secrets)."""
    env = root / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip() and not os.environ.get(key.strip()):
            os.environ[key.strip()] = value.strip().strip('"').strip("'")


def _summary(text: str) -> None:
    """Append Markdown to the GitHub Actions job summary when running in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def _page(cfg: Config):
    from .facebook import FacebookPage

    return FacebookPage(
        os.environ.get("FB_PAGE_ID", ""),
        os.environ.get("FB_PAGE_ACCESS_TOKEN", ""),
        version=cfg.facebook.graph_api_version,
    )


def _pillar_name(cfg: Config, pillar_id: str) -> str:
    return next((p.name for p in cfg.niche.pillars if p.id == pillar_id), pillar_id)


def _generate(cfg: Config, store: Store, count: int) -> list[Post]:
    from .generator import generate_posts

    posts = generate_posts(cfg, count, store.recent_pillars(), store.recent_topics())
    for post in posts:
        store.add(post)
    return posts


# ---------------------------------------------------------------- commands
def cmd_status(cfg: Config, store: Store, args) -> int:
    queued = store.queued()
    history = store.history()
    ready = store.next_ready(cfg.posting.require_approval)
    print(f"Page: {cfg.page.name} | niche: {cfg.niche.id} ({cfg.niche.title})")
    print(f"Queued: {len(queued)} (target {cfg.posting.queue_target}) | published so far: {len(history)}")
    if cfg.posting.require_approval:
        print(f"Approved and waiting: {sum(p.approved for p in queued)}")
    if ready:
        print(f"Next: [{_pillar_name(cfg, ready.pillar)}] {ready.topic}")
    if history:
        last = history[-1]
        print(f"Last published: {last.get('posted_at')} {last.get('permalink') or last.get('fb_id')}")
    return 0


def cmd_check(cfg: Config, store: Store, args) -> int:
    ok = True
    print(f"config OK: page '{cfg.page.name}', niche '{cfg.niche.id}', {len(cfg.niche.pillars)} pillars")
    from .cards import _HAS_RAQM

    print("Arabic text shaping (raqm): " + ("OK" if _HAS_RAQM else "MISSING, install libraqm/libfribidi"))
    ok &= _HAS_RAQM
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY: set")
    else:
        print("ANTHROPIC_API_KEY: not set (needed only to generate posts with the Claude API)")
    if os.environ.get("FB_PAGE_ID") and os.environ.get("FB_PAGE_ACCESS_TOKEN"):
        from .facebook import FacebookError

        try:
            info = _page(cfg).info()
            print(f"Facebook: connected to '{info.get('name')}' ({info.get('fan_count', '?')} followers)")
        except FacebookError as exc:
            print(f"Facebook: FAILED: {exc}")
            ok = False
    else:
        print("Facebook: FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN not set")
        ok = False
    return 0 if ok else 1


def cmd_plan(cfg: Config, store: Store, args) -> int:
    have = len(store.queued())
    count = args.count if args.count is not None else max(0, cfg.posting.queue_target - have)
    if count <= 0:
        print(f"Queue already has {have} posts (target {cfg.posting.queue_target}). Nothing to do.")
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set; cannot generate posts.", file=sys.stderr)
        return 1
    print(f"Generating {count} posts with {cfg.claude.model}…")
    posts = _generate(cfg, store, count)
    lines = [f"### Generated {len(posts)} posts", ""]
    for p in posts:
        line = f"- [{_pillar_name(cfg, p.pillar)}] {p.topic}" + (" 🖼️" if p.with_image else "")
        print(line)
        lines.append(line)
    if args.preview:
        _render_previews(cfg, store, posts)
    _summary("\n".join(lines))
    return 0


def _render_previews(cfg: Config, store: Store, posts: list[Post]) -> None:
    from .cards import render_card

    for p in posts:
        if p.with_image and p.card:
            render_card(cfg, p, store.image_path_for(p), _pillar_name(cfg, p.pillar))


def cmd_preview(cfg: Config, store: Store, args) -> int:
    posts = store.queued()
    if args.id:
        posts = [p for p in posts if p.id.startswith(args.id)]
    _render_previews(cfg, store, posts)
    for p in posts:
        print(f"\n===== {p.id} [{_pillar_name(cfg, p.pillar)}]{' + image' if p.with_image else ''} =====")
        print(p.full_text())
        if p.with_image:
            print(f"(image: {store.image_path_for(p).relative_to(cfg.root)})")
    return 0


def cmd_post(cfg: Config, store: Store, args) -> int:
    from .cards import render_card
    from .facebook import FacebookError

    post = store.next_ready(cfg.posting.require_approval)
    can_autogenerate = (
        cfg.posting.auto_generate_when_queue_empty
        and not cfg.posting.require_approval  # never publish unreviewed posts in approval mode
        and not store.queued()
        and os.environ.get("ANTHROPIC_API_KEY")
    )
    if post is None and can_autogenerate:
        print("Queue is empty; writing a fresh post with Claude…")
        post = _generate(cfg, store, 1)[0]
    if post is None:
        msg = "Nothing to publish: the queue is empty"
        if cfg.posting.require_approval:
            msg += " or no post is approved yet"
        print(f"::warning::{msg}" if os.environ.get("GITHUB_ACTIONS") else msg)
        _summary(f"⚠️ {msg}")
        return 0

    image = None
    if post.with_image and post.card:
        image = store.image_path_for(post)
        if not image.exists():
            image = cfg.root / "out" / f"{post.id}.png"
            render_card(cfg, post, image, _pillar_name(cfg, post.pillar))

    text = post.full_text()
    if args.dry_run:
        print("DRY RUN, nothing was published.\n")
        print(text)
        if image:
            print(f"\n(image: {image})")
        return 0

    page = _page(cfg)
    try:
        fb_id = page.post_photo(image, text) if image else page.post_text(text)
    except FacebookError as exc:
        print(f"Publishing failed: {exc}", file=sys.stderr)
        _summary(f"❌ Publishing failed: {exc}")
        return 1
    link = page.permalink(fb_id)
    store.record_published(post, fb_id, link)
    if image and image.parent.name == "out":
        image.unlink(missing_ok=True)
    print(f"Published {post.id} → {link or fb_id}")
    _summary(f"✅ Published **[{_pillar_name(cfg, post.pillar)}] {post.topic}**\n\n{link or fb_id}\n\n> " + text.replace("\n", "\n> "))
    return 0


def cmd_add(cfg: Config, store: Store, args) -> int:
    """Queue posts written outside the Claude API (e.g. by Claude Code or by hand).

    The file holds a JSON list of objects with: pillar, topic, text, hashtags,
    card_headline, card_body and optionally with_image / approved / not_before.
    """
    import json

    from .generator import _clean_card, _clean_hashtags
    from .store import Card, decide_image, new_post_id, now_utc

    items = json.loads(Path(args.file).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("posts", [items])
    pillar_ids = {p.id for p in cfg.niche.pillars}
    known = {t.strip() for t in store.recent_topics(limit=10_000)}
    added = 0
    for item in items:
        pillar = item.get("pillar", "")
        if pillar not in pillar_ids:
            print(f"Skipping '{item.get('topic', '?')}': unknown pillar '{pillar}'", file=sys.stderr)
            continue
        topic = item.get("topic", "").strip()
        if topic in known:
            print(f"Skipping duplicate topic: {topic}", file=sys.stderr)
            continue
        post_id = new_post_id(pillar)
        while (store.queue_dir / f"{post_id}.json").exists():
            post_id = new_post_id(pillar)
        with_image = item.get("with_image")
        post = Post(
            id=post_id,
            created_at=now_utc().isoformat(),
            pillar=pillar,
            topic=topic,
            text=item["text"].strip(),
            hashtags=_clean_hashtags(item.get("hashtags", [])),
            card=Card(headline=_clean_card(item.get("card_headline", "")), body=_clean_card(item.get("card_body", ""))),
            with_image=decide_image(cfg, pillar, post_id) if with_image is None else bool(with_image),
            approved=bool(item.get("approved", False)),
            not_before=item.get("not_before"),
            source=args.source,
        )
        if post.with_image and not post.card.headline:
            post.with_image = False
        store.add(post)
        known.add(topic)
        added += 1
        print(f"Queued {post.id}: {topic}")
    print(f"Added {added} post(s). Queue now has {len(store.queued())}.")
    return 0 if added or not items else 1


def cmd_token(cfg: Config, store: Store, args) -> int:
    from .facebook import exchange_for_page_tokens

    app_id = args.app_id or os.environ.get("FB_APP_ID")
    secret = args.app_secret or os.environ.get("FB_APP_SECRET")
    user_token = args.user_token or os.environ.get("FB_USER_TOKEN")
    if not (app_id and secret and user_token):
        print("Need --app-id, --app-secret and --user-token (or FB_APP_ID / FB_APP_SECRET / FB_USER_TOKEN).", file=sys.stderr)
        return 1
    pages = exchange_for_page_tokens(app_id, secret, user_token, cfg.facebook.graph_api_version)
    if not pages:
        print("No Pages found. Did you grant pages_show_list and pick the Page in the login dialog?")
        return 1
    for page in pages:
        print(f"\nPage: {page.get('name')}\n  FB_PAGE_ID={page.get('id')}\n  FB_PAGE_ACCESS_TOKEN={page.get('access_token')}")
    print("\nSave these two values as GitHub secrets. Never commit them.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fbposter", description="Claude-written posts for a Facebook Page")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show queue and history")
    sub.add_parser("check", help="verify config, fonts and Facebook token")
    p_plan = sub.add_parser("plan", help="generate posts with Claude to fill the queue")
    p_plan.add_argument("--count", type=int, help="number of posts (default: fill up to queue_target)")
    p_plan.add_argument("--preview", action="store_true", help="also render card images next to the queue files")
    p_prev = sub.add_parser("preview", help="print queued posts and render their cards")
    p_prev.add_argument("--id", help="only posts whose id starts with this")
    p_post = sub.add_parser("post", help="publish the next post in the queue")
    p_post.add_argument("--dry-run", action="store_true", help="show what would be published without publishing")
    p_add = sub.add_parser("add", help="queue posts from a JSON file (no API key needed)")
    p_add.add_argument("file")
    p_add.add_argument("--source", default="claude-code")
    p_tok = sub.add_parser("token", help="exchange a short-lived user token for permanent Page tokens")
    p_tok.add_argument("--app-id")
    p_tok.add_argument("--app-secret")
    p_tok.add_argument("--user-token")
    args = parser.parse_args(argv)

    _load_dotenv(ROOT)
    cfg = load_config()
    store = Store(cfg)
    handler = {
        "status": cmd_status,
        "check": cmd_check,
        "plan": cmd_plan,
        "preview": cmd_preview,
        "post": cmd_post,
        "add": cmd_add,
        "token": cmd_token,
    }[args.command]
    return handler(cfg, store, args)
