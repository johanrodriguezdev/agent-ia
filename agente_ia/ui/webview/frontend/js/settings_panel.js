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
  requestEmailCapabilities, saveEmailCapability,
  requestTaskModels, saveTaskModels,
  requestConnections, saveConnection, clearConnection,
  requestMcpServers, setMcpServerEnabled, removeMcpServer, probeMcpServer, loginMcpServer,
  saveMcpAllowedTools, saveMcpVariable, clearMcpVariable,
  setAutonomyMode,
} from "./bridge_client.js";
import { icon } from "./icons.js";

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
    // REQ-037 — sin nombre de ejemplo: sugerir "O.R.I.O.N" en el campo donde el usuario
    // elige cómo llamarlo es empujarlo a un nombre que no es suyo.
    placeholder: "Cómo querés llamarlo",
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
  { id: "modelos", label: "Modelos" },
  { id: "conexiones", label: "Conexiones" },
  { id: "seguridad", label: "Seguridad" },
];

let _panelOpen = false;
let _pendingRowId = null;   // guard contra doble click/doble evento en la MISMA fila
let _activeSection = "perfil";

export function openSettingsPanel(seccion) {
  if (_panelOpen) return;
  _panelOpen = true;
  // Se valida contra SECTIONS porque esta funcion tambien se usa como listener de click:
  // ahi el argumento es un Event, que no es ninguna seccion y cae en "perfil".
  _activeSection = SECTIONS.some((s) => s.id === seccion) ? seccion : "perfil";
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
  closeBtn.appendChild(icon("close", "ic-sm"));
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
  } else if (_activeSection === "modelos") {
    content.appendChild(buildModelsCard(null));
    requestTaskModels();       // mismo criterio: solo al entrar en la sección
  } else if (_activeSection === "conexiones") {
    content.appendChild(buildConnectionsCard(null));
    content.appendChild(buildMcpCard(null));
    requestConnections();
    requestMcpServers();
  } else {
    content.appendChild(buildAutonomyCard());
    content.appendChild(buildSecurityCard());
    content.appendChild(buildEmailCapabilitiesCard());
    requestSecurityOverrides();   // CA-19: carga perezosa, solo acá
    requestEmailCapabilities();   // mismo criterio: solo al entrar en la sección
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

// ------------------------------------------------- "Capacidades del correo"
//
// Ojo con la diferencia, que es la razón de que esto NO sea una fila más de Seguridad:
// las filas de arriba eligen CUÁNTA confirmación pide una acción (y solo se puede subir);
// estas eligen si la función existe siquiera. Encender "Enviar correos" no baja ninguna
// barrera — enviar sigue siendo ROJO y sigue pidiendo el PIN maestro. Apagado, ni se
// llega a preguntar.

let _pendingCapId = null;

function buildEmailCapabilitiesCard() {
  const card = document.createElement("div");
  card.className = "settings-card";

  const cardTitle = document.createElement("div");
  cardTitle.className = "settings-card-title";
  cardTitle.textContent = "Capacidades del correo";

  const nota = document.createElement("div");
  nota.className = "settings-row-desc";
  nota.textContent =
    "Vienen apagadas porque escriben sobre tu cuenta. Activarlas no quita las " +
    "confirmaciones: solo permite que la función exista.";

  const list = document.createElement("div");
  list.id = "email-capabilities-list";
  card.append(cardTitle, nota, list);
  return card;
}

export function renderEmailCapabilities(rows) {
  const list = document.getElementById("email-capabilities-list");
  if (!list) return;   // el panel ya se cerró antes de que llegara la respuesta
  list.replaceChildren();

  if (!rows || rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "No hay capacidades configurables.";
    list.appendChild(empty);
    return;
  }

  for (const row of rows) list.appendChild(buildCapabilityRow(row));
}

function buildCapabilityRow(row) {
  const item = document.createElement("div");
  item.className = "settings-row";
  item.dataset.capId = row.id;

  const info = document.createElement("div");
  info.className = "settings-row-info";
  const labelEl = document.createElement("span");
  labelEl.className = "settings-row-label";
  labelEl.textContent = row.label;              // nunca innerHTML
  const descEl = document.createElement("span");
  descEl.className = "settings-row-desc";
  descEl.textContent = row.description;
  info.append(labelEl, descEl);

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "settings-row-check";
  check.checked = Boolean(row.enabled);
  check.setAttribute("aria-label", row.label);
  check.addEventListener("change", () => {
    if (_pendingCapId === row.id) return;      // guard doble-click
    _pendingCapId = row.id;
    check.disabled = true;
    saveEmailCapability(row.id, check.checked);
  });

  item.append(info, check);
  return item;
}

export function handleEmailCapabilitySaved(capId, enabled) {
  _pendingCapId = null;
  const row = document.querySelector(`.settings-row[data-cap-id="${capId}"]`);
  const check = row && row.querySelector("input");
  if (check) {
    check.disabled = false;
    check.checked = Boolean(enabled);
  }
  showSettingsBanner(
    enabled
      ? "Activado. Se aplicará la próxima vez que abras la app, y seguirá pidiendo confirmación."
      : "Desactivado. Se aplicará la próxima vez que abras la app.",
    false,
  );
}

export function handleEmailCapabilityRejected(capId) {
  _pendingCapId = null;
  const row = document.querySelector(`.settings-row[data-cap-id="${capId}"]`);
  const check = row && row.querySelector("input");
  if (check) check.disabled = false;
  requestEmailCapabilities();   // re-sincroniza con la verdad del backend
  showSettingsBanner("No se pudo aplicar ese cambio.", true);
}

// ---------------------------------------------------------------- sección "Modelos"
//
// Qué modelo atiende cada tipo de trabajo. La gracia está en poder poner VARIOS por
// tarea: los catálogos gratuitos se quedan sin cuota todo el tiempo, y con una lista el
// agente pasa al siguiente en vez de abandonar la tarea o irse al modelo de pago.

let _catalogoModelos = [];

function buildModelsCard(payload) {
  const card = document.createElement("div");
  card.className = "settings-card";

  const title = document.createElement("div");
  title.className = "settings-card-title";
  title.textContent = "Modelo por tipo de trabajo";
  card.appendChild(title);

  const ayuda = document.createElement("p");
  ayuda.className = "settings-help";
  ayuda.textContent = payload
    ? `Sin nada elegido, cada tarea usa el modelo general (${payload.general}). `
      + "Puedes poner varios: si el primero se queda sin cuota, se prueba el siguiente."
    : "Cargando…";
  card.appendChild(ayuda);

  if (!payload) return card;

  for (const aviso of payload.avisos || []) {
    const linea = document.createElement("p");
    linea.className = "settings-help settings-help-warn";
    linea.textContent = aviso;               // §10.1 — viene de Python, nunca innerHTML
    card.appendChild(linea);
  }

  for (const tarea of payload.tareas) {
    card.appendChild(buildTaskRow(tarea));
  }
  return card;
}

function buildTaskRow(tarea) {
  const fila = document.createElement("div");
  fila.className = "settings-row settings-row-block";

  const info = document.createElement("div");
  info.className = "settings-row-info";
  const nombre = document.createElement("span");
  nombre.className = "settings-row-label";
  nombre.textContent = tarea.label;          // §10.1 — nunca innerHTML
  const desc = document.createElement("span");
  desc.className = "settings-row-desc";
  desc.textContent = tarea.descripcion;
  info.append(nombre, desc);
  fila.appendChild(info);

  const lista = document.createElement("div");
  lista.className = "model-chain";

  if (tarea.destinos.length === 0) {
    const vacio = document.createElement("span");
    vacio.className = "settings-row-desc";
    vacio.textContent = "Usa el modelo general.";
    lista.appendChild(vacio);
  }

  tarea.destinos.forEach((destino, indice) => {
    lista.appendChild(buildDestinoChip(tarea, destino, indice));
  });

  // Agregar: un `<select>` con todo el catálogo. Elegir agrega al final de la cadena.
  const agregar = document.createElement("select");
  agregar.className = "model-add";
  agregar.setAttribute("aria-label", `Agregar un modelo a ${tarea.label}`);

  const inicial = document.createElement("option");
  inicial.value = "";
  inicial.textContent = "+ Agregar modelo…";
  agregar.appendChild(inicial);

  for (const modelo of _catalogoModelos) {
    const ya = tarea.destinos.some(
      (d) => d.proveedor === modelo.proveedor && d.modelo === modelo.modelo,
    );
    if (ya) continue;
    const opcion = document.createElement("option");
    opcion.value = `${modelo.proveedor}|${modelo.modelo}`;
    // El "gratis" va en el texto y no en un color: el `<option>` nativo no se estiliza.
    opcion.textContent = modelo.gratis ? `${modelo.label} — gratis` : modelo.label;
    agregar.appendChild(opcion);
  }

  agregar.addEventListener("change", () => {
    if (!agregar.value) return;
    const [proveedor, modelo] = agregar.value.split("|");
    guardarCadena(tarea, [...tarea.destinos, { proveedor, modelo }]);
  });

  lista.appendChild(agregar);
  fila.appendChild(lista);
  return fila;
}

function buildDestinoChip(tarea, destino, indice) {
  const chip = document.createElement("span");
  chip.className = "model-chip" + (destino.gratis ? " model-chip-gratis" : "");

  const orden = document.createElement("span");
  orden.className = "model-chip-orden";
  orden.textContent = `${indice + 1}`;
  chip.appendChild(orden);

  const nombre = document.createElement("span");
  nombre.textContent = destino.label;        // §10.1
  chip.appendChild(nombre);

  const quitar = document.createElement("button");
  quitar.type = "button";
  quitar.className = "model-chip-quitar";
  quitar.setAttribute("aria-label", `Quitar ${destino.label}`);
  quitar.appendChild(icon("close", "ic-sm"));
  quitar.addEventListener("click", () => {
    guardarCadena(tarea, tarea.destinos.filter((_, i) => i !== indice));
  });
  chip.appendChild(quitar);

  return chip;
}

function guardarCadena(tarea, destinos) {
  saveTaskModels(
    tarea.id,
    JSON.stringify(destinos.map((d) => ({ proveedor: d.proveedor, modelo: d.modelo }))),
  );
}

/** Llega de `task_models_loaded`: repinta la sección entera con lo que hay guardado. */
export function renderTaskModels(payload) {
  _catalogoModelos = payload.catalogo || [];
  if (_activeSection !== "modelos") return;
  const content = document.getElementById("settings-content");
  if (!content) return;

  const anterior = content.querySelector(".settings-card");
  const nueva = buildModelsCard(payload);
  if (anterior) anterior.replaceWith(nueva);
  else content.appendChild(nueva);
}

// ------------------------------------------------------- sección "Conexiones"
//
// Las claves que la app necesita. El valor NUNCA viaja del lado de Python a la página: solo
// llega si está puesta y de dónde sale. Devolverla la dejaría en el DOM, en una captura de
// pantalla o en un volcado del webview, y para decidir si hay que cambiarla no hace falta
// verla.

function buildConnectionsCard(payload) {
  const card = document.createElement("div");
  card.className = "settings-card";
  card.id = "connections-card";

  const title = document.createElement("div");
  title.className = "settings-card-title";
  title.textContent = "Claves y credenciales";
  card.appendChild(title);

  const ayuda = document.createElement("p");
  ayuda.className = "settings-help";
  ayuda.textContent = payload
    ? "Se guardan en config.json, en este equipo. Una variable de entorno con el mismo "
      + "nombre manda sobre lo que pongas aquí."
    : "Cargando…";
  card.appendChild(ayuda);

  if (!payload) return card;

  for (const fila of payload.conexiones) {
    card.appendChild(buildConnectionRow(fila));
  }
  return card;
}

function buildConnectionRow(fila) {
  const row = document.createElement("div");
  row.className = "settings-row settings-row-block";

  const info = document.createElement("div");
  info.className = "settings-row-info";
  const nombre = document.createElement("span");
  nombre.className = "settings-row-label";
  nombre.textContent = fila.label;              // §10.1 — nunca innerHTML
  const desc = document.createElement("span");
  desc.className = "settings-row-desc";
  desc.textContent = fila.descripcion;
  info.append(nombre, desc);

  const estado = document.createElement("span");
  estado.className = "conexion-estado conexion-estado-" + (fila.origen || "vacia");
  estado.textContent = {
    entorno: "Configurada (variable de entorno)",
    archivo: "Configurada",
  }[fila.origen] || "Sin configurar";
  info.appendChild(estado);
  row.appendChild(info);

  const acciones = document.createElement("div");
  acciones.className = "conexion-acciones";

  const campo = document.createElement("input");
  campo.type = "password";                      // no se ve al escribir ni al pegar
  campo.className = "settings-input conexion-input";
  campo.placeholder = fila.origen ? "Reemplazar…" : "Pegar la clave…";
  campo.setAttribute("aria-label", "Clave de " + fila.label);
  campo.autocomplete = "off";

  const guardar = document.createElement("button");
  guardar.type = "button";
  guardar.className = "panel-submit-btn conexion-guardar";
  guardar.textContent = "Guardar";
  guardar.addEventListener("click", () => {
    const valor = campo.value.trim();
    if (!valor) return;
    saveConnection(fila.id, valor);
    campo.value = "";                           // no se queda en el DOM tras guardarla
  });
  campo.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") guardar.click();
  });

  acciones.append(campo, guardar);

  // Quitar solo tiene sentido sobre lo que está EN EL ARCHIVO: lo del entorno no se toca
  // desde aquí, y ofrecer un botón que no puede cumplir sería mentir.
  if (fila.origen === "archivo") {
    const quitar = document.createElement("button");
    quitar.type = "button";
    quitar.className = "panel-submit-btn panel-submit-btn-secundario conexion-quitar";
    quitar.textContent = "Quitar";
    quitar.addEventListener("click", () => clearConnection(fila.id));
    acciones.appendChild(quitar);
  }

  row.appendChild(acciones);
  return row;
}

