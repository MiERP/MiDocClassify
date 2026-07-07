from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx", ".doc", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
EQUIVALENT_EXTENSIONS = (".docx", ".pdf", ".txt", ".md")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_text(path: Path, runtime_dir: Path = Path("runtime")) -> tuple[str, str, str | None]:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore"), "ok", None
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".pdf":
        return _extract_pdf(path, runtime_dir)
    if suffix == ".doc":
        return _extract_doc(path, runtime_dir)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return _extract_image(path, runtime_dir)
    return "", f"unsupported extension {suffix}", None


def _extract_docx(path: Path) -> tuple[str, str, str | None]:
    try:
        import docx  # type: ignore[import-not-found]
        from docx.table import Table  # type: ignore[import-not-found]
        from docx.text.paragraph import Paragraph  # type: ignore[import-not-found]
    except ImportError:
        return "", "python-docx not bundled", None
    document = docx.Document(str(path))
    lines: list[str] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            text = Paragraph(child, document).text
            if text.strip():
                lines.append(text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        if paragraph.text.strip():
                            lines.append(paragraph.text)
    return "\n".join(lines), "ok", None

def _extract_pdf(path: Path, runtime_dir: Path = Path("runtime")) -> tuple[str, str, str | None]:
    try:
        import pypdfium2 as pdfium  # type: ignore[import-not-found]
    except ImportError:
        return "", "pypdfium2 not bundled; scanned/text PDF needs parser", None
    pdf = pdfium.PdfDocument(str(path))
    page_count = min(len(pdf), 3)
    pages = []
    for index in range(page_count):
        text_page = pdf[index].get_textpage()
        pages.append(text_page.get_text_range())
    text = "\n".join(pages).strip()
    if text:
        return text, "ok", None
    return _extract_rendered_pdf_pages(pdf, page_count, runtime_dir)


def _extract_rendered_pdf_pages(pdf, page_count: int, runtime_dir: Path) -> tuple[str, str, str | None]:
    ocr_text: list[str] = []
    last_status = "pdf has no text; bundled OCR required"
    ocr_engine: str | None = None
    with tempfile.TemporaryDirectory(prefix="phanloaivanban-pdf-ocr-") as temp_dir:
        output_dir = Path(temp_dir)
        for index in range(page_count):
            image_path = output_dir / f"page-{index + 1}.png"
            pdf[index].render(scale=2).to_pil().save(image_path)
            page_text, status, page_engine = _extract_image(image_path, runtime_dir)
            ocr_engine = page_engine or ocr_engine
            if status != "ok":
                last_status = status
                continue
            if page_text.strip():
                ocr_text.append(page_text.strip())
        text = "\n".join(ocr_text).strip()
        if text:
            return text, "ok", ocr_engine
    return "", last_status, ocr_engine


def _extract_image(path: Path, runtime_dir: Path) -> tuple[str, str, str | None]:
    tesseract = runtime_dir / "tesseract" / "tesseract.exe"
    if not tesseract.exists():
        return "", "bundled Tesseract not found at runtime/tesseract/tesseract.exe", "tesseract"
    traineddata = runtime_dir / "tesseract" / "tessdata" / "vie.traineddata"
    if not traineddata.exists():
        return "", "bundled Tesseract Vietnamese traineddata not found at runtime/tesseract/tessdata/vie.traineddata", "tesseract"
    result = subprocess.run(
        [str(tesseract), str(path), "stdout", "-l", "vie", "--psm", "6"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        return "", result.stderr.strip() or "Tesseract OCR failed", "tesseract"
    return result.stdout, "ok", "tesseract"


def _extract_doc(path: Path, runtime_dir: Path) -> tuple[str, str, str | None]:
    soffice = runtime_dir / "libreoffice" / "program" / "soffice.exe"
    if not soffice.exists():
        equivalent = find_equivalent_document(path)
        if equivalent is not None:
            text, status, _ = extract_text(equivalent, runtime_dir)
            if text.strip() and status == "ok":
                return text, "ok", f"equivalent:{equivalent.name}"
        return "", "missing_libreoffice", None
    with tempfile.TemporaryDirectory(prefix="phanloaivanban-doc-") as temp_dir:
        output_dir = Path(temp_dir)
        result = subprocess.run(
            [str(soffice), "--headless", "--convert-to", "docx", "--outdir", str(output_dir), str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        converted = output_dir / f"{path.stem}.docx"
        if result.returncode != 0 or not converted.exists():
            equivalent = find_equivalent_document(path)
            if equivalent is not None:
                text, status, _ = extract_text(equivalent, runtime_dir)
                if text.strip() and status == "ok":
                    return text, "ok", f"equivalent:{equivalent.name}"
            return "", result.stderr.strip() or "DOC conversion failed", None
        return _extract_docx(converted)


def document_key_from_name(file_name: str) -> str | None:
    import re

    match = re.search(r"(\d{1,4})[_-](\d{4})[_-](QH\d+)", file_name, flags=re.IGNORECASE)
    if not match:
        return None
    number, year, term = match.groups()
    return f"{int(number):02d}_{year}_{term.upper()}"


def find_equivalent_document(path: Path) -> Path | None:
    candidates = find_equivalent_documents(path)
    return candidates[0] if candidates else None


def find_equivalent_documents(path: Path) -> list[Path]:
    key = document_key_from_name(path.name)
    if key is None:
        return []
    search_roots = [path.parent]
    if path.parent.parent not in search_roots:
        search_roots.append(path.parent.parent)
    candidates: list[Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for candidate in root.iterdir():
            if not candidate.is_file() or candidate == path:
                continue
            if candidate.suffix.lower() not in EQUIVALENT_EXTENSIONS:
                continue
            if document_key_from_name(candidate.name) == key:
                candidates.append(candidate)
    return sorted(candidates, key=lambda item: EQUIVALENT_EXTENSIONS.index(item.suffix.lower()))
