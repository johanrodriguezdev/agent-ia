// ui/webview/frontend/js/composer.js
// REQ-015/CA-20..CA-25, CA-39, CA-40 — barra de entrada, chips y toggle de voz.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, Hallazgo A de security-audit-015.md):
// el nombre del archivo soltado (`file_attached.name`, viene de
// `QDropEvent.mimeData().urls()` — puede no ser texto que el propio usuario escribió, el
// caso más peligroso de los tres señalado por `orion-security`) se inserta EXCLUSIVAMENTE
// vía `textContent`. Este archivo NUNCA usa `innerHTML`/`insertAdjacentHTML` — verificado
// además por un grep estructural en `tests/test_webview_safe_dom_insertion.py`.

import { sendMessage, runChipAction, toggleWakeWord } from "./bridge_client.js";

const MAX_VISIBLE_ROWS = 5;
const LINE_HEIGHT_PX = 20;

let _sendEnabled = true;

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
  sendMessage(text);
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

  $("send-btn").addEventListener("click", doSend);

  $("wake-toggle-btn").addEventListener("click", () => {
    const btn = $("wake-toggle-btn");
    const turningOn = btn.dataset.wakeState === "INACTIVE";
    toggleWakeWord(turningOn);
  });

  $("attachment-chip-remove").addEventListener("click", () => {
    $("attachment-chip").hidden = true;
  });

  // CA-22: el flujo real de adjuntar es el drag&drop nativo sobre toda la ventana
  // (§5.3) — no hay slot de bridge para abrir un diálogo de selección en el contrato
  // aprobado (§4.1), así que el botón es un affordance visual, no dispara nada.
  $("attach-btn").title = "Arrastrá un archivo a la ventana para adjuntarlo";
}

export function setComposerEnabled(enabled) {
  // CA-24: guarda client-side (paridad UX) — el guard real, server-side y estricto,
  // vive en `Bridge.send_message()` (`_resolution_in_flight`), porque el bridge es
  // invocable desde JS sin pasar por el estado `disabled` del DOM.
  _sendEnabled = enabled;
  $("composer-input").disabled = !enabled;
  $("send-btn").disabled = !enabled;
}

export function setWakeState(state) {
  const btn = $("wake-toggle-btn");
  btn.dataset.wakeState = state;
  const labels = {
    INACTIVE: "Modo manos libres: inactivo",
    LISTENING_WAKE: "Modo manos libres: escuchando wake word",
    AWAKE: "Modo manos libres: despierto",
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
  chip.hidden = false;
}

export function renderChips(chips) {
  const row = $("chips-row");
  row.replaceChildren();
  for (const chip of chips) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip";

    if (chip.kind === "action" && chip.risk_level) {
      const dot = document.createElement("span");
      dot.className = `chip-risk-dot chip-risk-${chip.risk_level}`;
      btn.appendChild(dot);
    }

    const label = document.createElement("span");
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
