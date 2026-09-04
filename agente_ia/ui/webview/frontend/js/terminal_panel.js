// ui/webview/frontend/js/terminal_panel.js
// Terminales embebidas: cajón inferior con shells reales (ConPTY en Windows, PTY en
// Linux/macOS) del otro lado, en pestañas.
//
// Este módulo NO interpreta nada de lo que sale del shell. Recibe el flujo crudo con las
// secuencias ANSI y se lo pasa entero a xterm.js, que es quien sabe pintar colores, mover
// el cursor y redibujar una línea. Lo mismo al revés: `onData` entrega las teclas tal cual
// (Tab, Ctrl+C, flechas) y van derecho a la PTY.
//
// La lista de pestañas la manda Python (`terminal_tabs`) y acá se reconcilia: se monta lo
// que falta y se desmonta lo que ya no está. Así da igual quién abrió la sesión —el
// usuario con el "+" o el agente ejecutando un comando—, la pantalla siempre muestra las
// shells que de verdad existen.
//
// Ninguna pestaña se abre sola: `terminalOpen()`/`terminalNew()` disparan la confirmación
// 🟡 del lado Python (`terminal_open`), y hasta que no llega el estado "abierta" acá no se
// monta nada.

/* global Terminal, FitAddon, SearchAddon */

import {
  terminalOpen, terminalNew, terminalInput, terminalResize,
  terminalFocus, terminalClose, terminalCloseAll,
} from "./bridge_client.js";
import { icon } from "./icons.js";

const MIN_HEIGHT = 140;
const DEFAULT_HEIGHT = 300;

// Salida que llega antes de que su xterm esté montado. No es hipotético: el hilo lector de
// la PTY empieza a emitir en cuanto arranca el shell, y el aviso de "abierta" lo emite otro
// hilo — Qt garantiza el orden dentro de un mismo hilo, no entre dos. Sin este buffer se
// perdería el banner y el primer prompt, que es justo lo primero que el usuario mira.
const MAX_PENDIENTE = 40000;

/** id de sesión -> { term, fit, host } */
const _sesiones = new Map();
/** id de sesión -> salida que llegó antes de montar */
const _pendientes = new Map();
let _activa = null;

function $(id) {
  return document.getElementById(id);
}

/** Colores de xterm tomados de la paleta del tema (css/theme.css), para que la terminal
 *  no sea un rectángulo ajeno pegado en la ventana. Los 16 ANSI se declaran a mano: los
 *  que trae xterm por defecto están pensados para fondo oscuro y sobre el tema claro el
 *  amarillo y el cyan quedan ilegibles. */
function temaXterm() {
  const css = getComputedStyle(document.documentElement);
  const v = (nombre) => css.getPropertyValue(nombre).trim();
  const oscuro = (document.documentElement.dataset.theme || "light") === "dark";

  const ansiOscuro = {
    black: "#3b4048", red: "#f85149", green: "#3fb950", yellow: "#d29922",
    blue: "#58a6ff", magenta: "#bc8cff", cyan: "#39c5cf", white: "#b1bac4",
    brightBlack: "#6e7681", brightRed: "#ff7b72", brightGreen: "#56d364",
    brightYellow: "#e3b341", brightBlue: "#79c0ff", brightMagenta: "#d2a8ff",
    brightCyan: "#56d4dd", brightWhite: "#f0f6fc",
  };
  const ansiClaro = {
    black: "#24292f", red: "#cf222e", green: "#116329", yellow: "#7d4e00",
    blue: "#0969da", magenta: "#8250df", cyan: "#1b7c83", white: "#6e7781",
    brightBlack: "#57606a", brightRed: "#a40e26", brightGreen: "#1a7f37",
    brightYellow: "#633c01", brightBlue: "#0550ae", brightMagenta: "#6639ba",
    brightCyan: "#3192aa", brightWhite: "#24292f",
  };

  return Object.assign(
    {
      background: v("--bg-primary") || "#0c0d0f",
      foreground: v("--text-primary") || "#e8eaed",
      cursor: v("--text-accent") || "#58a6ff",
      cursorAccent: v("--bg-primary") || "#0c0d0f",
      selectionBackground: v("--bg-hover") || "#1f2226",
    },
    oscuro ? ansiOscuro : ansiClaro,
  );
}

// --------------------------------------------------------------------------- estructura

