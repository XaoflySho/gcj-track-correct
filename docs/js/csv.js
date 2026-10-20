import { TrackPoint } from "./detect.js";

export const FIELDNAMES = [
  "dataTime",
  "locType",
  "longitude",
  "latitude",
  "heading",
  "accuracy",
  "speed",
  "distance",
  "isBackForeground",
  "stepType",
  "altitude",
];

function parseCsvRows(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  const s = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (inQuotes) {
      if (c === '"') {
        if (s[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n") {
      if (field.endsWith("\r")) field = field.slice(0, -1);
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += c;
    }
  }
  if (field.length || row.length) {
    if (field.endsWith("\r")) field = field.slice(0, -1);
    row.push(field);
    rows.push(row);
  }
  return rows;
}

function escapeField(value) {
  const s = value == null ? "" : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replaceAll('"', '""')}"`;
  return s;
}

export function parseCsv(text) {
  const rows = parseCsvRows(text);
  if (!rows.length) throw new Error("Empty or invalid CSV");
  const header = rows[0].map((h, i) => (i === 0 ? h.replace(/^\uFEFF/, "") : h));
  if (!header.includes("dataTime") || !header.includes("longitude") || !header.includes("latitude")) {
    throw new Error("缺少列 dataTime / longitude / latitude（一生足迹导出格式）");
  }
  const points = [];
  for (let i = 1; i < rows.length; i++) {
    const cols = rows[i];
    if (cols.length === 1 && cols[0] === "") continue;
    const raw = {};
    for (let j = 0; j < header.length; j++) {
      raw[header[j]] = cols[j] ?? "";
    }
    if (raw.dataTime === "" && raw.longitude === "" && raw.latitude === "") continue;
    points.push(
      TrackPoint(
        points.length,
        parseInt(raw.dataTime, 10),
        parseFloat(raw.longitude),
        parseFloat(raw.latitude),
        parseFloat(raw.speed),
        parseFloat(raw.accuracy),
        parseFloat(raw.altitude),
        raw
      )
    );
  }
  for (const p of points) {
    if (!Number.isFinite(p.t) || !Number.isFinite(p.lon) || !Number.isFinite(p.lat)) {
      throw new Error("CSV 含无效的 dataTime / longitude / latitude");
    }
    if (!Number.isFinite(p.speed)) p.speed = -1;
    if (!Number.isFinite(p.accuracy)) p.accuracy = 0;
    if (!Number.isFinite(p.altitude)) p.altitude = 0;
  }
  return points;
}

export function stringifyCsv(rows) {
  const lines = [FIELDNAMES.join(",")];
  for (const row of rows) {
    lines.push(FIELDNAMES.map((k) => escapeField(row[k] ?? "")).join(","));
  }
  return lines.join("\r\n") + "\r\n";
}

export function mapPointsFromRows(rows) {
  const timeKey = rows.length && rows[0].dataTime != null ? "dataTime" : "timestamp";
  return rows.map((row) => ({
    t: parseInt(row[timeKey], 10),
    lon: parseFloat(row.longitude),
    lat: parseFloat(row.latitude),
  }));
}

export function mapPointsFromTrack(points) {
  return points.map((p) => ({ t: p.t, lon: p.lon, lat: p.lat }));
}
