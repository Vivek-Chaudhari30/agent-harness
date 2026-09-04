"""Tests for labeler.py — Lane C.

All tests run under MODEL_PROVIDER=fake with no API key.
"""

from __future__ import annotations

import importlib
import os

import pytest

from src.model_client import reset_fake_responder, set_fake_responder
from src.schemas import Label, derive_rule_id

_INSTRUCTION_SET = {
    "id": "is_01",
    "label": "casual founder-led outbound",
    "sender_persona": "founder",
    "instructions": [
        "Never mention pricing.",
        "Keep it under 90 words.",
        "No exclamation marks.",
    ],
}


@pytest.fixture(autouse=True)
def _fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_PROVIDER", "fake")
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MODEL_DEBUG_LOG", str(tmp_path / "calls.jsonl"))
    reset_fake_responder()
    yield
    reset_fake_responder()


# --------------------------------------------------------------------------- #
# Isolation guarantee: labeler must not import semantic_check
# --------------------------------------------------------------------------- #
def test_labeler_does_not_import_semantic_check():
    """Fail if labeler.py imports semantic_check at module level or on call.

    A labeler that shares the checker's judge prompts does not provide an
    independent signal: it would just measure whether the grader agrees with
    itself. This test exists so that separation cannot rot later.
    """
    import sys

    # Remove any prior import to force a fresh module load.
    for mod in list(sys.modules.keys()):
        if "labeler" in mod:
            del sys.modules[mod]
    for mod in list(sys.modules.keys()):
        if "semantic_check" in mod:
            del sys.modules[mod]

    import src.labeler  # noqa: F401 (side-effectful import)

    # After importing labeler, semantic_check must NOT be in sys.modules.
    assert "src.semantic_check" not in sys.modules, (
        "labeler.py imported src.semantic_check; the blind-labeler isolation is broken"
    )
    assert "semantic_check" not in sys.modules, (
        "labeler.py imported semantic_check; the blind-labeler isolation is broken"
    )


# --------------------------------------------------------------------------- #
# Basic shape
# --------------------------------------------------------------------------- #
def test_label_email_returns_one_label_per_rule():
    from src.labeler import label_email

    def responder(req):
        return {
            "verdicts": [
                {"rule_number": 1, "violated": False, "reason": "No pricing mentioned.", "confidence": "high"},
                {"rule_number": 2, "violated": True, "reason": "101 words, over the 90-word cap.", "confidence": "high"},
                {"rule_number": 3, "violated": False, "reason": "No exclamation marks found.", "confidence": "high"},
            ]
        }

    set_fake_responder(responder)
    labels = label_email("Test email body.", _INSTRUCTION_SET)
    assert len(labels) == 3
    for lbl in labels:
        assert isinstance(lbl, Label)


def test_label_email_returns_correct_rule_ids():
    from src.labeler import label_email

    set_fake_responder(lambda req: {
        "verdicts": [
            {"rule_number": i + 1, "violated": False, "reason": "ok", "confidence": "high"}
            for i in range(3)
        ]
    })
    labels = label_email("Some email.", _INSTRUCTION_SET)
    expected_ids = [derive_rule_id(ins) for ins in _INSTRUCTION_SET["instructions"]]
    assert [lbl.rule_id for lbl in labels] == expected_ids


def test_label_email_violated_and_reason_propagated():
    from src.labeler import label_email

    set_fake_responder(lambda req: {
        "verdicts": [
            {"rule_number": 1, "violated": True, "reason": "Mentions pricing.", "confidence": "high"},
            {"rule_number": 2, "violated": False, "reason": "Within word limit.", "confidence": "high"},
            {"rule_number": 3, "violated": False, "reason": "No exclamations.", "confidence": "high"},
        ]
    })
    labels = label_email("Our pricing is $50/month.", _INSTRUCTION_SET)
    assert labels[0].violated is True
    assert "pricing" in labels[0].reason.lower()
    assert labels[1].violated is False


