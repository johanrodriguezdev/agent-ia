// ui/webview/frontend/js/projects_panel.js
// REQ-016/CA-13..CA-21 — modal de Proyectos: maestro/detalle + picker de asignación.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, extendida por arquitectura-016.md §10):
// cualquier campo recibido de Python que no sea `html` ya sanitizado se inserta
// EXCLUSIVAMENTE vía `textContent`/`setAttribute` — nunca `innerHTML`/`insertAdjacentHTML`.
// Verificado además por un grep estructural en tests/test_webview_safe_dom_insertion.py.

import {
  requestProjects, createProject, assignConversationToProject,
  unassignConversationFromProject, requestProjectConversations, requestDeleteProject,
  requestProjectItems, assignItemToProject, unassignItemFromProject, requestAssignableItems,
} from "./bridge_client.js";
import { icon } from "./icons.js";
import { getLoadedConversations } from "./sidebar.js";   // REQ-016/§0.2

let _panelOpen = false;
let _detailProjectId = null;   // null = vista maestro; distinto de null = vista detalle

export function openProjectsPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  _detailProjectId = null;
  renderMasterShell();
  requestProjects();
}

export function closeProjectsPanel() {
  _panelOpen = false;
  _detailProjectId = null;
  document.getElementById("panel-modal-root").replaceChildren();
}

function renderMasterShell() {
  const root = document.getElementById("panel-modal-root");
  root.replaceChildren();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) closeProjectsPanel(); });

  const box = document.createElement("div");
  box.className = "modal-box modal-box-wide";

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Proyectos";   // texto propio, no viene de Python — no aplica §10.1
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.appendChild(icon("close", "ic-sm"));
  closeBtn.addEventListener("click", closeProjectsPanel);
  header.appendChild(title);
  header.appendChild(closeBtn);

  const form = buildProjectForm();
  const list = document.createElement("div");
  list.id = "projects-panel-list";
  list.className = "panel-list";

  box.appendChild(header);
  box.appendChild(form);
  box.appendChild(list);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

function buildProjectForm() {
  const form = document.createElement("form");
  form.className = "panel-form";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.placeholder = "Nombre del proyecto";
  nameInput.required = true;

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  submitBtn.className = "panel-submit-btn";
  submitBtn.textContent = "Crear";

  form.append(nameInput, submitBtn);
  form.addEventListener("submit", (evt) => {
    evt.preventDefault();
    const nameValue = nameInput.value.trim();
    if (!nameValue) return;   // CA-14: nombre obligatorio, guard también del lado JS
    createProject(nameValue);
    form.reset();
  });
  return form;
}

export function renderProjects(projects) {
  if (_detailProjectId !== null) return;   // hay una vista de detalle abierta, no pisar su lista
  const list = document.getElementById("projects-panel-list");
  if (!list) return;
  list.replaceChildren();
  if (projects.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "No hay proyectos todavía.";
    list.appendChild(empty);
    return;
  }
  for (const project of projects) {
    list.appendChild(buildProjectItem(project));
  }
}

