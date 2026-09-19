// ui/webview/frontend/js/sidebar.js
// REQ-015/CA-06..CA-11 — sidebar de conversaciones.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, Hallazgo A de security-audit-015.md):
// el título de cada conversación (`conv.title`, derivado de los primeros 30 caracteres
// del primer mensaje del usuario — texto NO confiable) se inserta EXCLUSIVAMENTE vía
// `textContent` sobre un nodo dedicado, creado con `document.createElement`. Este archivo
// NUNCA usa `innerHTML`/`insertAdjacentHTML` — verificado además por un grep estructural
// en `tests/test_webview_safe_dom_insertion.py`. Lo mismo vale para los fragmentos de
// búsqueda, que son texto crudo de conversaciones viejas.

import {
  newConversation, selectConversation, requestDeleteConversation, loadMoreConversations,
  renameConversation, searchConversations,
} from "./bridge_client.js";
import { icon } from "./icons.js";

// Debe coincidir con `ui/webview/bridge.py::_CONVERSATION_PAGE_SIZE` — usado solo para
// decidir si "Ver más" sigue teniendo sentido (arquitectura-015.md §10.2 nota de diseño
// en bridge.py, ver desarrollo-log-015.md).
const PAGE_SIZE = 30;

// Filtrar lo que ya está en pantalla es instantáneo; buscar en toda la base es medio
// segundo. Se espera a que el usuario deje de escribir antes de ir al historial.
const ESPERA_BUSQUEDA_MS = 350;
const MIN_CARACTERES_BUSQUEDA = 2;

let _pendingAppend = false;
let _activeConversationId = null;
let _count = 0;
let _searchTerm = "";
let _loadedConversations = [];   // REQ-016/§0.2 — fuente del picker de projects_panel.js
let _temporizadorBusqueda = null;
let _enResultados = false;
// REQ-051 — quien construye el botón «Mover a proyecto» de cada chat. Lo registra
// `sidebar_projects.js` al arrancar; así este módulo no importa de aquel (sin ciclo).
let _menuBuilder = null;

export function setConversationMenuBuilder(fn) {
  _menuBuilder = fn;
}

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

/** En qué franja cae una conversación. Una lista plana de treinta títulos con "hace 2
 *  días" al costado obliga a leerlos todos para ubicarse; con franjas se salta directo. */
function franja(isoString) {
  const cuando = new Date(isoString || "");
  if (Number.isNaN(cuando.getTime())) return "Antes";

  const hoy = new Date();
  const inicioDeHoy = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate());
  const dias = Math.floor((inicioDeHoy - cuando) / 86400000);

  if (dias <= 0) return "Hoy";
  if (dias === 1) return "Ayer";
  if (dias < 7) return "Esta semana";
  if (dias < 30) return "Este mes";
  return "Antes";
}

function encabezadoDeFranja(texto) {
  const fila = document.createElement("div");
  fila.className = "conv-group";
  fila.textContent = texto;
  return fila;
}

// --------------------------------------------------------------------------- renombrar

function empezarRenombrado(item, conv) {
  if (item.querySelector(".conv-rename-input")) return;
  const titulo = item.querySelector(".conv-title");
  const entrada = document.createElement("input");
  entrada.type = "text";
  entrada.className = "conv-rename-input";
  entrada.value = titulo.textContent;
  entrada.setAttribute("aria-label", "Nuevo nombre de la conversación");

  function terminar(guardar) {
    if (!entrada.isConnected) return;
    const nuevo = entrada.value;
    entrada.replaceWith(titulo);
    if (guardar) renameConversation(conv.conversation_id, nuevo);
  }

  entrada.addEventListener("keydown", (evt) => {
    evt.stopPropagation();
    if (evt.key === "Enter") terminar(true);
    if (evt.key === "Escape") terminar(false);
  });
  entrada.addEventListener("blur", () => terminar(true));
  entrada.addEventListener("click", (evt) => evt.stopPropagation());

  titulo.replaceWith(entrada);
  entrada.focus();
  entrada.select();
}

