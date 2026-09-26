"""Discover stay/home anchors from trajectory data (move-friendly, multi-address)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .detect import TrackPoint, haversine_m

# ~100 m grid at mid-latitudes
GRID_DECIMALS = 3  # ~111 m
STAY_SPEED_MPS = 0.5
TOP_K = 5
MIN_CLUSTER_POINTS = 20
NEAR_ANCHOR_M = 80.0


@dataclass(frozen=True)
class Anchor:
    lon: float
    lat: float
    count: int
    source: str  # "auto" or "manual"


def _grid_key(lon: float, lat: float) -> Tuple[float, float]:
    return (round(lon, GRID_DECIMALS), round(lat, GRID_DECIMALS))


def discover_stay_anchors(
    points: Sequence[TrackPoint],
    *,
    top_k: int = TOP_K,
    min_points: int = MIN_CLUSTER_POINTS,
    stay_speed: float = STAY_SPEED_MPS,
) -> List[Anchor]:
    """Cluster low-speed points into stay anchors (homes / workplaces / etc.)."""
    buckets: dict[Tuple[float, float], List[TrackPoint]] = defaultdict(list)
    for p in points:
        # speed == -1 is unknown; still useful near residences when dense
        if p.speed > stay_speed:
            continue
        buckets[_grid_key(p.lon, p.lat)].append(p)

    ranked: List[Anchor] = []
    for (glon, glat), pts in buckets.items():
        if len(pts) < min_points:
            continue
        lon = sum(p.lon for p in pts) / len(pts)
        lat = sum(p.lat for p in pts) / len(pts)
        ranked.append(Anchor(lon=lon, lat=lat, count=len(pts), source="auto"))

    ranked.sort(key=lambda a: -a.count)
    return ranked[:top_k]


def merge_anchors(
    auto: Sequence[Anchor],
    manual: Sequence[Tuple[float, float]],
    *,
    merge_within_m: float = 150.0,
) -> List[Anchor]:
    """Merge auto-discovered anchors with optional manual --home points."""
    out: List[Anchor] = list(auto)
    for lon, lat in manual:
        too_close = False
        for a in out:
            if haversine_m(lon, lat, a.lon, a.lat) < merge_within_m:
                too_close = True
                break
        if not too_close:
            out.append(Anchor(lon=lon, lat=lat, count=0, source="manual"))
    return out


def nearest_anchor(
    lon: float, lat: float, anchors: Sequence[Anchor]
) -> Optional[Tuple[Anchor, float]]:
    if not anchors:
        return None
    best: Optional[Tuple[Anchor, float]] = None
    for a in anchors:
        d = haversine_m(lon, lat, a.lon, a.lat)
        if best is None or d < best[1]:
            best = (a, d)
    return best


def near_any_anchor(
    lon: float, lat: float, anchors: Sequence[Anchor], radius_m: float = NEAR_ANCHOR_M
) -> bool:
    hit = nearest_anchor(lon, lat, anchors)
    return hit is not None and hit[1] < radius_m
