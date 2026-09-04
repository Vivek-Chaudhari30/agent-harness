"""Human review sheet: emit and ingest. (Lane C)

STUB. Implemented by Lane C. See docs/AGENT_LANES.md Lane C and docs/ROADMAP.md Phase 3.

Emits a single self-contained HTML review sheet (one row per (email, rule)) that a
human drives to confirm/overturn each draft verdict, and ingests the corrected
export into the labels_ground_truth.json schema with `reviewed` and `overturned`
set. A CSV round-trip is an acceptable fallback.
"""

from __future__ import annotations


def build_review_sheet(
    emails_path: str, labels_path: str, out_path: str
) -> str:
    raise NotImplementedError("lane C: src/review_tool.py")


def ingest_reviewed(reviewed_path: str, out_path: str) -> dict:
    raise NotImplementedError("lane C: src/review_tool.py")