/** Llega de `connections_loaded`: repinta la sección con lo que hay guardado. */
export function renderConnections(payload) {
  if (_activeSection !== "conexiones") return;
  const content = document.getElementById("settings-content");
  if (!content) return;

  const anterior = content.querySelector("#connections-card");
  const nueva = buildConnectionsCard(payload);
  if (anterior) anterior.replaceWith(nueva);
  else content.appendChild(nueva);
}

// ---------------------------------------------------------------- servidores MCP (REQ-043)
//
// Segunda tarjeta de la sección "Conexiones". No hay formulario para AGREGAR un servidor:
// eso se le pide al agente ("conectate al servidor MCP de Notion, el comando es ...") y
// él lo declara con confirmación. La pantalla es para ver cómo están, apagarlos,
// probarlos, quitarlos, decidir qué herramientas se aceptan y pegar los secretos que
// necesitan — que es justo lo que no debe pasar por el chat.

const EJEMPLO_PEDIDO_MCP =
  "«Conectate al servidor MCP de Notion: el comando es npx -y @notionhq/notion-mcp-server "
  + "y necesita la variable NOTION_TOKEN».";

function buildMcpCard(payload) {
  const card = document.createElement("div");
  card.className = "settings-card";
  card.id = "mcp-card";

  const title = document.createElement("div");
  title.className = "settings-card-title";
  title.textContent = "Servidores MCP";
  card.appendChild(title);

  const ayuda = document.createElement("p");
  ayuda.className = "settings-help";
  if (!payload) {
    ayuda.textContent = "Cargando…";
    card.appendChild(ayuda);
    return card;
  }
  ayuda.textContent =
    "Programas externos que le prestan herramientas al agente. Para agregar uno, pedíselo "
    + "en el chat, por ejemplo: " + EJEMPLO_PEDIDO_MCP + " Nada queda habilitado hasta que "
    + "digas qué herramientas aceptás.";
  card.appendChild(ayuda);

  if (!payload.servidores.length) {
    const vacio = document.createElement("p");
    vacio.className = "settings-help mcp-vacio";
    vacio.textContent = "Todavía no hay ningún servidor declarado.";
    card.appendChild(vacio);
    return card;
  }

  for (const servidor of payload.servidores) {
    card.appendChild(buildMcpServerRow(servidor, payload.canales));
  }

  if (payload.variables.length) {
    card.appendChild(buildMcpVariablesBlock(payload.variables));
  }
  return card;
}

