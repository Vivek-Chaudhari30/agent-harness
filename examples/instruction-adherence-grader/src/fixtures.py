"""Fixture generator: 50 emails with planted violations. (Lane C)

STUB. Implemented by Lane C. See docs/CONTRACTS.md section 3.2 and docs/AGENT_LANES.md.

Uses writer.write_compliant_email / writer.write_violating_email (Phase 0). Records
which rules each email was told to break as `planted_violations` (generation
bookkeeping only, never read by the checker, labeler, or scorer).
"""

from __future__ import annotations


def generate_fixtures(instruction_sets: list[dict], per_set: int = 10) -> list[dict]:
    raise NotImplementedError("lane C: src/fixtures.py")
