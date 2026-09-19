# Contexto REQ-050 — Configuración reorganizada

## Resumen ejecutivo
La sección «Conexiones» apilaba siete credenciales de cuatro líneas cada una con el campo
abierto, y los servidores MCP quedaban debajo de todo; además la caja del modal no tenía
scroll (se cortaba por arriba y por abajo). Ahora: seis secciones (Perfil, Modelos, Claves
de IA, Canales, MCP, Seguridad), cada credencial en una línea con su estado y un botón
«Pegar»/«Cambiar» que abre el campo solo al pedirlo, Telegram/Discord y los interruptores
de correo en «Canales», MCP con sección propia, y Seguridad con autonomía y niveles.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI · **Tipo:** MEJORA

## Origen
Captura de Johan (2026-09-19): «no se ve amigable y no se puede hacer scroll… no veo lo del
MCP». Se propuso el boceto de seis secciones y filas compactas, y lo aprobó («empieza con
todos los puntos»).

## Decisiones tomadas
2026-09-19 | conversación principal | Scroll: `max-height` en `.modal-box-settings` y `overflow-y` en `.settings-content`; cabecera y navegación fijas | La caja crecía más que la ventana y el overlay la centraba recortada. Commit aparte (`2326bbc`), era un defecto.
2026-09-19 | conversación principal | Una fila por credencial: nombre · estado · «Pegar»/«Cambiar» (+ «Quitar» si está en el archivo); el editor (campo tipo password + Guardar + Cancelar) vive dentro de la fila y solo se muestra al pedirlo | Siete campos de contraseña abiertos a la vez no se leen; uno, cuando hace falta, sí. La descripción larga queda en el `title` del nombre.
2026-09-19 | conversación principal | El id viejo `conexiones` cae en «claves» (`SECCIONES_VIEJAS`); el aviso de arranque sin clave abre «claves» | Un frontend cacheado o un aviso viejo no puede caer en Perfil.
2026-09-19 | conversación principal | Los interruptores de correo pasan de Seguridad a Canales | Son "qué puede hacer el correo", no "cuánto confirmar": estaban perdidos.
2026-09-19 | conversación principal | `.conexion-editor[hidden] { display: none }` | `display: flex` le gana al `[hidden]` del navegador; se vio en la captura offscreen (los editores salían siempre abiertos).

## Verificación
- Capturas offscreen de Claves de IA, Canales y MCP (tema oscuro): filas compactas, editor
  oculto por defecto, scroll dentro de la sección.
- `tests/test_webview_conexiones.py` (aviso de arranque → «claves»), `test_webview_mcp.py`,
  `test_webview_buttons.py`, `test_webview_bridge.py`, `test_email_escritura.py`: 245 passed.

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión.
