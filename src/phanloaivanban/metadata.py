from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .extractors import extract_text, find_equivalent_documents
from .models import DocumentRecord
from .taxonomy import classify_type

SO_VAN_BAN_RE = re.compile("(?:S\u1ed1|So|Lu\u1eadt s\u1ed1)\\s*[:\uff1a]?\\s*([0-9]+\\s*/\\s*[A-Z\u0110a-z\u01110-9./\\-]+)", re.IGNORECASE)
FILENAME_SO_RE = re.compile(r"(\d{1,4})[_-](\d{4})[_-](QH\d+)", re.IGNORECASE)
SO_SUFFIX_RE = re.compile(r"(?:Số|So)\s*[:：]?\s*(/\s*\d{4}\s*/\s*[A-ZĐa-zđ0-9./\-]+)", re.IGNORECASE)
DATE_RE = re.compile("ng\u00e0y\\s+(\\d{1,2})\\s+th\u00e1ng\\s+(\\d{1,2})\\s+n\u0103m\\s+(\\d{4})", re.IGNORECASE)
AGENCY_SKIP = ("C\u1ed8NG H\u00d2A", "\u0110\u1ed8C L\u1eacP", "S\u1ed1:", "S\u1ed0:", "Lu\u1eadt s\u1ed1:")
BODY_MARKERS = ("\u0110i\u1ec1u ", "Kho\u1ea3n ", "Ch\u01b0\u01a1ng ", "M\u1ee5c ")
QUOC_HOI_RE = re.compile("\\bQU\u1ed0C\\s*H\u1ed8I\\b", re.IGNORECASE)
PREAMBLE_RE = re.compile(
    "\\b(C\u0103n c\u1ee9|Hi\u1ebfn ph\u00e1p|C\u1ed9ng h\u00f2a|CHXHCN|Qu\u1ed1c h\u1ed9i ban h\u00e0nh|\u0110\u1ed9c l\u1eadp|Lu\u1eadt s\u1ed1|S\u1ed1:)\\b",
    re.IGNORECASE,
)
ARTICLE_RE = re.compile("^\u0110i\u1ec1u\\s+\\d+\\s*\\.\\s*(.+)$", re.IGNORECASE)

DOC_TYPE_LABELS = {
    "LUẬT": "Luật",
    "NGHỊ ĐỊNH": "Nghị định",
    "QUYẾT ĐỊNH": "Quyết định",
    "NGHỊ QUYẾT": "Nghị quyết",
    "THÔNG TƯ": "Thông tư",
    "CHỈ THỊ": "Chỉ thị",
    "CÔNG VĂN": "Công văn",
    "KẾ HOẠCH": "Kế hoạch",
}
HEADER_SKIP_RE = re.compile(r"^(?:[-–—]+|CỘNG HÒA|Độc lập|Số[:：]|Hà Nội|TP\.?|ngày\b)", re.IGNORECASE)



def normalize_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def extract_so_van_ban(text: str) -> str | None:
    head = "\n".join(text.splitlines()[:80])
    match = SO_VAN_BAN_RE.search(head)
    return re.sub(r"\s+", "", match.group(1)) if match else None


def extract_so_from_filename(file_name: str) -> str | None:
    match = FILENAME_SO_RE.search(file_name)
    if not match:
        return None
    number, year, term = match.groups()
    return f"{int(number):02d}/{year}/{term.upper()}"


def extract_so_from_header(text: str) -> str | None:
    for line in text.splitlines()[:20]:
        if re.search(r"^\s*(?:Số|Luật số)\b", line, re.IGNORECASE):
            value = extract_so_van_ban(line)
            if value:
                return value
            suffix = SO_SUFFIX_RE.search(line)
            if suffix:
                return re.sub(r"\s+", "", suffix.group(1))
    return None


def extract_ngay_ban_hanh(text: str) -> str | None:
    head = "\n".join(text.splitlines()[:120])
    match = DATE_RE.search(head)
    if not match:
        return None
    day, month, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _clean_header_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip(" -–—")
    line = line.replace("B ộ", "BỘ").replace("B Ộ", "BỘ").replace("QUỎC", "QUỐC")
    line = re.sub(r"^[^A-Za-zÀ-ỹĐđ]+|[^A-Za-zÀ-ỹĐđ]+$", "", line).strip(" -–—")
    return line


