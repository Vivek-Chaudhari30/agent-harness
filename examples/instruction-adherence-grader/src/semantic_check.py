"""Semantic judge: one model call per semantic rule. (Lane B)

Exactly one model call per rule, through model_client.call_json, with strict
structured output {"pass": bool, "reason": str}. Never batch rules into one call,
because losing per-rule attribution defeats the purpose of this system.

The model_client debug log records the full request and response for every call
so a verdict is auditable later rather than a boolean someone has to trust.
"""

from __future__ import annotations

from src.config import Config
from src.model_client import call_json
from src.schemas import Rule, RuleResult

# Strict JSON Schema for the per-rule verdict. Every semantic call uses this.
_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "pass": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["pass", "reason"],
    "additionalProperties": False,
}


def _build_system_prompt(rule: Rule) -> str:
    """Return the judge system prompt for this rule.

    Uses rule.judge_prompt when Lane A has compiled one; falls back to a
    templated prompt derived from source_instruction otherwise.
    """
    if rule.judge_prompt:
        return rule.judge_prompt
    return (
        f"You are a strict compliance judge evaluating an outbound sales email.\n\n"
        f"RULE: {rule.source_instruction}\n\n"
        f"Return pass=true if the email fully obeys this rule. Return pass=false if it "
        f"violates it in any way. Provide a concise one-line reason that quotes or "
        f"paraphrases the specific text that caused your verdict."
    )


def check_semantic_rule(
    email: str,
    rule: Rule,
    *,
    config: Config | None = None,
) -> RuleResult:
    """Check one semantic rule against an email. Exactly one model call.

    The debug log written by model_client records the raw request and response
    so every verdict is independently auditable.

    Args:
        email: The email body to evaluate.
        rule: The semantic rule to check. Must have kind=="semantic".
        config: Optional Config override; defaults to Config.from_env().
    """
    cfg = config or Config.from_env()
    system = _build_system_prompt(rule)
    prompt = f"EMAIL TO EVALUATE:\n\n{email}"

    response = call_json(
        prompt,
        _VERDICT_SCHEMA,
        system=system,
        config=cfg,
    )

    return RuleResult(
        rule_id=rule.id,
        passed=response["pass"],
        reason=response["reason"],
        kind="semantic",
        source="semantic",
    )