export function buildConversationItem(conv, contexto = null) {
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

  // Renombrar: el título derivado del primer mensaje casi nunca describe de qué terminó
  // tratando la charla.
  const renameBtn = document.createElement("button");
  renameBtn.type = "button";
  renameBtn.className = "conv-icon-btn";
  renameBtn.setAttribute("aria-label", "Renombrar conversación");
  renameBtn.title = "Renombrar";
  renameBtn.appendChild(icon("lapiz", "ic-sm"));
  renameBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    empezarRenombrado(item, conv);
  });
  item.appendChild(renameBtn);

  // REQ-051 — «Mover a proyecto» / «Sacar del proyecto».
  if (_menuBuilder) item.appendChild(_menuBuilder(conv, contexto));

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "conv-icon-btn conv-delete-btn";
  deleteBtn.setAttribute("aria-label", "Eliminar conversación");
  deleteBtn.title = "Eliminar conversación";
  deleteBtn.appendChild(icon("trash", "ic-sm"));
  deleteBtn.addEventListener("click", (evt) => {
    evt.stopPropagation();
    // §10.2: la confirmación YELLOW la resuelve `security_manager` del lado Python — este
    // click solo pide el borrado; si corresponde, el modal genérico aparece vía el evento
    // `confirmation_requested` (confirm_modal.js).
    requestDeleteConversation(conv.conversation_id);
  });
  item.appendChild(deleteBtn);

  item.addEventListener("click", () => {
    selectConversation(conv.conversation_id);
    setActiveConversationId(conv.conversation_id);
  });
  item.addEventListener("dblclick", () => empezarRenombrado(item, conv));

  return item;
}

// REQ-016/CA-03: filtra client-side sobre `.conv-item` ya renderizados, por `textContent`
// de `.conv-title` — sin round-trip al bridge. Es el filtro instantáneo; la búsqueda en
// el historial completo va aparte (`searchConversations`).
function applySearchFilter() {
  if (_enResultados) return;
  for (const item of document.querySelectorAll(".conv-item")) {
    const titulo = item.querySelector(".conv-title");
    const texto = titulo ? titulo.textContent.toLowerCase() : "";
    item.hidden = _searchTerm !== "" && !texto.includes(_searchTerm);
  }
  // Un encabezado de franja sin ítems visibles debajo es ruido.
  for (const grupo of document.querySelectorAll(".conv-group")) {
    let visible = false;
    let siguiente = grupo.nextElementSibling;
    while (siguiente && !siguiente.classList.contains("conv-group")) {
      if (!siguiente.hidden) { visible = true; break; }
      siguiente = siguiente.nextElementSibling;
    }
    grupo.hidden = !visible;
  }
}

function setCollapsed(collapsed) {
  const btn = $("sidebar-collapse-toggle");
  $("sidebar").classList.toggle("collapsed", collapsed);
  const label = collapsed ? "Expandir panel lateral" : "Colapsar panel lateral";
  btn.setAttribute("aria-label", label);
  btn.title = label;
}

