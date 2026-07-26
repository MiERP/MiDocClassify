from __future__ import annotations

import logging
from pathlib import Path

_LOG: logging.Logger | None = None

def close_logger() -> None:
    global _LOG
    if _LOG is None:
        return
    for handler in list(_LOG.handlers):
        handler.close()
        _LOG.removeHandler(handler)
    _LOG = None


def _setup_log() -> logging.Logger:
    global _LOG
    if _LOG is not None:
        return _LOG
    logger = logging.getLogger("phanloaivanban")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        log_dir = Path("data")
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_dir / "app.log"), encoding="utf-8", mode="a", delay=True)
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    _LOG = logger
    return logger


def get_logger() -> logging.Logger:
    return _setup_log()
