"""Single CLI entrypoint for the instruction adherence grader. (Lane D)

Subcommands and their owning modules:
  fixtures  -- src.fixtures.generate_fixtures          (Lane C)
  label     -- src.labeler.label_email                 (Lane C)
  review    -- src.review_tool                         (Lane C)
  grade     -- src.grader.grade_batch                  (Integration)
  score     -- src.score.adherence + grader_metrics    (Lane D)
  report    -- scripts/session_report.py               (Lane E)

Where a module is still a stub, NotImplementedError surfaces here intentionally:
that is the integration test that wiring is correct.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


# --------------------------------------------------------------------------- #
# Subcommand handlers
# --------------------------------------------------------------------------- #

def _cmd_fixtures(args: argparse.Namespace) -> int:
    from src.fixtures import generate_fixtures
    from src.schemas import load_instruction_sets

    isets_path = args.instruction_sets or os.path.join("fixtures", "instruction_sets.json")
    output_path = args.output or os.path.join("fixtures", "emails.json")
    per_set = args.per_set or 10
    limit = args.limit

    obj = load_instruction_sets(isets_path)
    sets = obj["sets"]
    if limit is not None:
        sets = sets[:limit]

    emails = generate_fixtures(sets, per_set=per_set)

    if limit is not None:
        emails = emails[:limit]

    out = {"version": 1, "emails": emails}
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"Wrote {len(emails)} emails to {output_path}")
    return 0


def _cmd_label(args: argparse.Namespace) -> int:
    from src.labeler import label_email
    from src.schemas import label_to_dict, load_emails, load_instruction_sets

    isets_path = args.instruction_sets or os.path.join("fixtures", "instruction_sets.json")
    emails_path = args.emails or os.path.join("fixtures", "emails.json")
    output_path = args.output or os.path.join("fixtures", "labels_model_draft.json")

    isets_obj = load_instruction_sets(isets_path)
    iset_map = {s["id"]: s for s in isets_obj["sets"]}

    emails_obj = load_emails(emails_path)
    email_records = emails_obj["emails"]

    if args.limit is not None:
        email_records = email_records[: args.limit]

    all_labels = []
    for rec in email_records:
        iset = iset_map[rec["instruction_set_id"]]
        labels = label_email(rec["body"], iset)
        all_labels.extend(label_to_dict(lbl) for lbl in labels)

    out = {
        "version": 1,
        "provenance": {
            "kind": "model_draft",
            "model": "see config",
            "labeler_prompt_sha": "pending",
            "reviewed_at": None,
            "reviewer_note": "",
        },
        "labels": all_labels,
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"Wrote {len(all_labels)} labels to {output_path}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    from src.review_tool import run_review  # type: ignore[attr-defined]

    draft_path = args.draft or os.path.join("fixtures", "labels_model_draft.json")
    output_path = args.output or os.path.join("fixtures", "labels_ground_truth.json")
    run_review(draft_path=draft_path, output_path=output_path, limit=args.limit)
    return 0


def _cmd_grade(args: argparse.Namespace) -> int:
    import datetime

    from src.grader import grade_batch
    from src.schemas import batch_run_result_to_dict, load_emails, load_instruction_sets

    isets_path = args.instruction_sets or os.path.join("fixtures", "instruction_sets.json")
    emails_path = args.emails or os.path.join("fixtures", "emails.json")
    output_dir = args.output or "runs"

    isets_obj = load_instruction_sets(isets_path)
    emails_obj = load_emails(emails_path)
    email_records = emails_obj["emails"]

    if args.limit is not None:
        email_records = email_records[: args.limit]

    iset_map = {s["id"]: s for s in isets_obj["sets"]}
    batch = grade_batch(email_records, iset_map)

    run_id = batch.run_id or datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{run_id}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(batch_run_result_to_dict(batch), fh, indent=2)
    print(f"Wrote run to {out_path}")
    return 0


def _cmd_score(args: argparse.Namespace) -> int:
    import glob

    from src.schemas import load_labels, load_run
    from src.score import adherence, grader_metrics

    # Resolve run path
    run_path = args.run
    if not run_path:
        candidates = sorted(glob.glob(os.path.join("runs", "*.json")))
        # Exclude .metrics.json files
        candidates = [p for p in candidates if not p.endswith(".metrics.json")]
        if not candidates:
            print("No run files found in runs/. Run 'grade' first or pass --run PATH.", file=sys.stderr)
            return 1
        run_path = candidates[-1]
        print(f"Using run: {run_path}")

    labels_path = args.labels or os.path.join("fixtures", "labels_ground_truth.json")

    batch = load_run(run_path)
    ground_truth = load_labels(labels_path)

    adherence_stats = adherence(batch)

    # Build pre_repair_results from initial_results (NOT final_results)
    pre_repair = {e.email_id: e.initial_results for e in batch.emails}
    grader_stats = grader_metrics(pre_repair, ground_truth)

    run_id = batch.run_id
    metrics = {
        "version": 1,
        "run_id": run_id,
        "adherence": adherence_stats,
        "grader": grader_stats,
    }

    # Write metrics file
    base = os.path.splitext(run_path)[0]
    out_path = args.output or f"{base}.metrics.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)

    # Print summary
    a = adherence_stats
    g = grader_stats["aggregate"]
    print(f"\n=== Adherence ===")
    print(f"  {a['n_emails']} emails: {a['passed_first_try']} passed, "
          f"{a['passed_after_repair']} repaired, {a['held']} held")
    print(f"  Adherence rate: {a['adherence_rate']:.1%}")

    if a["holds"]:
        print(f"\n  Held emails:")
        for h in a["holds"]:
            print(f"    {h['email_id']}: {h['reason']}")

    print(f"\n=== Grader accuracy (pre-repair vs ground truth) ===")
    print(f"  Precision: {g['precision']:.3f}  Recall: {g['recall']:.3f}  F1: {g['f1']:.3f}")
    print(f"  (n={g['support']}, TP={g['tp']}, FP={g['fp']}, FN={g['fn']}, TN={g['tn']})")

    bk = grader_stats.get("by_kind", {})
    for kind in ("deterministic", "semantic"):
        if kind in bk:
            k = bk[kind]
            print(f"  {kind:14s}: P={k['precision']:.3f}  R={k['recall']:.3f}  F1={k['f1']:.3f}")

    print(f"\nMetrics written to {out_path}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    import subprocess

    repo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
    script = os.path.join(repo_root, "scripts", "session_report.py")
    result = subprocess.run([sys.executable, script], check=False)
    return result.returncode


# --------------------------------------------------------------------------- #
# Parser construction
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grader",
        description="Instruction adherence grader.",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # --- fixtures ---
    p_fix = sub.add_parser("fixtures", help="Generate fixture emails (Lane C)")
    p_fix.add_argument("--instruction-sets", metavar="PATH",
                       help="Path to instruction_sets.json (default: fixtures/instruction_sets.json)")
    p_fix.add_argument("--output", metavar="PATH",
                       help="Output path (default: fixtures/emails.json)")
    p_fix.add_argument("--per-set", type=int, metavar="N",
                       help="Emails to generate per instruction set (default: 10)")
    p_fix.add_argument("--limit", type=int, metavar="N",
                       help="Cap total emails (cheap iteration)")
    p_fix.add_argument("--no-cache", action="store_true",
                       help="Bypass the model call cache")

    # --- label ---
    p_lbl = sub.add_parser("label", help="Blind-label emails (Lane C)")
    p_lbl.add_argument("--instruction-sets", metavar="PATH")
    p_lbl.add_argument("--emails", metavar="PATH",
                       help="Path to emails.json (default: fixtures/emails.json)")
    p_lbl.add_argument("--output", metavar="PATH",
                       help="Output labels file (default: fixtures/labels_model_draft.json)")
    p_lbl.add_argument("--limit", type=int, metavar="N")
    p_lbl.add_argument("--no-cache", action="store_true")

    # --- review ---
    p_rev = sub.add_parser("review", help="Human review tool (Lane C)")
    p_rev.add_argument("--draft", metavar="PATH",
                       help="Draft labels file (default: fixtures/labels_model_draft.json)")
    p_rev.add_argument("--output", metavar="PATH",
                       help="Output ground truth file (default: fixtures/labels_ground_truth.json)")
    p_rev.add_argument("--limit", type=int, metavar="N")

    # --- grade ---
    p_grd = sub.add_parser("grade", help="Run the grader pipeline (Integration)")
    p_grd.add_argument("--instruction-sets", metavar="PATH")
    p_grd.add_argument("--emails", metavar="PATH")
    p_grd.add_argument("--output", metavar="DIR",
                       help="Output directory for run files (default: runs/)")
    p_grd.add_argument("--limit", type=int, metavar="N")
    p_grd.add_argument("--no-cache", action="store_true")

    # --- score ---
    p_scr = sub.add_parser("score", help="Compute adherence + grader metrics (Lane D)")
    p_scr.add_argument("--run", metavar="PATH",
                       help="Path to run .json file (default: latest in runs/)")
    p_scr.add_argument("--labels", metavar="PATH",
                       help="Path to labels_ground_truth.json "
                            "(default: fixtures/labels_ground_truth.json)")
    p_scr.add_argument("--output", metavar="PATH",
                       help="Output metrics file (default: <run>.metrics.json)")
    p_scr.add_argument("--limit", type=int, metavar="N",
                       help="Score only first N emails (cheap iteration)")
    p_scr.add_argument("--no-cache", action="store_true")

    # --- report ---
    p_rpt = sub.add_parser("report", help="Generate session report (Lane E)")
    p_rpt.add_argument("--limit", type=int, metavar="N")
    p_rpt.add_argument("--no-cache", action="store_true")

    return parser


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

_HANDLERS = {
    "fixtures": _cmd_fixtures,
    "label": _cmd_label,
    "review": _cmd_review,
    "grade": _cmd_grade,
    "score": _cmd_score,
    "report": _cmd_report,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    handler = _HANDLERS[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