function estadoMcp(servidor) {
  if (!servidor.enabled) return { clase: "vacia", texto: "Deshabilitado" };
  if (!servidor.conectado) return { clase: "error", texto: "Desconectado" };
  if (!servidor.herramientas.length) {
    return { clase: "vacia", texto: "Conectado · sin herramientas habilitadas" };
  }
  const n = servidor.herramientas.length;
  return { clase: "archivo", texto: `Conectado · ${n} herramienta${n === 1 ? "" : "s"}` };
}

function buildMcpServerRow(servidor, canalesPosibles) {
  const row = document.createElement("div");
  row.className = "settings-row settings-row-block mcp-servidor";
  row.dataset.mcpServer = servidor.nombre;

  const cabecera = document.createElement("div");
  cabecera.className = "mcp-cabecera";

  const info = document.createElement("div");
  info.className = "settings-row-info";
  const nombre = document.createElement("span");
  nombre.className = "settings-row-label";
  nombre.textContent = servidor.nombre;               // nunca innerHTML
  const destino = document.createElement("span");
  destino.className = "settings-row-desc mcp-destino";
  destino.textContent = (servidor.transporte === "http" ? "HTTP · " : "Local · ") + servidor.destino;
  const estado = estadoMcp(servidor);
  const chip = document.createElement("span");
  chip.className = "conexion-estado conexion-estado-" + estado.clase;
  chip.textContent = estado.texto;
  info.append(nombre, destino, chip);

  const interruptor = document.createElement("input");
  interruptor.type = "checkbox";
  interruptor.className = "settings-row-check";
  interruptor.checked = Boolean(servidor.enabled);
  interruptor.setAttribute("aria-label", "Habilitar " + servidor.nombre);
  interruptor.addEventListener("change", () => {
    interruptor.disabled = true;                      // se repinta con la respuesta
    setMcpServerEnabled(servidor.nombre, interruptor.checked);
  });

  cabecera.append(info, interruptor);
  row.appendChild(cabecera);

  if (servidor.herramientas.length) {
    const lista = document.createElement("span");
    lista.className = "settings-row-desc";
    lista.textContent = "Habilitadas ahora: " + servidor.herramientas.join(", ");
    row.appendChild(lista);
  }

  row.appendChild(buildMcpAllowedEditor(servidor, canalesPosibles));

  const acciones = document.createElement("div");
  acciones.className = "conexion-acciones";

  const probar = document.createElement("button");
  probar.type = "button";
  probar.className = "panel-submit-btn panel-submit-btn-secundario";
  probar.textContent = "Probar";
  probar.addEventListener("click", () => {
    probar.disabled = true;
    mostrarSondeoMcp(row, "Probando…");
    probeMcpServer(servidor.nombre);
  });
  acciones.appendChild(probar);

  if (servidor.transporte === "http") {
    const autorizar = document.createElement("button");
    autorizar.type = "button";
    autorizar.className = "panel-submit-btn panel-submit-btn-secundario";
    autorizar.textContent = "Autorizar (OAuth)";
    autorizar.title = "Abre el navegador para autorizar el acceso, si el servidor lo pide.";
    autorizar.addEventListener("click", () => loginMcpServer(servidor.nombre));
    acciones.appendChild(autorizar);
  }

  const quitar = document.createElement("button");
  quitar.type = "button";
  quitar.className = "panel-submit-btn panel-submit-btn-secundario conexion-quitar";
  quitar.textContent = "Quitar";
  quitar.addEventListener("click", () => removeMcpServer(servidor.nombre));
  acciones.appendChild(quitar);

  row.appendChild(acciones);

  const sondeo = document.createElement("pre");
  sondeo.className = "mcp-sondeo";
  sondeo.hidden = true;
  row.appendChild(sondeo);
  return row;
}

