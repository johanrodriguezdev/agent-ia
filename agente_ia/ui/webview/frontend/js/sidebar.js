// ui/webview/frontend/js/sidebar.js
// REQ-015/CA-06..CA-11 — sidebar de conversaciones.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, Hallazgo A de security-audit-015.md):
// el título de cada conversación (`conv.title`, derivado de los primeros 30 caracteres
// del primer mensaje del usuario — texto NO confiable) se inserta EXCLUSIVAMENTE vía
// `textContent` sobre un nodo dedicado, creado con `document.createElement`. Este archivo
// NUNCA usa `innerHTML`/`insertAdjacentHTML` — verificado además por un grep estructural
// en `tests/test_webview_safe_dom_insertion.py`.

import {
  newConversation, selectConversation, requestDeleteConversation, loadMoreConversations,
} from "./bridge_client.js";

// Debe coincidir con `ui/webview/bridge.py::_CONVERSATION_PAGE_SIZE` — usado solo para
// decidir si "Ver más" sigue teniendo sentido (arquitectura-015.md §10.2 nota de diseño
// en bridge.py, ver desarrollo-log-015.md).
const PAGE_SIZE = 30;

let _pendingAppend = false;
let _activeConversationId = null;
let _count = 0;
let _searchTerm = "";
let _loadedConversations = [];   // REQ-016/§0.2 — fuente del picker de projects_panel.js

function $(id) {
  return document.getElementById(id);
}

function relativeTime(isoString) {
  if (!isoString) return "";
  const then = new Date(isoString);
  if (Number.isNaN(then.getTime())) return "";
  const diffMin = Math.round((Date.now() - then.getTime()) / 60000);
  const rtf = new Intl.RelativeTimeFormat("es", { numeric: "auto" });
  if (Math.abs(diffMin) < 60) return rtf.format(-diffMin, "minute");
  const diffHour = Math.round(diffMin / 60);
  if (Math.abs(diffHour) < 24) return rtf.format(-diffHour, "hour");
  const diffDay = Math.round(diffHour / 24);
  return rtf.format(-diffDay, "day");
}

function buildConversationItem(conv) {
  const item = document.createElement("div");
  item.className = "conv-item";
  item.dataset.conversationId = conv.conversation_id;
  item.setAttribute("role", "listitem");

  const title = document.createElement("span");
  title.className = "conv-title";
  title.textContent = conv.title; // §10.1 — nunca innerHTML
  item.appendChild(title);

  const meta = document.createElement("span");
  meta.className = "conv-meta";
  meta.textContent = relativeTime(conv.last_activity);
  item.appendChild(meta);

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "conv-delete-btn";
  deleteBtn.setAttribute("aria-label", "Eliminar conversación");
  deleteBtn.textContent = "✕";
  deleteBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    // §10.2: la confirmación YELLOW ahora la resuelve `security_manager` del lado
    // Python — este click solo pide el borrado; si corresponde, el modal genérico
    // aparece vía el evento `confirmation_requested` (confirm_modal.js).
    requestDeleteConversation(conv.conversation_id);
  });
  item.appendChild(deleteBtn);

  item.addEventListener("click", () => {
    selectConversation(conv.conversation_id);
    setActiveConversationId(conv.conversation_id);
  });

  return item;
}

// REQ-016/CA-03: filtra client-side sobre `.conv-item` ya renderizados, por `textContent`
// de `.conv-title` — sin round-trip al bridge.
function applySearchFilter() {
  for (const item of document.querySelectorAll(".conv-item")) {
    const title = item.querySelector(".conv-title").textContent.toLowerCase();
    item.hidden = _searchTerm !== "" && !title.includes(_searchTerm);
  }
}

export function initSidebar() {
  $("sidebar-collapse-toggle").addEventListener("click", () => {
    $("sidebar").classList.toggle("collapsed");
  });

  $("new-conversation-btn").addEventListener("click", () => {
    newConversation();
  });

  $("load-more-btn").addEventListener("click", () => {
    _pendingAppend = true;
    loadMoreConversations(_count);
  });

  $("sidebar-search-toggle").addEventListener("click", () => {
    const row = $("sidebar-search-row");
    row.hidden = !row.hidden;
    $("sidebar-search-toggle").classList.toggle("active", !row.hidden);
    if (!row.hidden) $("sidebar-search-input").focus();
  });

  $("sidebar-search-input").addEventListener("input", (evt) => {
    _searchTerm = evt.target.value.trim().toLowerCase();
    applySearchFilter();
  });
}

export function renderConversationList(items) {
  const container = $("conversation-list");
  if (!_pendingAppend) {
    container.replaceChildren();
    _count = 0;
    _loadedConversations = [];
  }
  for (const conv of items) {
    container.appendChild(buildConversationItem(conv));
    _loadedConversations.push({ conversation_id: conv.conversation_id, title: conv.title });
    _count += 1;
  }
  $("load-more-btn").hidden = items.length < PAGE_SIZE;
  _pendingAppend = false;
  setActiveConversationId(_activeConversationId);
  applySearchFilter();   // REQ-016/CA-03
}

export function getLoadedConversations() {
  return [..._loadedConversations];   // copia — no expone el array mutable interno
}

export function setActiveConversationId(conversationId) {
  _activeConversationId = conversationId;
  for (const el of document.querySelectorAll(".conv-item")) {
    el.classList.toggle("active", el.dataset.conversationId === conversationId);
  }
}

export function clearActiveConversation() {
  setActiveConversationId(null);
}

export function removeConversationFromList(conversationId) {
  for (const node of document.querySelectorAll(".conv-item")) {
    if (node.dataset.conversationId === conversationId) {
      node.remove();
      _count = Math.max(0, _count - 1);
    }
  }
  if (_activeConversationId === conversationId) {
    _activeConversationId = null;
  }
}
