"""The single chokepoint for every model call in this project.

Four agents hammer one API key in parallel and the whole batch is re-run many
times, so this module carries everything that makes that survivable:

  * Structured output only. `call_json` returns a parsed dict; OpenAI uses its
    native strict-schema parser and Anthropic uses a forced tool call. Free-text
    JSON parsing is banned project-wide.
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
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, create_model

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

# OpenAI models are checked against GET /v1/models before their first request.
_verified_openai_models: set[str] = set()
_verified_openai_models_lock = threading.Lock()
_run_usage: dict[tuple[str, str], dict[str, int]] = {}
_run_usage_lock = threading.Lock()


class ModelRefusal(RuntimeError):
    """Raised when a model explicitly declines a structured-output request."""


class StrictSchemaError(ValueError):
    """Raised before a non-strict JSON Schema can reach the OpenAI API."""


Schema = dict[str, Any] | type[BaseModel]


class _ProviderResponse:
    """Parsed result plus facts that belong in the audit record, not its schema."""

    def __init__(
        self,
        result: dict[str, Any],
        *,
        temperature_applied: bool = True,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.result = result
        self.temperature_applied = temperature_applied
        self.usage = usage


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def call_json(
    prompt: str,
    schema: Schema,
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
    cfg.validate()
    model = model or cfg.model_name
    params = params or {}
    schema_dict = _schema_dict(schema)

    key = _cache_key(cfg.model_provider, model, system, prompt, schema_dict, params)

    if use_cache:
        cached = _cache_get(cfg, key)
        if cached is not None:
            _debug_log(
                cfg, model, system, prompt, schema_dict, cached, cache_hit=True,
                temperature_applied=True, usage=None,
            )
            return cached

    if cfg.model_provider == "fake":
        provider_response = _ProviderResponse(
            _fake_call(prompt, schema_dict, model, system), usage=None
        )
    elif cfg.model_provider == "anthropic":
        provider_response = _with_retries(
            cfg,
            lambda: _anthropic_call(cfg, model, system, prompt, schema_dict, params),
        )
    elif cfg.model_provider == "openai":
        provider_response = _with_retries(
            cfg,
            lambda: _openai_call(cfg, model, system, prompt, schema, params),
        )
    else:
        raise ValueError(f"unknown MODEL_PROVIDER: {cfg.model_provider!r}")

    response = provider_response.result
    _validate_against_schema(response, schema_dict)

    if use_cache:
        _cache_put(cfg, key, response)
    _debug_log(
        cfg, model, system, prompt, schema_dict, response, cache_hit=False,
        temperature_applied=provider_response.temperature_applied,
        usage=provider_response.usage,
    )
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
    if schema.get("enum"):
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
# Real providers
# --------------------------------------------------------------------------- #
def _anthropic_call(
    cfg: Config,
    model: str,
    system: str | None,
    prompt: str,
    schema: dict[str, Any],
    params: dict,
) -> _ProviderResponse:
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
            return _ProviderResponse(dict(block.input))
    raise RuntimeError("model returned no tool_use block; structured output failed")


def _openai_call(
    cfg: Config,
    model: str,
    system: str | None,
    prompt: str,
    schema: Schema,
    params: dict,
) -> _ProviderResponse:
    """Make an OpenAI strict structured-output request without parsing text."""
    import openai  # lazy: keeps the fake path fully offline

    if not cfg.api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Use MODEL_PROVIDER=fake for offline runs."
        )

    client = openai.OpenAI(api_key=cfg.api_key)
    _verify_openai_model(client, model)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": _openai_response_format(schema),
    }
    if "max_tokens" in params:
        kwargs["max_tokens"] = params["max_tokens"]

    try:
        completion = _openai_parse(client)(
            **kwargs, temperature=cfg.temperature
        )
        temperature_applied = True
    except openai.BadRequestError as exc:
        if not _temperature_unsupported(exc):
            raise
        completion = _openai_parse(client)(**kwargs)
        temperature_applied = False

    msg = completion.choices[0].message
    if getattr(msg, "refusal", None):
        raise ModelRefusal(str(msg.refusal))
    parsed = getattr(msg, "parsed", None)
    if parsed is None:
        raise RuntimeError("OpenAI returned neither a parsed result nor a refusal")
    if isinstance(parsed, BaseModel):
        result = parsed.model_dump(mode="json")
    elif isinstance(parsed, dict):
        result = parsed
    else:
        raise TypeError("OpenAI parsed result is not a JSON object")
    return _ProviderResponse(
        result,
        temperature_applied=temperature_applied,
        usage=_usage_dict(getattr(completion, "usage", None)),
    )


def _openai_parse(client: Any) -> Callable[..., Any]:
    """Use the SDK's native parsed-output helper across supported SDK versions."""
    parse = getattr(client.chat.completions, "parse", None)
    if parse is not None:
        return parse
    return client.beta.chat.completions.parse


def _openai_response_format(schema: Schema) -> type[BaseModel]:
    """Give the SDK a Pydantic model, including for a caller-provided JSON Schema.

    The SDK converts this model to strict JSON Schema and returns ``message.parsed``.
    This retains native structured output for dict callers without parsing content.
    """
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    assert isinstance(schema, dict)  # checked by _schema_dict before provider dispatch
    return _pydantic_model_from_schema("StructuredResponse", schema)


