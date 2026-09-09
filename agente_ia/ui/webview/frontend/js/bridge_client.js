// ui/webview/frontend/js/bridge_client.js
// REQ-015/§4 — wrapper delgado sobre `window.bridge` (QWebChannel). Un método JS por
// comando JS→Python (§4.1) y un helper `on*` por evento Python→JS (§4.2). Ningún otro
// módulo del frontend toca `window.bridge`/`QWebChannel` directamente — todos pasan por
// acá (mismo criterio que "no importar funciones de otros skills directamente" de
// `.claude/rules/skills.md`, aplicado al lado JS).

/* global QWebChannel, qt */

let _bridge = null;

export function connectBridge() {
  return new Promise((resolve) => {
    new QWebChannel(qt.webChannelTransport, (channel) => {
      _bridge = channel.objects.bridge;
      resolve(_bridge);
    });
  });
}

export function getBridge() {
  return _bridge;
}

// ------------------------------------------------------------ JS → Python (§4.1)
export function requestInitialState() { _bridge.request_initial_state(); }
export function sendMessage(text, modo) { _bridge.send_message(text, modo || ""); }
export function newConversation() { _bridge.new_conversation(); }
export function selectConversation(conversationId) { _bridge.select_conversation(conversationId); }
export function requestDeleteConversation(conversationId) { _bridge.request_delete_conversation(conversationId); }
export function loadMoreConversations(offset) { _bridge.load_more_conversations(offset); }
export function runChipAction(actionName) { _bridge.run_chip_action(actionName); }
export function setTheme(name) { _bridge.set_theme(name); }
export function toggleWakeWord(enabled) { _bridge.toggle_wake_word(enabled); }
export function confirmResponse(requestId, confirmed) { _bridge.confirm_response(requestId, confirmed); }
export function startResize(edge) { _bridge.start_resize(edge); }
export function startMove() { _bridge.start_move(); }
export function windowMinimize() { _bridge.window_minimize(); }
export function windowToggleMaximize() { _bridge.window_toggle_maximize(); }
export function windowClose() { _bridge.window_close(); }

// ------------------------------------------------------------ JS → Python (REQ-016)
export function requestTasks() { _bridge.request_tasks(); }
export function createTask(title, description, dueDate, priority) { _bridge.create_task(title, description, dueDate, priority); }
export function completeTask(taskId) { _bridge.complete_task(taskId); }
export function requestDeleteTask(taskId) { _bridge.request_delete_task(taskId); }
export function requestProjects() { _bridge.request_projects(); }
export function createProject(name) { _bridge.create_project(name); }
export function assignConversationToProject(conversationId, projectId) { _bridge.assign_conversation_to_project(conversationId, projectId); }
export function unassignConversationFromProject(conversationId) { _bridge.unassign_conversation_from_project(conversationId); }
export function requestProjectConversations(projectId) { _bridge.request_project_conversations(projectId); }
export function requestDeleteProject(projectId) { _bridge.request_delete_project(projectId); }

// ------------------------------------------------------------ JS → Python (perfil)
export function requestProfile() { _bridge.request_profile(); }
export function saveProfile(agentName, pronunciation, displayName, userTitle) {
  _bridge.save_profile(agentName, pronunciation, displayName, userTitle);
}

// ------------------------------------------------------------ JS → Python (REQ-019)
export function requestSecurityOverrides() { _bridge.request_security_overrides(); }
export function saveSecurityOverride(rowId, level) { _bridge.save_security_override(rowId, level); }
export function requestFlows() { _bridge.request_flows(); }
export function runFlow(flowId) { _bridge.run_flow(flowId); }
export function cancelFlow(flowId) { _bridge.cancel_flow(flowId); }
export function requestDeleteFlow(flowId) { _bridge.request_delete_flow(flowId); }
export function removeFlowStep(flowId, indice) { _bridge.remove_flow_step(flowId, indice); }
export function requestEmailCapabilities() { _bridge.request_email_capabilities(); }
export function saveEmailCapability(capId, enabled) { _bridge.save_email_capability(capId, enabled); }

// ------------------------------------------------------------ Python → JS (§4.2)
export function onConversationListUpdated(cb) { _bridge.conversation_list_updated.connect(cb); }
export function onConversationCleared(cb) { _bridge.conversation_cleared.connect(cb); }
export function onConversationRemoved(cb) { _bridge.conversation_removed.connect(cb); }
export function onTurnsLoaded(cb) { _bridge.turns_loaded.connect(cb); }
export function onMessageAppended(cb) { _bridge.message_appended.connect(cb); }
export function onProgressUpdated(cb) { _bridge.progress_updated.connect(cb); }
export function onTypingStarted(cb) { _bridge.typing_started.connect(cb); }
export function onTypingStopped(cb) { _bridge.typing_stopped.connect(cb); }
export function onGuiStateChanged(cb) { _bridge.gui_state_changed.connect(cb); }
export function onWakeStateChanged(cb) { _bridge.wake_state_changed.connect(cb); }
export function onThemeChanged(cb) { _bridge.theme_changed.connect(cb); }
export function onConfirmationRequested(cb) { _bridge.confirmation_requested.connect(cb); }
export function onFileAttached(cb) { _bridge.file_attached.connect(cb); }
export function onChipsLoaded(cb) { _bridge.chips_loaded.connect(cb); }
export function onErrorOccurred(cb) { _bridge.error_occurred.connect(cb); }
export function onWindowMaximizedChanged(cb) { _bridge.window_maximized_changed.connect(cb); }
// REQ-033 — el modo autonomia. `setAutonomyMode` es lo unico que lo enciende: no existe
// ninguna herramienta del agente que llegue aca, a proposito.
export function setAutonomyMode(nivel, pin) { _bridge.set_autonomy_mode(nivel, pin || ""); }
export function onAutonomyChanged(cb) { _bridge.autonomy_changed.connect(cb); }

