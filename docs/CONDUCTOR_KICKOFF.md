# Conductor kickoff: Instruction Adherence Grader

**Paste this whole file as the opening instruction of the FIRST Conductor session. That session runs Phase 0 only.**
Phases 1–4 run in four parallel Conductor workspaces afterwards, using the prompts in `docs/AGENT_LANES.md`.

You are the foundation agent. Your job is not to build the grader. Your job is to build the
scaffolding, the frozen interfaces, and the shared spine that four sibling agents will build
against in parallel worktrees without ever touching each other's files. Do that job narrowly and
well, then stop.

---

## 1. What the finished project is

An **instruction adherence grader**. It answers one question, repeatedly: did an AI-written email
actually obey the rules a customer set for it?

The pipeline:

```
customer's rules (plain English)
        +                          ->   COMPILE   ->   checkable rules
   the written email                                        |
                                                          CHECK
                                                             |
                                                  pass / fail per rule
                                                             |
                                          one repair attempt if it failed
                                                             |
                                            adherence rate over a batch
```

The README ends up leading with two numbers:

1. **Adherence rate** over a batch of 50 emails, counting a successful single repair as a pass.
2. **Precision / recall / F1 of the grader itself** against a hand-labeled ground truth set,
   reported separately for deterministic and semantic rules.

The second number is the one that separates this from a weekend toy. Anyone can write "check if
this email follows the rules." Almost nobody measures whether their checker is right.

**Target problem space (one sentence, and the only framing allowed anywhere in the repo):**
AI-personalized outbound email tools need to verify that their own output follows customer-set
constraints. No real product, customer, or company is named, touched, scraped, or integrated with.
All fixtures are synthetic. No individual is named anywhere in the repo.

## 2. Repo layout

A top-level `agent-harness` repo. This grader is the worked example inside it, not the whole repo.

```
agent-harness/
  README.md                          top-level: what this repo is, one line per example
  docs/
    ROADMAP.md                       phases, dependency graph, definition of done
    CONTRACTS.md                     FROZEN interfaces. Read before writing any code.
    AGENT_LANES.md                   per-worktree lane assignments and ownership matrix
    CONDUCTOR_LOG.md                 the multi-session build record (showcase artifact)
    contract-changes/                one file per lane, append-only, never shared
  scripts/
    session_report.py                turns git metadata into the parallel-build evidence table
  examples/
    instruction-adherence-grader/
      README.md                      leads with adherence rate + grader precision/recall
      pyproject.toml
      .env.example                   ANTHROPIC_API_KEY, MODEL_NAME, MODEL_PROVIDER, ...
      Makefile
      src/
        config.py        Config object, env-driven, no hardcoded model IDs in logic
        model_client.py  single chokepoint for every model call: cache, retry, concurrency, fake provider
        schemas.py       Rule, RuleResult, and the JSON file schemas
        compile.py       instruction text -> Rule objects
        rules.py         deterministic check registry
        semantic_check.py one model call per semantic rule, structured output
        checker.py       check_email(email, rules) -> list[RuleResult]
        writer.py        generates an email (compliant mode / deliberately-violating mode)
        repair.py        exactly one repair attempt given violations
        grader.py        batch orchestration: compile -> check -> repair -> hold
        fixtures.py      generates the 50-email fixture set with planted violations
        labeler.py       blind first-pass labeling agent, prompt separate from the checker
        review_tool.py   emits the human review sheet, ingests the corrected version
        score.py         adherence rate + grader precision/recall/F1
        cli.py           single entrypoint
      fixtures/
        instruction_sets.json         the 5 instruction sets
        emails.json                   50 emails + planted_violations (generation metadata)
        labels_model_draft.json       labeler.py output, blind, pre-review
        labels_ground_truth.json      after human review. This is what score.py measures against.
      runs/                           grader run outputs (gitignored except the final committed run)
      tests/
        test_compile.py               (Lane A)
        test_deterministic_rules.py   (Lane A)
        test_semantic_check.py        (Lane B)
        test_repair_hold.py           (Lane B)
        test_fixtures.py              (Lane C)
        test_labeler.py               (Lane C)
        test_score.py                 (Lane D)
        test_grader_end_to_end.py     (Integration)
        data/                         (Lane D: synthetic run/label files for scorer tests)
```

Keep the whole example inside `examples/instruction-adherence-grader/`. Do not let it sprawl into
the top-level repo.

## 3. The three-file separation that keeps this honest

The single easiest way to make this exercise circular is to collapse these. Keep them as three
distinct files with three distinct meanings:

