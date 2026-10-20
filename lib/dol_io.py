"""Load / write 人生点点 (DoL) trajectory CSV exports."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Sequence

from .detect import TrackPoint


TIME_KEYS = ("timestamp", "dataTime")


def time_key(fieldnames: Sequence[str] | None) -> str:
    if not fieldnames:
        raise ValueError("Empty CSV header")
    for key in TIME_KEYS:
        if key in fieldnames:
            return key
    raise ValueError(
        f"CSV missing time column (expected one of {TIME_KEYS}): {list(fieldnames)}"
    )


def is_dol_csv(fieldnames: Sequence[str] | None) -> bool:
    return bool(fieldnames) and "timestamp" in fieldnames


def load_dol_csv(path: Path) -> List[TrackPoint]:
    """Load DoL (or compatible) CSV; preserve every column in TrackPoint.raw."""
    points: List[TrackPoint] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"Empty or invalid CSV: {path}")
        tkey = time_key(reader.fieldnames)
        for i, row in enumerate(reader):
            points.append(
                TrackPoint(
                    index=i,
                    t=int(row[tkey]),
                    lon=float(row["longitude"]),
                    lat=float(row["latitude"]),
                    speed=float(row["speed"]),
                    accuracy=float(row["accuracy"]),
                    altitude=float(row["altitude"]),
                    raw=dict(row),
                )
            )
    return points


def write_dol_csv(path: Path, rows: Sequence[dict], fieldnames: Sequence[str]) -> None:
    """Write CSV keeping the original column order; only lon/lat may change."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
