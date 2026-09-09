# Estado real del tracker — 2026-09-09

Johan preguntó dos veces qué había pendiente y las dos veces la respuesta honesta fue "el
CSV no dice la verdad": 17 REQs figuran en `EN_QA` desde hace semanas. Este documento es la
revisión, hecha contra la evidencia de cada REQ y contra el código, no contra el CSV.

**Nada de esto se aplicó al tracker.** Cerrar un REQ exige la prueba manual del humano
(`.claude/rules/definition-of-done.md`, `orion-qa`), y esa es de Johan. Acá está la lista
para que la confirme de una y se mueva todo junto.

## Lo que dice la evidencia

| REQ | Estado CSV | Veredicto de QA | Qué falta de verdad |
|---|---|---|---|
| REQ-007 | EN_QA | ✅ COMPLETADO | Solo la prueba manual |
| REQ-008 | EN_QA | ✅ COMPLETADO | Solo la prueba manual |
| REQ-009 | EN_QA | ✅ APROBADO (ciclo 2) | Solo la prueba manual |
| REQ-011 | EN_QA | ✅ COMPLETADO | Solo la prueba manual |
| REQ-013 | EN_QA | ✅ COMPLETADO | Su alcance lo **reemplazó REQ-014**: cerrar o marcar como superado |
| REQ-014 | EN_QA | ✅ COMPLETADO (3ª pasada) | Superado a su vez por REQ-015 (WebView) |
| REQ-015 | EN_QA | ✅ COMPLETADO | Es la interfaz que usás hoy — validado por uso diario |
| REQ-016 | EN_QA | ✅ COMPLETADO | Idem |
| REQ-017 | EN_QA | ✅ COMPLETADO | Solo la prueba manual |
| REQ-018 | EN_QA | ✅ APROBADO | Solo la prueba manual |
| REQ-019 | EN_QA | ✅ APROBADO | Solo la prueba manual |
| REQ-020 | EN_QA | ✅ COMPLETADO | Solo la prueba manual |
| REQ-021 | EN_QA | ✅ COMPLETADO | Solo la prueba manual |
| REQ-022 | EN_QA | ✅ COMPLETADO | Solo la prueba manual |
| REQ-024 | EN_QA | ✅ APROBADO | Solo la prueba manual |
| REQ-025 | EN_QA | ✅ COMPLETADO (2ª vuelta) | Verificado en código: el `logger.error` está en `channels/discord_bot.py:76` |

**Aviso sobre este cuadro:** el primer barrido automático me dio "RECHAZADO" para REQ-013 y
REQ-025 porque tomaba la primera aparición de la palabra en el documento. Los dos tienen una
segunda vuelta con veredicto positivo. Los veredictos de arriba son el ÚLTIMO de cada
auditoría, y los cuatro ambiguos (007, 018, 019, 024) se leyeron uno por uno.

## Los que sí tienen trabajo pendiente de verdad

| REQ | Estado | Situación |
|---|---|---|
| **REQ-003** | EN_PRUEBAS | El único sin auditoría de QA **ni** resultados de pruebas. Está genuinamente a medias |
| **REQ-023** | EN_ARQUITECTURA | `arquitectura-023.md` listo, esperando **tu revisión personal**. Marcado como no auto-aprobable |
| **REQ-010** | ARQUITECTURA_APROBADA | Obsoleto como está escrito — ver abajo |
| **REQ-012** | EN_PRUEBAS | Re-baseline y arreglado hoy (`426d970`) |
| **REQ-027** | EN_QA | Implementado, suite verde, falta tu prueba manual |
| **REQ-028** | EN_PRUEBAS | Implementado y verificado; falta probarlo con una reunión real |
| **REQ-029** | EN_PRUEBAS | Implementado y auditado; nace inerte hasta que habilites una carpeta |

## REQ-010 — el problema ya está resuelto, pero de otra manera

Su objetivo era que la ventana, la barra de tareas y la bandeja dejaran de mostrar el logo
de Python y un cuadrado azul. **Eso ya no pasa**: `ui/webview/app_icon.py` dibuja la marca y
`fijar_identidad_en_windows()` declara el AppUserModelID, que es lo que hacía falta para la
barra de tareas.

Pero sus criterios no se pueden cumplir como están escritos:

- **CA-03, CA-06, CA-07, CA-08** nombran `_setup_tray_icon()` con `QPixmap` sólido y
  `header_bar.py` — código de la GUI PyQt eliminada en REQ-015.
- **CA-04** pide un `.ico` multi-resolución con el logo de Noddoo. Eso **contradice una
  decisión posterior y deliberada**, documentada en `app_icon.py`: no hay archivo binario con
  un logo fijo porque *"el nombre del agente es del usuario — hoy se llama VIERNES, ayer
  ORION"*, y una marca dibujada no envejece con el nombre.
- Además, el nombre del producto sigue abierto, así que fijar "Noddoo" en un binario ahora
  sería trabajo para rehacer.

**Propuesta:** cerrarlo como superado por REQ-015, o reescribir su alcance cuando el nombre
del producto esté decidido. No hace falta código.

## Lo que recomiendo hacer

1. Confirmá los 16 de la primera tabla —los usás todos los días— y muevo el tracker de una.
2. REQ-013, REQ-014 y REQ-010 conviene marcarlos como superados, no como pendientes: arrastran
   la sensación de deuda sin tener trabajo detrás.
3. Queda REQ-003 como el único pendiente real y viejo.
