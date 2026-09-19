// ui/webview/frontend/js/marca.js
// REQ-052 — la marca del agente (los tres anillos entrelazados y el nodo central) dentro
// de la propia interfaz: al lado del nombre en la barra superior, en la pantalla vacía y
// en el centro del Mapa de conexiones.
//
// Hasta ahora la marca vivía solo en el icono de la app (`ui/webview/app_icon.py`,
// REQ-041) y la interfaz la representaba con la inicial del agente en un cuadrado. Acá
// se dibuja la misma geometría —los mismos números del canvas aprobado— como SVG inline,
// con degradado según el tema (metálico claro sobre oscuro, y al revés) y, donde tiene
// sentido, con los anillos girando despacio.
//
// La geometría de abajo es una COPIA de las constantes de `app_icon.py` (`_RINGS`,
// `_RING_R`, `_RING_DASHARRAY`, `_NODE_CENTER`). `tests/test_marca_webview.py` compara
// ambas para que no se separen: si alguien ajusta la marca en un lado, el test lo dice.
//
// Se arma con `createElementNS` (nunca `innerHTML`, §10.1 de REQ-015): un `<svg>` creado
// con `createElement` queda en el namespace HTML y el navegador no lo pinta. El degradado
// va en `<defs>` DENTRO de cada `<svg>` y no en el sprite oculto de `index.html`: un
// `<linearGradient>` referenciado desde otro documento SVG a través de `<use>` no siempre
// se resuelve, y el sprite tiene ancho 0.

const SVG_NS = "http://www.w3.org/2000/svg";

/** Anillos `[cx, cy, dashoffset]` en el espacio nativo 200×200 (= `_RINGS`). */
export const ANILLOS = [
  [100.0, 76.0, 0],
  [120.8, 112.0, 96],
  [79.2, 112.0, 192],
];
export const RADIO_ANILLO = 46.0;           // = _RING_R
export const DASHARRAY = "180 30";          // = _RING_DASHARRAY
export const NODO = [100.0, 100.0];         // = _NODE_CENTER
/** Puntos del degradado en el espacio nativo (= `_GRADIENT_DEF`: x1/y1 → x2/y2). */
const DEGRADADO = { x1: 20, y1: 10, x2: 180, y2: 190 };

let _contador = 0;

/**
 * Return la caja real que pintan los anillos, con medio trazo de margen por lado
 * (misma cuenta que `_marca_bbox` en `app_icon.py`).
 */
export function cajaDeLaMarca(trazo) {
  const medio = trazo / 2;
  const xMin = Math.min(...ANILLOS.map(([cx]) => cx - RADIO_ANILLO)) - medio;
  const yMin = Math.min(...ANILLOS.map(([, cy]) => cy - RADIO_ANILLO)) - medio;
  const xMax = Math.max(...ANILLOS.map(([cx]) => cx + RADIO_ANILLO)) + medio;
  const yMax = Math.max(...ANILLOS.map(([, cy]) => cy + RADIO_ANILLO)) + medio;
  return { xMin, yMin, xMax, yMax, ancho: xMax - xMin, alto: yMax - yMin };
}

/**
 * Return un `<svg>` con la marca.
 *
 * @param {object} opciones
 * @param {number} [opciones.tamano=24]   lado en píxeles CSS (la marca es cuadrada).
 * @param {number} [opciones.trazo=3.2]   grosor del anillo en el espacio nativo; a tamaños
 *                                        chicos conviene subirlo (la bandeja usa 8-10).
 * @param {number} [opciones.nodo=8.5]    radio del nodo central en el espacio nativo.
 * @param {boolean} [opciones.animada=false] los anillos giran despacio (CSS, respeta
 *                                        `prefers-reduced-motion`).
 * @param {string} [opciones.clase=""]    clases extra para el `<svg>`.
 * @param {string} [opciones.etiqueta=""] texto accesible; vacío = decorativa
 *                                        (`aria-hidden`).
 */
