"""Tests for src/semantic_check.py. All run under MODEL_PROVIDER=fake, no API key.

Rule objects are constructed by hand per CONTRACTS.md section 1 — Lane A is building
compile.py in parallel and we build against the schema shape, not its implementation.
"""

from __future__ import annotations

import json

import pytest

from src.config import Config
from src.model_client import reset_fake_responder, set_fake_responder
from src.schemas import Rule, RuleResult
from src.semantic_check import _VERDICT_SCHEMA, check_semantic_rule


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def fake_cfg(tmp_path):
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


def _semantic_rule(
    rule_id: str = "no_pricing_a1b2c3",
    source_instruction: str = "Never mention pricing.",
    judge_prompt: str | None = None,
) -> Rule:
    """Build a hand-crafted semantic Rule for tests, per CONTRACTS.md schema."""
    return Rule(
        id=rule_id,
        instruction_set_id="is_01",
        source_instruction=source_instruction,
        kind="semantic",
        description="No pricing information in the email",
        judge_prompt=judge_prompt or (
            "You are a strict compliance judge evaluating a sales email.\n\n"
            "RULE: Never mention pricing.\n\n"
            "Violations include: any dollar amount, percentage discounts, pricing tiers, "
            "plans with prices, or phrases like 'cost-effective' or 'ROI in weeks'.\n"
            "Not a violation: describing what the product does without mentioning cost.\n\n"
            "Return pass=true if the email obeys the rule, pass=false if it violates it. "
            "Give a one-line reason quoting or paraphrasing the offending text."
        ),
    )


_EMAIL_CLEAN = "Hi there, I wanted to share how our workflow tool helps teams like yours."
_EMAIL_VIOLATING = "Hi there, at just $49/month our tool pays for itself in weeks."


# --------------------------------------------------------------------------- #
# Core behavior
# --------------------------------------------------------------------------- #

def test_returns_rule_result_with_correct_fields(fake_cfg):
    set_fake_responder(lambda _req: {"pass": True, "reason": "no pricing mentioned"})
    rule = _semantic_rule()

    result = check_semantic_rule(_EMAIL_CLEAN, rule, config=fake_cfg)

    assert isinstance(result, RuleResult)
    assert result.rule_id == rule.id
    assert result.passed is True
    assert result.reason == "no pricing mentioned"
    assert result.kind == "semantic"
    assert result.source == "semantic"


def test_pass_false_propagates_correctly(fake_cfg):
    set_fake_responder(
        lambda _req: {"pass": False, "reason": "email says '$49/month'"}
    )
    rule = _semantic_rule()

    result = check_semantic_rule(_EMAIL_VIOLATING, rule, config=fake_cfg)

    assert result.passed is False
    assert "$49/month" in result.reason


def test_exactly_one_model_call_per_rule(fake_cfg):
    """Verify one call per check_semantic_rule invocation — no batching."""
    calls = {"n": 0}

    def responder(_req):
        calls["n"] += 1
        return {"pass": True, "reason": "ok"}

    set_fake_responder(responder)
    rule = _semantic_rule()

    check_semantic_rule(_EMAIL_CLEAN, rule, config=fake_cfg)
    assert calls["n"] == 1

    check_semantic_rule(_EMAIL_CLEAN, rule, config=fake_cfg)
    # Second call hits cache for identical inputs, so provider count stays at 1.
    assert calls["n"] == 1


def test_different_rules_make_separate_model_calls(fake_cfg):
    """Two rules with different judge prompts must produce two independent calls."""
    calls = {"n": 0}

    def responder(req):
        calls["n"] += 1
        return {"pass": True, "reason": f"call {calls['n']}"}

    set_fake_responder(responder)

    rule_a = _semantic_rule(rule_id="rule_a_000001", judge_prompt="Judge rule A.")
    rule_b = _semantic_rule(rule_id="rule_b_000002", judge_prompt="Judge rule B.")

    result_a = check_semantic_rule(_EMAIL_CLEAN, rule_a, config=fake_cfg)
    result_b = check_semantic_rule(_EMAIL_CLEAN, rule_b, config=fake_cfg)

    assert calls["n"] == 2, "two distinct rules must each make one provider call"
    assert result_a.rule_id == "rule_a_000001"
    assert result_b.rule_id == "rule_b_000002"


