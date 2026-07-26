from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from pathlib import Path

from .extractors import sha256_file
from .file_utils import atomic_write, extract_frontmatter
from .pipeline import iter_documents
from .storage import all_records


@dataclass
class ManifestRow:
    source_path: str = ""
    source_exists: bool = False
    source_hash: str = ""
    source_mtime_ns: int = 0
    source_size: int = 0
    file_name: str = ""
    wiki_path: str = ""
    wiki_exists: bool = False
    wiki_hash: str = ""
    status: str = ""
    updated_at: str = ""


MANIFEST_FIELDS = [
    "source_path", "source_exists", "source_hash", "source_mtime_ns", "source_size",
    "file_name", "wiki_path", "wiki_exists", "wiki_hash", "status", "updated_at",
]


def _bool(val: str) -> bool:
    return val.lower() in ("1", "true", "yes")


def _manifest_read_path(path: Path) -> Path:
    latest = path.with_name(path.stem + ".latest" + path.suffix)
    if latest.exists() and path.exists() and latest.stat().st_mtime_ns > path.stat().st_mtime_ns:
        return latest
    return path


def load_manifest(path: Path) -> dict[str, ManifestRow]:
    read_path = _manifest_read_path(path)
    if not read_path.exists():
        return {}
    rows: dict[str, ManifestRow] = {}
    with read_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            item = ManifestRow(
                source_path=row.get("source_path", ""),
                source_exists=_bool(row.get("source_exists", "")),
                source_hash=row.get("source_hash", ""),
                source_mtime_ns=int(row.get("source_mtime_ns", "0") or "0"),
                source_size=int(row.get("source_size", "0") or "0"),
                file_name=row.get("file_name", ""),
                wiki_path=row.get("wiki_path", ""),
                wiki_exists=_bool(row.get("wiki_exists", "")),
                wiki_hash=row.get("wiki_hash", ""),
                status=row.get("status", ""),
                updated_at=row.get("updated_at", ""),
            )
            if item.source_path:
                rows[item.source_path] = item
    return rows


def _serialise_manifest(rows: dict[str, ManifestRow]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=MANIFEST_FIELDS)
    writer.writeheader()
    for row in rows.values():
        writer.writerow({
            "source_path": row.source_path,
            "source_exists": "1" if row.source_exists else "0",
            "source_hash": row.source_hash,
            "source_mtime_ns": str(row.source_mtime_ns),
            "source_size": str(row.source_size),
            "file_name": row.file_name,
            "wiki_path": row.wiki_path,
            "wiki_exists": "1" if row.wiki_exists else "0",
            "wiki_hash": row.wiki_hash,
            "status": row.status,
            "updated_at": row.updated_at,
        })
    return buf.getvalue()


def write_manifest(path: Path, rows: dict[str, ManifestRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    csv_content = _serialise_manifest(rows)
    try:
        atomic_write(path, csv_content)
    except PermissionError:
        atomic_write(path.with_name(path.stem + ".latest" + path.suffix), csv_content)


def scan_sources(folder: Path, manifest: dict[str, ManifestRow]) -> dict[str, ManifestRow]:
    now = str(int(time.time()))
    out: dict[str, ManifestRow] = {}
    current = {str(path): path for path in iter_documents(folder)}
    for source_path, path in current.items():
        existing = manifest.get(source_path)
        try:
            stat = path.stat()
            mtime = stat.st_mtime_ns
            size = stat.st_size
        except OSError:
            mtime = 0
            size = 0
        source_hash = existing.source_hash if existing and existing.source_mtime_ns == mtime and existing.source_size == size and existing.source_hash else sha256_file(path)
        out[source_path] = ManifestRow(source_path=source_path, source_exists=True, source_hash=source_hash, source_mtime_ns=mtime, source_size=size, file_name=path.name, updated_at=now)
    for source_path, row in manifest.items():
        if source_path not in current:
            out[source_path] = ManifestRow(source_path=source_path, source_exists=False, source_hash=row.source_hash, source_mtime_ns=row.source_mtime_ns, source_size=row.source_size, file_name=row.file_name, wiki_path=row.wiki_path, wiki_exists=row.wiki_exists, wiki_hash=row.wiki_hash, status="deleted_source", updated_at=now)
    return out


def refresh_artifacts(rows: dict[str, ManifestRow], records: list, _wiki_root: Path) -> dict[str, ManifestRow]:
    now = str(int(time.time()))
    record_by_path = {str(record.original_path): record for record in records}
    for source_path, row in rows.items():
        if not row.source_exists and row.status == "deleted_source":
            row.updated_at = now
            continue
        record = record_by_path.get(source_path)
        if record is None:
            row.status = "source_missing_record"
            row.updated_at = now
            continue
        row.wiki_path = getattr(record, "wiki_path", None) or ""
        wiki_path = Path(row.wiki_path) if row.wiki_path else None
        row.wiki_exists = bool(wiki_path and wiki_path.exists())
        row.wiki_hash = ""
        if row.wiki_exists and wiki_path is not None:
            try:
                row.wiki_hash = extract_frontmatter(wiki_path.read_text("utf-8", errors="replace")).get("file_hash", "")
            except OSError:
                row.wiki_hash = ""
        if not row.wiki_exists:
            row.status = "missing_wiki"
        elif row.wiki_hash and row.wiki_hash != row.source_hash:
            row.status = "stale_wiki"
        elif getattr(record, "needs_review", False):
            row.status = "needs_review"
        else:
            row.status = "ready"
        row.updated_at = now
    return rows


def build_manifest(folder: Path, manifest_path: Path, db_path: Path, wiki_root: Path, **_: object) -> dict[str, ManifestRow]:
    rows = scan_sources(folder, load_manifest(manifest_path))
    if db_path.exists():
        rows = refresh_artifacts(rows, all_records(db_path), wiki_root)
    write_manifest(manifest_path, rows)
    return rows
