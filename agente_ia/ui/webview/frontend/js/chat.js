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
import { runCommandInTerminal, regenerateLast, editLast } from "./bridge_client.js";
import { mostrarAviso } from "./toasts.js";
import { abrirVisor } from "./visor_imagen.js";
import { crearMarca } from "./marca.js";

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

// REQ-060 — «Ir al final». Cuando el usuario sube a releer algo y mientras tanto llega
// una respuesta, el chat no lo arrastra (CA-16) pero tampoco le decía que había algo
// nuevo abajo. La pastilla aparece al alejarse del final; si llega contenido mientras
// está lejos, cambia a «Nuevos mensajes».
const LEJOS_DEL_FINAL_PX = 240;

function actualizarIrAlFinal() {
  const boton = $("ir-al-final");
  if (!boton) return;
  const area = $("chat-area");
  const lejos = area.scrollHeight - area.scrollTop - area.clientHeight > LEJOS_DEL_FINAL_PX;
  if (!lejos) {
    boton.hidden = true;
    boton.classList.remove("con-nuevos");
    $("ir-al-final-texto").textContent = "Ir al final";
    return;
  }
  boton.hidden = false;
}

function avisarNuevosAbajo() {
  const boton = $("ir-al-final");
  if (!boton || boton.hidden) return;
  boton.classList.add("con-nuevos");
  $("ir-al-final-texto").textContent = "Nuevos mensajes";
}

/** Hora del mensaje para la fila de acciones: «01:15» si es de hoy, «19 sept, 01:15» si
 *  no. Se muestra con las acciones (al pasar el mouse): la fecha exacta importa poco
 *  mientras se lee y mucho cuando se busca. */
function horaDelMensaje(timestamp) {
  if (!timestamp) return "";
  const fecha = new Date(timestamp);
  if (Number.isNaN(fecha.getTime())) return "";
  // Siempre 24 h («14:05»), sea cual sea la configuración regional del equipo.
  const hora = fecha.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const hoy = new Date();
  const mismoDia = fecha.getFullYear() === hoy.getFullYear() && fecha.getMonth() === hoy.getMonth()
                && fecha.getDate() === hoy.getDate();
  if (mismoDia) return hora;
  const dia = fecha.toLocaleDateString([], { day: "numeric", month: "short" });
  return `${dia}, ${hora}`;
}

function etiquetaDeHora(timestamp) {
  const hora = horaDelMensaje(timestamp);
  if (!hora) return null;
  const span = document.createElement("span");
  span.className = "msg-hora";
  span.textContent = hora;
  return span;
}

