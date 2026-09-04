// ui/webview/frontend/js/tasks_panel.js
// REQ-016/CA-05..CA-12 — modal de Tareas: crear, listar (pendientes/completadas),
// completar y eliminar tareas del escritorio.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1, extendida por arquitectura-016.md §10):
// cualquier campo recibido de Python que no sea `html` ya sanitizado se inserta
// EXCLUSIVAMENTE vía `textContent`/`setAttribute` — nunca `innerHTML`/`insertAdjacentHTML`.
// Verificado además por un grep estructural en tests/test_webview_safe_dom_insertion.py.

import { requestTasks, createTask, completeTask, requestDeleteTask } from "./bridge_client.js";
import { icon } from "./icons.js";

let _panelOpen = false;   // guard contra doble click (caso borde de SPEC-016)

export function openTasksPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  renderShell();
  requestTasks();   // CA-12: carga perezosa, solo acá
}

export function closeTasksPanel() {
  _panelOpen = false;
  document.getElementById("panel-modal-root").replaceChildren();
}

function renderShell() {
  const root = document.getElementById("panel-modal-root");
  root.replaceChildren();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) closeTasksPanel(); });

  const box = document.createElement("div");
  box.className = "modal-box modal-box-wide";

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Tareas";   // texto propio, no viene de Python — no aplica §10.1
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.appendChild(icon("close", "ic-sm"));
  closeBtn.addEventListener("click", closeTasksPanel);
  header.appendChild(title);
  header.appendChild(closeBtn);

  const form = buildTaskForm();
  const list = document.createElement("div");
  list.id = "tasks-panel-list";
  list.className = "panel-list";

  box.appendChild(header);
  box.appendChild(form);
  box.appendChild(list);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

function buildTaskForm() {
  const form = document.createElement("form");
  form.className = "panel-form";

  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.placeholder = "Título de la tarea";
  titleInput.required = true;

  const dateInput = document.createElement("input");
  dateInput.type = "datetime-local";

  const prioritySelect = document.createElement("select");
  for (const [value, label] of [["normal", "Normal"], ["high", "Alta prioridad"]]) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    prioritySelect.appendChild(opt);
  }

  const descInput = document.createElement("input");
  descInput.type = "text";
  descInput.placeholder = "Descripción (opcional)";

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  submitBtn.className = "panel-submit-btn";
  submitBtn.textContent = "Agregar";

  form.append(titleInput, dateInput, prioritySelect, descInput, submitBtn);
  form.addEventListener("submit", (evt) => {
    evt.preventDefault();
    const titleValue = titleInput.value.trim();
    if (!titleValue) return;   // CA-06: título obligatorio, guard también del lado JS
    createTask(titleValue, descInput.value, dateInput.value, prioritySelect.value);
    form.reset();
  });
  return form;
}

export function renderTasks(tasks) {
  const list = document.getElementById("tasks-panel-list");
  if (!list) return;   // panel ya fue cerrado antes de que llegara la respuesta
  list.replaceChildren();

  if (tasks.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "No hay tareas todavía.";
    list.appendChild(empty);
    return;
  }

  for (const task of tasks) {
    list.appendChild(buildTaskItem(task));
  }
}

function buildTaskItem(task) {
  const item = document.createElement("div");
  item.className = "panel-item task-item";
  if (task.status === "completed") item.classList.add("completed");   // CA-07: distinción visual

  const info = document.createElement("div");
  info.className = "panel-item-info";
  const titleEl = document.createElement("span");
  titleEl.className = "panel-item-title";
  titleEl.textContent = task.title;   // §10.1 — nunca innerHTML
  info.appendChild(titleEl);
  if (task.due_date) {
    const dateEl = document.createElement("span");
    dateEl.className = "panel-item-meta";
    dateEl.textContent = task.due_date;
    info.appendChild(dateEl);
  }

  const actions = document.createElement("div");
  actions.className = "panel-item-actions";

  if (task.status !== "completed") {
    const doneBtn = document.createElement("button");
    doneBtn.type = "button";
    doneBtn.className = "panel-item-btn";
    doneBtn.setAttribute("aria-label", "Marcar como completada");
    doneBtn.textContent = "✓";
    doneBtn.addEventListener("click", () => completeTask(task.id));
    actions.appendChild(doneBtn);
  }

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "panel-item-btn panel-item-btn-danger";
  deleteBtn.setAttribute("aria-label", "Eliminar tarea");
  deleteBtn.title = "Eliminar tarea";
  deleteBtn.appendChild(icon("trash", "ic-sm"));
  deleteBtn.addEventListener("click", () => requestDeleteTask(task.id));   // CA-08: dispara YELLOW
  actions.appendChild(deleteBtn);

  item.append(info, actions);
  return item;
}
