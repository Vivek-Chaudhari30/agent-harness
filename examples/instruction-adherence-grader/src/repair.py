"""repair_email: exactly one repair attempt. (Lane B)

Exactly one model call, given the original instructions, the current draft, and the
specific violations (rule id plus reason). This function does NOT re-check; the
caller re-runs the FULL checker on the result, because a fix for one rule routinely
breaks another (e.g. shortening to hit a word cap deletes the company reference).
There is never a second repair attempt — the caller decides whether to hold.
"""

from __future__ import annotations

from src.config import Config
from src.model_client import call_json
from src.schemas import RuleResult

_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "corrected_email": {"type": "string"},
    },
    "required": ["corrected_email"],
    "additionalProperties": False,
}

_REPAIR_SYSTEM = (
    "You are an expert email editor. You will receive a sales email draft that violates "
    "one or more instructions, along with the full instruction set it must satisfy. "
    "Rewrite the email to fix exactly the listed violations without introducing new ones. "
    "Return only the corrected email body — no explanation, no preamble."
)


def repair_email(
    email: str,
    failed: list[RuleResult],
    instruction_set: dict,
    *,
    config: Config | None = None,
) -> str:
    """Repair a draft email that failed one or more rules. Exactly one model call.

    The caller is responsible for re-running the full checker on the returned
    draft over ALL rules and deciding whether to accept or hold based on the
    results. This function never re-checks and never attempts a second repair.

    Args:
        email: The current (failing) email body.
        failed: RuleResults with passed==False that need to be fixed.
        instruction_set: The raw instruction set dict (must have "instructions" list).
        config: Optional Config override; defaults to Config.from_env().

    Returns:
        The corrected email body as a plain string.
    """
    cfg = config or Config.from_env()

    instructions = instruction_set.get("instructions", [])
    instructions_block = "\n".join(
        f"{i + 1}. {instr}" for i, instr in enumerate(instructions)
    )

    violations_block = "\n".join(
        f"- [{r.rule_id}] {r.reason}" for r in failed
    )

    prompt = (
        f"INSTRUCTIONS THE EMAIL MUST FOLLOW:\n{instructions_block}\n\n"
        f"CURRENT EMAIL DRAFT:\n{email}\n\n"
        f"VIOLATIONS TO FIX:\n{violations_block}\n\n"
        f"Write a corrected version that fixes all listed violations without "
        f"introducing new ones."
    )

    response = call_json(
        prompt,
        _REPAIR_SCHEMA,
        system=_REPAIR_SYSTEM,
        config=cfg,
        model=cfg.writer_model_name,
    )

    return response["corrected_email"]