| File | Meaning | Who writes it |
| --- | --- | --- |
| `emails.json` -> `planted_violations` | generation-time bookkeeping: which rules the writer was *told* to break | `fixtures.py` |
| `labels_model_draft.json` | a blind first-pass model read of the finished email, no knowledge of what was planted | `labeler.py` |
| `labels_ground_truth.json` | the human-reviewed, corrected labels | a person, via `review_tool.py` |

`planted_violations` is raw material, not truth: a planted violation may not actually manifest in
the finished text, and an email may accidentally break a rule nobody planted. Only the third file
is ground truth, and only the third file is what `score.py` compares the checker against.

`labeler.py` must use a **prompt distinct from the checker's semantic-check prompts** and must not
call into `semantic_check.py`. Its job is to approximate "a careful reader seeing this cold," not
"the grader grading itself." A first pass that shares the grader's prompt measures only whether the
grader agrees with itself.

## 4. What you build in Phase 0 (and nothing else)

Everything below is a shared dependency of two or more downstream lanes. That is the only reason
it is here. If it is used by exactly one lane, it is not yours: leave a stub.

### 4.1 Project scaffold
- `pyproject.toml` (or `requirements.txt`) with **every** dependency the whole project will need,
  declared now: `anthropic`, `pydantic`, `pytest`, `python-dotenv`, `rich` (optional, for the CLI),
  `jinja2` (optional, for the review sheet). Downstream lanes are forbidden from editing this file,
  so anything missing here becomes a merge conflict later. Be generous.
- `.env.example` with `ANTHROPIC_API_KEY`, `MODEL_NAME`, `WRITER_MODEL_NAME`, `MODEL_PROVIDER`,
  `MODEL_CACHE_DIR`, `MODEL_MAX_CONCURRENCY`.
- `.gitignore`: `.env`, `__pycache__`, `.model_cache/`, `runs/*.json` except a committed final run.
- A `Makefile` with **all** targets pre-declared, even ones whose implementation lands later, so no
  lane has to edit it: `install`, `test`, `lint`, `fixtures`, `label`, `review`, `grade`, `score`,
  `demo`, `report`. Targets whose code does not exist yet should print a clear "not implemented yet
  (lane X)" message and exit 0.

### 4.2 `config.py`
Env-driven `Config`. **Do not hardcode a model ID anywhere in application logic.** Model names
drift. Read `MODEL_NAME` from the environment with a documented default resolved at build time:
before you pick the default, verify the identifier against the Anthropic API (list the models
endpoint, or check the current docs). Do not invent one from memory. Use a mid-tier Claude model as
the checker/labeler default and allow `WRITER_MODEL_NAME` to differ. Record the resolved default in
`.env.example` with a comment saying where it came from and when.

### 4.3 `model_client.py` (the most important file you write)
Every model call in this project goes through this one module. Four agents will be hammering one
API key in parallel and the whole thing will be re-run many times, so this module carries:

- **Structured output.** Expose a `call_json(prompt, schema, *, model=None, system=None)` that uses
  tool-forced / structured output rather than parsing free text. Free-text JSON parsing is banned
  project-wide.
- **A content-addressed disk cache.** Key on `sha256(model + system + prompt + schema + params)`,
  store under `MODEL_CACHE_DIR` (default `.model_cache/`). `temperature=0`. A cache hit costs
  nothing and returns instantly. This is what makes re-running the batch free and makes results
  reproducible across the four worktrees. Support `--no-cache` / `use_cache=False`.
- **Retry with exponential backoff and jitter** on 429 / 529 / connection errors, and a
  `MODEL_MAX_CONCURRENCY` semaphore (default 4). Four parallel agents on one key will hit limits.
- **A `fake` provider.** `MODEL_PROVIDER=fake` returns deterministic canned responses driven by a
  small fixture map, so unit tests and CI run with no API key. Every lane's tests must pass under
  the fake provider. This is not optional; it is how four agents test in parallel without a key
  each.
- **A debug log.** Every semantic call's raw request and response appended to a JSONL file, so a
  verdict is auditable later rather than a boolean you have to trust.

### 4.4 `schemas.py`
Implement exactly what `docs/CONTRACTS.md` specifies: `Rule`, `RuleResult`, and loader/validator
helpers for each JSON file format. Nobody downstream redefines these. If a lane needs a field that
does not exist, it works around it and logs the request (see 4.7).

### 4.5 `writer.py` (real, not a stub)
This is a shared dependency of Lane B (repair) and Lane C (fixtures), so it lands in Phase 0. Two
clearly separate functions:

- `write_compliant_email(instruction_set, recipient_context) -> str`
- `write_violating_email(instruction_set, recipient_context, violate_rule_ids) -> str`

Keep them separate so nobody later accidentally wires the deliberately-violating mode into the
production repair path. Add a module docstring saying exactly that.

