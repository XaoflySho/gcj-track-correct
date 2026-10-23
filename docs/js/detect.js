/** Detect GCJ-02 contamination in driving tracks and label points. */

import { gcj02ToWgs84, wgs84ToGcj02 } from "./coords.js";

export const SEGMENT_GAP_S = 600;
export const DRIVE_MIN_SPEED_MPS = 8.0;

export const MAX_SWITCH_DT_S = 20;
export const MAX_SWITCH_DT_LONG_S = 600;
export const LONG_DT_ERR_M = 35.0;
export const MIN_JUMP_M = 250.0;
export const MAX_JUMP_M = 700.0;
export const MATCH_ERR_M = 40.0;
export const MATCH_MARGIN_M = 15.0;

export const MAX_LINK_DT_S = 40;
export const SAME_FRAME_ERR_M = 40.0;

export const MAX_PAIR_POINTS = 50;
export const MAX_PAIR_DT_S = 600;

export const DEDUPE_DISTANCE_M = 5.0;

export const PAIR_INTERIOR_MAX_M = 250.0;
export const SINGLE_MATCH_M = 100.0;
export const BOUNDARY_IMPROVE_M = 50.0;

const CST_OFFSET_MS = 8 * 3600 * 1000;

export function TrackPoint(index, t, lon, lat, speed, accuracy, altitude, raw) {
  return { index, t, lon, lat, speed, accuracy, altitude, raw };
}

export function SwitchEvent(afterLocalIdx, kind, errM, jumpM, dtS) {
  return {
    after_local_idx: afterLocalIdx,
    kind,
    err_m: errM,
    jump_m: jumpM,
    dt_s: dtS,
  };
}

