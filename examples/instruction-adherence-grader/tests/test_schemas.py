"""Phase 0 tests for schemas: rule id derivation, round-trips, and loaders."""

from __future__ import annotations

import json
import os

import pytest

from src import schemas
from src.schemas import (
    BatchRunResult,
    EmailRunResult,
    Label,
    RuleResult,
    SchemaError,
    batch_run_result_from_dict,
    batch_run_result_to_dict,
    derive_rule_id,
    label_from_dict,
    label_to_dict,
)

_INSTRUCTION_SETS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures",
    "instruction_sets.json",
)


def test_derive_rule_id_is_stable_and_content_based():
    a = derive_rule_id("Keep it under 90 words.")
    b = derive_rule_id("Keep it under 90 words.")
    assert a == b  # stable
    assert a != derive_rule_id("Keep it under 75 words.")  # content-sensitive
    assert a.startswith("keep_it_under_90_words")  # readable


def test_derive_rule_id_ignores_surrounding_whitespace():
    assert derive_rule_id("  No exclamation marks. ") == derive_rule_id(
        "No exclamation marks."
    )


def test_derive_rule_id_unique_within_a_set():
    obj = schemas.load_instruction_sets(_INSTRUCTION_SETS)
    for s in obj["sets"]:
        ids = [derive_rule_id(i) for i in s["instructions"]]
        assert len(ids) == len(set(ids)), f"duplicate rule id in set {s['id']}"


def test_rule_result_round_trip():
    r = RuleResult(rule_id="r1", passed=False, reason="97 words", kind="deterministic", source="deterministic")
    assert schemas.rule_result_from_dict(schemas.rule_result_to_dict(r)) == r


def test_label_round_trip():
    lbl = Label(
        email_id="em_001",
        rule_id="r1",
        violated=True,
        reason="over cap",
        kind="deterministic",
        confidence="low",
        reviewed=True,
        overturned=True,
    )
    assert label_from_dict(label_to_dict(lbl)) == lbl


def test_batch_run_result_round_trip():
    email = EmailRunResult(
        email_id="em_001",
        instruction_set_id="is_01",
        initial_results=[RuleResult("r1", False, "bad", "semantic", "semantic")],
        repair_attempted=True,
        repaired_body="fixed",
        final_results=[RuleResult("r1", True, "", "semantic", "semantic")],
        status="pass_after_repair",
        still_failing=[],
    )
    batch = BatchRunResult(
        run_id="run1",
        config={"model": "x"},
        emails=[email],
        summary={"n_emails": 1},
    )
    restored = batch_run_result_from_dict(batch_run_result_to_dict(batch))
    assert restored == batch


def test_instruction_sets_fixture_loads_and_validates():
    obj = schemas.load_instruction_sets(_INSTRUCTION_SETS)
    assert obj["version"] == 1
    assert len(obj["sets"]) == 5


def test_loader_raises_on_wrong_version(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"version": 2, "sets": []}))
    with pytest.raises(SchemaError):
        schemas.load_instruction_sets(str(p))


def test_run_loader_rejects_missing_version(tmp_path):
    p = tmp_path / "run.json"
    p.write_text(json.dumps({"run_id": "x", "emails": []}))
    with pytest.raises(SchemaError):
        schemas.load_run(str(p))
