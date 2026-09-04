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
# Mid-tier Claude model for the checker/labeler; the writer may differ.
DEFAULT_MODEL_NAME = "claude-sonnet-5"
DEFAULT_WRITER_MODEL_NAME = "claude-sonnet-5"
DEFAULT_PROVIDER = "anthropic"
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

    @classmethod
    def from_env(cls, *, dotenv: bool = True) -> "Config":
        """Read configuration from the environment (loading a local .env first)."""
        if dotenv:
            load_dotenv()
        return cls(
            model_name=os.environ.get("MODEL_NAME", DEFAULT_MODEL_NAME),
            writer_model_name=os.environ.get(
                "WRITER_MODEL_NAME", DEFAULT_WRITER_MODEL_NAME
            ),
            model_provider=os.environ.get("MODEL_PROVIDER", DEFAULT_PROVIDER),
            api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
            cache_dir=os.environ.get("MODEL_CACHE_DIR", DEFAULT_CACHE_DIR),
            max_concurrency=int(
                os.environ.get("MODEL_MAX_CONCURRENCY", DEFAULT_MAX_CONCURRENCY)
            ),
            debug_log=os.environ.get("MODEL_DEBUG_LOG", DEFAULT_DEBUG_LOG),
        )
