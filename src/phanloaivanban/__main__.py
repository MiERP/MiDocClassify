from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import scan_folder


def main() -> int:
    parser = argparse.ArgumentParser(prog="phanloaivanban")
    sub = parser.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("folder", type=Path)
    scan.add_argument("--db", type=Path, default=Path("data/documents.sqlite"))
    scan.add_argument("--csv", type=Path, default=Path("output/export.csv"))
    ui = sub.add_parser("desktop")
    ui.add_argument("--db", type=Path, default=Path("data/documents.sqlite"))
    args = parser.parse_args()
    if args.cmd == "scan":
        records = scan_folder(args.folder, args.db, args.csv)
        print(f"scanned={len(records)} db={args.db} csv={args.csv}")
        return 0
    if args.cmd == "desktop":
        from .desktop import run

        return run(args.db)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
