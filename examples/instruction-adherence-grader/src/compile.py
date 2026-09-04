"""Rule compiler: plain-English instruction set -> Rule objects. (Lane A)

compile_instructions(instruction_set) classifies each plain-English instruction as
deterministic or semantic and emits a Rule with the right check_id/params or
judge_prompt. Pattern-matching over recognized instruction shapes is the right
scope here; no general NLP compilation is attempted.

Rule id derivation: always calls schemas.derive_rule_id(source_instruction), never
derives from list position. See CONTRACTS.md section 1 for why this matters.

Deterministic check_ids (registered in rules.CHECKS):
  word_limit          params: {"limit": int}
  char_limit          params: {"limit": int}
  no_banned_words     params: {"words": list[str]}  (compiler expands families)
  signature_block     params: {}
  company_name_mentioned  params: {"company": ""}   (caller must inject company name)
  no_question_marks   params: {}
  no_exclamation_marks params: {}

Semantic types (judge_prompt compiled at this step):
  tone                overall voice is casual / not corporate
  implied_pricing     language implying cost or financial return
  specificity         company reference is specific and verifiable, not generic filler
"""

from __future__ import annotations

import re

from src.schemas import Rule, derive_rule_id, sha256_hex

# ---------------------------------------------------------------------------
# Word-family expansions for banned-word checks.
# Banning "pricing" also bans its inflections. The CHECK uses exact word-
# boundary matching; the compiler is responsible for including all forms.
# ---------------------------------------------------------------------------
_WORD_FAMILIES: dict[str, list[str]] = {
    "pricing": ["price", "prices", "pricing", "priced"],
    "price": ["price", "prices", "pricing", "priced"],
    "priced": ["price", "prices", "pricing", "priced"],
    "cost": ["cost", "costs", "costly"],
    "costs": ["cost", "costs", "costly"],
    "discount": ["discount", "discounts", "discounted", "discounting"],
    "discounts": ["discount", "discounts", "discounted", "discounting"],
    "discounted": ["discount", "discounts", "discounted", "discounting"],
}


def _expand_words(words: list[str]) -> list[str]:
    """Expand each word to its family and deduplicate, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        for expanded in _WORD_FAMILIES.get(w.lower(), [w.lower()]):
            if expanded not in seen:
                seen.add(expanded)
                result.append(expanded)
    return result


# ---------------------------------------------------------------------------
# Compiled patterns (order matters: most specific first)
# ---------------------------------------------------------------------------
_SIGNATURE_RE = re.compile(
    r"(?i)sign\s+off\s+with.*first\s+name.*company"
    r"|sign\s+off\s+with.*name.*company.*separate"
)
_CHAR_LIMIT_RE = re.compile(r"(?i)under\s+(\d+)\s+characters?")
_WORD_LIMIT_RE = re.compile(r"(?i)under\s+(\d+)\s+words?")
_NO_EXCLAMATION_RE = re.compile(r"(?i)no\s+exclamation|never\s+use\s+exclamation")
_NO_QUESTIONS_RE = re.compile(r"(?i)do\s+not\s+ask\s+(a\s+|any\s+)?question")

# "do not imply pricing" / "do not imply pricing without stating it" → semantic
_IMPLIED_PRICING_RE = re.compile(r"(?i)imply\s+pric")

# Explicit banned-word list: "never mention pricing" / "do not use/mention X or Y"
# Must NOT match "imply pricing" instructions (those are semantic, caught above).
_BANNED_PRICING_RE = re.compile(
    r"(?i)"
    r"(never\s+mention\s+pric"
    r"|do\s+not\s+(use|mention)\s+(pricing\s+words?|pric)"
    r"|do\s+not\s+mention\s+(pricing|discounts?))"
)

# Explicit word list after "such as" or "such words as"
_SUCH_AS_RE = re.compile(r"(?i)(?:such\s+(?:words?\s+)?as|like)\s+([^.]+)")

# "or" list: "pricing or discounts"
_OR_LIST_RE = re.compile(r"(?i)(pricing|price|cost|discount)\s+or\s+(pricing|price|cost|discount)")

# Specificity: "something specific" about company — semantic
_SPECIFICITY_RE = re.compile(
    r"(?i)(specific\s+(and\s+verifiable\s+)?about\s+(their|the)|always\s+reference\s+something\s+specific)"
)

# Company by name (deterministic substring check): "reference.*company.*by name"
# but NOT if it also says "specific" (those go to specificity semantic rule)
_COMPANY_NAME_RE = re.compile(r"(?i)reference.*company.*by\s+name")

# Tone: "tone.*casual|conversational|warm" or contains corporate avoidance
_TONE_RE = re.compile(
    r"(?i)(keep\s+the\s+tone|tone\s+(casual|warm|conversational)|never\s+(stiff|corporate))"
)


# ---------------------------------------------------------------------------
# Judge prompt templates (compiled into Rule.judge_prompt at compile time)
# The only remaining variable when Lane B uses these is {email_text}.
# ---------------------------------------------------------------------------

_TONE_JUDGE_TEMPLATE = """\
RULE: "{instruction}"

