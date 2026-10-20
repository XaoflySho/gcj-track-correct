#!/usr/bin/env python3
"""Generate a Leaflet HTML map comparing original vs corrected tracks.

    source .venv/bin/activate
    python view_tracks.py \\
      --original 2025.01.01-2025.12.31.csv \\
      --corrected output/2025.01.01-2025.12.31_corrected.csv \\
      --from "2025-01-04 10:50" --to "2025-01-04 11:20" \\
      --out output/preview_20250104.html
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import List

from lib.detect import TrackPoint, fmt_cst
from lib.view_map import (
    POINT_WARN_LIMIT,
    align_tracks,
    filter_by_time,
    window_from_day,
    window_from_range,
    write_preview_html,
)


def load_csv(path: Path) -> List[TrackPoint]:
    """Load 一生足迹 (dataTime) or 人生点点/DoL (timestamp) CSV."""
    from lib.dol_io import load_dol_csv, time_key

    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"Empty or invalid CSV: {path}")
        try:
            time_key(reader.fieldnames)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    return load_dol_csv(path)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="按时间窗导出原始/纠偏轨迹对比地图（Leaflet HTML，OSM/WGS-84）"
    )
    parser.add_argument("--original", required=True, type=Path, help="原始 CSV")
    parser.add_argument("--corrected", required=True, type=Path, help="纠偏后 CSV")
    parser.add_argument(
        "--from",
        dest="time_from",
        default=None,
        help="开始时间 CST，如 2025-01-04 10:50",
    )
    parser.add_argument(
        "--to",
        dest="time_to",
        default=None,
        help="结束时间 CST，如 2025-01-04 11:20",
    )
    parser.add_argument(
        "--day",
        default=None,
        help="整天快捷参数 YYYY-MM-DD（CST 00:00–次日 00:00）",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("output/preview.html"),
        help="输出 HTML 路径（默认 output/preview.html）",
    )
    parser.add_argument(
        "--min-shift-m",
        type=float,
        default=5.0,
        help="改动点位移阈值（米，默认 5）",
    )
    args = parser.parse_args(argv)

    if args.day:
        if args.time_from or args.time_to:
            print("错误：--day 与 --from/--to 不能同时使用", file=sys.stderr)
            return 2
        try:
            t0, t1 = window_from_day(args.day)
        except ValueError as e:
            print(f"错误：{e}", file=sys.stderr)
            return 2
        end_exclusive = True
        window_label = f"{args.day}（整天 CST）"
    else:
        if not args.time_from or not args.time_to:
            print("错误：请指定 --day，或同时指定 --from 与 --to", file=sys.stderr)
            return 2
        try:
            t0, t1 = window_from_range(args.time_from, args.time_to)
        except ValueError as e:
            print(f"错误：{e}", file=sys.stderr)
            return 2
        end_exclusive = False
        window_label = f"{args.time_from} → {args.time_to}（CST）"

    if not args.original.is_file():
        print(f"错误：找不到原始文件 {args.original}", file=sys.stderr)
        return 2
    if not args.corrected.is_file():
        print(f"错误：找不到纠偏文件 {args.corrected}", file=sys.stderr)
        return 2

    print(f"加载 {args.original} …")
    original_all = load_csv(args.original)
    print(f"加载 {args.corrected} …")
    corrected_all = load_csv(args.corrected)

    original = filter_by_time(original_all, t0, t1, end_exclusive=end_exclusive)
    corrected = filter_by_time(corrected_all, t0, t1, end_exclusive=end_exclusive)

    if not original and not corrected:
        print("错误：时间窗内无点", file=sys.stderr)
        return 1

    n_pts = max(len(original), len(corrected))
    if n_pts > POINT_WARN_LIMIT:
        print(
            f"警告：时间窗内约 {n_pts} 点（>{POINT_WARN_LIMIT}），浏览器可能较卡，"
            "建议缩小 --from/--to",
            file=sys.stderr,
        )

    view = align_tracks(original, corrected, min_shift_m=args.min_shift_m)
    title = "轨迹纠偏对比预览"
    subtitle = (
        f"{window_label} · 原始 {view.n_original} 点 · 纠偏 {view.n_corrected} 点 · "
        f"改动 {len(view.changed)} · 删除 {len(view.removed)}"
    )
    write_preview_html(args.out, view, title=title, subtitle=subtitle)

    print(f"已写入 {args.out.resolve()}")
    print(
        f"  时间窗 {fmt_cst(t0)} → "
        f"{fmt_cst(t1 - 1) if end_exclusive else fmt_cst(t1)} · "
        f"改动 {len(view.changed)} · 删除 {len(view.removed)}"
    )
    print("  请用浏览器打开上述 HTML（底图需联网加载 OSM）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