### 4.6 `fixtures/instruction_sets.json` (real, not a stub)
Author all 5 instruction sets now. They are the spine every lane builds against: Lane A compiles
them, Lane B judges against them, Lane C generates from them. Between them the 5 sets must exercise
at least:

- a word or character limit, including one tight enough that repair has to work at it (target 90),
- a banned word or phrase family (pricing language),
- a required element (a signature block; a specific reference to the recipient's company),
- a punctuation constraint (no question marks in a first email; no exclamation marks),
- at least two distinct semantic judgments: **specificity** (is the company reference actually
  specific to that company, or generic filler that would fit any company in that industry) and
  **tone** (asked for casual, drifts corporate), plus **implied content** (implies pricing without
  using a banned word: "cost-effective," "pays for itself," "ROI in weeks").

Recipients are generic placeholders only: "Acme Robotics," "a mid-size logistics company." No real
companies, no real people, no real email addresses.

### 4.7 Stubs and the contract-change protocol
Create every remaining `src/*.py` file as a stub with the exact signature from `CONTRACTS.md`, a
docstring, and `raise NotImplementedError("lane X")`. This means every lane starts from a repo that
imports cleanly.

Create `docs/contract-changes/` with a `README.md` explaining the protocol: if a lane believes a
contract is wrong, it does **not** edit `CONTRACTS.md` (four agents editing one spec file is a
guaranteed conflict). It writes the proposed change to `docs/contract-changes/<lane-id>.md`, its
own file, and continues building against the contract as written. The integration phase reconciles
them.

### 4.8 Docs and the showcase scaffold
`docs/` is already committed on `main` and is present in your worktree: `ROADMAP.md`,
`CONTRACTS.md`, `AGENT_LANES.md`, `CONDUCTOR_LOG.md`, this file, and `contract-changes/`. Read them;
do not rewrite them. Stub
`scripts/session_report.py` with its argument parsing and the marker-rewriting logic only; Lane E
implements it against the spec in `CONDUCTOR_LOG.md`. Write a placeholder top-level `README.md`
(Lane E owns the real one) so the repo is not headless on the first commit. Do not write the example
`README.md`; that is Lane D's, and it will be created from scratch there.

### 4.9 Commit convention
Every commit in this project, in every worktree, ends with a lane trailer:

```
Conductor-Lane: phase-0-foundation
```

`scripts/session_report.py` reads these to reconstruct which parallel session produced what. This
is what makes the multi-session build visible in the repo rather than merely claimed.

## 5. Done criteria for Phase 0

Stop when all of these hold. Do not start Lane A work.

- [ ] `make install && make test` passes on a clean checkout with **no API key set**
      (`MODEL_PROVIDER=fake`).
- [ ] `python -c "import src.compile, src.rules, src.semantic_check, src.checker, src.repair, src.grader, src.fixtures, src.labeler, src.review_tool, src.score, src.cli"` succeeds: every stub imports.
- [ ] `writer.py` really writes an email against a real API call, and its two modes are separate
      functions.
- [ ] `fixtures/instruction_sets.json` has 5 sets covering every rule category in 4.6, and validates
      against the schema in `CONTRACTS.md`.
- [ ] `model_client.py` demonstrably caches: the same call twice makes one network request. Prove it
      in a test.
- [ ] Every `Makefile` target exists and exits 0.
- [ ] `docs/` contains all five documents and `docs/contract-changes/README.md`.
- [ ] Committed and merged to `main` with the `Conductor-Lane: phase-0-foundation` trailer.

Then post a one-paragraph handoff: the resolved default model ID, anything in `CONTRACTS.md` you
had to interpret, and confirmation that the four lanes are unblocked.

## 6. Hard boundaries (apply to every phase, every agent)

- Do not touch, scrape, call, or integrate with any real product or company's systems.
- No real customer data, real email addresses, or real company names anywhere. Generic placeholders
  only.
- Do not name any individual anywhere in the repo.
- Do not frame the project as a confirmed engagement with any specific company. The one-sentence
  problem-space framing in section 1 is the only framing allowed.
- Never parse free-text JSON out of a model response. Structured output or nothing.
- Never bundle multiple semantic rules into one model call. You lose the ability to attribute a
  specific failure to a specific rule, which is the entire product.
- One repair attempt. Never two. An email that fails after repair is **held**, reported with its
  still-failing rules, and neither silently dropped nor silently sent.
- If a phase runs long, ship a smaller but fully hand-labeled fixture set rather than a larger one
  that skips manual labeling. An unlabeled fixture set produces no second number, and the second
  number is the project.
- If any definition-of-done item cannot be met in the time box, say so explicitly in the README's
  limitations section rather than quietly shipping the gap.
