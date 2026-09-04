"""Deterministic check registry. (Lane A)

STUB. Implemented by Lane A. See docs/CONTRACTS.md section 2.

CHECKS maps a check_id to a pure callable fn(email_text, params) -> (passed, reason).
Pure Python only: no network, no file I/O, no clock, no randomness, so every check
is unit-testable without an API key.
"""

from __future__ import annotations

from typing import Callable

# check_id -> fn(email_text, params) -> (passed, reason)
CHECKS: dict[str, Callable[[str, dict], tuple[bool, str]]] = {}