function buildMcpAllowedEditor(servidor, canalesPosibles) {
  const bloque = document.createElement("div");
  bloque.className = "mcp-permitidas";

  const etiqueta = document.createElement("label");
  etiqueta.className = "settings-row-desc";
  etiqueta.textContent = "Herramientas permitidas (nombres o patrones, separados por coma)";
  const campo = document.createElement("input");
  campo.type = "text";
  campo.className = "settings-input";
  campo.value = servidor.permitidas.join(", ");
  campo.placeholder = "search, read_*";
  campo.setAttribute("aria-label", "Herramientas permitidas de " + servidor.nombre);
  etiqueta.appendChild(campo);

  const canales = document.createElement("div");
  canales.className = "mcp-canales";
  const marcados = new Set(servidor.canales.length ? servidor.canales : ["desktop"]);
  const casillas = [];
  for (const canal of canalesPosibles) {
    const item = document.createElement("label");
    item.className = "mcp-canal";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.value = canal;
    check.checked = marcados.has(canal);
    check.disabled = canal === "desktop";             // siempre: es donde se confirma
    const texto = document.createElement("span");
    texto.textContent = { desktop: "escritorio", telegram: "Telegram", discord: "Discord", voice: "voz" }[canal] || canal;
    item.append(check, texto);
    canales.appendChild(item);
    casillas.push(check);
  }

  const guardar = document.createElement("button");
  guardar.type = "button";
  guardar.className = "panel-submit-btn conexion-guardar";
  guardar.textContent = "Guardar";
  guardar.addEventListener("click", () => {
    const patrones = campo.value.trim();
    if (!patrones) {
      showSettingsBanner("Escribe al menos una herramienta. Para cortar todo, deshabilita o quita el servidor.", true);
      return;
    }
    const elegidos = casillas.filter((c) => c.checked).map((c) => c.value).join(",");
    guardar.disabled = true;
    saveMcpAllowedTools(servidor.nombre, patrones, elegidos);
  });
  campo.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") guardar.click();
  });

  const fila = document.createElement("div");
  fila.className = "conexion-acciones";
  fila.append(canales, guardar);
  bloque.append(etiqueta, fila);
  return bloque;
}

