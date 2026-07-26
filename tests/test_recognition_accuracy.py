"""Recognition accuracy baseline for the classification engine.

Runs ``enrich_record`` over the golden set in ``data-template/5`` (whose
filenames encode ground-truth so/loai/co_quan/year) and reports per-field
accuracy plus a confusion matrix for ``loai_van_ban``.

This is STEP 0.2 of the accuracy-hardening plan: measure first, fix later.
It does NOT modify any recognition logic.

Run:  pytest tests/test_recognition_accuracy.py -q   (requires [dev] extras)
Report: output/accuracy/report.md  +  output/accuracy/report.json
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

from phanloaivanban.extractors import extract_text
from phanloaivanban.metadata import enrich_record
from phanloaivanban.models import DocumentRecord
from phanloaivanban.taxonomy import load_taxonomy

from golden_cases import build_golden_cases, norm_ascii

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = PROJECT_ROOT / "data-template" / "5"
REPORT_DIR = PROJECT_ROOT / "output" / "accuracy"
REPORT_MD = REPORT_DIR / "report.md"
REPORT_JSON = REPORT_DIR / "report.json"

# Acceptance gates protect the measured baseline for data-template/5.
ACCEPTANCE_MIN_SO = 0.98
ACCEPTANCE_MIN_LOAI = 0.98


def _record_with_text(path: Path, text: str, status: str) -> DocumentRecord:
    return DocumentRecord(
        original_path=path,
        file_name=path.name,
        file_hash="",
        extracted_text=text,
        extraction_status=status,
    )


def _render_md(metrics: dict, rows: list[dict]) -> str:
    lines = [
        "# Recognition Accuracy Baseline",
        "",
        f"- n = {metrics['n']}",
        f"- so_van_ban accuracy = {metrics['so_accuracy']}",
        f"- loai_van_ban accuracy = {metrics['loai_accuracy']}",
        f"- co_quan accuracy = {metrics['coquan_accuracy']}",
        f"- year accuracy = {metrics['year_accuracy']}",
        "",
        "## loai_van_ban confusion matrix (rows=expected, cols=predicted)",
        "",
    ]
    labels: list[str] = sorted(
        {e for e in metrics["confusion_loai"]}
        | {p for d in metrics["confusion_loai"].values() for p in d}
    )
    lines.append("| expected \\ predicted | " + " | ".join(labels) + " |")
    lines.append("|" + "---|" * (len(labels) + 1))
    for exp in labels:
        row = metrics["confusion_loai"].get(exp, {})
        cells = " | ".join(str(row.get(l, 0)) for l in labels)
        lines.append(f"| {exp} | {cells} |")
    lines += [
        "",
        "## Per-file detail",
        "",
        "| file | status | conf | review | exp_so | pred_so | so | "
        "exp_loai | pred_loai | loai | exp_coquan | pred_coquan | co | year |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['file']} | {r['status']} | {r['confidence']} | {r['needs_review']} | "
            f"{r['exp_so']} | {r['pred_so']} | {r['so_ok']} | "
            f"{r['exp_loai']} | {r['pred_loai']} | {r['loai_ok']} | "
            f"{r['exp_coquan']} | {r['pred_coquan']} | {r['coquan_ok']} | {r['year_ok']} |"
        )
    return "\n".join(lines) + "\n"


def test_recognition_accuracy_baseline() -> None:
    if not GOLDEN_DIR.exists():
        pytest.skip("golden fixture directory is not present")
    taxonomy = load_taxonomy()
    cases = build_golden_cases(GOLDEN_DIR)
    found_files = sorted(p.name for p in GOLDEN_DIR.iterdir()) if GOLDEN_DIR.exists() else []
    assert cases, f"No golden cases parsed from {GOLDEN_DIR} (found {len(found_files)} files: {found_files})"

    rows: list[dict] = []
    so_hit = loai_hit = year_hit = 0
    year_den = 0
    coquan_hit = coquan_den = 0
    confusion: dict[str, dict[str, int]] = {}

    for gc in cases:
        path = Path(gc.file)
        text, status, _ = extract_text(path)
        rec = enrich_record(_record_with_text(path, text, status), taxonomy)

        pred_so = rec.so_van_ban
        pred_loai = rec.loai_van_ban
        pred_coquan = rec.co_quan_phat_hanh
        pred_year = (rec.ngay_ban_hanh or "")[:4]

        so_ok = (norm_ascii(pred_so) == norm_ascii(gc.expected_so)) if gc.expected_so else None
        loai_ok = (norm_ascii(pred_loai) == norm_ascii(gc.expected_loai)) if gc.expected_loai else None
        coquan_ok: bool | None = None
        if gc.expected_co_quan is not None:
            coquan_den += 1
            coquan_ok = bool(pred_coquan) and (norm_ascii(gc.expected_co_quan) in norm_ascii(pred_coquan))
            coquan_hit += bool(coquan_ok)
        year_ok = None
        if gc.expected_year is not None:
            year_den += 1
            year_ok = pred_year == gc.expected_year
            year_hit += bool(year_ok)

        so_hit += bool(so_ok)
        loai_hit += bool(loai_ok)

        exp = gc.expected_loai or "<exp?>"
        confusion.setdefault(exp, {})
        confusion[exp][pred_loai or "<none>"] = confusion[exp].get(pred_loai or "<none>", 0) + 1

        rows.append({
            "file": path.name, "status": status,
            "confidence": round(rec.confidence, 3), "needs_review": rec.needs_review,
            "exp_so": gc.expected_so, "pred_so": pred_so, "so_ok": so_ok,
            "exp_loai": gc.expected_loai, "pred_loai": pred_loai, "loai_ok": loai_ok,
            "exp_coquan": gc.expected_co_quan, "pred_coquan": pred_coquan, "coquan_ok": coquan_ok,
            "exp_year": gc.expected_year, "pred_year": pred_year or "", "year_ok": year_ok,
        })

    n = len(cases)
    metrics = {
        "n": n,
        "so_accuracy": round(so_hit / n, 4),
        "loai_accuracy": round(loai_hit / n, 4),
        "coquan_accuracy": round(coquan_hit / coquan_den, 4) if coquan_den else None,
        "year_accuracy": round(year_hit / year_den, 4) if year_den else None,
        "confusion_loai": confusion,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(
        json.dumps({"metrics": metrics, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    REPORT_MD.write_text(_render_md(metrics, rows), encoding="utf-8")

    print("\n=== RECOGNITION BASELINE (data-template/5) ===")
    print(
        f"n={n}  so={metrics['so_accuracy']}  loai={metrics['loai_accuracy']}  "
        f"coquan={metrics['coquan_accuracy']}  year={metrics['year_accuracy']}"
    )
    print(f"Report: {REPORT_MD}")

    assert metrics["so_accuracy"] >= ACCEPTANCE_MIN_SO, metrics
    assert metrics["loai_accuracy"] >= ACCEPTANCE_MIN_LOAI, metrics
