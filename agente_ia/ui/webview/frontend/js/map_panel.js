// ui/webview/frontend/js/map_panel.js
// REQ-052 — el Mapa de conexiones: el agente en el centro y, alrededor, todo lo que tiene
// conectado — los modelos con los que responde, los canales por los que se le habla, los
// servidores MCP que le prestan herramientas y los flujos que aprendió.
//
// Es una pantalla para MIRAR, no para configurar: cada nodo dice en qué estado está y,
// al hacerle click, cuenta el detalle. Lo que haya que cambiar se cambia en Configuración
// (o pidiéndoselo al agente); desde el detalle hay un atajo a la sección que corresponde.
//
// Los datos los arma Python (`ui/webview/mapa_conexiones.py`) y llegan por
// `connection_map_loaded`; mientras el panel está abierto se piden de nuevo cada pocos
// segundos, así un servidor que conecta o un bot que arranca se ven sin cerrar y abrir.
//
// Todo el dibujo es SVG armado con `createElementNS`. Los textos que vienen de Python
// (nombres de servidores, de flujos, el destino de un servidor) se insertan SIEMPRE con
// `textContent` (§10.1 de REQ-015): son configuración o comandos dictados, no HTML.

import { requestConnectionMap } from "./bridge_client.js";
import { icon } from "./icons.js";
import { crearMarca } from "./marca.js";
import { openSettingsPanel } from "./settings_panel.js";

const SVG_NS = "http://www.w3.org/2000/svg";

const ANCHO = 900;
const ALTO = 600;
const CENTRO = { x: ANCHO / 2, y: ALTO / 2 };
const RADIO = 182;                // a qué distancia del centro orbitan los nodos
const RADIO_NODO = 19;
const AIRE_ETIQUETA = 33;         // de la órbita a la etiqueta del nodo
const ESCALON_ETIQUETA = 17;      // lo que se aleja una etiqueta de cada dos, arriba y abajo
const AIRE_TITULO_VERTICAL = 76;  // de la órbita al título, en los grupos de arriba y abajo
const AIRE_TITULO_LATERAL = 152;  // ídem a los costados, donde las etiquetas se extienden
//: Dónde queda el centro de cada grupo (mismo orden que GRUPOS): izquierda, arriba,
//: derecha, abajo. En coordenadas de pantalla el ángulo crece en sentido horario.
const CENTRO_DE_GRUPO = [Math.PI, Math.PI * 1.5, 0, Math.PI * 0.5];
const ARCO_MAXIMO = (76 * Math.PI) / 180;    // lo más que se abre un grupo (deja aire al vecino)
const PASO_MAXIMO = (26 * Math.PI) / 180;    // separación entre nodos vecinos, como mucho
const REFRESCO_MS = 5000;
const MAX_POR_GRUPO = 6;          // más que esto se resume en «+N más»

const GRUPOS = [
  { id: "modelos", titulo: "Modelos", icono: "cpu", seccion: "claves",
    vacio: "sin claves" },
  { id: "canales", titulo: "Canales", icono: "message", seccion: "canales",
    vacio: "" },
  { id: "mcp", titulo: "Servidores MCP", icono: "plug", seccion: "mcp",
    vacio: "ninguno todavía" },
  { id: "flujos", titulo: "Flujos", icono: "flows", seccion: null,
    vacio: "ninguno todavía" },
];

const ICONO_DE_CANAL = {
  desktop: "monitor", voice: "mic", telegram: "send", discord: "message", email: "mail",
};

const ETIQUETA_DE_ESTADO = {
  activo: "activo", configurado: "configurado", inactivo: "inactivo", error: "con problema",
};

let _panelOpen = false;
let _temporizador = null;
let _mapa = null;
let _ultimoJson = "";
let _seleccion = null;            // {grupo, id}

export function openMapPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  _seleccion = null;
  renderShell();
  if (_mapa) dibujar();           // lo último que se vio, mientras llega lo nuevo
  requestConnectionMap();
  _temporizador = setInterval(requestConnectionMap, REFRESCO_MS);
}

export function closeMapPanel() {
  _panelOpen = false;
  if (_temporizador) {
    clearInterval(_temporizador);
    _temporizador = null;
  }
  document.getElementById("panel-modal-root").replaceChildren();
}

/** Llega de `connection_map_loaded`. Se repinta solo si algo cambió. */
export function renderConnectionMap(mapa) {
  const json = JSON.stringify(mapa);
  const cambio = json !== _ultimoJson;
  _ultimoJson = json;
  _mapa = mapa;
  if (_panelOpen && cambio) dibujar();
}