You are evaluating whether the following outbound sales email follows the tone instruction above.

VIOLATION means: The email's overall voice is stiff, formal, corporate, or impersonal. It reads \
like a template, a press release, or a formal business letter rather than something a person would \
naturally write. Indicators: passive voice throughout, excessive business jargon, bureaucratic \
phrasing, or an impersonal register that would fit any recipient.

NOT a violation:
- Polite or professional phrasing alone is not a violation.
- Good grammar and clear structure are not violations.
- A single formal-sounding word in an otherwise warm, personal email does not constitute a \
violation; the overall register is what matters.
- Being organized and well-punctuated is not the same as being corporate.

Do NOT flag an email just because it is well-written. The question is whether it feels like a \
specific person wrote it to a specific recipient, or like a template was filled in.

EMAIL:
{email_text}

Respond with exactly these fields:
- "pass": true if the email's tone follows the instruction (i.e., is NOT stiff/corporate), \
false if it violates the tone instruction
- "reason": one sentence. If false, quote the specific phrase or describe the pattern that \
drove the decision.\
"""

_IMPLIED_PRICING_JUDGE_TEMPLATE = """\
RULE: "{instruction}"

You are evaluating whether the following outbound sales email implies pricing or cost-related \
value without explicitly stating a price or using explicitly banned pricing words.

VIOLATION means: The email uses language that prompts the reader to think about money, cost \
savings, or financial return, even if no explicit price or banned pricing word appears. Examples \
of violating language: "cost-effective," "pays for itself," "ROI in weeks," "saves you money," \
"affordable," "budget-friendly," "more than pays for the investment," "you'll recoup," or any \
phrase that frames the product in terms of financial benefit to the buyer.

NOT a violation:
- Describing a capability's outcome without a financial angle ("saves your team time," \
"reduces manual work") is not a violation.
- Generic value statements ("helps your team move faster") that do not invoke money or \
financial return are not violations.
- The test is whether the phrase causes the reader to think about cost or financial trade-offs, \
not just about outcomes or benefits.

Do NOT flag every mention of benefit as implied pricing. Only flag language that clearly invokes \
financial thinking.

EMAIL:
{email_text}

Respond with exactly these fields:
- "pass": true if the email does NOT imply pricing (i.e., follows the rule), false if it \
implies pricing or financial return
- "reason": one sentence. If false, quote the specific phrase that implies pricing.\
"""

_SPECIFICITY_JUDGE_TEMPLATE = """\
RULE: "{instruction}"

You are evaluating whether the following outbound sales email references the recipient's company \
in a specific, verifiable way — not just by name, and not with generic industry language.

VIOLATION means: The email either (a) does not mention the recipient's company at all, or (b) \
mentions the company name but only alongside language that would apply to any company in the same \
industry — for example, "I know you're growing fast," "I see you work in logistics," or "companies \
like yours face this challenge." The mention must be generic enough to fit a random competitor.

NOT a violation: Referencing the company name alongside any specific, checkable detail qualifies \
as a pass. The detail can be modest — a named product, a recent location opening, a specific \
initiative, a public announcement, a named team — as long as it is something that applies to this \
company specifically and not generically to every company in the space.

Do NOT penalize an email for mentioning the company name if it also includes a specific verifiable \
reference, even a small one. The question is whether a specific detail is present, not whether it \
is impressive.

EMAIL:
{email_text}

