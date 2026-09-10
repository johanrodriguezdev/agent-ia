// ui/webview/frontend/js/agente.js
// REQ-037 — El nombre del agente, en un solo lugar.
//
// El nombre lo elige el usuario: hoy se llama VIERNES, ayer ORION. Estaba escrito a mano en
// varios textos de la interfaz ("Pedíselo a O.R.I.O.N. hablando"), así que quien lo
// renombraba seguía leyendo el nombre viejo — y peor, un nombre que nunca eligió.
//
// El valor inicial lo inyecta `MainWindow._inject_agent_name_script()` como variable global
// antes de que corra cualquier script. Lo que faltaba era que ese valor se ACTUALIZARA al
// renombrar: la global se quedaba con el nombre del arranque y solo se repintaban tres
// nodos del DOM a mano. Ahora hay un único lugar que lo sabe, y todo lo demás pregunta.

const POR_DEFECTO = "tu asistente";

let _nombre = "";

/** Return el nombre del agente tal como lo eligió el usuario. */
export function nombreDelAgente() {
  const crudo = (_nombre || window.__ORION_AGENT_NAME__ || "").trim();
  return crudo || POR_DEFECTO;
}

/**
 * Guarda el nombre nuevo. Lo llama `setAgentIdentity()` en cada carga de perfil y cada
 * renombre, que son los dos únicos momentos en que el nombre puede cambiar.
 */
export function fijarNombreDelAgente(nombre) {
  const limpio = (nombre || "").trim();
  if (!limpio) return;
  _nombre = limpio;
  // La global también, para que quede una sola verdad: hay código que la lee directo y
  // dejarla desactualizada es justo el bug que esto viene a cerrar.
  window.__ORION_AGENT_NAME__ = limpio;
}