// ---------------------------------------------------------------- cascarón del panel

function renderShell() {
  const root = document.getElementById("panel-modal-root");
  root.replaceChildren();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) closeMapPanel(); });

  const box = document.createElement("div");
  box.className = "modal-box modal-box-map";

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Mapa";
  const leyenda = buildLeyenda();
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.appendChild(icon("close", "ic-sm"));
  closeBtn.addEventListener("click", closeMapPanel);
  header.append(title, leyenda, closeBtn);

  const lienzo = document.createElement("div");
  lienzo.id = "map-canvas";
  lienzo.className = "map-canvas";

  const cargando = document.createElement("div");
  cargando.className = "panel-empty map-cargando";
  cargando.textContent = "Mirando qué hay conectado…";
  lienzo.appendChild(cargando);

  const detalle = document.createElement("aside");
  detalle.id = "map-detalle";
  detalle.className = "map-detalle";
  detalle.hidden = true;

  // Lienzo y detalle van lado a lado: al abrir el detalle el mapa se encoge un poco en
  // vez de quedar tapado por la tarjeta.
  const cuerpo = document.createElement("div");
  cuerpo.className = "map-cuerpo";
  cuerpo.append(lienzo, detalle);

  box.append(header, cuerpo);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

function buildLeyenda() {
  const leyenda = document.createElement("div");
  leyenda.className = "map-leyenda";
  for (const estado of ["activo", "configurado", "inactivo", "error"]) {
    const item = document.createElement("span");
    item.className = "map-leyenda-item";
    const punto = document.createElement("span");
    punto.className = `map-punto map-estado-${estado}`;
    const texto = document.createElement("span");
    texto.textContent = ETIQUETA_DE_ESTADO[estado];
    item.append(punto, texto);
    leyenda.appendChild(item);
  }
  return leyenda;
}

// ---------------------------------------------------------------- distribución

/**
 * Reparte los nodos en la órbita: cada grupo tiene su lado fijo (Modelos a la izquierda,
 * Canales arriba, MCP a la derecha, Flujos abajo) y sus nodos se abren en abanico
 * alrededor de ese centro. El paso entre vecinos se achica cuando hay muchos, y las
 * etiquetas alternan entre dos distancias para que dos vecinas no se pisen.
 * Return [{grupo, nodos:[{nodo, angulo, aireEtiqueta}], anguloTitulo, radioTitulo}].
 */
function distribuir(mapa) {
  return GRUPOS.map((g, indice) => {
    const lista = (mapa[g.id] || []).slice();
    const visibles = lista.slice(0, MAX_POR_GRUPO);
    const sobrantes = lista.length - visibles.length;
    if (sobrantes > 0) {
      visibles.push({ id: "__mas__", label: `+${sobrantes} más`, estado: "inactivo",
                      detalle: "hay más de los que entran en el mapa", fantasma: true });
    }
    if (!visibles.length) {
      visibles.push({ id: "__vacio__", label: g.vacio || "ninguno", estado: "inactivo",
                      detalle: "", fantasma: true });
    }

    const centro = CENTRO_DE_GRUPO[indice];
    const lateral = indice % 2 === 0;          // Modelos y MCP: a los costados
    const n = visibles.length;
    const paso = n > 1 ? Math.min(PASO_MAXIMO, ARCO_MAXIMO / (n - 1)) : 0;
    const inicio = centro - paso * (n - 1) / 2;
    const nodos = visibles.map((nodo, i) => ({
      nodo,
      angulo: inicio + paso * i,
      // A los costados las etiquetas se apilan en vertical y no se tocan; arriba y abajo
      // son vecinas horizontales, así que una de cada dos va un escalón más afuera.
      aireEtiqueta: AIRE_ETIQUETA + (!lateral && i % 2 === 1 ? ESCALON_ETIQUETA : 0),
    }));
    return {
      grupo: g, nodos, anguloTitulo: centro,
      radioTitulo: RADIO + (lateral ? AIRE_TITULO_LATERAL : AIRE_TITULO_VERTICAL),
    };
  });
}

function polar(angulo, radio) {
  return { x: CENTRO.x + Math.cos(angulo) * radio, y: CENTRO.y + Math.sin(angulo) * radio };
}

// ---------------------------------------------------------------- dibujo