function buildMcpVariablesBlock(variables) {
  const bloque = document.createElement("div");
  bloque.className = "mcp-variables";

  const titulo = document.createElement("div");
  titulo.className = "settings-row-label";
  titulo.textContent = "Variables";
  const ayuda = document.createElement("p");
  ayuda.className = "settings-help";
  ayuda.textContent =
    "Los tokens que los servidores necesitan. Se guardan en config.json, en este equipo, y no "
    + "pasan por el chat. Una variable de entorno con el mismo nombre manda sobre lo que pongas aquí.";
  bloque.append(titulo, ayuda);

  for (const variable of variables) {
    bloque.appendChild(buildMcpVariableRow(variable));
  }
  return bloque;
}

function buildMcpVariableRow(variable) {
  const row = document.createElement("div");
  row.className = "settings-row settings-row-block";

  const info = document.createElement("div");
  info.className = "settings-row-info";
  const nombre = document.createElement("span");
  nombre.className = "settings-row-label";
  nombre.textContent = variable.nombre;
  const usada = document.createElement("span");
  usada.className = "settings-row-desc";
  usada.textContent = "La usa: " + variable.servidores.join(", ");
  const estado = document.createElement("span");
  estado.className = "conexion-estado conexion-estado-" + (variable.origen || "vacia");
  estado.textContent = {
    entorno: "Definida (variable de entorno)",
    archivo: "Definida",
  }[variable.origen] || "Sin definir";
  info.append(nombre, usada, estado);
  row.appendChild(info);

  const acciones = document.createElement("div");
  acciones.className = "conexion-acciones";

  const campo = document.createElement("input");
  campo.type = "password";                            // no se ve al escribir ni al pegar
  campo.className = "settings-input conexion-input";
  campo.placeholder = variable.origen ? "Reemplazar…" : "Pegar el valor…";
  campo.setAttribute("aria-label", "Valor de " + variable.nombre);
  campo.autocomplete = "off";

  const guardar = document.createElement("button");
  guardar.type = "button";
  guardar.className = "panel-submit-btn conexion-guardar";
  guardar.textContent = "Guardar";
  guardar.addEventListener("click", () => {
    const valor = campo.value.trim();
    if (!valor) return;
    saveMcpVariable(variable.nombre, valor);
    campo.value = "";                                 // no se queda en el DOM
  });
  campo.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter") guardar.click();
  });
  acciones.append(campo, guardar);

  if (variable.origen === "archivo") {
    const quitar = document.createElement("button");
    quitar.type = "button";
    quitar.className = "panel-submit-btn panel-submit-btn-secundario conexion-quitar";
    quitar.textContent = "Quitar";
    quitar.addEventListener("click", () => clearMcpVariable(variable.nombre));
    acciones.appendChild(quitar);
  }

  row.appendChild(acciones);
  return row;
}

