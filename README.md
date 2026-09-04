# agent-harness

[![CI](https://github.com/Vivek-Chaudhari30/agent-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/Vivek-Chaudhari30/agent-harness/actions/workflows/ci.yml)

A small harness for building and evaluating LLM-powered pipelines with reproducible,
env-configured model calls. Each example under `examples/` follows the same conventions:
models and providers are read from the environment (never hardcoded), every model call
is cached and uses structured output, a `fake` provider lets the full test suite run
with no API key, and temperature is set to 0 where the provider supports it.

## Examples

| Example | What it measures |
|---|---|
| [instruction-adherence-grader](examples/instruction-adherence-grader/) | Does an AI-written email obey the plain-English rules a sender set for it? Reports adherence rate over a batch and precision/recall/F1 of the grader against hand-labeled ground truth. |

## Harness conventions

- **Env-configured models.** `MODEL_PROVIDER` selects the provider (`openai`, `anthropic`,
  `fake`). `MODEL_NAME` and `WRITER_MODEL_NAME` select the model within that provider.
  No model name appears in source code.

- **Cached model calls.** Every call is written to a local disk cache keyed by
  `(provider, model, prompt_hash)`. Re-running the pipeline without `--no-cache` is
  fast and free.

- **Fake provider for tests.** `MODEL_PROVIDER=fake` returns deterministic structured
  responses without any network call. The full test suite runs with no API key and
  no internet access.

- **Structured output only.** Every model call specifies a JSON schema; responses are
  validated before use. The harness never parses free-form text.

## Build record

See [`docs/CONDUCTOR_LOG.md`](docs/CONDUCTOR_LOG.md) for the multi-session,
parallel-worktree build record, and [`docs/ROADMAP.md`](docs/ROADMAP.md) for the
phase plan.
