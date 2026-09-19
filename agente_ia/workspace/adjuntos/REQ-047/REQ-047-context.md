# Contexto REQ-047 — Frenar un turno desde Telegram/Discord, y presupuesto remoto 8

## Resumen ejecutivo
El techo de 5 vueltas fuera del escritorio (SPEC-027/CA-15) existía por un solo motivo: no
había forma de parar. Ahora `/detener` (Telegram; también `/stop`) y `!detener` o `/detener`
(Discord) frenan el turno en curso **de ese usuario**, cooperativamente, en el próximo punto
seguro (antes de la siguiente llamada al modelo o de la siguiente herramienta). Con eso,
Telegram y Discord pasan al presupuesto del escritorio sin modo (8). Voz, API, correo y
desconocido siguen en 5.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión autorizada por Johan, 2026-09-19)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** BOT · **Tipo:** MEJORA

## Decisiones tomadas
2026-09-19 | conversación principal | Turnos remotos con clave `canal:usuario` en `core/cancelacion.py` (`abrir_turno_remoto`, `cancelar_remoto`, `cerrar_turno_remoto`, `control_remoto`), separados del turno único del escritorio | El escritorio tiene UN turno de proceso con botón; un canal remoto tiene varios usuarios con mensajes en curso en hilos distintos. Un `/detener` no puede tocar el turno de otro usuario ni el del escritorio. Fijado por test.
2026-09-19 | conversación principal | `ejecutar_vuelta(..., control=callable)`: el camino remoto pasa su propio punto de control; el escritorio sigue con `abortar_si_cancelado()` | Un solo sitio para "parar entre herramientas", con el mecanismo de cada canal inyectado. `cancelable=False` sigue existiendo para quien no tenga ninguno.
2026-09-19 | conversación principal | `ask_claude()` abre el turno remoto con `clave_remota(channel, user_id)` (el `user_id` canónico que ya recibe), lo cierra en `finally`, y ante `TurnoCancelado` responde «Detenido» y saca el mensaje del historial | El mensaje detenido no es un turno: no puede quedar como pregunta sin respuesta que el modelo intente contestar después.
2026-09-19 | conversación principal | Los comandos de los bots resuelven la misma clave (`_owner_uid` en Telegram, `canonical_user_id("discord", …)` en Discord) | Si las claves no coincidieran, el stop nunca encontraría el turno. Fijado por test en los dos bots.
2026-09-19 | conversación principal | Presupuesto remoto = `TECHO_CANAL_REMOTO_CON_STOP = MAX_LLM_CALLS` (8), aplicado en `claude_brain` y en `_presupuesto_de_llamadas()` para TELEGRAM/DISCORD; el resto sigue en `TECHO_CANAL_NO_ESCRITORIO` (5) | Johan aprobó 8 (el del escritorio sin modo). Voz sigue sin forma de parar: sigue en 5.

## Qué puede hacer ahora
- Por Telegram: *«investigá X»* → si se está yendo por las ramas, `/detener` → «Deteniendo… Paro en cuanto termine lo que está haciendo ahora.» El siguiente mensaje arranca limpio.
- Por Discord: `!detener` en el canal o `/detener`.
- Ambos canales resuelven hasta 8 vueltas con herramientas (antes 5) más el cierre.

## Verificación
- `tests/test_cancelacion_remota.py`: 12 passed (nuevo).
- `tests/test_reasoning_loop.py::test_ca15_*` actualizado (techo 8 en Telegram/Discord, 5 en el resto); `tests/test_paridad_canales.py` con la constante nueva.
- Suite completa: ver commit.

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión.
