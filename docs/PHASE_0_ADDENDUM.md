# Phase 0 addendum: a `claude_cli` model provider

**Run this in the Phase 0 workspace, before the four lanes are created.**

`model_client.py`, `config.py` and `.env.example` are frozen shared property. Changing them after
four worktrees have branched means four rebases and four agents working against a moving floor. So
this lands now or not at all.

## Why

There is no `ANTHROPIC_API_KEY` available for this build, so the `anthropic` provider cannot run.
The Claude Code CLI is already installed and already authenticated against a subscription, and it
can be driven non-interactively with genuine schema-constrained output. That makes it a usable third
provider for this project's own model calls.

This is additive. The `anthropic` provider stays exactly as built and stays the default. A repo
called `agent-harness` having a pluggable provider layer, where the same grader runs against the API,
against the local CLI, or against a deterministic fake, is a better artifact than one hardwired to a
single backend.

## What to build

A third value for `MODEL_PROVIDER`: `anthropic` (default) | `claude_cli` | `fake`.

The `claude_cli` provider shells out per call. It is not the Python Agent SDK; it is the CLI as a
subprocess, which is the documented path for exactly this.

```
claude -p <prompt>
  --output-format json
  --json-schema '<the same JSON Schema call_json already takes>'
  --model <Config.model_name>
  --system-prompt <system>            # full replace, not append
  --permission-mode dontAsk
  --permission-prompts none
  --allowedTools ""
```

Read the result's `structured_output` field. That is real schema-constrained output, so
`call_json`'s contract holds and the project-wide ban on parsing free-text JSON is not weakened. If
`structured_output` is absent, raise. **Never fall back to scraping the `result` text field**; a
provider that silently degrades to text parsing is worse than one that fails.

Details that matter:

- **Do not pass `--bare`.** Bare mode never reads the OAuth credentials and requires an API key,
  which is the thing we do not have. The cost of omitting it is that the run loads ambient context,
  so set the subprocess `cwd` to an empty scratch directory with no `.claude/`, no `.mcp.json` and
  no `CLAUDE.md`. Anything in `~/.claude` still loads; note that in the limitations.
- **Version-check at startup.** `--permission-prompts` needs Claude Code v2.1.259 or later, and
  `--json-schema` is only reliably enforced from v2.1.205. Run `claude --version` once on first use
  and raise a clear, actionable error if the installed version is older, rather than discovering it
  350 calls into a batch.
- **Cache exactly as before.** The cache key must include the provider, so `anthropic` and
  `claude_cli` results never collide in `.model_cache/`.
- **Lower the concurrency default for this provider.** Each call is a full CLI process start, not an
  HTTP request. Two or three concurrent is right; the semaphore already exists.
- **Log `total_cost_usd`** from the JSON envelope into the existing debug log, per call and summed
  per run. It is a client-side estimate, so label it as one.
- **No temperature control.** The CLI does not expose it, so `temperature=0` reproducibility is not
  available on this provider. The disk cache becomes the reproducibility mechanism instead: a
  committed cache makes a run replayable, a cold cache does not. Say this plainly in the README
  limitations; it is a real caveat about the numbers, not a footnote.

Add tests: the provider builds the expected argv, parses `structured_output` correctly, raises when
it is missing, raises on an old CLI version, and keys the cache separately from `anthropic`. Mock
the subprocess. The suite must still pass with no API key and without invoking the real CLI.

Update `.env.example` to document all three providers and the tradeoffs above.

## One caution worth writing down

Using your own subscription through the CLI for your own local project is ordinary use. Shipping a
product that signs *other people* in with claude.ai, or that resells your rate limits, is not
permitted without prior approval from Anthropic. This repo is fine as long as it stays a project
that a reader runs with their own credentials. Do not add anything that authenticates a third party.

## Then

Verify: `make test` green with no API key, and one real end-to-end call through `claude_cli` proving
`structured_output` comes back schema-shaped. Paste that response into the commit message as
evidence, the same way Lane B is asked to.

Commit with `Conductor-Lane: phase-0-foundation`, merge Phase 0 to `main`, and only then create the
four lane workspaces.
