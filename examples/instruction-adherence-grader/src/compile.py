"""Rule compiler: plain-English instruction set -> Rule objects. (Lane A)

STUB. Implemented by Lane A. See docs/CONTRACTS.md section 2 and docs/AGENT_LANES.md.

Lane A note: derive rule ids from instruction content using
`schemas.derive_rule_id`, never from list position, so both this compiler and the
writer's id->instruction mapping agree.
"""

from __future__ import annotations

from src.schemas import Rule


def compile_instructions(instruction_set: dict) -> list[Rule]:
    raise NotImplementedError("lane A: src/compile.py")