def test_label_email_confidence_low_propagated():
    from src.labeler import label_email

    set_fake_responder(lambda req: {
        "verdicts": [
            {"rule_number": 1, "violated": True, "reason": "Borderline implied pricing.", "confidence": "low"},
            {"rule_number": 2, "violated": False, "reason": "Counts as within limit.", "confidence": "high"},
            {"rule_number": 3, "violated": False, "reason": "Clean.", "confidence": "high"},
        ]
    })
    labels = label_email("Our solution pays for itself.", _INSTRUCTION_SET)
    assert labels[0].confidence == "low"
    assert labels[1].confidence == "high"


def test_label_email_reviewed_and_overturned_false():
    from src.labeler import label_email

    set_fake_responder(lambda req: {
        "verdicts": [
            {"rule_number": i + 1, "violated": False, "reason": "ok", "confidence": "high"}
            for i in range(3)
        ]
    })
    labels = label_email("Test.", _INSTRUCTION_SET)
    for lbl in labels:
        assert lbl.reviewed is False
        assert lbl.overturned is False


def test_label_email_handles_missing_verdict_gracefully():
    from src.labeler import label_email

    # Model returns fewer verdicts than instructions.
    set_fake_responder(lambda req: {
        "verdicts": [
            {"rule_number": 1, "violated": False, "reason": "ok", "confidence": "high"},
        ]
    })
    labels = label_email("Test.", _INSTRUCTION_SET)
    # Must still return one label per instruction.
    assert len(labels) == 3
    # The missing rows must default to not-violated with low confidence.
    assert labels[1].violated is False
    assert labels[1].confidence == "low"
    assert labels[2].violated is False
    assert labels[2].confidence == "low"


def test_label_email_does_not_receive_planted_violations():
    """The prompt must not contain the string 'planted_violations'."""
    from src.labeler import label_email

    captured = {}

    def responder(req):
        captured["prompt"] = req["prompt"]
        return {
            "verdicts": [
                {"rule_number": i + 1, "violated": False, "reason": "ok", "confidence": "high"}
                for i in range(3)
            ]
        }

    set_fake_responder(responder)
    label_email("Test email.", _INSTRUCTION_SET)
    assert "planted_violations" not in captured.get("prompt", ""), (
        "labeler prompt contains 'planted_violations'; the blind isolation is broken"
    )


# --------------------------------------------------------------------------- #
# Prompt SHA reproducibility
# --------------------------------------------------------------------------- #
def test_labeler_prompt_sha_is_deterministic():
    from src.labeler import labeler_prompt_sha

    sha1 = labeler_prompt_sha(_INSTRUCTION_SET, "test body")
    sha2 = labeler_prompt_sha(_INSTRUCTION_SET, "test body")
    assert sha1 == sha2
    assert len(sha1) == 64  # hex sha256


def test_labeler_prompt_sha_differs_for_different_sets():
    from src.labeler import labeler_prompt_sha

    other_set = dict(_INSTRUCTION_SET, instructions=["Always use formal English."])
    sha1 = labeler_prompt_sha(_INSTRUCTION_SET, "body")
    sha2 = labeler_prompt_sha(other_set, "body")
    assert sha1 != sha2


# --------------------------------------------------------------------------- #
# Full instruction sets sanity (with fake provider)
# --------------------------------------------------------------------------- #
def test_label_all_five_instruction_sets(monkeypatch):
    from src.labeler import label_email
    from src.schemas import load_instruction_sets

    here = os.path.dirname(__file__)
    path = os.path.join(here, "..", "fixtures", "instruction_sets.json")
    if not os.path.exists(path):
        pytest.skip("instruction_sets.json not found")
    sets = load_instruction_sets(path)["sets"]

    def responder(req):
        # Count how many rules were in the prompt by counting numbered lines.
        import re
        n = len(re.findall(r"^\d+\.", req["prompt"], re.MULTILINE))
        return {
            "verdicts": [
                {"rule_number": i + 1, "violated": False, "reason": "ok", "confidence": "high"}
                for i in range(n)
            ]
        }

    set_fake_responder(responder)
    for iset in sets:
        labels = label_email("Sample email body.", iset)
        assert len(labels) == len(iset["instructions"]), (
            f"wrong label count for {iset['id']}: "
            f"got {len(labels)}, expected {len(iset['instructions'])}"
        )
