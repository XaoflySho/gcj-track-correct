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
import {
  fillGcjByKinematics,
  findLateralSpikeIndices,
  gcjRunsFromLabels,
  residualWarnJumps,
  summarizeRuns,
} from "./detect_dol.js";

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
  segSummaries,
  extras = {}
) {
  const runLines = extras.runLines || [];
  const removedIndices = extras.removedIndices || [];
  const warnLines = extras.warnLines || [];
  const lines = [
    "# 轨迹纠偏报告",
    "",
    `- 输入文件：\`${inputName}\``,
    `- 输入点数：**${totalIn}**`,
    `- 输出点数：**${totalOut}**`,
    `- GCJ→WGS 转换点数：**${fixedTotal}**`,
    `- 删除点数：**${removedTotal}**`,
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

  if (runLines.length) {
    lines.push("", "## GCJ 块（已转换）", "");
    for (const line of runLines) lines.push(`- ${line}`);
  }
  if (removedIndices.length) {
    lines.push("", "## 删除的点", "");
    for (const idx of removedIndices) {
      lines.push(`- 原始行号约 ${idx + 2}（0-based index ${idx}）`);
    }
  }
  if (warnLines.length) {
    lines.push("", "## 残留警告跳变", "");
    for (const line of warnLines) lines.push(`- ${line}`);
  }

  lines.push("");
  return lines.join("\n");
}

export function labelSegments(points, onProgress) {
  const times = points.map((p) => p.t);
  const segsIdx = segmentIndices(times);
  const anchors = discoverStayAnchors(points);
  const segs = [];

  for (let si = 0; si < segsIdx.length; si++) {
    const idxs = segsIdx[si];
    const segPoints = idxs.map((i) => points[i]);
    const result = analyzeSegment(segPoints);

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

    segs.push({ idxs, points: segPoints, result, labels });

    if (onProgress && (si % 8 === 0 || si === segsIdx.length - 1)) {
      onProgress({ processed: si + 1, total: segsIdx.length });
    }
  }

  return segs;
}

export function applyCorrections(segs, dedupe = true, dropIndices) {
  const dropSet = new Set(dropIndices || []);
  const outRows = [];
  const correctedPoints = [];
  const summaries = [];
  const removedAll = [];
  let fixedTotal = 0;

  for (const seg of segs) {
    const beforeCoords = seg.points.map((p) => [p.lon, p.lat]);
    const [, , maxBefore] = pathStats(beforeCoords);

    const keepPoints = [];
    const keepLabels = [];
    const dropped = [];
    for (let i = 0; i < seg.points.length; i++) {
      const p = seg.points[i];
      if (dropSet.has(p.index)) {
        dropped.push(p.index);
        continue;
      }
      keepPoints.push(p);
      keepLabels.push(seg.labels[i]);
    }

    let gcjCount = 0;
    for (const lab of keepLabels) if (lab === "G") gcjCount += 1;

    let corrected;
    let fixed = 0;
    let removed = [];
    if (seg.result.is_drive && gcjCount > 0) {
      [corrected, fixed, removed] = correctPoints(keepPoints, keepLabels, dedupe);
    } else {
      corrected = keepPoints;
    }
    removed = dropped.concat(removed);

    const afterCoords = corrected.map((p) => [p.lon, p.lat]);
    const [, , maxAfter] = pathStats(afterCoords);

    fixedTotal += fixed;
    removedAll.push(...removed);
    for (const p of corrected) {
      outRows.push(p.raw);
      correctedPoints.push(p);
    }

    summaries.push({
      t0: fmtCst(seg.result.t0),
      t1: fmtCst(seg.result.t1),
      n_in: seg.points.length,
      n_out: corrected.length,
      fixed,
      removed: removed.length,
      switches: seg.result.switches.length,
      max_spd: seg.result.max_speed,
      max_before: maxBefore,
      max_after: maxAfter,
      is_drive: seg.result.is_drive,
    });
  }

  return { outRows, correctedPoints, summaries, fixedTotal, removed: removedAll };
}

export function processPoints(points, dedupe = true, onProgress) {
  const segs = labelSegments(points, onProgress);
  const globalLabels = Array(points.length).fill("U");
  for (const seg of segs) {
    for (let i = 0; i < seg.idxs.length; i++) {
      globalLabels[seg.idxs[i]] = seg.labels[i];
    }
  }
  const { outRows, summaries, fixedTotal, removed } = applyCorrections(
    segs,
    dedupe
  );
  return {
    outRows,
    summaries,
    fixedTotal,
    removed,
    runLines: summarizeRuns(gcjRunsFromLabels(points, globalLabels)),
  };
}

export function processCsvText(text, options = {}) {
  const inputName = options.inputName || "input.csv";
  const onProgress = options.onProgress;
  const { points, fieldnames, format, timeKey } = parseCsv(text);
  const defaultDedupe = format !== "dol";
  const dedupe =
    options.dedupe === undefined ? defaultDedupe : options.dedupe !== false;

  if (format === "dol") {
    const segs = labelSegments(points, onProgress);
    let globalLabels = Array(points.length).fill("U");
    for (const seg of segs) {
      for (let i = 0; i < seg.idxs.length; i++) {
        globalLabels[seg.idxs[i]] = seg.labels[i];
      }
    }
    globalLabels = fillGcjByKinematics(points, globalLabels);
    for (const seg of segs) {
      for (let i = 0; i < seg.idxs.length; i++) {
        seg.labels[i] = globalLabels[seg.idxs[i]];
      }
    }
    const drop = findLateralSpikeIndices(points, globalLabels);
    const { outRows, correctedPoints, summaries, fixedTotal, removed } =
      applyCorrections(segs, dedupe, drop);
    const runLines = summarizeRuns(gcjRunsFromLabels(points, globalLabels));
    const warnLines = residualWarnJumps(correctedPoints).map(
      (w) =>
        `${fmtCst(w.t)}  步进 ${format0(w.jump_m)} m（期望约 ${format0(w.expect_m)} m）— ${w.note}`
    );
    return {
      format: "dol",
      inputName,
      totalIn: points.length,
      totalOut: outRows.length,
      fixedTotal,
      removedTotal: removed.length,
      summaries,
      dolRuns: runLines,
      dolWarns: warnLines,
      removedIndices: removed,
      report: buildReport(
        inputName,
        points.length,
        outRows.length,
        fixedTotal,
        removed.length,
        summaries,
        { runLines, removedIndices: removed, warnLines }
      ),
      fieldnames,
      timeKey,
      csvText: stringifyCsv(outRows, fieldnames),
      originalPoints: mapPointsFromTrack(points),
      correctedPoints: mapPointsFromRows(outRows, timeKey),
    };
  }

  const { outRows, summaries, fixedTotal, removed, runLines } = processPoints(
    points,
    dedupe,
    onProgress
  );
  const report = buildReport(
    inputName,
    points.length,
    outRows.length,
    fixedTotal,
    removed.length,
    summaries,
    { runLines, removedIndices: removed }
  );
  return {
    format: "footprint",
    inputName,
    totalIn: points.length,
    totalOut: outRows.length,
    fixedTotal,
    removedTotal: removed.length,
    summaries,
    dolRuns: runLines,
    dolWarns: [],
    removedIndices: removed,
    fieldnames,
    timeKey,
    report,
    csvText: stringifyCsv(outRows),
    originalPoints: mapPointsFromTrack(points),
    correctedPoints: mapPointsFromRows(outRows, timeKey),
  };
}
