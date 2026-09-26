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

from lib.detect import (
    TrackPoint,
    analyze_segment,
    correct_points,
    fmt_cst,
    haversine_m,
    path_stats,
    segment_indices,
)


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
        f"# Trajectory correction report",
        "",
        f"- Input: `{input_name}`",
        f"- Points in: **{total_in}**",
        f"- Points out: **{total_out}**",
        f"- Converted GCJ→WGS: **{fixed_total}**",
        f"- Near-duplicate removed: **{removed_total}**",
        "",
        "## Segments with corrections",
        "",
    ]

    corrected_segs = [s for s in seg_summaries if s["fixed"] > 0 or s["removed"] > 0]
    if not corrected_segs:
        lines.append("_No GCJ contamination detected._")
    else:
        lines.append(
            "| Start (CST) | End | n_in | n_out | fixed | removed | "
            "switches | max_spd m/s | max_step before→after |"
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
            "## Top driving segments by GCJ switches (incl. unfixed if any)",
            "",
        ]
    )
    top = sorted(
        [s for s in seg_summaries if s["is_drive"]],
        key=lambda x: (-x["switches"], -x["fixed"]),
    )[:20]
    if not top:
        lines.append("_No driving segments._")
    else:
        lines.append("| Start (CST) | n | switches | fixed | max_spd | kind |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for s in top:
            kind = "corrected" if s["fixed"] else ("clean" if s["switches"] == 0 else "detected")
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
    times = [p.t for p in points]
    segs_idx = segment_indices(times)

    out_rows: List[dict] = []
    summaries: List[dict] = []
    fixed_total = 0
    removed_total = 0

    for idxs in segs_idx:
        seg_points = [points[i] for i in idxs]
        result = analyze_segment(seg_points)

        before_coords = [(p.lon, p.lat) for p in seg_points]
        _, _, max_before = path_stats(before_coords)

        if result.is_drive and result.gcj_count > 0:
            corrected, fixed, removed = correct_points(
                seg_points, result.labels, dedupe=dedupe
            )
        else:
            corrected = seg_points
            fixed = 0
            removed = []

        after_coords = [(p.lon, p.lat) for p in corrected]
        _, _, max_after = path_stats(after_coords)

        fixed_total += fixed
        removed_total += len(removed)
        for p in corrected:
            out_rows.append(p.raw)

        summaries.append(
            {
                "t0": fmt_cst(result.t0),
                "t1": fmt_cst(result.t1),
                "n_in": len(seg_points),
                "n_out": len(corrected),
                "fixed": fixed,
                "removed": len(removed),
                "switches": len(result.switches),
                "max_spd": result.max_speed,
                "max_before": max_before,
                "max_after": max_after,
                "is_drive": result.is_drive,
            }
        )

    return out_rows, summaries, fixed_total, removed_total


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
