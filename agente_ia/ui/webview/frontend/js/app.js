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
  onTurnsLoaded, onMessageAppended, onTypingStarted, onTypingStopped, onProgressUpdated,
  onConfirmationRequested, onFileAttached, onErrorOccurred, onWindowMaximizedChanged,
  onTasksLoaded, onProjectsLoaded, onProjectConversationsLoaded, onProjectRemoved,
  onSecurityOverridesLoaded, onSecurityOverrideSaved, onSecurityOverrideSaveRejected,
  onEmailCapabilitiesLoaded, onEmailCapabilitySaved, onEmailCapabilitySaveRejected,
  onFlowsLoaded,
  onProfileLoaded, onProfileSaved,
  onTerminalOutput, onTerminalState, onTerminalTabs,
  onNoticeShown, onMessageChunk, onConversationSearchResults, onModelsLoaded,
  onProjectItemsLoaded, onAssignableItemsLoaded, onDragOverChanged,
  requestModels, newConversation,
} from "./bridge_client.js";
import {
  initSidebar, renderConversationList, clearActiveConversation, removeConversationFromList,
  renderSearchResults,
} from "./sidebar.js";
import {
  initChat, renderTurns, appendMessage, clearMessages, setTyping, setProgress, updateGuiState,
  appendChunk, clearChunks,
} from "./chat.js";
import {
  initComposer, setComposerEnabled, setWakeState, showAttachment, renderChips, renderModels,
} from "./composer.js";
import { initTheme, applyTheme } from "./theme.js";
import { showConfirmModal } from "./confirm_modal.js";
import { initWindowChrome, setMaximizedState } from "./window_chrome.js";
import { openTasksPanel, renderTasks } from "./tasks_panel.js";
import {
  toggleTerminalPanel, escribirSalida, manejarEstadoTerminal, renderTerminalTabs,
  refrescarTemaTerminal,
} from "./terminal_panel.js";
import { initToasts, mostrarAviso } from "./toasts.js";
import { initShortcuts } from "./shortcuts.js";
import { openFlowsPanel, renderFlows } from "./flows_panel.js";
import {
  openProjectsPanel, renderProjects, renderProjectConversations, handleProjectRemoved,
  renderProjectItems, renderAssignableItems,
} from "./projects_panel.js";
import {
  openSettingsPanel, renderSecurityOverrides, handleSecurityOverrideSaved,
  handleSecurityOverrideRejected, renderProfile, handleProfileSaved,
  renderEmailCapabilities, handleEmailCapabilitySaved, handleEmailCapabilityRejected,
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

function setAgentIdentity(name) {
  // CA-46: avatar = círculo con la inicial del agente. El valor inicial lo inyecta
  // `MainWindow` como variable global (ver `main_window.py::_inject_agent_name_script`);
  // cuando el usuario lo cambia en Configuración, `profile_loaded` trae el nombre nuevo y
  // esta misma función lo repinta sin reiniciar.
  const agentName = (name || window.__ORION_AGENT_NAME__ || "ORION").trim();
  const upper = agentName.toUpperCase();

  document.getElementById("agent-name-label").textContent = upper;
  document.getElementById("empty-state-avatar").textContent = agentName.charAt(0).toUpperCase();
  document.getElementById("empty-state-greeting").textContent = timeBasedGreeting();
}

async function bootstrap() {
  setAgentIdentity();

  initWindowChrome();
  initToasts();
  initTheme();
  initSidebar();
  initChat();
  initComposer();
  initShortcuts({ alternarTerminal: toggleTerminalPanel, chatNuevo: () => newConversation() });

  await connectBridge();

  onGuiStateChanged(updateGuiState);
  onWakeStateChanged(setWakeState);
  onThemeChanged((name) => {
    applyTheme(name);
    refrescarTemaTerminal();   // xterm pinta sobre canvas: no hereda el cambio de CSS
  });
  onChipsLoaded((json) => renderChips(JSON.parse(json)));

  onConversationListUpdated((json) => renderConversationList(JSON.parse(json)));
  onConversationCleared(() => {
    clearActiveConversation();
    clearMessages();
  });
  onConversationRemoved((conversationId) => removeConversationFromList(conversationId));

  onTurnsLoaded((json) => renderTurns(JSON.parse(json)));
  onMessageAppended((json) => appendMessage(JSON.parse(json)));

  onProgressUpdated((text) => setProgress(text));

  onTypingStarted(() => {
    setTyping(true);
    setComposerEnabled(false); // CA-24: paridad UX con el guard server-side del bridge
  });
  onTypingStopped(() => {
    setTyping(false);
    setComposerEnabled(true);
    // Si el turno se corto (boton de detener) no va a llegar ningun `message_appended`
    // que reemplace lo que se estaba escribiendo: se saca aca.
    clearChunks();
  });

  onConfirmationRequested((requestId, actionName, message) => {
    showConfirmModal(requestId, actionName, message);
  });
  onFileAttached((path, name, accepted, reason) => {
    showAttachment(path, name, accepted, reason);
  });
  // Los errores del bridge terminaban en un console.error que nadie mira: si fallaba
  // borrar una conversacion o guardar la configuracion, la pantalla no decia nada.
  onErrorOccurred((message) => {
    // eslint-disable-next-line no-console
    console.error("[bridge:error_occurred]", message);
    mostrarAviso("error", message);
  });
  onNoticeShown((nivel, mensaje) => mostrarAviso(nivel, mensaje));

  // La respuesta se ve mientras se escribe; el mensaje definitivo (ya con formato) la
  // reemplaza al llegar.
  onMessageChunk(appendChunk);

  onConversationSearchResults((json) => renderSearchResults(JSON.parse(json)));
  onModelsLoaded((json) => renderModels(JSON.parse(json)));
  onDragOverChanged((activo) => {
    const capa = document.getElementById("drop-overlay");
    if (capa) capa.hidden = !activo;
  });
  onWindowMaximizedChanged(setMaximizedState);

  // REQ-016: herramientas de la barra superior (Tareas/Flujos/Proyectos) + señales de
  // datos de sus modales. Antes eran botones con emoji dentro del sidebar.
  document.getElementById("terminal-btn").addEventListener("click", toggleTerminalPanel);
  onTerminalOutput(escribirSalida);
  onTerminalState(manejarEstadoTerminal);
  onTerminalTabs((json) => renderTerminalTabs(JSON.parse(json)));

  document.getElementById("tasks-btn").addEventListener("click", openTasksPanel);
  const flowsBtn = document.getElementById("flows-btn");
  if (flowsBtn) flowsBtn.addEventListener("click", openFlowsPanel);
  document.getElementById("projects-btn").addEventListener("click", openProjectsPanel);
  onTasksLoaded((json) => renderTasks(JSON.parse(json)));
  onProjectsLoaded((json) => renderProjects(JSON.parse(json)));
  onProjectConversationsLoaded((json, projectId) => renderProjectConversations(JSON.parse(json), projectId));
  onProjectRemoved((projectId) => handleProjectRemoved(projectId));
  onProjectItemsLoaded((json, projectId) => renderProjectItems(JSON.parse(json), projectId));
  onAssignableItemsLoaded((json) => renderAssignableItems(JSON.parse(json)));

  // REQ-019: "Configuración" (barra superior) + señales de la sección "Seguridad".
  document.getElementById("settings-btn").addEventListener("click", openSettingsPanel);
  // Perfil: `profile_loaded` llega tanto al abrir la sección como después de guardar, así
  // que renombrar al agente se refleja en la ventana al instante, sin reiniciar.
  onProfileLoaded((json) => {
    const profile = JSON.parse(json);
    renderProfile(profile);
    setAgentIdentity(profile.agent_name);
  });
  onProfileSaved((json) => handleProfileSaved(JSON.parse(json)));

  onSecurityOverridesLoaded((json) => renderSecurityOverrides(JSON.parse(json)));
  onSecurityOverrideSaved((rowId, level) => handleSecurityOverrideSaved(rowId, level));
  onSecurityOverrideSaveRejected((rowId) => handleSecurityOverrideRejected(rowId));
  onEmailCapabilitiesLoaded((json) => renderEmailCapabilities(JSON.parse(json)));
  onEmailCapabilitySaved((capId, enabled) => handleEmailCapabilitySaved(capId, enabled));
  onEmailCapabilitySaveRejected((capId) => handleEmailCapabilityRejected(capId));
  onFlowsLoaded((json) => renderFlows(JSON.parse(json)));

  requestInitialState();
  requestModels();   // el composer muestra con que modelo responde

  // Hook de sincronización para `tests/test_webview_smoke.py` (QWebEngineView offscreen
  // real) — sin esto, un test que emite un evento del bridge justo después de construir
  // la ventana podría hacerlo antes de que este módulo termine de suscribirse, y la
  // señal se perdería (Qt no reproduce señales para suscriptores tardíos). No se usa en
  // producción.
  window.__ORION_APP_READY__ = true;
}

bootstrap();
