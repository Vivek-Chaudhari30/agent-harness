"""Adversarial fixture generation. (Lane C)

Two callers, one shape:

  * `generate_fixtures` is the LIVE generator used by `make fixtures` at
    integration. It compiles an instruction set into rules, decides which rules
    (if any) each email should deliberately break, and calls the Phase 0 writer
    (`write_compliant_email` / `write_violating_email`) to produce the body. It
    never re-implements the model-calling writer.

  * `build_seed_corpus` produces the committed `fixtures/emails.json`: a curated,
    fully deterministic corpus authored so that every adversarial case Phase 3
    demands is present and identifiable, and so the two near-limit word counts sit
    exactly where they stress the boundary. Curated golden data is the right tool
    for *borderline* cases: a human controlling the prose is more reliable at
    placing a disagreement on the knife-edge than a model asked to be subtle. The
    seed is regenerated live at integration if desired; the bodies here exist so
    the review sheet has 50 real emails to open before the API is ever touched.

`planted_violations` is generation bookkeeping only. It records which rule ids the
writer was told to break. It is NEVER read by the checker, the labeler, or the
scorer; only a human reads it, to sanity-check coverage.

Rule ids. We obtain them by compiling the instruction set (`compile.compile_instructions`,
Lane A). When that module is still a stub in an isolated worktree, we fall back to
`schemas.derive_rule_id`, which is the single canonical derivation the compiler
itself uses, so the ids are byte-identical either way. We never hand-write a rule
id and never invent a second derivation. See docs/contract-changes/lane-c-fixtures.md.
"""

from __future__ import annotations

from src.schemas import Label, derive_rule_id

# Deterministic timestamp for the curated seed: no wall clock, so re-running the
# builder is reproducible and diff-free (matches the project's no-randomness rule).
_SEED_CREATED_AT = "2026-09-03T00:00:00Z"
_SEED_MODEL = "curated-seed"

# Kind per instruction, used only as a fallback when compile.py is still a stub.
# This mirrors the classification Lane A's compiler produces; at integration the
# real compiler supplies kind and this table is not consulted.
_KIND_BY_INSTRUCTION: dict[str, str] = {
    "Never mention pricing.": "deterministic",
    "Keep it under 90 words.": "deterministic",
    "Do not ask a question in the first email.": "deterministic",
    "Always reference something specific about their company.": "semantic",
    "No exclamation marks.": "deterministic",
    "Sign off with a first name and company name on separate lines.": "deterministic",
    "Keep the tone casual and conversational, never corporate.": "semantic",
    "Do not use pricing words such as price, cost, or discount.": "deterministic",
    "Do not imply pricing indirectly with phrases like cost-effective, pays for itself, or ROI.": "semantic",
    "Keep it under 120 words.": "deterministic",
    "Keep the whole email under 500 characters.": "deterministic",
    "Reference the recipient's company by name at least once.": "deterministic",
    "Reference something specific and verifiable about their company, not generic industry filler.": "semantic",
    "Do not ask any questions.": "deterministic",
    "Keep the tone warm and casual, never stiff or corporate.": "semantic",
    "Keep it under 75 words.": "deterministic",
    "Do not mention pricing or discounts.": "deterministic",
    "Never use exclamation marks.": "deterministic",
    "Keep it under 100 words.": "deterministic",
    "Reference the recipient's company by name.": "deterministic",
    "Do not imply pricing without stating it, avoiding phrases like affordable, saves you money, or pays for itself.": "semantic",
}


# --------------------------------------------------------------------------- #
# Rule resolution: compile if we can, canonical-derive if the compiler is a stub.
# --------------------------------------------------------------------------- #
class ResolvedRule:
    """The slice of a compiled rule the fixture path needs: id, text, kind."""

    __slots__ = ("index", "instruction", "rule_id", "kind")

    def __init__(self, index: int, instruction: str, rule_id: str, kind: str) -> None:
        self.index = index
        self.instruction = instruction
        self.rule_id = rule_id
        self.kind = kind


def resolve_rules(instruction_set: dict) -> list[ResolvedRule]:
    """Return one ResolvedRule per instruction, in order.

    Prefers Lane A's `compile_instructions`; falls back to the canonical
    `derive_rule_id` (plus the static kind table) when compile.py is still a stub.
    Either path yields identical rule ids.
    """
    instructions = instruction_set.get("instructions", [])
    compiled = _try_compile(instruction_set)
    if compiled is not None:
        by_instruction = {r.source_instruction: r for r in compiled}
        out: list[ResolvedRule] = []
        for i, ins in enumerate(instructions):
            r = by_instruction.get(ins)
            if r is None:
                out.append(_derived_rule(i, ins))
            else:
                out.append(ResolvedRule(i, ins, r.id, r.kind))
        return out
    return [_derived_rule(i, ins) for i, ins in enumerate(instructions)]


def _try_compile(instruction_set: dict):
    try:
        from src.compile import compile_instructions
    except Exception:
        return None
    try:
        rules = compile_instructions(instruction_set)
    except NotImplementedError:
        return None
    except Exception:
        return None
    return rules or None


def _derived_rule(index: int, instruction: str) -> ResolvedRule:
    return ResolvedRule(
        index,
        instruction,
        derive_rule_id(instruction),
        _KIND_BY_INSTRUCTION.get(instruction, "semantic"),
    )


