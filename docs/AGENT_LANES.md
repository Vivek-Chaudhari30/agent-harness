# AGENT_LANES.md: parallel worktree assignments

Phase 0 is done and merged to `main`. Open **four Conductor workspaces** and paste one lane block
into each. They run at the same time, in separate worktrees, and do not block each other.

Two later blocks (Integration, Lane E, Audit) are here too; start them when their row in
`docs/ROADMAP.md` comes up.

---

## Running this in Conductor

Conductor gives each session its own git worktree under
`~/conductor/workspaces/agent-harness/<name>`. All of them share one clone, so anything merged to
`main` appears in every workspace created afterwards. That is why `docs/` is committed: no lane
needs to be handed this file, it is already sitting in the worktree.

**The order matters more than anything else here.** Do not create the lane workspaces until Phase 0
is merged, or they will branch from a `main` with no scaffold in it.

1. **Phase 0.** One workspace. Paste:
   > Read `docs/CONDUCTOR_KICKOFF.md` and follow it exactly. Build Phase 0 only, then stop and give
   > me the handoff paragraph it asks for.

   When it finishes, merge that workspace to `main`.

2. **The four lanes.** Create four workspaces, named `lane-a-compiler`, `lane-b-judge`,
   `lane-c-fixtures`, `lane-d-scoring`. In each one paste three lines, changing only the lane name:
   > Read `docs/CONTRACTS.md`, `docs/ROADMAP.md`, and `docs/AGENT_LANES.md`.
   > You are **Lane A**. Follow your lane block in `AGENT_LANES.md` exactly.
   > Do not edit any file you do not own in the ownership matrix. Every commit gets the
   > `Conductor-Lane:` trailer.

   Start all four, then leave them alone. They do not need each other.

3. **Integration.** When all four are done, merge them to `main` in the order A, B, C, D, then run
   the Integration block in one workspace off updated `main`.

4. **The human gate.** Integration hands you the review sheet. Start Lane E in its own workspace so
   an agent is working while you label.

5. **Close.** Phase 7, then the audit.

Four Claude Code sessions running at once consume roughly four times the quota of one, and Phase 0's
model cache only covers the project's own API calls, not the agents themselves. If you are rate
limited, run A and B first, then C and D: the ownership matrix means the split costs correctness
nothing, only wall clock.

---

## File ownership matrix

Exclusive write access. **Editing a file you do not own is the one unrecoverable mistake in this
build**, because it turns a clean parallel merge into an hour of conflict resolution and undoes the
reason for running four sessions at all.

| File | Owner | Everyone else |
| --- | --- | --- |
| `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore` | Phase 0 | read-only |
| `src/config.py`, `src/model_client.py`, `src/schemas.py`, `src/writer.py` | Phase 0 | read-only |
| `fixtures/instruction_sets.json` | Phase 0 | read-only |
| `docs/CONTRACTS.md`, `docs/ROADMAP.md`, `docs/AGENT_LANES.md` | Phase 0 / Integration | read-only |
| `src/compile.py`, `src/rules.py` | **Lane A** | read-only |
| `tests/test_compile.py`, `tests/test_deterministic_rules.py` | **Lane A** | read-only |
| `src/semantic_check.py`, `src/checker.py`, `src/repair.py` | **Lane B** | read-only |
| `tests/test_semantic_check.py`, `tests/test_repair_hold.py` | **Lane B** | read-only |
| `src/fixtures.py`, `src/labeler.py`, `src/review_tool.py` | **Lane C** | read-only |
| `fixtures/emails.json`, `fixtures/labels_*.json` | **Lane C** | read-only |
| `tests/test_fixtures.py`, `tests/test_labeler.py` | **Lane C** | read-only |
| `src/score.py`, `src/cli.py` | **Lane D** | read-only |
| `examples/.../README.md` | **Lane D**, then Phase 7 | read-only |
| `tests/test_score.py` | **Lane D** | read-only |
| `src/grader.py`, `tests/test_grader_end_to_end.py` | **Integration** | read-only |
| top-level `README.md`, `.github/`, `docs/CONDUCTOR_LOG.md` | **Lane E** | read-only |
| `docs/contract-changes/<lane-id>.md` | that lane only | do not read or edit others' |