function dibujar() {
  const lienzo = document.getElementById("map-canvas");
  if (!lienzo || !_mapa) return;
  lienzo.replaceChildren(buildSvg(_mapa));
  pintarDetalle();
}

function el(nombre, atributos = {}, clase = "") {
  const nodo = document.createElementNS(SVG_NS, nombre);
  for (const [k, v] of Object.entries(atributos)) nodo.setAttribute(k, String(v));
  if (clase) nodo.setAttribute("class", clase);
  return nodo;
}

function buildSvg(mapa) {
  const svg = el("svg", { viewBox: `0 0 ${ANCHO} ${ALTO}`, role: "img" }, "map-svg");
  svg.setAttribute("aria-label", "Mapa de conexiones del agente");

  svg.appendChild(buildFondo());

  const distribucion = distribuir(mapa);
  const enlaces = el("g", {}, "map-enlaces");
  const nodos = el("g", {}, "map-nodos");
  const titulos = el("g", {}, "map-titulos");

  for (const { grupo, nodos: lista, anguloTitulo, radioTitulo } of distribucion) {
    titulos.appendChild(buildTitulo(grupo, anguloTitulo, radioTitulo));
    for (const { nodo, angulo, aireEtiqueta } of lista) {
      if (!nodo.fantasma) enlaces.appendChild(buildEnlace(nodo, angulo));
      nodos.appendChild(buildNodo(grupo, nodo, angulo, aireEtiqueta));
    }
  }

  svg.append(enlaces, buildCentro(mapa.agente || {}), nodos, titulos);
  return svg;
}

function buildFondo() {
  const g = el("g", {}, "map-fondo");
  // Órbitas: la de los nodos y dos más, tenues, para que el centro se lea como centro.
  for (const [r, clase] of [[RADIO, "map-orbita map-orbita-principal"],
                            [RADIO * 0.55, "map-orbita"], [RADIO * 1.32, "map-orbita map-orbita-externa"]]) {
    g.appendChild(el("circle", { cx: CENTRO.x, cy: CENTRO.y, r }, clase));
  }
  return g;
}

function buildTitulo(grupo, angulo, radio) {
  const p = polar(angulo, radio);
  const texto = el("text", { x: p.x, y: p.y, "text-anchor": "middle",
                             "dominant-baseline": "middle" }, "map-titulo");
  texto.textContent = grupo.titulo.toUpperCase();
  return texto;
}

function buildEnlace(nodo, angulo) {
  const destino = polar(angulo, RADIO - RADIO_NODO - 2);
  const origen = polar(angulo, 46);
  // Una curva suave: los puntos de control se corren un poco en perpendicular al radio,
  // así los enlaces no son rayos rectos y el conjunto se ve como un tejido, no como una
  // rueda de bicicleta.
  const desvio = 22;
  const nx = -Math.sin(angulo) * desvio;
  const ny = Math.cos(angulo) * desvio;
  const c1 = polar(angulo, 95);
  const c2 = polar(angulo, RADIO - 70);
  const d = `M ${origen.x.toFixed(1)} ${origen.y.toFixed(1)} `
          + `C ${(c1.x + nx).toFixed(1)} ${(c1.y + ny).toFixed(1)}, `
          + `${(c2.x + nx).toFixed(1)} ${(c2.y + ny).toFixed(1)}, `
          + `${destino.x.toFixed(1)} ${destino.y.toFixed(1)}`;

  const g = el("g", {}, `map-enlace map-estado-${nodo.estado}`);
  g.appendChild(el("path", { d }, "map-enlace-base"));
  if (nodo.estado === "activo") {
    // El pulso: un segundo trazo punteado que recorre el enlace. Solo en lo que está
    // vivo; lo configurado pero apagado se queda quieto.
    g.appendChild(el("path", { d }, "map-enlace-pulso"));
  }
  return g;
}

