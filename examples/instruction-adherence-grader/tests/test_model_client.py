"""Phase 0 tests for the model client. All run under MODEL_PROVIDER=fake, no key."""

from __future__ import annotations

import pytest

from src.config import Config
from src.model_client import call_json, set_fake_responder, reset_fake_responder


@pytest.fixture
def fake_cfg(tmp_path):
    """A fake-provider Config with an isolated cache dir and debug log."""
    return Config(
        model_provider="fake",
        cache_dir=str(tmp_path / "cache"),
        debug_log=str(tmp_path / "calls.jsonl"),
    )


@pytest.fixture(autouse=True)
def _clean_responder():
    reset_fake_responder()
    yield
    reset_fake_responder()


_SCHEMA = {
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass", "reason"],
}


def test_cache_makes_one_provider_call_for_two_identical_calls(fake_cfg):
    """The same call twice makes exactly one provider request; the second is cached."""
    calls = {"n": 0}

    def responder(_req):
        calls["n"] += 1
        return {"pass": True, "reason": "ok"}

    set_fake_responder(responder)

    r1 = call_json("prompt", _SCHEMA, config=fake_cfg)
    r2 = call_json("prompt", _SCHEMA, config=fake_cfg)

    assert calls["n"] == 1, "second identical call should hit the cache, not the provider"
    assert r1 == r2 == {"pass": True, "reason": "ok"}


def test_no_cache_bypasses_the_cache(fake_cfg):
    calls = {"n": 0}

    def responder(_req):
        calls["n"] += 1
        return {"pass": False, "reason": "n=%d" % calls["n"]}

    set_fake_responder(responder)

    call_json("prompt", _SCHEMA, config=fake_cfg, use_cache=False)
    call_json("prompt", _SCHEMA, config=fake_cfg, use_cache=False)

    assert calls["n"] == 2, "use_cache=False must reach the provider every time"


def test_different_prompts_are_cached_separately(fake_cfg):
    calls = {"n": 0}

    def responder(req):
        calls["n"] += 1
        return {"pass": True, "reason": req["prompt"]}

    set_fake_responder(responder)

    a = call_json("prompt A", _SCHEMA, config=fake_cfg)
    b = call_json("prompt B", _SCHEMA, config=fake_cfg)

    assert calls["n"] == 2
    assert a != b


def test_default_fake_responder_synthesizes_schema_valid_output(fake_cfg):
    # No responder installed -> synthesize from schema.
    out = call_json("prompt", _SCHEMA, config=fake_cfg)
    assert set(out.keys()) == {"pass", "reason"}
    assert isinstance(out["pass"], bool)
    assert isinstance(out["reason"], str)


def test_debug_log_appends_every_call(fake_cfg):
    set_fake_responder(lambda _req: {"pass": True, "reason": "ok"})
    call_json("prompt", _SCHEMA, config=fake_cfg)  # miss -> logged
    call_json("prompt", _SCHEMA, config=fake_cfg)  # hit  -> logged
    with open(fake_cfg.debug_log, encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip()]
    assert len(lines) == 2


def test_missing_required_key_raises(fake_cfg):
    set_fake_responder(lambda _req: {"pass": True})  # missing "reason"
    with pytest.raises(ValueError):
        call_json("prompt", _SCHEMA, config=fake_cfg)


def test_unknown_provider_raises(tmp_path):
    cfg = Config(model_provider="mystery", cache_dir=str(tmp_path), debug_log="")
    with pytest.raises(ValueError):
        call_json("prompt", _SCHEMA, config=cfg)
