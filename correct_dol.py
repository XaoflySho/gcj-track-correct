#!/usr/bin/env python3
"""Correct GCJ-02 contamination in 人生点点 (DoL) trajectory CSV exports.

Assumes the bulk of points are WGS-84. Uses kinematic speed×dt continuity to
label GCJ blocks (not the 一生足迹 switch detector).

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


def read_fieldnames(path: Path) -> List[str]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"Empty or invalid CSV: {path}")
        return list(reader.fieldnames)


def build_report(
    input_name: str,
    total_in: int,
    total_out: int,
    fixed: int,
    removed: Sequence[int],
    run_lines: Sequence[str],
    warn_lines: Sequence[str],
) -> str:
    lines = [
        "# 人生点点（DoL）轨迹纠偏报告",
        "",
        f"- 输入文件：`{input_name}`",
        f"- 输入点数：**{total_in}**",
        f"- 输出点数：**{total_out}**",
        f"- GCJ→WGS 转换点数：**{fixed}**",
        f"- 侧向野点删除：**{len(removed)}**",
        "",
        "## GCJ 块（已转换）",
        "",
    ]
    if not run_lines:
        lines.append("_未检测到 GCJ 污染。_")
    else:
        for line in run_lines:
            lines.append(f"- {line}")

    lines.extend(["", "## 删除的野点", ""])
    if not removed:
        lines.append("_无。_")
    else:
        for idx in removed:
            lines.append(f"- 原始行号约 {idx + 2}（0-based index {idx}）")

    lines.extend(["", "## 残留警告跳变", ""])
    if not warn_lines:
        lines.append("_无。_")
    else:
        for line in warn_lines:
            lines.append(f"- {line}")

    lines.append("")
    return "\n".join(lines)


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

    corrected, fixed, removed, runs, warns = process_dol_track(points)
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
        removed,
        run_lines,
        warn_lines,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(f"Wrote {csv_path} ({len(corrected)} points)")
    print(f"Wrote {report_path}")
    print(f"Converted: {fixed}, removed lateral spikes: {len(removed)}")
    if runs:
        print(f"GCJ runs: {len(runs)}")
    if warns:
        print(f"Residual warn jumps: {len(warns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
