import { parseCsv, stringifyCsv } from "./csv.js";
import { gcj02ToWgs84 } from "./coords.js";
import { zipUtf8Files } from "./zip.js";
import {
  alignTracks,
  clearSelectMarker,
  cstClockParts,
  cstDateParts,
  drawView,
  filterByTime,
  fmtCst,
  haversineM,
  initMap,
  moveSelectMarker,
  nearestPoint,
  pickRadiusM,
  MAX_SPAN_S,
  POINT_WARN_LIMIT,
  setPickHandler,
  setSelectMarker,
  windowFromParts,
} from "./map.js";

async function peekFormat(file) {
  const head = await file.slice(0, 400).text();
  const header = head.split(/\r?\n/)[0] || "";
  if (header.includes("timestamp")) return "dol";
  if (header.includes("dataTime")) return "footprint";
  return null;
}

const el = {
  fileInput: document.getElementById("fileInput"),
  fileName: document.getElementById("fileName"),
  noDedupe: document.getElementById("noDedupe"),
  btnCorrect: document.getElementById("btnCorrect"),
  btnDownload: document.getElementById("btnDownload"),
  status: document.getElementById("status"),
  stats: document.getElementById("stats"),
  tables: document.getElementById("tables"),
  previewBlock: document.getElementById("previewBlock"),
  dateFrom: document.getElementById("dateFrom"),
  dateTo: document.getElementById("dateTo"),
  clockFrom: document.getElementById("clockFrom"),
  clockTo: document.getElementById("clockTo"),
  btnShow: document.getElementById("btnShow"),
  dedupeRow: document.getElementById("dedupeRow"),
  pickMeta: document.getElementById("pickMeta"),
  pickLon: document.getElementById("pickLon"),
  pickLat: document.getElementById("pickLat"),
  btnGcj2Wgs: document.getElementById("btnGcj2Wgs"),
  btnApplyPick: document.getElementById("btnApplyPick"),
  btnRestorePick: document.getElementById("btnRestorePick"),
  btnDeletePick: document.getElementById("btnDeletePick"),
  btnPrevPick: document.getElementById("btnPrevPick"),
  btnNextPick: document.getElementById("btnNextPick"),
  pickBar: document.getElementById("pickBar"),
  pickIdle: document.getElementById("pickIdle"),
  pickActive: document.getElementById("pickActive"),
  btnClosePick: document.getElementById("btnClosePick"),
};

const state = {
  file: null,
  result: null,
  selectedIndex: null,
  selectedRemovedT: null,
  viewOriginal: [],
  viewCorrected: [],
  viewRemoved: [],
  origByT: new Map(),
};

let worker = null;

