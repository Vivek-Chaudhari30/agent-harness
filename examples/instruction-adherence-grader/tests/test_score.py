"""Tests for src/score.py. (Lane D)

Fixture data lives in tests/data/ as contract-shaped JSON, written by Lane D
rather than waiting for Lane C/B/A to produce real outputs. This forces the
scorer to be correct against the contract, not against whatever other lanes emit.

Test layout:
  - Sign-flip guard: must fail if rule_result_violated() inverts its logic
  - Incomplete ground truth: score.py must raise, not silently score a subset
  - initial_results vs final_results: assert the right field is used
  - Adherence rate: computed correctly for pass / pass_after_repair / held
  - Grader metrics: TP/FP/FN/TN, P/R/F1 aggregate + by_kind + by_rule
"""

from __future__ import annotations

import json
import os

import pytest

from src.schemas import (
    BatchRunResult,
    EmailRunResult,
    Label,
    RuleResult,
    batch_run_result_from_dict,
    load_labels,
    load_run,
)
from src.score import adherence, grader_metrics, rule_result_violated

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SAMPLE_RUN = os.path.join(DATA_DIR, "sample_run.json")
SAMPLE_LABELS = os.path.join(DATA_DIR, "sample_labels_ground_truth.json")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_result(rule_id: str, passed: bool, kind: str = "deterministic") -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        passed=passed,
        reason="" if passed else "synthetic violation",
        kind=kind,
        source="deterministic" if kind == "deterministic" else "semantic",
    )


def _make_label(email_id: str, rule_id: str, violated: bool, kind: str = "deterministic") -> Label:
    return Label(
        email_id=email_id,
        rule_id=rule_id,
        violated=violated,
        reason="synthetic",
        kind=kind,
        confidence="high",
        reviewed=True,
        overturned=False,
    )


def _ground_truth_dict(labels: list[Label]) -> dict:
    from src.schemas import label_to_dict
    return {
        "version": 1,
        "provenance": {"kind": "human_reviewed", "model": "fake", "labeler_prompt_sha": "x",
                       "reviewed_at": None, "reviewer_note": ""},
        "labels": [label_to_dict(lbl) for lbl in labels],
    }


# --------------------------------------------------------------------------- #
# Sign-flip guard
# --------------------------------------------------------------------------- #

def test_rule_result_violated_true_when_not_passed():
    """passed=False means a violation; violated must be True."""
    r = _make_result("r", passed=False)
    assert rule_result_violated(r) is True


def test_rule_result_violated_false_when_passed():
    """passed=True means compliant; violated must be False."""
    r = _make_result("r", passed=True)
    assert rule_result_violated(r) is False


def test_sign_flip_would_be_caught():
    """This test encodes the polarity contract.

    If rule_result_violated() were changed to `return result.passed` (the wrong sign),
    both tests above would fail. This docstring names the invariant explicitly so
    a future reader understands what these tests are protecting against.
    """
    compliant = _make_result("r", passed=True)
    violation = _make_result("r", passed=False)
    assert rule_result_violated(compliant) != rule_result_violated(violation)
    assert rule_result_violated(violation) is True
    assert rule_result_violated(compliant) is False


# --------------------------------------------------------------------------- #
# Incomplete ground truth
# --------------------------------------------------------------------------- #

def test_grader_metrics_raises_on_missing_label():
    """score.py must raise on incomplete ground truth, not silently score a subset."""
    pre_repair = {
        "em_001": [_make_result("rule_a", True), _make_result("rule_b", False)],
    }
    # Only cover rule_a, not rule_b -> incomplete
    labels = [_make_label("em_001", "rule_a", False)]
    gt = _ground_truth_dict(labels)

    with pytest.raises(ValueError, match="incomplete"):
        grader_metrics(pre_repair, gt)


