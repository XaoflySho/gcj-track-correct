#!/usr/bin/env python3
"""Correct GCJ-02 contamination in 一生足迹 trajectory CSV exports.

Assumes the bulk of points are WGS-84. Detects driving-segment WGS/GCJ switches
(interleaved or block-wise) and converts only GCJ points back to WGS-84.

Run inside the project virtualenv:

    source .venv/bin/activate
    python correct_tracks.py --input 2026.01.01-2026.12.31.csv --output-dir output/
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

from lib.detect import TrackPoint
from lib.process import process_track


FIELDNAMES = [
    "dataTime",
    "locType",
    "longitude",
    "latitude",
    "heading",
    "accuracy",
    "speed",
    "distance",
    "isBackForeground",
    "stepType",
    "altitude",
]


def load_csv(path: Path) -> List[TrackPoint]:
    points: List[TrackPoint] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"Empty or invalid CSV: {path}")
        for i, row in enumerate(reader):
            points.append(
                TrackPoint(
                    index=i,
                    t=int(row["dataTime"]),
                    lon=float(row["longitude"]),
                    lat=float(row["latitude"]),
                    speed=float(row["speed"]),
                    accuracy=float(row["accuracy"]),
                    altitude=float(row["altitude"]),
                    raw=dict(row),
                )
            )
    return points


def write_csv(path: Path, rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


def build_report(
    input_name: str,
    total_in: int,
    total_out: int,
    fixed_total: int,
    removed_total: int,
    seg_summaries: List[dict],
) -> str:
    lines = [
        "# 轨迹纠偏报告",
        "",
        f"- 输入文件：`{input_name}`",
        f"- 输入点数：**{total_in}**",
        f"- 输出点数：**{total_out}**",
        f"- GCJ→WGS 转换点数：**{fixed_total}**",
        f"- 近重复删除点数：**{removed_total}**",
        "",
        "## 发生纠偏的行程",
        "",
    ]

    corrected_segs = [s for s in seg_summaries if s["fixed"] > 0 or s["removed"] > 0]
    if not corrected_segs:
        lines.append("_未检测到 GCJ 污染。_")
    else:
        lines.append(
            "| 开始（CST） | 结束 | 输入点数 | 输出点数 | 转换 | 删除 | "
            "切换次数 | 最高速 m/s | 最大步进 修前→修后 |"
        )
        lines.append(
            "|---|---|---:|---:|---:|---:|---:|---:|---|"
        )
        for s in sorted(corrected_segs, key=lambda x: -x["fixed"]):
            lines.append(
                f"| {s['t0']} | {s['t1']} | {s['n_in']} | {s['n_out']} | "
                f"{s['fixed']} | {s['removed']} | {s['switches']} | "
                f"{s['max_spd']:.1f} | {s['max_before']:.0f}→{s['max_after']:.0f} m |"
            )

    lines.extend(
        [
            "",
            "## 驾车行程按 GCJ 切换次数排序（含未改动的）",
            "",
        ]
    )
    top = sorted(
        [s for s in seg_summaries if s["is_drive"]],
        key=lambda x: (-x["switches"], -x["fixed"]),
    )[:20]
    if not top:
        lines.append("_无驾车行程。_")
    else:
        lines.append("| 开始（CST） | 点数 | 切换次数 | 转换点数 | 最高速 | 状态 |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for s in top:
            if s["fixed"]:
                kind = "已纠偏"
            elif s["switches"] == 0:
                kind = "干净"
            else:
                kind = "已检测未改"
            lines.append(
                f"| {s['t0']} | {s['n_in']} | {s['switches']} | {s['fixed']} | "
                f"{s['max_spd']:.1f} | {kind} |"
            )

    lines.append("")
    return "\n".join(lines)


def process(
    points: List[TrackPoint],
    *,
    dedupe: bool = True,
) -> Tuple[List[dict], List[dict], int, int]:
    return process_track(points, dedupe=dedupe)


def validate_sep26_hint(summaries: Sequence[dict]) -> None:
    """Print a short sanity check for 2026-09-26 afternoon drive if present."""
    targets = [s for s in summaries if s["t0"].startswith("2026-09-26 14:")]
    if not targets:
        return
    print("\n[check] 2026-09-26 afternoon segments:")
    for s in targets:
        print(
            f"  {s['t0']} → {s['t1']}: fixed={s['fixed']} switches={s['switches']} "
            f"max_step {s['max_before']:.0f}→{s['max_after']:.0f} m"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Correct GCJ-02 points mixed into WGS-84 footprint tracks."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        type=Path,
        help="Input CSV from 一生足迹 export",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("output"),
        help="Directory for corrected CSV and report (default: output/)",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Do not remove near-duplicate points after conversion",
    )
    args = parser.parse_args(argv)

    input_path: Path = args.input
    if not input_path.is_file():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1

    print(f"Loading {input_path} ...")
    points = load_csv(input_path)
    print(f"Loaded {len(points)} points")

    out_rows, summaries, fixed_total, removed_total = process(
        points, dedupe=not args.no_dedupe
    )

    stem = input_path.stem
    out_dir: Path = args.output_dir
    csv_path = out_dir / f"{stem}_corrected.csv"
    report_path = out_dir / f"{stem}_report.md"

    write_csv(csv_path, out_rows)
    report = build_report(
        input_path.name,
        len(points),
        len(out_rows),
        fixed_total,
        removed_total,
        summaries,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    print(f"Wrote {csv_path} ({len(out_rows)} points)")
    print(f"Wrote {report_path}")
    print(f"Converted: {fixed_total}, removed near-duplicates: {removed_total}")
    validate_sep26_hint(summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
