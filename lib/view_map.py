"""Build Leaflet HTML previews comparing original vs corrected tracks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Sequence, Tuple

from .detect import TZ_CST, TrackPoint, fmt_cst, haversine_m

POINT_WARN_LIMIT = 8000


@dataclass
class AlignedView:
    original_latlngs: List[List[float]]  # [lat, lon] for Leaflet
    corrected_latlngs: List[List[float]]
    changed: List[dict]  # {lat, lon, t, shift_m, time_cst}
    removed: List[dict]  # {lat, lon, t, time_cst}
    n_original: int
    n_corrected: int


def parse_cst_datetime(value: str) -> datetime:
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=TZ_CST)
        except ValueError:
            continue
    raise ValueError(
        f"无法解析时间 {value!r}，请用 YYYY-MM-DD、YYYY-MM-DD HH:MM 或带秒"
    )


def window_from_day(day: str) -> Tuple[int, int]:
    start = parse_cst_datetime(day.strip())
    if start.hour or start.minute or start.second:
        raise ValueError(f"--day 只需日期 YYYY-MM-DD，收到 {day!r}")
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def window_from_range(start_s: str, end_s: str) -> Tuple[int, int]:
    start = parse_cst_datetime(start_s)
    end = parse_cst_datetime(end_s)
    if end < start:
        raise ValueError("--to 必须不早于 --from")
    # Inclusive end: if user gave minute precision, include the whole minute.
    if len(end_s.strip()) <= 16:  # YYYY-MM-DD HH:MM
        end = end + timedelta(seconds=59)
    return int(start.timestamp()), int(end.timestamp())


def filter_by_time(
    points: Sequence[TrackPoint], t0: int, t1: int, *, end_exclusive: bool = False
) -> List[TrackPoint]:
    if end_exclusive:
        return [p for p in points if t0 <= p.t < t1]
    return [p for p in points if t0 <= p.t <= t1]


def align_tracks(
    original: Sequence[TrackPoint],
    corrected: Sequence[TrackPoint],
    *,
    min_shift_m: float = 5.0,
) -> AlignedView:
    by_t_corr = {p.t: p for p in corrected}
    changed: List[dict] = []
    removed: List[dict] = []

    for p in original:
        q = by_t_corr.get(p.t)
        if q is None:
            removed.append(
                {
                    "lat": p.lat,
                    "lon": p.lon,
                    "t": p.t,
                    "time_cst": fmt_cst(p.t),
                }
            )
            continue
        shift = haversine_m(p.lon, p.lat, q.lon, q.lat)
        if shift >= min_shift_m:
            changed.append(
                {
                    "lat": q.lat,
                    "lon": q.lon,
                    "orig_lat": p.lat,
                    "orig_lon": p.lon,
                    "t": p.t,
                    "time_cst": fmt_cst(p.t),
                    "shift_m": round(shift, 1),
                }
            )

    return AlignedView(
        original_latlngs=[[p.lat, p.lon] for p in original],
        corrected_latlngs=[[p.lat, p.lon] for p in corrected],
        changed=changed,
        removed=removed,
        n_original=len(original),
        n_corrected=len(corrected),
    )


def write_preview_html(
    path: Path,
    view: AlignedView,
    *,
    title: str,
    subtitle: str,
) -> None:
    payload = {
        "original": view.original_latlngs,
        "corrected": view.corrected_latlngs,
        "changed": view.changed,
        "removed": view.removed,
    }
    data_json = json.dumps(payload, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape(title)}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
    crossorigin="" />
  <style>
    html, body {{ margin: 0; height: 100%; font-family: "PingFang SC", "Helvetica Neue", sans-serif; }}
    #map {{ position: absolute; inset: 0; }}
    .panel {{
      position: absolute; z-index: 1000; top: 12px; left: 12px;
      background: rgba(255,255,255,0.94); padding: 12px 14px; border-radius: 8px;
      box-shadow: 0 1px 6px rgba(0,0,0,0.18); max-width: min(360px, 90vw);
      font-size: 13px; line-height: 1.45; color: #222;
    }}
    .panel h1 {{ margin: 0 0 4px; font-size: 15px; font-weight: 600; }}
    .panel .sub {{ margin: 0 0 10px; color: #555; font-size: 12px; }}
    .legend-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
    .swatch {{ width: 22px; height: 4px; border-radius: 2px; flex-shrink: 0; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
    .dot.hollow {{ background: transparent; border: 2px solid #888; box-sizing: border-box; }}
    .note {{ margin-top: 8px; color: #666; font-size: 11px; }}
  </style>
</head>
<body>
  <div class="panel">
    <h1>{_escape(title)}</h1>
    <p class="sub">{_escape(subtitle)}</p>
    <div class="legend-row"><span class="swatch" style="background:#888;opacity:0.7"></span>原始轨迹</div>
    <div class="legend-row"><span class="swatch" style="background:#1a73e8"></span>纠偏轨迹</div>
    <div class="legend-row"><span class="dot" style="background:#f09000"></span>改动点（≥阈值）</div>
    <div class="legend-row"><span class="dot hollow"></span>删除点（近重复去除）</div>
    <p class="note">底图 OpenStreetMap（WGS-84）。请勿用高德/腾讯底图直接贴 WGS 点。</p>
  </div>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
    crossorigin=""></script>
  <script>
    const data = {data_json};
    const map = L.map('map', {{ preferCanvas: true }});
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }}).addTo(map);

    if (data.original.length) {{
      L.polyline(data.original, {{
        color: '#888', weight: 4, opacity: 0.55
      }}).addTo(map);
    }}
    if (data.corrected.length) {{
      L.polyline(data.corrected, {{
        color: '#1a73e8', weight: 4, opacity: 0.9
      }}).addTo(map);
    }}

    for (const p of data.changed) {{
      const m = L.circleMarker([p.lat, p.lon], {{
        radius: 5, color: '#c06000', fillColor: '#f09000',
        fillOpacity: 0.9, weight: 1
      }}).addTo(map);
      m.bindPopup(
        '<b>改动点</b><br/>' + p.time_cst +
        '<br/>位移 ' + p.shift_m + ' m' +
        '<br/>原 ' + p.orig_lat.toFixed(6) + ', ' + p.orig_lon.toFixed(6) +
        '<br/>新 ' + p.lat.toFixed(6) + ', ' + p.lon.toFixed(6)
      );
    }}

    for (const p of data.removed) {{
      const m = L.circleMarker([p.lat, p.lon], {{
        radius: 4, color: '#666', fillColor: 'transparent',
        fillOpacity: 0, weight: 2
      }}).addTo(map);
      m.bindPopup('<b>删除点</b><br/>' + p.time_cst);
    }}

    const all = [];
    data.original.forEach(ll => all.push(ll));
    data.corrected.forEach(ll => all.push(ll));
    data.changed.forEach(p => all.push([p.lat, p.lon]));
    data.removed.forEach(p => all.push([p.lat, p.lon]));
    if (all.length) {{
      map.fitBounds(all, {{ padding: [40, 40] }});
    }} else {{
      map.setView([34.2, 108.9], 12);
    }}
  </script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
