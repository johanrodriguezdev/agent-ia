/**
 * ui/webview/frontend/js/sidebar_projects.js
 * REQ-051 — los proyectos, en la barra lateral, como en cualquier app de chat.
 *
 * Por debajo ya existían (REQ-016: crear proyectos, asignar chats); lo que faltaba era
 * verlos donde uno los busca. Acá viven:
 *   - la sección «Proyectos» (arriba de «Recientes»), con cada proyecto desplegable y sus
 *     chats debajo, más «Nuevo chat aquí» y el «+» para crear uno;
 *   - el menú «Mover a proyecto» de cada chat (en Recientes) y «Sacar del proyecto» (en un
 *     proyecto), que se cuelga de `sidebar.js` sin que ese módulo importe de este
 *     (`setConversationMenuBuilder`), para no cerrar un ciclo de imports.
 *
 * Un chat que está en un proyecto no se repite en Recientes: el bridge lista Recientes
 * con `sin_proyecto=True`. El panel «Proyectos» de la barra superior sigue existiendo
 * para lo demás que se le asigna a un proyecto (flujos y módulos).
 *
 * Nada acá usa `innerHTML` (§10.1 de REQ-015): todo se arma con `createElement`.
 */

import {
  requestProjects, createProject, requestProjectConversations, newConversationInProject,
  assignConversationToProject, unassignConversationFromProject, requestDeleteProject,
  exportConversation,
} from "./bridge_client.js";
import { icon } from "./icons.js";
import { buildConversationItem, getActiveConversationId, setConversationMenuBuilder,
         clearActiveConversation } from "./sidebar.js";

let _projects = [];                   // [{id, name, conversation_count}]
const _expanded = new Set();          // ids desplegados (se recuerdan entre repintados)
const _chatsPorProyecto = new Map();  // id -> [conversations]
let _menuAbierto = null;

const $ = (id) => document.getElementById(id);

export function initSidebarProjects() {
  $("project-add-btn").addEventListener("click", (evt) => {
    evt.stopPropagation();
    empezarAltaDeProyecto();
  });
  setConversationMenuBuilder(buildMoveButton);
  document.addEventListener("click", cerrarMenu);
  requestProjects();
}

// ---------------------------------------------------------------- lista de proyectos

export function renderSidebarProjects(projects) {
  _projects = projects || [];
  const list = $("project-list");
  list.replaceChildren();

  for (const p of _projects) {
    list.appendChild(buildProjectRow(p));
    if (_expanded.has(p.id)) {
      const chats = document.createElement("div");
      chats.className = "project-chats";
      chats.dataset.projectId = String(p.id);
      list.appendChild(chats);
      pintarChats(p.id, _chatsPorProyecto.get(p.id) || null);
      requestProjectConversations(p.id);   // refresco: el contenido pudo cambiar
    }
  }
}

function buildProjectRow(p) {
  const row = document.createElement("div");
  row.className = "project-row";
  row.dataset.projectId = String(p.id);
  row.setAttribute("role", "button");
  row.tabIndex = 0;

  const chevron = icon("chevron", "ic-sm project-chevron");
  if (_expanded.has(p.id)) chevron.classList.add("open");
  row.appendChild(chevron);

  const name = document.createElement("span");
  name.className = "project-name";
  name.textContent = p.name;
  row.appendChild(name);

  const count = document.createElement("span");
  count.className = "project-count";
  count.textContent = String(p.conversation_count || 0);
  row.appendChild(count);

  const nuevo = document.createElement("button");
  nuevo.type = "button";
  nuevo.className = "conv-icon-btn";
  nuevo.setAttribute("aria-label", "Nuevo chat en " + p.name);
  nuevo.title = "Nuevo chat aquí";
  nuevo.appendChild(icon("plus", "ic-sm"));
  nuevo.addEventListener("click", (evt) => {
    evt.stopPropagation();
    nuevoChatEn(p.id);
  });
  row.appendChild(nuevo);

  const borrar = document.createElement("button");
  borrar.type = "button";
  borrar.className = "conv-icon-btn conv-delete-btn";
  borrar.setAttribute("aria-label", "Eliminar proyecto " + p.name);
  borrar.title = "Eliminar proyecto (los chats vuelven a Recientes)";
  borrar.appendChild(icon("trash", "ic-sm"));
  borrar.addEventListener("click", (evt) => {
    evt.stopPropagation();
    requestDeleteProject(p.id);   // la confirmación la resuelve Python (§10.2)
  });
  row.appendChild(borrar);

  const toggle = () => {
    if (_expanded.has(p.id)) _expanded.delete(p.id);
    else _expanded.add(p.id);
    renderSidebarProjects(_projects);
  };
  row.addEventListener("click", toggle);
  row.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter" || evt.key === " ") { evt.preventDefault(); toggle(); }
  });
  return row;
}

function pintarChats(projectId, conversations) {
  const cont = document.querySelector(`.project-chats[data-project-id="${projectId}"]`);
  if (!cont) return;
  cont.replaceChildren();

  if (conversations === null) {
    const cargando = document.createElement("div");
    cargando.className = "project-empty";
    cargando.textContent = "Cargando…";
    cont.appendChild(cargando);
    return;
  }
  const activa = getActiveConversationId();
  for (const conv of conversations) {
    const item = buildConversationItem(conv, { projectId });
    item.classList.toggle("active", conv.conversation_id === activa);
    cont.appendChild(item);
  }
  const nuevo = document.createElement("button");
  nuevo.type = "button";
  nuevo.className = "project-new-chat";
  nuevo.appendChild(icon("plus", "ic-sm"));
  const texto = document.createElement("span");
  texto.textContent = conversations.length ? "Nuevo chat aquí" : "Empezar un chat aquí";
  nuevo.appendChild(texto);
  nuevo.addEventListener("click", () => nuevoChatEn(projectId));
  cont.appendChild(nuevo);
}

