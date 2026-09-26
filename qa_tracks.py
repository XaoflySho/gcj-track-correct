#!/usr/bin/env python3
"""QA checks for GCJ-corrected trajectory CSVs.

Compares original vs corrected exports: residual GCJ switches, daily untouched,
stay-anchor drift (auto-discovered, move-friendly), shift magnitude, path quality,
plus fixed regression cases.

    source .venv/bin/activate
    python qa_tracks.py \
      --original 2026.01.01-2026.12.31.csv \
      --corrected output/2026.01.01-2026.12.31_corrected.csv \
      --output-dir output/
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

from lib.detect import TrackPoint, fmt_cst
from lib.qa_anchors import Anchor, discover_stay_anchors, merge_anchors
from lib.qa_cases import run_regression_cases
from lib.qa_checks import CheckResult, run_standard_checks, suspicious_segments


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


def parse_home(value: str) -> Tuple[float, float]:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected lon,lat got {value!r}")
    return float(parts[0].strip()), float(parts[1].strip())


def build_report(
    *,
    original_name: str,
    corrected_name: str,
    anchors: Sequence[Anchor],
    results: Sequence[CheckResult],
    suspects: Sequence[dict],
) -> str:
    def is_warn(r: CheckResult) -> bool:
        return r.ok and r.severity == "warn" and r.detail.startswith("警告")

    passed = sum(1 for r in results if r.ok and not is_warn(r))
    warned = sum(1 for r in results if is_warn(r))
    failed = sum(1 for r in results if not r.ok)
    lines = [
        "# 轨迹纠偏质检报告",
        "",
        f"- 原始文件：`{original_name}`",
        f"- 纠偏文件：`{corrected_name}`",
        f"- 检查结果：**通过 {passed}**，**警告 {warned}**，**失败 {failed}**",
        "",
        "## 常驻锚点",
        "",
    ]
    if not anchors:
        lines.append("_未发现 / 未提供常驻锚点。_")
    else:
        lines.append("| 经度 | 纬度 | 点数 | 来源 |")
        lines.append("|---:|---:|---:|---|")
        src_map = {"auto": "自动发现", "manual": "手动指定"}
        for a in anchors:
            lines.append(
                f"| {a.lon:.6f} | {a.lat:.6f} | {a.count} | {src_map.get(a.source, a.source)} |"
            )

    lines.extend(["", "## 检查项", ""])
    for r in results:
        if is_warn(r):
            mark = "警告"
        else:
            mark = "通过" if r.ok else "失败"
        lines.append(f"- **{mark}** `{r.name}` — {r.detail}")
        if r.table_headers and r.table_rows:
            lines.append("")
            lines.append("| " + " | ".join(r.table_headers) + " |")
            align_map = {
                "开始（CST）": "---",
                "结束": "---",
                "时间（CST）": "---",
                "样例": "---",
                "切换次数": "---:",
                "位移 m": "---:",
                "经度": "---:",
                "纬度": "---:",
            }
            aligns = [align_map.get(h, "---") for h in r.table_headers]
            lines.append("|" + "|".join(aligns) + "|")
            for row in r.table_rows:
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")

    lines.extend(["", "## 可疑已修改行程（Top-N）", ""])
    if not suspects:
        lines.append("_无。_")
    else:
        lines.append(
            "| 开始（CST） | 结束 | 修改点数 | 大跳变 修前→修后 | 最大步进 修前→修后 |"
        )
        lines.append("|---|---|---:|---|---|")
        for s in suspects:
            lines.append(
                f"| {fmt_cst(s['t0'])} | {fmt_cst(s['t1'])} | {s['fixed']} | "
                f"{s['jumps_before']}→{s['jumps_after']} | "
                f"{s['max_before']:.0f}→{s['max_after']:.0f} m |"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="QA for GCJ-corrected 一生足迹 trajectory CSVs."
    )
    parser.add_argument("--original", "-o", type=Path, required=True)
    parser.add_argument("--corrected", "-c", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--home",
        action="append",
        type=parse_home,
        default=[],
        help="Optional extra stay anchor lon,lat (repeatable)",
    )
    parser.add_argument(
        "--no-auto-home",
        action="store_true",
        help="Disable auto stay-anchor discovery (use only --home)",
    )
    args = parser.parse_args(argv)

    if not args.original.is_file():
        print(f"Original not found: {args.original}", file=sys.stderr)
        return 1
    if not args.corrected.is_file():
        print(f"Corrected not found: {args.corrected}", file=sys.stderr)
        return 1

    print(f"Loading original {args.original} ...")
    original = load_csv(args.original)
    print(f"Loading corrected {args.corrected} ...")
    corrected = load_csv(args.corrected)
    print(f"Loaded original={len(original)} corrected={len(corrected)}")

    if args.no_auto_home:
        auto: List[Anchor] = []
    else:
        auto = discover_stay_anchors(original)
        print(f"Auto stay anchors: {len(auto)}")
    anchors = merge_anchors(auto, args.home)
    for a in anchors:
        print(f"  anchor ({a.lon:.6f},{a.lat:.6f}) n={a.count} src={a.source}")

    results = run_standard_checks(original, corrected, anchors)
    results.extend(run_regression_cases(original, corrected))
    suspects = suspicious_segments(original, corrected, top_n=10)

    stem = args.corrected.stem.replace("_corrected", "")
    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{stem}_qa_report.md"
    report = build_report(
        original_name=args.original.name,
        corrected_name=args.corrected.name,
        anchors=anchors,
        results=results,
        suspects=suspects,
    )
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {report_path}")

    failed = [r for r in results if not r.ok]
    warnings = [
        r for r in results if r.ok and r.severity == "warn" and r.detail.startswith("警告")
    ]
    for r in results:
        if not r.ok:
            mark = "失败"
        elif r.severity == "warn" and r.detail.startswith("警告"):
            mark = "警告"
        else:
            mark = "通过"
        print(f"[{mark}] {r.name}: {r.detail}")

    if failed:
        print(f"\n质检失败（{len(failed)} 项）", file=sys.stderr)
        return 1
    if warnings:
        print(f"\n质检通过，另有 {len(warnings)} 条警告")
    else:
        print("\n质检通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
