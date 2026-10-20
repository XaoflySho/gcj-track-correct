import {
  alignTracks,
  cstDateParts,
  drawView,
  filterByTime,
  fmtCst,
  initMap,
  POINT_WARN_LIMIT,
  windowFromParts,
} from "./map.js";

const el = {
  fileInput: document.getElementById("fileInput"),
  fileName: document.getElementById("fileName"),
  noDedupe: document.getElementById("noDedupe"),
  btnCorrect: document.getElementById("btnCorrect"),
  btnCsv: document.getElementById("btnCsv"),
  btnReport: document.getElementById("btnReport"),
  status: document.getElementById("status"),
  stats: document.getElementById("stats"),
  tables: document.getElementById("tables"),
  previewBlock: document.getElementById("previewBlock"),
  dateFrom: document.getElementById("dateFrom"),
  dateTo: document.getElementById("dateTo"),
  clockFrom: document.getElementById("clockFrom"),
  clockTo: document.getElementById("clockTo"),
  btnShow: document.getElementById("btnShow"),
};

const state = {
  file: null,
  result: null,
};

let worker = null;

function setStatus(text, kind) {
  el.status.textContent = text;
  el.status.className = kind || "";
}

function downloadText(filename, text, mime) {
  const blob = new Blob([text], { type: mime });
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
  el.stats.innerHTML =
    `<p>输入 <b>${result.totalIn.toLocaleString()}</b> 点 · 输出 <b>${result.totalOut.toLocaleString()}</b> 点</p>` +
    `<p>GCJ→WGS 转换 <b>${result.fixedTotal}</b> · 近重复删除 <b>${result.removedTotal}</b></p>`;
}

function renderTables(summaries) {
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
  el.tables.innerHTML = html;
}

function fillDateRange(result) {
  const segs = result.summaries.filter((s) => s.fixed > 0 || s.removed > 0);
  if (segs.length) {
    const best = segs.slice().sort((a, b) => b.fixed - a.fixed)[0];
    el.dateFrom.value = best.t0.slice(0, 10);
    el.dateTo.value = best.t1.slice(0, 10);
    el.clockFrom.value = best.t0.slice(11, 16);
    el.clockTo.value = best.t1.slice(11, 16);
    return;
  }
  const points = result.originalPoints;
  if (!points.length) return;
  const day = cstDateParts(points[0].t);
  el.dateFrom.value = day;
  el.dateTo.value = day;
  el.clockFrom.value = "";
  el.clockTo.value = "";
}

function getWorker() {
  if (worker) return worker;
  worker = new Worker(new URL("../correct.worker.js", import.meta.url), {
    type: "module",
  });
  return worker;
}

function resetOutputs() {
  state.result = null;
  el.btnCsv.disabled = true;
  el.btnReport.disabled = true;
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
    setStatus("请选择一生足迹导出的 CSV，然后点击「开始纠偏」。");
    return;
  }
  el.fileName.textContent = file.name;
  el.btnCorrect.disabled = false;
  setStatus("已选择 " + file.name + "。点击「开始纠偏」。");
});

el.btnCorrect.addEventListener("click", async () => {
  if (!state.file) return;
  el.btnCorrect.disabled = true;
  el.btnCsv.disabled = true;
  el.btnReport.disabled = true;
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
    state.result = msg;
    el.btnCsv.disabled = false;
    el.btnReport.disabled = false;
    renderStats(msg);
    renderTables(msg.summaries);
    el.previewBlock.classList.remove("hidden");
    fillDateRange(msg);
    setStatus(
      `完成。转换 ${msg.fixedTotal} 点，删除近重复 ${msg.removedTotal} 点。可下载结果，或改时间后点「显示」。`
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

el.btnCsv.addEventListener("click", () => {
  if (!state.result || !state.file) return;
  downloadText(
    `${stemOf(state.file.name)}_corrected.csv`,
    state.result.csvText,
    "text/csv;charset=utf-8"
  );
});

el.btnReport.addEventListener("click", () => {
  if (!state.result || !state.file) return;
  downloadText(
    `${stemOf(state.file.name)}_report.md`,
    state.result.report,
    "text/markdown;charset=utf-8"
  );
});

el.btnShow.addEventListener("click", () => {
  if (!state.result) {
    setStatus("请先完成纠偏。", "err");
    return;
  }
  const dateFrom = el.dateFrom.value;
  const dateTo = el.dateTo.value;
  if (!dateFrom || !dateTo) {
    setStatus("请填写开始日期与结束日期。", "err");
    return;
  }
  let win;
  try {
    win = windowFromParts(dateFrom, el.clockFrom.value, dateTo, el.clockTo.value);
  } catch (e) {
    setStatus(String(e.message || e), "err");
    return;
  }
  const original = filterByTime(state.result.originalPoints, win.t0, win.t1, win.endExclusive);
  const corrected = filterByTime(state.result.correctedPoints, win.t0, win.t1, win.endExclusive);
  if (!original.length && !corrected.length) {
    setStatus("该时间窗内无点。", "err");
    return;
  }
  const view = alignTracks(original, corrected);
  drawView(view);
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
  if (nPts > POINT_WARN_LIMIT) {
    msg += "\n警告：点数 > " + POINT_WARN_LIMIT + "，浏览器可能较卡，建议缩小时间范围。";
    setStatus(msg, "warn");
  } else {
    setStatus(msg);
  }
});

initMap();
