# agent-harness

A small harness for building and evaluating LLM-powered examples with reproducible,
env-configured model calls. Each example lives under `examples/` and follows the
same conventions: models are read from the environment (never hardcoded), every
model call is cached and uses structured output, and a `fake` provider lets the
whole test suite run with no API key.

> This is a placeholder top-level README written in Phase 0 so the repo is not
> headless on its first commit. Lane E owns the real one.

## Examples

- [instruction-adherence-grader](examples/instruction-adherence-grader/) — does an
  AI-written email actually obey the rules a customer set for it? Leads with an
  adherence rate over a batch and, separately, the precision/recall/F1 of the
  grader itself against hand-labeled ground truth.

## How it was built

See [`docs/CONDUCTOR_LOG.md`](docs/CONDUCTOR_LOG.md) for the multi-session,
parallel-worktree build record, and [`docs/ROADMAP.md`](docs/ROADMAP.md) for the
phase plan.

## Model-call limitations

The instruction-adherence grader requests `temperature=0` for reproducibility. On
the verified `gpt-5.6-terra` configuration, the API rejected that setting, so the
provider retries once without it and records `temperature_applied: false` in the
call log. Those cached results are therefore auditable but not fully deterministic.

By default, the writer and judge use the same model family, so agreement between
them can be inflated. Configuring the writer and checker with different supported
providers/models is future work enabled by the provider layer.
