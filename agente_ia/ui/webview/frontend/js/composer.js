// ui/webview/frontend/js/composer.js
// REQ-015/CA-20..CA-25, CA-39, CA-40 — barra de entrada, chips y toggle de voz.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, Hallazgo A de security-audit-015.md):
// el nombre del archivo soltado (`file_attached.name`, viene de
// `QDropEvent.mimeData().urls()` — puede no ser texto que el propio usuario escribió, el
// caso más peligroso de los tres señalado por `orion-security`) se inserta EXCLUSIVAMENTE
// vía `textContent`. Este archivo NUNCA usa `innerHTML`/`insertAdjacentHTML` — verificado
// además por un grep estructural en `tests/test_webview_safe_dom_insertion.py`.

import {
  sendMessage, runChipAction, toggleWakeWord,
  openAttachDialog, clearAttachment, stopResolution, requestModels, setModel, setActiveMode,
  pasteFromClipboard,
} from "./bridge_client.js";
import { icon } from "./icons.js";

const MAX_VISIBLE_ROWS = 5;
const LINE_HEIGHT_PX = 20;

// REQ-026 — id del icono del sprite por cada modo. Los 4 ids (`codigo`, `investigacion`,
// `flujos`, `tareas`) son los que define `core/composer_modes.py`; reutilizan símbolos
// que ya existían en `index.html`, ninguno nuevo (ui-design-026.md).
const _MODE_ICONS = {
  codigo: "terminal",
  investigacion: "search",
  flujos: "flows",
  tareas: "tasks",
};

let _sendEnabled = true;
// Estado del modo activo: vive SOLO acá (fuente de verdad, arquitectura-026.md) — el
// espejo de `Bridge._modo_activo` es efímero y nunca decide nada, solo refleja esto.
let _activeModeId = null;

function $(id) {
  return document.getElementById(id);
}

function autoGrow(textarea) {
  textarea.style.height = "auto";
  const maxHeight = LINE_HEIGHT_PX * MAX_VISIBLE_ROWS;
  textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
}

function doSend() {
  if (!_sendEnabled) return;
  const input = $("composer-input");
  const text = input.value.trim();
  if (!text) return;
  sendMessage(text, _activeModeId || "");
  input.value = "";
  autoGrow(input);
}

export function initComposer() {
  const input = $("composer-input");

  input.addEventListener("input", () => autoGrow(input));

  input.addEventListener("keydown", (evt) => {
    // CA-21: Enter envía, Shift+Enter agrega un salto de línea (comportamiento nativo
    // del textarea, no se intercepta).
    if (evt.key === "Enter" && !evt.shiftKey) {
      evt.preventDefault();
      doSend();
    }
  });

  // REQ-054 — Ctrl+V con una captura (o un archivo copiado del Explorador). La pagina no
  // puede leer la ruta ni conviene mandarle los bytes a Python por el canal: solo se avisa
  // y el bridge lee el portapapeles del sistema. Si ademas hay texto, gana el texto: pegar
  // un parrafo copiado de una web con su imagen tiene que seguir pegando el parrafo.
  input.addEventListener("paste", (evt) => {
    const datos = evt.clipboardData;
    if (!datos) return;
    const hayArchivo = Array.from(datos.items || []).some((item) => item.kind === "file");
    const hayTexto = (datos.getData("text/plain") || "").trim() !== "";
    if (hayArchivo && !hayTexto) {
      evt.preventDefault();
      pasteFromClipboard();
    }
  });

  $("send-btn").addEventListener("click", doSend);

  $("wake-toggle-btn").addEventListener("click", () => {
    const btn = $("wake-toggle-btn");
    const turningOn = btn.dataset.wakeState === "INACTIVE";
    toggleWakeWord(turningOn);
  });

  $("attachment-chip-remove").addEventListener("click", () => {
    $("attachment-chip").hidden = true;
    showAttachmentPreview("");
    // Y del lado de Python tambien: si no, el archivo seguiria viajando con el proximo
    // mensaje aunque el chip ya no este en pantalla.
    clearAttachment();
  });

  // El clip abre el diálogo nativo de archivos. Antes era solo un cartel que decía
  // "arrastrá el archivo": un clip que no abre nada es un botón roto a los ojos de
  // cualquiera. El drag&drop sobre la ventana sigue funcionando igual.
  $("attach-btn").title = "Adjuntar un archivo (o arrastralo a la ventana)";
  $("attach-btn").addEventListener("click", openAttachDialog);

  // Detener: aparece en lugar de enviar mientras el agente responde.
  $("stop-btn").addEventListener("click", () => stopResolution());

  $("model-btn").addEventListener("click", (evt) => {
    evt.stopPropagation();
    alternarMenuDeModelos();
  });
}