def test_grader_metrics_raises_on_missing_email():
    """Missing email_id in labels is also an incomplete ground truth."""
    pre_repair = {
        "em_001": [_make_result("rule_a", True)],
        "em_002": [_make_result("rule_a", False)],
    }
    # Only em_001 labeled
    labels = [_make_label("em_001", "rule_a", False)]
    gt = _ground_truth_dict(labels)

    with pytest.raises(ValueError, match="incomplete"):
        grader_metrics(pre_repair, gt)


# --------------------------------------------------------------------------- #
# initial_results vs final_results guard
# --------------------------------------------------------------------------- #

def test_score_uses_initial_not_final_results():
    """grader_metrics must compare initial_results (pre-repair), not final_results.

    This test constructs an email where initial and final results differ and verifies
    that score.py is called with the initial field. The assertion is structural:
    the caller must extract initial_results; grader_metrics itself takes a plain dict.
    We simulate the caller's extraction logic and confirm the TP count changes.
    """
    # initial: rule_a=failed (violation). final: rule_a=passed (after repair).
    initial = [_make_result("rule_a", passed=False)]
    final = [_make_result("rule_a", passed=True)]

    labels = [_make_label("em_001", "rule_a", violated=True)]  # ground truth: violation
    gt = _ground_truth_dict(labels)

    # Using initial_results: grader caught the violation -> TP
    m_initial = grader_metrics({"em_001": initial}, gt)
    assert m_initial["aggregate"]["tp"] == 1
    assert m_initial["aggregate"]["fp"] == 0
    assert m_initial["aggregate"]["fn"] == 0

    # Using final_results (wrong): grader appears clean -> FN (inflated recall miss)
    m_final = grader_metrics({"em_001": final}, gt)
    assert m_final["aggregate"]["fn"] == 1  # violation missed
    assert m_final["aggregate"]["tp"] == 0  # no true positives


# --------------------------------------------------------------------------- #
# Adherence rate
# --------------------------------------------------------------------------- #

def test_adherence_from_fixture():
    """Load sample_run.json and verify adherence stats match designed values."""
    batch = load_run(SAMPLE_RUN)
    stats = adherence(batch)

    assert stats["n_emails"] == 5
    assert stats["passed_first_try"] == 2   # em_001, em_004
    assert stats["passed_after_repair"] == 2  # em_002, em_005
    assert stats["held"] == 1               # em_003
    assert stats["adherence_rate"] == 0.8

    holds = stats["holds"]
    assert len(holds) == 1
    assert holds[0]["email_id"] == "em_003"
    assert "rule_sem" in holds[0]["still_failing"]


def test_adherence_empty_batch():
    batch = BatchRunResult(run_id="x", config={}, emails=[], summary={})
    stats = adherence(batch)
    assert stats["n_emails"] == 0
    assert stats["adherence_rate"] == 0.0
    assert stats["holds"] == []


def test_adherence_all_pass():
    emails = [
        EmailRunResult("e1", "is_01", [], False, None, [], "pass", []),
        EmailRunResult("e2", "is_01", [], False, None, [], "pass", []),
    ]
    batch = BatchRunResult("r", {}, emails, {})
    stats = adherence(batch)
    assert stats["adherence_rate"] == 1.0
    assert stats["held"] == 0


def test_adherence_all_held():
    emails = [
        EmailRunResult("e1", "is_01", [], True, "x", [], "held", ["rule_a"]),
        EmailRunResult("e2", "is_01", [], True, "x", [], "held", ["rule_b", "rule_c"]),
    ]
    batch = BatchRunResult("r", {}, emails, {})
    stats = adherence(batch)
    assert stats["adherence_rate"] == 0.0
    assert len(stats["holds"]) == 2


# --------------------------------------------------------------------------- #
# Grader metrics: TP/FP/FN/TN, P/R/F1
# --------------------------------------------------------------------------- #