Respond with exactly these fields:
- "pass": true if the email references the company with a specific, verifiable detail, false if \
it does not
- "reason": one sentence. If false, state whether the company is not mentioned at all, or is \
mentioned only in a generic way.\
"""


# ---------------------------------------------------------------------------
# Per-instruction compiler
# ---------------------------------------------------------------------------

def _extract_banned_words_from_such_as(instruction: str) -> list[str]:
    """Extract words listed after 'such as' or 'like' in an instruction."""
    m = _SUCH_AS_RE.search(instruction)
    if not m:
        return []
    raw = m.group(1)
    # Split on commas (optionally followed by "or") and bare "or".
    # Handles "price, cost, or discount" where ", or" is a single separator.
    parts = re.split(r"\s*,\s*(?:or\s+)?|\s+or\s+", raw.strip().rstrip("."))
    return [p.strip().lower() for p in parts if p.strip()]


def _extract_banned_words_from_or(instruction: str) -> list[str]:
    """Extract words from 'pricing or discounts' style phrasings."""
    words: list[str] = []
    for m in re.finditer(
        r"(?i)\b(pricing|price|cost|discount|discounts)\b", instruction
    ):
        w = m.group(1).lower()
        if w not in words:
            words.append(w)
    return words


def _compile_one(instruction: str, is_id: str) -> Rule:
    rule_id = derive_rule_id(instruction)

    # --- Signature block ---
    if _SIGNATURE_RE.search(instruction):
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="deterministic",
            description="Email must end with the sender's first name and company name on separate lines.",
            check_id="signature_block",
            params={},
        )

    # --- Character limit ---
    m = _CHAR_LIMIT_RE.search(instruction)
    if m and "word" not in instruction.lower():
        limit = int(m.group(1))
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="deterministic",
            description=f"Email must be {limit} characters or fewer.",
            check_id="char_limit",
            params={"limit": limit},
        )

    # --- Word limit ---
    m = _WORD_LIMIT_RE.search(instruction)
    if m and "character" not in instruction.lower():
        limit = int(m.group(1))
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="deterministic",
            description=(
                f"Email must be {limit} words or fewer (signature included in the count)."
            ),
            check_id="word_limit",
            params={"limit": limit},
        )

    # --- No exclamation marks ---
    if _NO_EXCLAMATION_RE.search(instruction):
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="deterministic",
            description="Email must contain no exclamation marks.",
            check_id="no_exclamation_marks",
            params={},
        )

    # --- No question marks ---
    if _NO_QUESTIONS_RE.search(instruction):
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="deterministic",
            description="Email must contain no question marks.",
            check_id="no_question_marks",
            params={},
        )

    # --- Implied pricing (semantic) — must come before banned-word check ---
    if _IMPLIED_PRICING_RE.search(instruction):
        prompt = _IMPLIED_PRICING_JUDGE_TEMPLATE.format(
            instruction=instruction, email_text="{email_text}"
        )
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="semantic",
            description="Email must not imply pricing or financial return, even without banned words.",
            judge_prompt=prompt,
            judge_prompt_sha=sha256_hex(prompt),
        )

    # --- Explicit banned words (pricing / discount family) ---
    if _BANNED_PRICING_RE.search(instruction):
        # Try to extract an explicit "such as X, Y, Z" list
        words = _extract_banned_words_from_such_as(instruction)
        if not words:
            # Fall back to extracting from "pricing or discounts" style
            words = _extract_banned_words_from_or(instruction)
        if not words:
            words = ["pricing"]  # default for "never mention pricing"
        expanded = _expand_words(words)
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="deterministic",
            description=f"Email must not contain banned pricing words: {', '.join(expanded)}.",
            check_id="no_banned_words",
            params={"words": expanded},
        )

    # --- Specificity (semantic) — "specific about their company" ---
    if _SPECIFICITY_RE.search(instruction):
        prompt = _SPECIFICITY_JUDGE_TEMPLATE.format(
            instruction=instruction, email_text="{email_text}"
        )
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="semantic",
            description="Email must reference the recipient's company with a specific, verifiable detail.",
            judge_prompt=prompt,
            judge_prompt_sha=sha256_hex(prompt),
        )

    # --- Company name mentioned (deterministic) ---
    if _COMPANY_NAME_RE.search(instruction):
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="deterministic",
            description=(
                "Email must mention the recipient's company by name. "
                "Caller must populate params['company'] from the email record."
            ),
            check_id="company_name_mentioned",
            params={"company": ""},
        )

    # --- Tone (semantic) ---
    if _TONE_RE.search(instruction):
        prompt = _TONE_JUDGE_TEMPLATE.format(
            instruction=instruction, email_text="{email_text}"
        )
        return Rule(
            id=rule_id,
            instruction_set_id=is_id,
            source_instruction=instruction,
            kind="semantic",
            description="Email tone must be casual and personal, not corporate or stiff.",
            judge_prompt=prompt,
            judge_prompt_sha=sha256_hex(prompt),
        )

    # --- Unrecognized: raise rather than silently drop ---
    raise ValueError(
        f"compile_instructions: no pattern matched instruction {instruction!r} "
        f"in instruction set {is_id!r}. Add a pattern to compile.py or file a "
        "contract-change note."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compile_instructions(instruction_set: dict) -> list[Rule]:
    """Turn a plain-English instruction set into a list of Rule objects.

    Each instruction compiles to exactly one Rule, classified as deterministic
    or semantic. Rule ids are derived from instruction content via
    schemas.derive_rule_id, never from list position.

    Raises ValueError if an instruction matches no known pattern.
    """
    is_id = instruction_set["id"]
    return [_compile_one(instr, is_id) for instr in instruction_set["instructions"]]
