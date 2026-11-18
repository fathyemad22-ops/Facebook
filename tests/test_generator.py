import json
from types import SimpleNamespace as NS

import pytest

from fbposter.generator import GenerationError, generate_posts


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class FakeClient:
    """Mimics client.beta.messages.stream(...) and records the request kwargs."""

    def __init__(self, messages):
        self.calls = []
        self._messages = list(messages)
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self._messages.pop(0))


def reply(posts, stop_reason="end_turn", prefix_blocks=()):
    content = list(prefix_blocks) + [NS(type="text", text=json.dumps({"posts": posts}, ensure_ascii=False))]
    return NS(content=content, stop_reason=stop_reason, stop_details=None)


def gen(pillar, i):
    return {
        "pillar": pillar,
        "topic": f"موضوع {i}",
        "text": f"سطر الهوك {i}\n\nتفاصيل",
        "hashtags": ["#AI", "ذكاء اصطناعي", "#ai", "#a", "#b", "#c"],
        "card_headline": "عنوان 🔥 \"قوي\" #تاج",
        "card_body": "سطر صغير ✨",
    }


def test_generates_batches_with_planned_pillars(cfg):
    cfg.claude.batch_size = 2

    def answer(call):
        # pillars requested in this call, parsed from the user prompt
        return [line.split("`")[1] for line in call["messages"][0]["content"].splitlines() if "pillar `" in line]

    client = FakeClient([])
    def stream(**kwargs):
        client.calls.append(kwargs)
        pillars = answer(kwargs)
        return FakeStream(reply([gen(p, i) for i, p in enumerate(pillars)]))
    client.beta = NS(messages=NS(stream=stream))

    posts = generate_posts(cfg, 3, [], ["موضوع قديم"], client=client)
    assert len(posts) == 3 and len(client.calls) == 2
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in call and "temperature" not in call
    assert "موضوع قديم" in call["messages"][0]["content"]
    # second batch is told about topics produced by the first
    assert "موضوع 0" in client.calls[1]["messages"][0]["content"]
    p = posts[0]
    assert p.hashtags == ["#AI", "#ذكاء_اصطناعي", "#a", "#b", "#c"]
    assert p.card.headline == "عنوان قوي"
    assert p.card.body == "سطر صغير"
    assert len({x.id for x in posts}) == 3


def test_text_after_fallback_switch_is_used(cfg):
    partial = NS(type="text", text='{"posts": [')
    client = FakeClient([reply([gen("myth_fact", 1)], prefix_blocks=[partial, NS(type="fallback")])])
    posts = generate_posts(cfg, 1, [], [], client=client)
    assert posts[0].pillar == "myth_fact"


def test_no_fallbacks_param_for_models_without_it(cfg):
    cfg.claude.model = "claude-opus-4-8"
    client = FakeClient([reply([gen("myth_fact", 1)])])
    generate_posts(cfg, 1, [], [], client=client)
    assert "fallbacks" not in client.calls[0] and "betas" not in client.calls[0]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reasons_raise(cfg, stop):
    client = FakeClient([reply([], stop_reason=stop)])
    with pytest.raises(GenerationError):
        generate_posts(cfg, 1, [], [], client=client)
