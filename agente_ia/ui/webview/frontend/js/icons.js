// ui/webview/frontend/js/icons.js
// Rediseño — acceso a los iconos del sprite desde JS.
//
// Los iconos que están en `index.html` se escriben directo con `<use href="#ic-...">`.
// Este módulo es para los que crea el JS (borrar conversación, cerrar un panel, ejecutar
// un flujo): devuelve un `<svg>` ya listo, con la clase que css/icons.css espera.
//
// Se construye con `createElementNS` a propósito: un `<svg>` creado con
// `document.createElement()` queda en el namespace HTML y el navegador no lo dibuja, y
// armarlo con `innerHTML` está prohibido en estos archivos por la regla de §10.1
// (ver tests/test_webview_safe_dom_insertion.py).

const SVG_NS = "http://www.w3.org/2000/svg";

export function icon(name, extraClass) {
  const svg = document.createElementNS(SVG_NS, "svg");
  // `className` es de solo lectura en SVG (SVGAnimatedString): va por setAttribute.
  svg.setAttribute("class", extraClass ? `ic ${extraClass}` : "ic");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#ic-${name}`);
  svg.appendChild(use);

  return svg;
}
