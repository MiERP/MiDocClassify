from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .log_utils import get_logger
from .manifest import build_manifest
from .pipeline import ScanOptions, sync_folder
from .storage import all_records


@dataclass
class SystemHealth:
    db_missing: bool = False
    source_missing: list[str] = field(default_factory=list)
    db_stale: list[str] = field(default_factory=list)
    wiki_missing: list[str] = field(default_factory=list)
    wiki_stale: list[str] = field(default_factory=list)
    orphan_wiki: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not (self.db_missing or self.source_missing or self.db_stale or self.wiki_missing or self.wiki_stale or self.orphan_wiki)


@dataclass
class RepairResult:
    changed: int = 0
    deleted: int = 0
    review_count: int = 0
    wiki_missing_repaired: int = 0
    wiki_stale_repaired: int = 0
    orphan_wiki_removed: int = 0
    errors: list[str] = field(default_factory=list)


def check_system(folder: Path, db_path: Path = Path("data/documents.sqlite"), wiki_root: Path = Path("data/wiki"), manifest_path: Path = Path("data/sync_manifest.csv"), **_: object) -> SystemHealth:
    health = SystemHealth()
    if not db_path.exists():
        health.db_missing = True
        build_manifest(folder, manifest_path, db_path, wiki_root)
        return health
    manifest = build_manifest(folder, manifest_path, db_path, wiki_root)
    for source_path, row in manifest.items():
        if not row.source_exists or row.status == "source_missing_record":
            health.source_missing.append(source_path)
        elif row.status == "missing_wiki":
            health.wiki_missing.append(source_path)
        elif row.status == "stale_wiki":
            health.wiki_stale.append(source_path)
    known_wiki_paths = {Path(row.wiki_path) for row in all_records(db_path) if row.wiki_path}
    if wiki_root.is_dir():
        for wiki_path in wiki_root.rglob("*.md"):
            if wiki_path.name in {"index.md", "log.md"}:
                continue
            if wiki_path not in known_wiki_paths:
                health.orphan_wiki.append(str(wiki_path))
    health.source_missing = list(dict.fromkeys(health.source_missing))
    health.wiki_missing = list(dict.fromkeys(health.wiki_missing))
    health.wiki_stale = list(dict.fromkeys(health.wiki_stale))
    health.orphan_wiki = list(dict.fromkeys(health.orphan_wiki))
    return health


def repair_system(folder: Path, db_path: Path = Path("data/documents.sqlite"), csv_path: Path | None = None, wiki_root: Path = Path("data/wiki"), progress_callback: Callable[..., None] | None = None, manifest_path: Path = Path("data/sync_manifest.csv"), options: ScanOptions | None = None, **_: object) -> RepairResult:
    log = get_logger()
    result = RepairResult()
    before = check_system(folder, db_path, wiki_root=wiki_root, manifest_path=manifest_path)
    if before.db_missing or before.source_missing or before.db_stale or before.wiki_missing or before.wiki_stale:
        log.info("sync: scan/OCR/wiki phase needed")
        options = options or ScanOptions(export_csv=csv_path)
        records, deleted = sync_folder(folder, db_path, wiki_root=wiki_root, progress_callback=progress_callback, options=options)
        result.changed = len(records)
        result.deleted = deleted
        result.review_count = sum(1 for record in records if record.needs_review)
        after = check_system(folder, db_path, wiki_root=wiki_root, manifest_path=manifest_path)
        result.wiki_missing_repaired = len(before.wiki_missing) - len(after.wiki_missing)
        result.wiki_stale_repaired = len(before.wiki_stale) - len(after.wiki_stale)
        before = after
    build_manifest(folder, manifest_path, db_path, wiki_root)
    for orphan in before.orphan_wiki:
        try:
            Path(orphan).unlink(missing_ok=True)
            result.orphan_wiki_removed += 1
        except OSError:
            pass
    return result