function construirCajon() {
  const cajon = document.createElement("section");
  cajon.id = "terminal-drawer";
  cajon.style.height = `${DEFAULT_HEIGHT}px`;

  // Manija de arrastre: la terminal es una superficie de trabajo, y cuánto espacio
  // merece depende de lo que se esté corriendo.
  const manija = document.createElement("div");
  manija.id = "terminal-resize-handle";
  manija.setAttribute("role", "separator");
  manija.setAttribute("aria-label", "Redimensionar la terminal");
  manija.addEventListener("mousedown", iniciarArrastre);
  cajon.appendChild(manija);

  const header = document.createElement("div");
  header.id = "terminal-header";

  const titulo = document.createElement("span");
  titulo.className = "terminal-title";
  titulo.appendChild(icon("terminal", "ic-sm"));
  header.appendChild(titulo);

  const tabs = document.createElement("div");
  tabs.id = "terminal-tabs";
  tabs.setAttribute("role", "tablist");
  header.appendChild(tabs);

  const nueva = document.createElement("button");
  nueva.type = "button";
  nueva.id = "terminal-new-tab";
  nueva.className = "icon-btn";
  nueva.setAttribute("aria-label", "Nueva terminal");
  nueva.title = "Nueva terminal";
  nueva.appendChild(icon("plus", "ic-sm"));
  nueva.addEventListener("click", () => terminalNew());
  header.appendChild(nueva);

  const estado = document.createElement("span");
  estado.id = "terminal-status";
  header.appendChild(estado);

  // Buscar dentro de lo que ya salió por pantalla: con 5000 líneas de scrollback,
  // encontrar el error de hace tres comandos a fuerza de rueda del mouse no es viable.
  const buscador = document.createElement("input");
  buscador.type = "search";
  buscador.id = "terminal-search";
  buscador.placeholder = "Buscar…";
  buscador.setAttribute("aria-label", "Buscar en la terminal");
  buscador.addEventListener("keydown", (evt) => {
    evt.stopPropagation();     // la terminal no tiene que recibir lo que se teclea acá
    const sesion = _sesiones.get(_activa);
    if (!sesion || !sesion.search) return;
    if (evt.key === "Enter") {
      // Shift+Enter va hacia atrás, como en cualquier buscador.
      if (evt.shiftKey) sesion.search.findPrevious(buscador.value);
      else sesion.search.findNext(buscador.value);
    }
    if (evt.key === "Escape") {
      buscador.value = "";
      sesion.search.clearDecorations();
      sesion.term.focus();
    }
  });
  header.appendChild(buscador);

  const cerrar = document.createElement("button");
  cerrar.type = "button";
  cerrar.id = "terminal-close-panel";
  cerrar.className = "icon-btn";
  cerrar.setAttribute("aria-label", "Cerrar la terminal");
  cerrar.title = "Cerrar la terminal (termina las sesiones)";
  cerrar.appendChild(icon("close", "ic-sm"));
  cerrar.addEventListener("click", cerrarPanel);
  header.appendChild(cerrar);

  cajon.appendChild(header);

  const hosts = document.createElement("div");
  hosts.id = "terminal-hosts";
  cajon.appendChild(hosts);

  $("main-column").insertBefore(cajon, $("composer"));
  const btn = $("terminal-btn");
  if (btn) btn.classList.add("active");
  return cajon;
}

function iniciarArrastre(evtInicial) {
  evtInicial.preventDefault();
  const cajon = $("terminal-drawer");
  const alturaInicial = cajon.getBoundingClientRect().height;
  const yInicial = evtInicial.clientY;
  const maxAltura = Math.max(MIN_HEIGHT, window.innerHeight - 220);

  function mover(evt) {
    const alto = Math.min(maxAltura, Math.max(MIN_HEIGHT, alturaInicial + (yInicial - evt.clientY)));
    cajon.style.height = `${alto}px`;
    ajustarActiva();
  }
  function soltar() {
    document.removeEventListener("mousemove", mover);
    document.removeEventListener("mouseup", soltar);
    document.body.classList.remove("resizing-terminal");
  }
  document.body.classList.add("resizing-terminal");
  document.addEventListener("mousemove", mover);
  document.addEventListener("mouseup", soltar);
}

/** Recalcula filas/columnas y se las informa a la PTY: sin esto el shell sigue creyendo
 *  que la consola mide 120×30 y parte las líneas donde no corresponde. Solo tiene sentido
 *  sobre la pestaña visible — las ocultas miden 0 y `fit()` daría cualquier cosa. */
function ajustarActiva() {
  const sesion = _sesiones.get(_activa);
  if (!sesion) return;
  try {
    sesion.fit.fit();
    terminalResize(_activa, sesion.term.cols, sesion.term.rows);
  } catch (e) {
    // Pasa si el cajón todavía no tiene tamaño (primer frame): no es un error real.
    console.debug("[terminal] fit diferido:", e);
  }
}

