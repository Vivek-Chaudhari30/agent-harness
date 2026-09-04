"""Semantic judge: one model call per semantic rule. (Lane B)

STUB. Implemented by Lane B. See docs/CONTRACTS.md section 2.

Exactly one model call per rule, through model_client.call_json, with strict
structured output {"pass": bool, "reason": str}. Never batch rules into one call.
"""

from __future__ import annotations

from src.schemas import Rule, RuleResult


def check_semantic_rule(email: str, rule: Rule) -> RuleResult:
    raise NotImplementedError("lane B: src/semantic_check.py")
