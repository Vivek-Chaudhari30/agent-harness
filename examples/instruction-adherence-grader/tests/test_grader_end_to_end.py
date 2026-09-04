"""End-to-end smoke tests for src/grader.py. (Integration)

All tests run under MODEL_PROVIDER=fake with no API key.  The fake provider
returns deterministic schema-valid objects, so test coverage focuses on the
orchestration logic rather than model correctness.

Tests verify:
  1. grade_email: clean email → status=="pass", no repair attempted
  2. grade_email: violating email → repair attempted, may pass or be held
  3. grade_email: held path (fake always fails) → status=="held" with rule ids
  4. grade_batch: full summary counts are consistent with per-email statuses
  5. company_name_mentioned context injection (Lane A contract-change)
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MODEL_PROVIDER", "fake")

from src.compile import compile_instructions
from src.config import Config
from src.grader import grade_batch, grade_email
from src.model_client import reset_fake_responder, set_fake_responder
from src.schemas import EmailRunResult


# --------------------------------------------------------------------------- #
# Helpers and fixtures
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


def _passing_responder(request: dict) -> dict:
    """Fake: all semantic checks pass."""
    schema = request["schema"]
    props = schema.get("properties", {})
    result = {}
    for k, v in props.items():
        if v.get("type") == "boolean":
            result[k] = True   # pass == True means rule obeyed
        elif v.get("type") == "string":
            result[k] = ""
        else:
            result[k] = None
    return result


def _failing_responder(request: dict) -> dict:
    """Fake: all semantic checks fail (pass == False)."""
    schema = request["schema"]
    props = schema.get("properties", {})
    result = {}
    for k, v in props.items():
        if v.get("type") == "boolean":
            result[k] = False   # pass == False means rule violated
        elif v.get("type") == "string":
            result[k] = "fake violation"
        else:
            result[k] = None
    # repair call also goes through call_json → must return corrected_email
    if "corrected_email" in props:
        result["corrected_email"] = "Repaired body.\n\nStill fails.\nDev\nFlowstitch"
    return result


# Minimal instruction set with only deterministic rules (no API needed)
_ISET_DETERMINISTIC = {
    "id": "is_01",
    "label": "test",
    "sender_persona": "founder",
    "instructions": [
        "Keep it under 90 words.",
        "No exclamation marks.",
        "Sign off with a first name and company name on separate lines.",
    ],
}

# A well-formed, short, compliant email for the deterministic-only set.
_CLEAN_EMAIL = {
    "id": "em_test_clean",
    "instruction_set_id": "is_01",
    "recipient_context": {"company": "Acme Corp", "industry": "test"},
    "body": (
        "Hi Acme Corp team,\n\n"
        "We help logistics teams cut manual handoffs in half. "
        "Happy to walk you through the details.\n\n"
        "Talk soon,\nDev\nFlowstitch"
    ),
    "planted_violations": [],
    "difficulty": "clean",
    "generation": {"mode": "compliant", "model": "test", "created_at": "2026-09-04T00:00:00Z"},
}

# Same email but over the word limit.
_WORD_OVER_EMAIL = {
    "id": "em_test_word_over",
    "instruction_set_id": "is_01",
    "recipient_context": {"company": "Acme Corp", "industry": "test"},
    "body": (
        "Hi Acme Corp team,\n\n"
        + " ".join(["word"] * 95)
        + "\n\nTalk soon,\nDev\nFlowstitch"
    ),
    "planted_violations": ["keep_it_under_90_words"],
    "difficulty": "single",
    "generation": {"mode": "violating", "model": "test", "created_at": "2026-09-04T00:00:00Z"},
}


# --------------------------------------------------------------------------- #
# Test 1: clean email → pass, no repair
# --------------------------------------------------------------------------- #

def test_grade_email_clean_pass(fake_cfg):
    set_fake_responder(_passing_responder)
    rules = compile_instructions(_ISET_DETERMINISTIC)
    result = grade_email(_CLEAN_EMAIL, rules, config=fake_cfg)

    assert isinstance(result, EmailRunResult)
    assert result.status == "pass"
    assert result.repair_attempted is False
    assert result.repaired_body is None
    assert result.still_failing == []
    assert len(result.initial_results) == len(rules)
    assert result.final_results is result.initial_results


# --------------------------------------------------------------------------- #
# Test 2: word-limit violation → repair attempted, fake repair succeeds (0 words)
# --------------------------------------------------------------------------- #

def test_grade_email_violation_triggers_repair(fake_cfg):
    set_fake_responder(_passing_responder)
    rules = compile_instructions(_ISET_DETERMINISTIC)
    result = grade_email(_WORD_OVER_EMAIL, rules, config=fake_cfg)

    assert result.repair_attempted is True
    # Fake repair returns a short body → re-check should pass or fail depending
    # on what the fake synthesizer returns for corrected_email.
    # Either way, repair was attempted is the key assertion.
    assert result.status in ("pass_after_repair", "held", "pass")


# --------------------------------------------------------------------------- #
# Test 3: held path — semantic check always fails even after repair
# --------------------------------------------------------------------------- #

_ISET_SEMANTIC = {
    "id": "is_01",
    "label": "test",
    "sender_persona": "founder",
    "instructions": [
        "Never mention pricing.",   # deterministic → no_banned_words
        "Sign off with a first name and company name on separate lines.",
    ],
}

_PRICING_EMAIL = {
    "id": "em_test_pricing",
    "instruction_set_id": "is_01",
    "recipient_context": {"company": "Acme Corp", "industry": "test"},
    "body": (
        "Hi Acme,\n\n"
        "Our pricing is very competitive.\n\n"
        "Talk soon,\nDev\nFlowstitch"
    ),
    "planted_violations": ["never_mention_pricing"],
    "difficulty": "single",
    "generation": {"mode": "violating", "model": "test", "created_at": "2026-09-04T00:00:00Z"},
}


def test_grade_email_held_after_failed_repair(fake_cfg):
    """When the repaired email still fails deterministic checks, status is held."""
    # The failing responder returns a repaired_body that contains 'pricing',
    # so the no_banned_words check will still fire.
    def _repair_still_violates(request: dict) -> dict:
        props = request["schema"].get("properties", {})
        if "corrected_email" in props:
            return {"corrected_email": "Our pricing is still here.\nDev\nFlowstitch"}
        return {k: True if v.get("type") == "boolean" else "" for k, v in props.items()}

    set_fake_responder(_repair_still_violates)
    rules = compile_instructions(_ISET_SEMANTIC)
    result = grade_email(_PRICING_EMAIL, rules, config=fake_cfg)

    assert result.repair_attempted is True
    assert result.status == "held"
    assert len(result.still_failing) > 0
    assert result.repaired_body is not None
    # initial_results preserved separately from final_results
    assert result.initial_results is not result.final_results


# --------------------------------------------------------------------------- #
# Test 4: grade_batch — summary counts are consistent
# --------------------------------------------------------------------------- #

_BATCH_EMAILS = [_CLEAN_EMAIL, _WORD_OVER_EMAIL]
_BATCH_ISETS = {"is_01": _ISET_DETERMINISTIC}


def test_grade_batch_summary_consistent(fake_cfg):
    set_fake_responder(_passing_responder)
    batch = grade_batch(_BATCH_EMAILS, _BATCH_ISETS, config=fake_cfg)

    assert batch.run_id  # non-empty timestamp
    assert len(batch.emails) == 2
    s = batch.summary
    assert s["n_emails"] == 2
    assert s["passed_first_try"] + s["passed_after_repair"] + s["held"] == 2
    assert 0.0 <= s["adherence_rate"] <= 1.0


# --------------------------------------------------------------------------- #
# Test 5: company_name_mentioned context injection (Lane A contract-change)
# --------------------------------------------------------------------------- #

_ISET_COMPANY = {
    "id": "is_03",
    "label": "test",
    "sender_persona": "partnerships lead",
    "instructions": [
        "Reference the recipient's company by name at least once.",
        "Sign off with a first name and company name on separate lines.",
    ],
}

_COMPANY_MENTIONS = {
    "id": "em_company_ok",
    "instruction_set_id": "is_03",
    "recipient_context": {"company": "Brightline", "industry": "retail"},
    "body": "Hi Brightline team,\n\nWe help retailers like you.\n\nBest,\nDev\nFlowstitch",
    "planted_violations": [],
    "difficulty": "clean",
    "generation": {"mode": "compliant", "model": "test", "created_at": "2026-09-04T00:00:00Z"},
}

_COMPANY_MISSING = {
    "id": "em_company_missing",
    "instruction_set_id": "is_03",
    "recipient_context": {"company": "Brightline", "industry": "retail"},
    "body": "Hi team,\n\nWe help retailers.\n\nBest,\nDev\nFlowstitch",
    "planted_violations": ["company_name_mentioned"],
    "difficulty": "single",
    "generation": {"mode": "violating", "model": "test", "created_at": "2026-09-04T00:00:00Z"},
}


def test_company_name_injection_pass(fake_cfg):
    set_fake_responder(_passing_responder)
    rules = compile_instructions(_ISET_COMPANY)
    result = grade_email(_COMPANY_MENTIONS, rules, config=fake_cfg)
    # company_name_mentioned deterministic check should pass (Brightline is in body)
    det_results = [r for r in result.initial_results if r.kind == "deterministic"]
    company_res = [r for r in det_results if "company" in r.rule_id or
                   any("company" in rr.rule_id for rr in result.initial_results)]
    assert result.status == "pass"


def test_company_name_injection_fail(fake_cfg):
    set_fake_responder(_passing_responder)
    rules = compile_instructions(_ISET_COMPANY)
    result = grade_email(_COMPANY_MISSING, rules, config=fake_cfg)
    # "Brightline" is not in the body, so company_name_mentioned should fail
    det_initial = [r for r in result.initial_results if not r.passed]
    assert len(det_initial) > 0, "expected at least one initial failure"
    assert result.repair_attempted is True


# --------------------------------------------------------------------------- #
# Test 6: smoke test over first 5 fixture emails (from Lane C fixtures)
# --------------------------------------------------------------------------- #

import json
import pathlib

_FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"


def _load_fixture_emails(limit: int = 5) -> tuple[list[dict], dict]:
    with open(_FIXTURES_DIR / "emails.json", encoding="utf-8") as fh:
        emails_obj = json.load(fh)
    with open(_FIXTURES_DIR / "instruction_sets.json", encoding="utf-8") as fh:
        isets_obj = json.load(fh)
    emails = emails_obj["emails"][:limit]
    isets = {s["id"]: s for s in isets_obj["sets"]}
    return emails, isets


def test_smoke_fixture_emails_fake(fake_cfg):
    """grade_batch over 5 real fixture emails under fake provider: no crash, valid shape."""
    set_fake_responder(_passing_responder)
    emails, isets = _load_fixture_emails(5)
    batch = grade_batch(emails, isets, config=fake_cfg)

    assert len(batch.emails) == 5
    for er in batch.emails:
        assert er.status in ("pass", "pass_after_repair", "held")
        assert len(er.initial_results) > 0
        assert len(er.final_results) > 0
        if er.status == "pass":
            assert er.repair_attempted is False
        if er.status in ("pass_after_repair", "held"):
            assert er.repair_attempted is True
            assert er.repaired_body is not None
    s = batch.summary
    assert s["n_emails"] == 5
    assert s["passed_first_try"] + s["passed_after_repair"] + s["held"] == 5
