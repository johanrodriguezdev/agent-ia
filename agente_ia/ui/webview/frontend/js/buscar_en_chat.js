// ui/webview/frontend/js/buscar_en_chat.js
// REQ-058 — buscar dentro de la conversación abierta (Ctrl+F).
//
// El buscador de la barra lateral (Ctrl+K) encuentra conversaciones; este encuentra un
// texto DENTRO de la que está abierta: una barra flotante arriba del chat, los hallazgos
// resaltados, «3 de 12», Enter/↓ para el siguiente y Shift+Enter/↑ para el anterior.
//
// El resaltado se hace partiendo nodos de texto y envolviendo el trozo en un <mark>
// (`Range.surroundContents`): nunca innerHTML (§10.1 de REQ-015), y al cerrar se
// deshace dejando el DOM como estaba. Ignora mayúsculas y acentos («cafe» encuentra
// «Café»), comparando carácter a carácter para que las posiciones coincidan.

let _barra = null;
let _entrada = null;
let _contador = null;
let _marcas = [];
let _actual = -1;
let _observador = null;
let _reintento = null;

function $(id) {
  return document.getElementById(id);
}

/** Una unidad de texto sin acento ni mayúscula, de la misma longitud (1) que la original:
 *  así las posiciones en el texto plegado son las del nodo real. */
function plegar(unidad) {
  const base = unidad.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const baja = (base[0] || unidad).toLocaleLowerCase();
  return baja[0] || unidad;
}

function plegarTexto(texto) {
  // Unidad a unidad (UTF-16), no por code point: `indexOf` cuenta unidades, y un emoji
  // ocupa dos.
  let salida = "";
  for (let i = 0; i < texto.length; i++) salida += plegar(texto[i]);
  return salida;
}

