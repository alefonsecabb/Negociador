// Helpers compartilhados pelo dashboard (index.html) e pelo homebroker
// (homebroker.html). Carregado antes de dashboard.js / homebroker.js.

const DATA_BASE = "data";

async function fetchJson(path) {
  const resp = await fetch(`${DATA_BASE}/${path}?_=${Date.now()}`);
  if (!resp.ok) return null;
  return resp.json();
}

function fmtBRL(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
function fmtPct(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

// O sqlite grava created_at como "YYYY-MM-DD HH:MM:SS" (UTC, sem sufixo) via
// datetime('now') - alguns navegadores (Safari) nao parseiam esse formato
// corretamente com `new Date()`, entao normalizamos para ISO 8601 explicito.
function parseUtcTimestamp(s) {
  if (!s) return null;
  const iso = s.includes("T") ? s : s.replace(" ", "T") + "Z";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

function statTile(label, value, sub = "", cls = "") {
  return `<div class="stat-tile"><div class="label">${label}</div>
    <div class="value ${cls}">${value}</div>
    ${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function alertBadgeClass(type) {
  if (type === "ENTRADA") return "badge-entrada";
  if (type === "STOP_LOSS") return "badge-stop";
  if (type === "TAKE_PROFIT") return "badge-take";
  return "badge-tempo";
}
function alertLabel(type) {
  return { ENTRADA: "ENTRADA", STOP_LOSS: "STOP-LOSS", TAKE_PROFIT: "TAKE-PROFIT", SAIDA_POR_TEMPO: "SAIDA POR TEMPO" }[type] || type;
}