export function initSidebar() {
  $("sidebar-collapse-toggle").addEventListener("click", () => {
    setCollapsed(!$("sidebar").classList.contains("collapsed"));
  });

  $("new-conversation-btn").addEventListener("click", () => {
    newConversation();
  });

  $("load-more-btn").addEventListener("click", () => {
    _pendingAppend = true;
    loadMoreConversations(_count);
  });

  // El buscador vive en la barra superior y está siempre visible. Hace dos cosas a la
  // vez: filtra al instante lo que ya está en pantalla, y —si el texto da para algo—
  // busca DENTRO de todas las conversaciones guardadas, que es donde está lo que uno de
  // verdad no encuentra.
  const search = $("conv-search-input");

  search.addEventListener("input", (evt) => {
    _searchTerm = evt.target.value.trim().toLowerCase();
    applySearchFilter();

    clearTimeout(_temporizadorBusqueda);
    const consulta = evt.target.value.trim();
    if (consulta.length < MIN_CARACTERES_BUSQUEDA) {
      if (_enResultados) volverAlListado();
      return;
    }
    _temporizadorBusqueda = setTimeout(() => searchConversations(consulta), ESPERA_BUSQUEDA_MS);
  });

  // Buscar con el sidebar colapsado no tendría dónde mostrar el resultado: se expande.
  search.addEventListener("focus", () => setCollapsed(false));

  document.addEventListener("keydown", (evt) => {
    if ((evt.ctrlKey || evt.metaKey) && (evt.key === "k" || evt.key === "K")) {
      evt.preventDefault();
      search.focus();
      search.select();
      return;
    }
    // Escape limpia el filtro en vez de dejar la lista recortada sin que se vea por qué.
    if (evt.key === "Escape" && document.activeElement === search && search.value !== "") {
      search.value = "";
      _searchTerm = "";
      volverAlListado();
      applySearchFilter();
    }
  });
}

export function renderConversationList(items) {
  const container = $("conversation-list");
  if (!_pendingAppend) {
    container.replaceChildren();
    _count = 0;
    _loadedConversations = [];
  }
  _enResultados = false;

  let franjaActual = _pendingAppend && container.lastElementChild
    ? container.dataset.ultimaFranja || ""
    : "";

  for (const conv of items) {
    const suya = franja(conv.last_activity);
    if (suya !== franjaActual) {
      container.appendChild(encabezadoDeFranja(suya));
      franjaActual = suya;
    }
    container.appendChild(buildConversationItem(conv));
    _loadedConversations.push({ conversation_id: conv.conversation_id, title: conv.title });
    _count += 1;
  }
  container.dataset.ultimaFranja = franjaActual;

  $("load-more-btn").hidden = items.length < PAGE_SIZE;
  _pendingAppend = false;
  setActiveConversationId(_activeConversationId);
  applySearchFilter();   // REQ-016/CA-03
}

/** Resultados de buscar en TODO el historial, con el fragmento donde coincidió. */
export function renderSearchResults(resultados) {
  const consulta = $("conv-search-input").value.trim();
  if (consulta.length < MIN_CARACTERES_BUSQUEDA) return;

  const container = $("conversation-list");
  container.replaceChildren();
  _enResultados = true;
  $("load-more-btn").hidden = true;

  container.appendChild(encabezadoDeFranja(
    resultados.length ? `${resultados.length} en el historial` : "Sin resultados",
  ));

  for (const resultado of resultados) {
    const item = document.createElement("div");
    item.className = "conv-item conv-result";
    item.dataset.conversationId = resultado.conversation_id;
    item.setAttribute("role", "listitem");

    const cuerpo = document.createElement("div");
    cuerpo.className = "conv-result-body";

    const titulo = document.createElement("span");
    titulo.className = "conv-title";
    titulo.textContent = resultado.title;          // §10.1
    cuerpo.appendChild(titulo);

    const fragmento = document.createElement("span");
    fragmento.className = "conv-snippet";
    fragmento.textContent = resultado.snippet;     // §10.1 — texto crudo de la charla
    cuerpo.appendChild(fragmento);

    item.appendChild(cuerpo);
    item.addEventListener("click", () => {
      selectConversation(resultado.conversation_id);
      setActiveConversationId(resultado.conversation_id);
    });
    container.appendChild(item);
  }
}

function volverAlListado() {
  if (!_enResultados) return;
  _enResultados = false;
  // El listado normal lo repinta Python; pedirlo de nuevo es una sola consulta.
  loadMoreConversations(0);
  _pendingAppend = false;
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

export function getActiveConversationId() {
  return _activeConversationId;
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
