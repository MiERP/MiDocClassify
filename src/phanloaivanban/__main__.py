from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import ScanOptions, scan_folder
from .sync import check_system, repair_system


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="phanloaivanban")
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("folder", type=Path)
    scan.add_argument("--db", type=Path, default=Path("data/documents.sqlite"))
    scan.add_argument("--export-csv", "--csv", dest="export_csv", type=Path, default=None)
    scan.add_argument("--build-wiki", "--build", dest="build_wiki", action=argparse.BooleanOptionalAction, default=True)
    scan.add_argument("--full-text", action="store_true")
    scan.add_argument("--ocr-pages", type=int, default=2)
    scan.add_argument("--workers", type=int, default=None)

    desktop = sub.add_parser("desktop")
    desktop.add_argument("--db", type=Path, default=Path("data/documents.sqlite"))

    sync_check = sub.add_parser("sync-check")
    sync_check.add_argument("folder", type=Path)
    sync_check.add_argument("--db", type=Path, default=Path("data/documents.sqlite"))
    sync_check.add_argument("--wiki-root", type=Path, default=None)
    sync_check.add_argument("--manifest", type=Path, default=None)

    sync_repair = sub.add_parser("sync-repair")
    sync_repair.add_argument("folder", type=Path)
    sync_repair.add_argument("--db", type=Path, default=Path("data/documents.sqlite"))
    sync_repair.add_argument("--export-csv", "--csv", dest="export_csv", type=Path, default=None)
    sync_repair.add_argument("--build-wiki", action=argparse.BooleanOptionalAction, default=True)
    sync_repair.add_argument("--full-text", action="store_true")
    sync_repair.add_argument("--ocr-pages", type=int, default=2)
    sync_repair.add_argument("--workers", type=int, default=None)
    sync_repair.add_argument("--wiki-root", type=Path, default=None)
    sync_repair.add_argument("--manifest", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.cmd == "scan":
        defaults = ScanOptions()
        options = ScanOptions(
            full_text=args.full_text,
            ocr_pages=args.ocr_pages,
            workers=args.workers or defaults.workers,
            build_wiki=args.build_wiki,
            export_csv=args.export_csv,
        )
        records = scan_folder(args.folder, args.db, options=options)
        print(f"scanned={len(records)} db={args.db}")
        return 0

    if args.cmd == "desktop":
        from .desktop import run

        return run(args.db)

    if args.cmd == "sync-check":
        db_path = args.db
        wiki_root = args.wiki_root or db_path.parent / "wiki"
        manifest = args.manifest or db_path.parent / "sync_manifest.csv"
        health = check_system(args.folder, db_path=db_path, wiki_root=wiki_root, manifest_path=manifest)
        for field, label in [
            ("db_missing", "DB missing"),
            ("source_missing", "Source files not in DB"),
            ("db_stale", "DB file_hash stale"),
            ("wiki_missing", "Wiki files missing"),
            ("wiki_stale", "Wiki file_hash stale"),
            ("orphan_wiki", "Orphan wiki files"),
        ]:
            items = getattr(health, field)
            if isinstance(items, bool):
                if items:
                    print(f"FAIL  {label}")
            elif items:
                print(f"FAIL  {label}: {len(items)}")
        if health.healthy:
            print("OK  System healthy")
            return 0
        return 1

    if args.cmd == "sync-repair":
        db_path = args.db
        wiki_root = args.wiki_root or db_path.parent / "wiki"
        manifest = args.manifest or db_path.parent / "sync_manifest.csv"
        defaults = ScanOptions()
        options = ScanOptions(
            full_text=args.full_text,
            ocr_pages=args.ocr_pages,
            workers=args.workers or defaults.workers,
            build_wiki=args.build_wiki,
            export_csv=args.export_csv,
        )
        result = repair_system(
            args.folder,
            db_path=db_path,
            wiki_root=wiki_root,
            manifest_path=manifest,
            options=options,
        )
        print(f"changed={result.changed} deleted={result.deleted} review_count={result.review_count}")
        print(f"wiki_repaired={result.wiki_missing_repaired + result.wiki_stale_repaired}")
        print(f"orphan_wiki_removed={result.orphan_wiki_removed}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
