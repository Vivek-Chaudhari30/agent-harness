"""repair_email: exactly one repair attempt. (Lane B)

STUB. Implemented by Lane B. See docs/CONTRACTS.md section 2.

Exactly one model call, given the original instructions, the current draft, and the
specific violations (rule id plus reason). This function does NOT re-check; the
caller re-runs the FULL checker on the result, because a fix for one rule routinely
breaks another. There is never a second repair attempt.
"""

from __future__ import annotations

from src.schemas import RuleResult


def repair_email(email: str, failed: list[RuleResult], instruction_set: dict) -> str:
    raise NotImplementedError("lane B: src/repair.py")
