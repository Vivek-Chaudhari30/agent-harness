# Phase 0 addendum: pluggable model providers

**Run this in the Phase 0 workspace, before the four lanes are created.**

`model_client.py`, `config.py`, `.env.example` and `pyproject.toml` are frozen shared property.
Changing them after four worktrees have branched means four rebases and four agents building against
a floor that moved. So this lands now, or not at all.

## Why

There is no `ANTHROPIC_API_KEY` for this build, but an OpenAI API key is available. The project's own
model calls do not need to be Claude; they need to be a model with strict schema-constrained output
and a stable id. So `MODEL_PROVIDER` grows a fourth value and OpenAI becomes the working default for
this build.

This is additive. The `anthropic` provider stays exactly as built and stays supported. A repo called
`agent-harness` whose grader runs against any of several backends is a better artifact than one
hardwired to a single vendor, and it makes one real methodological improvement possible later: see
"the writer/judge caveat" at the bottom.

This section supersedes the model defaults in `CONDUCTOR_KICKOFF.md` §4.2 and §4.3. Everything else
in the kickoff stands, including the ban on hardcoded model ids in application logic.

## What to build

`MODEL_PROVIDER` becomes: `openai` (new default for this build) | `anthropic` | `fake`.

### The `openai` provider

Use the official `openai` Python SDK, added to `pyproject.toml`. Structured output is native and
strict, so `call_json`'s contract is fully preserved and the project-wide ban on parsing free-text
JSON is not weakened anywhere.

```python
completion = client.chat.completions.parse(
    model=cfg.model_name,
    messages=[{"role": "system", "content": system},
              {"role": "user",   "content": prompt}],
    response_format=SomePydanticModel,   # SDK converts it to a strict JSON schema
)
msg = completion.choices[0].message
if msg.refusal:
    raise ModelRefusal(msg.refusal)
result = msg.parsed
```

Requirements and gotchas:

- **`call_json` keeps its existing signature.** It already takes a schema. Accept either a Pydantic
  model or a plain JSON Schema dict; if a dict, it must satisfy strict mode, which means
  `additionalProperties: false` and every property listed in `required`. Validate this at call time
  and raise a clear error rather than letting the API reject it 200 calls into a batch.
- **Check `message.refusal` before `message.parsed`.** A refusal is a first-class field here, not an
  exception. Surface it as a distinct error type so a refused judgment never silently becomes a
  `pass`. A judge call that returns "the model declined" must not be scored as "no violation."
- **Temperature.** Attempt `temperature=0`. If the API rejects it as unsupported for the chosen
  model, retry once without it and set a flag on the response recording that the call was
  non-deterministic. Do not silently drop it: whether `temperature=0` actually applied changes what
  the disk cache means, and the README limitations section has to state which was true.
- **Cache key must include the provider and the model id**, so `openai`, `anthropic` and `fake`
  results never collide in `.model_cache/`.
- **Retry** on 429 and 5xx with the existing backoff. Concurrency stays as built.
- **Log usage** from `completion.usage` into the existing debug log, per call, plus a per-run total,
  so the README can state what the batch actually cost.

### Model ids and cost

Do not hardcode these in application logic; they are documented defaults read from `Config`.

As of September 2026 the current OpenAI text models are `gpt-5.6-luna` (small, $0.20 / $1.20 per
million input / output tokens), `gpt-5.6-terra` ($2 / $12), `gpt-5.6-sol` ($4 / $20) and
`gpt-6-astra` (flagship, $10 / $50). **Verify against `GET /v1/models` on first run** and fail with a
clear error if the configured id is not served, rather than discovering it mid-batch.

Defaults to set:

- `MODEL_NAME=gpt-5.6-terra` for the checker and the labeler. Semantic judgment on deliberately
  borderline cases is the hard part of this project and the place not to economize.
- `WRITER_MODEL_NAME=gpt-5.6-terra`, kept as a separate variable so it can diverge.
- Document `gpt-5.6-luna` as the cheap option for iterating during development.

The whole project is roughly 350 to 400 calls with short prompts. At `terra` that is on the order of
a dollar or two for a full cold-cache run, and near zero for every re-run after that, because the
cache makes repeats free. Cost is not a reason to pick the weaker model here.

### Config and env

`.env.example` documents all providers: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MODEL_PROVIDER`,
`MODEL_NAME`, `WRITER_MODEL_NAME`, `MODEL_CACHE_DIR`, `MODEL_MAX_CONCURRENCY`. `Config` validates
that the key matching the selected provider is present and raises a useful message naming the missing
variable if not. When `MODEL_NAME` is unset, resolve a provider-specific documented default rather
than failing.

`.env` is already gitignored. The key goes there and nowhere else: not in a commit, not in a
`Makefile`, not pasted into an agent session, not in a test fixture. Add a check to the audit pass
that greps the repo for anything shaped like an API key.

### Tests

Mock the SDK. Cover: a strict schema round-trips through `call_json`; a refusal raises the distinct
error type rather than returning a pass; a non-strict schema is rejected up front; the temperature
fallback sets its flag; the cache keys on provider plus model so two providers do not collide; and an
unknown model id fails at startup. The suite must still pass with **no keys of any kind** under
`MODEL_PROVIDER=fake`.

## The writer/judge caveat

With one provider, the same model family writes the fixture emails, judges them, and produces the
first-pass labels. Same-family agreement is inflated agreement: a judge tends to accept phrasing a
sibling model produced. This does not invalidate the numbers, but it does bound them, and it belongs
in the README limitations section in plain words.

The provider layer makes the fix a one-variable change rather than a rewrite. If an Anthropic key
ever becomes available, pointing `WRITER_MODEL_NAME` at one family and the checker at another turns
this into a genuine cross-family evaluation, which is a materially stronger result. Note that in the
README as future work, and make sure nothing in the code assumes a single provider for the whole run.

## Optional: a `claude_cli` provider

Not required, and not worth spending time-box on now that a key exists. For the record: `claude -p`
with `--output-format json --json-schema` returns strict structured output in a `structured_output`
field, using subscription auth, so it is a viable keyless provider. Do not pass `--bare`, which
ignores OAuth and demands a key. It offers no temperature control, and each call is a process start
rather than an HTTP request. Build it only if the other work is finished early.

## Then

Verify: `make test` green with no keys under `fake`, and one real end-to-end `openai` call proving a
strict schema comes back parsed. Paste that response into the commit message as evidence.

Commit with `Conductor-Lane: phase-0-foundation`, merge Phase 0 to `main`, and only then create the
four lane workspaces.