export function haversineM(lon1, lat1, lon2, lat2) {
  const r = 6371000.0;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dlmb = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dphi / 2) ** 2 +
    Math.cos(p1) * Math.cos(p2) * Math.sin(dlmb / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

export function bearingUnitEn(a, b) {
  const e = (b.lon - a.lon) * 111320.0 * Math.cos((a.lat * Math.PI) / 180);
  const n = (b.lat - a.lat) * 110540.0;
  const length = Math.hypot(e, n);
  if (length < 1.0) return [0.0, 0.0];
  return [e / length, n / length];
}

export function offsetPoint(lon, lat, eastM, northM) {
  return [
    lon + eastM / (111320.0 * Math.cos((lat * Math.PI) / 180)),
    lat + northM / 110540.0,
  ];
}

export function pathStats(coords) {
  if (coords.length < 2) return [0.0, 0.0, 0.0];
  const steps = [];
  for (let i = 0; i < coords.length - 1; i++) {
    const a = coords[i];
    const b = coords[i + 1];
    steps.push(haversineM(a[0], a[1], b[0], b[1]));
  }
  let total = 0;
  let maxStep = steps[0];
  for (const s of steps) {
    total += s;
    if (s > maxStep) maxStep = s;
  }
  return [total, total / steps.length, maxStep];
}

export function segmentIndices(times, gapS = SEGMENT_GAP_S) {
  if (!times.length) return [];
  const segs = [[0]];
  for (let i = 1; i < times.length; i++) {
    if (times[i] - times[i - 1] > gapS) segs.push([i]);
    else segs[segs.length - 1].push(i);
  }
  return segs;
}

export function maxValidSpeed(points) {
  const speeds = [];
  for (const p of points) {
    if (p.speed >= 0) speeds.push(p.speed);
  }
  if (!speeds.length) return -1.0;
  let m = speeds[0];
  for (const s of speeds) if (s > m) m = s;
  return m;
}

export function detectSwitches(points) {
  const switches = [];
  for (let j = 1; j < points.length; j++) {
    const a = points[j - 1];
    const b = points[j];
    const dt = b.t - a.t;
    if (dt <= 0) continue;
    const jump = haversineM(a.lon, a.lat, b.lon, b.lat);
    if (!(MIN_JUMP_M <= jump && jump <= MAX_JUMP_M)) continue;

    const spdA = Math.max(a.speed, 0.0);
    const spdB = Math.max(b.speed, 0.0);
    const spd = (spdA + spdB) / 2.0;
    if (dt <= MAX_LINK_DT_S && Math.abs(jump - spd * dt) < SAME_FRAME_ERR_M) {
      continue;
    }
    let ue = 0.0;
    let un = 0.0;
    if (j >= 2) {
      [ue, un] = bearingUnitEn(points[j - 2], a);
    }

    let predLon;
    let predLat;
    if (dt <= MAX_SWITCH_DT_S) {
      const moveM = spd * dt;
      [predLon, predLat] = offsetPoint(a.lon, a.lat, ue * moveM, un * moveM);
    } else {
      predLon = a.lon;
      predLat = a.lat;
    }

    const gPred = wgs84ToGcj02(predLon, predLat);
    const wPred = gcj02ToWgs84(predLon, predLat);
    const aGcj = wgs84ToGcj02(a.lon, a.lat);
    const aWgs = gcj02ToWgs84(a.lon, a.lat);
    const errW2g = Math.min(
      haversineM(gPred[0], gPred[1], b.lon, b.lat),
      haversineM(aGcj[0], aGcj[1], b.lon, b.lat)
    );
    const errG2w = Math.min(
      haversineM(wPred[0], wPred[1], b.lon, b.lat),
      haversineM(aWgs[0], aWgs[1], b.lon, b.lat)
    );
    const best = Math.min(errW2g, errG2w);
    const worst = Math.max(errW2g, errG2w);
    const strongDual = best <= 120.0 && worst >= 400.0;

    let errLimit;
    if (dt <= MAX_SWITCH_DT_S || dt <= 60) {
      errLimit = strongDual ? 120.0 : 80.0;
      if (best > errLimit) continue;
    } else if (dt <= MAX_SWITCH_DT_LONG_S) {
      if (best > LONG_DT_ERR_M) continue;
      errLimit = LONG_DT_ERR_M;
    } else {
      continue;
    }

    if (errW2g + MATCH_MARGIN_M < errG2w && errW2g <= errLimit) {
      switches.push(SwitchEvent(j, "W2G", errW2g, jump, dt));
    } else if (errG2w + MATCH_MARGIN_M < errW2g && errG2w <= errLimit) {
      switches.push(SwitchEvent(j, "G2W", errG2w, jump, dt));
    }
  }
  return switches;
}

function wgsRefsAfterG2w(points, switches, j) {
  const n = points.length;
  const spikeIdx = new Set();
  for (const s of switches) {
    if (s.kind === "W2G" && j < s.after_local_idx && s.after_local_idx < j + 6) {
      spikeIdx.add(s.after_local_idx);
    }
  }
  for (let i = 0; i < switches.length - 1; i++) {
    const a = switches[i];
    const b = switches[i + 1];
    if (
      a.kind === "W2G" &&
      b.kind === "G2W" &&
      j <= a.after_local_idx &&
      a.after_local_idx < b.after_local_idx &&
      b.after_local_idx <= j + 8 &&
      b.after_local_idx - a.after_local_idx <= 4
    ) {
      for (let k = a.after_local_idx; k < b.after_local_idx; k++) {
        spikeIdx.add(k);
      }
    }
  }

  const refs = [];
  for (let k = j; k < Math.min(n, j + 8); k++) {
    if (spikeIdx.has(k)) continue;
    refs.push(points[k]);
    if (refs.length >= 3) break;
  }
  if (!refs.length && j < n) return [points[j]];
  return refs;
}

function walkGcjTowardWgsRef(points, labels, startK, step, refs) {
  if (!refs.length) return;
  const n = points.length;
  let k = startK;
  while (k >= 0 && k < n) {
    const pk = points[k];
    let dRaw = Infinity;
    let dConv = Infinity;
    const conv = gcj02ToWgs84(pk.lon, pk.lat);
    for (const r of refs) {
      const raw = haversineM(pk.lon, pk.lat, r.lon, r.lat);
      const c = haversineM(conv[0], conv[1], r.lon, r.lat);
      if (raw < dRaw) dRaw = raw;
      if (c < dConv) dConv = c;
    }

    let chainOk = false;
    const labNb = k - step;
    if (labNb >= 0 && labNb < n && labels[labNb] === "G") {
      const nb = points[labNb];
      const nbC = gcj02ToWgs84(nb.lon, nb.lat);
      const stepRaw = haversineM(pk.lon, pk.lat, nb.lon, nb.lat);
      const stepBoth = haversineM(conv[0], conv[1], nbC[0], nbC[1]);
      if (stepRaw <= 150.0 && Math.abs(stepBoth - stepRaw) <= 40.0) {
        chainOk = true;
      }
    }

    if (dRaw < 80.0 && !chainOk) break;
    if (
      chainOk ||
      (dConv < 100.0 && dRaw > 200.0) ||
      (dConv + 80.0 < dRaw && dConv < 220.0)
    ) {
      labels[k] = "G";
      k += step;
      continue;
    }
    break;
  }
}

export function propagateLabels(points, switches) {
  const n = points.length;
  if (!switches.length) return Array(n).fill("U");

  const labels = Array(n).fill("W");

  function handleW2g(j) {
    labels[j] = "G";
    let refs = points.slice(Math.max(0, j - 3), j);
    if (!refs.length && j > 0) refs = [points[j - 1]];
    walkGcjTowardWgsRef(points, labels, j + 1, 1, refs);
  }

  function handleG2w(j) {
    if (j <= 0) return;
    labels[j - 1] = "G";
    const refs = wgsRefsAfterG2w(points, switches, j);
    walkGcjTowardWgsRef(points, labels, j - 2, -1, refs);
  }

  let i = 0;
  while (i < switches.length) {
    const sw = switches[i];
    if (
      sw.kind === "W2G" &&
      i + 1 < switches.length &&
      switches[i + 1].kind === "G2W"
    ) {
      const start = sw.after_local_idx;
      const end = switches[i + 1].after_local_idx;
      const span = end - start;
      if (end > start && span <= MAX_PAIR_POINTS) {
        let interiorOk = true;
        if (end - start >= 2) {
          let maxInterior = 0;
          for (let j = start; j < end - 1; j++) {
            const d = haversineM(
              points[j].lon,
              points[j].lat,
              points[j + 1].lon,
              points[j + 1].lat
            );
            if (d > maxInterior) maxInterior = d;
          }
          if (maxInterior > PAIR_INTERIOR_MAX_M) interiorOk = false;
        }
        let enterOk = true;
        let leaveOk = true;
        if (start > 0) {
          const prev = points[start - 1];
          const first = points[start];
          const firstC = gcj02ToWgs84(first.lon, first.lat);
          const gapRaw = haversineM(prev.lon, prev.lat, first.lon, first.lat);
          const gapC = haversineM(prev.lon, prev.lat, firstC[0], firstC[1]);
          enterOk = gapC <= gapRaw - BOUNDARY_IMPROVE_M;
        }
        if (end < n) {
          const last = points[end - 1];
          const nxt = points[end];
          const lastC = gcj02ToWgs84(last.lon, last.lat);
          const gapRaw = haversineM(last.lon, last.lat, nxt.lon, nxt.lat);
          const gapC = haversineM(lastC[0], lastC[1], nxt.lon, nxt.lat);
          leaveOk = gapC <= gapRaw - BOUNDARY_IMPROVE_M;
        }
        if (interiorOk && enterOk && leaveOk) {
          for (let j = start; j < end; j++) labels[j] = "G";
          i += 2;
          continue;
        }
      }
      handleW2g(start);
      handleG2w(end);
      i += 2;
      continue;
    }

    if (sw.kind === "W2G") handleW2g(sw.after_local_idx);
    else if (sw.kind === "G2W") handleG2w(sw.after_local_idx);
    i += 1;
  }

  if (!labels.some((lab) => lab === "G")) return Array(n).fill("U");
  return labels;
}

function jumpCount(coords, thr = MIN_JUMP_M) {
  if (coords.length < 2) return 0;
  let n = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const a = coords[i];
    const b = coords[i + 1];
    if (haversineM(a[0], a[1], b[0], b[1]) >= thr) n += 1;
  }
  return n;
}

