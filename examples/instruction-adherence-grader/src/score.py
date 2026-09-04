"""Scoring: adherence rate + grader precision/recall/F1. (Lane D)

STUB. Implemented by Lane D. See docs/CONTRACTS.md section 0 and 3.5.

Two computations that are NEVER conflated. The passed/violated sign flip
(RuleResult.passed vs Label.violated) is converted in exactly one named function
here, with a unit test that fails if the sign flips. score.py compares
initial_results (pre-repair), not final_results, and raises on an incomplete ground
truth set.
"""

from __future__ import annotations

from src.schemas import BatchRunResult


def adherence(batch: BatchRunResult) -> dict:
    raise NotImplementedError("lane D: src/score.py")


def grader_metrics(pre_repair_results: dict, ground_truth: dict) -> dict:
    raise NotImplementedError("lane D: src/score.py")