function mostrarSondeoMcp(row, texto) {
  const sondeo = row.querySelector(".mcp-sondeo");
  if (!sondeo) return;
  sondeo.textContent = texto;                         // texto plano del sondeo
  sondeo.hidden = !texto;
}

/** Llega de `mcp_servers_loaded`: repinta la tarjeta con el estado actual. */
export function renderMcpServers(payload) {
  if (_activeSection !== "conexiones") return;
  const content = document.getElementById("settings-content");
  if (!content) return;

  const anterior = content.querySelector("#mcp-card");
  const nueva = buildMcpCard(payload);
  if (anterior) anterior.replaceWith(nueva);
  else content.appendChild(nueva);
}

/** Llega de `mcp_probe_result`: el texto del sondeo va en la fila del servidor. */
export function renderMcpProbe(nombre, texto) {
  const row = document.querySelector(`.mcp-servidor[data-mcp-server="${CSS.escape(nombre)}"]`);
  if (!row) return;
  mostrarSondeoMcp(row, texto);
  const probar = Array.from(row.querySelectorAll("button")).find((b) => b.textContent === "Probar");
  if (probar) probar.disabled = false;
}

// ---------------------------------------------------------------- modo autonomía (REQ-033)
//
// Va dentro de "Seguridad" y no en una sección propia porque es exactamente eso: cuánto
// puede hacer el agente sin preguntar. Tres niveles, y el tercero pide el PIN maestro — el
// mecanismo que `security_manager` ya tenía previsto para lo rojo y nunca se había usado.

