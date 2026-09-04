"""Deterministic check registry. (Lane A)

CHECKS maps a check_id to a pure callable fn(email_text, params) -> (passed, reason).
Pure Python only: no network, no file I/O, no clock, no randomness, so every check
is unit-testable without an API key.

Word-counting convention: words are whitespace-delimited tokens. Hyphenated compounds
("cost-effective"), contractions ("don't"), and URLs each count as one word. The
signature block is included in the word count.

company_name_mentioned: params["company"] must be populated by the caller (grader.py)
from the email record's recipient_context before running this check. If the company
key is absent or empty the check passes silently, since it cannot verify without the
name. See docs/contract-changes/lane-a-compiler.md for the rationale.
"""

from __future__ import annotations

import re
from typing import Callable


def _check_word_limit(text: str, params: dict) -> tuple[bool, str]:
    limit = params["limit"]
    count = len(text.split())
    if count <= limit:
        return True, ""
    over = count - limit
    return False, f"{count} words, {over} over the {limit}-word cap"


def _check_char_limit(text: str, params: dict) -> tuple[bool, str]:
    limit = params["limit"]
    count = len(text)
    if count <= limit:
        return True, ""
    over = count - limit
    return False, f"{count} characters, {over} over the {limit}-character cap"


def _check_no_banned_words(text: str, params: dict) -> tuple[bool, str]:
    """Word-boundary match for each banned word/phrase (case-insensitive).

    Single words use \\b anchors. Multi-word phrases use simple substring search
    (phrase boundaries are implicit in word sequences). The compiler expands word
    families so that banning "pricing" also bans "priced", "price", "prices".
    """
    found = []
    text_lower = text.lower()
    for phrase in params.get("words", []):
        phrase_lower = phrase.lower()
        if " " in phrase_lower or "-" in phrase_lower:
            # Multi-word or hyphenated phrase: use as-is with word boundary wrapping
            pattern = r"\b" + re.escape(phrase_lower) + r"\b"
        else:
            pattern = r"\b" + re.escape(phrase_lower) + r"\b"
        if re.search(pattern, text_lower):
            found.append(phrase)
    if not found:
        return True, ""
    if len(found) == 1:
        return False, f"contains banned word/phrase: '{found[0]}'"
    quoted = ", ".join(f"'{w}'" for w in found[:3])
    suffix = " (and more)" if len(found) > 3 else ""
    return False, f"contains banned words/phrases: {quoted}{suffix}"


def _check_signature_block(text: str, params: dict) -> tuple[bool, str]:
    """Check that the email ends with a name and company name on separate lines.

    Looks at the last two non-empty lines. Both must be short (≤6 words), which
    is consistent with a first name and a company name but not a full sentence.
    """
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return False, "email too short to contain a signature block"
    last = lines[-1].strip()
    second_last = lines[-2].strip()
    if len(last.split()) <= 6 and len(second_last.split()) <= 6:
        return True, ""
    return (
        False,
        "email does not end with a first name and company name on separate lines",
    )


def _check_company_name_mentioned(text: str, params: dict) -> tuple[bool, str]:
    """Check that the email mentions the recipient's company by name (case-insensitive).

    params["company"] must be populated by the caller from the email record's
    recipient_context. Returns True silently when company is empty.
    """
    company = params.get("company", "")
    if not company:
        return True, ""
    if company.lower() in text.lower():
        return True, ""
    return False, f"email does not mention the recipient's company by name ('{company}')"


def _check_no_question_marks(text: str, params: dict) -> tuple[bool, str]:
    count = text.count("?")
    if count == 0:
        return True, ""
    plural = "s" if count != 1 else ""
    return False, f"contains {count} question mark{plural}"


def _check_no_exclamation_marks(text: str, params: dict) -> tuple[bool, str]:
    count = text.count("!")
    if count == 0:
        return True, ""
    plural = "s" if count != 1 else ""
    return False, f"contains {count} exclamation mark{plural}"


# check_id -> fn(email_text, params) -> (passed, reason)
CHECKS: dict[str, Callable[[str, dict], tuple[bool, str]]] = {
    "word_limit": _check_word_limit,
    "char_limit": _check_char_limit,
    "no_banned_words": _check_no_banned_words,
    "signature_block": _check_signature_block,
    "company_name_mentioned": _check_company_name_mentioned,
    "no_question_marks": _check_no_question_marks,
    "no_exclamation_marks": _check_no_exclamation_marks,
}
