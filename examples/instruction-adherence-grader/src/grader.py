"""Batch orchestration: compile -> check -> repair -> hold. (Integration)

STUB. Implemented in the Integration phase. See docs/CONTRACTS.md section 2 and 3.4.

grade_email classifies an email as pass / pass_after_repair / held, preserving
initial_results (pre-repair) separately from final_results (post-repair).
grade_batch runs the whole set and emits the batch summary.
"""

from __future__ import annotations

from src.schemas import BatchRunResult, EmailRunResult, Rule


def grade_email(email_record: dict, rules: list[Rule]) -> EmailRunResult:
    raise NotImplementedError("integration: src/grader.py")


def grade_batch(emails: list[dict], instruction_sets: dict) -> BatchRunResult:
    raise NotImplementedError("integration: src/grader.py")
