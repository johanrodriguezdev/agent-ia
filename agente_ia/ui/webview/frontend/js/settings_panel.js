// ui/webview/frontend/js/settings_panel.js
// REQ-019/CA-12..CA-19 — pantalla nueva "Configuración": modal con navegación lateral por
// secciones (patrón de referencia "WorkBuddy AI", ver SPEC-019 "Diseño de UI") + panel de
// contenido con tarjetas. v1 tiene una sola sección poblada, "Seguridad", que muestra una
// fila por cada acción de la categoría v1 (arquitectura-019.md §3.1) con su nivel efectivo
// actual y un <select> que solo ofrece el nivel vigente o niveles superiores (CA-16).
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, extendida por arquitectura-016.md §10,
// arquitectura-019.md §6): cualquier campo recibido de Python (label, description,
// effective_level/base_level, opciones) se inserta EXCLUSIVAMENTE vía
// textContent/setAttribute — nunca innerHTML/insertAdjacentHTML. Verificado además por un
// grep estructural en tests/test_webview_safe_dom_insertion.py.
//
// Modelo "aplicar al elegir" (arquitectura-019.md §4.2): cada fila es un <select> que al
// disparar `change` guarda de inmediato — no existe un botón de guardado separado ni un
// estado "elegido pero no guardado" que cerrar el modal pueda descartar (satisface CA-18
// por construcción, sin inventar un segundo mecanismo de "descartar").

import { requestSecurityOverrides, saveSecurityOverride } from "./bridge_client.js";

const LEVEL_LABELS = {
  green: "Sin confirmar",
  yellow: "Pide confirmación",
  red: "Bloqueado",
};

let _panelOpen = false;
let _pendingRowId = null;   // guard contra doble click/doble evento en la MISMA fila

export function openSettingsPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  renderShell();
  requestSecurityOverrides();   // CA-19: carga perezosa, solo acá
}

export function closeSettingsPanel() {
  _panelOpen = false;
  _pendingRowId = null;
  document.getElementById("panel-modal-root").replaceChildren();
}

function renderShell() {
  const root = document.getElementById("panel-modal-root");
  root.replaceChildren();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) closeSettingsPanel(); });

  const box = document.createElement("div");
  box.className = "modal-box modal-box-settings";

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Configuración";   // texto propio, no viene de Python — no aplica §10.1
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", closeSettingsPanel);
  header.appendChild(title);
  header.appendChild(closeBtn);

  const layout = document.createElement("div");
  layout.className = "settings-layout";

  const nav = document.createElement("nav");
  nav.className = "settings-nav";
  const navList = document.createElement("ul");
  const navItem = document.createElement("li");
  navItem.className = "settings-nav-item active";
  navItem.textContent = "Seguridad";   // única sección poblada en v1 — texto propio
  navList.appendChild(navItem);
  nav.appendChild(navList);

  const content = document.createElement("div");
  content.className = "settings-content";

  const banner = document.createElement("div");
  banner.id = "settings-banner";
  banner.className = "settings-banner";
  banner.hidden = true;

  const card = document.createElement("div");
  card.className = "settings-card";
  const cardTitle = document.createElement("div");
  cardTitle.className = "settings-card-title";
  cardTitle.textContent = "Seguridad";   // texto propio
  const list = document.createElement("div");
  list.id = "security-section-list";

  card.append(cardTitle, list);
  content.append(banner, card);
  layout.append(nav, content);

  box.append(header, layout);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

export function renderSecurityOverrides(rows) {
  const list = document.getElementById("security-section-list");
  if (!list) return;   // panel ya cerrado antes de que llegara la respuesta
  list.replaceChildren();

  if (rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "No hay acciones configurables todavía.";
    list.appendChild(empty);
    return;
  }

  for (const row of rows) list.appendChild(buildSecurityRow(row));
}

function buildSecurityRow(row) {
  const item = document.createElement("div");
  item.className = "settings-row";
  item.dataset.rowId = row.row_id;

  const info = document.createElement("div");
  info.className = "settings-row-info";
  const labelEl = document.createElement("span");
  labelEl.className = "settings-row-label";
  labelEl.textContent = row.label;              // §10.1 — nunca innerHTML
  const descEl = document.createElement("span");
  descEl.className = "settings-row-desc";
  descEl.textContent = row.description;
  info.append(labelEl, descEl);

  const select = document.createElement("select");
  select.className = "settings-row-select";
  select.setAttribute("aria-label", `Nivel de confirmación para ${row.label}`);
  for (const opt of row.options) {               // CA-16: solo lo que Python ofrece
    const optionEl = document.createElement("option");
    optionEl.value = opt;
    optionEl.textContent = LEVEL_LABELS[opt] || opt;
    optionEl.selected = opt === row.effective_level;
    select.appendChild(optionEl);
  }
  select.addEventListener("change", () => {
    if (_pendingRowId === row.row_id) return;   // guard doble-click/doble-evento
    _pendingRowId = row.row_id;
    select.disabled = true;
    saveSecurityOverride(row.row_id, select.value);
  });

  item.append(info, select);
  return item;
}

export function handleSecurityOverrideSaved(rowId, _level) {
  _pendingRowId = null;
  const row = document.querySelector(`.settings-row[data-row-id="${rowId}"]`);
  if (row) {
    const select = row.querySelector("select");
    if (select) select.disabled = false;
  }
  showSettingsBanner("Cambio guardado. Se aplicará la próxima vez que abras la app.", false);   // CA-10
}

export function handleSecurityOverrideRejected(rowId) {
  _pendingRowId = null;
  const row = document.querySelector(`.settings-row[data-row-id="${rowId}"]`);
  if (row) {
    const select = row.querySelector("select");
    if (select) select.disabled = false;
  }
  requestSecurityOverrides();   // re-sincroniza TODA la sección con la verdad del backend
  showSettingsBanner("No se pudo aplicar ese cambio.", true);
}

function showSettingsBanner(message, isError) {
  const banner = document.getElementById("settings-banner");
  if (!banner) return;   // panel ya fue cerrado
  banner.textContent = message;   // texto propio del frontend, no confiable solo por precaución — nunca innerHTML
  banner.classList.toggle("settings-banner-error", Boolean(isError));
  banner.hidden = false;
}