/** Llega de `project_conversations_loaded`: los chats de un proyecto desplegado. */
export function renderSidebarProjectConversations(conversations, projectId) {
  _chatsPorProyecto.set(projectId, conversations || []);
  if (_expanded.has(projectId)) pintarChats(projectId, conversations || []);
}

export function handleProjectRemovedInSidebar(projectId) {
  _expanded.delete(projectId);
  _chatsPorProyecto.delete(projectId);
  requestProjects();
}

function nuevoChatEn(projectId) {
  _expanded.add(projectId);
  newConversationInProject(projectId);
  clearActiveConversation();
}

// ---------------------------------------------------------------- alta inline del proyecto

function empezarAltaDeProyecto(alCrear = null) {
  const list = $("project-list");
  if (list.querySelector(".project-new-input")) return;

  const entrada = document.createElement("input");
  entrada.type = "text";
  entrada.className = "project-new-input";
  entrada.placeholder = "Nombre del proyecto";
  entrada.maxLength = 60;
  entrada.setAttribute("aria-label", "Nombre del proyecto nuevo");

  function terminar(guardar) {
    if (!entrada.isConnected) return;
    const nombre = entrada.value.trim();
    entrada.remove();
    if (guardar && nombre) {
      if (alCrear) alCrear(nombre);
      createProject(nombre);
    }
  }
  entrada.addEventListener("keydown", (evt) => {
    evt.stopPropagation();
    if (evt.key === "Enter") terminar(true);
    if (evt.key === "Escape") terminar(false);
  });
  entrada.addEventListener("blur", () => terminar(true));

  list.prepend(entrada);
  entrada.focus();
}

// ---------------------------------------------------------------- menú «Mover a proyecto»

function buildMoveButton(conv, contexto) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "conv-icon-btn";
  btn.setAttribute("aria-label", "Mover a un proyecto");
  btn.title = "Mover a un proyecto";
  btn.appendChild(icon("folder", "ic-sm"));
  btn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    abrirMenu(btn, conv, contexto);
  });
  return btn;
}

function abrirMenu(anchor, conv, contexto) {
  cerrarMenu();
  const menu = document.createElement("div");
  menu.className = "conv-menu";
  menu.setAttribute("role", "menu");

  const titulo = document.createElement("div");
  titulo.className = "conv-menu-title";
  titulo.textContent = "Mover a proyecto";
  menu.appendChild(titulo);

  const actual = contexto && contexto.projectId;
  for (const p of _projects) {
    if (p.id === actual) continue;
    menu.appendChild(itemDeMenu(p.name, () => {
      assignConversationToProject(conv.conversation_id, p.id);
      _expanded.add(p.id);
    }));
  }
  if (!_projects.filter((p) => p.id !== actual).length) {
    const vacio = document.createElement("div");
    vacio.className = "conv-menu-empty";
    vacio.textContent = "No hay otros proyectos.";
    menu.appendChild(vacio);
  }

  menu.appendChild(itemDeMenu("Nuevo proyecto…", () => {
    // El nombre se pide con la misma entrada inline del «+» (nada de diálogos nativos):
    // se crea y, cuando llegue la lista con el id nuevo, se mueve el chat ahí.
    empezarAltaDeProyecto((nombre) => {
      _moverAlCrear = { conversationId: conv.conversation_id, nombre };
    });
  }));

  if (actual) {
    menu.appendChild(itemDeMenu("Sacar del proyecto", () => {
      unassignConversationFromProject(conv.conversation_id);
    }, true));
  }

  // REQ-056 — la conversación como archivo .md. Va en este menú y no como un cuarto
  // icono en la fila: la fila ya tiene tres y este es el "menú del chat" de hecho.
  const separador = document.createElement("div");
  separador.className = "conv-menu-sep";
  menu.appendChild(separador);
  menu.appendChild(itemDeMenu("Exportar a Markdown…", () => {
    exportConversation(conv.conversation_id);
  }));

  anchor.closest(".conv-item").appendChild(menu);
  _menuAbierto = menu;
}

let _moverAlCrear = null;

/** Tras crear un proyecto desde el menú, la lista nueva trae su id: se mueve el chat. */
export function completarMovimientoPendiente(projects) {
  if (!_moverAlCrear) return;
  const destino = (projects || []).find((p) => p.name === _moverAlCrear.nombre);
  if (!destino) return;
  const { conversationId } = _moverAlCrear;
  _moverAlCrear = null;
  _expanded.add(destino.id);
  assignConversationToProject(conversationId, destino.id);
}

function itemDeMenu(texto, accion, peligroso = false) {
  const item = document.createElement("button");
  item.type = "button";
  item.className = "conv-menu-item" + (peligroso ? " conv-menu-item-peligroso" : "");
  item.setAttribute("role", "menuitem");
  item.textContent = texto;
  item.addEventListener("click", (evt) => {
    evt.stopPropagation();
    cerrarMenu();
    accion();
  });
  return item;
}

function cerrarMenu() {
  if (_menuAbierto) {
    _menuAbierto.remove();
    _menuAbierto = null;
  }
}
