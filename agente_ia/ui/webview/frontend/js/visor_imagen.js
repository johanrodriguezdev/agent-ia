// ui/webview/frontend/js/visor_imagen.js
// REQ-054 — ver una imagen del chat a tamaño completo.
//
// La burbuja muestra una miniatura; un click la abre sobre un fondo oscurecido, centrada
// y sin recortar. Click fuera, Escape o el botón la cierran. No hay zoom ni galería: es
// una captura que se quiere mirar bien un momento, no un visor de fotos.
//
// La fuente de la imagen es siempre un `data:` URL que armó Python (`core/imagenes.py`);
// se asigna por la propiedad `src`, nunca por innerHTML (§10.1).

import { icon } from "./icons.js";
import { requestImage } from "./bridge_client.js";

let _visor = null;
//: La ruta de la imagen que el visor tiene abierta: la respuesta del bridge (`image_loaded`)
//: solo se aplica si sigue siendo esa.
let _rutaAbierta = "";

function construir() {
  const visor = document.createElement("div");
  visor.className = "visor-imagen";
  visor.hidden = true;
  visor.setAttribute("role", "dialog");
  visor.setAttribute("aria-label", "Imagen a tamaño completo");

  const cerrar = document.createElement("button");
  cerrar.type = "button";
  cerrar.className = "visor-imagen-cerrar";
  cerrar.title = "Cerrar";
  cerrar.setAttribute("aria-label", "Cerrar");
  cerrar.appendChild(icon("close", "ic-sm"));
  cerrar.addEventListener("click", cerrarVisor);
  visor.appendChild(cerrar);

  const img = document.createElement("img");
  img.className = "visor-imagen-img";
  img.alt = "";
  // El click sobre la imagen no la cierra: se puede querer copiarla con el menú contextual.
  img.addEventListener("click", (evt) => evt.stopPropagation());
  visor.appendChild(img);

  const pie = document.createElement("div");
  pie.className = "visor-imagen-pie";
  visor.appendChild(pie);

  visor.addEventListener("click", cerrarVisor);
  document.body.appendChild(visor);
  return visor;
}

/** Abre el visor con la miniatura que ya está en pantalla y, si hay ruta, le pide al bridge
 *  la imagen entera: la miniatura se ve al instante y la nítida la reemplaza al llegar. */
export function abrirVisor(dataUrl, nombre, ruta) {
  if (!dataUrl || !dataUrl.startsWith("data:image/")) return;
  if (_visor === null) _visor = construir();
  _visor.querySelector(".visor-imagen-img").src = dataUrl;
  _visor.querySelector(".visor-imagen-pie").textContent = nombre || "";
  _visor.hidden = false;
  // Un frame después para que la transición de opacidad arranque desde el estado oculto.
  requestAnimationFrame(() => _visor.classList.add("abierto"));
  document.addEventListener("keydown", _alTeclear);
  _rutaAbierta = ruta || "";
  if (_rutaAbierta) requestImage(_rutaAbierta);
}

/** `image_loaded` del bridge: la imagen entera de `ruta`. Se ignora si el visor ya se
 *  cerró o abrió otra. */
export function ponerImagenCompleta(ruta, dataUrl) {
  if (!hayVisorAbierto() || !ruta || ruta !== _rutaAbierta) return;
  if (!dataUrl || !dataUrl.startsWith("data:image/")) return;
  _visor.querySelector(".visor-imagen-img").src = dataUrl;
}

export function cerrarVisor() {
  if (_visor === null || _visor.hidden) return;
  _visor.classList.remove("abierto");
  _visor.hidden = true;
  _visor.querySelector(".visor-imagen-img").removeAttribute("src");
  _rutaAbierta = "";
  document.removeEventListener("keydown", _alTeclear);
}

export function hayVisorAbierto() {
  return _visor !== null && !_visor.hidden;
}

function _alTeclear(evt) {
  if (evt.key === "Escape") {
    evt.preventDefault();
    cerrarVisor();
  }
}
