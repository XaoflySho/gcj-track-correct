import { discoverStayAnchors, nearAnyAnchor } from "./anchors.js";
import { parseCsv, stringifyCsv, mapPointsFromRows, mapPointsFromTrack } from "./csv.js";
import {
  analyzeSegment,
  correctPoints,
  fmtCst,
  gcjRuns,
  pathStats,
  segmentIndices,
} from "./detect.js";

function format1(n) {
  return n.toFixed(1);
}

function format0(n) {
  return Math.abs(n).toFixed(0);
}

export function buildReport(
  inputName,
  totalIn,
  totalOut,
  fixedTotal,
  removedTotal,
  segSummaries
) {
  const lines = [
    "# 轨迹纠偏报告",
    "",
    `- 输入文件：\`${inputName}\``,
    `- 输入点数：**${totalIn}**`,
    `- 输出点数：**${totalOut}**`,
    `- GCJ→WGS 转换点数：**${fixedTotal}**`,
    `- 近重复删除点数：**${removedTotal}**`,
    "",
    "## 发生纠偏的行程",
    "",
  ];

  const correctedSegs = segSummaries.filter((s) => s.fixed > 0 || s.removed > 0);
  if (!correctedSegs.length) {
    lines.push("_未检测到 GCJ 污染。_");
  } else {
    lines.push(
      "| 开始（CST） | 结束 | 输入点数 | 输出点数 | 转换 | 删除 | " +
        "切换次数 | 最高速 m/s | 最大步进 修前→修后 |"
    );
    lines.push("|---|---|---:|---:|---:|---:|---:|---:|---|");
    const sorted = correctedSegs.slice().sort((a, b) => b.fixed - a.fixed);
    for (const s of sorted) {
      lines.push(
        `| ${s.t0} | ${s.t1} | ${s.n_in} | ${s.n_out} | ` +
          `${s.fixed} | ${s.removed} | ${s.switches} | ` +
          `${format1(s.max_spd)} | ${format0(s.max_before)}→${format0(s.max_after)} m |`
      );
    }
  }

  lines.push("", "## 驾车行程按 GCJ 切换次数排序（含未改动的）", "");
  const top = segSummaries
    .filter((s) => s.is_drive)
    .sort((a, b) => b.switches - a.switches || b.fixed - a.fixed)
    .slice(0, 20);
  if (!top.length) {
    lines.push("_无驾车行程。_");
  } else {
    lines.push("| 开始（CST） | 点数 | 切换次数 | 转换点数 | 最高速 | 状态 |");
    lines.push("|---|---:|---:|---:|---:|---|");
    for (const s of top) {
      let kind;
      if (s.fixed) kind = "已纠偏";
      else if (s.switches === 0) kind = "干净";
      else kind = "已检测未改";
      lines.push(
        `| ${s.t0} | ${s.n_in} | ${s.switches} | ${s.fixed} | ` +
          `${format1(s.max_spd)} | ${kind} |`
      );
    }
  }

  lines.push("");
  return lines.join("\n");
}

export function processPoints(points, dedupe = true, onProgress) {
  const times = points.map((p) => p.t);
  const segsIdx = segmentIndices(times);
  const anchors = discoverStayAnchors(points);

  const outRows = [];
  const summaries = [];
  let fixedTotal = 0;
  let removedTotal = 0;

  for (let si = 0; si < segsIdx.length; si++) {
    const idxs = segsIdx[si];
    const segPoints = idxs.map((i) => points[i]);
    const result = analyzeSegment(segPoints);

    const beforeCoords = segPoints.map((p) => [p.lon, p.lat]);
    const [, , maxBefore] = pathStats(beforeCoords);

    let labels = result.labels.slice();
    if (anchors.length && result.gcj_count > 0) {
      for (const [start, end] of gcjRuns(labels)) {
        let hit = false;
        for (let i = start; i < end; i++) {
          if (nearAnyAnchor(segPoints[i].lon, segPoints[i].lat, anchors)) {
            hit = true;
            break;
          }
        }
        if (hit) {
          for (let i = start; i < end; i++) labels[i] = "W";
        }
      }
      if (!labels.some((lab) => lab === "G")) {
        labels = Array(labels.length).fill("U");
      }
    }

    let gcjCount = 0;
    for (const lab of labels) if (lab === "G") gcjCount += 1;

    let corrected;
    let fixed = 0;
    let removed = [];
    if (result.is_drive && gcjCount > 0) {
      [corrected, fixed, removed] = correctPoints(segPoints, labels, dedupe);
    } else {
      corrected = segPoints;
    }

    const afterCoords = corrected.map((p) => [p.lon, p.lat]);
    const [, , maxAfter] = pathStats(afterCoords);

    fixedTotal += fixed;
    removedTotal += removed.length;
    for (const p of corrected) outRows.push(p.raw);

    summaries.push({
      t0: fmtCst(result.t0),
      t1: fmtCst(result.t1),
      n_in: segPoints.length,
      n_out: corrected.length,
      fixed,
      removed: removed.length,
      switches: result.switches.length,
      max_spd: result.max_speed,
      max_before: maxBefore,
      max_after: maxAfter,
      is_drive: result.is_drive,
    });

    if (onProgress && (si % 8 === 0 || si === segsIdx.length - 1)) {
      onProgress({ processed: si + 1, total: segsIdx.length });
    }
  }

  return { outRows, summaries, fixedTotal, removedTotal };
}

export function processCsvText(text, options = {}) {
  const dedupe = options.dedupe !== false;
  const inputName = options.inputName || "input.csv";
  const onProgress = options.onProgress;
  const points = parseCsv(text);
  const { outRows, summaries, fixedTotal, removedTotal } = processPoints(
    points,
    dedupe,
    onProgress
  );
  const report = buildReport(
    inputName,
    points.length,
    outRows.length,
    fixedTotal,
    removedTotal,
    summaries
  );
  return {
    inputName,
    totalIn: points.length,
    totalOut: outRows.length,
    fixedTotal,
    removedTotal,
    summaries,
    report,
    csvText: stringifyCsv(outRows),
    originalPoints: mapPointsFromTrack(points),
    correctedPoints: mapPointsFromRows(outRows),
  };
}
