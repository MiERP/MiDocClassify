from __future__ import annotations

import os
import re
import time
import unicodedata
from pathlib import Path




def slugify_vi(text: str) -> str:
    text = text.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFKD", text.strip().lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9_-]", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


WRITE_RETRIES = 8
WRITE_RETRY_SECONDS = 0.25


def _atomic_write_with_retry(tmp: Path, target: Path) -> None:
    last_err: OSError | None = None
    for attempt in range(WRITE_RETRIES):
        try:
            tmp.replace(target)
            return
        except PermissionError:
            if attempt < WRITE_RETRIES - 1:
                time.sleep(WRITE_RETRY_SECONDS)
                continue
            _atomic_write_fallback(tmp, target)
            return
        except OSError as e:
            last_err = e
            break
    tmp.unlink(missing_ok=True)
    if last_err is not None:
        raise last_err


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return
        except OSError:
            pass
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    _atomic_write_with_retry(tmp, path)


def _atomic_write_fallback(tmp: Path, target: Path) -> None:
    try:
        if target.exists():
            _make_writable(target)
            target.unlink()
        tmp.replace(target)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        msg = (
            f"Cannot write {target} – file is locked by another process.\n"
            "Close the application holding this file, then retry."
        )
        raise PermissionError(msg) from None


def _make_writable(path: Path) -> None:
    try:
        path.chmod(0o666)
    except OSError:
        pass


def atomic_read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    return WIKILINK_RE.findall(text)


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def extract_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    result: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip().strip('"')
    return result