function nodosDeTexto(raiz) {
  const nodos = [];
  const paseo = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT, {
    acceptNode(nodo) {
      // Ni el texto de los botones (Copiar, Regenerar) ni el de los pasos plegados.
      if (nodo.parentElement.closest("button, .msg-pasos, mark.hallazgo")) {
        return NodeFilter.FILTER_REJECT;
      }
      return nodo.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  let nodo;
  while ((nodo = paseo.nextNode())) nodos.push(nodo);
  return nodos;
}

function quitarMarcas() {
  for (const marca of _marcas) {
    const padre = marca.parentNode;
    if (!padre) continue;
    while (marca.firstChild) padre.insertBefore(marca.firstChild, marca);
    padre.removeChild(marca);
    padre.normalize();
  }
  _marcas = [];
  _actual = -1;
  descartarMutacionesPropias();
}

/** Las marcas que pone y quita la propia búsqueda también son mutaciones del chat: se
 *  descartan del observador, o cada búsqueda dispararía otra, sin fin. */
function descartarMutacionesPropias() {
  if (_observador) _observador.takeRecords();
}

function marcar(nodo, inicio, fin) {
  const rango = document.createRange();
  rango.setStart(nodo, inicio);
  rango.setEnd(nodo, fin);
  const marca = document.createElement("mark");
  marca.className = "hallazgo";
  rango.surroundContents(marca);
  return marca;
}

function buscar() {
  quitarMarcas();
  const consulta = plegarTexto(_entrada.value);
  if (!consulta.trim()) {
    actualizarContador();
    return;
  }
  for (const nodo of nodosDeTexto($("messages"))) {
    // Se recorren los hallazgos de atrás hacia adelante: envolver uno parte el nodo, y
    // así los índices anteriores siguen valiendo.
    const texto = plegarTexto(nodo.nodeValue);
    const posiciones = [];
    let desde = texto.indexOf(consulta);
    while (desde !== -1) {
      posiciones.push(desde);
      desde = texto.indexOf(consulta, desde + consulta.length);
    }
    const nuevas = [];
    for (let i = posiciones.length - 1; i >= 0; i--) {
      nuevas.push(marcar(nodo, posiciones[i], posiciones[i] + consulta.length));
    }
    _marcas.push(...nuevas.reverse());
  }
  if (_marcas.length) irA(0);
  actualizarContador();
  descartarMutacionesPropias();
}

function irA(indice) {
  if (!_marcas.length) return;
  if (_actual >= 0 && _marcas[_actual]) _marcas[_actual].classList.remove("hallazgo-actual");
  _actual = ((indice % _marcas.length) + _marcas.length) % _marcas.length;
  const marca = _marcas[_actual];
  marca.classList.add("hallazgo-actual");
  // Un hallazgo dentro de una respuesta plegada («Ver más») no se vería: se despliega.
  const burbuja = marca.closest(".bubble.clamped");
  if (burbuja) {
    burbuja.classList.remove("clamped");
    const boton = burbuja.parentElement.querySelector(".bubble-expand-btn");
    if (boton) boton.remove();
  }
  marca.scrollIntoView({ block: "center", behavior: "smooth" });
  actualizarContador();
}

function actualizarContador() {
  if (!_entrada.value.trim()) {
    _contador.textContent = "";
    _barra.classList.remove("sin-resultados");
    return;
  }
  _contador.textContent = _marcas.length ? `${_actual + 1} de ${_marcas.length}` : "Sin resultados";
  _barra.classList.toggle("sin-resultados", !_marcas.length);
}

/** Con el chat cambiando (llega una respuesta, se carga otro historial) la búsqueda se
 *  rehace, con una pausa corta para no repetirla por cada nodo insertado. */
function vigilarCambios() {
  if (_observador) return;
  _observador = new MutationObserver(() => {
    if (_barra.hidden) return;
    clearTimeout(_reintento);
    _reintento = setTimeout(() => {
      if (_entrada.value.trim()) buscar();
    }, 150);
  });
  _observador.observe($("messages"), { childList: true, subtree: true, characterData: true });
}

export function abrirBusquedaEnChat() {
  if (!_barra) return;
  _barra.hidden = false;
  // El chat baja lo que mide la barra: que no tape el primer mensaje (chat.css).
  document.body.classList.add("buscando-en-chat");
  vigilarCambios();
  _entrada.focus();
  _entrada.select();
  if (_entrada.value.trim()) buscar();
}

export function cerrarBusquedaEnChat() {
  if (!_barra || _barra.hidden) return;
  quitarMarcas();
  _barra.hidden = true;
  document.body.classList.remove("buscando-en-chat");
  _barra.classList.remove("sin-resultados");
  _contador.textContent = "";
  const composer = $("composer-input");
  if (composer) composer.focus();
}

export function hayBusquedaEnChatAbierta() {
  return _barra !== null && !_barra.hidden;
}

export function initBuscarEnChat() {
  _barra = $("buscar-en-chat");
  _entrada = $("buscar-en-chat-input");
  _contador = $("buscar-en-chat-contador");
  if (!_barra || !_entrada || !_contador) return;

  _entrada.addEventListener("input", buscar);
  _entrada.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter" || evt.key === "ArrowDown") {
      evt.preventDefault();
      irA(_actual + (evt.shiftKey && evt.key === "Enter" ? -1 : 1));
    } else if (evt.key === "ArrowUp") {
      evt.preventDefault();
      irA(_actual - 1);
    } else if (evt.key === "Escape") {
      evt.preventDefault();
      evt.stopPropagation();
      cerrarBusquedaEnChat();
    }
  });
  $("buscar-en-chat-anterior").addEventListener("click", () => irA(_actual - 1));
  $("buscar-en-chat-siguiente").addEventListener("click", () => irA(_actual + 1));
  $("buscar-en-chat-cerrar").addEventListener("click", cerrarBusquedaEnChat);

  // Ctrl+F abre (también con el foco en el cuadro de escribir: es una combinación, no una
  // tecla suelta, así que no pisa nada). Con el foco en la terminal no: ahí Ctrl+F es
  // del shell.
  document.addEventListener("keydown", (evt) => {
    if (!(evt.ctrlKey || evt.metaKey) || (evt.key !== "f" && evt.key !== "F")) return;
    const activo = document.activeElement;
    if (activo && activo.closest("#terminal-drawer")) return;
    evt.preventDefault();
    abrirBusquedaEnChat();
  });
}