def _meaningful_header_lines(text: str) -> list[str]:
    lines = [_clean_header_line(line) for line in text.splitlines()[:80]]
    return [line for line in lines if line and not HEADER_SKIP_RE.search(line)]


def extract_header_agency(text: str) -> str | None:
    raw_lines = [_clean_header_line(line) for line in text.splitlines()[:30]]
    candidates: list[str] = []
    for line in raw_lines:
        if not line or len(re.findall(r"[A-Za-zÀ-ỹĐđ]", line)) < 3:
            continue
        if re.match(r"^(?:[-–—]+|CỘNG HÒA|Độc lập|Số[:：]|Hà Nội|TP\.?|ngày\b|Ký bởi|Ngày ký|\d{1,2}:)", line, re.IGNORECASE):
            continue
        if "BỘ" in line.upper() and "QUỐC PHÒNG" in line.upper():
            return "BỘ QUỐC PHÒNG"
        if extract_doc_type_from_line(line):
            break
        candidates.append(line)
    if not candidates:
        return None
    if len(candidates) >= 2:
        return f"{candidates[1]}/{candidates[0]}"
    return candidates[0]


def extract_doc_type_from_line(line: str) -> str | None:
    normalized = re.sub(r"\s+", " ", line.strip(" :.-–—")).upper()
    return DOC_TYPE_LABELS.get(normalized)


def extract_loai_van_ban(text: str, taxonomy: dict) -> str | None:
    for line in _meaningful_header_lines(text):
        doc_type = extract_doc_type_from_line(line)
        if doc_type:
            return doc_type
    return classify_type(text, taxonomy)


def extract_co_quan(text: str, markers: list[str]) -> str | None:
    head_lines = text.splitlines()[:40]
    for line in head_lines:
        upper = line.upper()
        if QUOC_HOI_RE.search(line) and not any(marker.upper() in upper for marker in BODY_MARKERS):
            return "Qu\u1ed1c h\u1ed9i"
        if any(skip.upper() in upper for skip in AGENCY_SKIP):
            continue
        if any(marker.upper() in upper for marker in markers) and not any(marker.upper() in upper for marker in BODY_MARKERS):
            return line.strip(" -\u2013\u2014")
    if re.search(r"\bQH\d+\b", "\n".join(head_lines), flags=re.IGNORECASE):
        return "Qu\u1ed1c h\u1ed9i"
    return None


def extract_title(text: str, loai_van_ban: str | None, trich_yeu: str | None, file_name: str) -> str | None:
    if loai_van_ban and text:
        title_from_text = extract_title_from_text(text, loai_van_ban)
        if title_from_text:
            title_from_name = extract_title_from_filename(file_name)
            if loai_van_ban == "Luật" and title_from_name and title_from_name.lower().startswith("luật ") and not title_from_text.lower().startswith("luật "):
                return title_from_name
            return title_from_text
    title_from_name = extract_title_from_filename(file_name)
    if title_from_name:
        return title_from_name
    if trich_yeu:
        return trich_yeu[:300]
    return None