function buildMessageNode(item) {
  const wrapper = document.createElement("div");
  wrapper.className = `message msg-${item.role || "assistant"}`;

  // REQ-053 — qué hizo el agente para responder (las herramientas que usó), plegado
  // encima de la respuesta. Llega con el turno en vivo y, desde REQ-059, también con el
  // historial: se guardan junto a la respuesta.
  if ((item.role || "assistant") === "assistant" && Array.isArray(item.pasos) && item.pasos.length) {
    wrapper.appendChild(buildPasos(item.pasos));
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  // REQ-054 — el adjunto del mensaje del usuario: la miniatura de la imagen o un chip con
  // el nombre del archivo. Python ya sacó el marcador «[Imagen adjunta: …]» del `html`.
  if (item.adjunto && typeof item.adjunto === "object") {
    bubble.appendChild(buildAdjunto(item.adjunto));
  }
  // CA-13, §5.2: único campo insertado vía innerHTML — ya sanitizado server-side.
  if (item.html) {
    const cuerpo = document.createElement("div");
    cuerpo.className = "bubble-texto";
    cuerpo.innerHTML = item.html;
    bubble.appendChild(cuerpo);
  }
  wrapper.appendChild(bubble);

  if ((item.role || "assistant") === "assistant") {
    decorarBloquesDeCodigo(bubble);
    const acciones = accionesDelMensaje(bubble);
    const hora = etiquetaDeHora(item.timestamp);
    if (hora) acciones.appendChild(hora);
    wrapper.appendChild(acciones);
  } else if ((item.role || "assistant") === "user") {
    const acciones = accionesDelUsuario(bubble);
    const hora = etiquetaDeHora(item.timestamp);
    if (hora) acciones.insertBefore(hora, acciones.firstChild);
    wrapper.appendChild(acciones);
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

/** REQ-054 — lo que el usuario adjuntó a su mensaje.
 *
 *  Con imagen: la miniatura (`data:` URL que armó `core/imagenes.py`), que se abre a tamaño
 *  completo al hacer click. Sin imagen (un PDF, un .py): un chip con el clip y el nombre.
 *  Todo por propiedades y textContent; el nombre del archivo lo eligió el usuario, no es
 *  marcado (§10.1). */
function buildAdjunto(adjunto) {
  const nombre = String(adjunto.nombre || "");
  const miniatura = String(adjunto.miniatura || "");
  const ruta = String(adjunto.ruta || "");

  if (miniatura.startsWith("data:image/")) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "bubble-imagen";
    boton.title = nombre ? `${nombre} — ver a tamaño completo` : "Ver a tamaño completo";
    boton.setAttribute("aria-label", boton.title);
    const img = document.createElement("img");
    img.src = miniatura;
    img.alt = nombre;
    img.loading = "lazy";
    boton.appendChild(img);
    boton.addEventListener("click", () => abrirVisor(miniatura, nombre, ruta));
    return boton;
  }

  const chip = document.createElement("span");
  chip.className = "bubble-adjunto";
  chip.appendChild(icon("paperclip", "ic-sm"));
  const texto = document.createElement("span");
  texto.textContent = nombre || "archivo adjunto";
  chip.appendChild(texto);
  return chip;
}

/** Los pasos del turno: «Buscando en internet: clima Bogotá», «Leyendo la página: …».
 *  Cada línea la compuso Python con datos del usuario (su consulta, una URL): va por
 *  textContent, nunca innerHTML (§10.1). */
function buildPasos(pasos) {
  const detalles = document.createElement("details");
  detalles.className = "msg-pasos";

  const resumen = document.createElement("summary");
  resumen.className = "msg-pasos-resumen";
  resumen.appendChild(icon("chevron", "ic-sm msg-pasos-chevron"));
  const texto = document.createElement("span");
  texto.textContent = pasos.length === 1 ? "1 paso" : `${pasos.length} pasos`;
  resumen.appendChild(texto);
  const vistazo = document.createElement("span");
  vistazo.className = "msg-pasos-vistazo";
  vistazo.textContent = pasos.map((p) => p.split(":")[0]).slice(0, 3).join(" · ")
                      + (pasos.length > 3 ? " · …" : "");
  resumen.appendChild(vistazo);
  detalles.appendChild(resumen);

  const lista = document.createElement("ol");
  lista.className = "msg-pasos-lista";
  for (const paso of pasos) {
    const li = document.createElement("li");
    li.textContent = paso;
    lista.appendChild(li);
  }
  detalles.appendChild(lista);
  return detalles;
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

/** Copiar la respuesta entera. Antes habia que seleccionarla con el mouse sin pasarse.
 *  «Regenerar» (REQ-055) existe en todas las respuestas pero solo se ve en la ultima
 *  (`marcarUltimos()` + chat.css): regenerar una del medio dejaria la conversacion
 *  contando otra historia a partir de ahi. */
function accionesDelMensaje(bubble) {
  const fila = document.createElement("div");
  fila.className = "msg-actions";
  fila.appendChild(botonDeAccion("copiar", "Copiar", async () => {
    const ok = await copiarAlPortapapeles(bubble.innerText.trim());
    mostrarAviso(ok ? "ok" : "error", ok ? "Respuesta copiada." : "No pude copiar.");
  }));
  const regenerar = botonDeAccion("refresh", "Regenerar", () => regenerateLast());
  regenerar.classList.add("msg-action-ultimo");
  fila.appendChild(regenerar);
  return fila;
}

/** Acciones del mensaje del usuario (REQ-055): copiar y, solo en el ultimo, «Editar»,
 *  que lo devuelve al cuadro para corregirlo y mandarlo de nuevo. */
function accionesDelUsuario(bubble) {
  const fila = document.createElement("div");
  fila.className = "msg-actions msg-actions-usuario";
  fila.appendChild(botonDeAccion("copiar", "Copiar", async () => {
    const texto = bubble.querySelector(".bubble-texto");
    const ok = await copiarAlPortapapeles((texto ? texto.innerText : bubble.innerText).trim());
    mostrarAviso(ok ? "ok" : "error", ok ? "Mensaje copiado." : "No pude copiar.");
  }));
  const editar = botonDeAccion("lapiz", "Editar", () => editLast());
  editar.classList.add("msg-action-ultimo");
  fila.appendChild(editar);
  return fila;
}

/** Marca el ultimo mensaje del usuario y la ultima respuesta con `es-ultimo`: son los
 *  unicos donde «Editar» y «Regenerar» tienen sentido. Se recalcula cada vez que la lista
 *  cambia. La respuesta solo cuenta si es el ultimo mensaje de todos (si el usuario ya
 *  mando otra pregunta, esa respuesta ya no es la ultima palabra). */
function marcarUltimos() {
  const mensajes = Array.from($("messages").querySelectorAll(".message"));
  for (const m of mensajes) m.classList.remove("es-ultimo");
  const ultimo = mensajes[mensajes.length - 1];
  if (!ultimo) return;
  if (ultimo.classList.contains("msg-assistant")) {
    ultimo.classList.add("es-ultimo");
    // Su pregunta: el ultimo mensaje del usuario antes de esa respuesta.
    for (let i = mensajes.length - 2; i >= 0; i--) {
      if (mensajes[i].classList.contains("msg-user")) {
        mensajes[i].classList.add("es-ultimo");
        break;
      }
    }
  }
}

/** REQ-055 — el ultimo intercambio salio de la conversacion guardada: se quitan sus dos
 *  burbujas (la respuesta y la pregunta que la provoco). */
export function removeLastTurn() {
  const mensajes = Array.from($("messages").querySelectorAll(".message"));
  const ultimo = mensajes[mensajes.length - 1];
  if (ultimo && ultimo.classList.contains("msg-assistant")) {
    ultimo.remove();
    for (let i = mensajes.length - 2; i >= 0; i--) {
      if (mensajes[i].classList.contains("msg-user")) {
        mensajes[i].remove();
        break;
      }
    }
  }
  marcarUltimos();
  syncEmptyState();
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
  // REQ-060 — la pastilla «Ir al final» sigue al scroll del chat.
  const area = $("chat-area");
  const boton = $("ir-al-final");
  if (area && boton) {
    area.addEventListener("scroll", actualizarIrAlFinal, { passive: true });
    boton.addEventListener("click", () => {
      area.scrollTo({ top: area.scrollHeight, behavior: "smooth" });
      boton.hidden = true;
      boton.classList.remove("con-nuevos");
      $("ir-al-final-texto").textContent = "Ir al final";
    });
  }
  // REQ-057 — mientras el agente piensa, la marca (los anillos de REQ-052) gira más
  // rápido que en la barra: es el mismo pulso de "vivo", acelerado porque está
  // trabajando. Reemplaza a los tres puntos genéricos.
  const sitio = $("typing-marca");
  if (sitio && !sitio.firstChild) {
    sitio.appendChild(crearMarca({ tamano: 22, trazo: 9, nodo: 12, animada: true, clase: "marca-pensando" }));
  }
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
      marcarUltimos();
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
  else avisarNuevosAbajo();
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
  marcarUltimos();
  syncEmptyState();
  if (shouldStick) {
    scrollToBottom(); // CA-16: no interrumpe si el usuario se alejó del final
  } else {
    avisarNuevosAbajo();
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