# --------------------------------------------------------------------------- #
# Live generator (used by `make fixtures` at integration)
# --------------------------------------------------------------------------- #
def generate_fixtures(instruction_sets: list[dict], per_set: int = 10) -> list[dict]:
    """Generate `per_set` emails per instruction set using the Phase 0 writer.

    For each planned email we resolve the rules to break into rule ids, ask the
    writer to break exactly those (or write a fully compliant email when none),
    and record the ids as `planted_violations`. The body comes from the writer;
    we do not author it here. This is the honest production-shaped path and needs
    a live model, so its output is not what ships in the committed seed.
    """
    from src.writer import write_compliant_email, write_violating_email

    by_id = {s["id"]: s for s in instruction_sets}
    records: list[dict] = []
    counter = 0
    for set_id, entries in _plan_by_set().items():
        instruction_set = by_id.get(set_id)
        if instruction_set is None:
            continue
        rules = resolve_rules(instruction_set)
        for entry in entries[:per_set]:
            counter += 1
            email_id = f"em_{counter:03d}"
            violate_ids = [rules[i].rule_id for i in entry["violate"]]
            recipient = entry["recipient"]
            if violate_ids:
                body = write_violating_email(instruction_set, recipient, violate_ids)
                mode = "violating"
            else:
                body = write_compliant_email(instruction_set, recipient)
                mode = "compliant"
            records.append(
                _record(email_id, set_id, recipient, body, violate_ids,
                        entry["difficulty"], mode, entry.get("tags", []))
            )
    return records


# --------------------------------------------------------------------------- #
# Curated seed corpus (committed fixtures/emails.json)
# --------------------------------------------------------------------------- #
def build_seed_corpus(instruction_sets: list[dict]) -> list[dict]:
    """Assemble the 50 curated email records deterministically, no model calls."""
    by_id = {s["id"]: s for s in instruction_sets}
    records: list[dict] = []
    counter = 0
    for set_id, entries in _plan_by_set().items():
        instruction_set = by_id[set_id]
        rules = resolve_rules(instruction_set)
        for entry in entries:
            counter += 1
            email_id = f"em_{counter:03d}"
            violate_ids = [rules[i].rule_id for i in entry["violate"]]
            mode = "violating" if violate_ids else "compliant"
            records.append(
                _record(email_id, set_id, entry["recipient"], entry["body"],
                        violate_ids, entry["difficulty"], mode, entry.get("tags", []))
            )
    return records


def build_draft_labels(instruction_sets: list[dict]) -> list[Label]:
    """One draft Label per (email, rule) for the whole curated corpus.

    The draft is a deliberately imperfect first pass: it is what a blind reader
    would guess, and on the borderline rows it disagrees with what a careful human
    would conclude, so the review gate has real overturns to make. `reviewed` and
    `overturned` are both false here; the review tool sets them.
    """
    by_id = {s["id"]: s for s in instruction_sets}
    labels: list[Label] = []
    counter = 0
    for set_id, entries in _plan_by_set().items():
        instruction_set = by_id[set_id]
        rules = resolve_rules(instruction_set)
        for entry in entries:
            counter += 1
            email_id = f"em_{counter:03d}"
            draft = entry.get("draft", {})
            for rule in rules:
                verdict = draft.get(rule.index)
                if verdict is None:
                    violated, reason, confidence = (
                        False, "Reads clean on this instruction.", "high"
                    )
                else:
                    violated, reason, confidence = verdict
                labels.append(
                    Label(
                        email_id=email_id,
                        rule_id=rule.rule_id,
                        violated=violated,
                        reason=reason,
                        kind=rule.kind,
                        confidence=confidence,
                    )
                )
    return labels


def _record(email_id, set_id, recipient, body, violate_ids, difficulty, mode, tags):
    rec = {
        "id": email_id,
        "instruction_set_id": set_id,
        "recipient_context": recipient,
        "body": body,
        "planted_violations": violate_ids,
        "difficulty": difficulty,
        "generation": {
            "mode": mode,
            "model": _SEED_MODEL,
            "created_at": _SEED_CREATED_AT,
        },
    }
    if tags:
        rec["adversarial_tags"] = tags
    return rec


def _plan_by_set() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for entry in _PLAN:
        grouped.setdefault(entry["set"], []).append(entry)
    return grouped


# --------------------------------------------------------------------------- #
# The authored plan. 50 emails, 10 per set. Draft verdicts keyed by rule index.
# Difficulty mix: 11 clean, 20 single, 8 multiple, 11 borderline.
# --------------------------------------------------------------------------- #
_V = True   # violated, in a draft tuple
_OK = False

