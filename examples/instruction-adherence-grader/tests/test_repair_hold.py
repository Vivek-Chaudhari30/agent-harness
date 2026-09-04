"""Tests for the one-repair-then-hold behavior. (Lane B)

These tests wire checker.py and repair.py together to prove that an email still
failing after exactly one repair attempt is surfaced as held with the specific
still-failing rule ids — neither silently dropped nor silently passed through.

grader.py (Integration) owns the caller logic; these tests own the proof that
the building blocks produce the correct observable behavior.

All tests run under MODEL_PROVIDER=fake with no API key.
"""

from __future__ import annotations

import pytest

from src.checker import check_email
from src.config import Config
from src.model_client import reset_fake_responder, set_fake_responder
from src.repair import repair_email
from src.schemas import Rule, RuleResult


# --------------------------------------------------------------------------- #
# Fixtures and helpers
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


def _sem_rule(rule_id: str, source_instruction: str, judge_prompt: str) -> Rule:
    """Build a hand-crafted semantic Rule for tests (CONTRACTS.md schema)."""
    return Rule(
        id=rule_id,
        instruction_set_id="is_01",
        source_instruction=source_instruction,
        kind="semantic",
        description=source_instruction,
        judge_prompt=judge_prompt,
    )


_RULE_NO_PRICING = _sem_rule(
    rule_id="no_pricing_aa0001",
    source_instruction="Never mention pricing.",
    judge_prompt=(
        "RULE: Never mention pricing.\n"
        "Return pass=true if no pricing is mentioned, pass=false if it is."
    ),
)

_RULE_SPECIFIC_REF = _sem_rule(
    rule_id="specific_ref_bb0002",
    source_instruction="Always reference something specific about their company.",
    judge_prompt=(
        "RULE: Always reference something specific about their company.\n"
        "Return pass=true if a specific company detail is referenced, pass=false otherwise."
    ),
)

_INSTRUCTION_SET = {
    "id": "is_01",
    "instructions": [
        "Never mention pricing.",
        "Always reference something specific about their company.",
    ],
}

_EMAIL_BAD = "Hi, our tool is very cost-effective and great for companies like yours."
_EMAIL_FIXED = "Hi, congrats on opening your second Ohio assembly line. Our tool helps."


def _simulate_grade(email: str, rules: list[Rule], cfg: Config) -> dict:
    """Simulate grader.py's check -> repair-if-needed -> check -> classify loop.

    This helper exists so test_repair_hold.py can prove the behavior of the
    building blocks without waiting for grader.py (Integration phase). grader.py
    will own this logic in production; this simulation must match it.

    Returns a dict with keys: status, initial, final, still_failing, repaired_body.
    """
    initial = check_email(email, rules, config=cfg)
    failed = [r for r in initial if not r.passed]

    if not failed:
        return {
            "status": "pass",
            "initial": initial,
            "final": initial,
            "still_failing": [],
            "repaired_body": None,
        }

    repaired_body = repair_email(email, failed, _INSTRUCTION_SET, config=cfg)
    final = check_email(repaired_body, rules, config=cfg)
    still_failing_ids = [r.rule_id for r in final if not r.passed]
    status = "held" if still_failing_ids else "pass_after_repair"

    return {
        "status": status,
        "initial": initial,
        "final": final,
        "still_failing": still_failing_ids,
        "repaired_body": repaired_body,
    }


# --------------------------------------------------------------------------- #
# Held behavior
# --------------------------------------------------------------------------- #

def test_held_when_repair_does_not_fix_the_failing_rule(fake_cfg):
    """Core held test: repair returns a draft that still fails -> status is 'held'."""
    check_calls = {"n": 0}

    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            # Semantic check: always fail (rule never satisfied)
            check_calls["n"] += 1
            return {"pass": False, "reason": "email still mentions pricing"}
        else:
            # Repair call: return a draft that still violates the rule
            return {"corrected_email": _EMAIL_BAD}

    set_fake_responder(responder)
    rules = [_RULE_NO_PRICING]
    result = _simulate_grade(_EMAIL_BAD, rules, fake_cfg)

    assert result["status"] == "held"
    assert "no_pricing_aa0001" in result["still_failing"]


