"""check_email: run every rule against an email. (Lane B)

STUB. Implemented by Lane B. See docs/CONTRACTS.md section 2.

Deterministic rules run inline via rules.CHECKS with no network call; semantic
rules dispatch to check_semantic_rule one at a time. Returns one RuleResult per
rule, in rules order.
"""

from __future__ import annotations

from src.schemas import Rule, RuleResult


def check_email(email: str, rules: list[Rule]) -> list[RuleResult]:
    raise NotImplementedError("lane B: src/checker.py")
