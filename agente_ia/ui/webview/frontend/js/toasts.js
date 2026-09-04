// ui/webview/frontend/js/toasts.js
// Avisos visibles. Antes, `error_occurred` del bridge terminaba en un `console.error`: si
// fallaba borrar una conversación, guardar la configuración o cargar un flujo, la pantalla
// no decía nada y parecía que el click no había hecho nada.
//
// Tres niveles y ninguna decisión más: `error` (algo no se pudo hacer), `ok` (algo se
// hizo) e `info` (algo pasó). Se apilan abajo a la derecha, se van solos, y el de error
// dura más porque suele traer algo que leer.
//
// Todo el texto entra por `textContent`: los mensajes vienen de Python y algunos incluyen
// el nombre de un archivo o el motivo de un error, que no es contenido de confianza
// (regla de §10.1).

import { icon } from "./icons.js";

const DURACION = { error: 9000, ok: 4000, info: 6000 };
const MAX_VISIBLES = 4;

const ICONO = { error: "alerta", ok: "check", info: "info" };

function contenedor() {
  let host = document.getElementById("toast-host");
  if (host === null) {
    host = document.createElement("div");
    host.id = "toast-host";
    host.setAttribute("role", "status");
    host.setAttribute("aria-live", "polite");
    document.body.appendChild(host);
  }
  return host;
}

export function mostrarAviso(nivel, mensaje) {
  const texto = (mensaje || "").trim();
  if (!texto) return;
  const tipo = DURACION[nivel] ? nivel : "info";

  const host = contenedor();
  // Más de cuatro avisos a la vez dejan de ser información y pasan a ser una pared: se
  // van los más viejos, que ya tuvieron su momento.
  while (host.children.length >= MAX_VISIBLES) {
    host.firstElementChild.remove();
  }

  const aviso = document.createElement("div");
  aviso.className = `toast toast-${tipo}`;
  aviso.appendChild(icon(ICONO[tipo], "ic-sm"));

  const cuerpo = document.createElement("span");
  cuerpo.className = "toast-text";
  cuerpo.textContent = texto;      // §10.1 — nunca innerHTML
  aviso.appendChild(cuerpo);

  const cerrar = document.createElement("button");
  cerrar.type = "button";
  cerrar.className = "toast-close";
  cerrar.setAttribute("aria-label", "Cerrar el aviso");
  cerrar.appendChild(icon("close", "ic-sm"));
  cerrar.addEventListener("click", () => aviso.remove());
  aviso.appendChild(cerrar);

  host.appendChild(aviso);

  const temporizador = setTimeout(() => aviso.remove(), DURACION[tipo]);
  // Si el usuario está leyendo el aviso, no se le va de abajo del mouse.
  aviso.addEventListener("mouseenter", () => clearTimeout(temporizador));
  aviso.addEventListener("mouseleave", () => setTimeout(() => aviso.remove(), 1500));
}

export function initToasts() {
  contenedor();
}