export function gcjRuns(labels) {
  const runs = [];
  let i = 0;
  const n = labels.length;
  while (i < n) {
    if (labels[i] !== "G") {
      i += 1;
      continue;
    }
    let j = i;
    while (j < n && labels[j] === "G") j += 1;
    runs.push([i, j]);
    i = j;
  }
  return runs;
}

export function verifyGcjLabels(points, labels) {
  const out = labels.slice();
  for (const [start, end] of gcjRuns(labels)) {
    let enterOk = true;
    let leaveOk = true;
    if (start > 0 && out[start - 1] !== "G") {
      const prev = points[start - 1];
      const first = points[start];
      const firstC = gcj02ToWgs84(first.lon, first.lat);
      const gapRaw = haversineM(prev.lon, prev.lat, first.lon, first.lat);
      const gapC = haversineM(prev.lon, prev.lat, firstC[0], firstC[1]);
      enterOk = gapC <= gapRaw - BOUNDARY_IMPROVE_M;
    }
    if (end < points.length && out[end] !== "G") {
      const last = points[end - 1];
      const nxt = points[end];
      const lastC = gcj02ToWgs84(last.lon, last.lat);
      const gapRaw = haversineM(last.lon, last.lat, nxt.lon, nxt.lat);
      const gapC = haversineM(lastC[0], lastC[1], nxt.lon, nxt.lat);
      leaveOk = gapC <= gapRaw - BOUNDARY_IMPROVE_M;
    }

    let ok;
    if (end - start === 1) {
      const j = start;
      const p = points[j];
      const converted = gcj02ToWgs84(p.lon, p.lat);
      let matched = false;
      const k0 = Math.max(0, j - 4);
      const k1 = Math.min(points.length, j + 5);
      for (let k = k0; k < k1; k++) {
        if (k === j) continue;
        if (Math.abs(points[k].t - p.t) > MAX_SWITCH_DT_LONG_S) continue;
        if (
          haversineM(converted[0], converted[1], points[k].lon, points[k].lat) <
          SINGLE_MATCH_M
        ) {
          matched = true;
          break;
        }
      }
      ok = matched && enterOk && leaveOk;
    } else {
      ok = enterOk && leaveOk;
      if (!ok && leaveOk && end - start >= 3) {
        let maxInterior = 0;
        for (let j = start; j < end - 1; j++) {
          const d = haversineM(
            points[j].lon,
            points[j].lat,
            points[j + 1].lon,
            points[j + 1].lat
          );
          if (d > maxInterior) maxInterior = d;
        }
        if (maxInterior <= 150.0) ok = true;
      }
    }

    if (!ok) {
      for (let j = start; j < end; j++) out[j] = "W";
    }
  }
  if (!out.some((lab) => lab === "G")) return Array(out.length).fill("U");
  return out;
}