function buildNodo(grupo, nodo, angulo, aireEtiqueta) {
  const p = polar(angulo, RADIO);
  const seleccionado = _seleccion && _seleccion.grupo === grupo.id && _seleccion.id === nodo.id;
  const g = el("g", { transform: `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})` },
               ["map-nodo", `map-estado-${nodo.estado}`, nodo.fantasma ? "map-nodo-fantasma" : "",
                seleccionado ? "map-nodo-seleccionado" : ""].filter(Boolean).join(" "));
  g.setAttribute("tabindex", "0");
  g.setAttribute("role", "button");
  g.setAttribute("aria-label", `${nodo.label}: ${ETIQUETA_DE_ESTADO[nodo.estado] || nodo.estado}`);
  g.dataset.grupo = grupo.id;
  g.dataset.id = nodo.id;

  if (nodo.estado === "activo" && !nodo.fantasma) {
    g.appendChild(el("circle", { r: RADIO_NODO + 7 }, "map-nodo-halo"));
  }
  g.appendChild(el("circle", { r: RADIO_NODO }, "map-nodo-disco"));
  g.appendChild(el("circle", { r: RADIO_NODO }, "map-nodo-anillo"));

  const nombreIcono = grupo.id === "canales" ? (ICONO_DE_CANAL[nodo.id] || "message")
                    : nodo.fantasma ? "plus" : grupo.icono;
  const ic = el("use", { href: `#ic-${nombreIcono}`, x: -9, y: -9, width: 18, height: 18 },
                "map-nodo-icono");
  g.appendChild(ic);

  // El punto de estado, en el borde del disco.
  if (!nodo.fantasma) {
    g.appendChild(el("circle", { cx: RADIO_NODO * 0.72, cy: -RADIO_NODO * 0.72, r: 4.2 },
                     "map-nodo-punto"));
  }

  // La etiqueta va del lado de afuera de la órbita, en la dirección del radio, para no
  // pisar los enlaces. A los costados se alinea hacia afuera; arriba y abajo, centrada.
  const cos = Math.cos(angulo);
  const sin = Math.sin(angulo);
  const anchor = cos > 0.35 ? "start" : cos < -0.35 ? "end" : "middle";
  const ex = aireEtiqueta * cos;
  const ey = aireEtiqueta * sin;
  const etiqueta = el("text", { x: ex.toFixed(1), y: (ey + (anchor === "middle" ? sin * 6 : 0)).toFixed(1),
                                "text-anchor": anchor, "dominant-baseline": "middle" },
                      "map-nodo-etiqueta");
  etiqueta.textContent = recortar(nodo.label, 16);
  g.appendChild(etiqueta);

  const abrir = () => seleccionar(grupo.id, nodo.id);
  g.addEventListener("click", abrir);
  g.addEventListener("keydown", (evt) => {
    if (evt.key === "Enter" || evt.key === " ") { evt.preventDefault(); abrir(); }
  });
  return g;
}

function buildCentro(agente) {
  const g = el("g", { transform: `translate(${CENTRO.x} ${CENTRO.y})` }, "map-centro");
  g.appendChild(el("circle", { r: 64 }, "map-centro-halo"));
  g.appendChild(el("circle", { r: 46 }, "map-centro-disco"));
  g.appendChild(el("circle", { r: 46 }, "map-centro-anillo"));

  const marca = crearMarca({ tamano: 58, trazo: 4.2, nodo: 9.5, animada: true, clase: "map-centro-marca" });
  marca.setAttribute("x", "-29");
  marca.setAttribute("y", "-29");
  g.appendChild(marca);

  const nombre = el("text", { y: 68, "text-anchor": "middle" }, "map-centro-nombre");
  nombre.textContent = (agente.nombre || "").toUpperCase();
  g.appendChild(nombre);

  const modelo = el("text", { y: 84, "text-anchor": "middle" }, "map-centro-modelo");
  modelo.textContent = agente.modelo ? `${agente.proveedor || ""} · ${agente.modelo}`.replace(/^ · /, "")
                                     : (agente.proveedor || "");
  g.appendChild(modelo);

  if (agente.autonomia && agente.autonomia.activo) {
    const insignia = el("text", { y: -58, "text-anchor": "middle" }, "map-centro-autonomia");
    insignia.textContent = agente.autonomia.nivel === "total" ? "AUTONOMÍA TOTAL" : "AUTONOMÍA";
    g.appendChild(insignia);
  }
  return g;
}

function recortar(texto, max) {
  const t = String(texto || "");
  return t.length > max ? t.slice(0, max - 1) + "…" : t;
}

// ---------------------------------------------------------------- detalle de un nodo

function seleccionar(grupoId, nodoId) {
  const igual = _seleccion && _seleccion.grupo === grupoId && _seleccion.id === nodoId;
  _seleccion = igual ? null : { grupo: grupoId, id: nodoId };
  dibujar();
}

function nodoSeleccionado() {
  if (!_seleccion || !_mapa) return null;
  if (_seleccion.id === "__vacio__" || _seleccion.id === "__mas__") {
    const grupo = GRUPOS.find((g) => g.id === _seleccion.grupo);
    return { grupo, nodo: null };
  }
  const lista = _mapa[_seleccion.grupo] || [];
  const nodo = lista.find((n) => String(n.id) === String(_seleccion.id));
  return nodo ? { grupo: GRUPOS.find((g) => g.id === _seleccion.grupo), nodo } : null;
}

