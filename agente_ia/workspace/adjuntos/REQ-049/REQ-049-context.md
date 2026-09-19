# Contexto REQ-049 — Órdenes por correo, acotadas a herramientas MCP de solo lectura

## Resumen ejecutivo
El correo sigue siendo entrada no confiable con política vacía. Lo que se abre es un camino
estrecho: un correo de un remitente de `command_senders`, verificado por DKIM/SPF de un
servidor de confianza, con asunto `ORION: …`, se resuelve en el canal EMAIL con acceso
únicamente a las herramientas MCP de **solo lectura** que el usuario habilitó para correo,
y la respuesta vuelve por correo al remitente. Interruptor propio, apagado por defecto.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión autorizada por Johan, 2026-09-19)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** SEGURIDAD · **Tipo:** FEATURE_NUEVA + SEGURIDAD

## Origen
Tercer "todavía no puede" del informe del 2026-09-18. Se le propuso a Johan la versión
acotada (solo lectura, remitentes verificados) y la aprobó en bloque. Spec:
`spec/SPEC-049.md`.

## Qué puede hacer ahora (ejemplos)
- Con el interruptor encendido y `search` de Notion habilitado para correo: mandar desde tu
  cuenta un correo con asunto *«ORION: qué notas tengo sobre la reunión del lunes»* → el
  agente busca en Notion y responde en el mismo hilo.
- Un correo con el mismo asunto desde otra dirección, o desde tu dirección pero suplantada
  (sin DKIM/SPF pass de tu servidor): descartado con warning en el log. Nada se ejecuta.
- Una orden que pida escribir algo (*«creá una página»*): la herramienta no tiene excepción
  EMAIL → denegada y auditada; el agente responde que no puede desde el correo.

## Decisiones tomadas
2026-09-19 | conversación principal | La política de `ChannelType.EMAIL` sigue vacía; lo único que entra son excepciones `(EMAIL, mcp__…)` que `mcp_manager._habilitar_canales` da solo a herramientas `readOnlyHint` no destructivas | `project_entrada_no_confiable`: lo que un desconocido puede originar no alcanza acciones amarillas. Aquí ni siquiera el dueño verificado alcanza escritura: no hay nadie delante para confirmar.
2026-09-19 | conversación principal | Nivel mínimo `verified` para órdenes aunque la cuenta tenga `none`; sin `trusted_authserv_ids` no se atiende ninguna orden | Leer un correo suplantado es ruido; obedecerlo es otra cosa. Reutiliza `core/email_auth.py` (trusted authserv-ids, criterio de OpenClaw).
2026-09-19 | conversación principal | Adaptador de confirmación para EMAIL que aprueba solo `mcp__*` con excepción EMAIL | Mantiene el invariante «amarillo = decide un adaptador» y queda auditado por `require_confirmation()`. Registrado en `main.py`.
2026-09-19 | conversación principal | `catalogo_para_modelo(canal)` ofrece también las herramientas con excepción de canal | Bug pre-existente: una MCP amarilla habilitada para Telegram/Discord nunca se le ofrecía al modelo ahí (no estaba en los niveles del canal), así que la excepción no servía. Fijado por test.
2026-09-19 | conversación principal | La respuesta va por `email_sender.enviar()` directo, auditada como `email_command_reply`, sin pasar por `send_email_as_user` (🔴) ni por el interruptor «Enviar correos» | No es el agente escribiéndole a quien quiera como el usuario: es la respuesta a una orden verificada, al remitente, y el interruptor «Atender órdenes» es la decisión explícita. Documentado en `security-levels.md`.
2026-09-19 | conversación principal | Estado propio `comandos::…` en `email_state.json`; en el estreno no se atiende nada viejo | Atender órdenes no consume los correos del resumen; una orden de hace meses no se ejecuta hoy.
2026-09-19 | conversación principal | Poller en hilo (cada `command_poll_minutes`, 5 por defecto) arrancado desde `main.py` solo si el interruptor está encendido; encenderlo después exige reiniciar | Mismo criterio que el resto de capacidades de correo.

## Prueba manual sugerida (para Johan)
1. En `config.json → email`: `sender_auth.trusted_authserv_ids` con tu servidor (Gmail:
   `mx.google.com`), `command_senders` con tu dirección. Encender «Atender órdenes por
   correo» en Configuración → Seguridad. Habilitar una herramienta de solo lectura de algún
   servidor MCP para correo (chat: *«habilitale search para desktop y email»*). Reiniciar.
2. Mandarte un correo con asunto `ORION: buscá X` → en ≤5 min debe llegar la respuesta.
3. Mandar el mismo asunto desde otra cuenta → nada, y un warning en `logs/`.

## Verificación
- `tests/test_email_commands.py`: 22 passed (nuevo).
- Suites de MCP, seguridad, skills y política remota: verdes con el catálogo por excepciones.
- Suite completa: **3052 passed, 0 failed** (sin `test_webview_smoke.py`). Se actualizaron 4 tests que fijaban el estado anterior (el conjunto de capacidades de correo y «EMAIL no tiene adaptador»).

## Riesgos activos
- No se probó contra IMAP/SMTP reales (regla de tests). `_revisar_cuenta` sigue el mismo
  patrón que `email_reader._leer_cuenta`.
- El cuerpo de la orden entra al prompt del modelo: es texto del dueño verificado, pero un
  correo reenviado con contenido ajeno también lo sería. El daño posible está acotado por
  construcción a leer de los servidores habilitados y responder al propio remitente.

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión.
