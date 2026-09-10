// ui/webview/frontend/js/flows_panel.js
// Pantalla de Flujos: VER lo que se creó hablando y corregir un paso que salió mal.
//
// Deliberadamente NO es un constructor de flujos. El flujo se crea diciéndolo ("aprendé el
// flujo modo trabajo: abrí chrome, después el bloc de notas"); esta pantalla sirve para
// mirarlo, ver en qué paso quedó, sacar un paso equivocado, ejecutarlo, cancelarlo o
// borrarlo. Un asistente al que hay que llenarle un formulario para enseñarle una rutina
// deja de ser un asistente.
//
// REGLA DE SEGURIDAD (arquitectura-015.md §10.1): todo lo que viene de Python se inserta
// EXCLUSIVAMENTE vía `textContent`/`setAttribute` — nunca `innerHTML`. El nombre de un
// flujo puede venir de un comando dictado y el resultado de un paso es la salida cruda de
// una acción: ninguno de los dos es HTML de confianza.

import {
  requestFlows, runFlow, cancelFlow, requestDeleteFlow, removeFlowStep,
} from "./bridge_client.js";
import { icon } from "./icons.js";
import { nombreDelAgente } from "./agente.js";

let _panelOpen = false;

const ESTADO_ETIQUETA = {
  pendiente: "sin empezar",
  corriendo: "ejecutándose",
  esperando: "esperando permiso",
  exitoso: "completado",
  fallido: "falló",
  cancelado: "cancelado",
  omitido: "omitido",
};

export function openFlowsPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  renderShell();
  requestFlows();   // carga perezosa, solo acá
}

export function closeFlowsPanel() {
  _panelOpen = false;
  document.getElementById("panel-modal-root").replaceChildren();
}

function renderShell() {
  const root = document.getElementById("panel-modal-root");
  root.replaceChildren();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) closeFlowsPanel(); });

  const box = document.createElement("div");
  box.className = "modal-box modal-box-wide";

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Flujos";
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.appendChild(icon("close", "ic-sm"));
  closeBtn.addEventListener("click", closeFlowsPanel);
  header.append(title, closeBtn);

  const ayuda = document.createElement("div");
  ayuda.className = "panel-hint";
  ayuda.textContent =
    "Los flujos se crean hablando: «aprendé el flujo modo trabajo: abrí chrome, después " +
    "el bloc de notas». Acá los ves y los corregís.";

  const list = document.createElement("div");
  list.id = "flows-panel-list";
  list.className = "panel-list";

  box.append(header, ayuda, list);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

export function renderFlows(flujos) {
  const list = document.getElementById("flows-panel-list");
  if (!list) return;   // el panel ya se cerró antes de que llegara la respuesta
  list.replaceChildren();

  if (!flujos || flujos.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    // REQ-037 — el nombre lo eligió el usuario: acá decía "O.R.I.O.N." escrito a mano, y
    // quien renombró a su agente leía un nombre que nunca puso.
    empty.textContent = `Todavía no tenés ningún flujo. Pedíselo a ${nombreDelAgente()} hablando.`;
    list.appendChild(empty);
    return;
  }

  for (const flujo of flujos) list.appendChild(buildFlowCard(flujo));
}

function buildFlowCard(flujo) {
  const card = document.createElement("div");
  card.className = "flow-card";
  card.dataset.flowId = String(flujo.id);

  card.appendChild(buildFlowHeader(flujo));

  const pasos = document.createElement("ol");
  pasos.className = "flow-steps";
  flujo.pasos.forEach((paso, indice) => {
    pasos.appendChild(buildStep(flujo, paso, indice));
  });
  card.appendChild(pasos);

  if (flujo.motivo) {
    const motivo = document.createElement("div");
    motivo.className = "flow-reason";
    motivo.textContent = flujo.motivo;
    card.appendChild(motivo);
  }

  card.appendChild(buildFlowActions(flujo));
  return card;
}

function buildFlowHeader(flujo) {
  const header = document.createElement("div");
  header.className = "flow-card-header";

  const nombre = document.createElement("span");
  nombre.className = "flow-name";
  nombre.textContent = flujo.nombre;

  const estado = document.createElement("span");
  estado.className = `flow-state flow-state-${flujo.estado}`;
  estado.textContent = ESTADO_ETIQUETA[flujo.estado] || flujo.estado;

  header.append(nombre, estado);

  if (flujo.horario) {
    const horario = document.createElement("span");
    horario.className = "flow-schedule";
    horario.textContent = flujo.horario;
    horario.title = "Se ejecuta solo con este horario";
    header.appendChild(horario);
  }
  return header;
}

function buildStep(flujo, paso, indice) {
  const item = document.createElement("li");
  item.className = `flow-step flow-step-${paso.estado}`;

  const cuerpo = document.createElement("div");
  cuerpo.className = "flow-step-body";

  const accion = document.createElement("span");
  accion.className = "flow-step-action";
  accion.textContent = paso.accion;
  cuerpo.appendChild(accion);

  if (paso.condicion) {
    const condicion = document.createElement("span");
    condicion.className = "flow-step-cond";
    condicion.textContent = paso.condicion;
    cuerpo.appendChild(condicion);
  }
  if (paso.resultado) {
    const resultado = document.createElement("span");
    resultado.className = "flow-step-result";
    resultado.textContent = paso.resultado;
    cuerpo.appendChild(resultado);
  }
  item.appendChild(cuerpo);

  // Quitar un paso solo se ofrece cuando Python dice que se puede: editar un flujo a medio
  // correr desalinearía lo ya hecho con la lista de pasos.
  if (flujo.editable && flujo.pasos.length > 1) {
    const quitar = document.createElement("button");
    quitar.type = "button";
    quitar.className = "flow-step-remove";
    quitar.appendChild(icon("close", "ic-sm"));
    quitar.setAttribute("aria-label", `Quitar el paso ${indice + 1}: ${paso.accion}`);
    quitar.addEventListener("click", () => {
      quitar.disabled = true;
      removeFlowStep(flujo.id, indice);
    });
    item.appendChild(quitar);
  }
  return item;
}

function buildFlowActions(flujo) {
  const acciones = document.createElement("div");
  acciones.className = "flow-actions";

  if (!flujo.terminado) {
    const etiqueta = flujo.estado === "esperando" ? "Retomar" : "Ejecutar";
    acciones.appendChild(boton(etiqueta, "panel-item-btn", () => runFlow(flujo.id)));
    acciones.appendChild(boton("Cancelar", "panel-item-btn", () => cancelFlow(flujo.id)));
  } else {
    acciones.appendChild(boton("Ejecutar de nuevo", "panel-item-btn", () => runFlow(flujo.id)));
  }
  acciones.appendChild(
    boton("Borrar", "panel-item-btn panel-item-btn-danger", () => requestDeleteFlow(flujo.id)),
  );
  return acciones;
}

function boton(texto, clase, alHacerClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = clase;
  b.textContent = texto;
  b.addEventListener("click", alHacerClick);
  return b;
}
