"""Detect GCJ-02 contamination in driving tracks and label points."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

from .coords import gcj02_to_wgs84, wgs84_to_gcj02

TZ_CST = timezone(timedelta(hours=8))

# Segmentation / classification
SEGMENT_GAP_S = 600
DRIVE_MIN_SPEED_MPS = 8.0

# Switch detection
MAX_SWITCH_DT_S = 20
# High-confidence GCJ-sized jumps may span longer pauses (resume with other source)
MAX_SWITCH_DT_LONG_S = 600
LONG_DT_ERR_M = 35.0
MIN_JUMP_M = 250.0
MAX_JUMP_M = 700.0
MATCH_ERR_M = 40.0
MATCH_MARGIN_M = 15.0

# Closed W2G→G2W fills must stay short; longer spans are usually WGS with endpoint spikes
MAX_PAIR_POINTS = 20
MAX_PAIR_DT_S = 120

# Optional near-duplicate removal after conversion
DEDUPE_DISTANCE_M = 5.0


@dataclass
class TrackPoint:
    index: int  # row index in original list (0-based)
    t: int
    lon: float
    lat: float
    speed: float
    accuracy: float
    altitude: float
    raw: dict  # original CSV row as strings


@dataclass
class SwitchEvent:
    after_local_idx: int  # index within segment of the point AFTER the switch
    kind: str  # "W2G" or "G2W"
    err_m: float
    jump_m: float
    dt_s: int


@dataclass
class SegmentResult:
    points: List[TrackPoint]
    is_drive: bool
    labels: List[str]  # "W", "G", or "U" per point
    switches: List[SwitchEvent] = field(default_factory=list)
    max_speed: float = -1.0
    fixed_count: int = 0
    removed_indices: List[int] = field(default_factory=list)  # global indices removed by dedupe

    @property
    def t0(self) -> int:
        return self.points[0].t

    @property
    def t1(self) -> int:
        return self.points[-1].t

    @property
    def gcj_count(self) -> int:
        return sum(1 for lab in self.labels if lab == "G")


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_unit_en(a: TrackPoint, b: TrackPoint) -> Tuple[float, float]:
    e = (b.lon - a.lon) * 111320.0 * math.cos(math.radians(a.lat))
    n = (b.lat - a.lat) * 110540.0
    length = math.hypot(e, n)
    if length < 1.0:
        return 0.0, 0.0
    return e / length, n / length


def offset_point(lon: float, lat: float, east_m: float, north_m: float) -> Tuple[float, float]:
    return (
        lon + east_m / (111320.0 * math.cos(math.radians(lat))),
        lat + north_m / 110540.0,
    )


def path_stats(coords: Sequence[Tuple[float, float]]) -> Tuple[float, float, float]:
    """Return (total_m, mean_step_m, max_step_m)."""
    if len(coords) < 2:
        return 0.0, 0.0, 0.0
    steps = [
        haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:])
    ]
    total = sum(steps)
    return total, total / len(steps), max(steps)


def segment_indices(times: Sequence[int], gap_s: int = SEGMENT_GAP_S) -> List[List[int]]:
    if not times:
        return []
    segs: List[List[int]] = [[0]]
    for i in range(1, len(times)):
        if times[i] - times[i - 1] > gap_s:
            segs.append([i])
        else:
            segs[-1].append(i)
    return segs


def max_valid_speed(points: Sequence[TrackPoint]) -> float:
    speeds = [p.speed for p in points if p.speed >= 0]
    return max(speeds) if speeds else -1.0


def detect_switches(points: Sequence[TrackPoint]) -> List[SwitchEvent]:
    switches: List[SwitchEvent] = []
    for j in range(1, len(points)):
        a, b = points[j - 1], points[j]
        dt = b.t - a.t
        if dt <= 0:
            continue
        jump = haversine_m(a.lon, a.lat, b.lon, b.lat)
        if not (MIN_JUMP_M <= jump <= MAX_JUMP_M):
            continue

        spd_a = max(a.speed, 0.0)
        spd_b = max(b.speed, 0.0)
        spd = (spd_a + spd_b) / 2.0
        if j >= 2:
            ue, un = bearing_unit_en(points[j - 2], a)
        else:
            ue, un = 0.0, 0.0
        # For long pauses, motion compensation is meaningless — use raw points.
        if dt <= MAX_SWITCH_DT_S:
            move_m = spd * dt
            pred_lon, pred_lat = offset_point(a.lon, a.lat, ue * move_m, un * move_m)
        else:
            pred_lon, pred_lat = a.lon, a.lat

        g_pred = wgs84_to_gcj02(pred_lon, pred_lat)
        w_pred = gcj02_to_wgs84(pred_lon, pred_lat)
        err_w2g = min(
            haversine_m(g_pred[0], g_pred[1], b.lon, b.lat),
            haversine_m(*wgs84_to_gcj02(a.lon, a.lat), b.lon, b.lat),
        )
        err_g2w = min(
            haversine_m(w_pred[0], w_pred[1], b.lon, b.lat),
            haversine_m(*gcj02_to_wgs84(a.lon, a.lat), b.lon, b.lat),
        )
        best = min(err_w2g, err_g2w)

        if dt <= MAX_SWITCH_DT_S:
            if best > 80.0:
                continue
            err_limit = 80.0
        elif dt <= 60:
            # Brief pauses still use the short-window error tolerance.
            if best > 80.0:
                continue
            err_limit = 80.0
        elif dt <= MAX_SWITCH_DT_LONG_S:
            # Long gap: only accept very confident GCJ-sized switches.
            if best > LONG_DT_ERR_M:
                continue
            err_limit = LONG_DT_ERR_M
        else:
            continue

        if err_w2g + MATCH_MARGIN_M < err_g2w and err_w2g <= err_limit:
            switches.append(SwitchEvent(j, "W2G", err_w2g, jump, dt))
        elif err_g2w + MATCH_MARGIN_M < err_w2g and err_g2w <= err_limit:
            switches.append(SwitchEvent(j, "G2W", err_g2w, jump, dt))
    return switches


def _walk_gcj_toward_wgs_ref(
    points: Sequence[TrackPoint],
    labels: List[str],
    *,
    start_k: int,
    step: int,
    refs: Sequence[TrackPoint],
) -> None:
    """Mark contiguous GCJ points walking from start_k; stop at WGS-like points."""
    if not refs:
        return
    n = len(points)
    k = start_k
    while 0 <= k < n:
        pk = points[k]
        d_raw = min(haversine_m(pk.lon, pk.lat, r.lon, r.lat) for r in refs)
        conv = gcj02_to_wgs84(pk.lon, pk.lat)
        d_conv = min(haversine_m(conv[0], conv[1], r.lon, r.lat) for r in refs)
        if d_raw < 120.0:
            break
        if d_conv < 100.0 and d_raw > 200.0:
            labels[k] = "G"
            k += step
            continue
        if d_conv + 80.0 < d_raw and d_conv < 200.0:
            labels[k] = "G"
            k += step
            continue
        break


def propagate_labels(points: Sequence[TrackPoint], switches: Sequence[SwitchEvent]) -> List[str]:
    """Label GCJ points conservatively.

    Rules:
    1. Short adjacent W2G → G2W pair (≤ MAX_PAIR_POINTS / MAX_PAIR_DT_S):
       mark [W2G_idx, G2W_idx) as G.
    2. Longer pairs are rejected as fills (often WGS with endpoint spikes, e.g. 2026-01-16);
       each edge is handled as unpaired instead.
    3. Unpaired W2G: mark that point; walk forward while GCJ-like vs prior WGS refs.
    4. Unpaired G2W: mark previous point; walk backward while GCJ-like vs following WGS refs.
    """
    n = len(points)
    if not switches:
        return ["U"] * n

    labels = ["W"] * n

    def handle_w2g(j: int) -> None:
        labels[j] = "G"
        refs = points[max(0, j - 3) : j]
        _walk_gcj_toward_wgs_ref(points, labels, start_k=j + 1, step=1, refs=refs)

    def handle_g2w(j: int) -> None:
        if j <= 0:
            return
        labels[j - 1] = "G"
        refs = points[j : min(n, j + 4)]
        _walk_gcj_toward_wgs_ref(points, labels, start_k=j - 2, step=-1, refs=refs)

    i = 0
    while i < len(switches):
        sw = switches[i]
        if (
            sw.kind == "W2G"
            and i + 1 < len(switches)
            and switches[i + 1].kind == "G2W"
        ):
            start = sw.after_local_idx
            end = switches[i + 1].after_local_idx
            dt = points[end].t - points[start].t if 0 <= end < n else 10**9
            span = end - start
            if end > start and span <= MAX_PAIR_POINTS:
                # Reject fills that are not a contiguous same-system run
                # (e.g. 2026-01-16: GCJ spikes at both ends with WGS in between).
                interior_ok = True
                if end - start >= 2:
                    max_interior = max(
                        haversine_m(
                            points[j].lon,
                            points[j].lat,
                            points[j + 1].lon,
                            points[j + 1].lat,
                        )
                        for j in range(start, end - 1)
                    )
                    if max_interior > 200.0:
                        interior_ok = False
                enter_ok = leave_ok = True
                if start > 0:
                    prev, first = points[start - 1], points[start]
                    first_c = gcj02_to_wgs84(first.lon, first.lat)
                    gap_raw = haversine_m(prev.lon, prev.lat, first.lon, first.lat)
                    gap_c = haversine_m(prev.lon, prev.lat, first_c[0], first_c[1])
                    enter_ok = gap_c <= gap_raw - 50.0
                if end < n:
                    last, nxt = points[end - 1], points[end]
                    last_c = gcj02_to_wgs84(last.lon, last.lat)
                    gap_raw = haversine_m(last.lon, last.lat, nxt.lon, nxt.lat)
                    gap_c = haversine_m(last_c[0], last_c[1], nxt.lon, nxt.lat)
                    leave_ok = gap_c <= gap_raw - 50.0
                if interior_ok and enter_ok and leave_ok:
                    for j in range(start, end):
                        labels[j] = "G"
                    i += 2
                    continue
            handle_w2g(start)
            handle_g2w(end)
            i += 2
            continue

        if sw.kind == "W2G":
            handle_w2g(sw.after_local_idx)
        elif sw.kind == "G2W":
            handle_g2w(sw.after_local_idx)
        i += 1

    if not any(lab == "G" for lab in labels):
        return ["U"] * n
    return labels


def _jump_count(coords: Sequence[Tuple[float, float]], thr: float = MIN_JUMP_M) -> int:
    if len(coords) < 2:
        return 0
    return sum(
        1
        for a, b in zip(coords, coords[1:])
        if haversine_m(a[0], a[1], b[0], b[1]) >= thr
    )


def _gcj_runs(labels: Sequence[str]) -> List[Tuple[int, int]]:
    """Return [start, end) runs of G labels."""
    runs: List[Tuple[int, int]] = []
    i = 0
    n = len(labels)
    while i < n:
        if labels[i] != "G":
            i += 1
            continue
        j = i
        while j < n and labels[j] == "G":
            j += 1
        runs.append((i, j))
        i = j
    return runs


def _verify_gcj_labels(points: Sequence[TrackPoint], labels: List[str]) -> List[str]:
    """Keep or drop each GCJ run as a whole (never partially convert a block)."""
    out = list(labels)
    for start, end in _gcj_runs(labels):
        # Boundary continuity: W neighbor before/after vs converting the whole run.
        ok = True
        if start > 0 and out[start - 1] != "G":
            prev = points[start - 1]
            first = points[start]
            first_c = gcj02_to_wgs84(first.lon, first.lat)
            gap_raw = haversine_m(prev.lon, prev.lat, first.lon, first.lat)
            gap_c = haversine_m(prev.lon, prev.lat, first_c[0], first_c[1])
            if gap_c > gap_raw - 50.0:
                ok = False
        if ok and end < len(points) and out[end] != "G":
            last = points[end - 1]
            nxt = points[end]
            last_c = gcj02_to_wgs84(last.lon, last.lat)
            gap_raw = haversine_m(last.lon, last.lat, nxt.lon, nxt.lat)
            gap_c = haversine_m(last_c[0], last_c[1], nxt.lon, nxt.lat)
            if gap_c > gap_raw - 50.0:
                ok = False
        # Isolated single point: require conversion to land near some neighbor.
        # Allow a wide time window — GCJ spikes often sit across long pauses.
        if ok and end - start == 1:
            j = start
            p = points[j]
            converted = gcj02_to_wgs84(p.lon, p.lat)
            matched = False
            for k in range(max(0, j - 4), min(len(points), j + 5)):
                if k == j:
                    continue
                if abs(points[k].t - p.t) > MAX_SWITCH_DT_LONG_S:
                    continue
                if haversine_m(converted[0], converted[1], points[k].lon, points[k].lat) < 80.0:
                    matched = True
                    break
            ok = matched
        if not ok:
            for j in range(start, end):
                out[j] = "W"
    if not any(lab == "G" for lab in out):
        return ["U"] * len(out)
    return out


def analyze_segment(points: List[TrackPoint]) -> SegmentResult:
    max_spd = max_valid_speed(points)
    is_drive = max_spd >= DRIVE_MIN_SPEED_MPS
    if not is_drive:
        return SegmentResult(
            points=points,
            is_drive=False,
            labels=["U"] * len(points),
            max_speed=max_spd,
        )

    switches = detect_switches(points)
    labels = propagate_labels(points, switches)
    if any(lab == "G" for lab in labels):
        labels = _verify_gcj_labels(points, labels)

    # Safety: keep GCJ labels only if correction clearly improves the path.
    if any(lab == "G" for lab in labels):
        before_coords = [(p.lon, p.lat) for p in points]
        trial = [
            gcj02_to_wgs84(p.lon, p.lat) if lab == "G" else (p.lon, p.lat)
            for p, lab in zip(points, labels)
        ]
        _, mean_b, max_b = path_stats(before_coords)
        _, mean_a, max_a = path_stats(trial)
        jumps_b = _jump_count(before_coords)
        jumps_a = _jump_count(trial)
        improved = (
            max_a <= max_b - 30.0
            or mean_a <= mean_b - 8.0
            or (jumps_b >= 2 and jumps_a <= jumps_b * 0.6)
        )
        if not improved:
            labels = ["U"] * len(points)

    return SegmentResult(
        points=points,
        is_drive=True,
        labels=labels,
        switches=list(switches),
        max_speed=max_spd,
    )


def correct_points(
    points: Sequence[TrackPoint],
    labels: Sequence[str],
    *,
    dedupe: bool = True,
) -> Tuple[List[TrackPoint], int, List[int]]:
    """
    Return corrected point list (may drop near-duplicates), fixed_count, removed global indices.
    Only GCJ-labeled points are converted to WGS-84.
    """
    corrected: List[TrackPoint] = []
    fixed = 0
    removed: List[int] = []

    for p, lab in zip(points, labels):
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

        if dedupe and corrected:
            prev = corrected[-1]
            if haversine_m(prev.lon, prev.lat, lon, lat) < DEDUPE_DISTANCE_M and abs(
                prev.t - new_p.t
            ) <= MAX_SWITCH_DT_S:
                # Prefer keeping the non-converted / earlier point when nearly identical.
                removed.append(new_p.index)
                continue
        corrected.append(new_p)

    return corrected, fixed, removed


def fmt_cst(ts: int) -> str:
    return datetime.fromtimestamp(ts, TZ_CST).strftime("%Y-%m-%d %H:%M:%S")
