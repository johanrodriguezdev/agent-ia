#!/usr/bin/env node
// Máquina de estados del tracker de REQs (requerimientos.csv).
// Único punto de escritura permitido para el CSV — los agentes nunca lo editan a mano.
//
// Uso:
//   node update-tracker.mjs --siguiente-id
//   node update-tracker.mjs --crear --id REQ-001 --Descripcion "..." --Categoria "CORE"
//   node update-tracker.mjs --id REQ-001 --Estado "EN_SPEC"
//   node update-tracker.mjs --lista [--Estado EN_QA]

import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const CSV_PATH = path.join(REPO_ROOT, "requerimientos.csv");
const ADJUNTOS_DIR = path.join(REPO_ROOT, "workspace", "adjuntos");

const COLUMNS = [
  "ID",
  "Descripcion",
  "Categoria",
  "Estado",
  "Tipo_Cambio",
  "Aprobacion_SPEC",
  "Aprobacion_Arquitectura",
  "Rama",
];

const ESTADOS_VALIDOS = [
  "NUEVO",
  "EN_SPEC",
  "SPEC_APROBADO",
  "EN_BASELINE",
  "EN_ARQUITECTURA",
  "ARQUITECTURA_APROBADA",
  "EN_DESARROLLO",
  "EN_PRUEBAS",
  "EN_QA",
  "LISTO_PARA_COMMIT",
];

const TRANSICIONES = {
  NUEVO:                ["EN_SPEC"],
  EN_SPEC:              ["SPEC_APROBADO"],
  SPEC_APROBADO:        ["EN_BASELINE"],
  EN_BASELINE:          ["EN_ARQUITECTURA"],
  EN_ARQUITECTURA:      ["ARQUITECTURA_APROBADA"],
  ARQUITECTURA_APROBADA:["EN_DESARROLLO"],
  EN_DESARROLLO:        ["EN_PRUEBAS"],
  EN_PRUEBAS:           ["EN_QA", "EN_DESARROLLO"],
  EN_QA:                ["LISTO_PARA_COMMIT", "EN_DESARROLLO"],
  LISTO_PARA_COMMIT:    [],
};

function fail(msg) {
  console.error(`❌ ${msg}`);
  process.exit(1);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else { inQuotes = false; }
      } else { field += c; }
    } else if (c === '"') { inQuotes = true; }
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c === "\r") { }
    else { field += c; }
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  return rows.filter((r) => r.length > 1 || (r.length === 1 && r[0] !== ""));
}

function csvEscape(value) {
  const s = value ?? "";
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function readTracker() {
  if (!existsSync(CSV_PATH)) return [];
  const text = readFileSync(CSV_PATH, "utf-8");
  if (!text.trim()) return [];
  const rows = parseCsv(text);
  const header = rows[0];
  return rows.slice(1).map((r) => {
    const obj = {};
    header.forEach((col, idx) => { obj[col] = r[idx] ?? ""; });
    return obj;
  });
}

function writeTracker(records) {
  const lines = [COLUMNS.join(",")];
  for (const rec of records) {
    lines.push(COLUMNS.map((col) => csvEscape(rec[col] ?? "")).join(","));
  }
  writeFileSync(CSV_PATH, lines.join("\n") + "\n", "utf-8");
}

function parseArgs(argv) {
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) { flags[key] = true; }
    else { flags[key] = next; i++; }
  }
  return flags;
}

function siguienteId() {
  let maxN = 0;
  const records = readTracker();
  for (const r of records) {
    const m = /^REQ-(\d+)$/.exec(r.ID || "");
    if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
  }
  if (existsSync(ADJUNTOS_DIR)) {
    for (const entry of readdirSync(ADJUNTOS_DIR)) {
      const m = /^REQ-(\d+)$/.exec(entry);
      if (m) maxN = Math.max(maxN, parseInt(m[1], 10));
    }
  }
  const next = maxN + 1;
  const id = `REQ-${String(next).padStart(3, "0")}`;
  console.log(id);
  return id;
}

function crear(flags) {
  const id = flags.id;
  if (!id) fail("--crear requiere --id REQ-XXX");
  if (!/^REQ-\d+$/.test(id)) fail(`ID inválido: "${id}" (formato esperado REQ-XXX)`);
  const records = readTracker();
  if (records.some((r) => r.ID === id)) fail(`${id} ya existe en requerimientos.csv`);
  const nuevo = {
    ID: id,
    Descripcion: flags.Descripcion || "—",
    Categoria: flags.Categoria || "—",
    Estado: "NUEVO",
    Tipo_Cambio: flags.Tipo_Cambio || "—",
    Aprobacion_SPEC: "—",
    Aprobacion_Arquitectura: "—",
    Rama: "—",
  };
  records.push(nuevo);
  writeTracker(records);
  console.log(`✅ ${id} creado en requerimientos.csv | Estado=NUEVO`);
}

function actualizar(flags) {
  const id = flags.id;
  if (!id) fail("Falta --id REQ-XXX");
  const records = readTracker();
  const rec = records.find((r) => r.ID === id);
  if (!rec) fail(`${id} no existe en requerimientos.csv. ¿Falta --crear?`);
  const camposEditables = COLUMNS.filter((c) => c !== "ID");
  let cambios = 0;
  if (flags.Estado !== undefined) {
    const nuevo = flags.Estado;
    if (!ESTADOS_VALIDOS.includes(nuevo)) {
      fail(`Estado inválido: "${nuevo}". Válidos: ${ESTADOS_VALIDOS.join(", ")}`);
    }
    const actual = rec.Estado || "NUEVO";
    const permitidos = TRANSICIONES[actual] || [];
    if (nuevo !== actual && !permitidos.includes(nuevo)) {
      fail(`Transición no permitida: ${actual} → ${nuevo}. ` +
        `Desde "${actual}" solo se permite: ${permitidos.join(", ") || "(ninguna, estado terminal)"}`);
    }
    rec.Estado = nuevo;
    cambios++;
  }
  for (const campo of camposEditables) {
    if (campo === "Estado") continue;
    if (flags[campo] !== undefined) {
      rec[campo] = String(flags[campo]);
      cambios++;
    }
  }
  if (cambios === 0) fail("No se pasó ningún campo para actualizar");
  writeTracker(records);
  console.log(`✅ ${id} actualizado | Estado=${rec.Estado}`);
}

function lista(flags) {
  const records = readTracker();
  const filtrados = flags.Estado ? records.filter((r) => r.Estado === flags.Estado) : records;
  if (filtrados.length === 0) { console.log("(sin resultados)"); return; }
  for (const r of filtrados) {
    console.log(`${r.ID} | ${r.Categoria} | ${r.Estado} | SPEC=${r.Aprobacion_SPEC} | Arq=${r.Aprobacion_Arquitectura} | ${r.Descripcion}`);
  }
}

const flags = parseArgs(process.argv.slice(2));

if (flags["siguiente-id"]) { siguienteId(); }
else if (flags.crear) { crear(flags); }
else if (flags.lista) { lista(flags); }
else if (flags.id) { actualizar(flags); }
else {
  console.log([
    "Uso:",
    "  node update-tracker.mjs --siguiente-id",
    '  node update-tracker.mjs --crear --id REQ-001 --Descripcion "..." --Categoria "CORE"',
    '  node update-tracker.mjs --id REQ-001 --Estado "EN_SPEC"',
    "  node update-tracker.mjs --lista [--Estado EN_QA]",
  ].join("\n"));
  process.exit(1);
}
