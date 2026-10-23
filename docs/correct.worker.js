import { processCsvText } from "./js/process.js";

self.onmessage = (event) => {
  const { text, fileName, dedupe } = event.data || {};
  try {
    const result = processCsvText(text, {
      dedupe: dedupe !== false,
      inputName: fileName || "input.csv",
      onProgress: (p) => {
        self.postMessage({ type: "progress", processed: p.processed, total: p.total });
      },
    });
    self.postMessage({
      type: "done",
      format: result.format,
      inputName: result.inputName,
      totalIn: result.totalIn,
      totalOut: result.totalOut,
      fixedTotal: result.fixedTotal,
      removedTotal: result.removedTotal,
      summaries: result.summaries,
      dolRuns: result.dolRuns || [],
      dolWarns: result.dolWarns || [],
      removedIndices: result.removedIndices || [],
      fieldnames: result.fieldnames,
      timeKey: result.timeKey,
      report: result.report,
      csvText: result.csvText,
      originalPoints: result.originalPoints,
      correctedPoints: result.correctedPoints,
    });
  } catch (err) {
    self.postMessage({
      type: "error",
      error: err && err.message ? err.message : String(err),
    });
  }
};
