/** Kinematic GCJ-02 detection for 人生点点 (DoL) driving tracks. */

import { gcj02ToWgs84 } from "./coords.js";
import {
  DRIVE_MIN_SPEED_MPS,
  TrackPoint,
  fmtCst,
  haversineM,
  maxValidSpeed,
  segmentIndices,
} from "./detect.js";

export const MAX_LINK_DT_S = 40;
export const MIN_JUMP_EXCESS_M = 250.0;
export const MATCH_ERR_M = 50.0;
export const SAME_FRAME_ERR_M = 40.0;

export const LATERAL_CROSS_M = 300.0;
export const LATERAL_EXCESS_M = 200.0;
export const LATERAL_MAX_DT_S = 20;

export const WARN_EXCESS_M = 200.0;
export const WARN_MAX_DT_S = 30;

function expectM(speed, dt) {
  return Math.max(speed, 0.0) * dt;
}

function labelDriveSegment(points) {
  const n = points.length;
  const labels = Array(n).fill("?");

  for (let i = 1; i < n; i++) {
    const a = points[i - 1];
    const b = points[i];
    const dt = b.t - a.t;
    if (dt <= 0 || dt > MAX_LINK_DT_S) continue;
    const exp = expectM(b.speed, dt);
    const raw = haversineM(a.lon, a.lat, b.lon, b.lat);
    const bWgs = gcj02ToWgs84(b.lon, b.lat);
    const aWgs = gcj02ToWgs84(a.lon, a.lat);
    const errRaw = Math.abs(raw - exp);
    const errBGcj = Math.abs(haversineM(a.lon, a.lat, bWgs[0], bWgs[1]) - exp);
    const errAGcj = Math.abs(haversineM(aWgs[0], aWgs[1], b.lon, b.lat) - exp);

    const rawOk = errRaw < SAME_FRAME_ERR_M;
    const bGcjOk =
      errBGcj < MATCH_ERR_M && raw > exp + MIN_JUMP_EXCESS_M && !rawOk;
    const aGcjOk =
      errAGcj < MATCH_ERR_M && raw > exp + MIN_JUMP_EXCESS_M && !rawOk;

    if (rawOk && !bGcjOk && !aGcjOk) {
      if (labels[i - 1] === "?") labels[i - 1] = "W";
      if (labels[i - 1] === "W" || labels[i - 1] === "G") labels[i] = labels[i - 1];
    } else if (bGcjOk && (labels[i - 1] === "W" || labels[i - 1] === "?")) {
      labels[i - 1] = "W";
      labels[i] = "G";
    } else if (aGcjOk && (labels[i - 1] === "G" || labels[i - 1] === "?")) {
      labels[i - 1] = "G";
      labels[i] = "W";
    } else if (labels[i - 1] === "G" && !rawOk) {
      if (errAGcj + 15.0 < errRaw) labels[i] = "W";
      else if (errRaw < MATCH_ERR_M * 3) labels[i] = "G";
    }
  }

  for (let i = 1; i < n; i++) {
    if (labels[i] !== "?" || (labels[i - 1] !== "W" && labels[i - 1] !== "G")) {
      continue;
    }
    const a = points[i - 1];
    const b = points[i];
    const dt = b.t - a.t;
    if (dt <= 0 || dt > MAX_LINK_DT_S) continue;
    const exp = expectM(b.speed, dt);
    const raw = haversineM(a.lon, a.lat, b.lon, b.lat);
    if (Math.abs(raw - exp) < SAME_FRAME_ERR_M) labels[i] = labels[i - 1];
  }

  return labels.map((lab) => (lab === "?" ? "W" : lab));
}

function gcjRunsLocal(labels) {
  const runs = [];
  let start = null;
  const seq = labels.concat(["W"]);
  for (let i = 0; i < seq.length; i++) {
    const lab = seq[i];
    if (lab === "G") {
      if (start === null) start = i;
    } else if (start !== null) {
      runs.push([start, i]);
      start = null;
    }
  }
  return runs;
}

export function analyzeDolSegment(points) {
  const maxSpd = maxValidSpeed(points);
  const isDrive = maxSpd >= DRIVE_MIN_SPEED_MPS;
  if (!isDrive) {
    return {
      points,
      is_drive: false,
      labels: Array(points.length).fill("U"),
      max_speed: maxSpd,
      gcj_runs: [],
    };
  }
  const labels = labelDriveSegment(points);
  return {
    points,
    is_drive: true,
    labels,
    max_speed: maxSpd,
    gcj_runs: gcjRunsLocal(labels),
  };
}

function crossTrackM(lonA, latA, lonC, latC, lonB, latB) {
  const eC = (lonC - lonA) * 111320.0 * Math.cos((latA * Math.PI) / 180);
  const nC = (latC - latA) * 110540.0;
  const eB = (lonB - lonA) * 111320.0 * Math.cos((latA * Math.PI) / 180);
  const nB = (latB - latA) * 110540.0;
  const length = Math.hypot(eC, nC);
  if (length < 30.0) return haversineM(lonA, latA, lonB, latB);
  const ue = eC / length;
  const un = nC / length;
  return eB * -un + nB * ue;
}

