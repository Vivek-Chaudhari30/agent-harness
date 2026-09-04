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
