# SPEC-049 — Órdenes por correo, acotadas a herramientas MCP de solo lectura

**Categoría:** SEGURIDAD · **Tipo:** FEATURE_NUEVA + SEGURIDAD · **Fecha:** 2026-09-19
**Origen:** el tercer "todavía no puede" del informe del 2026-09-18. Johan aprobó en bloque
la versión acotada que se le propuso: solo remitentes de una lista, verificados, solo
herramientas de solo lectura, respuesta por correo.

## Lo que NO cambia (el constraint)

El correo es entrada que cualquiera puede originar. Su canal (`ChannelType.EMAIL`) tiene
política **vacía** —ni siquiera verde— y eso sigue igual: `open_app`, `recall_memory`,
`file_read`, nada del sistema es alcanzable desde un correo. Lo único que este REQ abre es
una lista cerrada de herramientas remotas **de solo lectura** (`readOnlyHint: true` en las
anotaciones del servidor MCP), que el usuario habilitó **explícitamente** para el canal
correo desde el escritorio (con confirmación, `mcp_allow_tools` con `canales=email`).

## Flujo

1. Un poller (hilo, cada N minutos; solo si el interruptor «Atender órdenes por correo»
   está encendido) busca en cada cuenta IMAP los correos nuevos cuyo **asunto empieza por
   el prefijo** configurado (por defecto `ORION:`).
2. El remitente tiene que estar en `command_senders` (lista cerrada, direcciones exactas)
   **y** el correo tiene que superar `sender_auth` con nivel mínimo `verified` (DKIM o SPF
   `pass` de un servidor en `trusted_authserv_ids`). Sin `trusted_authserv_ids` configurado
   no hay forma de verificar y **no se atiende ninguna orden** (fail-closed, con log).
3. La orden (asunto sin prefijo + cuerpo) se resuelve con `reasoning_loop.run()` en el
   canal EMAIL, sin turnos previos, con el presupuesto de 5 del canal. El modelo solo ve
   las herramientas que tienen excepción de canal para EMAIL (`catalogo_para_modelo`
   pasa a incluir las excepciones, que también arregla que las herramientas MCP habilitadas
   para Telegram/Discord se le ofrezcan al modelo ahí).
4. Cada herramienta pasa por el gate: YELLOW en EMAIL → adaptador de confirmación de
   correo, que **solo aprueba** acciones `mcp__*` con excepción para EMAIL (o sea, las de
   solo lectura que el usuario habilitó) y deniega todo lo demás. Queda auditado como
   cualquier confirmación.
5. La respuesta vuelve por correo **al remitente** (`Re:` en el mismo hilo), vía
   `email_sender.enviar()`. No pasa por el interruptor «Enviar correos» ni por el gate
   🔴 `send_email_as_user`: no es el agente escribiendo a quien quiera como el usuario, es
   la respuesta a una orden verificada, y el interruptor de órdenes ya es la decisión
   explícita del usuario. Se registra en la auditoría (`email_command_reply`).
6. El UID procesado se anota en un estado propio (`comandos::…`), independiente del del
   lector de resúmenes: atender órdenes no consume los correos del resumen.

## Criterios de aceptación

| # | Criterio |
|---|---|
| CA-01 | `email_capabilities.CAPACIDADES` tiene `commands` («Atender órdenes por correo»), apagado por defecto, visible en Configuración. |
| CA-02 | `mcp_config.CANALES_HABILITABLES` incluye `email`; `mcp_manager._habilitar_canales` solo agrega la excepción EMAIL a herramientas con `readOnlyHint: true` y no destructivas; las demás se registran sin ese canal, con log. |
| CA-03 | `catalogo_para_modelo(canal)` ofrece también las herramientas con excepción `(canal, nombre)` en `CHANNEL_ACTION_EXCEPTIONS`. |
| CA-04 | Adaptador de confirmación para `ChannelType.EMAIL` (`core/email_commands.confirmar_por_correo`): aprueba solo `mcp__*` con excepción EMAIL; deniega todo lo demás. Registrado en `main.py`. |
| CA-05 | `procesar_mensaje()`: sin `command_senders` → nada; remitente fuera de la lista → descartado; `sender_auth` no verificado o sin `trusted_authserv_ids` → descartado con warning; asunto sin prefijo → ignorado. |
| CA-06 | Una orden válida ejecuta `reasoning_loop.run(texto, EMAIL, prior_turns=[])` y responde por correo al remitente con `Re:`; el envío queda auditado. |
| CA-07 | El poller no consume el estado del lector de resúmenes (clave de estado propia). |
| CA-08 | Sin la capacidad encendida, el poller no arranca ni procesa. |
| CA-09 | Suite completa sin fallos nuevos; tests sin IMAP ni SMTP reales. |

## Fuera de alcance
- Órdenes que escriban algo (crear página, enviar mensaje): amarillas; nadie delante para
  confirmar. Si algún día se quieren, el camino es un segundo factor (p. ej. confirmación
  por Telegram), no bajar el nivel.
- Adjuntos en las órdenes: se ignoran.