**Contract-change protocol.** If a frozen interface looks wrong, do not edit `CONTRACTS.md` and do
not "just fix it" in a shared file. Write the proposal, with the reason and your workaround, to
`docs/contract-changes/<your-lane-id>.md`, and keep building against the contract as written.
Integration reconciles all of them at once.

**Every commit** ends with a trailer: `Conductor-Lane: <your-lane-id>`. The session report is
generated from these, so a missing trailer means your work is invisible in the build record.

**Every lane's tests must pass with no API key set**, under `MODEL_PROVIDER=fake`. If your tests
need a live key, your lane is not done.

---

## Lane A: rule compiler and deterministic checks

> **Lane id: `lane-a-compiler`. Create a Conductor workspace named `lane-a-compiler`; whatever branch Conductor gives it is fine, the commit trailer is what identifies your work.**
>
> Read `docs/CONTRACTS.md` and `docs/ROADMAP.md` (Phase 1) first. You own exactly:
> `src/compile.py`, `src/rules.py`, `tests/test_compile.py`, `tests/test_deterministic_rules.py`.
> Everything else in the repo is read-only for you.
>
> Build `compile_instructions(instruction_set) -> list[Rule]`, turning the plain-English
> instructions in `fixtures/instruction_sets.json` into `Rule` objects classified as deterministic
> or semantic. A pattern-matching layer over recognized instruction shapes is the right scope here;
> do not attempt general natural-language-to-code compilation.
>
> Rule ids must be derived from instruction content, never from list position, so that reordering an
> instruction set does not silently invalidate every label downstream.
>
> Deterministic: implement a `CHECKS` registry mapping `check_id` to pure
> `fn(text, params) -> (passed, reason)` callables. No network, no I/O, no clock, no randomness.
> Cover at minimum: word/character limit, banned word or phrase family, required element (signature
> block, and a "references the company by name" structural check), punctuation constraints (question
> marks, exclamation marks). Reasons are one line and specific: "97 words, 7 over the 90-word cap,"
> not "too long."
>
> Semantic: your output is a compiled **judge prompt**, not the raw instruction restated. It states
> the rule, gives what counts as a violation and what explicitly does not, warns against the obvious
> failure mode, and asks for one boolean plus a one-line reason. Record `judge_prompt_sha`. Cover at
> least two distinct types among specificity, tone, and implied content. Lane B will call these
> prompts; you do not make any model calls yourself.
>
> Watch the boundary cases in your deterministic checks, because the fixture set is built to attack
> them: what counts as a word when the text contains hyphenates, contractions, URLs, and a signature
> block; whether the signature counts toward a word limit (pick one, document it in the rule
> description, and be consistent); banned-word matching that catches "pricing" and "priced" without
> firing on "surprisingly."
>
> Done when: every instruction in all 5 sets compiles to a rule with no unrecognized leftovers; the
> deterministic checks have unit tests including the near-limit cases (89 vs 90 vs 91 words); and
> `make test` is green with no API key.

---

## Lane B: semantic judge, checker, repair

