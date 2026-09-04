"""Batch orchestration: compile -> check -> repair -> hold. (Integration)

grade_email classifies one email as pass / pass_after_repair / held, preserving
initial_results (pre-repair) separately from final_results (post-repair) so
score.py compares the right column.  grade_batch runs the full set and emits the
run-level summary.

Contract-change accepted (docs/contract-changes/lane-a-compiler.md):
  Rules with check_id == "company_name_mentioned" have params["company"] == ""
  at compile time.  grade_email injects the recipient's company name from the
  email record before calling check_email.  See CONTRACTS.md section 3.6.
"""

from __future__ import annotations

import dataclasses
import datetime

from src.checker import check_email
from src.compile import compile_instructions
from src.config import Config
from src.repair import repair_email
from src.schemas import BatchRunResult, EmailRunResult, Rule, RuleResult


def _inject_company(rules: list[Rule], company: str) -> list[Rule]:
    """Clone any company_name_mentioned rule with the live company name."""
    if not company:
        return rules
    return [
        dataclasses.replace(r, params={**r.params, "company": company})
        if r.check_id == "company_name_mentioned"
        else r
        for r in rules
    ]


def _minimal_iset(email_record: dict, rules: list[Rule]) -> dict:
    """Reconstruct the minimal instruction-set dict repair_email needs."""
    return {
        "id": email_record.get("instruction_set_id", ""),
        "instructions": [r.source_instruction for r in rules],
    }


def grade_email(
    email_record: dict,
    rules: list[Rule],
    *,
    config: Config | None = None,
) -> EmailRunResult:
    """Grade one email: check -> optional repair -> classify.

    initial_results captures the pre-repair verdict.  final_results is the
    post-repair verdict, or identical to initial_results when no repair ran.
    score.py compares initial_results against ground-truth labels.
    """
    email_text = email_record["body"]
    company = (email_record.get("recipient_context") or {}).get("company", "")
    enriched_rules = _inject_company(rules, company)

    initial_results = check_email(email_text, enriched_rules, config=config)
    failed = [r for r in initial_results if not r.passed]

    if not failed:
        return EmailRunResult(
            email_id=email_record["id"],
            instruction_set_id=email_record["instruction_set_id"],
            initial_results=initial_results,
            repair_attempted=False,
            repaired_body=None,
            final_results=initial_results,
            status="pass",
            still_failing=[],
        )

    # One repair attempt, then re-check the full rule set.
    iset = _minimal_iset(email_record, rules)
    repaired_body = repair_email(email_text, failed, iset, config=config)
    final_results = check_email(repaired_body, enriched_rules, config=config)
    still_failing = [r.rule_id for r in final_results if not r.passed]

    if not still_failing:
        status: str = "pass_after_repair"
    else:
        status = "held"

    return EmailRunResult(
        email_id=email_record["id"],
        instruction_set_id=email_record["instruction_set_id"],
        initial_results=initial_results,
        repair_attempted=True,
        repaired_body=repaired_body,
        final_results=final_results,
        status=status,
        still_failing=still_failing,
    )


def grade_batch(
    emails: list[dict],
    instruction_sets: dict,
    *,
    config: Config | None = None,
) -> BatchRunResult:
    """Grade every email in the batch and return a BatchRunResult.

    instruction_sets maps instruction_set_id -> instruction_set dict.
    Each instruction set is compiled once, then reused for every email in that set.
    """
    cfg = config or Config.from_env()
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    compiled: dict[str, list[Rule]] = {
        is_id: compile_instructions(iset)
        for is_id, iset in instruction_sets.items()
    }

    results: list[EmailRunResult] = []
    for rec in emails:
        is_id = rec["instruction_set_id"]
        rules = compiled[is_id]
        results.append(grade_email(rec, rules, config=cfg))

    n = len(results)
    passed_first = sum(1 for r in results if r.status == "pass")
    passed_repaired = sum(1 for r in results if r.status == "pass_after_repair")
    held = sum(1 for r in results if r.status == "held")
    adherence_rate = (passed_first + passed_repaired) / n if n else 0.0

    run_config: dict = {
        "model": cfg.model_name,
        "writer_model": cfg.writer_model_name,
        "cache": bool(cfg.cache_dir),
    }

    return BatchRunResult(
        run_id=run_id,
        config=run_config,
        emails=results,
        summary={
            "n_emails": n,
            "passed_first_try": passed_first,
            "passed_after_repair": passed_repaired,
            "held": held,
            "adherence_rate": adherence_rate,
        },
    )