function buildProjectItem(project) {
  const item = document.createElement("div");
  item.className = "panel-item";

  const info = document.createElement("div");
  info.className = "panel-item-info";
  const nameEl = document.createElement("span");
  nameEl.className = "panel-item-title";
  nameEl.textContent = project.name;   // §10.1 — nunca innerHTML
  const countEl = document.createElement("span");
  countEl.className = "panel-item-meta";
  countEl.textContent = `${project.conversation_count} conversación(es)`;
  info.appendChild(nameEl);
  info.appendChild(countEl);

  const actions = document.createElement("div");
  actions.className = "panel-item-actions";

  const viewBtn = document.createElement("button");
  viewBtn.type = "button";
  viewBtn.className = "panel-item-btn";
  viewBtn.textContent = "Ver";
  viewBtn.addEventListener("click", () => openProjectDetail(project.id, project.name));
  actions.appendChild(viewBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "panel-item-btn panel-item-btn-danger";
  deleteBtn.setAttribute("aria-label", "Eliminar proyecto");
  deleteBtn.title = "Eliminar proyecto";
  deleteBtn.appendChild(icon("trash", "ic-sm"));
  deleteBtn.addEventListener("click", () => requestDeleteProject(project.id));   // CA-18: YELLOW
  actions.appendChild(deleteBtn);

  item.append(info, actions);
  return item;
}

let _pickerProjectId = null;

function openProjectDetail(projectId, projectName) {
  _detailProjectId = projectId;
  renderDetailShell(projectId, projectName);
  requestProjectConversations(projectId);
  requestProjectItems(projectId);
}

function renderDetailShell(projectId, projectName) {
  const root = document.getElementById("panel-modal-root");
  root.replaceChildren();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) closeProjectsPanel(); });

  const box = document.createElement("div");
  box.className = "modal-box modal-box-wide";

  const header = document.createElement("div");
  header.className = "panel-header";

  const backBtn = document.createElement("button");
  backBtn.type = "button";
  backBtn.className = "panel-back-btn";
  backBtn.setAttribute("aria-label", "Volver");
  backBtn.textContent = "← Volver";
  backBtn.addEventListener("click", () => {
    _detailProjectId = null;
    renderMasterShell();
    requestProjects();
  });

  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = projectName;   // §10.1 — nunca innerHTML

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.appendChild(icon("close", "ic-sm"));
  closeBtn.addEventListener("click", closeProjectsPanel);

  header.append(backBtn, title, closeBtn);

  // Un proyecto agrupa lo que se hizo, no solo lo que se habló: chats, flujos y las
  // partes del sistema que le corresponden. Dos botones, dos listas.
  const acciones = document.createElement("div");
  acciones.className = "panel-form";

  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "panel-submit-btn";
  addBtn.textContent = "+ Conversación";
  addBtn.addEventListener("click", () => openAssignPicker(projectId));

  const addItemBtn = document.createElement("button");
  addItemBtn.type = "button";
  addItemBtn.className = "panel-submit-btn panel-submit-btn-secundario";
  addItemBtn.textContent = "+ Flujo o módulo";
  addItemBtn.addEventListener("click", () => {
    _pickerProjectId = projectId;
    requestAssignableItems();
  });

  acciones.append(addBtn, addItemBtn);

  const list = document.createElement("div");
  list.id = "project-detail-list";
  list.className = "panel-list";

  const tituloItems = document.createElement("div");
  tituloItems.className = "panel-section-title";
  tituloItems.textContent = "Flujos y módulos";

  const listaItems = document.createElement("div");
  listaItems.id = "project-items-list";
  listaItems.className = "panel-list";

  box.appendChild(header);
  box.appendChild(acciones);
  box.appendChild(list);
  box.appendChild(tituloItems);
  box.appendChild(listaItems);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

// El handler de `project_conversations_loaded(json, projectId)` (cableado en app.js) descarta la
// respuesta si `projectId` no coincide con `_detailProjectId` — caso borde de SPEC-016: doble click
// rápido entre dos proyectos no debe mezclar datos de un proyecto con la vista del otro.
export function renderProjectConversations(conversations, projectId) {
  if (projectId !== _detailProjectId) return;
  const list = document.getElementById("project-detail-list");
  if (!list) return;
  list.replaceChildren();

  if (conversations.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "Este proyecto no tiene conversaciones todavía.";
    list.appendChild(empty);
    return;
  }

  for (const conv of conversations) {
    const row = document.createElement("div");
    row.className = "panel-item";
    const titleEl = document.createElement("span");
    titleEl.className = "panel-item-title";
    titleEl.textContent = conv.title;   // §10.1 — nunca innerHTML
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "panel-item-btn";
    removeBtn.textContent = "Quitar";
    removeBtn.addEventListener("click", () => {
      unassignConversationFromProject(conv.conversation_id);
      row.remove();   // feedback inmediato — projects_loaded (conteo) llega poco después igual
    });
    row.append(titleEl, removeBtn);
    list.appendChild(row);
  }
}

// Si el proyecto en vista detalle es el que se acaba de borrar, volver al maestro
// (arquitectura-016.md §0.4 — señal "targeted" project_removed).
/** Flujos y módulos del proyecto. Misma guarda que las conversaciones: una respuesta de
 *  otro proyecto (doble click rápido entre dos) se descarta en vez de mezclarse. */