export function findLateralSpikeIndices(points, labels) {
  const drop = [];
  const n = points.length;
  for (let i = 1; i < n - 1; i++) {
    if (labels[i] === "G") continue;
    const a = points[i - 1];
    const b = points[i];
    const c = points[i + 1];
    const dt1 = b.t - a.t;
    const dt2 = c.t - b.t;
    if (!(dt1 > 0 && dt1 <= LATERAL_MAX_DT_S && dt2 > 0 && dt2 <= LATERAL_MAX_DT_S)) {
      continue;
    }
    const e1 = expectM(b.speed, dt1);
    const e2 = expectM(c.speed, dt2);
    const raw1 = haversineM(a.lon, a.lat, b.lon, b.lat);
    const raw2 = haversineM(b.lon, b.lat, c.lon, c.lat);
    if (raw1 < e1 + LATERAL_EXCESS_M && raw2 < e2 + LATERAL_EXCESS_M) continue;
    const bw = gcj02ToWgs84(b.lon, b.lat);
    const w1 = haversineM(a.lon, a.lat, bw[0], bw[1]);
    const w2 = haversineM(bw[0], bw[1], c.lon, c.lat);
    if (Math.abs(w1 - e1) < MATCH_ERR_M && Math.abs(w2 - e2) < MATCH_ERR_M) continue;
    const cross = Math.abs(crossTrackM(a.lon, a.lat, c.lon, c.lat, b.lon, b.lat));
    if (cross >= LATERAL_CROSS_M) drop.push(b.index);
  }
  return drop;
}

function formatCoord(n) {
  return n.toFixed(6);
}

export function correctDolPoints(points, labels, dropIndices) {
  const dropSet = new Set(dropIndices || []);
  const out = [];
  let fixed = 0;
  const removed = [];

  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    const lab = labels[i];
    if (dropSet.has(p.index)) {
      removed.push(p.index);
      continue;
    }
    let lon = p.lon;
    let lat = p.lat;
    if (lab === "G") {
      [lon, lat] = gcj02ToWgs84(lon, lat);
      fixed += 1;
    }
    const newP = TrackPoint(p.index, p.t, lon, lat, p.speed, p.accuracy, p.altitude, {
      ...p.raw,
    });
    newP.raw.longitude = formatCoord(lon);
    newP.raw.latitude = formatCoord(lat);
    out.push(newP);
  }
  return [out, fixed, removed];
}

export function residualWarnJumps(points) {
  const warns = [];
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const dt = b.t - a.t;
    if (dt <= 0 || dt > WARN_MAX_DT_S) continue;
    const exp = expectM(b.speed, dt);
    const jump = haversineM(a.lon, a.lat, b.lon, b.lat);
    if (jump > exp + WARN_EXCESS_M) {
      warns.push({
        after_index: b.index,
        t: b.t,
        jump_m: jump,
        expect_m: exp,
        note: "修后仍偏大（非 GCJ 或未覆盖）",
        t0: fmtCst(b.t),
      });
    }
  }
  return warns;
}

export function processDolTrack(points, onProgress) {
  const times = points.map((p) => p.t);
  const segs = segmentIndices(times);

  const globalLabels = Array(points.length).fill("U");
  for (let si = 0; si < segs.length; si++) {
    const idxs = segs[si];
    const seg = idxs.map((i) => points[i]);
    const result = analyzeDolSegment(seg);
    for (let local = 0; local < idxs.length; local++) {
      globalLabels[idxs[local]] = result.labels[local];
    }
    if (onProgress && (si % 8 === 0 || si === segs.length - 1)) {
      onProgress({ processed: si + 1, total: segs.length });
    }
  }

  const drop = findLateralSpikeIndices(points, globalLabels);
  const [corrected, fixed, removed] = correctDolPoints(
    points,
    globalLabels,
    drop
  );

  const runs = [];
  let start = null;
  const seq = globalLabels.concat(["W"]);
  for (let i = 0; i < seq.length; i++) {
    const lab = seq[i];
    if (lab === "G") {
      if (start === null) start = i;
    } else if (start !== null) {
      runs.push({
        start,
        end: i,
        t0: points[start].t,
        t1: points[i - 1].t,
        n: i - start,
      });
      start = null;
    }
  }

  const warns = residualWarnJumps(corrected);
  return { corrected, fixed, removed, runs, warns };
}

export function summarizeRuns(runs) {
  return runs.map(
    (r) =>
      `${fmtCst(r.t0)} → ${fmtCst(r.t1)}  点数 ${r.n}  (行 ${r.start + 2}–${r.end + 1})`
  );
}
