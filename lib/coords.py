"""WGS-84 / GCJ-02 conversion via the public coordTransform library."""

from __future__ import annotations

import coordTransform as ct


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    """Convert WGS-84 to GCJ-02. Outside China, returns input unchanged."""
    result = ct.wgs84_to_gcj02(lon, lat)
    return float(result[0]), float(result[1])


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    """Convert GCJ-02 to WGS-84. Outside China, returns input unchanged."""
    result = ct.gcj02_to_wgs84(lon, lat)
    return float(result[0]), float(result[1])


def out_of_china(lon: float, lat: float) -> bool:
    return bool(ct.out_of_china(lon, lat))
