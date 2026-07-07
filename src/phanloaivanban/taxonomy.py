from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_TAXONOMY: dict[str, Any] = {
    "document_types": {
        "luat": {"label": "Luật", "patterns": [r"\bLUẬT\b", r"\bQH\d+\b"]},
        "quyet_dinh": {"label": "Quyết định", "patterns": [r"\bQUYẾT\s+ĐỊNH\b", r"\bQĐ[-/]"]},
        "thong_tu": {"label": "Thông tư", "patterns": [r"\bTHÔNG\s+TƯ\b", r"\bTT[-/]"]},
        "nghi_dinh": {"label": "Nghị định", "patterns": [r"\bNGHỊ\s+ĐỊNH\b", r"\bNĐ[-/]"]},
        "nghi_quyet": {"label": "Nghị quyết", "patterns": [r"\bNGHỊ\s+QUYẾT\b", r"\bNQ[-/]"]},
        "cong_van": {"label": "Công văn", "patterns": [r"\bCÔNG\s+VĂN\b", r"\bCV[-/]"]},
        "huong_dan": {"label": "Hướng dẫn", "patterns": [r"\bHƯỚNG\s+DẪN\b"]},
        "ke_hoach": {"label": "Kế hoạch", "patterns": [r"\bKẾ\s+HOẠCH\b", r"\bKH[-/]"]},
        "chi_thi": {"label": "Chỉ thị", "patterns": [r"\bCHỈ\s+THỊ\b", r"\bCT[-/]"]},
    },
    "agency_markers": ["ỦY BAN NHÂN DÂN", "UBND", "BỘ ", "SỞ ", "CỤC ", "TỔNG CỤC", "HỘI ĐỒNG NHÂN DÂN"],
}


def load_taxonomy(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path("config/taxonomy.vi-law.yaml")
    if not path.exists():
        return DEFAULT_TAXONOMY
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return DEFAULT_TAXONOMY
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else DEFAULT_TAXONOMY


def classify_type(text: str, taxonomy: dict[str, Any]) -> str | None:
    head = "\n".join(text.splitlines()[:80]).upper()
    for spec in taxonomy.get("document_types", {}).values():
        for pattern in spec.get("patterns", []):
            if re.search(pattern, head, flags=re.IGNORECASE):
                return str(spec.get("label"))
    return None
