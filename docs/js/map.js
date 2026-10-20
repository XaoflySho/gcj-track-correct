const MIN_SHIFT_M = 5;
export const POINT_WARN_LIMIT = 8000;
export const MAX_SPAN_S = 31 * 86400;
const CST_OFFSET_MS = 8 * 3600 * 1000;

let map = null;
let layerGroup = null;
let selectMarker = null;
let pickHandler = null;
let suppressMapPick = false;

function emitPick(latlng, hint) {
  if (!pickHandler) return;
  suppressMapPick = true;
  try {
    pickHandler(latlng, hint);
  } finally {
    setTimeout(() => {
      suppressMapPick = false;
    }, 0);
  }
}

export function haversineM(lon1, lat1, lon2, lat2) {
  const R = 6371000;
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLon = (lon2 - lon1) * toRad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

export function fmtCst(ts) {
  const d = new Date(ts * 1000 + CST_OFFSET_MS);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  const ss = String(d.getUTCSeconds()).padStart(2, "0");
  return `${y}-${m}-${day} ${hh}:${mm}:${ss}`;
}

export function cstDateParts(ts) {
  const d = new Date(ts * 1000 + CST_OFFSET_MS);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function cstClockParts(ts) {
  const d = new Date(ts * 1000 + CST_OFFSET_MS);
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function parseCstDateTime(dayStr, clockStr, endOfDay) {
  const dm = dayStr.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!dm) throw new Error("日期格式无效");
  const y = Number(dm[1]);
  const mo = Number(dm[2]);
  const d = Number(dm[3]);
  let hh = 0;
  let mm = 0;
  let ss = 0;
  if (clockStr) {
    const tm = clockStr.match(/^(\d{2}):(\d{2})(?::(\d{2}))?$/);
    if (!tm) throw new Error("时分格式无效");
    hh = Number(tm[1]);
    mm = Number(tm[2]);
    ss = tm[3] != null ? Number(tm[3]) : 0;
    if (!tm[3] && endOfDay) ss = 59;
  } else if (endOfDay) {
    hh = 23;
    mm = 59;
    ss = 59;
  }
  return Date.UTC(y, mo - 1, d, hh, mm, ss) / 1000 - 8 * 3600;
}

export function windowFromParts(dateFrom, clockFrom, dateTo, clockTo) {
  const t0 = parseCstDateTime(dateFrom, clockFrom || "", false);
  const t1 = parseCstDateTime(dateTo, clockTo || "", true);
  if (t1 < t0) throw new Error("结束时间不能早于开始时间");
  if (t1 - t0 > MAX_SPAN_S + 59) {
    throw new Error("时间跨度不能超过 31 天，请缩小范围");
  }
  return { t0, t1, endExclusive: false };
}

export function filterByTime(points, t0, t1, endExclusive) {
  if (endExclusive) return points.filter((p) => p.t >= t0 && p.t < t1);
  return points.filter((p) => p.t >= t0 && p.t <= t1);
}

export function alignTracks(original, corrected) {
  const changed = [];
  const removed = [];
  const byT = new Map();
  for (const p of corrected) byT.set(p.t, p);
  for (const p of original) {
    const q = byT.get(p.t);
    if (!q) {
      removed.push({ lat: p.lat, lon: p.lon, t: p.t, time_cst: fmtCst(p.t) });
      continue;
    }
    const shift = haversineM(p.lon, p.lat, q.lon, q.lat);
    if (shift >= MIN_SHIFT_M) {
      changed.push({
        lat: q.lat,
        lon: q.lon,
        orig_lat: p.lat,
        orig_lon: p.lon,
        t: p.t,
        time_cst: fmtCst(p.t),
        shift_m: Math.round(shift * 10) / 10,
      });
    }
  }
  return {
    originalLatLngs: original.map((p) => [p.lat, p.lon]),
    correctedLatLngs: corrected.map((p) => [p.lat, p.lon]),
    changed,
    removed,
    nOriginal: original.length,
    nCorrected: corrected.length,
  };
}

export function initMap(targetId = "map") {
  map = L.map(targetId, {
    preferCanvas: true,
    zoomControl: false,
  }).setView([34.2, 108.9], 12);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  layerGroup = L.layerGroup().addTo(map);
  map.getContainer()._leafletMap = map;
  map.on("click", (e) => {
    if (suppressMapPick) return;
    if (pickHandler) pickHandler(e.latlng);
  });
  return map;
}

export function getMap() {
  return map;
}

export function setPickHandler(fn) {
  pickHandler = fn;
}

export function pickRadiusM() {
  if (!map) return 80;
  const center = map.getCenter();
  const p = map.latLngToContainerPoint(center);
  const ll = map.containerPointToLatLng(L.point(p.x + 36, p.y));
  return Math.max(30, map.distance(center, ll));
}

export function nearestPoint(latlng, points, maxM) {
  if (!points || !points.length) return null;
  let best = null;
  let bestD = Infinity;
  for (const p of points) {
    const d = haversineM(latlng.lng, latlng.lat, p.lon, p.lat);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  if (!best || bestD > maxM) return null;
  return { point: best, distM: bestD };
}

export function setSelectMarker(lat, lon, onDragEnd, draggable = true) {
  if (!map) return;
  if (selectMarker) {
    selectMarker.remove();
    selectMarker = null;
  }
  selectMarker = L.marker([lat, lon], {
    draggable,
    zIndexOffset: 1200,
    title: draggable ? "拖动以手动修正" : "已删除，可恢复到输出",
  }).addTo(map);
  if (draggable && onDragEnd) {
    selectMarker.on("dragend", () => {
      const ll = selectMarker.getLatLng();
      onDragEnd(ll.lng, ll.lat);
    });
  }
}

export function moveSelectMarker(lat, lon) {
  if (selectMarker) selectMarker.setLatLng([lat, lon]);
}

export function clearSelectMarker() {
  if (selectMarker) {
    selectMarker.remove();
    selectMarker = null;
  }
}

export function clearLayers() {
  if (layerGroup) layerGroup.clearLayers();
}

export function drawView(view, options = {}) {
  const fit = options.fit !== false;
  clearLayers();
  const bounds = [];

  if (view.originalLatLngs.length) {
    const line = L.polyline(view.originalLatLngs, {
      color: "#888",
      weight: 4,
      opacity: 0.55,
      bubblingMouseEvents: false,
    }).addTo(layerGroup);
    line.on("click", (e) => {
      L.DomEvent.stop(e);
      emitPick(e.latlng);
    });
    view.originalLatLngs.forEach((ll) => bounds.push(ll));
  }
  if (view.correctedLatLngs.length) {
    const line = L.polyline(view.correctedLatLngs, {
      color: "#1a73e8",
      weight: 4,
      opacity: 0.9,
      bubblingMouseEvents: false,
    }).addTo(layerGroup);
    line.on("click", (e) => {
      L.DomEvent.stop(e);
      emitPick(e.latlng);
    });
    view.correctedLatLngs.forEach((ll) => bounds.push(ll));
  }
  for (const p of view.changed) {
    const m = L.circleMarker([p.lat, p.lon], {
      radius: 6,
      color: "#c06000",
      fillColor: "#f09000",
      fillOpacity: 0.9,
      weight: 1,
      bubblingMouseEvents: false,
    }).addTo(layerGroup);
    m.on("click", (e) => {
      L.DomEvent.stop(e);
      emitPick({ lat: p.lat, lng: p.lon }, { kind: "out", t: p.t });
    });
    bounds.push([p.lat, p.lon]);
  }
  for (const p of view.removed) {
    const m = L.circleMarker([p.lat, p.lon], {
      radius: 5,
      color: "#666",
      fillColor: "#ffffff",
      fillOpacity: 0.35,
      weight: 2,
      fill: true,
      bubblingMouseEvents: false,
    }).addTo(layerGroup);
    m.on("click", (e) => {
      L.DomEvent.stop(e);
      emitPick({ lat: p.lat, lng: p.lon }, { kind: "removed", t: p.t });
    });
    bounds.push([p.lat, p.lon]);
  }

  if (fit && bounds.length) {
    map.fitBounds(bounds, { padding: [40, 40] });
  }
}

export function invalidateMap() {
  if (map) map.invalidateSize();
}
