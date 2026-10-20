"""Kinematic GCJ-02 detection for 人生点点 (DoL) driving tracks.

Uses speed×dt continuity instead of the 一生足迹 W2G/G2W switch detector,
so real motion along the GCJ offset direction (e.g. a 19 s highway step) is
not mistaken for a frame change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

from .coords import gcj02_to_wgs84
from .detect import (
    DRIVE_MIN_SPEED_MPS,
    TrackPoint,
    fmt_cst,
    haversine_m,
    max_valid_speed,
    segment_indices,
)

# Link window for kinematic checks
MAX_LINK_DT_S = 40
# Raw step must exceed expect by this much to count as a frame jump
MIN_JUMP_EXCESS_M = 250.0
# Converted / raw residual vs speed×dt
MATCH_ERR_M = 50.0
# Same-frame cruise: |raw − expect| below this continues the current label
SAME_FRAME_ERR_M = 40.0

# Lateral wild spike (not GCJ): cross-track vs chord of neighbors
LATERAL_CROSS_M = 300.0
LATERAL_EXCESS_M = 200.0
LATERAL_MAX_DT_S = 20

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


@dataclass
class DolSegmentResult:
    points: List[TrackPoint]
    is_drive: bool
    labels: List[str]  # "W", "G", or "U"
    max_speed: float
    gcj_runs: List[Tuple[int, int]]  # local [start, end)


def _expect_m(speed: float, dt: int) -> float:
    return max(speed, 0.0) * dt


def _label_drive_segment(points: Sequence[TrackPoint]) -> List[str]:
    n = len(points)
    labels: List[str] = ["?"] * n

    for i in range(1, n):
        a, b = points[i - 1], points[i]
        dt = b.t - a.t
        if dt <= 0 or dt > MAX_LINK_DT_S:
            continue
        exp = _expect_m(b.speed, dt)
        raw = haversine_m(a.lon, a.lat, b.lon, b.lat)
        b_wgs = gcj02_to_wgs84(b.lon, b.lat)
        a_wgs = gcj02_to_wgs84(a.lon, a.lat)
        err_raw = abs(raw - exp)
        err_b_gcj = abs(haversine_m(a.lon, a.lat, b_wgs[0], b_wgs[1]) - exp)
        err_a_gcj = abs(haversine_m(a_wgs[0], a_wgs[1], b.lon, b.lat) - exp)

        raw_ok = err_raw < SAME_FRAME_ERR_M
        # Anti false-positive: if raw already matches speed×dt, never open a G run
        # just because converting happens to look closer (e.g. 13:48 real move).
        b_gcj_ok = (
            err_b_gcj < MATCH_ERR_M
            and raw > exp + MIN_JUMP_EXCESS_M
            and not raw_ok
        )
        a_gcj_ok = (
            err_a_gcj < MATCH_ERR_M
            and raw > exp + MIN_JUMP_EXCESS_M
            and not raw_ok
        )

        if raw_ok and not b_gcj_ok and not a_gcj_ok:
            if labels[i - 1] == "?":
                labels[i - 1] = "W"
            if labels[i - 1] in ("W", "G"):
                labels[i] = labels[i - 1]
        elif b_gcj_ok and labels[i - 1] in ("W", "?"):
            labels[i - 1] = "W"
            labels[i] = "G"
        elif a_gcj_ok and labels[i - 1] in ("G", "?"):
            labels[i - 1] = "G"
            labels[i] = "W"
        elif labels[i - 1] == "G" and not raw_ok:
            # Soft leave: converting previous G improves this link more than raw.
            if err_a_gcj + 15.0 < err_raw:
                labels[i] = "W"
            elif err_raw < MATCH_ERR_M * 3:
                # Still roughly cruising in GCJ frame (gap / speed glitch).
                labels[i] = "G"

    # Extend same-frame labels across remaining unknowns.
    for i in range(1, n):
        if labels[i] != "?" or labels[i - 1] not in ("W", "G"):
            continue
        a, b = points[i - 1], points[i]
        dt = b.t - a.t
        if dt <= 0 or dt > MAX_LINK_DT_S:
            continue
        exp = _expect_m(b.speed, dt)
        raw = haversine_m(a.lon, a.lat, b.lon, b.lat)
        if abs(raw - exp) < SAME_FRAME_ERR_M:
            labels[i] = labels[i - 1]

    # Unknown → W for drive output consistency (only G is converted).
    return ["W" if lab == "?" else lab for lab in labels]


def _gcj_runs_local(labels: Sequence[str]) -> List[Tuple[int, int]]:
    runs: List[Tuple[int, int]] = []
    start: int | None = None
    for i, lab in enumerate(list(labels) + ["W"]):
        if lab == "G":
            if start is None:
                start = i
        elif start is not None:
            runs.append((start, i))
            start = None
    return runs


def analyze_dol_segment(points: List[TrackPoint]) -> DolSegmentResult:
    max_spd = max_valid_speed(points)
    is_drive = max_spd >= DRIVE_MIN_SPEED_MPS
    if not is_drive:
        return DolSegmentResult(
            points=points,
            is_drive=False,
            labels=["U"] * len(points),
            max_speed=max_spd,
            gcj_runs=[],
        )
    labels = _label_drive_segment(points)
    return DolSegmentResult(
        points=points,
        is_drive=True,
        labels=labels,
        max_speed=max_spd,
        gcj_runs=_gcj_runs_local(labels),
    )


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
        # GCJ hypothesis must not explain both links.
        bw = gcj02_to_wgs84(b.lon, b.lat)
        w1 = haversine_m(a.lon, a.lat, bw[0], bw[1])
        w2 = haversine_m(bw[0], bw[1], c.lon, c.lat)
        if abs(w1 - e1) < MATCH_ERR_M and abs(w2 - e2) < MATCH_ERR_M:
            continue
        cross = abs(_cross_track_m(a.lon, a.lat, c.lon, c.lat, b.lon, b.lat))
        if cross >= LATERAL_CROSS_M:
            drop.append(b.index)
    return drop


def correct_dol_points(
    points: Sequence[TrackPoint],
    labels: Sequence[str],
    *,
    drop_indices: Sequence[int] | None = None,
) -> Tuple[List[TrackPoint], int, List[int]]:
    """Convert G→WGS; optionally drop lateral spikes. Preserve raw columns."""
    drop_set = set(drop_indices or ())
    out: List[TrackPoint] = []
    fixed = 0
    removed: List[int] = []

    for p, lab in zip(points, labels):
        if p.index in drop_set:
            removed.append(p.index)
            continue
        lon, lat = p.lon, p.lat
        if lab == "G":
            lon, lat = gcj02_to_wgs84(lon, lat)
            fixed += 1
        new_p = TrackPoint(
            index=p.index,
            t=p.t,
            lon=lon,
            lat=lat,
            speed=p.speed,
            accuracy=p.accuracy,
            altitude=p.altitude,
            raw=dict(p.raw),
        )
        new_p.raw["longitude"] = f"{lon:.6f}"
        new_p.raw["latitude"] = f"{lat:.6f}"
        out.append(new_p)
    return out, fixed, removed


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


def process_dol_track(
    points: List[TrackPoint],
) -> Tuple[List[TrackPoint], int, List[int], List[DolGcjRun], List[DolWarnJump]]:
    """Full DoL pass: label per drive segment, convert, drop lateral spikes."""
    times = [p.t for p in points]
    segs = segment_indices(times)

    global_labels = ["U"] * len(points)
    for idxs in segs:
        seg = [points[i] for i in idxs]
        result = analyze_dol_segment(seg)
        for local, gi in enumerate(idxs):
            global_labels[gi] = result.labels[local]

    drop = find_lateral_spike_indices(points, global_labels)
    corrected, fixed, removed = correct_dol_points(
        points, global_labels, drop_indices=drop
    )

    runs: List[DolGcjRun] = []
    start: int | None = None
    for i, lab in enumerate(global_labels + ["W"]):
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

    warns = residual_warn_jumps(corrected)
    return corrected, fixed, removed, runs, warns


def summarize_runs(runs: Sequence[DolGcjRun]) -> List[str]:
    lines = []
    for r in runs:
        lines.append(
            f"{fmt_cst(r.t0)} → {fmt_cst(r.t1)}  "
            f"点数 {r.n}  (行 {r.start + 2}–{r.end + 1})"
        )
    return lines