_PLAN: list[dict] = [
    # ----------------------- is_01: casual founder, hard 90-word cap --------- #
    {
        "set": "is_01",
        "recipient": {"company": "Acme Robotics", "industry": "industrial automation",
                      "detail": "opened a second assembly line in Ohio last month"},
        "difficulty": "clean",
        "violate": [],
        "tags": ["near_limit_word_count_under"],
        "body": (
            "Hi Acme Robotics team,\n\n"
            "Saw the note about your second assembly line opening in Ohio, and getting "
            "it running ahead of schedule is no small thing. Most teams standing up a "
            "new line end up with three tools that refuse to talk to each other, and "
            "the handoffs quietly eat a day a week. We stitch those handoffs together "
            "without anyone changing how they already work. I would love to walk you "
            "through the short version and hear whether it maps to how your floor "
            "actually runs.\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Acme Robotics", "industry": "industrial automation",
                      "detail": "opened a second assembly line in Ohio last month"},
        "difficulty": "single",
        "violate": [1],
        "tags": ["near_limit_word_count_over"],
        "draft": {1: (_V, "Runs a couple of words past the 90-word cap.", "low")},
        "body": (
            "Hi Acme Robotics team,\n\n"
            "Saw the note about your second assembly line opening in Ohio, and getting "
            "it running ahead of schedule is genuinely no small thing at all. Most "
            "teams standing up a brand new line end up with three separate tools that "
            "refuse to talk to each other, and the handoffs quietly eat a full day a "
            "week. We stitch those handoffs together without anyone changing how they "
            "already work today. I would love to walk you through the short version "
            "and hear whether it truly maps to how your floor actually runs.\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Northwind Freight", "industry": "trucking and freight",
                      "detail": "rolled out a driver mobile app this spring"},
        "difficulty": "borderline",
        "violate": [2],
        "tags": ["indirect_question_no_qmark"],
        "draft": {2: (_V, "Frames a question rhetorically without a question mark.", "low")},
        "body": (
            "Hi Northwind Freight team,\n\n"
            "You might be wondering how a driver app like the one you rolled out this "
            "spring holds up once dispatch volume spikes. That gap between the app and "
            "the back office is exactly where we live. We keep the two in sync so "
            "nobody rekeys a load twice. Happy to show you what that looks like on a "
            "real week of freight.\n\n"
            "Best,\nMara\nRelaylane"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Cascade Logistics", "industry": "third-party logistics",
                      "detail": "expanded into refrigerated warehousing"},
        "difficulty": "single",
        "violate": [0],
        "draft": {0: (_V, "States pricing outright.", "high")},
        "body": (
            "Hi Cascade Logistics team,\n\n"
            "Congrats on moving into refrigerated warehousing, that is a hard mode to "
            "add. Our pricing starts at a flat monthly rate that undercuts what most "
            "cold-chain teams pay for tracking. We keep temperature logs and handoffs "
            "in one place so audits stop being a fire drill. I would love to show you "
            "the short version.\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Latham Manufacturing", "industry": "contract manufacturing",
                      "detail": "took on a large aerospace client this year"},
        "difficulty": "single",
        "violate": [4],
        "draft": {4: (_V, "Uses exclamation marks.", "high")},
        "body": (
            "Hi Latham Manufacturing team,\n\n"
            "Landing a big aerospace client this year is a huge deal! Those programs "
            "bury a floor in paperwork fast, and the handoffs between stations are "
            "where quality slips. We keep all of that in one thread so nothing gets "
            "lost. Would love to show you the short version!\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Pinnacle Freight", "industry": "freight brokerage",
                      "detail": "hired a new head of operations recently"},
        "difficulty": "single",
        "violate": [5],
        "draft": {5: (_V, "Sign-off is on one line without the company name.", "high")},
        "body": (
            "Hi Pinnacle Freight team,\n\n"
            "With a new head of operations settling in, this is the moment tooling gaps "
            "get noticed. We stitch the load handoffs your brokers do by hand into one "
            "clean flow, so onboarding a process change takes a day instead of a "
            "quarter. Glad to walk the new ops lead through it whenever the dust "
            "settles.\n\n"
            "Thanks, Dev"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Orchard Software", "industry": "field-service software",
                      "detail": "a mid-size company in field service"},
        "difficulty": "borderline",
        "violate": [3],
        "tags": ["namedrop_boilerplate"],
        "draft": {3: (_V, "Names the company but the reference is generic industry filler.", "low")},
        "body": (
            "Hi Orchard Software team,\n\n"
            "Companies in field service like Orchard Software all run into the same "
            "wall as they scale: too many tools, not enough glue. We are the glue. We "
            "connect the systems your teams already use so the handoffs stop leaking "
            "time. I would love to walk you through the short version.\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Meridian Foods", "industry": "food distribution",
                      "detail": "added a second distribution hub"},
        "difficulty": "multiple",
        "violate": [0, 4],
        "draft": {
            0: (_V, "States a monthly price.", "high"),
            4: (_V, "Uses exclamation marks.", "high"),
        },
        "body": (
            "Hi Meridian Foods team,\n\n"
            "A second distribution hub is a great problem to have! Our platform runs "
            "$400 a month and ties your two hubs into one view so nothing falls "
            "between them. Congrats again on the expansion!\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Vantage Health", "industry": "medical device distribution",
                      "detail": "a mid-size medical distributor"},
        "difficulty": "multiple",
        "violate": [1, 2, 3],
        "draft": {
            1: (_V, "Well over the 90-word cap.", "high"),
            2: (_V, "Ends on a direct question.", "high"),
            3: (_V, "No specific reference to the recipient.", "low"),
        },
        "body": (
            "Hi there,\n\n"
            "I am reaching out because a lot of distributors your size are drowning in "
            "disconnected systems, and I think we can help. Our platform brings every "
            "handoff into a single place so your team stops rekeying the same order "
            "into three tools, which is the kind of quiet tax that adds up to a full "
            "day a week per person once you actually measure it across a quarter. We "
            "have done this for teams a lot like yours and the results were strong. "
            "Would you be open to a quick call next week to see whether it fits how "
            "your operation runs today?\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },
    {
        "set": "is_01",
        "recipient": {"company": "Brightline Retail", "industry": "specialty retail",
                      "detail": "launched a same-day delivery pilot in Austin"},
        "difficulty": "clean",
        "violate": [],
        "body": (
            "Hi Brightline Retail team,\n\n"
            "Your same-day delivery pilot in Austin caught my eye. Same-day is where "
            "the seams between order, pick, and dispatch really show, and a dropped "
            "handoff there costs you a customer, not just a minute. We keep those "
            "steps in one flow so the pilot can scale without a rebuild. I would love "
            "to walk you through the short version.\n\n"
            "Talk soon,\nDev\nFlowstitch"
        ),
    },

    # ----------------------- is_02: casual, no implied pricing --------------- #
    {
        "set": "is_02",
        "recipient": {"company": "Harborview Support Co", "industry": "customer support outsourcing",
                      "detail": "a mid-size support BPO"},
        "difficulty": "clean",
        "violate": [],
        "body": (
            "Hey Harborview team,\n\n"
            "Quick one. Running a support floor at your size usually means agents "
            "bouncing between a helpdesk, a wiki, and three chat windows just to "
            "answer one ticket. We pull the answers into the same place the agent is "
            "already typing, so the good reps stop playing detective. Want me to send "
            "over a two-minute clip of it working on a real queue? No pressure either "
            "way.\n\n"
            "Cheers,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Tidewater Apps", "industry": "consumer mobile apps",
                      "detail": "a fast-growing app studio"},
        "difficulty": "borderline",
        "violate": [2],
        "tags": ["implied_pricing_no_banned_word"],
        "draft": {2: (_V, "Implies pricing value without a banned word.", "low")},
        "body": (
            "Hey Tidewater team,\n\n"
            "Loved seeing how fast your studio is shipping lately. Here is the thing "
            "we hear from teams growing at your clip: support headcount balloons right "
            "when you least want it to. Our tool basically pays for itself within a "
            "quarter because one agent handles what used to take three, and the "
            "returns show up in weeks, not some far-off someday. Want a peek at it "
            "running on a real queue?\n\n"
            "Cheers,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Copperline Retail", "industry": "e-commerce",
                      "detail": "a mid-size online retailer"},
        "difficulty": "single",
        "violate": [1],
        "draft": {1: (_V, "Uses the banned word 'cost'.", "high")},
        "body": (
            "Hey Copperline team,\n\n"
            "Quick one. Support at your volume gets expensive fast, and most of that "
            "cost is agents digging for answers that already exist somewhere. We drop "
            "those answers right where the agent is typing. Want me to send a short "
            "clip of it on a live queue?\n\n"
            "Cheers,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Sterling Financial Group", "industry": "financial services",
                      "detail": "a mid-size wealth manager"},
        "difficulty": "borderline",
        "violate": [0],
        "tags": ["corporate_tone_drift"],
        "draft": {0: (_V, "Tone drifts corporate rather than casual.", "low")},
        "body": (
            "Hello Sterling Financial Group,\n\n"
            "I am reaching out to explore whether there may be an opportunity to align "
            "on how your organization handles client-support operations this quarter. "
            "We enable support teams to leverage existing knowledge more effectively "
            "and drive measurable efficiency across the function. I would welcome the "
            "chance to connect and discuss how this maps to your strategic "
            "priorities.\n\n"
            "Regards,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Junebug Goods", "industry": "consumer goods",
                      "detail": "a growing DTC brand"},
        "difficulty": "single",
        "violate": [3],
        "draft": {3: (_V, "Runs well past the 120-word cap.", "high")},
        "body": (
            "Hey Junebug team,\n\n"
            "Quick one, and I will keep it real. When a DTC brand takes off the way "
            "yours has, support is usually the first thing to buckle, because every "
            "new customer is a new question and the team answering them is still the "
            "same three people who were there at the start. What tends to happen is "
            "the good reps burn out playing detective across a helpdesk, a wiki, and a "
            "handful of chat threads that never quite agree with each other. We fix "
            "that by pulling the right answer into the exact place the agent is "
            "already typing, so nobody has to go hunting, and the answers stay "
            "consistent no matter who is on shift. Teams tell us it feels less like "
            "adding a tool and more like finally giving the team the memory it always "
            "should have had. Want a peek at it on a live queue sometime this week?\n\n"
            "Cheers,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Alderman Health", "industry": "healthtech",
                      "detail": "a telehealth startup"},
        "difficulty": "single",
        "violate": [4],
        "draft": {4: (_V, "Sign-off omits the company line.", "high")},
        "body": (
            "Hey Alderman Health team,\n\n"
            "Quick one. Telehealth support has a nasty habit of turning every routine "
            "question into a five-tool scavenger hunt. We keep the answers where your "
            "agents already work so they can actually stay with the patient. Want a "
            "short clip of it on a live queue?\n\n"
            "Cheers,\nJonah"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Redwood Outfitters", "industry": "outdoor retail",
                      "detail": "a mid-size outdoor gear retailer"},
        "difficulty": "multiple",
        "violate": [1, 2],
        "draft": {
            1: (_V, "Uses the banned word 'cost'.", "high"),
            2: (_V, "Also implies pricing with 'cost-effective' and 'pays for itself'.", "high"),
        },
        "body": (
            "Hey Redwood team,\n\n"
            "Quick one. Support at peak season gets pricey, and the cost mostly comes "
            "from agents hunting for answers. Our tool is genuinely cost-effective and "
            "pays for itself fast because one rep does the work of three. Want a clip "
            "of it on a live queue?\n\n"
            "Cheers,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Maple & Co", "industry": "home goods",
                      "detail": "a mid-size home goods brand"},
        "difficulty": "clean",
        "violate": [],
        "body": (
            "Hey Maple & Co team,\n\n"
            "Quick one. As a home goods brand scales, the same twenty questions come "
            "in a thousand different ways, and your reps end up rewriting the same "
            "answer all day. We surface the right one automatically, right where they "
            "are typing. Want me to send a two-minute clip of it working on a live "
            "queue? Totally fine if the timing is off.\n\n"
            "Cheers,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Gearbox Tools", "industry": "hardware e-commerce",
                      "detail": "a mid-size tool retailer"},
        "difficulty": "borderline",
        "violate": [],
        "tags": ["borderline_value_not_pricing"],
        "draft": {2: (_V, "Reads like implied pricing, though it only claims time saved.", "low")},
        "body": (
            "Hey Gearbox team,\n\n"
            "Quick one. Your reps probably lose a chunk of every shift just hunting "
            "for the answer to a question they have answered before. We put that "
            "answer right where they are typing, which saves the team hours it can "
            "spend on the tickets that actually need a human. Want a short clip of it "
            "on a live queue?\n\n"
            "Cheers,\nJonah\nDeskweave"
        ),
    },
    {
        "set": "is_02",
        "recipient": {"company": "Vanguard Realty Partners", "industry": "real estate",
                      "detail": "a mid-size brokerage"},
        "difficulty": "multiple",
        "violate": [0, 3],
        "draft": {
            0: (_V, "Corporate, stiff tone throughout.", "high"),
            3: (_V, "Exceeds the 120-word cap.", "high"),
        },
        "body": (
            "Dear Vanguard Realty Partners,\n\n"
            "I am writing to introduce our organization and to explore a potential "
            "partnership opportunity that we believe may deliver significant value to "
            "your enterprise. In today's competitive landscape, client-support "
            "operations represent a critical differentiator, and many firms of your "
            "stature are actively seeking to optimize this function. Our solution "
            "empowers support organizations to leverage their institutional knowledge "
            "base, thereby driving operational efficiencies and elevating the overall "
            "client experience across every touchpoint. We have partnered with "
            "numerous best-in-class organizations to realize these outcomes, and we "
            "are confident that a similar engagement could yield comparable results "
            "for your esteemed team. I would be most grateful for the opportunity to "
            "schedule an introductory call at your earliest convenience.\n\n"
            "Warm regards,\nJonah\nDeskweave"
        ),
    },

    # ----------------------- is_03: 500-char budget, verifiable ref ---------- #
    {
        "set": "is_03",
        "recipient": {"company": "Northwind Freight", "industry": "freight",
                      "detail": "opened a Columbus cross-dock in March"},
        "difficulty": "clean",
        "violate": [],
        "tags": ["specific_checkable"],
        "body": (
            "Hi Northwind Freight,\n\n"
            "Saw you opened the Columbus cross-dock in March. New cross-docks are "
            "where load data goes to get lost between systems. We keep it in sync so "
            "your dispatchers stop rekeying. Worth a quick look?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Northwind Freight", "industry": "freight",
                      "detail": "opened a Columbus cross-dock in March"},
        "difficulty": "borderline",
        "violate": [2],
        "tags": ["namedrop_boilerplate"],
        "draft": {2: (_V, "Names the company but says nothing specific or verifiable.", "low")},
        "body": (
            "Hi Northwind Freight,\n\n"
            "Companies in freight like Northwind Freight all face the same pressures "
            "as they grow: rising complexity, tighter margins, more systems to "
            "juggle. We help you stay ahead of all of it. Worth a quick look?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Cobalt Data", "industry": "data integration",
                      "detail": "shipped a new API gateway"},
        "difficulty": "clean",
        "violate": [],
        "tags": ["specific_checkable"],
        "body": (
            "Hi Cobalt Data,\n\n"
            "Your new API gateway launch got my attention. Gateways multiply the "
            "integrations you have to babysit. We keep those mappings in sync so a "
            "schema change does not page someone at 2am. Worth fifteen minutes?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Brightpath Analytics", "industry": "analytics",
                      "detail": "a mid-size analytics vendor"},
        "difficulty": "single",
        "violate": [0],
        "draft": {0: (_V, "Body exceeds the 500-character budget.", "high")},
        "body": (
            "Hi Brightpath Analytics,\n\n"
            "I wanted to reach out because analytics vendors at your stage almost "
            "always hit the same wall: the number of upstream data sources you have "
            "to integrate grows faster than the team maintaining them, and every "
            "schema change upstream quietly breaks a dashboard downstream that nobody "
            "notices until a customer does. We keep all of those source mappings in "
            "sync automatically, so your engineers stop spending their mornings "
            "chasing silent breakages and can get back to the roadmap work you "
            "actually hired them for. Would it be worth a short call?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Keystone Payments", "industry": "payments",
                      "detail": "a mid-size payments processor"},
        "difficulty": "multiple",
        "violate": [1, 2],
        "draft": {
            1: (_V, "Never names the recipient company.", "high"),
            2: (_V, "No specific or verifiable detail about them.", "high"),
        },
        "body": (
            "Hi there,\n\n"
            "Payments companies all deal with the same integration sprawl as they "
            "scale. We keep your data mappings in sync so nothing breaks silently. "
            "Worth a quick look?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Solstice Media", "industry": "digital media",
                      "detail": "migrated to a new CMS"},
        "difficulty": "single",
        "violate": [3],
        "draft": {3: (_V, "Uses an exclamation mark.", "high")},
        "body": (
            "Hi Solstice Media,\n\n"
            "Congrats on the CMS migration! Migrations scatter content data across "
            "systems that fall out of sync fast. We keep those mappings aligned so "
            "your team stops firefighting. Worth a quick look?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Ironwood Manufacturing", "industry": "manufacturing",
                      "detail": "adopted a new ERP"},
        "difficulty": "single",
        "violate": [4],
        "draft": {4: (_V, "Sign-off is missing the company line.", "high")},
        "body": (
            "Hi Ironwood Manufacturing,\n\n"
            "Saw you adopted a new ERP. ERP rollouts leave a trail of half-synced "
            "integrations behind them. We keep those mappings clean so the rollout "
            "actually sticks. Worth a quick look?\n\n"
            "Best,\nPriya"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Lumen Robotics", "industry": "robotics",
                      "detail": "closed a Series B in April"},
        "difficulty": "clean",
        "violate": [],
        "tags": ["specific_checkable"],
        "body": (
            "Hi Lumen Robotics,\n\n"
            "Congrats on the April Series B. Fresh funding usually means new systems "
            "bolted on fast, and fast means integrations drift. We keep your data "
            "mappings in sync so scaling does not mean breaking. Worth a look?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Fairfield Logistics", "industry": "logistics",
                      "detail": "a mid-size logistics company"},
        "difficulty": "borderline",
        "violate": [2],
        "tags": ["vague_reference"],
        "draft": {2: (_V, "References 'recent growth' but nothing checkable.", "low")},
        "body": (
            "Hi Fairfield Logistics,\n\n"
            "Your recent growth is hard to miss, and growth like that usually strains "
            "the systems holding your shipment data together. We keep those in sync so "
            "nothing slips. Worth a quick look?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },
    {
        "set": "is_03",
        "recipient": {"company": "Cedar Grove Foods", "industry": "food production",
                      "detail": "added a second production line"},
        "difficulty": "multiple",
        "violate": [0, 3],
        "draft": {
            0: (_V, "Well over the 500-character budget.", "high"),
            3: (_V, "Uses exclamation marks.", "high"),
        },
        "body": (
            "Hi Cedar Grove Foods,\n\n"
            "Congrats on the second production line, that is a milestone worth "
            "celebrating! Adding a line is exactly the moment your traceability data "
            "starts living in two places at once, and the two places never quite "
            "agree, which is how a recall turns from a bad afternoon into a bad week "
            "that no one on the floor will forget! We keep every batch and lot mapping "
            "synced across both lines automatically so your quality team is working "
            "from one source of truth instead of reconciling spreadsheets by hand at "
            "the end of every shift! Worth a quick fifteen minutes to see it?\n\n"
            "Best,\nPriya\nSyncrail"
        ),
    },

    # ----------------------- is_04: warm, short, no questions, no pricing ---- #
    {
        "set": "is_04",
        "recipient": {"company": "Sunny Day Camps", "industry": "youth programs",
                      "detail": "runs summer camps across three states"},
        "difficulty": "clean",
        "violate": [],
        "body": (
            "Hi Sunny Day Camps team,\n\n"
            "Running camps across three states means a scheduling headache the rest of "
            "us can only imagine. We take the back-and-forth out of it so your staff "
            "spends time with kids, not calendars. I would love to show you how light "
            "it feels.\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Coastal Dental", "industry": "dental practice",
                      "detail": "opened a second office"},
        "difficulty": "borderline",
        "violate": [0],
        "tags": ["indirect_question_no_qmark"],
        "draft": {0: (_V, "Poses a question in rhetorical form without a question mark.", "low")},
        "body": (
            "Hi Coastal Dental team,\n\n"
            "You might be wondering how a second office is supposed to share a front "
            "desk without the schedule turning into chaos. That is the exact knot we "
            "untie. We keep both calendars in step so nobody double-books a chair. I "
            "would love to show you.\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Riverside Fitness", "industry": "fitness",
                      "detail": "a growing gym chain"},
        "difficulty": "single",
        "violate": [0],
        "draft": {0: (_V, "Asks a direct question.", "high")},
        "body": (
            "Hi Riverside Fitness team,\n\n"
            "Class scheduling across a growing chain is a lot to hold in your head. We "
            "make it feel effortless so your front desk can actually greet people. "
            "Would you have twenty minutes this week for a quick look?\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Hillcrest Veterinary", "industry": "veterinary",
                      "detail": "a busy multi-vet clinic"},
        "difficulty": "borderline",
        "violate": [1],
        "tags": ["corporate_tone_drift"],
        "draft": {1: (_V, "Tone reads stiff and corporate rather than warm.", "low")},
        "body": (
            "Hello Hillcrest Veterinary,\n\n"
            "Per our focus on operational excellence, we provide scheduling "
            "infrastructure designed to optimize appointment throughput for "
            "multi-provider clinics. Our platform facilitates resource allocation and "
            "reduces administrative overhead across your practice. We would value the "
            "opportunity to demonstrate the solution.\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Maplewood Academy", "industry": "private education",
                      "detail": "a K-8 private school"},
        "difficulty": "single",
        "violate": [2],
        "draft": {2: (_V, "Runs past the 75-word cap.", "high")},
        "body": (
            "Hi Maplewood Academy team,\n\n"
            "Coordinating parent-teacher conferences by hand is the kind of task that "
            "quietly eats a whole week of somebody's time every single term, and it "
            "never gets easier no matter how many times you have done it before. We "
            "take that entire scramble off your plate so your staff can focus on the "
            "students in front of them instead of a spreadsheet full of time slots "
            "that keeps changing every hour. I would genuinely love to show you how "
            "simple we can make the whole thing feel.\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Gables Realty", "industry": "real estate",
                      "detail": "a boutique brokerage"},
        "difficulty": "single",
        "violate": [3],
        "draft": {3: (_V, "Mentions a discount.", "high")},
        "body": (
            "Hi Gables Realty team,\n\n"
            "Juggling showings across a busy weekend is a scheduling puzzle we love to "
            "solve. We keep every agent's calendar in step so nobody double-books a "
            "listing. And there is a nice discount for boutique teams like yours right "
            "now. I would love to show you.\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Northshore Spa", "industry": "wellness",
                      "detail": "a day spa and wellness center"},
        "difficulty": "single",
        "violate": [4],
        "draft": {4: (_V, "Sign-off omits the company name on its own line.", "high")},
        "body": (
            "Hi Northshore Spa team,\n\n"
            "A day spa lives and dies by the calendar, and a single mixed-up booking "
            "can throw a whole afternoon. We keep it all flowing so your guests feel "
            "looked after from the first minute. I would love to show you.\n\n"
            "Warmly, Eli"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Trailhead Outfitters", "industry": "outdoor retail",
                      "detail": "runs guided trips"},
        "difficulty": "clean",
        "violate": [],
        "body": (
            "Hi Trailhead Outfitters team,\n\n"
            "Booking guided trips around weather and guide availability is a real "
            "juggle. We make the whole dance feel easy so your crew can focus on the "
            "trail, not the calendar. I would love to walk you through it whenever "
            "suits.\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Beacon Legal", "industry": "legal services",
                      "detail": "a mid-size law firm"},
        "difficulty": "multiple",
        "violate": [0, 1, 2],
        "draft": {
            0: (_V, "Asks a direct question.", "high"),
            1: (_V, "Stiff, corporate tone.", "high"),
            2: (_V, "Exceeds the 75-word cap.", "high"),
        },
        "body": (
            "Dear Beacon Legal,\n\n"
            "We wish to formally introduce our scheduling solution, which has been "
            "architected to optimize calendar coordination for professional services "
            "firms of your caliber and to reduce the administrative burden associated "
            "with multi-attorney availability management across your practice groups. "
            "Would your firm be amenable to scheduling a formal introductory "
            "consultation at a mutually agreeable time in the coming weeks to review "
            "the capabilities of the platform in appropriate detail?\n\n"
            "Regards,\nEli\nBrightslot"
        ),
    },
    {
        "set": "is_04",
        "recipient": {"company": "Willow Creek Clinic", "industry": "healthcare",
                      "detail": "a family medicine clinic"},
        "difficulty": "borderline",
        "violate": [],
        "tags": ["borderline_tone_ok"],
        "draft": {1: (_V, "One phrase reads slightly formal, though overall warm.", "low")},
        "body": (
            "Hi Willow Creek Clinic team,\n\n"
            "A family clinic runs on a calendar that never sits still, and one "
            "mix-up ripples through a whole morning. We keep the schedule steady and, "
            "respectfully, out of your way, so your team can stay with patients. I "
            "would love to show you how easy it feels.\n\n"
            "Warmly,\nEli\nBrightslot"
        ),
    },

    # ----------------------- is_05: polished, no marks or questions ---------- #
    {
        "set": "is_05",
        "recipient": {"company": "Portside Logistics", "industry": "logistics",
                      "detail": "manages a regional port terminal"},
        "difficulty": "clean",
        "violate": [],
        "body": (
            "Hello Portside Logistics team,\n\n"
            "Running a regional port terminal means your shipment data moves faster "
            "than the tools tracking it. We give your operation a single, current view "
            "of every container so your dispatchers stop reconciling by hand. I would "
            "welcome the chance to show Portside Logistics a short walkthrough on a "
            "real day of throughput.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Granite Freight", "industry": "freight",
                      "detail": "a regional carrier"},
        "difficulty": "borderline",
        "violate": [4],
        "tags": ["implied_pricing_no_banned_word"],
        "draft": {4: (_V, "Implies pricing benefit with 'pays for itself'.", "low")},
        "body": (
            "Hello Granite Freight team,\n\n"
            "As a regional carrier scales, the analytics stack usually sprawls faster "
            "than anyone planned. We give Granite Freight one clean view of "
            "throughput, and for most carriers the platform pays for itself well "
            "before renewal because the reclaimed dispatcher hours add up quickly. I "
            "would welcome the chance to walk you through it.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Summit Distribution", "industry": "wholesale distribution",
                      "detail": "a national distributor"},
        "difficulty": "single",
        "violate": [0],
        "draft": {0: (_V, "Uses an exclamation mark.", "high")},
        "body": (
            "Hello Summit Distribution team,\n\n"
            "Operating at national scale means your throughput data lives in a dozen "
            "places at once! We consolidate it into one current view so Summit "
            "Distribution can act on today's numbers, not last week's. I would welcome "
            "the chance to walk you through a short version.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Beacon Freightways", "industry": "freight",
                      "detail": "an interstate carrier"},
        "difficulty": "single",
        "violate": [1],
        "draft": {1: (_V, "Opens with a direct question.", "high")},
        "body": (
            "Hello Beacon Freightways team,\n\n"
            "How much time does your dispatch team lose reconciling numbers across "
            "systems every week. For most interstate carriers it is more than they "
            "expect. We give Beacon Freightways one current view of throughput so that "
            "work disappears. I would welcome the chance to show you.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Cardinal Supply", "industry": "industrial supply",
                      "detail": "a regional supplier"},
        "difficulty": "single",
        "violate": [2],
        "draft": {2: (_V, "Exceeds the 100-word cap.", "high")},
        "body": (
            "Hello Cardinal Supply team,\n\n"
            "As a regional supplier grows, the reporting stack tends to grow with it, "
            "but not in any planned way, and before long your operations team is "
            "pulling numbers from four systems that never quite agree, then spending "
            "the first hour of every morning deciding which version to believe before "
            "anyone can make a single real decision about the day ahead. We consolidate "
            "all of it into one current, trustworthy view of throughput for Cardinal "
            "Supply, so that reconciliation work simply goes away and your team starts "
            "the day already aligned. I would genuinely welcome the chance to walk you "
            "through exactly how it comes together.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Delta Warehousing", "industry": "warehousing",
                      "detail": "a mid-size 3PL"},
        "difficulty": "single",
        "violate": [3],
        "draft": {3: (_V, "Never names the recipient company.", "high")},
        "body": (
            "Hello there,\n\n"
            "Warehousing operations at your scale generate more throughput data than "
            "any one dashboard can hold. We consolidate it into a single current view "
            "so your team stops reconciling by hand. I would welcome the chance to "
            "walk you through a short version.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Monarch Transport", "industry": "transport",
                      "detail": "a regional trucking company"},
        "difficulty": "single",
        "violate": [5],
        "draft": {5: (_V, "Sign-off omits the company line.", "high")},
        "body": (
            "Hello Monarch Transport team,\n\n"
            "Regional trucking runs on numbers that change by the hour, and stale "
            "reports cost you real decisions. We give Monarch Transport one current "
            "view of throughput so your team acts on today. I would welcome the chance "
            "to show you.\n\n"
            "Best regards, Tomas"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Evergreen Freight", "industry": "freight",
                      "detail": "a mid-size carrier"},
        "difficulty": "multiple",
        "violate": [0, 4],
        "draft": {
            0: (_V, "Uses exclamation marks.", "high"),
            4: (_V, "Implies pricing with 'saves you money'.", "high"),
        },
        "body": (
            "Hello Evergreen Freight team,\n\n"
            "Your throughput data is scattered across too many tools right now! We "
            "pull it into one current view for Evergreen Freight, and it saves you "
            "money almost immediately by cutting the hours your team burns "
            "reconciling! I would welcome the chance to show you.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Anchor Shipping", "industry": "maritime shipping",
                      "detail": "runs a coastal fleet"},
        "difficulty": "clean",
        "violate": [],
        "body": (
            "Hello Anchor Shipping team,\n\n"
            "Coordinating a coastal fleet means throughput numbers that shift with "
            "every tide and port call. We give Anchor Shipping one current view of it "
            "all so your team plans against reality instead of yesterday's snapshot. I "
            "would welcome the chance to walk you through a short version.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
    {
        "set": "is_05",
        "recipient": {"company": "Highland Distribution", "industry": "distribution",
                      "detail": "a regional distributor"},
        "difficulty": "borderline",
        "violate": [4],
        "tags": ["implied_pricing_soft"],
        "draft": {4: (_V, "Softly implies pricing with 'won't stretch your budget'.", "low")},
        "body": (
            "Hello Highland Distribution team,\n\n"
            "As a regional distributor grows, the reporting stack grows with it, "
            "usually into a tangle. We consolidate throughput into one current view "
            "for Highland Distribution, and it will not stretch your budget the way "
            "another heavy platform would. I would welcome the chance to show you.\n\n"
            "Best regards,\nTomas\nCleartrack"
        ),
    },
]