export function crearMarca({
  tamano = 24, trazo = 3.2, nodo = 8.5, animada = false, clase = "", etiqueta = "",
} = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  const caja = cajaDeLaMarca(trazo);
  // Cuadrada y centrada en la caja real de los anillos: el centro geométrico de la marca
  // está en y≈94, no en 100 (ver `_app_icon_svg`), así que centrar el viewBox nativo la
  // dejaría corrida hacia arriba.
  const lado = Math.max(caja.ancho, caja.alto);
  const x0 = (caja.xMin + caja.xMax) / 2 - lado / 2;
  const y0 = (caja.yMin + caja.yMax) / 2 - lado / 2;
  svg.setAttribute("viewBox", `${x0.toFixed(2)} ${y0.toFixed(2)} ${lado.toFixed(2)} ${lado.toFixed(2)}`);
  svg.setAttribute("width", String(tamano));
  svg.setAttribute("height", String(tamano));
  svg.setAttribute("class", ["marca", animada ? "marca-animada" : "", clase].filter(Boolean).join(" "));
  svg.setAttribute("focusable", "false");
  if (etiqueta) {
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", etiqueta);
  } else {
    svg.setAttribute("aria-hidden", "true");
  }

  const idDegradado = `marca-degradado-${++_contador}`;
  const defs = document.createElementNS(SVG_NS, "defs");
  const degradado = document.createElementNS(SVG_NS, "linearGradient");
  degradado.setAttribute("id", idDegradado);
  degradado.setAttribute("gradientUnits", "userSpaceOnUse");
  for (const [k, v] of Object.entries(DEGRADADO)) degradado.setAttribute(k, String(v));
  // Los colores de las paradas los pone CSS (`.marca-parada-N { stop-color }`): así el
  // degradado sigue al tema sin que este módulo conozca ningún hex.
  for (const [n, offset] of [[1, "0%"], [2, "50%"], [3, "100%"]]) {
    const parada = document.createElementNS(SVG_NS, "stop");
    parada.setAttribute("offset", offset);
    parada.setAttribute("class", `marca-parada marca-parada-${n}`);
    degradado.appendChild(parada);
  }
  defs.appendChild(degradado);
  svg.appendChild(defs);

  const trazoUrl = `url(#${idDegradado})`;
  ANILLOS.forEach(([cx, cy, offset], i) => {
    const anillo = document.createElementNS(SVG_NS, "circle");
    anillo.setAttribute("class", `marca-anillo marca-anillo-${i + 1}`);
    anillo.setAttribute("cx", String(cx));
    anillo.setAttribute("cy", String(cy));
    anillo.setAttribute("r", String(RADIO_ANILLO));
    anillo.setAttribute("fill", "none");
    anillo.setAttribute("stroke", trazoUrl);
    anillo.setAttribute("stroke-width", String(trazo));
    anillo.setAttribute("stroke-linecap", "round");
    anillo.setAttribute("stroke-dasharray", DASHARRAY);
    anillo.setAttribute("stroke-dashoffset", String(offset));
    svg.appendChild(anillo);
  });

  const centro = document.createElementNS(SVG_NS, "circle");
  centro.setAttribute("class", "marca-nodo");
  centro.setAttribute("cx", String(NODO[0]));
  centro.setAttribute("cy", String(NODO[1]));
  centro.setAttribute("r", String(nodo));
  centro.setAttribute("fill", trazoUrl);
  svg.appendChild(centro);

  return svg;
}

/**
 * Pone la marca dentro de `contenedor` (vaciándolo antes). Idempotente: sirve para
 * repintar sin acumular SVGs.
 */
export function montarMarca(contenedor, opciones) {
  if (!contenedor) return null;
  contenedor.replaceChildren();
  const marca = crearMarca(opciones);
  contenedor.appendChild(marca);
  return marca;
}