def test_grader_metrics_from_fixtures():
    """Load sample fixtures and verify the expected confusion matrix.

    Designed values (see tests/data/README):
      rule_det (deterministic): TP=1, FP=1, FN=1, TN=2
      rule_sem (semantic):      TP=1, FP=0, FN=0, TN=4
      aggregate:                TP=2, FP=1, FN=1, TN=6
    """
    batch = load_run(SAMPLE_RUN)
    ground_truth = load_labels(SAMPLE_LABELS)

    pre_repair = {e.email_id: e.initial_results for e in batch.emails}
    metrics = grader_metrics(pre_repair, ground_truth)

    agg = metrics["aggregate"]
    assert agg["tp"] == 2
    assert agg["fp"] == 1
    assert agg["fn"] == 1
    assert agg["tn"] == 6
    assert abs(agg["precision"] - 2 / 3) < 0.001
    assert abs(agg["recall"] - 2 / 3) < 0.001
    assert abs(agg["f1"] - 2 / 3) < 0.001
    assert agg["support"] == 10

    det = metrics["by_kind"]["deterministic"]
    assert det["tp"] == 1
    assert det["fp"] == 1
    assert det["fn"] == 1
    assert det["tn"] == 2
    assert abs(det["precision"] - 0.5) < 0.001
    assert abs(det["recall"] - 0.5) < 0.001

    sem = metrics["by_kind"]["semantic"]
    assert sem["tp"] == 1
    assert sem["fp"] == 0
    assert sem["fn"] == 0
    assert sem["tn"] == 4
    assert abs(sem["precision"] - 1.0) < 0.001
    assert abs(sem["recall"] - 1.0) < 0.001
    assert abs(sem["f1"] - 1.0) < 0.001

    by_rule = metrics["by_rule"]
    assert "rule_det" in by_rule
    assert "rule_sem" in by_rule
    assert by_rule["rule_det"]["tp"] == 1
    assert by_rule["rule_sem"]["tp"] == 1


def test_grader_metrics_label_counts():
    """n_labels, n_reviewed, n_overturned are counted correctly."""
    batch = load_run(SAMPLE_RUN)
    ground_truth = load_labels(SAMPLE_LABELS)
    pre_repair = {e.email_id: e.initial_results for e in batch.emails}
    metrics = grader_metrics(pre_repair, ground_truth)

    assert metrics["n_labels"] == 10       # 5 emails × 2 rules
    assert metrics["n_reviewed"] == 10     # all reviewed in synthetic fixture
    assert metrics["n_overturned"] == 1    # em_005 rule_det was overturned


def test_grader_metrics_perfect_grader():
    """When grader matches ground truth exactly, precision=recall=F1=1.0."""
    pre_repair = {
        "em_a": [_make_result("rule_x", passed=False)],  # correctly flags violation
        "em_b": [_make_result("rule_x", passed=True)],   # correctly clears compliant
    }
    labels = [
        _make_label("em_a", "rule_x", violated=True),
        _make_label("em_b", "rule_x", violated=False),
    ]
    gt = _ground_truth_dict(labels)
    metrics = grader_metrics(pre_repair, gt)

    agg = metrics["aggregate"]
    assert agg["tp"] == 1
    assert agg["fp"] == 0
    assert agg["fn"] == 0
    assert agg["tn"] == 1
    assert agg["precision"] == 1.0
    assert agg["recall"] == 1.0
    assert agg["f1"] == 1.0


def test_grader_metrics_all_false_negatives():
    """Grader misses all violations: recall=0, F1=0."""
    pre_repair = {"em_a": [_make_result("rule_x", passed=True)]}  # grader says OK
    labels = [_make_label("em_a", "rule_x", violated=True)]       # actually violated
    gt = _ground_truth_dict(labels)
    metrics = grader_metrics(pre_repair, gt)

    agg = metrics["aggregate"]
    assert agg["tp"] == 0
    assert agg["fn"] == 1
    assert agg["recall"] == 0.0
    assert agg["f1"] == 0.0


def test_grader_metrics_positive_class_documented():
    """The positive_class field must be 'violation_present'."""
    pre_repair = {"e": [_make_result("r", True)]}
    labels = [_make_label("e", "r", False)]
    gt = _ground_truth_dict(labels)
    m = grader_metrics(pre_repair, gt)
    assert m["positive_class"] == "violation_present"
