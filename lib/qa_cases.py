"""固定回归用例（不写死家坐标）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Callable, List, Sequence

from .detect import TrackPoint, fmt_cst, haversine_m, segment_indices
from .qa_checks import CheckResult, _index_by_time, _jump_count

TZ = timezone(timedelta(hours=8))


@dataclass
class RegressionCase:
    name: str
    run: Callable[[Sequence[TrackPoint], Sequence[TrackPoint]], CheckResult]


def _window(
    points: Sequence[TrackPoint], start: datetime, end: datetime
) -> List[TrackPoint]:
    t0, t1 = int(start.timestamp()), int(end.timestamp())
    return [p for p in points if t0 <= p.t <= t1]


def _data_covers(points: Sequence[TrackPoint], start: datetime, end: datetime) -> bool:
    if not points:
        return False
    t0, t1 = int(start.timestamp()), int(end.timestamp())
    return points[0].t <= t1 and points[-1].t >= t0


def _case_sep26_drive(orig: Sequence[TrackPoint], corr: Sequence[TrackPoint]) -> CheckResult:
    name = "回归_2026-09-26_驾车"
    start = datetime(2026, 9, 26, 14, 44, tzinfo=TZ)
    end = datetime(2026, 9, 26, 16, 5, tzinfo=TZ)
    if not _data_covers(orig, start, end):
        return CheckResult(name, True, "跳过（数据不含该日期）")
    cwin = _window(corr, start, end)
    jumps = _jump_count(cwin)
    if jumps != 0:
        return CheckResult(name, False, f"纠偏后≥250m 跳变={jumps}，期望为 0")
    return CheckResult(name, True, f"驾车时段≥250m 跳变=0（点数 {len(cwin)}）")


def _case_sep26_daily(orig: Sequence[TrackPoint], corr: Sequence[TrackPoint]) -> CheckResult:
    name = "回归_2026-09-26_日常"
    start = datetime(2026, 9, 26, 13, 18, tzinfo=TZ)
    end = datetime(2026, 9, 26, 13, 54, tzinfo=TZ)
    if not _data_covers(orig, start, end):
        return CheckResult(name, True, "跳过（数据不含该日期）")
    owin = _window(orig, start, end)
    corr_by_t = _index_by_time(corr)
    changed = 0
    for p in owin:
        cands = corr_by_t.get(p.t)
        if not cands:
            continue
        best = min(cands, key=lambda c: haversine_m(p.lon, p.lat, c.lon, c.lat))
        if haversine_m(p.lon, p.lat, best.lon, best.lat) > 1.0:
            changed += 1
    if changed:
        return CheckResult(name, False, f"日常时段有 {changed} 个点被改动")
    return CheckResult(name, True, "日常时段未被修改")


def _case_jun12_start(orig: Sequence[TrackPoint], corr: Sequence[TrackPoint]) -> CheckResult:
    name = "回归_2026-06-12_起点"
    start = datetime(2026, 6, 12, 8, 42, tzinfo=TZ)
    if not _data_covers(orig, start, start + timedelta(hours=1)):
        return CheckResult(name, True, "跳过（数据不含该日期）")
    target = int(start.timestamp())
    segs = segment_indices([p.t for p in orig])
    seg0 = None
    for idxs in segs:
        if abs(orig[idxs[0]].t - target) <= 180:
            seg0 = orig[idxs[0]]
            break
    if seg0 is None:
        return CheckResult(name, True, "跳过（未找到对应行程）")
    corr_by_t = _index_by_time(corr)
    cands = corr_by_t.get(seg0.t)
    if not cands:
        return CheckResult(name, False, f"纠偏文件缺少起点 {fmt_cst(seg0.t)}")
    best = min(cands, key=lambda c: haversine_m(seg0.lon, seg0.lat, c.lon, c.lat))
    shift = haversine_m(seg0.lon, seg0.lat, best.lon, best.lat)
    if shift >= 20.0:
        return CheckResult(
            name,
            False,
            f"行程起点位移 {shift:.1f}m（{fmt_cst(seg0.t)}），期望 <20m",
        )
    return CheckResult(name, True, f"起点稳定（位移 {shift:.1f}m，{fmt_cst(seg0.t)}）")


def _case_jumps_zero(
    name: str, y: int, m: int, d: int, hh: int, mm: int, dur_h: float = 3.0
) -> RegressionCase:
    start = datetime(y, m, d, hh, mm, tzinfo=TZ)
    end = start + timedelta(hours=dur_h)

    def run(orig: Sequence[TrackPoint], corr: Sequence[TrackPoint]) -> CheckResult:
        if not _data_covers(orig, start, end):
            return CheckResult(name, True, "跳过（数据不含该日期）")
        target = int(start.timestamp())
        segs = segment_indices([p.t for p in corr])
        chosen = None
        for idxs in segs:
            if abs(corr[idxs[0]].t - target) <= 180:
                chosen = [corr[i] for i in idxs]
                break
        if chosen is None:
            chosen = _window(corr, start, end)
        jumps = _jump_count(chosen)
        if jumps != 0:
            return CheckResult(
                name,
                False,
                f"纠偏后≥250m 跳变={jumps}（{fmt_cst(target)} 附近，点数 {len(chosen)}）",
            )
        return CheckResult(name, True, f"≥250m 跳变=0（点数 {len(chosen)}）")

    return RegressionCase(name, run)


def _case_jan16(orig: Sequence[TrackPoint], corr: Sequence[TrackPoint]) -> CheckResult:
    name = "回归_2026-01-16"
    start = datetime(2026, 1, 16, 10, 57, tzinfo=TZ)
    end = datetime(2026, 1, 16, 11, 36, tzinfo=TZ)
    if not _data_covers(orig, start, end):
        return CheckResult(name, True, "跳过（数据不含该日期）")
    target = int(start.timestamp())
    o_segs = segment_indices([p.t for p in orig])
    c_by_t = _index_by_time(corr)
    opts = None
    for idxs in o_segs:
        if abs(orig[idxs[0]].t - target) <= 180:
            opts = [orig[i] for i in idxs]
            break
    if opts is None:
        opts = _window(orig, start, end)
    cpts = []
    fixed = 0
    for p in opts:
        cands = c_by_t.get(p.t)
        if not cands:
            continue
        best = min(cands, key=lambda c: haversine_m(p.lon, p.lat, c.lon, c.lat))
        cpts.append(best)
        if haversine_m(p.lon, p.lat, best.lon, best.lat) > 1.0:
            fixed += 1
    jumps = _jump_count(cpts)
    if jumps != 0:
        return CheckResult(name, False, f"≥250m 跳变={jumps}，期望为 0")
    if fixed >= 10:
        return CheckResult(
            name, False, f"修改点数={fixed}（期望仅尖峰级 <10）"
        )
    return CheckResult(name, True, f"跳变=0，修改点数={fixed}")


REGRESSION_CASES: List[RegressionCase] = [
    RegressionCase("回归_2026-09-26_驾车", _case_sep26_drive),
    RegressionCase("回归_2026-09-26_日常", _case_sep26_daily),
    RegressionCase("回归_2026-06-12_起点", _case_jun12_start),
    RegressionCase("回归_2026-01-16", _case_jan16),
    _case_jumps_zero("回归_2026-08-21", 2026, 8, 21, 16, 55, 2.0),
    _case_jumps_zero("回归_2026-05-31", 2026, 5, 31, 18, 14, 3.0),
]


def run_regression_cases(
    original: Sequence[TrackPoint], corrected: Sequence[TrackPoint]
) -> List[CheckResult]:
    return [case.run(original, corrected) for case in REGRESSION_CASES]
