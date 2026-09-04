"""Phase 0 tests for env-driven config."""

from __future__ import annotations

from src.config import Config, DEFAULT_MODEL_NAME, DEFAULT_WRITER_MODEL_NAME


def test_defaults_when_env_absent(monkeypatch):
    for var in (
        "MODEL_NAME",
        "WRITER_MODEL_NAME",
        "MODEL_PROVIDER",
        "ANTHROPIC_API_KEY",
        "MODEL_CACHE_DIR",
        "MODEL_MAX_CONCURRENCY",
        "MODEL_DEBUG_LOG",
    ):
        monkeypatch.delenv(var, raising=False)
    cfg = Config.from_env(dotenv=False)
    assert cfg.model_name == DEFAULT_MODEL_NAME
    assert cfg.writer_model_name == DEFAULT_WRITER_MODEL_NAME
    assert cfg.model_provider == "anthropic"
    assert cfg.temperature == 0.0
    assert cfg.api_key is None


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "some-model")
    monkeypatch.setenv("WRITER_MODEL_NAME", "another-model")
    monkeypatch.setenv("MODEL_PROVIDER", "fake")
    monkeypatch.setenv("MODEL_MAX_CONCURRENCY", "9")
    cfg = Config.from_env(dotenv=False)
    assert cfg.model_name == "some-model"
    assert cfg.writer_model_name == "another-model"
    assert cfg.model_provider == "fake"
    assert cfg.max_concurrency == 9


def test_checker_and_writer_models_are_independent(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "checker")
    monkeypatch.setenv("WRITER_MODEL_NAME", "writer")
    cfg = Config.from_env(dotenv=False)
    assert cfg.model_name != cfg.writer_model_name
