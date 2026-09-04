#!/usr/bin/env python3
"""Turn git metadata into the parallel-build evidence table. (Lane E)

PHASE 0 STUB. Per docs/CONDUCTOR_KICKOFF.md section 4.8, Phase 0 ships the argument
parsing and the marker-rewriting logic only. Lane E implements the git-metadata
collection (`collect_sessions`) against the spec in docs/CONDUCTOR_LOG.md and wires
it into `main`.

Standard library only, no network, no API key: it must run in CI.
"""

from __future__ import annotations

import argparse
import os
import sys

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
    the same `new_block` produces no diff. This is the marker-rewriting logic the
    Phase 0 stub is required to provide; Lane E supplies `new_block`.
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


def collect_sessions(repo_root: str) -> list[dict]:
    """Group commits by Conductor-Lane trailer and compute per-lane stats.

    Implemented by Lane E per the spec in docs/CONDUCTOR_LOG.md.
    """
    raise NotImplementedError("lane E: collect_sessions")


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
    _build_parser().parse_args(argv)
    print("session_report: not implemented yet (lane E).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