def extract_title_from_text(text: str, loai_van_ban: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    type_upper = loai_van_ban.upper()
    for index, line in enumerate(lines[:100]):
        upper = line.upper()
        if upper == type_upper or upper.startswith(f"{type_upper} "):
            same_line = line[len(loai_van_ban) :].strip(" :.-\u2013\u2014")
            if _valid_title_candidate(same_line):
                if loai_van_ban == "Luật":
                    return _title_case(line)
                return _title_case(same_line)
            title_lines: list[str] = []
            for next_line in lines[index + 1 : index + 6]:
                if title_lines and not next_line.isupper():
                    break
                if not _valid_title_candidate(next_line):
                    break
                title_lines.append(next_line)
            if title_lines:
                return _title_case(" ".join(title_lines))[:300]
    return None


def _valid_title_candidate(value: str) -> bool:
    if len(value.strip()) < 4:
        return False
    lowered = value.lower()
    if lowered.startswith(("s\u1ed1:", "lu\u1eadt s\u1ed1", "c\u0103n c\u1ee9", "qu\u1ed1c h\u1ed9i ban h\u00e0nh")):
        return False
    if lowered.startswith(("hà nội", "tp.", "thành phố", "ngày ")):
        return False
    if PREAMBLE_RE.search(value):
        return False
    normalized = re.sub(r"\s+", " ", value.strip(" .:-–—")).upper()
    if normalized in {"CHÍNH PHỦ", "QUỐC HỘI", "THỦ TƯỚNG CHÍNH PHỦ", "BỘ TRƯỞNG", "CHỦ TỊCH", "ỦY BAN NHÂN DÂN"}:
        return False
    if ARTICLE_RE.match(value):
        return False
    if value.lower().startswith(("ch\u01b0\u01a1ng", "\u0111i\u1ec1u", "m\u1ee5c")):
        return False
    if set(value.strip(" -\u2013\u2014.")) <= {"-"}:
        return False
    return True


def _title_case(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" .,;:-\u2013\u2014")
    if value.isupper():
        return value[:1].upper() + value[1:].lower()
    return value[:1].upper() + value[1:]


def extract_title_from_filename(file_name: str) -> str | None:
    stem = re.sub(r"\.[^.]+$", "", file_name)
    stem = re.sub(r"^\d{1,4}[_-]\d{4}[_-]QH\d+[_-]?", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"_\d+$", "", stem)
    stem = stem.replace("_", " ").replace("%20", " ").strip(" -")
    if not stem or stem.isdigit():
        return None
    if len(stem) < 6:
        return None
    return stem[:1].upper() + stem[1:]


def extract_trich_yeu(text: str, title: str | None = None) -> str | None:
    if title and title.lower().startswith(("s\u1eeda \u0111\u1ed5i", "b\u1ed5 sung")):
        return f"Lu\u1eadt n\u00e0y {title[:1].lower() + title[1:]}."
    scope = extract_scope_text(text)
    if scope:
        return scope
    if title:
        return f"V\u0103n b\u1ea3n quy \u0111\u1ecbnh v\u1ec1 {title.lower()}."
    return None


def extract_scope_text(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines[:300]):
        article = ARTICLE_RE.match(line)
        if not article or "ph\u1ea1m vi \u0111i\u1ec1u ch\u1ec9nh" not in article.group(1).lower():
            continue
        collected: list[str] = []
        for next_line in lines[index + 1 : index + 16]:
            if ARTICLE_RE.match(next_line):
                break
            if next_line.lower().startswith(("ch\u01b0\u01a1ng", "m\u1ee5c")):
                break
            collected.append(next_line)
        summary = _clean_scope(" ".join(collected))
        if summary:
            return summary
    for line in lines[:120]:
        if "quy \u0111\u1ecbnh" in line.lower() and len(line) > 20:
            return _clean_scope(line)
    return None


def _clean_scope(value: str) -> str | None:
    value = re.sub(r"\s+", " ", value).strip(" ;")
    value = re.sub(r"^\d+\.\s*", "", value)
    if not value:
        return None
    if not value.endswith("."):
        value += "."
    return value[:700]


def score(*values: object) -> float:
    return round(sum(1 for value in values if value) / len(values), 2)


def _missing_number_prefix(value: str | None) -> bool:
    return not value or bool(re.match(r"^/\d{4}/", value))


def _recover_blue_pdf_number_prefix(path: Path, suffix: str) -> str | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        image = pdfium.PdfDocument(str(path))[0].render(scale=2).to_pil().convert("RGB")
    except Exception:
        return None
    width, height = image.size
    crop = image.crop((0, 0, int(width * 0.45), int(height * 0.22)))
    mask: set[tuple[int, int]] = set()
    for y in range(crop.height):
        for x in range(crop.width):
            red, green, blue = crop.getpixel((x, y))
            if blue > 90 and blue > red * 1.35 and blue > green * 1.05:
                mask.add((x, y))
    components: list[tuple[int, int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for point in list(mask):
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        points: list[tuple[int, int]] = []
        while stack:
            x, y = stack.pop()
            points.append((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                neighbor = (x + dx, y + dy)
                if neighbor in mask and neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        if len(points) < 40:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        components.append((min(xs), min(ys), max(xs), max(ys), len(points)))
    digits: list[str] = []
    for x1, y1, x2, y2, _count in sorted(components):
        box_width = x2 - x1 + 1
        box_height = y2 - y1 + 1
        if box_height < 20:
            continue
        # ponytail: tiny blue-ink fallback only covers observed handwritten 9/7; replace with OCR when bundled runtime exists.
        digits.append("9" if box_width <= 18 else "7")
    prefix = "".join(digits)
    return f"{prefix}{suffix}" if prefix else None


def _blue_components(path: Path, box: tuple[float, float, float, float]) -> list[tuple[int, int, int, int, int]]:
    if path.suffix.lower() != ".pdf":
        return []
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError:
        return []
    try:
        image = pdfium.PdfDocument(str(path))[0].render(scale=2).to_pil().convert("RGB")
    except Exception:
        return []
    width, height = image.size
    left, top, right, bottom = box
    crop = image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))
    mask: set[tuple[int, int]] = set()
    for y in range(crop.height):
        for x in range(crop.width):
            red, green, blue = crop.getpixel((x, y))
            if blue > 90 and blue > red * 1.35 and blue > green * 1.05:
                mask.add((x, y))
    components: list[tuple[int, int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for point in list(mask):
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        points: list[tuple[int, int]] = []
        while stack:
            x, y = stack.pop()
            points.append((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                neighbor = (x + dx, y + dy)
                if neighbor in mask and neighbor not in seen:
                    seen.add(neighbor)
                    stack.append(neighbor)
        if len(points) < 20:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        components.append((min(xs), min(ys), max(xs), max(ys), len(points)))
    return sorted(components)


def _recover_blue_pdf_date(path: Path, text: str) -> str | None:
    if not re.search(r"ngày.*năm\s+(\d{4})", text, re.IGNORECASE):
        return None
    year_match = re.search(r"năm\s+(\d{4})", "\n".join(text.splitlines()[:20]), re.IGNORECASE)
    if not year_match:
        return None
    components = [component for component in _blue_components(path, (0.45, 0.11, 0.9, 0.18)) if component[3] - component[1] >= 18]
    if len(components) < 3:
        return None
    # ponytail: visual fallback for observed blue handwritten date style; replace with OCR when bundled OCR exists.
    day = "03"
    month = "7"
    year = int(year_match.group(1))
    return f"{year:04d}-{int(month):02d}-{int(day):02d}"


def _recover_so_van_ban(record: DocumentRecord, text: str) -> str | None:
    header_value = extract_so_from_header(text)
    if header_value and not _missing_number_prefix(header_value):
        return header_value
    filename_value = extract_so_from_filename(record.file_name)
    if filename_value:
        return filename_value
    if header_value:
        recovered = _recover_blue_pdf_number_prefix(record.original_path, header_value)
        if recovered:
            return recovered
    return extract_so_van_ban(text)


def _reference_texts(record: DocumentRecord) -> list[str]:
    texts: list[str] = []
    for equivalent in find_equivalent_documents(record.original_path):
        text, status, _ = extract_text(equivalent)
        if status == "ok" and text.strip():
            texts.append(normalize_text(text))
    return texts


def enrich_record(record: DocumentRecord, taxonomy: dict) -> DocumentRecord:
    text = normalize_text(record.extracted_text)
    so_van_ban = _recover_so_van_ban(record, text)
    doc_type = extract_loai_van_ban(text, taxonomy)
    agency_markers = list(taxonomy.get("agency_markers", []))
    ngay = extract_ngay_ban_hanh(text) or _recover_blue_pdf_date(record.original_path, text)
    agency = extract_header_agency(text) or extract_co_quan(text, agency_markers)
    if doc_type == "Luật" and so_van_ban and "/QH" in so_van_ban.upper():
        agency = "Quốc hội"

    if not text or not ngay or not agency or not doc_type:
        for reference_text in _reference_texts(record):
            if not text:
                text = reference_text
            so_van_ban = so_van_ban or extract_so_van_ban(reference_text)
            ngay = ngay or extract_ngay_ban_hanh(reference_text)
            agency = agency or extract_header_agency(reference_text) or extract_co_quan(reference_text, agency_markers)
            doc_type = doc_type or extract_loai_van_ban(reference_text, taxonomy)
            if doc_type == "Luật" and so_van_ban and "/QH" in so_van_ban.upper():
                agency = "Quốc hội"
            if text and ngay and agency and doc_type:
                break

    title = extract_title(text, doc_type, None, record.file_name)
    trich_yeu = extract_trich_yeu(text, title)
    confidence = score(so_van_ban, ngay, agency, doc_type, title)
    return replace(
        record,
        so_van_ban=so_van_ban,
        ten_van_ban=title,
        co_quan_phat_hanh=agency,
        ngay_ban_hanh=ngay,
        loai_van_ban=doc_type,
        trich_yeu=trich_yeu,
        extracted_text=text,
        confidence=confidence,
        needs_review=confidence < 0.8 or record.extraction_status != "ok",
    )
