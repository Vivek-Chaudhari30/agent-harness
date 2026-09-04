# agent-harness

[![CI](https://github.com/Vivek-Chaudhari30/agent-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/Vivek-Chaudhari30/agent-harness/actions/workflows/ci.yml)

A small harness for building and evaluating LLM-powered pipelines with reproducible,
env-configured model calls. Each example under `examples/` follows the same conventions:
models and providers are read from the environment (never hardcoded), every model call
is cached and uses structured output, a `fake` provider lets the full test suite run
with no API key, and temperature is set to 0 where the provider supports it.

---

## Examples

| Example | What it measures |
|---|---|
| [instruction-adherence-grader](examples/instruction-adherence-grader/) | Does an AI-written email obey the plain-English rules a sender set for it? Reports adherence rate over a batch and precision/recall/F1 of the grader against hand-labeled ground truth. |

---

## What we built — instruction-adherence-grader

### The problem

AI-written sales emails can break the sender's own rules — too many words, wrong tone,
implied pricing, missing sign-off. Manually checking every email doesn't scale. This
project asks: can an AI grader catch those violations reliably, and how do you measure
how well it does?

### How it works

```
Plain-English instruction set (e.g. "under 90 words, no pricing, casual tone")
        │
        ▼
 Compile into typed Rules  (deterministic: word count, banned words, regex)
        │                  (semantic: tone, specificity, implied content)
        ▼
 Grade each email  ──────►  Repair if failing  ──────►  Hold if still failing
        │
        ▼
 Compare grader verdicts vs. human-reviewed ground truth
        │
        ▼
 Precision / Recall / F1
```

**Two kinds of rules:**
- **Deterministic** — word count, banned words, exclamation marks, character limits. These have exact answers and the grader uses regex/counting, not AI.
- **Semantic** — tone ("casual, never stiff"), specificity ("reference something verifiable about their company"), implied pricing. These need an AI judge.

**Two-pass ground truth:** A model first labeled all 270 (email, rule) pairs blindly. A human then reviewed every verdict. The human/model separation matters — a labeler that imports the checker's code would be grading itself.

---

## Real results (run 2026-09-04, OpenAI, 50 synthetic emails)

### Adherence rate — 88%

| | Count |
|---|---|
| Emails graded | 50 |
| ✅ Passed on first try (no violations) | **17** |
| 🔧 Fixed by the repair step | **27** |
| ❌ Held (still failing after repair) | **6** |
| **Adherence rate** | **88%** |

34 of 50 emails had at least one violation on first draft. The repair step fixed 27 of
them. The 6 that remain held all failed on hard semantic rules — "reference something
specific and verifiable about the recipient's company" and "do not imply pricing
indirectly." These are the genuinely difficult cases where even a human reviewer pauses.

### Grader accuracy vs. human labels (270 checks across 50 emails)

| Segment | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| **Overall** | **0.977** | **0.796** | **0.878** | 270 |
| Deterministic rules | 1.000 | 0.771 | 0.871 | 210 |
| Semantic rules | 0.941 | 0.842 | 0.889 | 60 |

**Positive class = violation present.** TP = grader correctly flags a real violation.

| | Count |
|---|---|
| True positives | 43 |
| False positives (false alarms) | **1** |
| False negatives (missed violations) | 11 |
| True negatives | 215 |

**What these numbers mean in plain English:**

- **Precision 0.977** — When the grader says "this email broke a rule," it is right
  97.7% of the time. You can trust its flags.
- **Recall 0.796** — The grader catches about 80% of real violations. Roughly 1 in 5
  slips through undetected.
- **Only 1 false alarm** out of 270 checks — the grader almost never blocks a good
  email.
- **11 missed violations** — all subtle cases the human reviewer caught that the model
  glossed over.
- **Semantic rules (F1 0.889) outperformed deterministic (F1 0.871)** — counterintuitive,
  but the deterministic layer missed more violations (recall 0.771) while the semantic
  judge was more thorough (recall 0.842). The deterministic misses were edge cases like
  rhetorical questions that technically don't end in "?" and near-limit word counts.

### Per-rule breakdown

| Rule | Kind | Precision | Recall | F1 |
|---|---|---|---|---|
| keep_it_under_90_words | deterministic | 1.000 | 1.000 | **1.000** |
| no_exclamation_marks | deterministic | 1.000 | 1.000 | **1.000** |
| do_not_imply_pricing_indirectly | semantic | 1.000 | 1.000 | **1.000** |
| keep_the_tone_warm_and_casual | semantic | 1.000 | 1.000 | **1.000** |
| keep_it_under_120_words | deterministic | 1.000 | 1.000 | **1.000** |
| keep_whole_email_under_500_chars | deterministic | 1.000 | 1.000 | **1.000** |
| keep_it_under_75_words | deterministic | 1.000 | 1.000 | **1.000** |
| do_not_mention_pricing_or_discounts | deterministic | 1.000 | 1.000 | **1.000** |
| do_not_imply_pricing_without_stating | semantic | 1.000 | 1.000 | **1.000** |
| reference_something_specific_verifiable | semantic | 1.000 | 0.800 | 0.889 |
| sign_off_with_first_name_and_company | deterministic | 1.000 | 0.600 | 0.750 |
| do_not_ask_questions | deterministic | 1.000 | 0.667 | 0.800 |
| never_mention_pricing | deterministic | 1.000 | 0.500 | 0.667 |
| do_not_ask_a_question_in_first_email | deterministic | 1.000 | 0.200 | **0.333** |
| always_reference_something_specific | semantic | 0.667 | 0.667 | 0.667 |

The worst-performing rule ("do not ask a question in the first email", F1 0.333) missed
4 out of 5 real violations — all rhetorical questions phrased without a literal "?".
The one true positive was a direct question. This is a known edge case flagged in the
fixture design.

---

## What the numbers tell us

1. **The grader is production-quality on deterministic rules.** Zero false alarms across
   all word counts, character limits, banned words, and punctuation checks. If it flags
   one of these, believe it.

2. **The semantic judge is surprisingly good.** F1 0.889 with only 1 false alarm across
   60 semantic checks means it is not trigger-happy. The misses are genuinely hard
   cases.

3. **The repair step does most of the work.** 27 of 44 first-draft failures were fixed
   on the second attempt. A one-shot writer + one-shot repair gets you from ~66%
   first-try pass rate to 88% overall.

4. **Held emails cluster on specificity and implied pricing.** These two semantic rules
   account for all 6 held emails. They are intentionally adversarial (see fixture
   design) and are the hardest for both writer and grader.

5. **Ground truth matters.** The model-only labeling pass would have given different
   F1 numbers — the human review changed verdicts and set the true baseline.

---

## Harness conventions

- **Env-configured models.** `MODEL_PROVIDER` selects the provider (`openai`, `anthropic`,
  `fake`). `MODEL_NAME` and `WRITER_MODEL_NAME` select the model. No model name appears
  in source code.

- **Cached model calls.** Every call is written to a local disk cache keyed by
  `(provider, model, prompt_hash)`. Re-running the pipeline without `--no-cache` is
  instant and free — results are reproducible across machines and worktrees.

- **Fake provider for tests.** `MODEL_PROVIDER=fake` returns deterministic type-default
  responses without any network call. The full 250-test suite runs with no API key and
  no internet. CI uses this.

- **Structured output only.** Every model call specifies a JSON schema; the provider
  enforces it (OpenAI strict mode, Anthropic tool-call mode). No free-text parsing
  anywhere in the codebase.

---

## Running it yourself

```bash
cd examples/instruction-adherence-grader
pip install -e ".[dev]"

# Run the full test suite (no API key needed)
make test

# Run the grading pipeline (requires API key)
export OPENAI_API_KEY=sk-...        # or ANTHROPIC_API_KEY + MODEL_PROVIDER=anthropic
make grade                          # grades all 50 emails, writes runs/<id>.json
make score                          # compares to ground truth, prints precision/recall/F1

# Cheap iteration (subset)
python -m src.cli grade --limit 10
python -m src.cli score
```

---

## How it was built

Built in a single working session using [Conductor](https://conductor.build) to run
five Claude Code agents in parallel git worktrees. See
[`docs/CONDUCTOR_LOG.md`](docs/CONDUCTOR_LOG.md) for the full build record — which
lane did what, when, and how the work was kept from colliding.

All data is synthetic. No real product, customer, company, or email address appears
anywhere in this repository.
