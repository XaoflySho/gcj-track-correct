#!/usr/bin/env python3
"""Compare two trajectory CSVs (Python vs JS) by dataTime.

Reports row-count mismatch, missing timestamps, and lon/lat deltas.
Exit 0 if every shared row is within --tol degrees (default 1e-6).
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Dict, Tuple


def time_key(fieldnames) -> str:
    if "dataTime" in fieldnames:
        return "dataTime"
    if "timestamp" in fieldnames:
        return "timestamp"
    raise SystemExit("CSV missing dataTime/timestamp")


def load_rows(path: Path) -> Tuple[str, Dict[int, Tuple[float, float]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit(f"Empty CSV: {path}")
        key = time_key(reader.fieldnames)
        out: Dict[int, Tuple[float, float]] = {}
        for row in reader:
            t = int(row[key])
            out[t] = (float(row["longitude"]), float(row["latitude"]))
    return key, out


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diff two corrected track CSVs.")
    parser.add_argument("--python", "-p", required=True, type=Path, help="Python output CSV")
    parser.add_argument("--js", "-j", required=True, type=Path, help="JS output CSV")
    parser.add_argument(
        "--tol",
        type=float,
        default=1e-6,
        help="Max allowed lon/lat delta in degrees (default 1e-6)",
    )
    args = parser.parse_args(argv)

    _, py_rows = load_rows(args.python)
    _, js_rows = load_rows(args.js)

    only_py = sorted(set(py_rows) - set(js_rows))
    only_js = sorted(set(js_rows) - set(py_rows))
    shared = sorted(set(py_rows) & set(js_rows))

    max_ddeg = 0.0
    max_dm = 0.0
    n_over = 0
    worst_t = None
    for t in shared:
        lon_a, lat_a = py_rows[t]
        lon_b, lat_b = js_rows[t]
        ddeg = max(abs(lon_a - lon_b), abs(lat_a - lat_b))
        dm = haversine_m(lon_a, lat_a, lon_b, lat_b)
        if ddeg > max_ddeg:
            max_ddeg = ddeg
            worst_t = t
        if dm > max_dm:
            max_dm = dm
        if ddeg > args.tol:
            n_over += 1

    print(f"Python rows: {len(py_rows)}")
    print(f"JS rows:     {len(js_rows)}")
    print(f"Shared:      {len(shared)}")
    print(f"Only Python: {len(only_py)}")
    print(f"Only JS:     {len(only_js)}")
    print(f"Max |Δdeg|:  {max_ddeg:.12f} (t={worst_t})")
    print(f"Max Δm:      {max_dm:.6f}")
    print(f"Over tol:    {n_over} (tol={args.tol})")
    if only_py[:5]:
        print(f"  sample only-Python t: {only_py[:5]}")
    if only_js[:5]:
        print(f"  sample only-JS t: {only_js[:5]}")

    ok = not only_py and not only_js and n_over == 0
    if not ok:
        print("FAIL")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
