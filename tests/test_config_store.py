from collections import Counter
from datetime import timedelta

import pytest

from fbposter.config import load_config
from fbposter.store import Card, Post, Store, now_utc, plan_pillars

from .conftest import REPO


def make_post(pid: str, pillar: str = "ready_prompt", **kw) -> Post:
    return Post(id=pid, created_at=now_utc().isoformat(), pillar=pillar, topic=f"topic {pid}",
                text="نص البوست", hashtags=["ذكاء_اصطناعي", "#AI"], card=Card(headline="عنوان"), **kw)


@pytest.mark.parametrize("niche", sorted(p.stem for p in (REPO / "niches").glob("*.yaml")))
def test_every_niche_loads(niche, monkeypatch):
    monkeypatch.setenv("FB_NICHE", niche)
    cfg = load_config(REPO)
    assert cfg.niche.id == niche
    assert cfg.niche.pillars


def test_unknown_niche_lists_available(root, monkeypatch):
    monkeypatch.setenv("FB_NICHE", "nope")
    with pytest.raises(FileNotFoundError, match="tech_ai"):
        load_config(root)


def test_plan_pillars_follows_weights_without_back_to_back_repeats(cfg):
    plan = plan_pillars(cfg.niche, [], 50)
    assert all(a != b for a, b in zip(plan, plan[1:]))
    counts = Counter(plan)
    weights = {p.id: p.weight for p in cfg.niche.pillars}
    total = sum(weights.values())
    for pid, w in weights.items():
        assert abs(counts[pid] - 50 * w / total) <= 2, (pid, counts)


def test_plan_pillars_compensates_for_history(cfg):
    recent = ["ready_prompt"] * 10
    plan = plan_pillars(cfg.niche, recent, 4)
    assert "ready_prompt" not in plan


def test_queue_order_approval_and_not_before(cfg):
    store = Store(cfg)
    store.add(make_post("20260101-000000-a"))
    store.add(make_post("20260101-000001-b", approved=True))
    store.add(make_post("20260101-000002-c", approved=True,
                        not_before=(now_utc() + timedelta(days=1)).isoformat()))
    assert store.next_ready(require_approval=False).id == "20260101-000000-a"
    assert store.next_ready(require_approval=True).id == "20260101-000001-b"
    assert [p.id for p in store.queued()] == ["20260101-000000-a", "20260101-000001-b", "20260101-000002-c"]


def test_record_published_moves_post_to_history(cfg):
    store = Store(cfg)
    post = make_post("20260101-000000-a")
    store.add(post)
    store.image_path_for(post).write_bytes(b"png")
    store.record_published(post, "123_456", "https://facebook.com/123_456")
    assert store.queued() == []
    assert not store.image_path_for(post).exists()
    (row,) = store.history()
    assert row["fb_id"] == "123_456" and row["topic"] == post.topic
    assert store.recent_topics() == [post.topic]


def test_full_text_normalises_hashtags():
    post = make_post("x")
    assert post.full_text() == "نص البوست\n\n#ذكاء_اصطناعي #AI"
