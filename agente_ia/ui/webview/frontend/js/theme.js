// ui/webview/frontend/js/theme.js
// REQ-015/CA-33, CA-37, CA-38 — `set_theme()` solo cambia `data-theme` del `<html>`, sin
// recarga de página ni reinicio (CA-37). El cambio visual es 100% CSS (`transition` en
// theme.css) — este módulo solo mueve el atributo y activa la hoja de Pygments correcta.

import { setTheme } from "./bridge_client.js";

function $(id) {
  return document.getElementById(id);
}

function syncPygmentsLink(themeName) {
  $("pygments-dark-link").disabled = themeName !== "dark";
  $("pygments-light-link").disabled = themeName !== "light";
}

function syncToggleIcon(themeName) {
  const btn = $("theme-toggle-btn");
  const label = themeName === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro";
  // El botón muestra el icono del tema al que va a cambiar, igual que su etiqueta: en
  // oscuro se ve el sol (click = aclarar), en claro la luna. Solo se reapunta el `<use>`
  // del sprite, no se reconstruye el nodo.
  $("theme-toggle-icon").setAttribute("href", themeName === "dark" ? "#ic-sun" : "#ic-moon");
  btn.setAttribute("aria-label", label);
  btn.title = label;
}

export function applyTheme(themeName) {
  document.documentElement.dataset.theme = themeName;
  syncPygmentsLink(themeName);
  syncToggleIcon(themeName);
}

export function initTheme() {
  // CA-38: DEFAULT_THEME = "light" — index.html ya trae data-theme="light" hasta que
  // llegue el theme_changed real (disparado por request_initial_state()).
  applyTheme(document.documentElement.dataset.theme || "light");

  $("theme-toggle-btn").addEventListener("click", () => {
    const current = document.documentElement.dataset.theme || "light";
    setTheme(current === "dark" ? "light" : "dark");
  });
}