function montarSesion(sessionId) {
  if (_sesiones.has(sessionId)) return;
  if ($("terminal-drawer") === null) construirCajon();

  const host = document.createElement("div");
  host.className = "terminal-host";
  host.dataset.sessionId = sessionId;
  $("terminal-hosts").appendChild(host);

  const FitCtor = (FitAddon && FitAddon.FitAddon) || FitAddon;
  const term = new Terminal({
    fontFamily: '"Cascadia Code", Consolas, "JetBrains Mono", monospace',
    fontSize: 13,
    lineHeight: 1.2,
    cursorBlink: true,
    scrollback: 5000,
    allowProposedApi: false,
    theme: temaXterm(),
  });
  const fit = new FitCtor();
  term.loadAddon(fit);

  const SearchCtor = (typeof SearchAddon !== "undefined")
    ? (SearchAddon.SearchAddon || SearchAddon) : null;
  const search = SearchCtor ? new SearchCtor() : null;
  if (search) term.loadAddon(search);

  term.open(host);

  // Ctrl+C en una terminal manda la señal de interrupción, así que copiar es Ctrl+Shift+C
  // (lo mismo que hace cualquier terminal de Linux y la de Windows). Devolver `false`
  // impide que la tecla siga viaje hacia la PTY.
  term.attachCustomKeyEventHandler((evt) => {
    if (evt.type !== "keydown" || !evt.ctrlKey || !evt.shiftKey) return true;
    const tecla = evt.key.toLowerCase();
    if (tecla === "c") {
      const seleccion = term.getSelection();
      if (seleccion) {
        navigator.clipboard.writeText(seleccion).catch((e) => console.debug("[terminal] copiar:", e));
      }
      return false;
    }
    if (tecla === "v") {
      navigator.clipboard.readText()
        .then((texto) => { if (texto) terminalInput(sessionId, texto); })
        .catch((e) => console.debug("[terminal] pegar:", e));
      return false;
    }
    if (tecla === "f") {
      const buscador = $("terminal-search");
      if (buscador) { buscador.focus(); buscador.select(); }
      return false;
    }
    return true;
  });

  // Todo lo que se teclea va crudo a la PTY. No se interpreta ni se valida acá: el
  // registro de lo que se ejecutó lo lleva Python, comando por comando, en la auditoría.
  term.onData((data) => terminalInput(sessionId, data));

  _sesiones.set(sessionId, { term, fit, host, search });

  const pendiente = _pendientes.get(sessionId);
  if (pendiente) {
    term.write(pendiente);
    _pendientes.delete(sessionId);
  }
}

function desmontarSesion(sessionId) {
  const sesion = _sesiones.get(sessionId);
  if (!sesion) return;
  sesion.term.dispose();
  sesion.host.remove();
  _sesiones.delete(sessionId);
  _pendientes.delete(sessionId);
  if (_activa === sessionId) _activa = null;
}

function activarSesion(sessionId) {
  if (!_sesiones.has(sessionId)) return;
  _activa = sessionId;
  for (const [id, sesion] of _sesiones) {
    sesion.host.classList.toggle("visible", id === sessionId);
  }
  for (const boton of document.querySelectorAll(".terminal-tab")) {
    boton.classList.toggle("active", boton.dataset.sessionId === sessionId);
    boton.setAttribute("aria-selected", boton.dataset.sessionId === sessionId ? "true" : "false");
  }
  requestAnimationFrame(() => {
    // Se vuelve a buscar: entre este frame y el anterior la pestaña pudo cerrarse (el
    // shell terminó con `exit`, o el agente la cerró), y enfocar un xterm ya destruido
    // tira una excepción que dejaría muda a la siguiente.
    const actual = _sesiones.get(sessionId);
    if (!actual) return;
    ajustarActiva();
    actual.term.focus();
  });
}

function setEstado(texto) {
  const el = $("terminal-status");
  if (el) el.textContent = texto || "";
}

// --------------------------------------------------------------------------- API pública

export function toggleTerminalPanel() {
  if ($("terminal-drawer") !== null) {
    cerrarPanel();
    return;
  }
  abrirPanel();
}

export function abrirPanel() {
  if ($("terminal-drawer") === null) {
    construirCajon();
    setEstado("esperando confirmación…");
  }
  // Python decide: si ya hay sesiones vivas se reengancha sin preguntar; si no, pide la
  // confirmación 🟡 antes de abrir el primer shell.
  terminalOpen();
}

export function cerrarPanel() {
  const cajon = $("terminal-drawer");
  if (cajon !== null) cajon.remove();
  const btn = $("terminal-btn");
  if (btn) btn.classList.remove("active");

  for (const id of Array.from(_sesiones.keys())) desmontarSesion(id);
  _pendientes.clear();
  _activa = null;

  // Cerrar el panel mata los procesos: no se deja una shell viva sin ventana que la
  // muestre. Cada pestaña tiene su propia ✕ para cerrar solo esa.
  terminalCloseAll();
}

