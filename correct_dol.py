#!/usr/bin/env python3
"""Correct GCJ-02 contamination in 人生点点 (DoL) trajectory CSV exports.

Uses the same W2G/G2W switch detector as correct_tracks.py (including the
speed×dt kinematic veto), then drops lateral wild spikes.

    source .venv/bin/activate
    python correct_dol.py --input DoL_261017_7052pt.csv --output-dir output/
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Sequence

from lib.detect import fmt_cst
from lib.detect_dol import process_dol_track, summarize_runs
from lib.dol_io import load_dol_csv, write_dol_csv
from lib.report import build_report


def read_fieldnames(path: Path) -> List[str]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"Empty or invalid CSV: {path}")
        return list(reader.fieldnames)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="纠偏人生点点（DoL）导出中混入的 GCJ-02 点。"
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        type=Path,
        help="DoL 导出 CSV（含 timestamp 列）",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("output"),
        help="输出目录（默认 output/）",
    )
    args = parser.parse_args(argv)

    input_path: Path = args.input
    if not input_path.is_file():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    fieldnames = read_fieldnames(input_path)
    if "timestamp" not in fieldnames:
        print(
            "提示：未找到 timestamp 列。若为一生足迹导出，请改用 correct_tracks.py。",
            file=sys.stderr,
        )
        return 1

    print(f"Loading {input_path} ...")
    points = load_dol_csv(input_path)
    print(f"Loaded {len(points)} points")

    corrected, fixed, removed, runs, warns, summaries = process_dol_track(points)
    run_lines = summarize_runs(runs)
    warn_lines = [
        f"{fmt_cst(w.t)}  步进 {w.jump_m:.0f} m（期望约 {w.expect_m:.0f} m）— {w.note}"
        for w in warns
    ]

    stem = input_path.stem
    out_dir: Path = args.output_dir
    csv_path = out_dir / f"{stem}_corrected.csv"
    report_path = out_dir / f"{stem}_report.md"

    write_dol_csv(csv_path, [p.raw for p in corrected], fieldnames)
    report = build_report(
        input_path.name,
        len(points),
        len(corrected),
        fixed,
        len(removed),
        summaries,
        run_lines=run_lines,
        removed_indices=removed,
        warn_lines=warn_lines,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(f"Wrote {csv_path} ({len(corrected)} points)")
    print(f"Wrote {report_path}")
    print(f"Converted: {fixed}, removed: {len(removed)}")
    if runs:
        print(f"GCJ runs: {len(runs)}")
    if warns:
        print(f"Residual warn jumps: {len(warns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
