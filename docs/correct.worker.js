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
      inputName: result.inputName,
      totalIn: result.totalIn,
      totalOut: result.totalOut,
      fixedTotal: result.fixedTotal,
      removedTotal: result.removedTotal,
      summaries: result.summaries,
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