function setStatus(text, kind) {
  el.status.textContent = text;
  el.status.className = kind || "";
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function stemOf(name) {
  return name.replace(/\.csv$/i, "");
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function renderStats(result) {
  el.stats.classList.remove("hidden");
  const removedLabel = result.format === "dol" ? "侧向野点删除" : "近重复删除";
  const kind = result.format === "dol" ? "人生点点 / DoL" : "一生足迹";
  el.stats.innerHTML =
    `<p>格式 <b>${kind}</b> · 输入 <b>${result.totalIn.toLocaleString()}</b> 点 · 输出 <b>${result.totalOut.toLocaleString()}</b> 点</p>` +
    `<p>GCJ→WGS 转换 <b>${result.fixedTotal}</b> · ${removedLabel} <b>${result.removedTotal}</b></p>`;
}

function renderDolExtras(result) {
  let html = `<div class="section-title">GCJ 块（已转换）</div>`;
  if (!result.dolRuns.length) {
    html += `<p class="hint">未检测到 GCJ 污染。</p>`;
  } else {
    html += `<ul class="hint" style="padding-left:18px">`;
    for (const line of result.dolRuns) {
      html += `<li>${escapeHtml(line)}</li>`;
    }
    html += `</ul>`;
  }
  html += `<div class="section-title">残留警告跳变</div>`;
  if (!result.dolWarns.length) {
    html += `<p class="hint">无。</p>`;
  } else {
    html += `<ul class="hint" style="padding-left:18px">`;
    for (const line of result.dolWarns) {
      html += `<li>${escapeHtml(line)}</li>`;
    }
    html += `</ul>`;
  }
  return html;
}

function renderTables(result) {
  const summaries = result.summaries || [];
  const corrected = summaries
    .filter((s) => s.fixed > 0 || s.removed > 0)
    .sort((a, b) => b.fixed - a.fixed);
  const top = summaries
    .filter((s) => s.is_drive)
    .sort((a, b) => b.switches - a.switches || b.fixed - a.fixed)
    .slice(0, 20);

  let html = "";
  html += `<div class="section-title">发生纠偏的行程</div>`;
  if (!corrected.length) {
    html += `<p class="hint">未检测到 GCJ 污染。</p>`;
  } else {
    html += `<div class="table-wrap"><table><thead><tr>
      <th>开始（CST）</th><th>结束</th><th class="num">转换</th><th class="num">删除</th>
      <th class="num">切换</th><th class="num">最高速</th></tr></thead><tbody>`;
    for (const s of corrected) {
      html += `<tr>
        <td>${escapeHtml(s.t0)}</td><td>${escapeHtml(s.t1)}</td>
        <td class="num">${s.fixed}</td><td class="num">${s.removed}</td>
        <td class="num">${s.switches}</td><td class="num">${s.max_spd.toFixed(1)}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;
  }

  html += `<div class="section-title">驾车行程（按切换次数）</div>`;
  if (!top.length) {
    html += `<p class="hint">无驾车行程。</p>`;
  } else {
    html += `<div class="table-wrap"><table><thead><tr>
      <th>开始（CST）</th><th class="num">点数</th><th class="num">切换</th>
      <th class="num">转换</th><th>状态</th></tr></thead><tbody>`;
    for (const s of top) {
      const kind = s.fixed ? "已纠偏" : s.switches === 0 ? "干净" : "已检测未改";
      html += `<tr>
        <td>${escapeHtml(s.t0)}</td>
        <td class="num">${s.n_in}</td>
        <td class="num">${s.switches}</td>
        <td class="num">${s.fixed}</td>
        <td>${kind}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;
  }
  if (result.format === "dol") {
    html += renderDolExtras(result);
  }
  el.tables.innerHTML = html;
}

function fillDateRange(result) {
  const points = result.originalPoints;
  if (!points.length) return;
  let t0 = points[0].t;
  let t1 = points[points.length - 1].t;
  if (t1 < t0) {
    const tmp = t0;
    t0 = t1;
    t1 = tmp;
  }
  if (t1 - t0 > MAX_SPAN_S) t1 = t0 + MAX_SPAN_S;
  el.dateFrom.value = cstDateParts(t0);
  el.clockFrom.value = cstClockParts(t0);
  el.dateTo.value = cstDateParts(t1);
  el.clockTo.value = cstClockParts(t1);
}

function getWorker() {
  if (worker) return worker;
  worker = new Worker(new URL("../correct.worker.js", import.meta.url), {
    type: "module",
  });
  return worker;
}

function hydrateResult(msg) {
  const parsed = parseCsv(msg.csvText);
  msg.fieldnames = msg.fieldnames || parsed.fieldnames;
  msg.timeKey = msg.timeKey || parsed.timeKey;
  msg.rows = parsed.points.map((p) => p.raw);
  msg.correctedPoints = parsed.points.map((p, i) => ({
    index: i,
    t: p.t,
    lon: p.lon,
    lat: p.lat,
  }));
  msg.edited = new Set();
  msg.deletedTs = [];
  msg.deletedByT = new Map();
  msg.baseReport = msg.report;
  return msg;
}

function originalOf(t) {
  return state.origByT.get(t) || null;
}

function currentWindow() {
  return windowFromParts(
    el.dateFrom.value,
    el.clockFrom.value,
    el.dateTo.value,
    el.clockTo.value
  );
}

function previewVisible() {
  return !!(state.result && el.previewBlock && !el.previewBlock.classList.contains("hidden"));
}

function renderPickMeta() {
  if (!previewVisible()) {
    el.pickBar.classList.add("hidden");
    return;
  }
  el.pickBar.classList.remove("hidden");
  const i = state.selectedIndex;
  const removedT = state.selectedRemovedT;
  if (i == null && removedT == null) {
    el.pickIdle.classList.remove("hidden");
    el.pickActive.classList.add("hidden");
    el.pickLon.value = "";
    el.pickLat.value = "";
    return;
  }
  el.pickIdle.classList.add("hidden");
  el.pickActive.classList.remove("hidden");
  const nEdit = state.result.edited.size;
  const nDel = (state.result.deletedTs || []).length;
  const manualBits = [];
  if (nEdit) manualBits.push(`改 ${nEdit}`);
  if (nDel) manualBits.push(`删 ${nDel}`);
  const manualLine = manualBits.length
    ? `\n已手动${manualBits.join("、")}（下载会包含）`
    : "";

  if (removedT != null) {
    const orig = originalOf(removedT);
    el.pickMeta.textContent =
      `${fmtCst(removedT)}  · 已从输出删除（空心点）` +
      (orig ? `\n原始 ${orig.lon.toFixed(6)}, ${orig.lat.toFixed(6)}` : "") +
      manualLine;
    if (orig) {
      el.pickLon.value = orig.lon.toFixed(6);
      el.pickLat.value = orig.lat.toFixed(6);
    }
    el.btnRestorePick.textContent = "恢复到输出";
    el.btnRestorePick.disabled = !orig;
    el.btnDeletePick.disabled = true;
    el.btnGcj2Wgs.disabled = !orig;
    el.btnApplyPick.disabled = !orig;
    updatePickNav(removedT, "removed");
    return;
  }

  const p = state.result.correctedPoints[i];
  const orig = originalOf(p.t);
  const shift = orig ? haversineM(orig.lon, orig.lat, p.lon, p.lat) : 0;
  el.pickMeta.textContent =
    `${fmtCst(p.t)}  · 相对原始 ${shift.toFixed(1)} m` +
    (orig ? `\n原始 ${orig.lon.toFixed(6)}, ${orig.lat.toFixed(6)}` : "") +
    manualLine;
  el.pickLon.value = p.lon.toFixed(6);
  el.pickLat.value = p.lat.toFixed(6);
  el.btnRestorePick.textContent = "恢复原始";
  el.btnRestorePick.disabled = !orig;
  el.btnDeletePick.disabled = false;
  el.btnGcj2Wgs.disabled = false;
  el.btnApplyPick.disabled = false;
  updatePickNav(p.t, "out");
}

function pickSequence() {
  const out = state.viewCorrected.map((p) => ({
    kind: "out",
    t: p.t,
    index: p.index,
    lon: p.lon,
    lat: p.lat,
  }));
  const rem = state.viewRemoved.map((p) => ({
    kind: "removed",
    t: p.t,
    lon: p.lon,
    lat: p.lat,
  }));
  return out.concat(rem).sort((a, b) => a.t - b.t || (a.kind === "out" ? -1 : 1));
}

function updatePickNav(t, kind) {
  const seq = pickSequence();
  const viewIdx = seq.findIndex((q) => q.t === t && q.kind === kind);
  el.btnPrevPick.disabled = viewIdx <= 0;
  el.btnNextPick.disabled = viewIdx < 0 || viewIdx >= seq.length - 1;
}

function bindSelectMarker() {
  if (!state.result) {
    clearSelectMarker();
    return;
  }
  if (state.selectedRemovedT != null) {
    const orig = originalOf(state.selectedRemovedT);
    if (!orig) {
      clearSelectMarker();
      return;
    }
    setSelectMarker(orig.lat, orig.lon, (lon, lat) => restoreRemovedPoint(lon, lat), true);
    return;
  }
  const i = state.selectedIndex;
  if (i == null) {
    clearSelectMarker();
    return;
  }
  const p = state.result.correctedPoints[i];
  setSelectMarker(p.lat, p.lon, (lon, lat) => applyEdit(i, lon, lat), true);
}

function applyEdit(corrIndex, lon, lat) {
  if (!state.result) return;
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
    setStatus("经纬度无效。", "err");
    return;
  }
  const p = state.result.correctedPoints[corrIndex];
  p.lon = lon;
  p.lat = lat;
  const row = state.result.rows[corrIndex];
  if (row) {
    row.longitude = lon.toFixed(6);
    row.latitude = lat.toFixed(6);
  }
  state.result.csvText = stringifyCsv(state.result.rows, state.result.fieldnames);
  const orig = originalOf(p.t);
  const shifted = orig ? haversineM(orig.lon, orig.lat, lon, lat) >= 0.05 : true;
  if (shifted) state.result.edited.add(p.t);
  else state.result.edited.delete(p.t);
  refreshManualReport();
  redrawMap(false);
  if (state.selectedIndex === corrIndex) {
    moveSelectMarker(lat, lon);
    renderPickMeta();
  }
}

function refreshManualReport() {
  const nEdit = state.result.edited.size;
  const nDel = (state.result.deletedTs || []).length;
  let extra = "";
  if (nEdit || nDel) {
    extra = "\n## 手动修改\n\n";
    if (nEdit) extra += `- 手动改动点数：**${nEdit}**\n`;
    if (nDel) extra += `- 手动删除点数：**${nDel}**\n`;
  }
  state.result.report = (state.result.baseReport || "").replace(/\n$/, "") + extra + "\n";
}

function reindexCorrected() {
  state.result.correctedPoints.forEach((p, i) => {
    p.index = i;
  });
  state.result.totalOut = state.result.correctedPoints.length;
  state.result.csvText = stringifyCsv(state.result.rows, state.result.fieldnames);
}

function emptyRowFromOriginal(orig) {
  const row = {};
  for (const k of state.result.fieldnames) row[k] = "";
  row[state.result.timeKey] = String(orig.t);
  row.longitude = orig.lon.toFixed(6);
  row.latitude = orig.lat.toFixed(6);
  return row;
}

function insertCorrectedPoint(point, row) {
  const pts = state.result.correctedPoints;
  let i = pts.findIndex((p) => p.t > point.t);
  if (i < 0) i = pts.length;
  pts.splice(i, 0, point);
  state.result.rows.splice(i, 0, row);
  reindexCorrected();
  return i;
}

function restoreRemovedPoint(lon, lat) {
  if (!state.result || state.selectedRemovedT == null) return;
  const t = state.selectedRemovedT;
  const orig = originalOf(t);
  if (!orig) {
    setStatus("找不到该点的原始坐标。", "err");
    return;
  }
  const useLon = Number.isFinite(lon) ? lon : orig.lon;
  const useLat = Number.isFinite(lat) ? lat : orig.lat;
  const saved = state.result.deletedByT.get(t);
  const row = saved && saved.row ? { ...saved.row } : emptyRowFromOriginal(orig);
  row[state.result.timeKey] = String(t);
  row.longitude = useLon.toFixed(6);
  row.latitude = useLat.toFixed(6);
  const i = insertCorrectedPoint({ index: 0, t, lon: useLon, lat: useLat }, row);
  state.result.deletedByT.delete(t);
  state.result.deletedTs = (state.result.deletedTs || []).filter((x) => x !== t);
  const shifted = haversineM(orig.lon, orig.lat, useLon, useLat) >= 0.05;
  if (shifted) state.result.edited.add(t);
  else state.result.edited.delete(t);
  refreshManualReport();
  renderStats(state.result);
  state.selectedRemovedT = null;
  state.selectedIndex = i;
  redrawMap(false);
  selectCorrIndex(i);
  setStatus(`已将 ${fmtCst(t)} 恢复到输出。`);
}

function deleteSelectedPoint() {
  if (!state.result || state.selectedIndex == null) return;
  const i = state.selectedIndex;
  const p = state.result.correctedPoints[i];
  if (!p) return;
  const seq = pickSequence();
  const seqIdx = seq.findIndex((q) => q.kind === "out" && q.index === i);
  const nextHint = seq[seqIdx + 1] || seq[seqIdx - 1];
  const row = state.result.rows[i] ? { ...state.result.rows[i] } : null;
  state.result.edited.delete(p.t);
  state.result.deletedTs.push(p.t);
  state.result.deletedByT.set(p.t, { lon: p.lon, lat: p.lat, row });
  state.result.correctedPoints.splice(i, 1);
  state.result.rows.splice(i, 1);
  reindexCorrected();
  refreshManualReport();
  renderStats(state.result);
  state.selectedIndex = null;
  clearSelectMarker();
  redrawMap(false);
  if (nextHint && nextHint.kind === "removed") selectRemoved(nextHint.t);
  else if (nextHint) {
    const found = state.result.correctedPoints.find((q) => q.t === nextHint.t);
    if (found) selectCorrIndex(found.index);
    else renderPickMeta();
  } else renderPickMeta();
  setStatus(`已删除 ${fmtCst(p.t)} 的点。下载结果将不含该点。`);
}

function selectCorrIndex(corrIndex) {
  if (!state.result || corrIndex == null) return;
  if (corrIndex < 0 || corrIndex >= state.result.correctedPoints.length) return;
  state.selectedRemovedT = null;
  state.selectedIndex = corrIndex;
  renderPickMeta();
  bindSelectMarker();
}

function selectRemoved(t) {
  if (!state.result || t == null) return;
  state.selectedIndex = null;
  state.selectedRemovedT = t;
  renderPickMeta();
  bindSelectMarker();
}

function selectOutByT(t) {
  const p =
    state.result.correctedPoints.find((q) => q.t === t) ||
    state.viewCorrected.find((q) => q.t === t);
  if (!p) return false;
  selectCorrIndex(p.index);
  setStatus(`已选中 ${fmtCst(p.t)}。可拖动标记、改坐标、转换或删除。`);
  return true;
}

function onMapPick(latlng, hint) {
  if (!state.result) return;
  if (hint && hint.kind === "removed" && hint.t != null) {
    selectRemoved(hint.t);
    setStatus(`已选中删除点 ${fmtCst(hint.t)}。可「恢复到输出」或先改坐标再恢复。`);
    return;
  }
  if (hint && hint.kind === "out" && hint.t != null) {
    if (selectOutByT(hint.t)) return;
  }
  if (!state.viewCorrected.length && !state.viewRemoved.length) return;
  const radius = pickRadiusM();
  const hitCorr = nearestPoint(latlng, state.viewCorrected, radius);
  const hitRem = nearestPoint(latlng, state.viewRemoved, radius * 1.6);
  let kind = null;
  let hit = null;
  if (hitCorr && hitRem) {
    // Hollow near-dupes sit on remaining points; give them a small bonus
    // so clicking the circle selects the deleted point, not the neighbor.
    if (hitRem.distM <= hitCorr.distM + 8) {
      kind = "removed";
      hit = hitRem;
    } else {
      kind = "out";
      hit = hitCorr;
    }
  } else if (hitRem) {
    kind = "removed";
    hit = hitRem;
  } else if (hitCorr) {
    kind = "out";
    hit = hitCorr;
  }
  if (!hit) {
    setStatus("附近没有轨迹点，请放大后点蓝色轨迹或空心删除点。", "warn");
    return;
  }
  if (kind === "removed") {
    selectRemoved(hit.point.t);
    setStatus(`已选中删除点 ${fmtCst(hit.point.t)}。可「恢复到输出」或先改坐标再恢复。`);
    return;
  }
  selectCorrIndex(hit.point.index);
  setStatus(
    `已选中 ${fmtCst(hit.point.t)}。可拖动标记、改坐标、转换或删除。`
  );
}

function stepSelected(delta) {
  const seq = pickSequence();
  if (!seq.length) return;
  let viewIdx = -1;
  if (state.selectedRemovedT != null) {
    viewIdx = seq.findIndex(
      (q) => q.kind === "removed" && q.t === state.selectedRemovedT
    );
  } else if (state.selectedIndex != null) {
    viewIdx = seq.findIndex(
      (q) => q.kind === "out" && q.index === state.selectedIndex
    );
  }
  if (viewIdx < 0) return;
  const next = seq[viewIdx + delta];
  if (!next) return;
  if (next.kind === "removed") selectRemoved(next.t);
  else selectCorrIndex(next.index);
}

function redrawMap(fit) {
  if (!state.result) return;
  let win;
  try {
    win = currentWindow();
  } catch (e) {
    setStatus(String(e.message || e), "err");
    return false;
  }
  const original = filterByTime(
    state.result.originalPoints,
    win.t0,
    win.t1,
    win.endExclusive
  );
  const corrected = filterByTime(
    state.result.correctedPoints,
    win.t0,
    win.t1,
    win.endExclusive
  );
  const corrT = new Set(corrected.map((p) => p.t));
  state.viewOriginal = original;
  state.viewCorrected = corrected;
  state.viewRemoved = original.filter((p) => !corrT.has(p.t));
  if (!original.length && !corrected.length) {
    setStatus("该时间窗内无点。", "err");
    return false;
  }
  const view = alignTracks(original, corrected);
  drawView(view, { fit });
  if (state.selectedIndex != null || state.selectedRemovedT != null) {
    bindSelectMarker();
  }
  const nPts = Math.max(original.length, corrected.length);
  let msg =
    fmtCst(win.t0) +
    " → " +
    fmtCst(win.t1) +
    "\n原始 " +
    view.nOriginal +
    " 点 · 纠偏 " +
    view.nCorrected +
    " 点 · 改动 " +
    view.changed.length +
    " · 删除 " +
    view.removed.length;
  const nEdit = state.result.edited ? state.result.edited.size : 0;
  const nDel = (state.result.deletedTs || []).length;
  if (nEdit || nDel) {
    msg += " · 手动改 " + nEdit + " · 手动删 " + nDel;
  }
  if (nPts > POINT_WARN_LIMIT) {
    msg +=
      "\n警告：点数 > " +
      POINT_WARN_LIMIT +
      "，浏览器可能较卡，建议缩小时间范围。";
    setStatus(msg, "warn");
  } else {
    setStatus(msg);
  }
  renderPickMeta();
  return true;
}

function resetOutputs() {
  state.result = null;
  state.selectedIndex = null;
  state.selectedRemovedT = null;
  state.viewOriginal = [];
  state.viewCorrected = [];
  state.viewRemoved = [];
  state.origByT = new Map();
  clearSelectMarker();
  renderPickMeta();
  el.btnDownload.disabled = true;
  el.stats.classList.add("hidden");
  el.stats.innerHTML = "";
  el.tables.innerHTML = "";
  el.previewBlock.classList.add("hidden");
}

el.fileInput.addEventListener("change", () => {
  const file = el.fileInput.files && el.fileInput.files[0];
  state.file = file || null;
  resetOutputs();
  if (!file) {
    el.fileName.textContent = "未选择";
    el.btnCorrect.disabled = true;
    el.dedupeRow.classList.remove("hidden");
    setStatus("请选择一生足迹或人生点点导出的 CSV，然后点击「开始纠偏」。");
    return;
  }
  el.fileName.textContent = file.name;
  el.btnCorrect.disabled = false;
  peekFormat(file).then((fmt) => {
    el.dedupeRow.classList.remove("hidden");
    if (fmt === "dol") {
      el.noDedupe.checked = true;
      setStatus("已识别为人生点点 / DoL。点击「开始纠偏」。");
    } else if (fmt === "footprint") {
      el.noDedupe.checked = false;
      setStatus("已识别为一生足迹。点击「开始纠偏」。");
    } else {
      el.noDedupe.checked = false;
      setStatus("已选择 " + file.name + "。点击「开始纠偏」（将按表头识别格式）。");
    }
  });
});

el.btnCorrect.addEventListener("click", async () => {
  if (!state.file) return;
  el.btnCorrect.disabled = true;
  el.btnDownload.disabled = true;
  setStatus("正在读取 " + state.file.name + " …");
  let text;
  try {
    text = await state.file.text();
  } catch (e) {
    el.btnCorrect.disabled = false;
    setStatus("读取失败：" + (e.message || e), "err");
    return;
  }

  const w = getWorker();
  const onMessage = (event) => {
    const msg = event.data;
    if (msg.type === "progress") {
      setStatus(`正在纠偏 ${msg.processed} / ${msg.total} 段…`);
      return;
    }
    w.removeEventListener("message", onMessage);
    w.removeEventListener("error", onError);
    el.btnCorrect.disabled = false;
    if (msg.type === "error") {
      setStatus("纠偏失败：" + msg.error, "err");
      return;
    }
    state.result = hydrateResult(msg);
    state.origByT = new Map();
    for (const p of state.result.originalPoints) {
      if (!state.origByT.has(p.t)) state.origByT.set(p.t, p);
    }
    state.selectedIndex = null;
    clearSelectMarker();
    el.btnDownload.disabled = false;
    renderStats(state.result);
    renderTables(state.result);
    el.previewBlock.classList.remove("hidden");
    fillDateRange(msg);
    const removedLabel = msg.format === "dol" ? "侧向野点" : "近重复";
    setStatus(
      `完成。转换 ${msg.fixedTotal} 点，删除${removedLabel} ${msg.removedTotal} 点。可下载结果，或改时间后点「显示」。`
    );
    el.btnShow.click();
  };
  const onError = (err) => {
    w.removeEventListener("message", onMessage);
    w.removeEventListener("error", onError);
    el.btnCorrect.disabled = false;
    setStatus("Worker 错误：" + (err.message || err), "err");
  };
  w.addEventListener("message", onMessage);
  w.addEventListener("error", onError);
  setStatus("正在纠偏…");
  w.postMessage({
    text,
    fileName: state.file.name,
    dedupe: !el.noDedupe.checked,
  });
});

el.btnDownload.addEventListener("click", () => {
  if (!state.result || !state.file) return;
  const stem = stemOf(state.file.name);
  const zip = zipUtf8Files([
    { name: `${stem}_corrected.csv`, text: state.result.csvText },
    { name: `${stem}_report.md`, text: state.result.report },
  ]);
  downloadBlob(`${stem}_corrected.zip`, zip);
});

el.btnShow.addEventListener("click", () => {
  if (!state.result) {
    setStatus("请先完成纠偏。", "err");
    return;
  }
  if (!el.dateFrom.value || !el.dateTo.value) {
    setStatus("请填写开始日期与结束日期。", "err");
    return;
  }
  redrawMap(true);
});

el.btnGcj2Wgs.addEventListener("click", () => {
  if (!state.result) return;
  if (state.selectedRemovedT != null) {
    const orig = originalOf(state.selectedRemovedT);
    if (!orig) return;
    const [lon, lat] = gcj02ToWgs84(orig.lon, orig.lat);
    restoreRemovedPoint(lon, lat);
    setStatus(`已将 ${fmtCst(orig.t)} 按 GCJ→WGS 转换并恢复到输出。`);
    return;
  }
  if (state.selectedIndex == null) return;
  const p = state.result.correctedPoints[state.selectedIndex];
  const src = originalOf(p.t) || p;
  const [lon, lat] = gcj02ToWgs84(src.lon, src.lat);
  applyEdit(state.selectedIndex, lon, lat);
  setStatus(`已将 ${fmtCst(p.t)} 的原始坐标按 GCJ→WGS 转换。`);
});

el.btnApplyPick.addEventListener("click", () => {
  const lon = parseFloat(el.pickLon.value);
  const lat = parseFloat(el.pickLat.value);
  if (state.selectedRemovedT != null) {
    restoreRemovedPoint(lon, lat);
    return;
  }
  if (state.selectedIndex == null) return;
  applyEdit(state.selectedIndex, lon, lat);
  setStatus("已应用手动坐标。");
});

el.btnDeletePick.addEventListener("click", () => {
  deleteSelectedPoint();
});

el.btnRestorePick.addEventListener("click", () => {
  if (!state.result) return;
  if (state.selectedRemovedT != null) {
    const orig = originalOf(state.selectedRemovedT);
    restoreRemovedPoint(orig ? orig.lon : NaN, orig ? orig.lat : NaN);
    return;
  }
  if (state.selectedIndex == null) return;
  const p = state.result.correctedPoints[state.selectedIndex];
  const orig = originalOf(p.t);
  if (!orig) {
    setStatus("找不到该点的原始坐标。", "err");
    return;
  }
  applyEdit(state.selectedIndex, orig.lon, orig.lat);
  setStatus(`已恢复 ${fmtCst(p.t)} 为原始坐标。`);
});

el.btnPrevPick.addEventListener("click", () => stepSelected(-1));
el.btnNextPick.addEventListener("click", () => stepSelected(1));
el.btnClosePick.addEventListener("click", () => {
  state.selectedIndex = null;
  state.selectedRemovedT = null;
  clearSelectMarker();
  renderPickMeta();
});

function applyFromInputs() {
  el.btnApplyPick.click();
}
el.pickLon.addEventListener("keydown", (e) => {
  if (e.key === "Enter") applyFromInputs();
});
el.pickLat.addEventListener("keydown", (e) => {
  if (e.key === "Enter") applyFromInputs();
});

initMap();
setPickHandler(onMapPick);
renderPickMeta();
