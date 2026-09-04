"""Tests for src/compile.py (Lane A).

All tests run under MODEL_PROVIDER=fake with no API key.
"""

from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("MODEL_PROVIDER", "fake")

from src.compile import compile_instructions
from src.schemas import Rule, derive_rule_id


# ---------------------------------------------------------------------------
# Fixture: instruction sets from the canonical JSON file
# ---------------------------------------------------------------------------

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "fixtures",
    "instruction_sets.json",
)


def _load_sets() -> list[dict]:
    with open(_FIXTURE_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return data["sets"]


ALL_SETS = _load_sets()
SET_BY_ID = {s["id"]: s for s in ALL_SETS}


# ---------------------------------------------------------------------------
# Compile completeness: every instruction compiles to exactly one Rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("iset", ALL_SETS, ids=lambda s: s["id"])
def test_compile_produces_one_rule_per_instruction(iset):
    rules = compile_instructions(iset)
    assert len(rules) == len(iset["instructions"]), (
        f"{iset['id']}: expected {len(iset['instructions'])} rules, got {len(rules)}"
    )


@pytest.mark.parametrize("iset", ALL_SETS, ids=lambda s: s["id"])
def test_all_rules_are_rule_objects(iset):
    rules = compile_instructions(iset)
    for r in rules:
        assert isinstance(r, Rule), f"Expected Rule, got {type(r)}"


@pytest.mark.parametrize("iset", ALL_SETS, ids=lambda s: s["id"])
def test_no_unrecognized_instructions(iset):
    """compile_instructions must not raise for any instruction in any set."""
    rules = compile_instructions(iset)
    assert rules  # non-empty


# ---------------------------------------------------------------------------
# Rule id stability: ids come from instruction content, not list position
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("iset", ALL_SETS, ids=lambda s: s["id"])
def test_rule_ids_match_derive_rule_id(iset):
    rules = compile_instructions(iset)
    for rule, instruction in zip(rules, iset["instructions"]):
        expected = derive_rule_id(instruction)
        assert rule.id == expected, (
            f"Rule id mismatch for {instruction!r}: got {rule.id!r}, expected {expected!r}"
        )


def test_reordering_instructions_preserves_individual_ids():
    """Reordering instructions must not change any individual rule's id."""
    iset = dict(SET_BY_ID["is_01"])
    original = compile_instructions(iset)
    original_ids = {r.source_instruction: r.id for r in original}

    # Reverse order
    reversed_set = dict(iset, instructions=list(reversed(iset["instructions"])))
    reversed_rules = compile_instructions(reversed_set)

    for rule in reversed_rules:
        assert rule.id == original_ids[rule.source_instruction], (
            f"Rule id changed after reordering: {rule.source_instruction!r}"
        )


def test_rule_ids_are_unique_within_set():
    for iset in ALL_SETS:
        rules = compile_instructions(iset)
        ids = [r.id for r in rules]
        assert len(ids) == len(set(ids)), (
            f"{iset['id']}: duplicate rule ids: {ids}"
        )


def test_rule_instruction_set_id_matches():
    for iset in ALL_SETS:
        rules = compile_instructions(iset)
        for r in rules:
            assert r.instruction_set_id == iset["id"]


def test_source_instruction_is_verbatim():
    for iset in ALL_SETS:
        rules = compile_instructions(iset)
        for r, instruction in zip(rules, iset["instructions"]):
            assert r.source_instruction == instruction


# ---------------------------------------------------------------------------
# Kind classification: mix of deterministic and semantic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("iset", ALL_SETS, ids=lambda s: s["id"])
def test_each_set_has_both_kinds(iset):
    rules = compile_instructions(iset)
    kinds = {r.kind for r in rules}
    assert "deterministic" in kinds, f"{iset['id']}: no deterministic rules"
    assert "semantic" in kinds, f"{iset['id']}: no semantic rules"


# ---------------------------------------------------------------------------
# Deterministic rule correctness
# ---------------------------------------------------------------------------

class TestIs01:
    """is_01: casual founder-led outbound, hard word cap."""

    def setup_method(self):
        self.rules = compile_instructions(SET_BY_ID["is_01"])
        self.by_instr = {r.source_instruction: r for r in self.rules}

    def test_word_limit_90(self):
        r = self.by_instr["Keep it under 90 words."]
        assert r.kind == "deterministic"
        assert r.check_id == "word_limit"
        assert r.params["limit"] == 90

    def test_no_question_marks(self):
        r = self.by_instr["Do not ask a question in the first email."]
        assert r.kind == "deterministic"
        assert r.check_id == "no_question_marks"

    def test_no_exclamation_marks(self):
        r = self.by_instr["No exclamation marks."]
        assert r.kind == "deterministic"
        assert r.check_id == "no_exclamation_marks"

    def test_signature_block(self):
        r = self.by_instr["Sign off with a first name and company name on separate lines."]
        assert r.kind == "deterministic"
        assert r.check_id == "signature_block"

    def test_pricing_banned(self):
        r = self.by_instr["Never mention pricing."]
        assert r.kind == "deterministic"
        assert r.check_id == "no_banned_words"
        words = r.params["words"]
        assert "pricing" in words
        assert "price" in words
        assert "priced" in words

    def test_specificity_is_semantic(self):
        r = self.by_instr["Always reference something specific about their company."]
        assert r.kind == "semantic"
        assert r.judge_prompt is not None
        assert r.judge_prompt_sha is not None


class TestIs02:
    """is_02: casual tone, no pricing said or implied."""

    def setup_method(self):
        self.rules = compile_instructions(SET_BY_ID["is_02"])
        self.by_instr = {r.source_instruction: r for r in self.rules}

    def test_tone_is_semantic(self):
        r = self.by_instr["Keep the tone casual and conversational, never corporate."]
        assert r.kind == "semantic"
        assert r.judge_prompt is not None
        assert r.judge_prompt_sha is not None

    def test_banned_pricing_words_with_explicit_list(self):
        r = self.by_instr["Do not use pricing words such as price, cost, or discount."]
        assert r.kind == "deterministic"
        assert r.check_id == "no_banned_words"
        words = r.params["words"]
        # Should expand: price family, cost family, discount family
        assert "price" in words
        assert "pricing" in words
        assert "cost" in words
        assert "discount" in words

    def test_implied_pricing_is_semantic(self):
        r = self.by_instr[
            "Do not imply pricing indirectly with phrases like cost-effective, pays for itself, or ROI."
        ]
        assert r.kind == "semantic"
        assert r.judge_prompt is not None

    def test_word_limit_120(self):
        r = self.by_instr["Keep it under 120 words."]
        assert r.kind == "deterministic"
        assert r.check_id == "word_limit"
        assert r.params["limit"] == 120

    def test_signature_block(self):
        r = self.by_instr["Sign off with a first name and company name on separate lines."]
        assert r.check_id == "signature_block"


class TestIs03:
    """is_03: tight character budget, verifiable company reference."""

    def setup_method(self):
        self.rules = compile_instructions(SET_BY_ID["is_03"])
        self.by_instr = {r.source_instruction: r for r in self.rules}

    def test_char_limit_500(self):
        r = self.by_instr["Keep the whole email under 500 characters."]
        assert r.kind == "deterministic"
        assert r.check_id == "char_limit"
        assert r.params["limit"] == 500

    def test_company_name_mentioned(self):
        r = self.by_instr["Reference the recipient's company by name at least once."]
        assert r.kind == "deterministic"
        assert r.check_id == "company_name_mentioned"
        # params["company"] is a placeholder — caller must inject
        assert "company" in r.params

    def test_specificity_is_semantic(self):
        r = self.by_instr[
            "Reference something specific and verifiable about their company, not generic industry filler."
        ]
        assert r.kind == "semantic"
        assert r.judge_prompt is not None
        assert r.judge_prompt_sha is not None

    def test_no_exclamation_marks(self):
        r = self.by_instr["No exclamation marks."]
        assert r.check_id == "no_exclamation_marks"


class TestIs04:
    """is_04: warm and short, no questions, no pricing."""

    def setup_method(self):
        self.rules = compile_instructions(SET_BY_ID["is_04"])
        self.by_instr = {r.source_instruction: r for r in self.rules}

    def test_no_questions(self):
        r = self.by_instr["Do not ask any questions."]
        assert r.kind == "deterministic"
        assert r.check_id == "no_question_marks"

    def test_tone_is_semantic(self):
        r = self.by_instr["Keep the tone warm and casual, never stiff or corporate."]
        assert r.kind == "semantic"
        assert r.judge_prompt is not None

    def test_word_limit_75(self):
        r = self.by_instr["Keep it under 75 words."]
        assert r.check_id == "word_limit"
        assert r.params["limit"] == 75

    def test_pricing_discounts_banned(self):
        r = self.by_instr["Do not mention pricing or discounts."]
        assert r.kind == "deterministic"
        assert r.check_id == "no_banned_words"
        words = r.params["words"]
        assert "pricing" in words or "price" in words
        assert "discount" in words or "discounts" in words


class TestIs05:
    """is_05: polished first-touch, no exclamations or questions."""

    def setup_method(self):
        self.rules = compile_instructions(SET_BY_ID["is_05"])
        self.by_instr = {r.source_instruction: r for r in self.rules}

    def test_no_exclamation_marks(self):
        r = self.by_instr["Never use exclamation marks."]
        assert r.check_id == "no_exclamation_marks"

    def test_no_question_marks(self):
        r = self.by_instr["Do not ask a question in the first email."]
        assert r.check_id == "no_question_marks"

    def test_word_limit_100(self):
        r = self.by_instr["Keep it under 100 words."]
        assert r.check_id == "word_limit"
        assert r.params["limit"] == 100

    def test_company_name_mentioned(self):
        r = self.by_instr["Reference the recipient's company by name."]
        assert r.check_id == "company_name_mentioned"

    def test_implied_pricing_is_semantic(self):
        r = self.by_instr[
            "Do not imply pricing without stating it, avoiding phrases like affordable, saves you money, or pays for itself."
        ]
        assert r.kind == "semantic"
        assert r.judge_prompt is not None


# ---------------------------------------------------------------------------
# Semantic rule quality checks
# ---------------------------------------------------------------------------

def test_semantic_rules_have_judge_prompt_sha():
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "semantic":
                assert rule.judge_prompt_sha is not None, (
                    f"Semantic rule {rule.id!r} missing judge_prompt_sha"
                )
                assert len(rule.judge_prompt_sha) == 64, "sha256 should be 64 hex chars"


def test_semantic_rules_have_non_trivial_judge_prompt():
    """Judge prompt must be more than a restatement of the instruction."""
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "semantic":
                assert rule.judge_prompt is not None
                # Must contain the key elements: VIOLATION, NOT a violation, email placeholder
                assert "VIOLATION" in rule.judge_prompt, (
                    f"Judge prompt for {rule.id!r} missing VIOLATION definition"
                )
                assert "{email_text}" in rule.judge_prompt, (
                    f"Judge prompt for {rule.id!r} missing {{email_text}} placeholder"
                )
                assert "pass" in rule.judge_prompt.lower(), (
                    f"Judge prompt for {rule.id!r} missing 'pass' field"
                )
                assert "reason" in rule.judge_prompt.lower(), (
                    f"Judge prompt for {rule.id!r} missing 'reason' field"
                )


def test_judge_prompt_sha_matches_content():
    from src.schemas import sha256_hex
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "semantic":
                expected = sha256_hex(rule.judge_prompt)
                assert rule.judge_prompt_sha == expected, (
                    f"judge_prompt_sha mismatch for {rule.id!r}"
                )


def test_at_least_two_distinct_semantic_types():
    """At minimum two distinct semantic check types (tone, implied_pricing, specificity)."""
    all_prompts = set()
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "semantic":
                # Identify type from description keywords
                desc = rule.description.lower()
                if "tone" in desc or "casual" in desc or "corporate" in desc:
                    all_prompts.add("tone")
                elif "imply" in desc or "implied" in desc or "pricing" in desc:
                    all_prompts.add("implied_pricing")
                elif "specific" in desc or "verifiable" in desc:
                    all_prompts.add("specificity")
    assert len(all_prompts) >= 2, (
        f"Need at least 2 distinct semantic types, found: {all_prompts}"
    )


# ---------------------------------------------------------------------------
# Deterministic rule field invariants
# ---------------------------------------------------------------------------

def test_deterministic_rules_have_check_id():
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "deterministic":
                assert rule.check_id is not None, (
                    f"Deterministic rule {rule.id!r} missing check_id"
                )


def test_deterministic_rules_check_id_in_registry():
    from src.rules import CHECKS
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "deterministic":
                assert rule.check_id in CHECKS, (
                    f"check_id {rule.check_id!r} not in rules.CHECKS"
                )


def test_semantic_rules_have_no_check_id():
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "semantic":
                assert rule.check_id is None, (
                    f"Semantic rule {rule.id!r} should not have check_id"
                )


def test_deterministic_rules_have_no_judge_prompt():
    for iset in ALL_SETS:
        for rule in compile_instructions(iset):
            if rule.kind == "deterministic":
                assert rule.judge_prompt is None, (
                    f"Deterministic rule {rule.id!r} should not have judge_prompt"
                )
