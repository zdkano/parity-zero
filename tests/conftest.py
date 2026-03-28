"""Shared test fixtures for parity-zero test suite.

Provides session-level and function-level fixtures that ensure clean
test isolation, especially around FastAPI dependency overrides and
shared application state.

See ADR-036 for the test isolation hardening decisions.
"""

from __future__ import annotations

import pytest

from api.main import app


@pytest.fixture(autouse=True)
def _reset_dependency_overrides():
    """Reset FastAPI dependency overrides before and after each test.

    This prevents cross-test pollution from module-level overrides
    (e.g. test_api.py setting overrides at import time that bleed
    into test_auth.py).  Each test module is responsible for setting
    its own overrides via fixtures.
    """
    saved = dict(app.dependency_overrides)
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)
