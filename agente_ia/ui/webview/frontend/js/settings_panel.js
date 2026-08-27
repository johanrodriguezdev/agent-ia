// ui/webview/frontend/js/settings_panel.js
// Pantalla "Configuración": modal con navegación lateral por secciones + panel de
// contenido con tarjetas.
//
// Secciones:
//   - "Perfil"     — nombre del agente, palabra de activación, nombre del usuario y
//                    cómo quiere que el agente lo trate. Se aplica al instante (sin
//                    reiniciar): al guardar, Python re-emite el perfil y la ventana se
//                    actualiza en vivo (ver app.js).
//   - "Seguridad"  — REQ-019/CA-12..CA-19: una fila por acción de la categoría v1
//                    (arquitectura-019.md §3.1) con su nivel efectivo y un <select> que
//                    solo ofrece el nivel vigente o superiores (CA-16). A diferencia de
//                    "Perfil", este cambio SÍ requiere reiniciar (CA-10).
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, extendida por arquitectura-016.md §10,
// arquitectura-019.md §6): cualquier campo recibido de Python (label, description,
// effective_level/base_level, opciones, valores del perfil) se inserta EXCLUSIVAMENTE vía
// textContent/value/setAttribute — nunca innerHTML/insertAdjacentHTML. Verificado además
// por un grep estructural en tests/test_webview_safe_dom_insertion.py.
//
// Modelo "aplicar al elegir" en Seguridad (arquitectura-019.md §4.2): cada fila es un
// <select> que al disparar `change` guarda de inmediato — no existe un botón de guardado
// separado ni un estado "elegido pero no guardado" que cerrar el modal pueda descartar
// (satisface CA-18 por construcción). "Perfil" sí usa botón, porque son campos de texto
// libre: guardar en cada tecla escribiría el config en disco decenas de veces.

import {
  requestSecurityOverrides, saveSecurityOverride, requestProfile, saveProfile,
} from "./bridge_client.js";

const LEVEL_LABELS = {
  green: "Sin confirmar",
  yellow: "Pide confirmación",
  red: "Bloqueado",
};

const PROFILE_FIELDS = [
  {
    key: "agent_name",
    label: "Nombre del agente",
    hint: "Cómo se llama tu asistente. Aparece en la ventana y en la bandeja del sistema.",
    placeholder: "O.R.I.O.N",
  },
  {
    key: "agent_pronunciation",
    label: "Palabra de activación",
    hint: "Cómo suena el nombre al decirlo en voz alta. Es lo que escucha para despertarse.",
    placeholder: "orion",
  },
  {
    key: "display_name",
    label: "Tu nombre completo",
    hint: "Para que el agente sepa con quién está hablando.",
    placeholder: "Tu nombre y apellido",
  },
  {
    key: "user_title",
    label: "Cómo debe dirigirse a ti",
    hint: "El trato que usa al hablarte. Déjalo vacío si prefieres que no use ninguno.",
    placeholder: "Señor",
  },
];

const SECTIONS = [
  { id: "perfil", label: "Perfil" },
  { id: "seguridad", label: "Seguridad" },
];

let _panelOpen = false;
let _pendingRowId = null;   // guard contra doble click/doble evento en la MISMA fila
let _activeSection = "perfil";

export function openSettingsPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  _activeSection = "perfil";
  renderShell();
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
  for (const section of SECTIONS) {
    const navItem = document.createElement("li");
    navItem.className = "settings-nav-item";
    navItem.classList.toggle("active", section.id === _activeSection);
    navItem.tabIndex = 0;
    navItem.textContent = section.label;   // texto propio
    navItem.addEventListener("click", () => selectSection(section.id));
    navItem.addEventListener("keydown", (evt) => {
      if (evt.key === "Enter" || evt.key === " ") {
        evt.preventDefault();
        selectSection(section.id);
      }
    });
    navList.appendChild(navItem);
  }
  nav.appendChild(navList);

  const content = document.createElement("div");
  content.className = "settings-content";
  content.id = "settings-content";

  layout.append(nav, content);
  box.append(header, layout);
  overlay.appendChild(box);
  root.appendChild(overlay);

  renderActiveSection();
}

