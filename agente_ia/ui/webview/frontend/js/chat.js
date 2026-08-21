// ui/webview/frontend/js/chat.js
// REQ-015/CA-12..CA-19 — feed de conversación.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §5.2, §10.1): este es el ÚNICO archivo del
// frontend que usa `innerHTML`, y únicamente para el campo `html` de `turns_loaded`/
// `message_appended` — ya sanitizado del lado Python por `render_markdown()` + `bleach`
// (`ui/webview/markdown_render.py`) antes de llegar acá. Ningún otro campo de este
// archivo (ni de ningún otro módulo JS) se inserta así — ver sidebar.js/composer.js/
// confirm_modal.js para los campos de texto NO confiable, que van por `textContent`.

const CLAMP_THRESHOLD = 500; // CA-18

function $(id) {
  return document.getElementById(id);
}

function isEmpty() {
  return $("messages").children.length === 0;
}

function syncEmptyState() {
  $("empty-state").style.display = isEmpty() ? "flex" : "none";
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

export function initChat() {
  syncEmptyState();
}

export function renderTurns(turns) {
  const container = $("messages");
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

export function appendMessage(item) {
  const container = $("messages");
  const shouldStick = isNearBottom();
  container.appendChild(buildMessageNode(item));
  syncEmptyState();
  if (shouldStick) {
    scrollToBottom(); // CA-16: no interrumpe si el usuario se alejó del final
  }
}

export function clearMessages() {
  $("messages").replaceChildren();
  syncEmptyState();
}

export function setTyping(active) {
  $("typing-indicator").hidden = !active;
  if (active) scrollToBottom();
}

export function updateGuiState(state) {
  document.body.dataset.guiState = state;
}
