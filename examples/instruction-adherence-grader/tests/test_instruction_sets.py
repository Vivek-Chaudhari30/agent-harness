"""Phase 0 coverage test: the 5 instruction sets exercise every category in
CONDUCTOR_KICKOFF.md section 4.6, so every downstream lane has something to build
against. Heuristic keyword checks over the verbatim instruction text.
"""

from __future__ import annotations

import os

from src import schemas

_INSTRUCTION_SETS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures",
    "instruction_sets.json",
)


def _all_instructions() -> list[str]:
    obj = schemas.load_instruction_sets(_INSTRUCTION_SETS)
    out = []
    for s in obj["sets"]:
        out.extend(i.lower() for i in s["instructions"])
    return out


def test_exactly_five_sets():
    obj = schemas.load_instruction_sets(_INSTRUCTION_SETS)
    assert len(obj["sets"]) == 5


def test_has_word_limit_including_a_tight_one():
    instrs = _all_instructions()
    word_limits = [i for i in instrs if "word" in i and "under" in i]
    assert word_limits, "need at least one word-limit instruction"
    # A tight cap that forces repair to work at it (target ~90 or below).
    assert any(
        n in " ".join(word_limits) for n in ("90 words", "75 words", "100 words")
    )


def test_has_character_limit():
    instrs = _all_instructions()
    assert any("character" in i for i in instrs)


def test_has_banned_pricing_family():
    instrs = _all_instructions()
    assert any("pricing" in i or "price" in i or "cost" in i or "discount" in i for i in instrs)


def test_has_signature_block_requirement():
    instrs = _all_instructions()
    assert any("sign off" in i or "sign-off" in i for i in instrs)


def test_has_company_reference_requirement():
    instrs = _all_instructions()
    assert any("company" in i for i in instrs)


def test_has_question_mark_constraint():
    instrs = _all_instructions()
    assert any("question" in i for i in instrs)


def test_has_exclamation_constraint():
    instrs = _all_instructions()
    assert any("exclamation" in i for i in instrs)


def test_has_semantic_specificity():
    instrs = _all_instructions()
    assert any("specific" in i for i in instrs)


def test_has_semantic_tone():
    instrs = _all_instructions()
    assert any("tone" in i or "corporate" in i for i in instrs)


def test_has_semantic_implied_pricing():
    instrs = _all_instructions()
    assert any("imply" in i or "cost-effective" in i or "pays for itself" in i for i in instrs)
