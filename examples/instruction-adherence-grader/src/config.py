"""Env-driven configuration for the grader.

No model id is hardcoded in application logic anywhere in this project. Model names
drift, so they are read from the environment. The two constants below are the
*documented defaults*, resolved once at Phase 0 build time and recorded (with
provenance) in `.env.example`. Everything else in the codebase reads the resolved
value from a `Config` instance, never a literal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Resolved defaults. See .env.example for provenance (source + date verified).
# OpenAI is the working default for this build. Anthropic remains supported.
DEFAULT_MODEL_NAME = "gpt-5.6-terra"
DEFAULT_WRITER_MODEL_NAME = "gpt-5.6-terra"
DEFAULT_PROVIDER = "openai"
_PROVIDER_DEFAULTS = {
    "openai": ("gpt-5.6-terra", "gpt-5.6-terra"),
    "anthropic": ("claude-sonnet-5", "claude-sonnet-5"),
    "fake": ("fake-model", "fake-model"),
}
_KEY_ENV_BY_PROVIDER = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
DEFAULT_CACHE_DIR = ".model_cache"
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_DEBUG_LOG = ".model_cache/calls.jsonl"

# Every model call in this project runs at temperature 0. This is not configurable:
# reproducibility and the content-addressed cache both depend on it.
TEMPERATURE = 0.0


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration. Build with `Config.from_env()`."""

    model_name: str = DEFAULT_MODEL_NAME
    writer_model_name: str = DEFAULT_WRITER_MODEL_NAME
    model_provider: str = DEFAULT_PROVIDER
    api_key: str | None = None
    cache_dir: str = DEFAULT_CACHE_DIR
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    debug_log: str = DEFAULT_DEBUG_LOG
    temperature: float = TEMPERATURE

    def validate(self) -> None:
        """Ensure this configuration can make calls for its selected provider."""
        if self.model_provider not in _PROVIDER_DEFAULTS:
            raise ValueError(
                "unknown MODEL_PROVIDER: "
                f"{self.model_provider!r}; expected openai, anthropic, or fake"
            )
        if self.max_concurrency < 1:
            raise ValueError("MODEL_MAX_CONCURRENCY must be at least 1")
        key_env = _KEY_ENV_BY_PROVIDER.get(self.model_provider)
        if key_env and not self.api_key:
            raise RuntimeError(
                f"{key_env} is not set for MODEL_PROVIDER={self.model_provider!r}. "
                "Use MODEL_PROVIDER=fake for offline runs."
            )

    @classmethod
    def from_env(cls, *, dotenv: bool = True) -> Config:
        """Read configuration from the environment (loading a local .env first)."""
        if dotenv:
            load_dotenv()
        provider = os.environ.get("MODEL_PROVIDER", DEFAULT_PROVIDER)
        model_default, writer_default = _PROVIDER_DEFAULTS.get(
            provider, (DEFAULT_MODEL_NAME, DEFAULT_WRITER_MODEL_NAME)
        )
        key_env = _KEY_ENV_BY_PROVIDER.get(provider)
        cfg = cls(
            model_name=os.environ.get("MODEL_NAME", model_default),
            writer_model_name=os.environ.get("WRITER_MODEL_NAME", writer_default),
            model_provider=provider,
            api_key=os.environ.get(key_env) if key_env else None,
            cache_dir=os.environ.get("MODEL_CACHE_DIR", DEFAULT_CACHE_DIR),
            max_concurrency=int(
                os.environ.get("MODEL_MAX_CONCURRENCY", DEFAULT_MAX_CONCURRENCY)
            ),
            debug_log=os.environ.get("MODEL_DEBUG_LOG", DEFAULT_DEBUG_LOG),
        )
        cfg.validate()
        return cfg
