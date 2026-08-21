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
export function sendMessage(text) { _bridge.send_message(text); }
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

// ------------------------------------------------------------ JS → Python (REQ-019)
export function requestSecurityOverrides() { _bridge.request_security_overrides(); }
export function saveSecurityOverride(rowId, level) { _bridge.save_security_override(rowId, level); }

// ------------------------------------------------------------ Python → JS (§4.2)
export function onConversationListUpdated(cb) { _bridge.conversation_list_updated.connect(cb); }
export function onConversationCleared(cb) { _bridge.conversation_cleared.connect(cb); }
export function onConversationRemoved(cb) { _bridge.conversation_removed.connect(cb); }
export function onTurnsLoaded(cb) { _bridge.turns_loaded.connect(cb); }
export function onMessageAppended(cb) { _bridge.message_appended.connect(cb); }
export function onTypingStarted(cb) { _bridge.typing_started.connect(cb); }
export function onTypingStopped(cb) { _bridge.typing_stopped.connect(cb); }
export function onGuiStateChanged(cb) { _bridge.gui_state_changed.connect(cb); }
export function onWakeStateChanged(cb) { _bridge.wake_state_changed.connect(cb); }
export function onThemeChanged(cb) { _bridge.theme_changed.connect(cb); }
export function onConfirmationRequested(cb) { _bridge.confirmation_requested.connect(cb); }
export function onFileAttached(cb) { _bridge.file_attached.connect(cb); }
export function onChipsLoaded(cb) { _bridge.chips_loaded.connect(cb); }
export function onErrorOccurred(cb) { _bridge.error_occurred.connect(cb); }

// ------------------------------------------------------------ Python → JS (REQ-016)
export function onTasksLoaded(cb) { _bridge.tasks_loaded.connect(cb); }
export function onProjectsLoaded(cb) { _bridge.projects_loaded.connect(cb); }
export function onProjectConversationsLoaded(cb) { _bridge.project_conversations_loaded.connect(cb); }
export function onProjectRemoved(cb) { _bridge.project_removed.connect(cb); }

// ------------------------------------------------------------ Python → JS (REQ-019)
export function onSecurityOverridesLoaded(cb) { _bridge.security_overrides_loaded.connect(cb); }
export function onSecurityOverrideSaved(cb) { _bridge.security_override_saved.connect(cb); }
export function onSecurityOverrideSaveRejected(cb) { _bridge.security_override_save_rejected.connect(cb); }