export function analyzeSegment(points) {
  const maxSpd = maxValidSpeed(points);
  const isDrive = maxSpd >= DRIVE_MIN_SPEED_MPS;
  if (!isDrive) {
    return {
      points,
      is_drive: false,
      labels: Array(points.length).fill("U"),
      switches: [],
      max_speed: maxSpd,
      t0: points[0].t,
      t1: points[points.length - 1].t,
      gcj_count: 0,
    };
  }

  const switches = detectSwitches(points);
  let labels = propagateLabels(points, switches);
  if (labels.some((lab) => lab === "G")) {
    labels = verifyGcjLabels(points, labels);
  }

  if (labels.some((lab) => lab === "G")) {
    const beforeCoords = points.map((p) => [p.lon, p.lat]);
    const trial = points.map((p, i) =>
      labels[i] === "G" ? gcj02ToWgs84(p.lon, p.lat) : [p.lon, p.lat]
    );
    const [, meanB, maxB] = pathStats(beforeCoords);
    const [, meanA, maxA] = pathStats(trial);
    const jumpsB = jumpCount(beforeCoords);
    const jumpsA = jumpCount(trial);
    const improved =
      jumpsA <= jumpsB &&
      maxA <= maxB + 30.0 &&
      (maxA <= maxB - 30.0 || meanA <= meanB - 8.0 || jumpsA < jumpsB);
    if (!improved) labels = Array(points.length).fill("U");
  }

  let gcjCount = 0;
  for (const lab of labels) if (lab === "G") gcjCount += 1;

  return {
    points,
    is_drive: true,
    labels,
    switches: switches.slice(),
    max_speed: maxSpd,
    t0: points[0].t,
    t1: points[points.length - 1].t,
    gcj_count: gcjCount,
  };
}

function formatCoord(n) {
  return n.toFixed(6);
}

export function correctPoints(points, labels, dedupe = true) {
  const corrected = [];
  let fixed = 0;
  const removed = [];

  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    const lab = labels[i];
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

    if (dedupe && corrected.length) {
      const prev = corrected[corrected.length - 1];
      if (
        haversineM(prev.lon, prev.lat, lon, lat) < DEDUPE_DISTANCE_M &&
        Math.abs(prev.t - newP.t) <= MAX_SWITCH_DT_S
      ) {
        removed.push(newP.index);
        continue;
      }
    }
    corrected.push(newP);
  }

  return [corrected, fixed, removed];
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
