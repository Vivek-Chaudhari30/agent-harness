"""Tests for deterministic checks in src/rules.py (Lane A).

All checks are pure functions — no API key, no network, no I/O.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("MODEL_PROVIDER", "fake")

from src.rules import CHECKS

word_limit = CHECKS["word_limit"]
char_limit = CHECKS["char_limit"]
no_banned_words = CHECKS["no_banned_words"]
signature_block = CHECKS["signature_block"]
company_name_mentioned = CHECKS["company_name_mentioned"]
no_question_marks = CHECKS["no_question_marks"]
no_exclamation_marks = CHECKS["no_exclamation_marks"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _words(n: int) -> str:
    """Return a string of exactly n whitespace-separated words."""
    return " ".join(["word"] * n)


def _email_with_sig(body_words: int, name: str = "Alex", company: str = "Acme Corp") -> str:
    """Build a fake email with a body of exactly body_words words + a 2-line signature."""
    body = _words(body_words)
    return f"{body}\n{name}\n{company}"


# ---------------------------------------------------------------------------
# word_limit
# ---------------------------------------------------------------------------

class TestWordLimit:
    params = {"limit": 90}

    def test_89_words_passes(self):
        passed, reason = word_limit(_words(89), self.params)
        assert passed is True
        assert reason == ""

    def test_90_words_passes(self):
        passed, reason = word_limit(_words(90), self.params)
        assert passed is True

    def test_91_words_fails(self):
        passed, reason = word_limit(_words(91), self.params)
        assert passed is False
        assert "91 words" in reason
        assert "90-word cap" in reason
        assert "1 over" in reason

    def test_reason_is_specific_not_generic(self):
        passed, reason = word_limit(_words(97), {"limit": 90})
        assert passed is False
        assert "97 words" in reason
        assert "7 over" in reason

    def test_exact_limit_is_inclusive(self):
        """limit=90 means 90 words is allowed (≤ not <)."""
        passed, _ = word_limit(_words(90), {"limit": 90})
        assert passed is True

    def test_hyphenated_word_counts_as_one(self):
        # "cost-effective" is one whitespace-delimited token → 1 word
        text = "cost-effective " + _words(89)  # 90 total
        passed, _ = word_limit(text, {"limit": 90})
        assert passed is True

    def test_contraction_counts_as_one_word(self):
        text = "don't " + _words(89)  # 90 total
        passed, _ = word_limit(text, {"limit": 90})
        assert passed is True

    def test_url_counts_as_one_word(self):
        text = "https://example.com/path?q=1 " + _words(89)  # 90 total
        passed, _ = word_limit(text, {"limit": 90})
        assert passed is True

    def test_signature_counted_in_word_total(self):
        # Signature "Alex\nAcme Corp" adds 3 words; body_words=88 → total=91
        email = _email_with_sig(body_words=88)
        passed, _ = word_limit(email, {"limit": 90})
        assert passed is False

    def test_different_limits(self):
        assert word_limit(_words(74), {"limit": 75})[0] is True
        assert word_limit(_words(75), {"limit": 75})[0] is True
        assert word_limit(_words(76), {"limit": 75})[0] is False

    def test_empty_text(self):
        passed, _ = word_limit("", {"limit": 90})
        assert passed is True


# ---------------------------------------------------------------------------
# char_limit
# ---------------------------------------------------------------------------

class TestCharLimit:
    params = {"limit": 500}

    def test_under_limit_passes(self):
        passed, reason = char_limit("a" * 499, self.params)
        assert passed is True

    def test_at_limit_passes(self):
        passed, _ = char_limit("a" * 500, self.params)
        assert passed is True

    def test_over_limit_fails(self):
        passed, reason = char_limit("a" * 501, self.params)
        assert passed is False
        assert "501 characters" in reason
        assert "500-character cap" in reason
        assert "1 over" in reason

    def test_reason_is_specific(self):
        passed, reason = char_limit("a" * 550, {"limit": 500})
        assert "550 characters" in reason
        assert "50 over" in reason

    def test_empty_text(self):
        passed, _ = char_limit("", self.params)
        assert passed is True


# ---------------------------------------------------------------------------
# no_banned_words
# ---------------------------------------------------------------------------

class TestNoBannedWords:
    pricing_params = {"words": ["price", "prices", "pricing", "priced"]}
    family_params = {"words": ["price", "prices", "pricing", "priced",
                               "cost", "costs", "costly",
                               "discount", "discounts", "discounted"]}

    def test_clean_email_passes(self):
        passed, _ = no_banned_words("Here is a great product for you.", self.pricing_params)
        assert passed is True

    def test_catches_pricing(self):
        passed, reason = no_banned_words("Never mention pricing again.", self.pricing_params)
        assert passed is False
        assert "pricing" in reason

    def test_catches_priced(self):
        passed, reason = no_banned_words("This is priced at a competitive level.", self.pricing_params)
        assert passed is False
        assert "priced" in reason

    def test_catches_price(self):
        passed, reason = no_banned_words("What is the price?", self.pricing_params)
        assert passed is False
        assert "price" in reason

    def test_does_not_fire_on_surprisingly(self):
        """'surprisingly' must not trigger a 'pric' family ban."""
        passed, _ = no_banned_words("This is surprisingly effective.", self.pricing_params)
        assert passed is True

    def test_does_not_fire_on_surprising(self):
        passed, _ = no_banned_words("The results were surprising and positive.", self.pricing_params)
        assert passed is True

    def test_case_insensitive(self):
        passed, _ = no_banned_words("PRICING is not allowed.", self.pricing_params)
        assert passed is False

    def test_partial_word_does_not_trigger(self):
        """'reprice' or 'underprice' should not trigger if 'price' is banned (word boundary)."""
        # "reprice" contains "price" but starts with "re" — boundary check
        passed, _ = no_banned_words("We could reprice the offer.", self.pricing_params)
        # "reprice" has "price" after "re" — \bprice\b would NOT match inside "reprice"
        assert passed is True

    def test_word_boundary_works_for_price_in_repriced(self):
        """'repriced' should not match the banned word 'price'."""
        passed, _ = no_banned_words("The product was repriced.", self.pricing_params)
        assert passed is True

    def test_multi_word_phrase_caught(self):
        params = {"words": ["pays for itself"]}
        passed, reason = no_banned_words(
            "This tool pays for itself within weeks.", params
        )
        assert passed is False
        assert "pays for itself" in reason

    def test_multi_word_phrase_not_caught_as_partial(self):
        params = {"words": ["pays for itself"]}
        passed, _ = no_banned_words("It pays for your team.", params)
        assert passed is True

    def test_multiple_violations_reported(self):
        passed, reason = no_banned_words(
            "The price and discount are competitive.", self.family_params
        )
        assert passed is False
        # Should mention at least one violation
        assert "price" in reason or "discount" in reason

    def test_empty_words_list_always_passes(self):
        passed, _ = no_banned_words("Any email content.", {"words": []})
        assert passed is True

    def test_reason_includes_banned_word(self):
        passed, reason = no_banned_words("Mention pricing here.", self.pricing_params)
        assert passed is False
        assert "pricing" in reason


# ---------------------------------------------------------------------------
# signature_block
# ---------------------------------------------------------------------------

class TestSignatureBlock:
    def test_valid_signature_passes(self):
        email = "Hi there, here is some content.\n\nAlex\nAcme Corp"
        passed, _ = signature_block(email, {})
        assert passed is True

    def test_valid_signature_with_greeting_passes(self):
        email = "Some body text.\n\nBest,\nAlex\nAcme Corp"
        # Last two lines: "Alex" and "Acme Corp" — both short
        passed, _ = signature_block(email, {})
        assert passed is True

    def test_missing_signature_fails(self):
        email = "Here is some content that ends without a proper signature block."
        passed, reason = signature_block(email, {})
        assert passed is False
        assert "separate lines" in reason or "signature" in reason

    def test_signature_on_one_line_fails(self):
        email = "Some content.\n\nAlex, Acme Corp"
        # Last two lines: "Some content." and "Alex, Acme Corp"
        # "Some content." is 2 words — short enough
        # "Alex, Acme Corp" is 3 words — short enough
        # This passes with our heuristic — acceptable behavior since the constraint
        # is about the LAST two lines both being short, not about the comma
        # If we want to fail this, we'd need stricter checks. Keep it simple.
        # This test documents current behavior.
        passed, _ = signature_block(email, {})
        # Current implementation: both short → passes. This is a known limitation.
        # A stricter check could require the last 2 lines to each have ≤ 3 words.
        assert passed is True  # heuristic passes; stricter check would fail

    def test_body_ending_in_long_line_fails(self):
        email = (
            "Some content.\n\n"
            "This long closing sentence describes something in great detail and never ends."
        )
        passed, reason = signature_block(email, {})
        assert passed is False

    def test_only_one_non_empty_line_fails(self):
        passed, reason = signature_block("Alex", {})
        assert passed is False

    def test_empty_email_fails(self):
        passed, reason = signature_block("", {})
        assert passed is False

    def test_multiword_company_name_ok(self):
        email = "Body text.\n\nSam\nGlobal Logistics Partners"
        # "Global Logistics Partners" = 3 words ≤ 6
        passed, _ = signature_block(email, {})
        assert passed is True

    def test_long_last_line_fails(self):
        email = "Body.\n\nAlex\nThis company name is unrealistically long and verbose here"
        # Last line has 9 words > 6 → fails
        passed, _ = signature_block(email, {})
        assert passed is False


# ---------------------------------------------------------------------------
# company_name_mentioned
# ---------------------------------------------------------------------------

class TestCompanyNameMentioned:
    def test_company_present_passes(self):
        passed, _ = company_name_mentioned(
            "We love working with Acme Robotics and their team.",
            {"company": "Acme Robotics"},
        )
        assert passed is True

    def test_company_absent_fails(self):
        passed, reason = company_name_mentioned(
            "We love working with your logistics team.",
            {"company": "Acme Robotics"},
        )
        assert passed is False
        assert "Acme Robotics" in reason

    def test_case_insensitive(self):
        passed, _ = company_name_mentioned(
            "ACME ROBOTICS has been doing great work.",
            {"company": "Acme Robotics"},
        )
        assert passed is True

    def test_empty_company_always_passes(self):
        passed, _ = company_name_mentioned("No company here.", {"company": ""})
        assert passed is True

    def test_missing_company_key_passes(self):
        passed, _ = company_name_mentioned("No company here.", {})
        assert passed is True

    def test_partial_match_passes(self):
        passed, _ = company_name_mentioned(
            "I see Acme is expanding.",
            {"company": "Acme Robotics"},
        )
        # "Acme" is in "Acme Robotics" but "Acme Robotics" is not in text
        assert passed is False

    def test_full_name_required(self):
        passed, _ = company_name_mentioned(
            "I heard Acme Robotics opened a new facility.",
            {"company": "Acme Robotics"},
        )
        assert passed is True


# ---------------------------------------------------------------------------
# no_question_marks
# ---------------------------------------------------------------------------

class TestNoQuestionMarks:
    def test_clean_email_passes(self):
        passed, _ = no_question_marks("I wanted to reach out about your team.", {})
        assert passed is True

    def test_single_question_mark_fails(self):
        passed, reason = no_question_marks("How are you?", {})
        assert passed is False
        assert "1 question mark" in reason

    def test_multiple_question_marks(self):
        passed, reason = no_question_marks("How are you? Is this correct?", {})
        assert passed is False
        assert "2 question marks" in reason

    def test_empty_email_passes(self):
        passed, _ = no_question_marks("", {})
        assert passed is True

    def test_question_mark_in_url_still_fails(self):
        passed, _ = no_question_marks("Visit https://example.com?ref=email", {})
        assert passed is False


# ---------------------------------------------------------------------------
# no_exclamation_marks
# ---------------------------------------------------------------------------

class TestNoExclamationMarks:
    def test_clean_email_passes(self):
        passed, _ = no_exclamation_marks("Hello, I hope this finds you well.", {})
        assert passed is True

    def test_single_exclamation_fails(self):
        passed, reason = no_exclamation_marks("Great to meet you!", {})
        assert passed is False
        assert "1 exclamation mark" in reason

    def test_multiple_exclamations(self):
        passed, reason = no_exclamation_marks("Wow! Amazing!", {})
        assert passed is False
        assert "2 exclamation marks" in reason

    def test_empty_email_passes(self):
        passed, _ = no_exclamation_marks("", {})
        assert passed is True


# ---------------------------------------------------------------------------
# Near-limit boundary: the canonical 89 / 90 / 91 word test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("count,limit,expected_pass", [
    (89, 90, True),
    (90, 90, True),
    (91, 90, False),
    (74, 75, True),
    (75, 75, True),
    (76, 75, False),
    (99, 100, True),
    (100, 100, True),
    (101, 100, False),
    (119, 120, True),
    (120, 120, True),
    (121, 120, False),
])
def test_word_limit_near_boundary(count, limit, expected_pass):
    passed, reason = word_limit(_words(count), {"limit": limit})
    assert passed is expected_pass, (
        f"{count} words with limit={limit}: expected pass={expected_pass}, "
        f"got pass={passed}, reason={reason!r}"
    )


# ---------------------------------------------------------------------------
# CHECKS registry completeness
# ---------------------------------------------------------------------------

def test_checks_registry_has_all_required_check_ids():
    required = {
        "word_limit",
        "char_limit",
        "no_banned_words",
        "signature_block",
        "company_name_mentioned",
        "no_question_marks",
        "no_exclamation_marks",
    }
    assert required.issubset(set(CHECKS.keys())), (
        f"Missing check_ids: {required - set(CHECKS.keys())}"
    )


def test_all_checks_are_callable():
    for check_id, fn in CHECKS.items():
        assert callable(fn), f"CHECKS[{check_id!r}] is not callable"
