// ui/webview/frontend/js/shortcuts.js
// Atajos de teclado. Una app de escritorio en la que todo se hace con el mouse se siente
// como una página web metida en una ventana.
//
// Reglas que sigue todo atajo de acá:
//
// - **Nunca pisa lo que estás escribiendo.** Si el foco está en un campo de texto o en la
//   terminal, los atajos de una sola tecla no corren: en la terminal, `Esc` es una tecla
//   que el shell necesita, no un atajo de la app.
// - **Nunca dispara una acción destructiva.** Todos abren, cierran o enfocan algo. Borrar,
//   ejecutar o confirmar sigue necesitando un click deliberado.
//
// `Ctrl+K` (buscar) vive en sidebar.js, junto al buscador que enfoca.

const CAMPOS_DE_TEXTO = new Set(["INPUT", "TEXTAREA"]);

function escribiendo() {
  const activo = document.activeElement;
  if (!activo) return false;
  if (CAMPOS_DE_TEXTO.has(activo.tagName)) return true;
  if (activo.isContentEditable) return true;
  // xterm.js pone el foco en un textarea propio dentro del cajón de la terminal.
  return activo.closest("#terminal-drawer") !== null;
}

function hayModalAbierto() {
  return document.querySelector(".modal-overlay") !== null;
}

export function initShortcuts({ alternarTerminal, chatNuevo }) {
  document.addEventListener("keydown", (evt) => {
    const conCtrl = evt.ctrlKey || evt.metaKey;

    // Ctrl+` — mostrar/ocultar la terminal. Es el atajo que ya tiene todo el mundo en la
    // cabeza por VS Code, y funciona incluso con el foco dentro de la terminal (es la
    // forma de salir de ahí sin buscar el mouse).
    if (conCtrl && (evt.key === "`" || evt.code === "Backquote")) {
      evt.preventDefault();
      alternarTerminal();
      return;
    }

    if (conCtrl && (evt.key === "n" || evt.key === "N")) {
      evt.preventDefault();
      chatNuevo();
      return;
    }

    if (evt.key === "Escape") {
      // Con un modal abierto, Escape es del modal (confirm_modal.js), no de acá.
      if (hayModalAbierto() || escribiendo()) return;
      evt.preventDefault();
      const entrada = document.getElementById("composer-input");
      if (entrada) entrada.focus();
    }
  });
}
