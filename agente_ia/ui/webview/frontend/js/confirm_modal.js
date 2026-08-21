// ui/webview/frontend/js/confirm_modal.js
// REQ-015/CA-41, §4.3, §10.2 — modal genérico de confirmación YELLOW. Cubre tanto las
// confirmaciones "clásicas" (CA-41) como `delete_conversation` desde el ajuste de §10.2
// (mismo modal, sin lógica de borrado propia — ver sidebar.js).
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, Hallazgo A de security-audit-015.md):
// tanto `action_name` como `message` (que incluye `details`, construido por
// `format_details()` a partir de `params` de un intent parseado por NLP — no garantizado
// 100% confiable) se insertan EXCLUSIVAMENTE vía `textContent`. Este archivo NUNCA usa
// `innerHTML`/`insertAdjacentHTML` — verificado además por un grep estructural en
// `tests/test_webview_safe_dom_insertion.py`.

import { confirmResponse } from "./bridge_client.js";

function $(id) {
  return document.getElementById(id);
}

export function showConfirmModal(requestId, actionName, message) {
  const root = $("confirm-modal-root");
  root.replaceChildren(); // por si quedó un modal previo sin resolver (no debería pasar)

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";

  const box = document.createElement("div");
  box.className = "modal-box";

  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Confirmación requerida"; // texto propio, no viene de Python

  const body = document.createElement("div");
  body.className = "modal-message";
  body.textContent = message || actionName; // §10.1 — nunca innerHTML

  const actions = document.createElement("div");
  actions.className = "modal-actions";

  function resolveAndClose(confirmed) {
    confirmResponse(requestId, confirmed);
    root.replaceChildren();
  }

  const cancelBtn = document.createElement("button");
  cancelBtn.type = "button";
  cancelBtn.className = "modal-btn";
  cancelBtn.textContent = "Cancelar";
  cancelBtn.addEventListener("click", () => resolveAndClose(false));

  const confirmBtn = document.createElement("button");
  confirmBtn.type = "button";
  confirmBtn.className = "modal-btn modal-btn-confirm";
  confirmBtn.textContent = "Confirmar";
  confirmBtn.addEventListener("click", () => resolveAndClose(true));

  actions.appendChild(cancelBtn);
  actions.appendChild(confirmBtn);
  box.appendChild(title);
  box.appendChild(body);
  box.appendChild(actions);
  overlay.appendChild(box);
  root.appendChild(overlay);

  confirmBtn.focus();
}
