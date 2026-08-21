// ui/webview/frontend/js/app.js
// REQ-015 — bootstrap: conecta QWebChannel, cablea todos los listeners del bridge (§4.2)
// a los módulos de UI, y pide el estado inicial.
//
// Decisión de implementación (ver desarrollo-log-015.md): `request_initial_state()` es
// un slot nuevo, sin equivalente literal en la tabla de §4.1 — necesario porque una señal
// Qt emitida ANTES de que este módulo se suscriba se pierde (no hay replay). Se llama una
// única vez, apenas `window.bridge` está disponible.

import {
  connectBridge, requestInitialState,
  onGuiStateChanged, onWakeStateChanged, onThemeChanged, onChipsLoaded,
  onConversationListUpdated, onConversationCleared, onConversationRemoved,
  onTurnsLoaded, onMessageAppended, onTypingStarted, onTypingStopped,
  onConfirmationRequested, onFileAttached, onErrorOccurred,
  onTasksLoaded, onProjectsLoaded, onProjectConversationsLoaded, onProjectRemoved,
  onSecurityOverridesLoaded, onSecurityOverrideSaved, onSecurityOverrideSaveRejected,
} from "./bridge_client.js";
import {
  initSidebar, renderConversationList, clearActiveConversation, removeConversationFromList,
} from "./sidebar.js";
import {
  initChat, renderTurns, appendMessage, clearMessages, setTyping, updateGuiState,
} from "./chat.js";
import {
  initComposer, setComposerEnabled, setWakeState, showAttachment, renderChips,
} from "./composer.js";
import { initTheme, applyTheme } from "./theme.js";
import { showConfirmModal } from "./confirm_modal.js";
import { initWindowChrome } from "./window_chrome.js";
import { openTasksPanel, renderTasks } from "./tasks_panel.js";
import {
  openProjectsPanel, renderProjects, renderProjectConversations, handleProjectRemoved,
} from "./projects_panel.js";
import {
  openSettingsPanel, renderSecurityOverrides, handleSecurityOverrideSaved,
  handleSecurityOverrideRejected,
} from "./settings_panel.js";

const GREETINGS_BY_HOUR = [
  { from: 5, to: 12, text: "Buenos días" },
  { from: 12, to: 19, text: "Buenas tardes" },
];

function timeBasedGreeting() {
  const hour = new Date().getHours();
  const match = GREETINGS_BY_HOUR.find((slot) => hour >= slot.from && hour < slot.to);
  return match ? match.text : "Buenas noches";
}

function setAgentIdentity() {
  // CA-46: avatar = círculo con la inicial del agente; inyectado como variable global por
  // `MainWindow` (ver `ui/webview/main_window.py::_inject_agent_name_script`) — más
  // simple que ampliar el contrato de `Bridge` (§4) para un valor estático.
  const agentName = (window.__ORION_AGENT_NAME__ || "ORION").trim();
  const upper = agentName.toUpperCase();

  document.getElementById("agent-name-label").textContent = upper;
  document.getElementById("sidebar-logo").textContent = upper;
  document.getElementById("empty-state-avatar").textContent = agentName.charAt(0).toUpperCase();
  document.getElementById("empty-state-greeting").textContent = timeBasedGreeting();
}

async function bootstrap() {
  setAgentIdentity();

  initWindowChrome();
  initTheme();
  initSidebar();
  initChat();
  initComposer();

  await connectBridge();

  onGuiStateChanged(updateGuiState);
  onWakeStateChanged(setWakeState);
  onThemeChanged(applyTheme);
  onChipsLoaded((json) => renderChips(JSON.parse(json)));

  onConversationListUpdated((json) => renderConversationList(JSON.parse(json)));
  onConversationCleared(() => {
    clearActiveConversation();
    clearMessages();
  });
  onConversationRemoved((conversationId) => removeConversationFromList(conversationId));

  onTurnsLoaded((json) => renderTurns(JSON.parse(json)));
  onMessageAppended((json) => appendMessage(JSON.parse(json)));

  onTypingStarted(() => {
    setTyping(true);
    setComposerEnabled(false); // CA-24: paridad UX con el guard server-side del bridge
  });
  onTypingStopped(() => {
    setTyping(false);
    setComposerEnabled(true);
  });

  onConfirmationRequested((requestId, actionName, message) => {
    showConfirmModal(requestId, actionName, message);
  });
  onFileAttached((path, name, accepted, reason) => {
    showAttachment(path, name, accepted, reason);
  });
  onErrorOccurred((message) => {
    // eslint-disable-next-line no-console
    console.error("[bridge:error_occurred]", message);
  });

  // REQ-016: botones "Tareas"/"Proyectos" del sidebar + señales de datos de sus modales.
  document.getElementById("tasks-btn").addEventListener("click", openTasksPanel);
  document.getElementById("projects-btn").addEventListener("click", openProjectsPanel);
  onTasksLoaded((json) => renderTasks(JSON.parse(json)));
  onProjectsLoaded((json) => renderProjects(JSON.parse(json)));
  onProjectConversationsLoaded((json, projectId) => renderProjectConversations(JSON.parse(json), projectId));
  onProjectRemoved((projectId) => handleProjectRemoved(projectId));

  // REQ-019: botón "Configuración" del sidebar + señales de la sección "Seguridad".
  document.getElementById("settings-btn").addEventListener("click", openSettingsPanel);
  onSecurityOverridesLoaded((json) => renderSecurityOverrides(JSON.parse(json)));
  onSecurityOverrideSaved((rowId, level) => handleSecurityOverrideSaved(rowId, level));
  onSecurityOverrideSaveRejected((rowId) => handleSecurityOverrideRejected(rowId));

  requestInitialState();

  // Hook de sincronización para `tests/test_webview_smoke.py` (QWebEngineView offscreen
  // real) — sin esto, un test que emite un evento del bridge justo después de construir
  // la ventana podría hacerlo antes de que este módulo termine de suscribirse, y la
  // señal se perdería (Qt no reproduce señales para suscriptores tardíos). No se usa en
  // producción.
  window.__ORION_APP_READY__ = true;
}

bootstrap();