def _pydantic_model_from_schema(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    properties = schema.get("properties", {})
    fields = {
        field_name: (_pydantic_type(field_name.title(), field_schema), ...)
        for field_name, field_schema in properties.items()
    }
    return create_model(name, __config__=ConfigDict(extra="forbid"), **fields)


def _pydantic_type(name: str, schema: dict[str, Any]) -> Any:
    if "enum" in schema:
        return Literal.__getitem__(tuple(schema["enum"]))
    schema_type = schema.get("type")
    if schema_type == "string":
        return str
    if schema_type == "boolean":
        return bool
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "array":
        return list[_pydantic_type(f"{name}Item", schema.get("items", {}))]
    if schema_type == "object" or "properties" in schema:
        return _pydantic_model_from_schema(name, schema)
    raise StrictSchemaError(
        f"schema type {schema_type!r} cannot be represented as native structured output"
    )


def _verify_openai_model(client: Any, model: str) -> None:
    """Fail before a batch begins when the configured OpenAI model is unavailable."""
    with _verified_openai_models_lock:
        if model in _verified_openai_models:
            return
        listed = client.models.list()  # GET /v1/models
        records = getattr(listed, "data", listed)
        available = {getattr(record, "id", None) for record in records}
        if model not in available:
            raise ValueError(
                f"OpenAI model {model!r} is not served by GET /v1/models; "
                "set MODEL_NAME to an available model."
            )
        _verified_openai_models.add(model)


def _temperature_unsupported(exc: Exception) -> bool:
    message = str(exc).lower()
    return "temperature" in message and (
        "unsupported" in message
        or "not supported" in message
        or "only the default" in message
    )


def _usage_dict(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None
    raw = usage.model_dump() if hasattr(usage, "model_dump") else vars(usage)
    result = {
        name: int(value)
        for name, value in raw.items()
        if name in {"prompt_tokens", "completion_tokens", "total_tokens"}
        and value is not None
    }
    return result or None


def _with_retries(cfg: Config, fn: Callable[[], _ProviderResponse]) -> _ProviderResponse:
    if cfg.model_provider == "anthropic":
        import anthropic

        retryable = (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        )
        status_error = anthropic.APIStatusError
    elif cfg.model_provider == "openai":
        import openai

        retryable = (
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.InternalServerError,
        )
        status_error = openai.APIStatusError
    else:
        raise ValueError(f"unknown MODEL_PROVIDER: {cfg.model_provider!r}")

    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except status_error as exc:  # includes 429 / 529 / 5xx
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
    provider: str,
    model: str,
    system: str | None,
    prompt: str,
    schema: dict,
    params: dict,
) -> str:
    payload = json.dumps(
        {
            "provider": provider,
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
    temperature_applied: bool,
    usage: dict[str, int] | None,
) -> None:
    if not cfg.debug_log:
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": cfg.model_provider,
        "model": model,
        "cache_hit": cache_hit,
        "temperature_applied": temperature_applied,
        "usage": usage,
        "run_usage": _record_usage(cfg.model_provider, model, usage),
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


def _record_usage(
    provider: str, model: str, usage: dict[str, int] | None
) -> dict[str, int]:
    """Keep a process-wide total in each call's audit record."""
    with _run_usage_lock:
        total = _run_usage.setdefault((provider, model), {})
        if usage:
            for name, value in usage.items():
                total[name] = total.get(name, 0) + value
        return dict(total)


# --------------------------------------------------------------------------- #
# Light response validation
# --------------------------------------------------------------------------- #
def _schema_dict(schema: Schema) -> dict[str, Any]:
    """Normalize a Pydantic model class or reject a non-strict dict schema."""
    if isinstance(schema, dict):
        _validate_strict_schema(schema)
        return schema
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    raise TypeError("schema must be a JSON Schema dict or a Pydantic BaseModel class")


def _validate_strict_schema(schema: dict[str, Any], where: str = "schema") -> None:
    """Validate the subset OpenAI strict mode requires before making a call."""
    if schema.get("type") == "object" or "properties" in schema:
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise StrictSchemaError(f"{where}: object schema must define properties")
        if schema.get("additionalProperties") is not False:
            raise StrictSchemaError(
                f"{where}: strict schemas require additionalProperties: false"
            )
        required = schema.get("required")
        if not isinstance(required, list) or set(required) != set(properties):
            raise StrictSchemaError(
                f"{where}: strict schemas require every property in required"
            )
        for name, child in properties.items():
            if isinstance(child, dict):
                _validate_strict_schema(child, f"{where}.properties[{name!r}]")
    if isinstance(schema.get("items"), dict):
        _validate_strict_schema(schema["items"], f"{where}.items")
    for keyword in ("allOf", "anyOf", "oneOf"):
        for index, child in enumerate(schema.get(keyword, [])):
            if isinstance(child, dict):
                _validate_strict_schema(child, f"{where}.{keyword}[{index}]")


def _validate_against_schema(obj: Any, schema: dict) -> None:
    """Cheap structural check: required keys present. Not a full JSON Schema validator."""
    if schema.get("type") == "object" or "properties" in schema:
        if not isinstance(obj, dict):
            raise ValueError("structured output is not an object")
        for req in schema.get("required", []):
            if req not in obj:
                raise ValueError(f"structured output missing required key {req!r}")