export function renderProjectItems(items, projectId) {
  if (projectId !== _detailProjectId) return;
  const lista = document.getElementById("project-items-list");
  if (!lista) return;
  lista.replaceChildren();

  if (items.length === 0) {
    const vacio = document.createElement("div");
    vacio.className = "panel-empty";
    vacio.textContent = "Sin flujos ni módulos asignados.";
    lista.appendChild(vacio);
    return;
  }

  for (const item of items) {
    const fila = document.createElement("div");
    fila.className = "panel-item";

    const info = document.createElement("div");
    info.className = "panel-item-info";
    const titulo = document.createElement("span");
    titulo.className = "panel-item-title";
    titulo.textContent = item.label || item.item_id;   // §10.1
    const meta = document.createElement("span");
    meta.className = "panel-item-meta";
    meta.textContent = item.kind === "flujo" ? "Flujo" : "Módulo";
    info.append(titulo, meta);

    const quitar = document.createElement("button");
    quitar.type = "button";
    quitar.className = "panel-item-btn";
    quitar.textContent = "Quitar";
    quitar.addEventListener("click", () => {
      unassignItemFromProject(item.kind, item.item_id, projectId);
      fila.remove();
    });

    fila.append(info, quitar);
    lista.appendChild(fila);
  }
}

/** Picker de flujos y módulos: llega cuando Python responde `assignable_items_loaded`. */
export function renderAssignableItems(payload) {
  if (_pickerProjectId === null) return;
  const projectId = _pickerProjectId;
  _pickerProjectId = null;

  const root = document.getElementById("panel-modal-root");
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) overlay.remove(); });

  const box = document.createElement("div");
  box.className = "modal-box";

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Agregar al proyecto";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.appendChild(icon("close", "ic-sm"));
  closeBtn.addEventListener("click", () => overlay.remove());
  header.append(title, closeBtn);

  const lista = document.createElement("div");
  lista.className = "panel-list";

  function agregarGrupo(etiqueta, kind, elementos) {
    if (!elementos.length) return;
    const titulo = document.createElement("div");
    titulo.className = "panel-section-title";
    titulo.textContent = etiqueta;
    lista.appendChild(titulo);

    for (const elemento of elementos) {
      const boton = document.createElement("button");
      boton.type = "button";
      boton.className = "panel-item panel-item-pickable";
      const nombre = document.createElement("span");
      nombre.className = "panel-item-title";
      nombre.textContent = elemento.label;   // §10.1
      boton.appendChild(nombre);
      boton.addEventListener("click", () => {
        assignItemToProject(kind, elemento.id, projectId, elemento.label);
        overlay.remove();
      });
      lista.appendChild(boton);
    }
  }

  agregarGrupo("Flujos", "flujo", payload.flujos || []);
  agregarGrupo("Módulos", "modulo", payload.modulos || []);

  if (!lista.children.length) {
    const vacio = document.createElement("div");
    vacio.className = "panel-empty";
    vacio.textContent = "No hay nada para agregar todavía.";
    lista.appendChild(vacio);
  }

  box.append(header, lista);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

export function handleProjectRemoved(projectId) {
  if (_detailProjectId === projectId) {
    _detailProjectId = null;
    if (_panelOpen) {
      renderMasterShell();
      requestProjects();
    }
  }
}

// Picker de asignación (CA-16) — fuente: getLoadedConversations() de sidebar.js, sin round-trip
// nuevo al bridge (§0.2). Se abre desde el botón "+ Agregar conversación" de la vista detalle.
function openAssignPicker(projectId) {
  const picker = document.createElement("div");
  picker.className = "modal-overlay";
  const box = document.createElement("div");
  box.className = "modal-box";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Elegí una conversación";
  box.appendChild(title);

  const loaded = getLoadedConversations();
  if (loaded.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "No hay conversaciones cargadas todavía.";
    box.appendChild(empty);
  }

  for (const conv of loaded) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "panel-item panel-item-pickable";
    row.textContent = conv.title;   // §10.1 — nunca innerHTML
    row.addEventListener("click", () => {
      assignConversationToProject(conv.conversation_id, projectId);
      picker.remove();
    });
    box.appendChild(row);
  }
  picker.appendChild(box);
  picker.addEventListener("click", (evt) => { if (evt.target === picker) picker.remove(); });
  document.getElementById("panel-modal-root").appendChild(picker);   // se apila sobre el panel
}
