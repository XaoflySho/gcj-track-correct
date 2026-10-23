#!/usr/bin/env node
import { mkdirSync, readFileSync, writeFileSync } from "fs";
import { basename, join } from "path";
import { processCsvText } from "../docs/js/process.js";

const args = process.argv.slice(2);
function opt(name, fallback) {
  const i = args.indexOf(name);
  if (i < 0) return fallback;
  return args[i + 1];
}

const input = opt("--input") || opt("-i");
const outDir = opt("--output-dir") || opt("-o") || "output";
let dedupe;
if (args.includes("--no-dedupe")) dedupe = false;
else if (args.includes("--dedupe")) dedupe = true;

if (!input) {
  console.error(
    "Usage: node scripts/run_js_correct.mjs --input FILE [--output-dir DIR] [--dedupe|--no-dedupe]"
  );
  process.exit(1);
}

const text = readFileSync(input, "utf8");
const result = processCsvText(text, {
  dedupe,
  inputName: basename(input),
});

mkdirSync(outDir, { recursive: true });
const stem = basename(input).replace(/\.csv$/i, "");
const csvPath = join(outDir, `${stem}_js_corrected.csv`);
const reportPath = join(outDir, `${stem}_js_report.md`);
writeFileSync(csvPath, result.csvText, "utf8");
writeFileSync(reportPath, result.report, "utf8");
console.log(`Wrote ${csvPath} (${result.totalOut} points)`);
console.log(`Wrote ${reportPath}`);
const removedLabel = result.format === "dol" ? "lateral spikes" : "near-duplicates";
console.log(`Format: ${result.format}`);
console.log(`Converted: ${result.fixedTotal}, removed ${removedLabel}: ${result.removedTotal}`);
