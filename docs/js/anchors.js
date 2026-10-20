/** Discover stay/home anchors from trajectory data. */

import { haversineM } from "./detect.js";

export const GRID_DECIMALS = 3;
export const STAY_SPEED_MPS = 0.5;
export const TOP_K = 5;
export const MIN_CLUSTER_POINTS = 20;
export const NEAR_ANCHOR_M = 80.0;

function pythonRound(value, ndigits) {
  const factor = 10 ** ndigits;
  const scaled = value * factor;
  const sign = scaled < 0 ? -1 : 1;
  const abs = Math.abs(scaled);
  const floor = Math.floor(abs);
  const diff = abs - floor;
  let n;
  if (diff > 0.5) n = floor + 1;
  else if (diff < 0.5) n = floor;
  else n = floor % 2 === 0 ? floor : floor + 1;
  return (sign * n) / factor;
}

function gridKey(lon, lat) {
  return `${pythonRound(lon, GRID_DECIMALS)},${pythonRound(lat, GRID_DECIMALS)}`;
}

export function discoverStayAnchors(
  points,
  topK = TOP_K,
  minPoints = MIN_CLUSTER_POINTS,
  staySpeed = STAY_SPEED_MPS
) {
  const buckets = new Map();
  for (const p of points) {
    if (p.speed > staySpeed) continue;
    const key = gridKey(p.lon, p.lat);
    let list = buckets.get(key);
    if (!list) {
      list = [];
      buckets.set(key, list);
    }
    list.push(p);
  }

  const ranked = [];
  for (const pts of buckets.values()) {
    if (pts.length < minPoints) continue;
    let lon = 0;
    let lat = 0;
    for (const p of pts) {
      lon += p.lon;
      lat += p.lat;
    }
    ranked.push({
      lon: lon / pts.length,
      lat: lat / pts.length,
      count: pts.length,
      source: "auto",
    });
  }

  ranked.sort((a, b) => b.count - a.count);
  return ranked.slice(0, topK);
}

export function nearestAnchor(lon, lat, anchors) {
  if (!anchors.length) return null;
  let best = null;
  for (const a of anchors) {
    const d = haversineM(lon, lat, a.lon, a.lat);
    if (best === null || d < best[1]) best = [a, d];
  }
  return best;
}

export function nearAnyAnchor(lon, lat, anchors, radiusM = NEAR_ANCHOR_M) {
  const hit = nearestAnchor(lon, lat, anchors);
  return hit !== null && hit[1] < radiusM;
}
