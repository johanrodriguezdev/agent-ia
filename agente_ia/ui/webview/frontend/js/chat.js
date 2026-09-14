// ui/webview/frontend/js/chat.js
// REQ-015/CA-12..CA-19 — feed de conversación.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §5.2, §10.1): este es el ÚNICO archivo del
// frontend que usa `innerHTML`, y únicamente para el campo `html` de `turns_loaded`/
// `message_appended` — ya sanitizado del lado Python por `render_markdown()` + `bleach`
// (`ui/webview/markdown_render.py`) antes de llegar acá. Ningún otro campo de este
// archivo (ni de ningún otro módulo JS) se inserta así — ver sidebar.js/composer.js/
// confirm_modal.js para los campos de texto NO confiable, que van por `textContent`.

import { icon } from "./icons.js";
import { runCommandInTerminal } from "./bridge_client.js";
import { mostrarAviso } from "./toasts.js";

const CLAMP_THRESHOLD = 500; // CA-18

// Un bloque de codigo de hasta 3 lineas es un comando; uno de cuarenta es un programa, y
// ofrecer "ejecutar" ahi seria ofrecer pegar un archivo entero en la consola.
const MAX_LINEAS_EJECUTABLE = 3;

// Burbuja viva: la respuesta que se esta escribiendo ahora mismo (`message_chunk`). Es
// texto plano; el mensaje definitivo llega por `message_appended` ya convertido a HTML y
// saneado del lado Python, y reemplaza a esta.
let _viva = null;

function $(id) {
  return document.getElementById(id);
}

function isEmpty() {
  return $("messages").children.length === 0;
}

function syncEmptyState() {
  const empty = isEmpty();
  $("empty-state").style.display = empty ? "flex" : "none";
  // El composer sube a una pieza centrada con el saludo cuando no hay conversación y
  // vuelve a fijarse abajo en cuanto llegan mensajes (ver chat.css, estado vacío).
  document.body.classList.toggle("chat-empty", empty);
}

function isNearBottom() {
  const area = $("chat-area");
  return area.scrollHeight - area.scrollTop - area.clientHeight <= 40; // CA-16
}

function scrollToBottom() {
  const area = $("chat-area");
  area.scrollTop = area.scrollHeight;
}

