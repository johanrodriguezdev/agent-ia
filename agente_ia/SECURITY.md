# Política de seguridad

O.R.I.O.N. es un agente que **ejecuta acciones reales en el equipo del usuario**: abre y cierra
programas, escribe archivos, corre comandos, lee la pantalla y responde por Telegram y Discord.
Una vulnerabilidad aquí no filtra datos: puede hacer que un tercero opere la máquina. Por eso
el modelo de seguridad es parte del diseño y no una capa encima.

## Cómo reportar una vulnerabilidad

**No abras un issue público.** Usa el reporte privado de GitHub: en el repositorio, pestaña
**Security → Report a vulnerability**. Solo lo ve el mantenedor. Incluye:

- qué versión o commit probaste,
- los pasos para reproducirlo (si aplica, el mensaje exacto que le enviaste al agente y por qué
  canal),
- qué esperabas que pasara y qué pasó.

Recibirás respuesta en un plazo razonable (el proyecto lo mantiene una persona). Si el problema
se confirma, se corrige en un commit que cita el reporte, y se te acredita si quieres.

## Qué se considera vulnerabilidad

Cualquier forma de que el agente haga algo que su modelo de seguridad dice que no puede hacer:

- Ejecutar una acción 🟡 amarilla **sin** la confirmación del usuario, o una 🔴 roja sin
  permiso explícito.
- Alcanzar desde un canal remoto (Telegram, Discord, correo, voz) una acción que ese canal no
  tiene permitida — por ejemplo, leer un archivo del disco desde un mensaje de Telegram.
- Que un contenido de terceros (una página web, un correo, un documento) consiga que el agente
  ejecute instrucciones que el usuario no dio (inyección de prompt con efecto real).
- Que el agente lea o escriba fuera de las carpetas que el usuario habilitó, o toque su propio
  código fuente.
- Que una clave de API, un token de bot o una credencial OAuth acabe en un log, en una
  respuesta del agente, en la base de auditoría o en el repositorio.
- Que `web_read` u otra herramienta de red alcance direcciones de la red local o metadatos de
  nube (SSRF).
- Que un mensaje de un remitente **no autorizado** en Telegram/Discord sea atendido.

No son vulnerabilidades: que el modelo responda mal, que una herramienta falle con un error
visible, o que una acción 🟢 verde (solo lectura, sin efectos) se ejecute sin preguntar.

## El modelo, en corto

- **Tres niveles**, aplicados en el punto de entrada de cada camino de ejecución
  (`core/security_manager.py::require_confirmation()`): 🟢 verde actúa, 🟡 amarillo confirma,
  🔴 rojo se bloquea salvo permiso explícito.
- **Fail-closed**: una acción sin clasificar se bloquea. Un archivo de configuración de
  seguridad ausente o corrupto significa "sin permisos", nunca "sin restricciones".
- **Por canal**: la voz y los canales remotos solo alcanzan acciones verdes, y hay acciones
  verdes que aun así son solo de escritorio (`DESKTOP_ONLY_ACTIONS`). El canal lo declara
  quien recibe el mensaje; nunca se deduce del texto.
- **El usuario solo puede subir niveles**, nunca bajarlos (`security_overrides.json`), y las
  acciones rojas no se pueden bajar ni editando el archivo a mano.
- **Todo lo amarillo y rojo queda auditado** en `audit.db`, incluidos los comandos de la
  terminal embebida tal como se ejecutaron.
- **Entrada no confiable, agente restringido**: lo que un tercero puede originar (correo,
  webhooks) llega por un canal con política más estricta que la voz, nunca al agente con
  permisos de escritorio.

El detalle, con las decisiones y sus motivos, está en
[.claude/rules/security-levels.md](.claude/rules/security-levels.md). Cada requerimiento que
tocó seguridad dejó su auditoría en `workspace/adjuntos/REQ-XXX/pruebas/security-audit-XXX.md`.

## Secretos

Las claves de API se guardan en `config.json` (ignorado por git) o en variables de entorno;
los tokens OAuth de servidores MCP en `mcp_tokens.json` (ignorado); las identidades autorizadas
de Telegram/Discord en `authorized_users.json` (ignorado). Ninguno de esos archivos debe subirse
al repositorio. Si por error lo haces, **revoca la clave** antes que nada: borrarla del historial
de git no la saca de las copias que ya se descargaron.