> **Lane id: `lane-b-judge`. Create a Conductor workspace named `lane-b-judge`; whatever branch Conductor gives it is fine, the commit trailer is what identifies your work.**
>
> Read `docs/CONTRACTS.md` and `docs/ROADMAP.md` (Phase 2) first. You own exactly:
> `src/semantic_check.py`, `src/checker.py`, `src/repair.py`, `tests/test_semantic_check.py`,
> `tests/test_repair_hold.py`. Everything else is read-only.
>
> Lane A is building `compile.py` in parallel, so you cannot import real rules yet. Construct `Rule`
> objects by hand in your tests, per the `CONTRACTS.md` schema. That is the point of the frozen
> contract: build against the shape, not the implementation.
>
> `check_semantic_rule(email, rule)`: exactly one model call per rule, through
> `model_client.call_json`, with strict structured output `{"pass": bool, "reason": str}`. Never
> bundle rules into one call, even when it would be cheaper, because you lose the ability to
> attribute a specific failure to a specific rule and that attribution is the entire product. Log
> the raw request and response for every call so a verdict is auditable later instead of a boolean
> someone has to trust.
>
> `check_email(email, rules)`: deterministic rules run inline through Lane A's `CHECKS` registry
> with no network call; semantic rules dispatch one at a time. Return one `RuleResult` per rule, in
> rules order, with `source` set correctly.
>
> `repair_email(email, failed, instruction_set)`: exactly one model call, given the original
> instructions, the current draft, and the specific violations as rule id plus reason. Ask for a
> single corrected version fixing those without introducing new ones. **Your function does not
> re-check.** The caller re-runs the full checker over all rules, because a fix for one rule
> routinely breaks another: shortening to hit a word cap is the standard way to delete the specific
> company reference. Do not add a second repair attempt, ever, even if it would raise the headline
> number.
>
> Held behavior lives in the caller, but the test for it is yours: `tests/test_repair_hold.py` must
> prove that an email still failing after one repair is surfaced as held with its still-failing rule
> ids, and is neither silently dropped nor silently passed through.
>
> Done when: your three modules are implemented, tests pass under `MODEL_PROVIDER=fake` with no API
> key, and you have manually run one real semantic check against the API and pasted the logged
> request/response into your commit message as evidence the prompt behaves.

---

## Lane C: adversarial fixtures, blind labeling, review tooling

