import json
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from fbposter import cli
from fbposter.cards import render_card
from fbposter.facebook import FacebookError, FacebookPage
from fbposter.store import Store

from .test_config_store import make_post


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)


def test_post_text_and_photo(tmp_path):
    s = FakeSession(FakeResp(200, {"id": "1_2"}), FakeResp(200, {"id": "9", "post_id": "1_9"}))
    page = FacebookPage("1", "TOKEN", session=s)
    assert page.post_text("hello") == "1_2"
    method, url, kw = s.calls[0]
    assert (method, url) == ("POST", "https://graph.facebook.com/v26.0/1/feed")
    assert kw["data"] == {"message": "hello", "access_token": "TOKEN"}
    img = tmp_path / "x.png"
    img.write_bytes(b"png")
    assert page.post_photo(img, "caption") == "1_9"
    method, url, kw = s.calls[1]
    assert url.endswith("/1/photos") and kw["data"]["message"] == "caption" and "source" in kw["files"]


def test_token_errors_are_explained():
    s = FakeSession(FakeResp(400, {"error": {"message": "Error validating access token", "code": 190}}))
    with pytest.raises(FacebookError, match="Token problem") as exc:
        FacebookPage("1", "T", session=s).post_text("x")
    assert exc.value.code == 190


def test_render_card_size(cfg, tmp_path):
    out = render_card(cfg, make_post("p1"), tmp_path / "c.png")
    assert Image.open(out).size == (1080, 1350)


class FakePage:
    def __init__(self):
        self.published = []

    def post_photo(self, image, text):
        assert image.exists()
        self.published.append(("photo", text))
        return "1_100"

    def post_text(self, text):
        self.published.append(("text", text))
        return "1_101"

    def permalink(self, fb_id):
        return f"https://facebook.com/{fb_id}"


@pytest.fixture
def run(cfg, monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "_load_dotenv", lambda root: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    page = FakePage()
    monkeypatch.setattr(cli, "_page", lambda c: page)
    return lambda *argv: (cli.main(list(argv)), page)


def test_cli_post_publishes_and_records(cfg, run):
    store = Store(cfg)
    store.add(make_post("20260101-000000-a", with_image=True))
    store.add(make_post("20260101-000001-b", pillar="community_question", with_image=False))
    code, page = run("post")
    assert code == 0 and page.published[0][0] == "photo"
    code, page = run("post")
    assert page.published[1][0] == "text"
    assert store.queued() == [] and len(store.history()) == 2
    assert not (cfg.root / "out" / "20260101-000000-a.png").exists()


def test_cli_dry_run_changes_nothing(cfg, run, capsys):
    store = Store(cfg)
    store.add(make_post("20260101-000000-a"))
    code, page = run("post", "--dry-run")
    assert code == 0 and page.published == []
    assert len(store.queued()) == 1 and store.history() == []
    assert "نص البوست" in capsys.readouterr().out


def test_cli_empty_queue_is_not_an_error(cfg, run):
    code, page = run("post")
    assert code == 0 and page.published == []


def test_cli_approval_mode_skips_unapproved(cfg, run):
    cfg.posting.require_approval = True
    Store(cfg).add(make_post("20260101-000000-a"))
    code, page = run("post")
    assert page.published == []


def test_cli_add_queues_valid_posts_and_skips_bad_ones(cfg, run, tmp_path):
    items = [
        {"pillar": "myth_fact", "topic": "موضوع جديد", "text": "نص", "hashtags": ["AI"],
         "card_headline": "عنوان 🔥", "card_body": "", "with_image": True},
        {"pillar": "nope", "topic": "x", "text": "y"},
        {"pillar": "myth_fact", "topic": "موضوع جديد", "text": "مكرر"},
    ]
    f = tmp_path / "posts.json"
    f.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    code, _ = run("add", str(f))
    (post,) = Store(cfg).queued()
    assert code == 0 and post.topic == "موضوع جديد" and post.hashtags == ["#AI"]
    assert post.card.headline == "عنوان" and post.with_image and post.source == "claude-code"
