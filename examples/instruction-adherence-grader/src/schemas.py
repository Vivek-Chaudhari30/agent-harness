"""Frozen data types and JSON file schemas for the whole project.

Everything in `docs/CONTRACTS.md` section 1 lives here. Nobody downstream redefines
these types locally. If a lane needs a field that does not exist, it works around it
and files a note in `docs/contract-changes/<lane-id>.md`.

Polarity convention (see CONTRACTS.md section 0, read it twice):
  - RuleResult.passed  -> True means the email OBEYED the rule.
  - Label.violated     -> True means the rule was BROKEN.
  `violated == not passed`. Convert at exactly one place, in score.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

SCHEMA_VERSION = 1

RuleKind = Literal["deterministic", "semantic"]
Verdict = Literal["deterministic", "semantic", "labeler", "human"]


# --------------------------------------------------------------------------- #
# Core types (CONTRACTS.md section 1)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Rule:
    id: str  # stable slug, unique within an instruction set
    instruction_set_id: str
    source_instruction: str  # the original plain-English text, verbatim
    kind: RuleKind
    description: str  # one human-readable line, shown in the review sheet
    check_id: str | None = None  # deterministic only: key into rules.CHECKS
    params: dict[str, Any] = field(default_factory=dict)  # deterministic only
    judge_prompt: str | None = None  # semantic only: fully specified judge prompt
    judge_prompt_sha: str | None = None  # sha256 of judge_prompt, for auditability


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool  # True == obeyed
    reason: str  # one line. Required when passed is False. May be "" when passed.
    kind: RuleKind
    source: Verdict  # who produced this verdict


@dataclass
class Label:
    email_id: str
    rule_id: str
    violated: bool  # True == broken. Inverted polarity vs RuleResult.passed.
    reason: str
    kind: RuleKind
    confidence: Literal["high", "low"] = "high"
    reviewed: bool = False  # a human actually looked at this row
    overturned: bool = False  # the human disagreed with the model draft


@dataclass
class EmailRunResult:
    email_id: str
    instruction_set_id: str
    initial_results: list[RuleResult]  # PRE-repair. score.py compares this.
    repair_attempted: bool
    repaired_body: str | None
    final_results: list[RuleResult]  # post-repair, or identical when none attempted
    status: Literal["pass", "pass_after_repair", "held"]
    still_failing: list[str]  # rule ids; empty unless status == "held"


@dataclass
class BatchRunResult:
    run_id: str
    config: dict
    emails: list[EmailRunResult]
    summary: dict  # n_emails, passed_first_try, passed_after_repair, held, adherence_rate


# --------------------------------------------------------------------------- #
# Rule id derivation (shared primitive)
# --------------------------------------------------------------------------- #
def derive_rule_id(source_instruction: str) -> str:
    """Derive a stable, unique rule id from the instruction *content*.

    Rule ids must never come from list position: reordering an instruction set
    must not silently invalidate every label downstream (CONTRACTS.md section 1).

    Both the compiler (Lane A) and the writer/fixtures path (which must map a rule
    id back to the instruction it refers to) depend on this being the single agreed
    derivation. Use this function; do not invent a second one.

    Produces a readable slug plus a short content hash so that two similar
    instructions never collide:  "keep_it_under_90_words_3f9a1c"
    """
    normalized = source_instruction.strip()
    slug = re.sub(r"[^a-z0-9]+", "_", normalized.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")[:40].strip("_") or "rule"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:6]
    return f"{slug}_{digest}"


def sha256_hex(text: str) -> str:
    """sha256 hex digest, used for judge_prompt_sha and labeler_prompt_sha."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# (De)serialization helpers
# --------------------------------------------------------------------------- #
def rule_result_to_dict(r: RuleResult) -> dict:
    return {
        "rule_id": r.rule_id,
        "passed": r.passed,
        "reason": r.reason,
        "kind": r.kind,
        "source": r.source,
    }


def rule_result_from_dict(d: dict) -> RuleResult:
    return RuleResult(
        rule_id=d["rule_id"],
        passed=bool(d["passed"]),
        reason=d.get("reason", ""),
        kind=d["kind"],
        source=d["source"],
    )


def email_run_result_to_dict(e: EmailRunResult) -> dict:
    return {
        "email_id": e.email_id,
        "instruction_set_id": e.instruction_set_id,
        "initial_results": [rule_result_to_dict(r) for r in e.initial_results],
        "repair_attempted": e.repair_attempted,
        "repaired_body": e.repaired_body,
        "final_results": [rule_result_to_dict(r) for r in e.final_results],
        "status": e.status,
        "still_failing": list(e.still_failing),
    }


