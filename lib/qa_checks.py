"""Automated QA checks for corrected trajectory CSVs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .detect import (
    DRIVE_MIN_SPEED_MPS,
    TrackPoint,
    detect_switches,
    fmt_cst,
    haversine_m,
    max_valid_speed,
    path_stats,
    segment_indices,
)
from .qa_anchors import Anchor, near_any_anchor

JUMP_THR_M = 250.0
SHIFT_MIN_M = 300.0
SHIFT_MAX_M = 700.0
DRIFT_FAIL_M = 200.0
MAX_STEP_WORSE_M = 30.0
COORD_EPS = 1e-7


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    severity: str = "error"  # "error" fails exit; "warn" reported only
    table_headers: Optional[List[str]] = None
    table_rows: Optional[List[List[str]]] = None


def check_residual_gcj_switches(corrected: Sequence[TrackPoint]) -> CheckResult:
    """纠偏后驾车段是否仍有疑似 GCJ 跳变（警告，不导致失败退出）。"""
    segs = segment_indices([p.t for p in corrected])
    leftover = []
    for idxs in segs:
        pts = [corrected[i] for i in idxs]
        if max_valid_speed(pts) < DRIVE_MIN_SPEED_MPS:
            continue
        switches = detect_switches(pts)
        switches = [s for s in switches if s.err_m <= 50.0]
        if switches:
            leftover.append(
                (
                    pts[0].t,
                    pts[-1].t,
                    len(switches),
                    [(s.kind, s.after_local_idx, round(s.err_m, 1)) for s in switches[:5]],
                )
            )
    if leftover:
        rows = [
            [
                fmt_cst(a),
                fmt_cst(b),
                str(n),
                "；".join(f"{k}@{i} {e}m" for k, i, e in samp),
            ]
            for a, b, n, samp in leftover
        ]
        return CheckResult(
            "残留GCJ跳变",
            True,
            f"警告：仍有 {len(leftover)} 段驾车轨迹出现疑似 GCJ 跳变（建议抽查）",
            severity="warn",
            table_headers=["开始（CST）", "结束", "切换次数", "样例"],
            table_rows=rows,
        )
    return CheckResult(
        "残留GCJ跳变",
        True,
        "纠偏后驾车段未发现疑似 GCJ 跳变",
        severity="warn",
    )


def _index_by_time(points: Sequence[TrackPoint]) -> Dict[int, List[TrackPoint]]:
    out: Dict[int, List[TrackPoint]] = {}
    for p in points:
        out.setdefault(p.t, []).append(p)
    return out


def _changed(
    orig: TrackPoint, corr_by_t: Dict[int, List[TrackPoint]]
) -> Optional[Tuple[TrackPoint, float]]:
    cands = corr_by_t.get(orig.t)
    if not cands:
        return None
    best = min(cands, key=lambda c: haversine_m(orig.lon, orig.lat, c.lon, c.lat))
    d = haversine_m(orig.lon, orig.lat, best.lon, best.lat)
    if d > 1.0:
        return best, d
    return None


def _jump_count(points: Sequence[TrackPoint], thr: float = JUMP_THR_M) -> int:
    if len(points) < 2:
        return 0
    return sum(
        1
        for a, b in zip(points, points[1:])
        if haversine_m(a.lon, a.lat, b.lon, b.lat) >= thr
    )


def check_daily_untouched(
    original: Sequence[TrackPoint], corrected: Sequence[TrackPoint]
) -> CheckResult:
    corr_by_t = _index_by_time(corrected)
    segs = segment_indices([p.t for p in original])
    bad = 0
    examples = []
    for idxs in segs:
        pts = [original[i] for i in idxs]
        if max_valid_speed(pts) >= DRIVE_MIN_SPEED_MPS:
            continue
        for p in pts:
            ch = _changed(p, corr_by_t)
            if ch is not None:
                bad += 1
                if len(examples) < 5:
                    examples.append(f"{fmt_cst(p.t)} 位移={ch[1]:.1f}m")
    if bad:
        return CheckResult(
            "日常段零修改",
            False,
            f"日常/慢速段有 {bad} 个点被改动：" + "，".join(examples),
        )
    return CheckResult("日常段零修改", True, "日常/慢速段坐标未被修改")


def check_stay_no_drift(
    original: Sequence[TrackPoint],
    corrected: Sequence[TrackPoint],
    anchors: Sequence[Anchor],
) -> CheckResult:
    if not anchors:
        return CheckResult(
            "常驻点不外漂",
            True,
            "无可用常驻锚点，已跳过",
        )
    corr_by_t = _index_by_time(corrected)
    drifted = 0
    rows: List[List[str]] = []
    for p in original:
        if not near_any_anchor(p.lon, p.lat, anchors):
            continue
        ch = _changed(p, corr_by_t)
        if ch is None:
            continue
        _, shift = ch
        if shift > DRIFT_FAIL_M:
            drifted += 1
            if len(rows) < 20:
                rows.append(
                    [
                        fmt_cst(p.t),
                        f"{shift:.0f}",
                        f"{p.lon:.5f}",
                        f"{p.lat:.5f}",
                    ]
                )
    if drifted:
        return CheckResult(
            "常驻点不外漂",
            False,
            f"常驻点附近有 {drifted} 个点纠偏后外漂超过 {DRIFT_FAIL_M:.0f}m",
            table_headers=["时间（CST）", "位移 m", "经度", "纬度"],
            table_rows=rows,
        )
    return CheckResult(
        "常驻点不外漂",
        True,
        f"常驻点附近坐标稳定（锚点数 {len(anchors)}）",
    )


def check_shift_magnitude(
    original: Sequence[TrackPoint], corrected: Sequence[TrackPoint]
) -> CheckResult:
    corr_by_t = _index_by_time(corrected)
    shifts = []
    for p in original:
        ch = _changed(p, corr_by_t)
        if ch is not None:
            shifts.append(ch[1])
    if not shifts:
        return CheckResult("修改点位移形态", True, "没有坐标被修改")
    outliers = [s for s in shifts if not (SHIFT_MIN_M <= s <= SHIFT_MAX_M)]
    ratio = len(outliers) / len(shifts)
    median = sorted(shifts)[len(shifts) // 2]
    if len(outliers) >= 5 and ratio > 0.15:
        return CheckResult(
            "修改点位移形态",
            False,
            f"{len(outliers)}/{len(shifts)} 个修改点位移不在 "
            f"{SHIFT_MIN_M:.0f}–{SHIFT_MAX_M:.0f}m（占比 {ratio:.0%}）；"
            f"中位位移={median:.0f}m",
        )
    return CheckResult(
        "修改点位移形态",
        True,
        f"共修改 {len(shifts)} 点；中位位移={median:.0f}m；"
        f"异常位移 {len(outliers)} 个",
    )


def check_path_improved(
    original: Sequence[TrackPoint], corrected: Sequence[TrackPoint]
) -> CheckResult:
    corr_by_t = _index_by_time(corrected)
    segs = segment_indices([p.t for p in original])
    failures = []
    checked = 0
    for idxs in segs:
        opts = [original[i] for i in idxs]
        modified = False
        cpts: List[TrackPoint] = []
        for p in opts:
            cands = corr_by_t.get(p.t)
            if not cands:
                continue
            best = min(cands, key=lambda c: abs(c.t - p.t))
            cpts.append(best)
            if haversine_m(p.lon, p.lat, best.lon, best.lat) > 1.0:
                modified = True
        if not modified or len(cpts) < 2:
            continue
        checked += 1
        jb = _jump_count(opts)
        ja = _jump_count(cpts)
        _, _, max_b = path_stats([(p.lon, p.lat) for p in opts])
        _, _, max_a = path_stats([(p.lon, p.lat) for p in cpts])
        if ja > jb:
            failures.append(f"{fmt_cst(opts[0].t)}: 大跳变 {jb}→{ja}")
        if max_a > max_b + MAX_STEP_WORSE_M:
            failures.append(
                f"{fmt_cst(opts[0].t)}: 最大步进 {max_b:.0f}→{max_a:.0f}m"
            )
    if failures:
        return CheckResult(
            "路径质量",
            False,
            f"{len(failures)} 段修改后路径变差：" + "；".join(failures[:8]),
        )
    return CheckResult(
        "路径质量",
        True,
        f"已检查 {checked} 段有修改的行程；大跳变/最大步进未回退",
    )


def run_standard_checks(
    original: Sequence[TrackPoint],
    corrected: Sequence[TrackPoint],
    anchors: Sequence[Anchor],
) -> List[CheckResult]:
    return [
        check_residual_gcj_switches(corrected),
        check_daily_untouched(original, corrected),
        check_stay_no_drift(original, corrected, anchors),
        check_shift_magnitude(original, corrected),
        check_path_improved(original, corrected),
    ]


def suspicious_segments(
    original: Sequence[TrackPoint],
    corrected: Sequence[TrackPoint],
    *,
    top_n: int = 10,
) -> List[dict]:
    """列出修改后仍可疑的行程段。"""
    corr_by_t = _index_by_time(corrected)
    rows = []
    for idxs in segment_indices([p.t for p in original]):
        opts = [original[i] for i in idxs]
        cpts = []
        fixed = 0
        for p in opts:
            cands = corr_by_t.get(p.t)
            if not cands:
                continue
            best = min(cands, key=lambda c: haversine_m(p.lon, p.lat, c.lon, c.lat))
            cpts.append(best)
            if haversine_m(p.lon, p.lat, best.lon, best.lat) > 1.0:
                fixed += 1
        if fixed == 0 or len(cpts) < 2:
            continue
        jb = _jump_count(opts)
        ja = _jump_count(cpts)
        _, mean_b, max_b = path_stats([(p.lon, p.lat) for p in opts])
        _, mean_a, max_a = path_stats([(p.lon, p.lat) for p in cpts])
        score = ja * 10 + max(0, max_a - max_b) + fixed * 0.01
        rows.append(
            {
                "t0": opts[0].t,
                "t1": opts[-1].t,
                "fixed": fixed,
                "jumps_before": jb,
                "jumps_after": ja,
                "max_before": max_b,
                "max_after": max_a,
                "mean_before": mean_b,
                "mean_after": mean_a,
                "score": score,
            }
        )
    rows.sort(key=lambda r: -r["score"])
    return rows[:top_n]
