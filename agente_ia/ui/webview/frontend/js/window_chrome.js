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

  document.getElementById("drag-region").addEventListener("mousedown", (evt) => {
    if (evt.button !== 0) return;
    startMove();
  });

  document.getElementById("btn-minimize").addEventListener("click", windowMinimize);
  document.getElementById("btn-maximize").addEventListener("click", windowToggleMaximize);
  document.getElementById("btn-close").addEventListener("click", windowClose);
}
