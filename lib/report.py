"""Shared markdown report for footprint and DoL corrections."""

from __future__ import annotations

from typing import List, Optional, Sequence

from .detect import TrackPoint, fmt_cst


def gcj_run_lines(points: Sequence[TrackPoint], labels: Sequence[str]) -> List[str]:
    """Format converted GCJ blocks as report bullets."""
    lines: List[str] = []
    start: int | None = None
    for i, lab in enumerate(list(labels) + ["W"]):
        if lab == "G":
            if start is None:
                start = i
        elif start is not None:
            lines.append(
                f"{fmt_cst(points[start].t)} → {fmt_cst(points[i - 1].t)}  "
                f"点数 {i - start}  (行 {start + 2}–{i + 1})"
            )
            start = None
    return lines


def build_report(
    input_name: str,
    total_in: int,
    total_out: int,
    fixed_total: int,
    removed_total: int,
    seg_summaries: Sequence[dict],
    *,
    run_lines: Optional[Sequence[str]] = None,
    removed_indices: Optional[Sequence[int]] = None,
    warn_lines: Optional[Sequence[str]] = None,
) -> str:
    lines = [
        "# 轨迹纠偏报告",
        "",
        f"- 输入文件：`{input_name}`",
        f"- 输入点数：**{total_in}**",
        f"- 输出点数：**{total_out}**",
        f"- GCJ→WGS 转换点数：**{fixed_total}**",
        f"- 删除点数：**{removed_total}**",
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
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
        for s in sorted(corrected_segs, key=lambda x: -x["fixed"]):
            lines.append(
                f"| {s['t0']} | {s['t1']} | {s['n_in']} | {s['n_out']} | "
                f"{s['fixed']} | {s['removed']} | {s['switches']} | "
                f"{s['max_spd']:.1f} | {s['max_before']:.0f}→{s['max_after']:.0f} m |"
            )

    lines.extend(["", "## 驾车行程按 GCJ 切换次数排序（含未改动的）", ""])
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

    if run_lines:
        lines.extend(["", "## GCJ 块（已转换）", ""])
        for line in run_lines:
            lines.append(f"- {line}")

    if removed_indices:
        lines.extend(["", "## 删除的点", ""])
        for idx in removed_indices:
            lines.append(f"- 原始行号约 {idx + 2}（0-based index {idx}）")

    if warn_lines:
        lines.extend(["", "## 残留警告跳变", ""])
        for line in warn_lines:
            lines.append(f"- {line}")

    lines.append("")
    return "\n".join(lines)
