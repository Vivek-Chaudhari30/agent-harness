"""The single chokepoint for every model call in this project.

Four agents hammer one API key in parallel and the whole batch is re-run many
times, so this module carries everything that makes that survivable:

  * Structured output only. `call_json` uses a forced tool call and returns a dict.
    Free-text JSON parsing is banned project-wide.
  * A content-addressed disk cache keyed on the full request. temperature=0. A
    cache hit costs nothing and returns instantly, which is what makes re-running
    the batch free and reproducible across worktrees. Bypass with use_cache=False.
  * Retry with exponential backoff + jitter on 429 / 529 / connection errors, and
    a concurrency semaphore (MODEL_MAX_CONCURRENCY).
  * A `fake` provider: MODEL_PROVIDER=fake returns deterministic canned responses
    so unit tests and CI run with no API key. Every lane's tests use this.
  * A debug log: every call's raw request and response appended to a JSONL file so
    a verdict is auditable later rather than a boolean you have to trust.

Usage:
    from src.model_client import call_json
    result = call_json(prompt, schema, system=..., model=...)
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from src.config import Config

# Default cap on assistant output tokens per call. Callers can override via params.
_DEFAULT_MAX_TOKENS = 4096
# Retry policy for the real provider.
_MAX_RETRIES = 6
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_CAP_SECONDS = 30.0

# Concurrency semaphore, created lazily so tests can vary max_concurrency.
_semaphore_lock = threading.Lock()
_semaphore: threading.BoundedSemaphore | None = None
_semaphore_size: int | None = None

# Fake provider responder. Tests may install their own; default synthesizes a
# schema-valid object.
FakeResponder = Callable[[dict], dict]
_fake_responder: FakeResponder | None = None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def call_json(
    prompt: str,
    schema: dict,
    *,
    model: str | None = None,
    system: str | None = None,
    use_cache: bool = True,
    config: Config | None = None,
    params: dict | None = None,
) -> dict:
    """Make one structured model call and return the parsed JSON object.

    `schema` is a JSON Schema describing the object the model must emit. The result
    is guaranteed (by the provider or the fake synthesizer) to carry the schema's
    required keys.
    """
    cfg = config or Config.from_env()
    model = model or cfg.model_name
    params = params or {}

    key = _cache_key(model, system, prompt, schema, params)

    if use_cache:
        cached = _cache_get(cfg, key)
        if cached is not None:
            _debug_log(cfg, model, system, prompt, schema, cached, cache_hit=True)
            return cached

    if cfg.model_provider == "fake":
        response = _fake_call(prompt, schema, model, system)
    elif cfg.model_provider == "anthropic":
        response = _with_retries(
            cfg,
            lambda: _anthropic_call(cfg, model, system, prompt, schema, params),
        )
    else:
        raise ValueError(f"unknown MODEL_PROVIDER: {cfg.model_provider!r}")

    _validate_against_schema(response, schema)

    if use_cache:
        _cache_put(cfg, key, response)
    _debug_log(cfg, model, system, prompt, schema, response, cache_hit=False)
    return response


# --------------------------------------------------------------------------- #
# Fake provider
# --------------------------------------------------------------------------- #
def set_fake_responder(fn: FakeResponder | None) -> None:
    """Install a deterministic responder for MODEL_PROVIDER=fake.

    `fn` receives {"prompt", "schema", "model", "system"} and returns a dict that
    satisfies the schema. Pass None to fall back to schema synthesis.
    """
    global _fake_responder
    _fake_responder = fn


def reset_fake_responder() -> None:
    set_fake_responder(None)


def _fake_call(prompt: str, schema: dict, model: str, system: str | None) -> dict:
    if _fake_responder is not None:
        return _fake_responder(
            {"prompt": prompt, "schema": schema, "model": model, "system": system}
        )
    return _synthesize_from_schema(schema)


def _synthesize_from_schema(schema: dict) -> Any:
    """Build a minimal, deterministic, schema-valid value."""
    if "default" in schema:
        return schema["default"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {k: _synthesize_from_schema(v) for k, v in props.items()}
    if t == "array":
        return []
    if t == "boolean":
        return False
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "string":
        return ""
    if t == "null":
        return None
    return None


# --------------------------------------------------------------------------- #
# Real provider (Anthropic), using a forced tool call for structured output.
# --------------------------------------------------------------------------- #
def _anthropic_call(
    cfg: Config,
    model: str,
    system: str | None,
    prompt: str,
    schema: dict,
    params: dict,
) -> dict:
    import anthropic  # lazy: keeps the fake path fully offline

    if not cfg.api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Use MODEL_PROVIDER=fake for offline runs."
        )

    client = anthropic.Anthropic(api_key=cfg.api_key)
    tool = {
        "name": "emit_result",
        "description": "Emit the structured result. This is the only allowed output.",
        "input_schema": schema,
    }
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": params.get("max_tokens", _DEFAULT_MAX_TOKENS),
        "temperature": cfg.temperature,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": "emit_result"},
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    with _acquire(cfg):
        message = client.messages.create(**kwargs)

    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_result":
            return dict(block.input)
    raise RuntimeError("model returned no tool_use block; structured output failed")


def _with_retries(cfg: Config, fn: Callable[[], dict]) -> dict:
    import anthropic

    retryable = (
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.InternalServerError,
    )
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except anthropic.APIStatusError as exc:  # includes 429 / 529 / 5xx
            if exc.status_code not in (429, 500, 502, 503, 504, 529):
                raise
            if attempt == _MAX_RETRIES:
                raise
            _sleep_backoff(attempt)
        except retryable:
            if attempt == _MAX_RETRIES:
                raise
            _sleep_backoff(attempt)
    raise RuntimeError("unreachable: retry loop exhausted")


def _sleep_backoff(attempt: int) -> None:
    delay = min(_BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_CAP_SECONDS)
    time.sleep(delay + random.uniform(0, delay))


def _acquire(cfg: Config):
    global _semaphore, _semaphore_size
    with _semaphore_lock:
        if _semaphore is None or _semaphore_size != cfg.max_concurrency:
            _semaphore = threading.BoundedSemaphore(cfg.max_concurrency)
            _semaphore_size = cfg.max_concurrency
        sem = _semaphore
    return _SemaphoreGuard(sem)


class _SemaphoreGuard:
    def __init__(self, sem: threading.BoundedSemaphore):
        self._sem = sem

    def __enter__(self):
        self._sem.acquire()
        return self

    def __exit__(self, *exc):
        self._sem.release()
        return False


# --------------------------------------------------------------------------- #
# Content-addressed disk cache
# --------------------------------------------------------------------------- #
def _cache_key(
    model: str, system: str | None, prompt: str, schema: dict, params: dict
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "system": system or "",
            "prompt": prompt,
            "schema": schema,
            "params": params,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(cfg: Config, key: str) -> str:
    return os.path.join(cfg.cache_dir, f"{key}.json")


def _cache_get(cfg: Config, key: str) -> dict | None:
    if not cfg.cache_dir:
        return None
    path = _cache_path(cfg, key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _cache_put(cfg: Config, key: str, response: dict) -> None:
    if not cfg.cache_dir:
        return
    os.makedirs(cfg.cache_dir, exist_ok=True)
    path = _cache_path(cfg, key)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(response, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic: safe under concurrent writers


# --------------------------------------------------------------------------- #
# Debug log
# --------------------------------------------------------------------------- #
def _debug_log(
    cfg: Config,
    model: str,
    system: str | None,
    prompt: str,
    schema: dict,
    response: dict,
    *,
    cache_hit: bool,
) -> None:
    if not cfg.debug_log:
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": cfg.model_provider,
        "model": model,
        "cache_hit": cache_hit,
        "system": system,
        "prompt": prompt,
        "schema": schema,
        "response": response,
    }
    directory = os.path.dirname(cfg.debug_log)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(cfg.debug_log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# Light response validation
# --------------------------------------------------------------------------- #
def _validate_against_schema(obj: Any, schema: dict) -> None:
    """Cheap structural check: required keys present. Not a full JSON Schema validator."""
    if schema.get("type") == "object" or "properties" in schema:
        if not isinstance(obj, dict):
            raise ValueError("structured output is not an object")
        for req in schema.get("required", []):
            if req not in obj:
                raise ValueError(f"structured output missing required key {req!r}")
