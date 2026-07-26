from __future__ import annotations

from pathlib import Path

from phanloaivanban.log_utils import close_logger, get_logger

def teardown_function() -> None:
    close_logger()


def test_get_logger_returns_singleton() -> None:
    a = get_logger()
    b = get_logger()
    assert a is b


def test_get_logger_creates_log_file(tmp_path: Path, monkeypatch) -> None:
    close_logger()
    monkeypatch.chdir(tmp_path)
    log_path = Path("data/app.log")
    logger = get_logger()
    logger.info("test message")
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "test message" in content


def test_get_logger_does_not_crash_on_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("phanloaivanban.log_utils.Path.mkdir", lambda self, **kw: (_ for _ in ()).throw(OSError("permission denied")))
    logger = get_logger()
    logger.info("should not crash")