export function setComposerEnabled(enabled) {
  // CA-24: guarda client-side (paridad UX) — el guard real, server-side y estricto,
  // vive en `Bridge.send_message()` (`_resolution_in_flight`), porque el bridge es
  // invocable desde JS sin pasar por el estado `disabled` del DOM.
  _sendEnabled = enabled;
  $("composer-input").disabled = !enabled;
  // Mientras el agente responde, el botón de enviar se convierte en uno de detener: es el
  // mismo lugar de la pantalla, y es el único momento en que hace falta cada uno.
  $("send-btn").hidden = !enabled;
  $("stop-btn").hidden = enabled;
}

export function setWakeState(state) {
  const btn = $("wake-toggle-btn");
  btn.dataset.wakeState = state;
  const labels = {
    INACTIVE: "Modo manos libres: inactivo",
    LISTENING_WAKE: "Modo manos libres: escuchando wake word",
    AWAKE: "Modo manos libres: despierto",
    // REQ-028: perdió el micrófono y está reintentando solo. No puede caer en el
    // `|| labels.INACTIVE` de abajo: el botón diría "inactivo" mientras el manos libres
    // sigue vivo, que es justo el aviso silencioso que este REQ vino a arreglar.
    RECONNECTING: "Modo manos libres: reconectando el micrófono",
  };
  const label = labels[state] || labels.INACTIVE;
  btn.title = label;
  btn.setAttribute("aria-label", label);
}

export function showAttachment(path, name, accepted, reason) {
  const chip = $("attachment-chip");
  const nameEl = $("attachment-chip-name");
  // §10.1 — nunca innerHTML: `name` puede no ser texto del propio usuario.
  nameEl.textContent = accepted ? name : `Rechazado: ${name} (${reason})`;
  chip.classList.toggle("rechazado", !accepted);
  chip.hidden = false;
}

/** REQ-054 — la miniatura del adjunto en el chip (un `data:` URL que armo Python), o
 *  nada si no es una imagen. Va por la propiedad `src`, nunca por innerHTML. */
export function showAttachmentPreview(dataUrl) {
  const img = $("attachment-chip-thumb");
  if (!img) return;
  if (dataUrl && dataUrl.startsWith("data:image/")) {
    img.src = dataUrl;
    img.hidden = false;
  } else {
    img.removeAttribute("src");
    img.hidden = true;
  }
}

// --------------------------------------------------------------------------- modos (REQ-026)

function _applyActiveModeVisuals() {
  const row = $("actions-row");
  if (!row) return;
  for (const btn of row.children) {
    // REQ-026 addendum 1: `#actions-row` mezcla los 4 botones de modo con "Recuérdame
    // algo" (mismo componente `.mode-btn`, ver `renderQuickActions()`). Solo los primeros
    // llevan `dataset.modeId` — "Recuérdame algo" no participa del toggle, no lleva
    // `aria-pressed` y nunca debe recibir `.mode-btn--active` (ui-design-026-addendum-1.md
    // §2, tabla de diferencias).
    if (!btn.dataset.modeId) continue;
    const active = btn.dataset.modeId === _activeModeId;
    btn.classList.toggle("mode-btn--active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");
    // El check se reserva con `visibility` (no se agrega/saca del DOM) para no mover el
    // resto de los botones al togglear — ui-design-026.md, estado "Activo".
    const check = btn.querySelector(".mode-btn-check");
    if (check) check.style.visibility = active ? "visible" : "hidden";
  }
}

