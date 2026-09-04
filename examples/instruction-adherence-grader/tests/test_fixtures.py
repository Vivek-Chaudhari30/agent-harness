"""Tests for fixtures.py — Lane C.

All tests run under MODEL_PROVIDER=fake with no API key.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

import pytest

from src.fixtures import (
    _PLAN,
    build_draft_labels,
    build_seed_corpus,
    generate_fixtures,
    resolve_rules,
)
from src.model_client import reset_fake_responder, set_fake_responder
from src.schemas import derive_rule_id, load_emails, load_instruction_sets


@pytest.fixture(autouse=True)
def _fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_PROVIDER", "fake")
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MODEL_DEBUG_LOG", str(tmp_path / "calls.jsonl"))
    reset_fake_responder()
    yield
    reset_fake_responder()


@pytest.fixture()
def instruction_sets():
    here = os.path.dirname(__file__)
    path = os.path.join(here, "..", "fixtures", "instruction_sets.json")
    return load_instruction_sets(path)["sets"]


@pytest.fixture()
def emails_path():
    here = os.path.dirname(__file__)
    return os.path.join(here, "..", "fixtures", "emails.json")


# --------------------------------------------------------------------------- #
# Plan integrity
# --------------------------------------------------------------------------- #
def test_plan_has_50_entries():
    assert len(_PLAN) == 50


def test_plan_10_per_set():
    counts = Counter(e["set"] for e in _PLAN)
    for sid, n in counts.items():
        assert n == 10, f"{sid!r} has {n} entries, expected 10"


def test_plan_difficulty_distribution():
    diffs = Counter(e["difficulty"] for e in _PLAN)
    # At least 8 clean, 8 single, 4 multiple, 8 borderline.
    assert diffs["clean"] >= 8
    assert diffs["single"] >= 8
    assert diffs["multiple"] >= 4
    assert diffs["borderline"] >= 8


def test_plan_no_real_companies_or_emails():
    text = json.dumps(_PLAN)
    # No email addresses.
    assert "@" not in text or all(
        addr in text for addr in ("@gmail.com", "@anthropic")
    ) is False
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text), "found an email address in plan"
    # No '.com' in company names.
    for entry in _PLAN:
        company = entry["recipient"].get("company", "")
        assert ".com" not in company.lower(), f"company name looks like a URL: {company}"


# --------------------------------------------------------------------------- #
# Adversarial coverage requirements from Phase 3
# --------------------------------------------------------------------------- #
def test_implied_pricing_case_present():
    """At least one email must use the implied_pricing_no_banned_word adversarial tag."""
    tagged = [e for e in _PLAN if "implied_pricing_no_banned_word" in e.get("tags", [])]
    assert tagged, "no implied-pricing adversarial case in plan"


def test_namedrop_boilerplate_vs_specific_present():
    """One boilerplate name-drop AND one specific/checkable reference must exist."""
    has_boilerplate = any("namedrop_boilerplate" in e.get("tags", []) for e in _PLAN)
    has_specific = any("specific_checkable" in e.get("tags", []) for e in _PLAN)
    assert has_boilerplate, "no namedrop_boilerplate case in plan"
    assert has_specific, "no specific_checkable case in plan"


def test_indirect_question_case_present():
    """At least one email must use the indirect_question_no_qmark adversarial tag."""
    tagged = [e for e in _PLAN if "indirect_question_no_qmark" in e.get("tags", [])]
    assert tagged, "no indirect-question adversarial case in plan"


def test_corporate_tone_drift_present():
    """At least one email must drift to corporate tone against a casual instruction."""
    tagged = [e for e in _PLAN if "corporate_tone_drift" in e.get("tags", [])]
    assert tagged, "no corporate_tone_drift case in plan"


def test_near_limit_word_counts_present():
    """At least one tagged under-limit and one over-limit email must exist."""
    under = [e for e in _PLAN if "near_limit_word_count_under" in e.get("tags", [])]
    over = [e for e in _PLAN if "near_limit_word_count_over" in e.get("tags", [])]
    assert under, "no near_limit_word_count_under case in plan"
    assert over, "no near_limit_word_count_over case in plan"


# --------------------------------------------------------------------------- #
# Seed corpus shape
# --------------------------------------------------------------------------- #
def test_seed_corpus_produces_50_records(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    assert len(records) == 50


def test_seed_corpus_ids_unique(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_seed_corpus_ids_sequential(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    for i, r in enumerate(records):
        assert r["id"] == f"em_{i + 1:03d}"


def test_seed_corpus_schema_valid(instruction_sets):
    """build_seed_corpus output must pass the frozen schema validator."""
    records = build_seed_corpus(instruction_sets)
    data = {"version": 1, "emails": records}
    raw = json.dumps(data)
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        f.write(raw)
        f.flush()
        load_emails(f.name)


def test_seed_corpus_planted_violations_are_real_rule_ids(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    by_set = {s["id"]: s for s in instruction_sets}
    for record in records:
        iset = by_set[record["instruction_set_id"]]
        valid_ids = {derive_rule_id(i) for i in iset["instructions"]}
        for vid in record["planted_violations"]:
            assert vid in valid_ids, (
                f"planted_violation {vid!r} in {record['id']} "
                f"is not a valid rule id for {iset['id']}"
            )


def test_seed_corpus_bodies_non_empty(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    for r in records:
        assert isinstance(r["body"], str) and r["body"].strip(), (
            f"{r['id']} has an empty body"
        )


def test_seed_corpus_no_real_companies(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    text = json.dumps(records)
    assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text), (
        "real email address found in fixture corpus"
    )


def test_seed_corpus_generation_mode(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    for r in records:
        gen = r["generation"]
        assert gen["mode"] in ("compliant", "violating")
        if r["planted_violations"]:
            assert gen["mode"] == "violating"
        else:
            assert gen["mode"] == "compliant"


# --------------------------------------------------------------------------- #
# Draft labels shape
# --------------------------------------------------------------------------- #
def test_draft_labels_complete(instruction_sets):
    """Every (email_id, rule_id) pair must have exactly one label."""
    by_set = {s["id"]: s for s in instruction_sets}
    records = build_seed_corpus(instruction_sets)
    labels = build_draft_labels(instruction_sets)

    expected: set[tuple[str, str]] = set()
    for r in records:
        iset = by_set[r["instruction_set_id"]]
        for ins in iset["instructions"]:
            expected.add((r["id"], derive_rule_id(ins)))

    got: set[tuple[str, str]] = set()
    for lbl in labels:
        key = (lbl.email_id, lbl.rule_id)
        assert key not in got, f"duplicate label for {key}"
        got.add(key)

    missing = expected - got
    assert not missing, f"missing labels: {sorted(missing)[:5]}"


def test_draft_labels_no_reviewed_or_overturned(instruction_sets):
    labels = build_draft_labels(instruction_sets)
    for lbl in labels:
        assert lbl.reviewed is False
        assert lbl.overturned is False


def test_draft_labels_count(instruction_sets):
    records = build_seed_corpus(instruction_sets)
    labels = build_draft_labels(instruction_sets)
    by_set = {s["id"]: s for s in instruction_sets}
    expected_total = sum(
        len(by_set[r["instruction_set_id"]]["instructions"]) for r in records
    )
    assert len(labels) == expected_total


# --------------------------------------------------------------------------- #
# Live generator (fake provider)
# --------------------------------------------------------------------------- #
def test_generate_fixtures_returns_records(instruction_sets):
    set_fake_responder(lambda req: {"email": "Hi Acme, hope all is well.\n\nBest,\nAlex\nCorp"})
    records = generate_fixtures(instruction_sets, per_set=2)
    assert len(records) == 10  # 5 sets × 2
    for r in records:
        assert "body" in r and r["body"]
        assert "planted_violations" in r


def test_generate_fixtures_planted_violations_are_real_rule_ids(instruction_sets):
    set_fake_responder(lambda req: {"email": "Test email body for grader.\n\nBest,\nAlex\nCorp"})
    records = generate_fixtures(instruction_sets, per_set=1)
    by_set = {s["id"]: s for s in instruction_sets}
    for record in records:
        iset = by_set[record["instruction_set_id"]]
        valid_ids = {derive_rule_id(i) for i in iset["instructions"]}
        for vid in record["planted_violations"]:
            assert vid in valid_ids, f"generated record has invalid planted violation: {vid!r}"


def test_generate_fixtures_mode_matches_violations(instruction_sets):
    set_fake_responder(lambda req: {"email": "Best,\nAlex\nCorp"})
    records = generate_fixtures(instruction_sets, per_set=1)
    for r in records:
        if r["planted_violations"]:
            assert r["generation"]["mode"] == "violating"
        else:
            assert r["generation"]["mode"] == "compliant"


# --------------------------------------------------------------------------- #
# Committed emails.json (if it exists)
# --------------------------------------------------------------------------- #
def test_committed_emails_json_valid(emails_path):
    if not os.path.exists(emails_path):
        pytest.skip("fixtures/emails.json not yet generated")
    data = load_emails(emails_path)
    assert len(data["emails"]) == 50


def test_committed_emails_json_adversarial_cases(emails_path, instruction_sets):
    if not os.path.exists(emails_path):
        pytest.skip("fixtures/emails.json not yet generated")
    data = load_emails(emails_path)
    emails = data["emails"]
    tags_all = []
    for e in emails:
        tags_all.extend(e.get("adversarial_tags", []))
    assert "implied_pricing_no_banned_word" in tags_all
    assert "namedrop_boilerplate" in tags_all
    assert "specific_checkable" in tags_all
    assert "indirect_question_no_qmark" in tags_all
    assert "corporate_tone_drift" in tags_all
    assert "near_limit_word_count_under" in tags_all
    assert "near_limit_word_count_over" in tags_all