// ------------------------------------------------------------ Python → JS (REQ-016)
export function onTasksLoaded(cb) { _bridge.tasks_loaded.connect(cb); }
export function onProjectsLoaded(cb) { _bridge.projects_loaded.connect(cb); }
export function onProjectConversationsLoaded(cb) { _bridge.project_conversations_loaded.connect(cb); }
export function onProjectRemoved(cb) { _bridge.project_removed.connect(cb); }

// ------------------------------------------------------------ Python → JS (perfil)
export function onProfileLoaded(cb) { _bridge.profile_loaded.connect(cb); }
export function onProfileSaved(cb) { _bridge.profile_saved.connect(cb); }

// ------------------------------------------------------------ Python → JS (REQ-019)
export function onSecurityOverridesLoaded(cb) { _bridge.security_overrides_loaded.connect(cb); }
export function onSecurityOverrideSaved(cb) { _bridge.security_override_saved.connect(cb); }
export function onSecurityOverrideSaveRejected(cb) { _bridge.security_override_save_rejected.connect(cb); }
export function onFlowsLoaded(cb) { _bridge.flows_loaded.connect(cb); }
export function onEmailCapabilitiesLoaded(cb) { _bridge.email_capabilities_loaded.connect(cb); }
export function onEmailCapabilitySaved(cb) { _bridge.email_capability_saved.connect(cb); }
export function onEmailCapabilitySaveRejected(cb) { _bridge.email_capability_save_rejected.connect(cb); }

// ------------------------------------------------------------ terminal embebida
// Cada llamada lleva el id de la sesión: hay varias pestañas y el agente trabaja contra la
// que está a la vista. `terminalInput` manda las teclas crudas (Tab, Ctrl+C, flechas):
// xterm.js entrega lo que el usuario tecleó sin interpretarlo y del otro lado lo recibe la
// PTY igual de crudo.
export function terminalOpen() { _bridge.terminal_open(); }
export function terminalNew() { _bridge.terminal_new(); }
export function terminalInput(sessionId, data) { _bridge.terminal_input(sessionId, data); }
export function terminalResize(sessionId, cols, rows) { _bridge.terminal_resize(sessionId, cols, rows); }
export function terminalFocus(sessionId) { _bridge.terminal_focus(sessionId); }
export function terminalClose(sessionId) { _bridge.terminal_close(sessionId); }
export function terminalCloseAll() { _bridge.terminal_close_all(); }
export function requestTerminalTabs() { _bridge.request_terminal_tabs(); }
export function onTerminalOutput(cb) { _bridge.terminal_output.connect(cb); }
export function onTerminalState(cb) { _bridge.terminal_state.connect(cb); }
export function onTerminalTabs(cb) { _bridge.terminal_tabs.connect(cb); }

// ------------------------------------------------------------ turno en curso y avisos
export function stopResolution() { _bridge.stop_resolution(); }
export function onNoticeShown(cb) { _bridge.notice_shown.connect(cb); }
export function onMessageChunk(cb) { _bridge.message_chunk.connect(cb); }

// ------------------------------------------------------------ adjuntar, renombrar, buscar
export function openAttachDialog() { _bridge.open_attach_dialog(); }
export function renameConversation(conversationId, title) {
  _bridge.rename_conversation(conversationId, title);
}
export function searchConversations(query) { _bridge.search_conversations(query); }
export function onConversationSearchResults(cb) {
  _bridge.conversation_search_results.connect(cb);
}

// ------------------------------------------------------------ codigo -> terminal
export function runCommandInTerminal(command) { _bridge.run_command_in_terminal(command); }

// ------------------------------------------------------------ proveedor y modelo
export function requestModels() { _bridge.request_models(); }
export function setModel(provider, model) { _bridge.set_model(provider, model); }
export function onModelsLoaded(cb) { _bridge.models_loaded.connect(cb); }

// ------------------------------------------------------------ modos estratégicos (REQ-026)
export function setActiveMode(modoId) { _bridge.set_active_mode(modoId || ""); }

// ------------------------------------------------------------ elementos de proyecto
export function requestProjectItems(projectId) { _bridge.request_project_items(projectId); }
export function assignItemToProject(kind, itemId, projectId, label) {
  _bridge.assign_item_to_project(kind, itemId, projectId, label);
}
export function unassignItemFromProject(kind, itemId, projectId) {
  _bridge.unassign_item_from_project(kind, itemId, projectId);
}
export function requestAssignableItems() { _bridge.request_assignable_items(); }
export function onProjectItemsLoaded(cb) { _bridge.project_items_loaded.connect(cb); }
export function onAssignableItemsLoaded(cb) { _bridge.assignable_items_loaded.connect(cb); }
export function onDragOverChanged(cb) { _bridge.drag_over_changed.connect(cb); }
export function clearAttachment() { _bridge.clear_attachment(); }

// ------------------------------------------------------------ modelo por tarea
export function requestTaskModels() { _bridge.request_task_models(); }
export function saveTaskModels(tarea, destinosJson) {
  _bridge.save_task_models(tarea, destinosJson);
}
export function onTaskModelsLoaded(cb) { _bridge.task_models_loaded.connect(cb); }

// ------------------------------------------------------------ credenciales
export function requestConnections() { _bridge.request_connections(); }
export function saveConnection(clave, valor) { _bridge.save_connection(clave, valor); }
export function clearConnection(clave) { _bridge.clear_connection(clave); }
export function onConnectionsLoaded(cb) { _bridge.connections_loaded.connect(cb); }
export function onSetupRequired(cb) { _bridge.setup_required.connect(cb); }