function toggleMode(modoId) {
  // Un modo activo se desactiva clickeándolo de nuevo (toggle); clickear otro lo
  // reemplaza — nunca hay dos modos activos a la vez (SPEC-026).
  _activeModeId = _activeModeId === modoId ? null : modoId;
  _applyActiveModeVisuals();
  // `.mode-btn` nunca se deshabilita (ni siquiera con una respuesta en curso, per
  // ui-design-026.md "Estados") — togglear siempre está permitido, y el bridge se entera
  // igual para que el selector de modelo refleje "Fijado: ..." si corresponde.
  setActiveMode(_activeModeId || "");
}

export function renderModes(modes) {
  // REQ-026 addendum 1: `#actions-row` reemplaza a `#modes-row`/`#quick-actions-row` (dos
  // filas separadas) — ahora los 4 modos y "Recuérdame algo" comparten una única fila sin
  // salto de línea (SPEC-026-addendum-1.md, "Layout"). Esta función limpia la fila entera
  // y la deja con solo los 4 modos; `renderQuickActions()` (llamada siempre después, ver
  // `app.js::onChipsLoaded`) AGREGA "Recuérdame algo" al final sin volver a limpiar — el
  // orden de las dos llamadas importa.
  const row = $("actions-row");
  row.replaceChildren();
  for (const modo of modes) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mode-btn";
    btn.dataset.modeId = modo.id;
    btn.setAttribute("aria-pressed", "false");
    btn.title = modo.label;

    const iconName = _MODE_ICONS[modo.id];
    if (iconName) btn.appendChild(icon(iconName));

    const label = document.createElement("span");
    label.className = "mode-btn-label";
    label.textContent = modo.label;
    btn.appendChild(label);

    // Reservado desde el primer render — nunca se agrega/quita del DOM (ver
    // `_applyActiveModeVisuals`).
    const check = icon("check", "mode-btn-check");
    check.style.visibility = "hidden";
    btn.appendChild(check);

    btn.addEventListener("click", () => toggleMode(modo.id));
    row.appendChild(btn);
  }
  _applyActiveModeVisuals();
}

// REQ-026: al cambiar de conversación (nueva, cargada del historial, o limpiada) el modo
// activo no debe sobrevivir — es estado del turno que se está por escribir, no de la
// conversación que se acaba de abrir.
export function resetActiveMode() {
  if (_activeModeId === null) return;
  _activeModeId = null;
  _applyActiveModeVisuals();
  setActiveMode("");
}

// --------------------------------------------------------------------------- accesos rápidos

// REQ-026 addendum 1: "Recuérdame algo" dejó de ser un `.chip` en píldora aparte — ahora
// comparte el componente `.mode-btn` con los 4 modos (mismo tamaño/forma/ícono), pero SIN
// `aria-pressed`, SIN `.mode-btn--active` y SIN el nodo de check reservado: no es un modo,
// nunca tiene estado activo, solo prellena el input al clickear (ui-design-026-addendum-1.md
// §2). Se agrega al final de `#actions-row` — nunca limpia la fila, `renderModes()` ya lo
// hizo (ver su comentario).
export function renderQuickActions(items) {
  const row = $("actions-row");
  for (const chip of items) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mode-btn";
    btn.title = chip.label;

    if (chip.icon) btn.appendChild(icon(chip.icon));

    const label = document.createElement("span");
    label.className = "mode-btn-label";
    label.textContent = chip.label;
    btn.appendChild(label);

    btn.addEventListener("click", () => {
      if (chip.kind === "template") {
        const input = $("composer-input");
        input.value = chip.payload;
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        autoGrow(input);
      } else {
        runChipAction(chip.payload);
      }
    });

    row.appendChild(btn);
  }
}

