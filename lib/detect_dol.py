"""DoL post-processing on top of the shared switch detector.

Fills leftover GCJ blocks the WGS-ref walker can miss (adjacent blocks),
drops off-path wild points, and reports residual jumps after conversion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .coords import gcj02_to_wgs84
from .detect import (
    MAX_LINK_DT_S,
    SAME_FRAME_ERR_M,
    TrackPoint,
    fmt_cst,
    haversine_m,
)
from .process import apply_corrections, label_segments

# Raw step must exceed expect by this much to open a leftover G run
MIN_JUMP_EXCESS_M = 250.0


# Lateral wild spike (not GCJ): cross-track vs chord of neighbors
LATERAL_CROSS_M = 300.0
LATERAL_EXCESS_M = 200.0
LATERAL_MAX_DT_S = 20
# Converted residual vs speed×dt when testing the GCJ hypothesis
MATCH_ERR_M = 50.0

# Residual jump warning after correction
WARN_EXCESS_M = 200.0
WARN_MAX_DT_S = 30


@dataclass
class DolGcjRun:
    start: int  # inclusive global index
    end: int  # exclusive global index
    t0: int
    t1: int
    n: int


@dataclass
class DolWarnJump:
    after_index: int
    t: int
    jump_m: float
    expect_m: float
    note: str


def _expect_m(speed: float, dt: int) -> float:
    return max(speed, 0.0) * dt


def _cross_track_m(
    lon_a: float,
    lat_a: float,
    lon_c: float,
    lat_c: float,
    lon_b: float,
    lat_b: float,
) -> float:
    """Signed cross-track distance of B from chord A→C (metres)."""
    e_c = (lon_c - lon_a) * 111320.0 * math.cos(math.radians(lat_a))
    n_c = (lat_c - lat_a) * 110540.0
    e_b = (lon_b - lon_a) * 111320.0 * math.cos(math.radians(lat_a))
    n_b = (lat_b - lat_a) * 110540.0
    length = math.hypot(e_c, n_c)
    if length < 30.0:
        return haversine_m(lon_a, lat_a, lon_b, lat_b)
    ue, un = e_c / length, n_c / length
    return e_b * (-un) + n_b * ue


def fill_gcj_by_kinematics(
    points: Sequence[TrackPoint], labels: Sequence[str]
) -> List[str]:
    """Mark leftover GCJ points the switch walker missed (adjacent blocks).

    Only opens or extends G; never clears a switch-detector label. Skips
    non-drive ``U`` points. Real motion that already matches speed×dt stays W.
    """
    out = list(labels)
    n = len(points)
    for i in range(1, n):
        if out[i] == "U" or out[i] == "G":
            continue
        a, b = points[i - 1], points[i]
        dt = b.t - a.t
        if dt <= 0 or dt > MAX_LINK_DT_S:
            continue
        exp = _expect_m(b.speed, dt)
        raw = haversine_m(a.lon, a.lat, b.lon, b.lat)
        b_wgs = gcj02_to_wgs84(b.lon, b.lat)
        err_raw = abs(raw - exp)
        err_b_gcj = abs(haversine_m(a.lon, a.lat, b_wgs[0], b_wgs[1]) - exp)
        raw_ok = err_raw < SAME_FRAME_ERR_M
        b_gcj_ok = (
            err_b_gcj < MATCH_ERR_M
            and raw > exp + MIN_JUMP_EXCESS_M
            and not raw_ok
        )
        if b_gcj_ok:
            out[i] = "G"
        elif out[i - 1] == "G" and raw_ok:
            out[i] = "G"
        elif out[i - 1] == "G" and not raw_ok and err_raw < MATCH_ERR_M * 3:
            if err_b_gcj + 15.0 < err_raw:
                continue
            out[i] = "G"
    return out


def find_lateral_spike_indices(
    points: Sequence[TrackPoint], labels: Sequence[str]
) -> List[int]:
    """Drop wild points that are off-path and not explained by GCJ conversion."""
    drop: List[int] = []
    n = len(points)
    for i in range(1, n - 1):
        if labels[i] == "G":
            continue
        a, b, c = points[i - 1], points[i], points[i + 1]
        dt1, dt2 = b.t - a.t, c.t - b.t
        if not (0 < dt1 <= LATERAL_MAX_DT_S and 0 < dt2 <= LATERAL_MAX_DT_S):
            continue
        e1, e2 = _expect_m(b.speed, dt1), _expect_m(c.speed, dt2)
        raw1 = haversine_m(a.lon, a.lat, b.lon, b.lat)
        raw2 = haversine_m(b.lon, b.lat, c.lon, c.lat)
        if raw1 < e1 + LATERAL_EXCESS_M and raw2 < e2 + LATERAL_EXCESS_M:
            continue
        bw = gcj02_to_wgs84(b.lon, b.lat)
        w1 = haversine_m(a.lon, a.lat, bw[0], bw[1])
        w2 = haversine_m(bw[0], bw[1], c.lon, c.lat)
        if abs(w1 - e1) < MATCH_ERR_M and abs(w2 - e2) < MATCH_ERR_M:
            continue
        cross = abs(_cross_track_m(a.lon, a.lat, c.lon, c.lat, b.lon, b.lat))
        if cross >= LATERAL_CROSS_M:
            drop.append(b.index)
    return drop


def residual_warn_jumps(points: Sequence[TrackPoint]) -> List[DolWarnJump]:
    warns: List[DolWarnJump] = []
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        dt = b.t - a.t
        if dt <= 0 or dt > WARN_MAX_DT_S:
            continue
        exp = _expect_m(b.speed, dt)
        jump = haversine_m(a.lon, a.lat, b.lon, b.lat)
        if jump > exp + WARN_EXCESS_M:
            warns.append(
                DolWarnJump(
                    after_index=b.index,
                    t=b.t,
                    jump_m=jump,
                    expect_m=exp,
                    note="修后仍偏大（非 GCJ 或未覆盖）",
                )
            )
    return warns


def _gcj_runs_from_labels(
    points: Sequence[TrackPoint], labels: Sequence[str]
) -> List[DolGcjRun]:
    runs: List[DolGcjRun] = []
    start: int | None = None
    for i, lab in enumerate(list(labels) + ["W"]):
        if lab == "G":
            if start is None:
                start = i
        elif start is not None:
            runs.append(
                DolGcjRun(
                    start=start,
                    end=i,
                    t0=points[start].t,
                    t1=points[i - 1].t,
                    n=i - start,
                )
            )
            start = None
    return runs


def process_dol_track(
    points: List[TrackPoint],
    *,
    dedupe: bool = False,
) -> Tuple[List[TrackPoint], int, List[int], List[DolGcjRun], List[DolWarnJump], List[dict]]:
    """Shared switch labels + stay anchors, then drop lateral spikes."""
    segs = label_segments(points)
    global_labels = ["U"] * len(points)
    for seg in segs:
        for local, gi in enumerate(seg.idxs):
            global_labels[gi] = seg.labels[local]

    global_labels = fill_gcj_by_kinematics(points, global_labels)
    for seg in segs:
        for local, gi in enumerate(seg.idxs):
            seg.labels[local] = global_labels[gi]

    drop = find_lateral_spike_indices(points, global_labels)
    corrected, summaries, fixed, removed = apply_corrections(
        segs, dedupe=dedupe, drop_indices=drop
    )
    runs = _gcj_runs_from_labels(points, global_labels)
    warns = residual_warn_jumps(corrected)
    return corrected, fixed, removed, runs, warns, summaries


def summarize_runs(runs: Sequence[DolGcjRun]) -> List[str]:
    lines = []
    for r in runs:
        lines.append(
            f"{fmt_cst(r.t0)} → {fmt_cst(r.t1)}  "
            f"点数 {r.n}  (行 {r.start + 2}–{r.end + 1})"
        )
    return lines
