/** DoL post-processing: lateral spikes and residual jump warnings. */

import { gcj02ToWgs84 } from "./coords.js";
import { fmtCst, haversineM, MAX_LINK_DT_S, SAME_FRAME_ERR_M } from "./detect.js";

export const MIN_JUMP_EXCESS_M = 250.0;

export const LATERAL_CROSS_M = 300.0;
export const LATERAL_EXCESS_M = 200.0;
export const LATERAL_MAX_DT_S = 20;
export const MATCH_ERR_M = 50.0;

export const WARN_EXCESS_M = 200.0;
export const WARN_MAX_DT_S = 30;

function expectM(speed, dt) {
  return Math.max(speed, 0.0) * dt;
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

export function fillGcjByKinematics(points, labels) {
  const out = labels.slice();
  const n = points.length;
  for (let i = 1; i < n; i++) {
    if (out[i] === "U" || out[i] === "G") continue;
    const a = points[i - 1];
    const b = points[i];
    const dt = b.t - a.t;
    if (dt <= 0 || dt > MAX_LINK_DT_S) continue;
    const exp = expectM(b.speed, dt);
    const raw = haversineM(a.lon, a.lat, b.lon, b.lat);
    const bWgs = gcj02ToWgs84(b.lon, b.lat);
    const errRaw = Math.abs(raw - exp);
    const errBGcj = Math.abs(haversineM(a.lon, a.lat, bWgs[0], bWgs[1]) - exp);
    const rawOk = errRaw < SAME_FRAME_ERR_M;
    const bGcjOk =
      errBGcj < MATCH_ERR_M && raw > exp + MIN_JUMP_EXCESS_M && !rawOk;
    if (bGcjOk) out[i] = "G";
    else if (out[i - 1] === "G" && rawOk) out[i] = "G";
    else if (out[i - 1] === "G" && !rawOk && errRaw < MATCH_ERR_M * 3) {
      if (errBGcj + 15.0 < errRaw) continue;
      out[i] = "G";
    }
  }
  return out;
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

export function gcjRunsFromLabels(points, labels) {
  const runs = [];
  let start = null;
  const seq = labels.concat(["W"]);
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
  return runs;
}

export function summarizeRuns(runs) {
  return runs.map(
    (r) =>
      `${fmtCst(r.t0)} → ${fmtCst(r.t1)}  点数 ${r.n}  (行 ${r.start + 2}–${r.end + 1})`
  );
}