// --------------------------------------------------------------------------- modelo

let _modelos = null;

function cerrarMenuDeModelos() {
  const menu = document.getElementById("model-menu");
  if (menu !== null) menu.remove();
  document.removeEventListener("click", cerrarMenuDeModelos);
}

function alternarMenuDeModelos() {
  // REQ-022/CA-02: defensa en profundidad — el botón ya está `disabled` cuando hay un
  // destino fijado por tarea, esto cubre una apertura programática.
  if (_modelos && _modelos.fijado_por_tarea) return;
  if (document.getElementById("model-menu") !== null) {
    cerrarMenuDeModelos();
    return;
  }
  if (_modelos === null) {
    requestModels();      // llega por `models_loaded` y se vuelve a abrir solo
    return;
  }

  const menu = document.createElement("div");
  menu.id = "model-menu";
  menu.setAttribute("role", "menu");

  for (const proveedor of _modelos.proveedores) {
    const grupo = document.createElement("div");
    grupo.className = "model-group";
    const titulo = document.createElement("div");
    titulo.className = "model-group-title";
    titulo.textContent = proveedor.label;
    grupo.appendChild(titulo);

    for (const modelo of proveedor.modelos) {
      const activo = proveedor.activo && modelo === _modelos.activo.modelo;
      const opcion = document.createElement("button");
      opcion.type = "button";
      opcion.className = "model-option" + (activo ? " active" : "");
      opcion.setAttribute("role", "menuitem");
      const nombre = document.createElement("span");
      nombre.textContent = modelo;      // viene de Python: textContent, nunca innerHTML
      opcion.appendChild(nombre);
      if (activo) opcion.appendChild(icon("check", "ic-sm"));
      opcion.addEventListener("click", () => {
        setModel(proveedor.id, modelo);
        cerrarMenuDeModelos();
      });
      grupo.appendChild(opcion);
    }
    menu.appendChild(grupo);
  }

  $("composer-input-row").appendChild(menu);
  // Un click en cualquier otro lado lo cierra; el del propio botón no llega acá porque
  // `alternarMenuDeModelos` corta la propagación.
  setTimeout(() => document.addEventListener("click", cerrarMenuDeModelos), 0);
}

export function renderModels(payload) {
  _modelos = payload;
  const etiqueta = document.getElementById("model-btn-label");
  const boton = document.getElementById("model-btn");
  const fijado = payload.fijado_por_tarea;

  if (fijado) {
    // REQ-022/CA-02: "razonamiento" tiene destino fijado en `task_providers` — el
    // selector no tendría ningún efecto real, así que se muestra deshabilitado en vez
    // de dejar elegir algo que el backend va a ignorar.
    if (etiqueta) etiqueta.textContent = `Fijado: ${fijado.etiqueta}`;
    if (boton) {
      boton.disabled = true;
      boton.title = `Fijado desde Configuración: ${fijado.etiqueta}`;
    }
    if (document.getElementById("model-menu") !== null) cerrarMenuDeModelos();
    return;
  }

  // REQ-022/CA-05: por si el botón había quedado deshabilitado de una carga anterior.
  if (boton) boton.disabled = false;
  if (etiqueta) etiqueta.textContent = payload.activo.resumen || payload.activo.label || "modelo";
  if (boton) {
    boton.title = `Responde ${payload.activo.label}${payload.activo.modelo ? " · " + payload.activo.modelo : ""}`;
  }
  // Si el menú estaba abierto (o se pidió abrir y faltaban los datos), se repinta.
  if (document.getElementById("model-menu") !== null) {
    cerrarMenuDeModelos();
    alternarMenuDeModelos();
  }
}
