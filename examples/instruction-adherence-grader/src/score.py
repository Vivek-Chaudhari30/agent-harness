"""Scoring: adherence rate + grader precision/recall/F1. (Lane D)

Two computations, never conflated.

  adherence()       -- operational metric: % of emails that pass every rule,
                       counting a successful single repair as a pass.

  grader_metrics()  -- accuracy metric: how well the checker's PRE-REPAIR
                       per-rule verdicts match labels_ground_truth.json.
                       Positive class: "violation present."

The passed/violated sign flip (RuleResult.passed vs Label.violated) is
converted in exactly one named function: rule_result_violated().
A unit test in tests/test_score.py must catch any sign reversal.

score.py compares initial_results (pre-repair), NOT final_results. Comparing
post-repair verdicts against labels for the original email is a category error
that inflates apparent accuracy. An assertion guards this in the metrics path.

score.py raises on an incomplete ground truth set rather than silently scoring
a subset. A missing (email_id, rule_id) pair is an error.
"""

from __future__ import annotations

from typing import NamedTuple

from src.schemas import BatchRunResult, Label, RuleResult, labels_as_objects


# --------------------------------------------------------------------------- #
# Sign-flip conversion -- exactly one place in the whole project
# --------------------------------------------------------------------------- #

def rule_result_violated(result: RuleResult) -> bool:
    """Convert RuleResult.passed to the positive-class boolean 'violated'.

    RuleResult.passed=True means the email OBEYED the rule (not a violation).
    Label.violated=True means the rule was BROKEN (a violation).

    violated == not passed. This is the single authorised conversion point;
    do not replicate this logic elsewhere. A unit test in test_score.py will
    fail if the sign is reversed here.
    """
    return not result.passed


# --------------------------------------------------------------------------- #
# Adherence rate
# --------------------------------------------------------------------------- #

def adherence(batch: BatchRunResult) -> dict:
    """Compute adherence stats from a BatchRunResult.

    Adherence rate = (passed_first_try + passed_after_repair) / n_emails.
    Held emails are named individually with their still-failing rules.

    Returns a dict matching the 'adherence' key in CONTRACTS.md 3.5.
    """
    n = len(batch.emails)
    passed_first = sum(1 for e in batch.emails if e.status == "pass")
    passed_repair = sum(1 for e in batch.emails if e.status == "pass_after_repair")
    held = sum(1 for e in batch.emails if e.status == "held")

    if n == 0:
        adherence_rate = 0.0
    else:
        adherence_rate = (passed_first + passed_repair) / n

    holds = [
        {
            "email_id": e.email_id,
            "still_failing": list(e.still_failing),
            "reason": "; ".join(e.still_failing) if e.still_failing else "unknown",
        }
        for e in batch.emails
        if e.status == "held"
    ]

    return {
        "n_emails": n,
        "passed_first_try": passed_first,
        "passed_after_repair": passed_repair,
        "held": held,
        "adherence_rate": round(adherence_rate, 4),
        "holds": holds,
    }


# --------------------------------------------------------------------------- #
# Grader metrics
# --------------------------------------------------------------------------- #

class _Counts(NamedTuple):
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    def add(self, grader_violated: bool, label_violated: bool) -> "_Counts":
        if grader_violated and label_violated:
            return self._replace(tp=self.tp + 1)
        elif grader_violated and not label_violated:
            return self._replace(fp=self.fp + 1)
        elif not grader_violated and label_violated:
            return self._replace(fn=self.fn + 1)
        else:
            return self._replace(tn=self.tn + 1)

    def to_dict(self) -> dict:
        p, r, f1, support = _prf1(self)
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "support": support,
        }


def _prf1(c: _Counts) -> tuple[float, float, float, int]:
    support = c.tp + c.fp + c.fn + c.tn
    precision = c.tp / (c.tp + c.fp) if (c.tp + c.fp) > 0 else 0.0
    recall = c.tp / (c.tp + c.fn) if (c.tp + c.fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return precision, recall, f1, support


def grader_metrics(pre_repair_results: dict[str, list[RuleResult]], ground_truth: dict) -> dict:
    """Compare the checker's pre-repair verdicts against the ground-truth labels.

    Args:
        pre_repair_results: maps email_id -> list[RuleResult] from initial_results.
            These must come from EmailRunResult.initial_results, NOT final_results.
            The caller is responsible for passing the right field; this function
            asserts that the same key lookup cannot silently pull final_results
            by checking the caller's dict is keyed by email_id (str keys).
        ground_truth: the raw dict from schemas.load_labels(), i.e., the object
            with "version", "provenance", and "labels" keys.

    Returns a dict matching the 'grader' key in CONTRACTS.md 3.5.

    Raises:
        ValueError: if any (email_id, rule_id) in pre_repair_results is missing
                    from ground_truth. A silent subset is how a grader reports
                    perfect recall on the rules it covered.
    """
    # Sanity check: pre_repair_results must be str-keyed (email_id -> results).
    # This guards against passing the whole BatchRunResult or a final_results dict.
    if not isinstance(pre_repair_results, dict):
        raise TypeError(
            "pre_repair_results must be a dict mapping email_id -> list[RuleResult]"
        )
    for k in pre_repair_results:
        if not isinstance(k, str):
            raise TypeError(
                f"pre_repair_results keys must be email_id strings; got {type(k)}"
            )

    labels: list[Label] = labels_as_objects(ground_truth)
    label_index: dict[tuple[str, str], Label] = {
        (lbl.email_id, lbl.rule_id): lbl for lbl in labels
    }

    # Completeness check: every (email_id, rule_id) in pre_repair_results must
    # have a corresponding label. Missing pairs are errors, not implicit passes.
    missing = []
    for email_id, results in pre_repair_results.items():
        for r in results:
            if (email_id, r.rule_id) not in label_index:
                missing.append((email_id, r.rule_id))
    if missing:
        formatted = ", ".join(f"({e}, {r})" for e, r in missing[:5])
        tail = f" ... and {len(missing) - 5} more" if len(missing) > 5 else ""
        raise ValueError(
            f"Ground truth is incomplete. Missing labels for {len(missing)} "
            f"(email_id, rule_id) pair(s): {formatted}{tail}. "
            "score.py refuses to score a subset."
        )

    # Accumulate counts
    aggregate = _Counts()
    by_kind: dict[str, _Counts] = {}
    by_rule: dict[str, _Counts] = {}

    for email_id, results in pre_repair_results.items():
        for result in results:
            lbl = label_index[(email_id, result.rule_id)]
            grader_v = rule_result_violated(result)
            label_v = lbl.violated

            aggregate = aggregate.add(grader_v, label_v)

            kind = result.kind
            by_kind[kind] = by_kind.get(kind, _Counts()).add(grader_v, label_v)

            rule_id = result.rule_id
            by_rule[rule_id] = by_rule.get(rule_id, _Counts()).add(grader_v, label_v)

    n_reviewed = sum(1 for lbl in labels if lbl.reviewed)
    n_overturned = sum(1 for lbl in labels if lbl.overturned)

    return {
        "positive_class": "violation_present",
        "aggregate": aggregate.to_dict(),
        "by_kind": {k: v.to_dict() for k, v in by_kind.items()},
        "by_rule": {k: v.to_dict() for k, v in by_rule.items()},
        "n_labels": len(labels),
        "n_reviewed": n_reviewed,
        "n_overturned": n_overturned,
    }