def test_rule_id_on_result_matches_rule(fake_cfg):
    """The RuleResult.rule_id must match the Rule.id passed in, not be hardcoded."""
    set_fake_responder(lambda _req: {"pass": False, "reason": "violation"})
    rule = _semantic_rule(rule_id="my_custom_rule_id_abc123")

    result = check_semantic_rule("any email", rule, config=fake_cfg)

    assert result.rule_id == "my_custom_rule_id_abc123"


def test_fallback_prompt_used_when_judge_prompt_is_none(fake_cfg):
    """When rule.judge_prompt is None, a system prompt is still sent (not empty)."""
    received = {}

    def responder(req):
        received["system"] = req["system"]
        return {"pass": True, "reason": "ok"}

    set_fake_responder(responder)
    rule = Rule(
        id="test_rule_none_prompt_zz9999",
        instruction_set_id="is_01",
        source_instruction="Do not ask a question in the first email.",
        kind="semantic",
        description="No questions",
        judge_prompt=None,
    )

    check_semantic_rule("Some email.", rule, config=fake_cfg)

    system = received.get("system", "")
    assert system, "a system prompt must be sent even when judge_prompt is None"
    assert "Do not ask a question" in system


def test_judge_prompt_used_verbatim_as_system(fake_cfg):
    """When rule.judge_prompt is set, it is sent as the system message unchanged."""
    received = {}

    def responder(req):
        received["system"] = req["system"]
        return {"pass": False, "reason": "x"}

    set_fake_responder(responder)
    custom_prompt = "CUSTOM JUDGE PROMPT: evaluate only tone."
    rule = _semantic_rule(judge_prompt=custom_prompt)

    check_semantic_rule("email body", rule, config=fake_cfg)

    assert received["system"] == custom_prompt


def test_email_body_appears_in_user_prompt(fake_cfg):
    """The email text must be sent to the model, not just the system prompt."""
    received = {}

    def responder(req):
        received["prompt"] = req["prompt"]
        return {"pass": True, "reason": "ok"}

    set_fake_responder(responder)
    email = "Hello, this is the body of the email under evaluation."

    check_semantic_rule(email, _semantic_rule(), config=fake_cfg)

    assert email in received["prompt"]


# --------------------------------------------------------------------------- #
# Debug log (auditability requirement)
# --------------------------------------------------------------------------- #

def test_debug_log_written_for_every_call(fake_cfg):
    """Every check must produce an entry in the debug log (cache miss and hit)."""
    set_fake_responder(lambda _req: {"pass": True, "reason": "ok"})
    rule = _semantic_rule()

    check_semantic_rule(_EMAIL_CLEAN, rule, config=fake_cfg)   # miss
    check_semantic_rule(_EMAIL_CLEAN, rule, config=fake_cfg)   # hit (cached)

    with open(fake_cfg.debug_log, encoding="utf-8") as fh:
        entries = [json.loads(ln) for ln in fh if ln.strip()]

    assert len(entries) == 2, "both the cache miss and cache hit must be logged"
    for entry in entries:
        assert "prompt" in entry
        assert "response" in entry
        assert "schema" in entry


def test_debug_log_entry_contains_request_and_response(fake_cfg):
    """Each log entry must carry both the request and the response for auditability."""
    set_fake_responder(lambda _req: {"pass": False, "reason": "pricing found"})

    check_semantic_rule(_EMAIL_VIOLATING, _semantic_rule(), config=fake_cfg)

    with open(fake_cfg.debug_log, encoding="utf-8") as fh:
        entry = json.loads(fh.readline())

    assert entry["response"]["pass"] is False
    assert entry["response"]["reason"] == "pricing found"
    assert _EMAIL_VIOLATING in entry["prompt"]


# --------------------------------------------------------------------------- #
# Schema shape
# --------------------------------------------------------------------------- #

def test_verdict_schema_is_strict():
    """The schema used in model calls must be strict (additionalProperties: false)."""
    assert _VERDICT_SCHEMA.get("additionalProperties") is False
    assert set(_VERDICT_SCHEMA.get("required", [])) == {"pass", "reason"}
    props = _VERDICT_SCHEMA.get("properties", {})
    assert props.get("pass", {}).get("type") == "boolean"
    assert props.get("reason", {}).get("type") == "string"