> **Lane id: `lane-c-fixtures`. Create a Conductor workspace named `lane-c-fixtures`; whatever branch Conductor gives it is fine, the commit trailer is what identifies your work.**
>
> Read `docs/CONTRACTS.md` and `docs/ROADMAP.md` (Phase 3) first. You own exactly:
> `src/fixtures.py`, `src/labeler.py`, `src/review_tool.py`, `fixtures/emails.json`,
> `fixtures/labels_model_draft.json`, `tests/test_fixtures.py`, `tests/test_labeler.py`.
> Everything else is read-only. Use `writer.py` from Phase 0; do not write your own generator.
>
> **Fixtures.** 50 emails, 10 per instruction set. Per email, decide at generation time which rules
> if any to deliberately violate, instruct the writer to violate exactly those, and record them as
> `planted_violations`. That field is generation bookkeeping and nothing else: it is never read by
> the checker, the labeler, or the scorer.
>
> Mix deliberately: some clean on every rule, some breaking exactly one, some breaking two or more,
> and a real share where the violation is borderline enough that reasonable people could disagree.
> The borderline ones are the point. A fixture set of obvious violations produces a grader that
> scores 98% and tells you nothing.
>
> Must include: implied pricing with no banned word ("cost-effective," "pays for itself," "ROI in
> weeks"); a company reference that name-drops the company but is otherwise industry boilerplate,
> sitting next to one that references something specific and checkable; rhetorical or indirect
> questions that avoid a literal "?" but function as questions; tone drifting corporate subtly
> against a "casual" instruction; and near-limit word counts (89 and 91) to stress the deterministic
> boundary and to make repair work at a tight cap.
>
> Recipients are generic placeholders only: "Acme Robotics," "a mid-size logistics company." No real
> companies, no real people, no real email addresses, anywhere.
>
> **Labeler.** `label_email(email_text, instruction_set)` is blind: it receives the email and the
> plain-English instructions, the same input a careful reader would have. It must not receive
> `planted_violations`, and it must not import `semantic_check.py` or reuse the checker's judge
> prompts. Write your own labeling prompt from scratch, framed as "read this cold and say which
> instructions it breaks." Add a test that fails if `labeler.py` imports `semantic_check`, so the
> separation cannot rot later. Output the complete label set, one label per (email, rule) pair, to
> `labels_model_draft.json`.
>
> **Review tool.** This is what makes the two-hour human gate survivable, so treat it as a real
> deliverable, not a script you dash off at the end. Emit a single self-contained HTML page: one row
> per (email, rule), showing the email body, the instruction, the draft verdict and its reason, with
> keyboard-driven confirm/overturn, a reason field for overturns, a progress counter, and an export
> button that writes corrected JSON in the `labels_ground_truth.json` schema with `reviewed` and
> `overturned` set. Group rows by email so the reviewer reads each email once rather than fifty
> times. Roughly 300 rows at 20 seconds each is the budget; five extra seconds per row costs 25
> minutes. Keep all state in JavaScript variables and export explicitly. A CSV round-trip is an
> acceptable fallback if the HTML runs long, but try the HTML first.
>
> Done when: `emails.json` has 50 validated records with the adversarial cases above present and
> identifiable; `labels_model_draft.json` is complete with no missing (email, rule) pair; the review
> sheet opens in a browser, keyboard navigation works, and export round-trips into a schema-valid
> file; tests pass with no API key.

---

## Lane D: scoring and surface

> **Lane id: `lane-d-scoring`. Create a Conductor workspace named `lane-d-scoring`; whatever branch Conductor gives it is fine, the commit trailer is what identifies your work.**
>
> Read `docs/CONTRACTS.md` and `docs/ROADMAP.md` (Phase 4) first. You own exactly:
> `src/score.py`, `src/cli.py`, `tests/test_score.py`, and the example
> `examples/instruction-adherence-grader/README.md`. Everything else is read-only.
>
> Nothing upstream of you is finished yet, and you do not need it. Code against the JSON schemas in
> `CONTRACTS.md` and write your own small synthetic run files and label files as test fixtures under
> `tests/data/`. Doing it that way is better than waiting: it forces the scorer to be correct
> against the contract rather than against whatever the other lanes happen to emit.
>
> Two computations, never conflated:
>
> **Adherence rate.** Percentage of emails in the batch that end up passing every rule, counting a
> successful single repair as a pass. Report the breakdown too: passed first try, passed after
> repair, held. Held emails get named individually with their still-failing rules.
>
> **Grader precision / recall / F1.** Compare the checker's **pre-repair** per-rule verdicts, the
> `initial_results` field, against `labels_ground_truth.json`. Comparing post-repair results would
> inflate the number; add an assertion that would catch it. Positive class is "violation present."
> Report aggregate, per rule, and split deterministic vs semantic. Deterministic should be at or
> near perfect and a deviation there is a real bug worth surfacing loudly; semantic is where the
> signal is.
>
> The `passed` / `violated` sign flip between `RuleResult` and `Label` is the likeliest bug in this
> project. Convert in exactly one named function, and write a unit test that fails if the sign
> flips. Also make `score.py` raise on an incomplete ground truth set rather than silently scoring
> the subset it happens to have, since a silent subset is how a grader reports perfect recall on the
> rules it covered.
>
> **CLI**: one entrypoint with `fixtures`, `label`, `review`, `grade`, `score`, `report`
> subcommands, plus `--limit N` for cheap iteration and `--no-cache`. Wire subcommands to the
> owning modules' documented signatures; where a module is still a stub, call it anyway and let the
> `NotImplementedError` surface. Integration will confirm the wiring.
>
> **README skeleton**: fix the section order now, with numbers as `TBD` placeholders that Phase 7
> fills in. Order is: the two headline numbers, a one-line statement of what the project does, the
> synthetic-data and no-real-product disclosure, the pipeline diagram, method (fixture generation,
> how ground truth was produced, the labeler/checker separation and why), the numbers in detail
> including the deterministic/semantic split and the named holds, then limitations (small fixture
> set, synthetic data, one person's judgment as ground truth, no production traffic, single model
> family). Do not oversell. The limitations section being honest is worth more than the headline
> number being high.
>
> Done when: `score.py` computes both numbers from contract-shaped inputs, the sign-flip and
> incomplete-labels tests exist and pass, `--help` works for every subcommand, and the README
> skeleton is committed with placeholders.

---

## Integration: merge, `grader.py`, first real batch

> **Lane id: `phase-5-integration`. Run this in the Phase 0 workspace after the lanes have merged, or a fresh workspace off updated `main`.**
>
> Lanes A–D are merged in that order, each rebased on `main` before merging. Ownership was disjoint,
> so conflicts should be nil; if you hit one, Phase 0 under-specified a shared file, and the fix goes
> in the shared file rather than in a lane. Read every `docs/contract-changes/*.md` and reconcile
> them into `CONTRACTS.md` in one commit, noting which proposals you accepted and which you did not.
>
> Then write `src/grader.py`: `grade_email` and `grade_batch` per the contract. Compile the
> instruction set, check, repair once if anything failed, re-check the full rule set, classify as
> `pass` / `pass_after_repair` / `held`, and emit `runs/<run_id>.json` in the contract shape with
> `initial_results` preserved separately from `final_results`.
>
> Write `tests/test_grader_end_to_end.py`: a smoke test over a handful of fixture emails under
> `MODEL_PROVIDER=fake`, plus the held-email case end to end.
>
> Then run for real, in this order, watching cost: `make grade` over a `--limit 5` slice first to
> confirm the pipeline before spending the full batch, then the full 50, then `make label` to
> produce `labels_model_draft.json`, then `make review` to open the review sheet. Hand the sheet to
> the human and stop.

---

## Lane E: polish, runs concurrently with the human labeling gate

> **Lane id: `lane-e-polish`. Create a Conductor workspace named `lane-e-polish`; whatever branch Conductor gives it is fine, the commit trailer is what identifies your work.**
>
> Start this when the human labeling gate starts, so an agent is doing useful work during those two
> hours. You own: the top-level `README.md`, `.github/workflows/`, `docs/CONDUCTOR_LOG.md`,
> `scripts/session_report.py`. Do not touch anything under `src/` or `fixtures/`; the human is
> actively producing `labels_ground_truth.json` and Phase 7 needs the tree stable.
>
> Top-level `agent-harness/README.md`: what the repo is in two or three sentences, a one-line entry
> per example with a link, and a short note on the harness conventions this repo follows
> (env-configured models, cached model calls, fake provider for tests, structured output only). It
> should read as a harness that happens to contain this example, not as a wrapper invented to hold
> one project.
>
> CI: a GitHub Actions workflow that installs and runs `make test` with `MODEL_PROVIDER=fake` and no
> secrets. A green badge on a repo whose tests need no API key is a small, real signal.
>
> Finish `scripts/session_report.py` per the spec in `CONDUCTOR_LOG.md` and regenerate the table.
>
> Sweep the whole repo for the boundaries: no individual named, no real company or customer, no real
> email addresses, no framing of this as a confirmed engagement with any company. Grep for the
> obvious things and fix anything you find.

---

## Phase 7: final numbers and the record

> **Lane id: `phase-7-final`. Run this in the integration workspace, off updated `main`.**
>
> Starts when the human hands back `labels_ground_truth.json`. You own `src/score.py` outputs, the
> example README, and `docs/CONDUCTOR_LOG.md`'s prose sections.
>
> Run `make score`. Put the real numbers into the README in the order Lane D fixed: adherence rate,
> then grader precision/recall/F1 with the deterministic/semantic split. Report the overturn rate
> from the label review as its own line, since it says how far a blind model read sits from a
> careful human one, and that gap is a finding rather than a footnote.
>
> Write the holds section properly. Not "3 held" but which three and why, one line each, in the
> shape of "two exceeded the word limit even after repair, one still implied pricing through
> 'cost-effective' language." If a hold is the grader's fault rather than the writer's, say so.
>
> If a deterministic rule scored below perfect, do not smooth it over: find out why and either fix
> it or write the reason in limitations. That is the most informative single line the README can
> carry.
>
> Then `make report` to regenerate the session table, and fill the per-lane paragraphs in
> `docs/CONDUCTOR_LOG.md` including what went wrong in each lane. Then run the audit below.

---

## Audit: definition-of-done pass

> Run this as a subagent at the end, in a clean worktree, with this instruction:
>
> "Read `docs/ROADMAP.md`. For each checkbox in the Definition of done section, find the concrete
> evidence in the repo that satisfies it: the file, the function, the test, or the README line.
> Report a table of item, verdict (met / partially met / not met), and the evidence or the specific
> gap. Do not fix anything and do not be generous: an item with no test behind it is at best
> partially met. Then check the hard boundaries in `CONDUCTOR_KICKOFF.md` section 6 by grepping the
> repo, and separately verify that `labeler.py` does not import `semantic_check.py` and that
> `score.py` compares `initial_results` rather than `final_results`."
>
> Anything the audit marks not met goes into the README limitations section verbatim, before the
> repo is called finished.