const NIVELES_AUTONOMIA = [
  {
    id: "normal",
    label: "Normal",
    detalle: "Pregunta antes de escribir un archivo, editarlo o ejecutar algo. Es el estado de fábrica.",
  },
  {
    id: "proyectos",
    label: "Trabajar sin preguntar en mis proyectos",
    detalle: "Escribe, edita y ejecuta dentro de las carpetas habilitadas sin interrumpir. "
           + "Sigue preguntando para todo lo demás: apagar el equipo, mandar mensajes, habilitar otra carpeta.",
  },
  {
    id: "total",
    label: "Total: además puede mejorar su propio código",
    detalle: "Lo anterior, y además puede modificar su propio código. Pide el PIN maestro "
           + "y trabaja sobre una rama de git aparte, para que puedas ver el diff y volver atrás.",
  },
];

function buildAutonomyCard() {
  const card = document.createElement("div");
  card.className = "settings-card";

  const cardTitle = document.createElement("div");
  cardTitle.className = "settings-card-title";
  cardTitle.textContent = "Modo autonomía";

  const aviso = document.createElement("div");
  aviso.className = "settings-row-description";
  aviso.textContent = "Nada de esto alcanza a Telegram, Discord, voz ni correo: el modo vive "
                    + "en este equipo. Queda encendido hasta que lo apagues.";

  const lista = document.createElement("div");
  lista.id = "autonomy-options";
  for (const nivel of NIVELES_AUTONOMIA) lista.appendChild(buildAutonomyRow(nivel));

  const estado = document.createElement("div");
  estado.id = "autonomy-state";
  estado.className = "settings-row-description";

  card.append(cardTitle, aviso, lista, estado);
  return card;
}

function buildAutonomyRow(nivel) {
  const fila = document.createElement("div");
  fila.className = "settings-row";
  fila.dataset.nivel = nivel.id;

  const texto = document.createElement("div");
  texto.className = "settings-row-text";
  const titulo = document.createElement("div");
  titulo.className = "settings-row-label";
  titulo.textContent = nivel.label;
  const detalle = document.createElement("div");
  detalle.className = "settings-row-description";
  detalle.textContent = nivel.detalle;
  texto.append(titulo, detalle);

  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "settings-row-action";
  boton.textContent = "Activar";
  boton.addEventListener("click", () => activarNivel(nivel.id));

  fila.append(texto, boton);
  return fila;
}

function activarNivel(nivel) {
  // El PIN se pide EN EL MOMENTO de encender, una sola vez. Durante la noche no vuelve a
  // aparecer: esa es toda la idea del modo.
  let pin = "";
  if (nivel === "total") {
    pin = window.prompt("PIN maestro para autorizar que modifique su propio código:") || "";
    if (!pin) return;
  }
  setAutonomyMode(nivel, pin);
}

export function renderAutonomy(estado) {
  const lista = document.getElementById("autonomy-options");
  if (lista) {
    for (const fila of lista.children) {
      const activo = fila.dataset.nivel === estado.nivel;
      const boton = fila.querySelector("button");
      if (boton) {
        boton.textContent = activo ? "Activo" : "Activar";
        boton.disabled = activo;
      }
    }
  }
  const linea = document.getElementById("autonomy-state");
  if (linea) {
    linea.textContent = estado.activo
      ? `Encendido desde ${estado.desde}` + (estado.rama ? ` sobre la rama ${estado.rama}.` : ".")
      : "";
  }
}
