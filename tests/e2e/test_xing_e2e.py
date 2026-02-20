from __future__ import annotations

import os

import pytest


@pytest.mark.e2e
@pytest.mark.skipif(
    os.getenv("XING_E2E_ENABLED", "0") != "1",
    reason="E2E intentionally disabled unless XING_E2E_ENABLED=1",
)
def test_xing_e2e_not_run_by_default() -> None:
    pytest.skip("Manual e2e smoke test. Use scripts/xing_e2e.py when needed.")
