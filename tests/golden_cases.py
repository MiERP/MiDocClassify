"""Golden (ground-truth) cases derived from Vietnamese legal filenames.

Vietnamese legal documents encode their identity in the filename:

    {so}_{nam}_{KYHIEU}_{ma}.ext
    e.g. 183_2026_ND-CP_690304.docx
         -> so_van_ban = "183/2026/ND-CP"
         -> loai_van_ban = "Nghị định"
         -> co_quan_phat_hanh = "Chính phủ"

The KYHIEU (ký hiệu) is a standardized government code, so it is reliable
ground truth for ``loai_van_ban`` and (for the well-known prefixes) for
``co_quan_phat_hanh``. ``so_van_ban`` and the year portion of
``ngay_ban_hanh`` are also recoverable from the filename.

This module is a *helper*, not a test (no ``test_`` prefix), so pytest will
not collect it. Import it from ``test_recognition_accuracy.py``.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# KYHIEU prefix -> (loai_van_ban label, co_quan_phat_hanh)
# Only the deterministic, standardized prefixes get a co_quan; generic ones
# leave co_quan unknown (None) because the prefix alone cannot name the agency.
KYHIEU_MAP: dict[str, tuple[str, str | None]] = {
    "QH": ("Luật", "Quốc hội"),
    "ND-CP": ("Nghị định", "Chính phủ"),
    "CT-TTg": ("Chỉ thị", "Thủ tướng Chính phủ"),
    "QD-TTg": ("Quyết định", "Thủ tướng Chính phủ"),
    "TB-VPCP": ("Thông báo", "Văn phòng Chính phủ"),
    "QD": ("Quyết định", None),
    "TT": ("Thông tư", None),
    "NQ": ("Nghị quyết", None),
    "CV": ("Công văn", None),
    "KH": ("Kế hoạch", None),
    "HD": ("Hướng dẫn", None),
    "TB": ("Thông báo", None),
}

_KYHIEU_TOKEN_RE = re.compile(
    r"^(QH\d+|N[ĐD]-CP|CT-TTg|QD-[A-Za-zĐđ]+|TB-[A-Za-zĐđ]+|TT-[A-Za-zĐđ]+|"
    r"NQ-[A-Za-zĐđ]+|CV-[A-Za-zĐđ]+|KH-[A-Za-zĐđ]+|HD-[A-Za-zĐđ]+)$",
    re.IGNORECASE,
)
_NUM_RE = re.compile(r"^\d{1,4}$")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


@dataclass
class GoldenCase:
    file: str
    expected_so: str | None = None
    expected_loai: str | None = None
    expected_co_quan: str | None = None
    expected_year: str | None = None


def norm_ascii(value: str | None) -> str:
    """Normalize to ASCII-uppercase for diacritic/case-insensitive compare."""
    if not value:
        return ""
    value = value.replace("Đ", "D").replace("đ", "d")
    return unicodedata.normalize("NFD", value).encode("ascii", "ignore").decode().upper()


def lookup_kyhieu(kyhieu: str) -> tuple[str | None, str | None]:
    """Resolve a document code to expected type and issuing agency."""
    normalized = norm_ascii(kyhieu)
    normalized_map = {norm_ascii(key): value for key, value in KYHIEU_MAP.items()}

    if normalized in normalized_map:
        return normalized_map[normalized]
    if normalized.startswith("QH"):
        return KYHIEU_MAP.get("QH", (None, None))

    prefix = normalized.split("-", 1)[0]
    return normalized_map.get(prefix, (None, None))


def parse_filename(stem: str) -> GoldenCase | None:
    """Parse a filename stem into a GoldenCase, or None if not enough signal.

    Files with no recognizable KYHIEU (e.g. a scanned image ``93_Anh``) return
    None and are skipped -- they cannot be auto-labeled from the filename.
    """
    tokens = [t for t in stem.split("_") if t]
    so = nam = kyhieu = None
    for tok in tokens:
        if kyhieu is None and _KYHIEU_TOKEN_RE.match(tok):
            kyhieu = tok
        elif so is None and _NUM_RE.match(tok):
            so = tok
        elif nam is None and _YEAR_RE.match(tok):
            nam = tok
    if kyhieu is None or so is None:
        return None

    loai, co_quan = lookup_kyhieu(kyhieu)
    if loai is None:
        return None

    expected_so = f"{int(so):02d}/{nam}/{kyhieu}" if nam else f"{int(so):02d}/{kyhieu}"
    return GoldenCase(
        file="",  # filled by caller
        expected_so=expected_so,
        expected_loai=loai,
        expected_co_quan=co_quan,
        expected_year=nam,
    )


def build_golden_cases(folder: Path, supported_ext: set[str] | None = None) -> list[GoldenCase]:
    if supported_ext is None:
        supported_ext = {".pdf", ".doc", ".docx", ".txt", ".md"}
    cases: list[GoldenCase] = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in supported_ext:
            continue
        case = parse_filename(path.stem)
        if case is None:
            continue
        case.file = str(path)
        cases.append(case)
    return cases
