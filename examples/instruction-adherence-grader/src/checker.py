"""check_email: run every rule against an email. (Lane B)

Deterministic rules run inline via rules.CHECKS with no network call; semantic
rules dispatch to check_semantic_rule one at a time. Returns one RuleResult per
rule, in rules order, with source set to the producing system.
"""

from __future__ import annotations

from src.config import Config
from src.rules import CHECKS
from src.schemas import Rule, RuleResult
from src.semantic_check import check_semantic_rule


def check_email(
    email: str,
    rules: list[Rule],
    *,
    config: Config | None = None,
) -> list[RuleResult]:
    """Run every rule against the email and return one RuleResult per rule.

    Deterministic rules run pure Python via CHECKS — no network, no I/O.
    Semantic rules each get exactly one model call via check_semantic_rule.
    Results are returned in the same order as `rules`.

    Args:
        email: The email body to evaluate.
        rules: Ordered list of Rule objects to check.
        config: Optional Config override; threaded through to semantic calls.

    Raises:
        ValueError: If a deterministic rule's check_id is absent from CHECKS.
    """
    results: list[RuleResult] = []

    for rule in rules:
        if rule.kind == "deterministic":
            if rule.check_id is None or rule.check_id not in CHECKS:
                raise ValueError(
                    f"Rule {rule.id!r}: check_id {rule.check_id!r} is not registered "
                    f"in rules.CHECKS. Lane A must add it before this rule can run."
                )
            passed, reason = CHECKS[rule.check_id](email, rule.params)
            results.append(
                RuleResult(
                    rule_id=rule.id,
                    passed=passed,
                    reason=reason,
                    kind="deterministic",
                    source="deterministic",
                )
            )
        elif rule.kind == "semantic":
            results.append(check_semantic_rule(email, rule, config=config))
        else:
            raise ValueError(f"Unknown rule kind {rule.kind!r} on rule {rule.id!r}")

    return results