def email_run_result_from_dict(d: dict) -> EmailRunResult:
    return EmailRunResult(
        email_id=d["email_id"],
        instruction_set_id=d["instruction_set_id"],
        initial_results=[rule_result_from_dict(x) for x in d["initial_results"]],
        repair_attempted=bool(d["repair_attempted"]),
        repaired_body=d.get("repaired_body"),
        final_results=[rule_result_from_dict(x) for x in d["final_results"]],
        status=d["status"],
        still_failing=list(d.get("still_failing", [])),
    )


def batch_run_result_to_dict(b: BatchRunResult) -> dict:
    return {
        "version": SCHEMA_VERSION,
        "run_id": b.run_id,
        "config": b.config,
        "emails": [email_run_result_to_dict(e) for e in b.emails],
        "summary": b.summary,
    }


def batch_run_result_from_dict(d: dict) -> BatchRunResult:
    _require_version(d)
    return BatchRunResult(
        run_id=d["run_id"],
        config=d.get("config", {}),
        emails=[email_run_result_from_dict(x) for x in d["emails"]],
        summary=d.get("summary", {}),
    )


def label_to_dict(label: Label) -> dict:
    return {
        "email_id": label.email_id,
        "rule_id": label.rule_id,
        "violated": label.violated,
        "reason": label.reason,
        "kind": label.kind,
        "confidence": label.confidence,
        "reviewed": label.reviewed,
        "overturned": label.overturned,
    }


def label_from_dict(d: dict) -> Label:
    return Label(
        email_id=d["email_id"],
        rule_id=d["rule_id"],
        violated=bool(d["violated"]),
        reason=d.get("reason", ""),
        kind=d["kind"],
        confidence=d.get("confidence", "high"),
        reviewed=bool(d.get("reviewed", False)),
        overturned=bool(d.get("overturned", False)),
    )


# --------------------------------------------------------------------------- #
# JSON file loaders / validators (CONTRACTS.md section 3)
#
# Every file carries "version": 1. Every loader validates and raises on mismatch.
# --------------------------------------------------------------------------- #
class SchemaError(ValueError):
    """Raised when a JSON file does not match the frozen schema."""


def _require_version(obj: dict) -> None:
    if not isinstance(obj, dict):
        raise SchemaError("expected a JSON object at the top level")
    if obj.get("version") != SCHEMA_VERSION:
        raise SchemaError(
            f"version mismatch: expected {SCHEMA_VERSION}, got {obj.get('version')!r}"
        )


def _require_keys(obj: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise SchemaError(f"{where}: missing required keys {missing}")


def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_instruction_sets(path: str) -> dict:
    """Load and validate fixtures/instruction_sets.json (CONTRACTS.md 3.1)."""
    obj = load_json(path)
    _require_version(obj)
    if not isinstance(obj.get("sets"), list) or not obj["sets"]:
        raise SchemaError("instruction_sets.json: 'sets' must be a non-empty list")
    for s in obj["sets"]:
        _require_keys(
            s, ("id", "label", "sender_persona", "instructions"), "instruction set"
        )
        if not isinstance(s["instructions"], list) or not all(
            isinstance(i, str) for i in s["instructions"]
        ):
            raise SchemaError(
                f"instruction set {s.get('id')!r}: 'instructions' must be a list of strings"
            )
    return obj


def load_emails(path: str) -> dict:
    """Load and validate fixtures/emails.json (CONTRACTS.md 3.2)."""
    obj = load_json(path)
    _require_version(obj)
    if not isinstance(obj.get("emails"), list):
        raise SchemaError("emails.json: 'emails' must be a list")
    for e in obj["emails"]:
        _require_keys(
            e,
            (
                "id",
                "instruction_set_id",
                "recipient_context",
                "body",
                "planted_violations",
                "difficulty",
                "generation",
            ),
            "email record",
        )
    return obj


def load_labels(path: str) -> dict:
    """Load and validate a labels_*.json file (CONTRACTS.md 3.3).

    Returns the raw dict; call `labels_as_objects` to get list[Label].
    """
    obj = load_json(path)
    _require_version(obj)
    _require_keys(obj, ("provenance", "labels"), "labels file")
    if not isinstance(obj["labels"], list):
        raise SchemaError("labels file: 'labels' must be a list")
    for lbl in obj["labels"]:
        _require_keys(
            lbl, ("email_id", "rule_id", "violated", "kind"), "label entry"
        )
    return obj


def labels_as_objects(obj: dict) -> list[Label]:
    return [label_from_dict(d) for d in obj["labels"]]


def load_run(path: str) -> BatchRunResult:
    """Load and validate a runs/<run_id>.json file into a BatchRunResult (3.4)."""
    obj = load_json(path)
    return batch_run_result_from_dict(obj)