/** Reconciliación: la lista de pestañas que manda Python es la verdad. */
export function renderTerminalTabs(lista) {
  const tabs = $("terminal-tabs");
  if (tabs === null) {
    if (lista.length > 0) construirCajon();
    else return;
  }

  const vivos = new Set(lista.map((t) => t.id));
  for (const id of Array.from(_sesiones.keys())) {
    if (!vivos.has(id)) desmontarSesion(id);
  }
  for (const id of Array.from(_pendientes.keys())) {
    if (!vivos.has(id)) _pendientes.delete(id);
  }

  if (lista.length === 0) {
    // No queda ninguna shell: el cajón no tiene nada que mostrar.
    const cajon = $("terminal-drawer");
    if (cajon !== null) cajon.remove();
    const btn = $("terminal-btn");
    if (btn) btn.classList.remove("active");
    return;
  }

  for (const tab of lista) montarSesion(tab.id);

  const contenedor = $("terminal-tabs");
  contenedor.replaceChildren();
  let activa = null;

  for (const tab of lista) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "terminal-tab";
    boton.dataset.sessionId = tab.id;
    boton.setAttribute("role", "tab");

    const nombre = document.createElement("span");
    nombre.className = "terminal-tab-name";
    // Título y ruta vienen de Python: van por textContent, nunca innerHTML (§10.1).
    nombre.textContent = tab.titulo;
    boton.appendChild(nombre);
    boton.title = tab.cwd;
    boton.addEventListener("click", () => {
      terminalFocus(tab.id);
      activarSesion(tab.id);
    });

    // Con una sola pestaña la ✕ propia sobra: para cerrarla está la del panel.
    if (lista.length > 1) {
      const cerrar = document.createElement("span");
      cerrar.className = "terminal-tab-close";
      cerrar.setAttribute("role", "button");
      cerrar.setAttribute("aria-label", `Cerrar ${tab.titulo}`);
      cerrar.appendChild(icon("close", "ic-sm"));
      cerrar.addEventListener("click", (evt) => {
        evt.stopPropagation();
        terminalClose(tab.id);
      });
      boton.appendChild(cerrar);
    }

    contenedor.appendChild(boton);
    if (tab.activa) activa = tab.id;
  }

  activarSesion(activa || lista[lista.length - 1].id);
  setEstado("");
}

/** Salida cruda de la PTY, con el id de la sesión a la que pertenece. */
export function escribirSalida(sessionId, chunk) {
  const sesion = _sesiones.get(sessionId);
  if (sesion) {
    sesion.term.write(chunk);
    return;
  }
  // Todavía no está montada: se guarda hasta que la pestaña exista. Lo que sobre de
  // sesiones que nunca se montan lo limpia `renderTerminalTabs`.
  const previo = _pendientes.get(sessionId) || "";
  _pendientes.set(sessionId, (previo + chunk).slice(-MAX_PENDIENTE));
}

export function manejarEstadoTerminal(sessionId, estado, detalle) {
  if (estado === "abierta") {
    // El agente pudo abrirla con el panel cerrado: entonces se abre solo, porque el
    // usuario tiene que ver lo que se está ejecutando en su máquina. El resto del
    // trabajo (montar, pestañas) lo hace `renderTerminalTabs`, que llega enseguida.
    if ($("terminal-drawer") === null) construirCajon();
    montarSesion(sessionId);
    activarSesion(sessionId);
    setEstado(detalle || "");
    return;
  }

  if (estado === "cerrada") {
    desmontarSesion(sessionId);
    return;
  }

  if (estado === "denegada") {
    // El usuario dijo que no: si no queda ninguna sesión, el cajón se va sin haber
    // existido. Dejarlo abierto con un cartel sería insistir con algo ya decidido.
    setEstado("");
    if (_sesiones.size === 0) cerrarPanel();
    return;
  }

  // "error": acá sí hay algo que explicar (falta la dependencia de PTY, no se pudo crear
  // la consola) y el cajón se queda con el motivo a la vista.
  setEstado(detalle || "No se pudo abrir la terminal.");
  if (_sesiones.size === 0 && $("terminal-hosts") !== null) {
    const aviso = document.createElement("p");
    aviso.className = "terminal-aviso";
    aviso.textContent = detalle || "No se pudo abrir la terminal.";
    $("terminal-hosts").replaceChildren(aviso);
  }
}

/** El tema cambia en caliente (theme.js solo mueve `data-theme`): xterm no lee CSS, hay
 *  que pasarle la paleta nueva a mano, a cada pestaña. */
export function refrescarTemaTerminal() {
  const tema = temaXterm();
  for (const sesion of _sesiones.values()) {
    sesion.term.options.theme = tema;
  }
}

// La ventana cambia de tamaño y el cajón con ella: la PTY tiene que enterarse.
window.addEventListener("resize", ajustarActiva);
