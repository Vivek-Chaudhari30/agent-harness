# Every target is declared here in Phase 0, including ones whose implementation
# lands in a later lane, so no lane ever has to edit this file. Targets whose code
# does not exist yet route through the CLI, whose Phase 0 stub prints a clear
# "not implemented yet (lane X)" message and exits 0.

PY ?= python3
PIP ?= $(PY) -m pip
REPO_ROOT ?= ../..

.PHONY: install test lint fixtures label review grade score demo report

install:
	$(PIP) install -e ".[dev]"

test:
	MODEL_PROVIDER=fake $(PY) -m pytest

lint:
	@if $(PY) -m ruff --version >/dev/null 2>&1; then \
		$(PY) -m ruff check src tests || true; \
	else \
		echo "ruff not installed; skipping lint (make install to add it)"; \
	fi

fixtures:
	$(PY) -m src.cli fixtures

label:
	$(PY) -m src.cli label

review:
	$(PY) -m src.cli review

grade:
	$(PY) -m src.cli grade

score:
	$(PY) -m src.cli score

demo:
	$(PY) -m src.cli demo

report:
	$(PY) $(REPO_ROOT)/scripts/session_report.py
