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

export function timeKeyOf(header) {
  if (header.includes("timestamp")) return "timestamp";
  if (header.includes("dataTime")) return "dataTime";
  return null;
}

export function formatOf(header) {
  const key = timeKeyOf(header);
  if (key === "timestamp") return "dol";
  if (key === "dataTime") return "footprint";
  return null;
}

export function parseCsv(text) {
  const rows = parseCsvRows(text);
  if (!rows.length) throw new Error("Empty or invalid CSV");
  const header = rows[0].map((h, i) => (i === 0 ? h.replace(/^\uFEFF/, "") : h));
  const tkey = timeKeyOf(header);
  if (!tkey || !header.includes("longitude") || !header.includes("latitude")) {
    throw new Error("缺少时间列（dataTime 或 timestamp）以及 longitude / latitude");
  }
  const format = formatOf(header);
  const points = [];
  for (let i = 1; i < rows.length; i++) {
    const cols = rows[i];
    if (cols.length === 1 && cols[0] === "") continue;
    const raw = {};
    for (let j = 0; j < header.length; j++) {
      raw[header[j]] = cols[j] ?? "";
    }
    if (raw[tkey] === "" && raw.longitude === "" && raw.latitude === "") continue;
    points.push(
      TrackPoint(
        points.length,
        parseInt(raw[tkey], 10),
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
      throw new Error("CSV 含无效的时间 / longitude / latitude");
    }
    if (!Number.isFinite(p.speed)) p.speed = -1;
    if (!Number.isFinite(p.accuracy)) p.accuracy = 0;
    if (!Number.isFinite(p.altitude)) p.altitude = 0;
  }
  return { points, fieldnames: header, format, timeKey: tkey };
}

export function stringifyCsv(rows, fieldnames = FIELDNAMES) {
  const cols = fieldnames && fieldnames.length ? fieldnames : FIELDNAMES;
  const lines = [cols.join(",")];
  for (const row of rows) {
    lines.push(cols.map((k) => escapeField(row[k] ?? "")).join(","));
  }
  return lines.join("\r\n") + "\r\n";
}

export function mapPointsFromRows(rows, timeKey) {
  const key =
    timeKey ||
    (rows.length && rows[0].dataTime != null ? "dataTime" : "timestamp");
  return rows.map((row, i) => ({
    index: i,
    t: parseInt(row[key], 10),
    lon: parseFloat(row.longitude),
    lat: parseFloat(row.latitude),
  }));
}

export function mapPointsFromTrack(points) {
  return points.map((p) => ({
    index: p.index,
    t: p.t,
    lon: p.lon,
    lat: p.lat,
  }));
}
