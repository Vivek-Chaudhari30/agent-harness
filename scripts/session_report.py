#!/usr/bin/env python3
"""Turn git metadata into the parallel-build evidence table. (Lane E)

Standard library only, no network, no API key: it must run in CI.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import warnings
from datetime import datetime, timezone, timedelta

BEGIN_MARKER = "<!-- BEGIN GENERATED: scripts/session_report.py -->"
END_MARKER = "<!-- END GENERATED -->"

_DEFAULT_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "CONDUCTOR_LOG.md",
)


def rewrite_generated_block(content: str, new_block: str) -> str:
    """Replace the text between BEGIN/END markers with `new_block`.

    Idempotent: prose outside the markers is untouched, and running it twice with
    the same `new_block` produces no diff.
    """
    start = content.find(BEGIN_MARKER)
    end = content.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            "could not find BEGIN/END GENERATED markers in the target file"
        )
    before = content[: start + len(BEGIN_MARKER)]
    after = content[end:]
    body = new_block if new_block.startswith("\n") else "\n" + new_block
    if not body.endswith("\n"):
        body += "\n"
    return f"{before}{body}{after}"


def _parse_date(date_str: str) -> datetime:
    """Parse a git author-date string into a timezone-aware datetime."""
    # Format: "2026-09-04 10:48:58 -0700"
    date_str = date_str.strip()
    parts = date_str.rsplit(" ", 1)
    dt = datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
    tz_str = parts[1]
    sign = 1 if tz_str[0] == "+" else -1
    hours = int(tz_str[1:3])
    minutes = int(tz_str[3:5])
    offset = timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
    return dt.replace(tzinfo=offset)


def _fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_span(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def collect_sessions(repo_root: str) -> list[dict]:
    """Group commits by Conductor-Lane trailer and compute per-lane stats."""
    # Pass 1: commit metadata (hash, date, body for trailer extraction)
    meta_out = subprocess.check_output(
        ["git", "log", "--format=%H%x01%ai%x01%B%x00", "origin/main"],
        cwd=repo_root,
        text=True,
    )
    commits: dict[str, dict] = {}
    for record in meta_out.split("\x00"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x01", 2)
        if len(parts) < 3:
            continue
        sha, date_str, body = parts
        sha = sha.strip()
        date_str = date_str.strip()
        m = re.search(r"Conductor-Lane:\s*(\S+)", body)
        lane = m.group(1) if m else "unattributed"
        commits[sha] = {"sha": sha, "date": _parse_date(date_str), "lane": lane}

    if not commits:
        return []

    unattributed = [c["sha"][:8] for c in commits.values() if c["lane"] == "unattributed"]
    if unattributed:
        warnings.warn(
            f"unattributed commits (no Conductor-Lane trailer): {', '.join(unattributed)}",
            stacklevel=2,
        )

    # Pass 2: numstat for file/line stats
    numstat_out = subprocess.check_output(
        ["git", "log", "--numstat", "--format=COMMIT:%H", "origin/main"],
        cwd=repo_root,
        text=True,
    )

    current_sha: str | None = None
    for line in numstat_out.splitlines():
        if line.startswith("COMMIT:"):
            current_sha = line[7:].strip()
        elif current_sha and line.strip():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                added_s, deleted_s, path = parts
                # "-" means binary file; treat as 0
                added = int(added_s) if added_s != "-" else 0
                deleted = int(deleted_s) if deleted_s != "-" else 0
                if current_sha in commits:
                    c = commits[current_sha]
                    c.setdefault("files", set()).add(path)
                    c["added"] = c.get("added", 0) + added
                    c["deleted"] = c.get("deleted", 0) + deleted

    # Group by lane
    lanes: dict[str, list[dict]] = {}
    for c in commits.values():
        lanes.setdefault(c["lane"], []).append(c)

    rows: list[dict] = []
    for lane, lane_commits in sorted(lanes.items()):
        dates = [c["date"] for c in lane_commits]
        first = min(dates)
        last = max(dates)
        files: set[str] = set()
        added = deleted = 0
        for c in lane_commits:
            files |= c.get("files", set())
            added += c.get("added", 0)
            deleted += c.get("deleted", 0)
        rows.append({
            "lane": lane,
            "commits": len(lane_commits),
            "first": first,
            "last": last,
            "span": last - first,
            "files": len(files),
            "net": added - deleted,
        })

    return rows


def _compute_overlap(rows: list[dict]) -> tuple[timedelta, float]:
    """Return (overlap_duration, compression_ratio).

    overlap_duration: wall-clock time during which ≥2 lanes had commits in flight.
    compression_ratio: sum of lane spans / total elapsed time (wall clock).
    """
    if not rows:
        return timedelta(0), 1.0

    intervals = [(r["first"], r["last"]) for r in rows]
    all_dates = [d for iv in intervals for d in iv]
    wall_start = min(all_dates)
    wall_end = max(all_dates)
    wall_clock = wall_end - wall_start
    sum_spans = sum((r["last"] - r["first"] for r in rows), timedelta(0))

    # Sweep to find time during which ≥2 lanes are active
    events: list[tuple[datetime, int]] = []
    for start, end in intervals:
        events.append((start, +1))
        events.append((end, -1))
    events.sort()

    overlap = timedelta(0)
    active = 0
    prev_t: datetime | None = None
    for t, delta in events:
        if active >= 2 and prev_t is not None:
            overlap += t - prev_t
        prev_t = t
        active += delta

    ratio = sum_spans.total_seconds() / wall_clock.total_seconds() if wall_clock.total_seconds() > 0 else 1.0
    return overlap, ratio


def _render_table(rows: list[dict], overlap: timedelta, ratio: float) -> str:
    header = "| Lane | Commits | First commit | Last commit | Span | Files touched | Net lines |"
    sep    = "| --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for r in rows:
        span_s = _fmt_span(r["span"])
        first_s = _fmt_dt(r["first"])
        last_s = _fmt_dt(r["last"])
        net_s = f"+{r['net']}" if r["net"] >= 0 else str(r["net"])
        lines.append(
            f"| {r['lane']} | {r['commits']} | {first_s} | {last_s} | {span_s} | {r['files']} | {net_s} |"
        )

    overlap_s = _fmt_span(overlap)
    lines.append("")
    lines.append(f"**Overlap:** {overlap_s} of concurrent activity across lanes. "
                 f"Sum of lane spans / wall clock = **{ratio:.2f}x**.")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the parallel-build session table in CONDUCTOR_LOG.md."
    )
    parser.add_argument(
        "--log",
        default=_DEFAULT_LOG,
        help="path to docs/CONDUCTOR_LOG.md (the file whose generated block is rewritten)",
    )
    parser.add_argument(
        "--repo-root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="repository root to read git history from",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the generated table instead of writing it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    rows = collect_sessions(args.repo_root)
    overlap, ratio = _compute_overlap(rows)
    table = _render_table(rows, overlap, ratio)

    if args.dry_run:
        print(table)
        return 0

    with open(args.log, encoding="utf-8") as f:
        content = f.read()

    new_content = rewrite_generated_block(content, table)

    with open(args.log, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"session_report: wrote {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
