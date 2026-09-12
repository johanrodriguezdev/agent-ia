// ui/webview/frontend/js/window_chrome.js
// REQ-015/CA-01, CA-02 — resize/move/min/max/close vía bridge, usando las APIs nativas
// del sistema operativo (`startSystemResize()`/`startSystemMove()` de `QWindow`, Qt
// 5.15+) — nunca una reimplementación manual de arrastre con mouse-tracking (arquitectura-015.md §4.1).

import {
  startMove, startResize, windowClose, windowMinimize, windowToggleMaximize,
} from "./bridge_client.js";

const EDGE_THRESHOLD_PX = 6;

const CURSOR_BY_EDGE = {
  n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
  ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize",
};

function edgeAt(x, y) {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const nearTop = y <= EDGE_THRESHOLD_PX;
  const nearBottom = y >= h - EDGE_THRESHOLD_PX;
  const nearLeft = x <= EDGE_THRESHOLD_PX;
  const nearRight = x >= w - EDGE_THRESHOLD_PX;

  if (nearTop && nearLeft) return "nw";
  if (nearTop && nearRight) return "ne";
  if (nearBottom && nearLeft) return "sw";
  if (nearBottom && nearRight) return "se";
  if (nearTop) return "n";
  if (nearBottom) return "s";
  if (nearLeft) return "w";
  if (nearRight) return "e";
  return null;
}

const ETIQUETAS_AUTONOMIA = {
  proyectos: "AUTONOMÍA: PROYECTOS",
  total: "AUTONOMÍA: TOTAL",
};

export function setAutonomyIndicator(estado) {
  const insignia = document.getElementById("autonomy-badge");
  if (!insignia) return;
  const etiqueta = ETIQUETAS_AUTONOMIA[estado && estado.nivel];
  insignia.hidden = !etiqueta;
  insignia.textContent = etiqueta || "";
  insignia.dataset.nivel = (estado && estado.nivel) || "normal";
  // El `title` dice desde cuándo: con un modo que no expira solo, "encendido desde el
  // martes" es el dato que hace que alguien se acuerde de apagarlo.
  insignia.title = etiqueta
    ? `Modo autonomía encendido desde ${estado.desde || "hace un rato"}`
    : "";
}

export function setMaximizedState(maximized) {
  document.documentElement.dataset.maximized = maximized ? "true" : "false";
}

export function initWindowChrome() {
  document.addEventListener("mousemove", (evt) => {
    const edge = edgeAt(evt.clientX, evt.clientY);
    document.body.style.cursor = edge ? CURSOR_BY_EDGE[edge] : "";
  });

  document.addEventListener("mousedown", (evt) => {
    if (evt.button !== 0) return;
    const edge = edgeAt(evt.clientX, evt.clientY);
    if (edge) {
      startResize(edge);
    }
  });

  // Toda la barra superior arrastra la ventana, MENOS sus zonas interactivas: el
  // buscador, las herramientas y los controles de ventana están marcados con
  // `data-no-drag` en index.html. Sin ese chequeo, un click en el input dispararía
  // `startSystemMove()` y el foco se perdería antes de poder escribir.
  document.getElementById("window-chrome").addEventListener("mousedown", (evt) => {
    if (evt.button !== 0) return;
    if (evt.target.closest("[data-no-drag]")) return;
    // Los 6px de borde de arriba son zona de resize (el listener de `document` de mas
    // arriba ya disparo `startResize`): ahi no se mueve la ventana.
    if (edgeAt(evt.clientX, evt.clientY)) return;
    startMove();
  });

  document.getElementById("btn-minimize").addEventListener("click", windowMinimize);
  document.getElementById("btn-maximize").addEventListener("click", windowToggleMaximize);
  document.getElementById("btn-close").addEventListener("click", windowClose);
}
