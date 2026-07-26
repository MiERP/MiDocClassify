from __future__ import annotations

import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True, scope="session")
def _anchor_cwd() -> None:
    """Keep CWD at repo root so relative data-template paths resolve in CI."""
    prev = os.getcwd()
    os.chdir(PROJECT_ROOT)
    try:
        yield
    finally:
        os.chdir(prev)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "requires_parsers: needs pypdfium2/python-docx/Pillow")
    config.addinivalue_line("markers", "requires_desktop: needs PySide6 GUI stack")
    config.addinivalue_line("markers", "slow: long-running test")