function selectSection(sectionId) {
  if (sectionId === _activeSection) return;
  _activeSection = sectionId;
  for (const item of document.querySelectorAll(".settings-nav-item")) {
    const match = SECTIONS.find((s) => s.label === item.textContent);
    item.classList.toggle("active", Boolean(match) && match.id === sectionId);
  }
  renderActiveSection();
}

function renderActiveSection() {
  const content = document.getElementById("settings-content");
  if (!content) return;
  content.replaceChildren();

  const banner = document.createElement("div");
  banner.id = "settings-banner";
  banner.className = "settings-banner";
  banner.hidden = true;
  content.appendChild(banner);

  if (_activeSection === "perfil") {
    content.appendChild(buildProfileCard());
    requestProfile();          // carga perezosa: solo al entrar en la sección
  } else {
    content.appendChild(buildSecurityCard());
    requestSecurityOverrides();   // CA-19: carga perezosa, solo acá
  }
}

// ---------------------------------------------------------------- sección "Perfil"

function buildProfileCard() {
  const card = document.createElement("div");
  card.className = "settings-card";

  const cardTitle = document.createElement("div");
  cardTitle.className = "settings-card-title";
  cardTitle.textContent = "Perfil";   // texto propio
  card.appendChild(cardTitle);

  for (const field of PROFILE_FIELDS) {
    const row = document.createElement("div");
    row.className = "settings-row";

    const info = document.createElement("div");
    info.className = "settings-row-info";
    const labelEl = document.createElement("label");
    labelEl.className = "settings-row-label";
    labelEl.textContent = field.label;
    labelEl.setAttribute("for", `profile-${field.key}`);
    const hintEl = document.createElement("span");
    hintEl.className = "settings-row-desc";
    hintEl.textContent = field.hint;
    info.append(labelEl, hintEl);

    const input = document.createElement("input");
    input.type = "text";
    input.className = "settings-row-input";
    input.id = `profile-${field.key}`;
    input.dataset.profileKey = field.key;
    input.placeholder = field.placeholder;
    input.autocomplete = "off";

    row.append(info, input);
    card.appendChild(row);
  }

  const actions = document.createElement("div");
  actions.className = "settings-card-actions";
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.id = "profile-save-btn";
  saveBtn.className = "settings-primary-btn";
  saveBtn.textContent = "Guardar";
  saveBtn.addEventListener("click", submitProfile);
  actions.appendChild(saveBtn);
  card.appendChild(actions);

  return card;
}

function submitProfile() {
  const saveBtn = document.getElementById("profile-save-btn");
  const values = {};
  for (const field of PROFILE_FIELDS) {
    const input = document.getElementById(`profile-${field.key}`);
    values[field.key] = input ? input.value : "";
  }

  if (!values.agent_name.trim()) {
    showSettingsBanner("El nombre del agente no puede quedar vacío.", true);
    return;
  }

  if (saveBtn) saveBtn.disabled = true;
  saveProfile(
    values.agent_name, values.agent_pronunciation, values.display_name, values.user_title,
  );
}

export function renderProfile(profile) {
  for (const field of PROFILE_FIELDS) {
    const input = document.getElementById(`profile-${field.key}`);
    if (input) input.value = profile[field.key] || "";   // §10.1 — nunca innerHTML
  }
}

export function handleProfileSaved(_profile) {
  const saveBtn = document.getElementById("profile-save-btn");
  if (saveBtn) saveBtn.disabled = false;
  showSettingsBanner("Cambios guardados.", false);
}

// ---------------------------------------------------------------- sección "Seguridad"

function buildSecurityCard() {
  const card = document.createElement("div");
  card.className = "settings-card";
  const cardTitle = document.createElement("div");
  cardTitle.className = "settings-card-title";
  cardTitle.textContent = "Seguridad";   // texto propio
  const list = document.createElement("div");
  list.id = "security-section-list";
  card.append(cardTitle, list);
  return card;
}

export function renderSecurityOverrides(rows) {
  const list = document.getElementById("security-section-list");
  if (!list) return;   // panel ya cerrado (o sección cambiada) antes de que llegara la respuesta
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
