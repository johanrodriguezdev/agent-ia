// ui/webview/frontend/js/sugerencias.js
// REQ-053 — sugerencias de arranque: qué se le puede pedir al agente, con ejemplos.
//
// Un asistente que puede conectar servidores MCP, aprender flujos, ordenar chats en
// proyectos o atender el correo no sirve de nada si quien lo abre no sabe que puede
// pedírselo. Debajo del cuadro de texto, mientras la conversación está vacía, se
// muestran unas pocas frases de ejemplo tomadas al azar de un repertorio. Un click deja
// la frase escrita en el cuadro —no la manda— para que se ajuste antes de enviar.
//
// Se esconden en cuanto hay un mensaje (`body.chat-empty` lo decide chat.js) y se
// vuelven a sortear en cada conversación nueva, así con el tiempo se ven todas.

const REPERTORIO = [
  "¿Qué tenés conectado?",
  "Conectate al servidor MCP de Notion: el comando es npx -y @notionhq/notion-mcp-server y necesita NOTION_TOKEN",
  "Aprendé el flujo modo trabajo: abrí Chrome y después el bloc de notas",
  "Recordame mañana a las 9 llamar al banco",
  "Guardá este chat en el proyecto Tesis",
  "Buscá en internet las novedades de Python y resumímelas en tres puntos",
  "¿Qué hay en mi carpeta de Descargas?",
  "Tomá una captura de pantalla",
  "¿Qué tareas tengo pendientes?",
  "Leé el PDF que te adjunto y decime de qué trata",
  "Abrí la calculadora",
  "¿Cómo está el clima hoy?",
];

const CUANTAS = 4;

const $ = (id) => document.getElementById(id);

export function initSugerencias() {
  sortearSugerencias();
}

/** Elige `CUANTAS` frases distintas al azar y las pinta. */
export function sortearSugerencias() {
  const cont = $("sugerencias");
  if (!cont) return;
  cont.replaceChildren();

  const bolsa = REPERTORIO.slice();
  for (let i = bolsa.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [bolsa[i], bolsa[j]] = [bolsa[j], bolsa[i]];
  }
  for (const frase of bolsa.slice(0, CUANTAS)) {
    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "sugerencia";
    boton.textContent = recortar(frase, 52);
    boton.title = frase;
    boton.addEventListener("click", () => usarSugerencia(frase));
    cont.appendChild(boton);
  }
}

function usarSugerencia(frase) {
  const input = $("composer-input");
  if (!input) return;
  input.value = frase;
  input.dispatchEvent(new Event("input", { bubbles: true }));   // que crezca si hace falta
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}

function recortar(texto, max) {
  return texto.length > max ? texto.slice(0, max - 1).trimEnd() + "…" : texto;
}
