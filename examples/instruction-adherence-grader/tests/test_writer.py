"""Phase 0 tests for the writer, under MODEL_PROVIDER=fake.

The writer's real-API behavior is verified manually (no key in CI). Here we prove
its two modes are separate functions, that both return a string, and that the
violating mode actually targets the requested rules by id.
"""

from __future__ import annotations

import pytest

from src.model_client import set_fake_responder, reset_fake_responder
from src.schemas import derive_rule_id
from src.writer import write_compliant_email, write_violating_email

_INSTRUCTION_SET = {
    "id": "is_01",
    "label": "test",
    "sender_persona": "founder at a small workflow-automation company",
    "instructions": [
        "Never mention pricing.",
        "Keep it under 90 words.",
        "No exclamation marks.",
    ],
}
_RECIPIENT = {"company": "Acme Robotics", "industry": "industrial automation"}


@pytest.fixture(autouse=True)
def _fake_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_PROVIDER", "fake")
    monkeypatch.setenv("MODEL_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("MODEL_DEBUG_LOG", str(tmp_path / "calls.jsonl"))
    reset_fake_responder()
    yield
    reset_fake_responder()


def test_compliant_and_violating_are_distinct_functions():
    assert write_compliant_email is not write_violating_email


def test_compliant_email_returns_string_and_uses_writer_model(monkeypatch):
    monkeypatch.setenv("WRITER_MODEL_NAME", "writer-xyz")
    captured = {}

    def responder(req):
        captured["model"] = req["model"]
        captured["prompt"] = req["prompt"]
        return {"email": "Hi Acme Robotics team, quick note. Founder, Co."}

    set_fake_responder(responder)
    out = write_compliant_email(_INSTRUCTION_SET, _RECIPIENT)
    assert isinstance(out, str) and out
    assert captured["model"] == "writer-xyz"
    assert "Follow ALL of these rules" in captured["prompt"]


def test_violating_email_targets_requested_rules_by_id():
    target = derive_rule_id("Never mention pricing.")
    captured = {}

    def responder(req):
        captured["prompt"] = req["prompt"]
        return {"email": "Our pricing is great. Founder, Co."}

    set_fake_responder(responder)
    out = write_violating_email(_INSTRUCTION_SET, _RECIPIENT, [target])
    assert isinstance(out, str) and out
    # The rule to break is resolved back to its instruction text in the prompt.
    assert "Never mention pricing." in captured["prompt"]
    assert "Deliberately BREAK" in captured["prompt"]
    # And the other rules are still listed as ones to keep.
    assert "Keep it under 90 words." in captured["prompt"]