def test_held_not_silently_passed(fake_cfg):
    """A held email must not appear as 'pass' or 'pass_after_repair'."""
    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            return {"pass": False, "reason": "still violates pricing rule"}
        return {"corrected_email": _EMAIL_BAD}

    set_fake_responder(responder)
    result = _simulate_grade(_EMAIL_BAD, [_RULE_NO_PRICING], fake_cfg)

    assert result["status"] not in ("pass", "pass_after_repair"), (
        f"held email must not be reported as {result['status']!r}"
    )


def test_held_not_silently_dropped(fake_cfg):
    """A held email must appear in the result — it cannot be absent."""
    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            return {"pass": False, "reason": "violation persists"}
        return {"corrected_email": _EMAIL_BAD}

    set_fake_responder(responder)
    result = _simulate_grade(_EMAIL_BAD, [_RULE_NO_PRICING], fake_cfg)

    # A silently dropped result would have no status key or raise. Neither should happen.
    assert "status" in result
    assert result["status"] == "held"


def test_held_surfaces_correct_rule_ids(fake_cfg):
    """still_failing must list exactly the rule ids that are still not passing."""
    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            return {"pass": False, "reason": "both rules still violated"}
        return {"corrected_email": _EMAIL_BAD}

    set_fake_responder(responder)
    rules = [_RULE_NO_PRICING, _RULE_SPECIFIC_REF]
    result = _simulate_grade(_EMAIL_BAD, rules, fake_cfg)

    assert result["status"] == "held"
    assert set(result["still_failing"]) == {"no_pricing_aa0001", "specific_ref_bb0002"}


def test_held_still_failing_does_not_include_passing_rules(fake_cfg):
    """A rule that passes after repair must not appear in still_failing."""
    call_count = {"check": 0}

    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            call_count["check"] += 1
            rule_judge = (req.get("system") or "")
            if "specific" in rule_judge.lower():
                # specific_ref rule passes after repair
                return {"pass": True, "reason": "specific detail found"}
            # no_pricing rule still fails after repair
            return {"pass": False, "reason": "pricing still mentioned"}
        return {"corrected_email": _EMAIL_FIXED}

    set_fake_responder(responder)
    rules = [_RULE_NO_PRICING, _RULE_SPECIFIC_REF]
    result = _simulate_grade(_EMAIL_BAD, rules, fake_cfg)

    assert result["status"] == "held"
    assert "no_pricing_aa0001" in result["still_failing"]
    assert "specific_ref_bb0002" not in result["still_failing"]


# --------------------------------------------------------------------------- #
# Pass-after-repair behavior (contrast case for held)
# --------------------------------------------------------------------------- #

def test_pass_after_repair_when_all_rules_fixed(fake_cfg):
    """Contrast: if repair fixes all rules, status is 'pass_after_repair', not 'held'."""
    initial_done = {"done": False}

    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            if not initial_done["done"]:
                # Initial check: fail
                return {"pass": False, "reason": "pricing mentioned"}
            else:
                # Post-repair check: pass
                return {"pass": True, "reason": ""}
        # Repair call: mark initial as done so post-repair checks pass
        initial_done["done"] = True
        return {"corrected_email": _EMAIL_FIXED}

    set_fake_responder(responder)
    result = _simulate_grade(_EMAIL_BAD, [_RULE_NO_PRICING], fake_cfg)

    assert result["status"] == "pass_after_repair"
    assert result["still_failing"] == []


