"""Email writer. Two deliberately separate modes.

`write_compliant_email` and `write_violating_email` are kept as two distinct
functions ON PURPOSE. The violating mode exists only to manufacture adversarial
fixtures (Lane C). It must NEVER be wired into the production repair path (Lane B),
because a repair path that can be told to break rules is a repair path that will,
eventually, break them by accident. Keep the two callers separate.

Both modes go through `model_client.call_json` with structured output; no free-text
parsing. The email body is returned as a plain string.
"""

from __future__ import annotations

from src.config import Config
from src.model_client import call_json
from src.schemas import derive_rule_id

# The model must return exactly this shape.
_EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "email": {
            "type": "string",
            "description": "The full email body, ready to send.",
        }
    },
    "required": ["email"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write short outbound sales emails. You are given a sender persona, a set "
    "of plain-English writing rules, and some context about the recipient's company. "
    "Return only the email body."
)


def _recipient_block(recipient_context: dict) -> str:
    lines = []
    for key in ("company", "industry", "detail"):
        if recipient_context.get(key):
            lines.append(f"- {key}: {recipient_context[key]}")
    for key, value in recipient_context.items():
        if key not in ("company", "industry", "detail") and value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines) if lines else "- (no specific recipient detail provided)"


def _instructions_block(instruction_set: dict) -> str:
    return "\n".join(f"- {i}" for i in instruction_set.get("instructions", []))


def write_compliant_email(instruction_set: dict, recipient_context: dict) -> str:
    """Write an email that obeys every rule in the instruction set.

    This is the honest, production-shaped mode: follow all the rules.
    """
    prompt = (
        f"Sender persona: {instruction_set.get('sender_persona', 'a sales rep')}\n\n"
        "Follow ALL of these rules exactly:\n"
        f"{_instructions_block(instruction_set)}\n\n"
        "Recipient context:\n"
        f"{_recipient_block(recipient_context)}\n\n"
        "Write one short outbound email that obeys every rule above. Make the "
        "company reference concrete and specific to this recipient, not generic "
        "industry filler."
    )
    cfg = Config.from_env()
    result = call_json(
        prompt, _EMAIL_SCHEMA, model=cfg.writer_model_name, system=_SYSTEM, config=cfg
    )
    return result["email"]


def write_violating_email(
    instruction_set: dict,
    recipient_context: dict,
    violate_rule_ids: list[str],
) -> str:
    """Write an email that deliberately breaks exactly the given rules.

    FIXTURE GENERATION ONLY. Do not call this from repair or any production path.

    `violate_rule_ids` are rule ids as produced by `schemas.derive_rule_id` over the
    instruction texts. We map them back to their instructions here so the model
    knows precisely which rules to break and which to keep.
    """
    id_to_instruction = {
        derive_rule_id(i): i for i in instruction_set.get("instructions", [])
    }
    to_break: list[str] = []
    for rid in violate_rule_ids:
        instruction = id_to_instruction.get(rid)
        to_break.append(instruction if instruction else f"(rule id: {rid})")
    to_keep = [
        i
        for i in instruction_set.get("instructions", [])
        if derive_rule_id(i) not in set(violate_rule_ids)
    ]

    break_block = (
        "\n".join(f"- {b}" for b in to_break)
        if to_break
        else "- (break nothing; write a fully compliant email)"
    )
    keep_block = (
        "\n".join(f"- {k}" for k in to_keep)
        if to_keep
        else "- (no other rules)"
    )

    prompt = (
        f"Sender persona: {instruction_set.get('sender_persona', 'a sales rep')}\n\n"
        "You are manufacturing a TEST email for a grader. Deliberately BREAK exactly "
        "these rules, and no others:\n"
        f"{break_block}\n\n"
        "Keep obeying all of these rules:\n"
        f"{keep_block}\n\n"
        "Recipient context:\n"
        f"{_recipient_block(recipient_context)}\n\n"
        "Write one short outbound email. Break the listed rules naturally, the way a "
        "careless human would, not with obvious flags. Keep every other rule intact."
    )
    cfg = Config.from_env()
    result = call_json(
        prompt, _EMAIL_SCHEMA, model=cfg.writer_model_name, system=_SYSTEM, config=cfg
    )
    return result["email"]
