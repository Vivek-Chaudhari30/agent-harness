"""Phase 0 tests for the model client. All run under MODEL_PROVIDER=fake, no key."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src import model_client
from src.config import Config
from src.model_client import (
    ModelRefusal,
    StrictSchemaError,
    call_json,
    reset_fake_responder,
    set_fake_responder,
)


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
    "additionalProperties": False,
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
        return {"pass": False, "reason": f"n={calls['n']}"}

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


class _Answer(BaseModel):
    verdict: bool
    reason: str


def _openai_client(*, parsed=None, refusal=None, available=("test-model",), fail_first=False):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        if fail_first and len(calls) == 1:
            raise _TemperatureUnsupported("temperature is unsupported")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, refusal=refusal))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )

    return (
        SimpleNamespace(
            models=SimpleNamespace(
                list=lambda: SimpleNamespace(
                    data=[SimpleNamespace(id=model) for model in available]
                )
            ),
            chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)),
        ),
        calls,
    )


class _TemperatureUnsupported(Exception):
    pass


def _openai_cfg(tmp_path):
    return Config(
        model_name="test-model",
        model_provider="openai",
        api_key="test-key",
        cache_dir=str(tmp_path / "cache"),
        debug_log=str(tmp_path / "calls.jsonl"),
    )


def test_openai_pydantic_schema_round_trips_without_text_parsing(monkeypatch, tmp_path):
    import openai

    client, calls = _openai_client(parsed=_Answer(verdict=True, reason="clear"))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: client)
    model_client._verified_openai_models.clear()

    cfg = _openai_cfg(tmp_path)
    assert call_json("prompt", _Answer, config=cfg) == {
        "verdict": True,
        "reason": "clear",
    }
    assert calls[0]["response_format"] is _Answer
    assert calls[0]["temperature"] == 0.0
    with open(cfg.debug_log, encoding="utf-8") as fh:
        entry = json.loads(fh.readline())
    assert entry["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert entry["run_usage"] == entry["usage"]


def test_openai_refusal_is_distinct_error(monkeypatch, tmp_path):
    import openai

    client, _calls = _openai_client(refusal="I cannot do that")
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: client)
    model_client._verified_openai_models.clear()

    with pytest.raises(ModelRefusal, match="cannot"):
        call_json("prompt", _Answer, config=_openai_cfg(tmp_path), use_cache=False)


def test_non_strict_dict_schema_is_rejected_before_a_provider_call(fake_cfg):
    non_strict = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    with pytest.raises(StrictSchemaError, match="additionalProperties"):
        call_json("prompt", non_strict, config=fake_cfg)


def test_openai_temperature_fallback_is_recorded(monkeypatch, tmp_path):
    import openai

    client, calls = _openai_client(
        parsed=_Answer(verdict=True, reason="clear"), fail_first=True
    )
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: client)
    monkeypatch.setattr(openai, "BadRequestError", _TemperatureUnsupported)
    model_client._verified_openai_models.clear()

    cfg = _openai_cfg(tmp_path)
    assert call_json("prompt", _Answer, config=cfg, use_cache=False) == {
        "verdict": True,
        "reason": "clear",
    }
    assert len(calls) == 2
    assert "temperature" not in calls[1]
    with open(cfg.debug_log, encoding="utf-8") as fh:
        entry = json.loads(fh.readline())
    assert entry["temperature_applied"] is False


def test_cache_keys_are_isolated_by_provider():
    fake_key = model_client._cache_key("fake", "model", None, "prompt", _SCHEMA, {})
    openai_key = model_client._cache_key("openai", "model", None, "prompt", _SCHEMA, {})
    assert fake_key != openai_key


def test_unknown_openai_model_fails_before_completion(monkeypatch, tmp_path):
    import openai

    client, calls = _openai_client(parsed=_Answer(verdict=True, reason="clear"), available=())
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: client)
    model_client._verified_openai_models.clear()

    with pytest.raises(ValueError, match="not served"):
        call_json("prompt", _Answer, config=_openai_cfg(tmp_path), use_cache=False)
    assert calls == []
