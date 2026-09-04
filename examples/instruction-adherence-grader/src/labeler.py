"""Blind first-pass labeler. (Lane C)

STUB. Implemented by Lane C. See docs/CONTRACTS.md section 2 and 3.3.

label_email is BLIND: it receives only the email text and the plain-English
instructions, the same input a careful reader would have. It MUST NOT receive
planted_violations, and it MUST NOT import semantic_check or reuse the checker's
judge prompts. Its prompt is written from scratch, framed as "read this cold and
say which instructions it breaks." A first pass that shares the grader's prompt
measures only whether the grader agrees with itself.
"""

from __future__ import annotations

from src.schemas import Label


def label_email(email_text: str, instruction_set: dict) -> list[Label]:
    raise NotImplementedError("lane C: src/labeler.py")
