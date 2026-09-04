"""Blind first-pass labeler. (Lane C)

label_email receives only the email text and the plain-English instruction set:
the same information a careful human reader would have. It must not receive
planted_violations and must not import semantic_check or reuse the checker's
judge prompts. The prompt here is framed as "read this cold and say which
instructions it breaks", which is categorically different from the checker's
per-rule judge prompts that Lane B compiles and executes one at a time.

A first pass that shares the grader's prompt would measure whether the grader
agrees with itself. This does not: it is an independent blind read designed to
produce a different error distribution than the checker, so the overturn rate
from human review is a real and informative signal.

Output is one Label per (email, rule) pair, covering every instruction in the
set. Missing pairs are an error; the caller that writes labels_model_draft.json
must validate completeness before writing.
"""

from __future__ import annotations

import hashlib

from src.config import Config
from src.model_client import call_json
from src.schemas import Label, derive_rule_id

# --------------------------------------------------------------------------- #
# Labeler prompt (written from scratch, not shared with semantic_check.py)
# --------------------------------------------------------------------------- #
_SYSTEM = (
    "You are a careful, skeptical email reviewer. You receive an outbound sales "
    "email and a list of plain-English writing rules the sender was supposed to "
    "follow. Your job is to read both cold and decide, for each rule, whether the "
    "email breaks it. You are not the author and you have no inside knowledge about "
    "what was intended. You only have what is on the page."
)

_PROMPT_TEMPLATE = """\
You will assess an outbound sales email against a set of writing rules.

RULES (numbered for reference only):
{rules_block}

EMAIL BODY:
---
{email_text}
---

For each numbered rule above, output a verdict. Read the email as a careful \
first-time reader would: does this email, as written, break that rule?

Guidelines:
- For word or character limits: count the words or characters in the email body \
exactly (excluding the label "EMAIL BODY" and the dashes, but including the \
signature). If within the limit, it passes; if over, it fails.
- For "no exclamation marks" or "no questions": look for the literal character "!" \
or "?". Also flag sentences that function as questions even without a "?" (e.g. \
"You might be wondering..." or "I would be curious to know...").
- For tone rules (casual, warm, corporate): judge the overall register of the email, \
not just individual words.
- For reference rules: distinguish between naming a company generically and citing \
something specific and verifiable about them (a product launch, a location, a hire).
- For implied pricing: flag phrases like "pays for itself", "saves you money", \
"ROI", "affordable", "cost-effective", "won't stretch your budget", even when no \
price is stated.
- For sign-off rules: the first name and company name must appear on separate lines.
- On borderline cases: mark confidence "low" and explain what makes it ambiguous.
- Reason must be one concrete line. For a pass, say why it clearly passes; \
for a fail, quote the specific text or describe the specific breach.

Return a JSON object with a "verdicts" array, one entry per rule in the same order \
as the numbered list above. Do not add, merge, or reorder rules.
"""

_LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_number": {"type": "integer"},
                    "violated": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "string"},
                },
                "required": ["rule_number", "violated", "reason", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def _prompt_sha(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def _build_prompt(email_text: str, instructions: list[str]) -> str:
    rules_block = "\n".join(f"{i + 1}. {ins}" for i, ins in enumerate(instructions))
    return _PROMPT_TEMPLATE.format(rules_block=rules_block, email_text=email_text)


def label_email(email_text: str, instruction_set: dict) -> list[Label]:
    """Blind first-pass labeling: one Label per rule in the instruction set.

    Receives only the email body and the plain-English instructions. Must not
    receive planted_violations. Does not import or call semantic_check.

    Returns one Label per instruction, in instruction-list order.
    The caller is responsible for supplying email_id to each label; this function
    returns Labels with email_id="" which the caller replaces.
    """
    instructions = instruction_set.get("instructions", [])
    if not instructions:
        return []

    prompt = _build_prompt(email_text, instructions)
    cfg = Config.from_env()
    result = call_json(prompt, _LABEL_SCHEMA, system=_SYSTEM, model=cfg.model_name, config=cfg)

    verdicts = result.get("verdicts", [])
    # Align verdicts to instructions by position (model is asked for same order).
    labels: list[Label] = []
    for i, instruction in enumerate(instructions):
        rule_id = derive_rule_id(instruction)
        # Fall back to "not violated" with a note if the model omitted a row.
        if i < len(verdicts):
            v = verdicts[i]
            violated = bool(v.get("violated", False))
            reason = str(v.get("reason", "")).strip() or "No reason given."
            raw_conf = str(v.get("confidence", "high")).lower()
            confidence = "low" if "low" in raw_conf else "high"
        else:
            violated = False
            reason = "Verdict not returned by labeler; defaulting to pass."
            confidence = "low"
        # Kind is derived from the static table (same as the fixtures fallback).
        # At integration the caller can override with compiled rule kinds.
        from src.fixtures import _KIND_BY_INSTRUCTION
        kind = _KIND_BY_INSTRUCTION.get(instruction, "semantic")
        labels.append(
            Label(
                email_id="",
                rule_id=rule_id,
                violated=violated,
                reason=reason,
                kind=kind,
                confidence=confidence,
                reviewed=False,
                overturned=False,
            )
        )
    return labels


def labeler_prompt_sha(instruction_set: dict, email_text: str = "") -> str:
    """Return the sha256 of the labeler prompt for provenance tracking."""
    instructions = instruction_set.get("instructions", [])
    prompt = _build_prompt(email_text, instructions)
    return _prompt_sha(prompt)