function pintarDetalle() {
  const panel = document.getElementById("map-detalle");
  if (!panel) return;
  const sel = nodoSeleccionado();
  panel.replaceChildren();
  if (!sel) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const { grupo, nodo } = sel;

  const cabecera = document.createElement("div");
  cabecera.className = "map-detalle-cabecera";
  const titulo = document.createElement("div");
  titulo.className = "map-detalle-titulo";
  titulo.textContent = nodo ? nodo.label : grupo.titulo;
  const cerrar = document.createElement("button");
  cerrar.type = "button";
  cerrar.className = "panel-close-btn";
  cerrar.setAttribute("aria-label", "Cerrar detalle");
  cerrar.appendChild(icon("close", "ic-sm"));
  cerrar.addEventListener("click", () => { _seleccion = null; dibujar(); });
  cabecera.append(titulo, cerrar);
  panel.appendChild(cabecera);

  const grupoLinea = document.createElement("div");
  grupoLinea.className = "map-detalle-grupo";
  grupoLinea.textContent = grupo.titulo;
  panel.appendChild(grupoLinea);

  if (nodo) {
    const estado = document.createElement("div");
    estado.className = "map-detalle-estado";
    const punto = document.createElement("span");
    punto.className = `map-punto map-estado-${nodo.estado}`;
    const texto = document.createElement("span");
    texto.textContent = ETIQUETA_DE_ESTADO[nodo.estado] || nodo.estado;
    estado.append(punto, texto);
    panel.appendChild(estado);

    if (nodo.detalle) panel.appendChild(parrafo(nodo.detalle));
    for (const fila of filasDeDetalle(grupo.id, nodo)) panel.appendChild(fila);
  } else {
    panel.appendChild(parrafo(textoDeGrupoVacio(grupo.id)));
  }

  if (grupo.seccion) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "panel-submit-btn panel-submit-btn-secundario map-detalle-abrir";
    boton.textContent = "Abrir en Configuración";
    boton.addEventListener("click", () => {
      closeMapPanel();
      openSettingsPanel(grupo.seccion);
    });
    panel.appendChild(boton);
  }
}

function parrafo(texto) {
  const p = document.createElement("p");
  p.className = "map-detalle-texto";
  p.textContent = texto;
  return p;
}

function filaClaveValor(clave, valor, mono = false) {
  const fila = document.createElement("div");
  fila.className = "map-detalle-fila";
  const k = document.createElement("span");
  k.className = "map-detalle-clave";
  k.textContent = clave;
  const v = document.createElement("span");
  v.className = "map-detalle-valor" + (mono ? " map-detalle-mono" : "");
  v.textContent = valor;
  fila.append(k, v);
  return fila;
}

function filasDeDetalle(grupoId, nodo) {
  const filas = [];
  if (grupoId === "mcp") {
    filas.push(filaClaveValor(nodo.transporte === "http" ? "URL" : "Comando", nodo.destino || "", true));
    filas.push(filaClaveValor("Permitidas", (nodo.permitidas || []).join(", ") || "nada todavía"));
    filas.push(filaClaveValor("Habilitadas ahora", (nodo.herramientas || []).join(", ") || "ninguna"));
    filas.push(filaClaveValor("Canales", (nodo.canales || []).join(", ") || "escritorio"));
  } else if (grupoId === "flujos") {
    filas.push(filaClaveValor("Estado", nodo.estado_flujo || ""));
  } else if (grupoId === "canales" && nodo.capacidades && nodo.capacidades.length) {
    filas.push(filaClaveValor("Capacidades", nodo.capacidades.join(", ")));
  }
  return filas;
}

function textoDeGrupoVacio(grupoId) {
  return {
    modelos: "No hay ninguna clave de proveedor puesta: el agente no puede responder. Se pegan en Configuración → Claves de IA.",
    canales: "",
    mcp: "Todavía no hay servidores MCP. Lo más fácil es pedírselo en el chat: «Conectate al servidor MCP de Notion: el comando es npx -y @notionhq/notion-mcp-server y necesita NOTION_TOKEN».",
    flujos: "Todavía no hay flujos. Se crean hablando: «aprendé el flujo modo trabajo: abrí chrome, después el bloc de notas».",
  }[grupoId] || "";
}