function buildMessageNode(item) {
  const wrapper = document.createElement("div");
  wrapper.className = `message msg-${item.role || "assistant"}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  // CA-13, §5.2: único campo insertado vía innerHTML — ya sanitizado server-side.
  bubble.innerHTML = item.html || "";
  wrapper.appendChild(bubble);

  if ((item.role || "assistant") === "assistant") {
    decorarBloquesDeCodigo(bubble);
    wrapper.appendChild(accionesDelMensaje(bubble));
  }

  if ((item.html || "").length > CLAMP_THRESHOLD) {
    bubble.classList.add("clamped");
    const expandBtn = document.createElement("button");
    expandBtn.type = "button";
    expandBtn.className = "bubble-expand-btn";
    expandBtn.textContent = "Ver más";
    expandBtn.addEventListener("click", () => {
      bubble.classList.remove("clamped");
      expandBtn.remove();
    });
    wrapper.appendChild(expandBtn);
  }

  return wrapper;
}

async function copiarAlPortapapeles(texto) {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch (e) {
    // El portapapeles del navegador puede estar cerrado segun la configuracion del motor.
    // El camino viejo (textarea + execCommand) es feo pero funciona en cualquier caso, y
    // es preferible a un boton de copiar que no copia.
    try {
      const area = document.createElement("textarea");
      area.value = texto;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    } catch (e2) {
      console.debug("[chat] no se pudo copiar:", e, e2);
      return false;
    }
  }
}

function botonDeAccion(nombreIcono, etiqueta, alHacerClick) {
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "msg-action";
  boton.title = etiqueta;
  boton.setAttribute("aria-label", etiqueta);
  boton.appendChild(icon(nombreIcono, "ic-sm"));
  const texto = document.createElement("span");
  texto.textContent = etiqueta;
  boton.appendChild(texto);
  boton.addEventListener("click", alHacerClick);
  return boton;
}

/** Copiar la respuesta entera. Antes habia que seleccionarla con el mouse sin pasarse. */
function accionesDelMensaje(bubble) {
  const fila = document.createElement("div");
  fila.className = "msg-actions";
  fila.appendChild(botonDeAccion("copiar", "Copiar", async () => {
    const ok = await copiarAlPortapapeles(bubble.innerText.trim());
    mostrarAviso(ok ? "ok" : "error", ok ? "Respuesta copiada." : "No pude copiar.");
  }));
  return fila;
}

/** Copiar y —si parece un comando— mandar a la terminal cada bloque de codigo.
 *
 *  Ejecutar pasa por el MISMO gate amarillo que usa el agente, con el comando a la vista:
 *  el codigo lo escribio el modelo, y que este en un bloque bonito no lo hace mas
 *  confiable. */
function decorarBloquesDeCodigo(bubble) {
  for (const bloque of bubble.querySelectorAll("pre")) {
    const contenedor = bloque.closest(".codehilite") || bloque;
    if (contenedor.querySelector(".code-actions")) continue;
    contenedor.classList.add("code-block");

    const codigo = bloque.innerText.replace(/\s+$/, "");
    if (!codigo) continue;

    const acciones = document.createElement("div");
    acciones.className = "code-actions";
    acciones.appendChild(botonDeAccion("copiar", "Copiar", async () => {
      const ok = await copiarAlPortapapeles(codigo);
      mostrarAviso(ok ? "ok" : "error", ok ? "Código copiado." : "No pude copiar.");
    }));

    if (codigo.split("\n").length <= MAX_LINEAS_EJECUTABLE) {
      acciones.appendChild(botonDeAccion("play", "Ejecutar", () => {
        runCommandInTerminal(codigo);
      }));
    }
    contenedor.appendChild(acciones);
  }
}

export function initChat() {
  syncEmptyState();
}

export function renderTurns(turns) {
  const container = $("messages");
  clearChunks();
  container.replaceChildren();

  // CA-17: inserción diferida en tandas de 50 vía requestAnimationFrame — evita el jank
  // de pintar todo el historial de una sola pasada.
  let index = 0;
  function insertBatch() {
    const end = Math.min(index + 50, turns.length);
    for (; index < end; index += 1) {
      container.appendChild(buildMessageNode(turns[index]));
    }
    if (index < turns.length) {
      requestAnimationFrame(insertBatch);
    } else {
      syncEmptyState();
      scrollToBottom();
    }
  }

  if (turns.length > 0) {
    requestAnimationFrame(insertBatch);
  } else {
    syncEmptyState();
  }
}

/** Pedazo de respuesta recien llegado: se ve como se escribe. */
export function appendChunk(texto) {
  if (!texto) return;
  const container = $("messages");
  const shouldStick = isNearBottom();

  if (_viva === null) {
    const wrapper = document.createElement("div");
    wrapper.className = "message msg-assistant msg-viva";
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    wrapper.appendChild(bubble);
    container.appendChild(wrapper);
    _viva = bubble;
    syncEmptyState();
  }

  // textContent y no innerHTML: esto es texto crudo del modelo, todavia sin sanear. El
  // Markdown se ve recien cuando llega el mensaje definitivo.
  _viva.textContent += texto;
  if (shouldStick) scrollToBottom();
}

/** Saca la burbuja viva. La respuesta definitiva ocupa su lugar (o nada, si se cancelo). */
export function clearChunks() {
  if (_viva === null) return;
  const wrapper = _viva.closest(".message");
  if (wrapper) wrapper.remove();
  _viva = null;
}

export function appendMessage(item) {
  const container = $("messages");
  const shouldStick = isNearBottom();
  // El mensaje definitivo reemplaza a lo que se estaba escribiendo: si no, quedaria la
  // respuesta dos veces, una en texto plano y otra con formato.
  clearChunks();
  container.appendChild(buildMessageNode(item));
  syncEmptyState();
  if (shouldStick) {
    scrollToBottom(); // CA-16: no interrumpe si el usuario se alejó del final
  }
}

export function clearMessages() {
  clearChunks();
  $("messages").replaceChildren();
  syncEmptyState();
}

export function setTyping(active) {
  $("typing-indicator").hidden = !active;
  if (!active) setProgress("");   // al terminar, no dejar colgado el ultimo paso
  if (active) scrollToBottom();
}

// Linea de estado: que esta haciendo el agente ahora mismo. Antes, entre la pregunta y la
// respuesta solo habia tres puntos, y diez segundos buscando en internet se veian igual
// que un cuelgue. Se usa textContent y no innerHTML a proposito: el texto lo componen
// modulos de Python con datos que vienen del usuario (su consulta, una URL), y aqui no
// tiene por que interpretarse como marcado.
export function setProgress(text) {
  const el = $("progress-text");
  if (!el) return;
  el.textContent = text || "";
  if (text) scrollToBottom();
}

export function updateGuiState(state) {
  document.body.dataset.guiState = state;
}