def test_clean_email_never_triggers_repair(fake_cfg):
    """An email that passes all rules initially must not call repair at all."""
    repair_calls = {"n": 0}

    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            return {"pass": True, "reason": "compliant"}
        repair_calls["n"] += 1
        return {"corrected_email": "irrelevant"}

    set_fake_responder(responder)
    result = _simulate_grade(_EMAIL_FIXED, [_RULE_NO_PRICING], fake_cfg)

    assert result["status"] == "pass"
    assert repair_calls["n"] == 0, "repair must not be called when initial check passes"


# --------------------------------------------------------------------------- #
# Exactly one repair attempt
# --------------------------------------------------------------------------- #

def test_exactly_one_repair_call_even_when_still_failing(fake_cfg):
    """repair_email is called at most once; the caller decides to hold, not retry."""
    repair_calls = {"n": 0}

    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "pass" in schema_props:
            return {"pass": False, "reason": "still broken"}
        repair_calls["n"] += 1
        return {"corrected_email": _EMAIL_BAD}

    set_fake_responder(responder)
    _simulate_grade(_EMAIL_BAD, [_RULE_NO_PRICING], fake_cfg)

    assert repair_calls["n"] == 1, (
        f"repair must be attempted exactly once; got {repair_calls['n']} call(s)"
    )


# --------------------------------------------------------------------------- #
# Repair call structure
# --------------------------------------------------------------------------- #

def test_repair_includes_original_instructions_in_prompt(fake_cfg):
    """The repair prompt must include the original instruction text."""
    received = {}

    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "corrected_email" in schema_props:
            received["prompt"] = req["prompt"]
            return {"corrected_email": _EMAIL_FIXED}
        return {"pass": False, "reason": "violation"}

    set_fake_responder(responder)
    # Trigger repair path (initial check fails, repair called)
    initial_done = {"done": False}

    def mixed(req):
        schema_props = req["schema"].get("properties", {})
        if "corrected_email" in schema_props:
            received["prompt"] = req["prompt"]
            initial_done["done"] = True
            return {"corrected_email": _EMAIL_FIXED}
        if not initial_done["done"]:
            return {"pass": False, "reason": "violation"}
        return {"pass": True, "reason": ""}

    set_fake_responder(mixed)

    result = _simulate_grade(_EMAIL_BAD, [_RULE_NO_PRICING], fake_cfg)
    assert result["status"] in ("pass_after_repair", "held")

    prompt = received.get("prompt", "")
    assert "Never mention pricing." in prompt, (
        "the repair prompt must contain the original instruction text"
    )


def test_repair_includes_violation_rule_id_and_reason(fake_cfg):
    """The repair prompt must name the failing rule id and its reason."""
    received = {}
    initial_done = {"done": False}

    def responder(req):
        schema_props = req["schema"].get("properties", {})
        if "corrected_email" in schema_props:
            received["prompt"] = req["prompt"]
            initial_done["done"] = True
            return {"corrected_email": _EMAIL_FIXED}
        if not initial_done["done"]:
            return {"pass": False, "reason": "email says cost-effective"}
        return {"pass": True, "reason": ""}

    set_fake_responder(responder)
    _simulate_grade(_EMAIL_BAD, [_RULE_NO_PRICING], fake_cfg)

    prompt = received.get("prompt", "")
    assert "no_pricing_aa0001" in prompt
    assert "cost-effective" in prompt


def test_repair_result_is_a_string(fake_cfg):
    """repair_email must return a plain string, not a dict or None."""
    set_fake_responder(lambda req: (
        {"corrected_email": _EMAIL_FIXED}
        if "corrected_email" in req["schema"].get("properties", {})
        else {"pass": False, "reason": "violation"}
    ))

    failed = [
        RuleResult(
            rule_id="no_pricing_aa0001",
            passed=False,
            reason="pricing mentioned",
            kind="semantic",
            source="semantic",
        )
    ]
    result = repair_email(_EMAIL_BAD, failed, _INSTRUCTION_SET, config=fake_cfg)

    assert isinstance(result, str)
    assert len(result) > 0
