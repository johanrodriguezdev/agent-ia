# Contexto REQ-060 — Leer una conversación larga: «Ir al final» y la hora de cada mensaje

## Resumen ejecutivo
1. **«Ir al final».** Desde REQ-015 (CA-16) el chat no arrastra al usuario que subió a
   releer algo cuando llega una respuesta; pero tampoco le decía que había algo nuevo
   abajo. Ahora, al alejarse del final aparece una pastilla «Ir al final» flotando sobre
   el último contenido; si llega contenido mientras está arriba (una respuesta entera o
   el texto que se va escribiendo), pasa a «Nuevos mensajes» con un punto de la marca
   latiendo. Un click baja con suavidad y la esconde.
2. **La hora de cada mensaje** en la fila de acciones que aparece al pasar el mouse:
   «14:05» si es de hoy, «19 sept, 14:05» si no. Siempre en 24 h.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI
- **Tipo:** MEJORA

## Origen
Noche del 2026-09-20, aprobación en bloque de Johan.

## Decisiones tomadas
2026-09-20 | conversación principal | La pastilla vive en un envoltorio `position: sticky; bottom: 0; height: 0` al final del área de scroll, con el botón desplazado hacia arriba | Flota sobre el último contenido sin ocupar sitio ni depender de la altura del composer (que cambia con los chips y el adjunto). `align-items: flex-end` para que el botón no se estire a la altura 0 del envoltorio (se vio en la primera captura).
2026-09-20 | conversación principal | Aparece a más de 240 px del final; «Nuevos mensajes» solo si llega contenido estando lejos | Cerca del final el auto-scroll ya lo lleva (CA-16); mostrarla siempre sería ruido.
2026-09-20 | conversación principal | La hora va con las acciones (visible al pasar el mouse), no fija en cada burbuja | La fecha exacta importa poco mientras se lee y mucho cuando se busca; fija en cada mensaje recargaría el chat (ver [[feedback_ui_simplicidad]]).
2026-09-20 | conversación principal | 24 h con `hourCycle: "h23"` | El equipo de Johan formatea en 12 h («02:05 p. m.») con la configuración regional; la hora en el chat tiene que ser corta.

## Archivos
- Tocados: `index.html` (`#ir-al-final`), `js/chat.js` (`actualizarIrAlFinal`,
  `avisarNuevosAbajo`, `horaDelMensaje`, `etiquetaDeHora`), `css/chat.css`.
- Tests: `test_webview_buttons.py` (+2, e inventario de botones). El test de la pastilla
  muestra la ventana (`window.show()`): sin mostrarla el área de chat mide 0 px de alto en
  offscreen y no hay scroll que medir.

## Verificación
- Suite completa: ver `pruebas/suite-060.txt`.
- Capturas offscreen: `pruebas/final_dark.png`, `pruebas/final_light.png` («Nuevos
  mensajes» tras llegar una respuesta con el usuario arriba; hora «00:43» junto a Copiar).

## Prueba manual sugerida (Johan)
1. En una conversación larga, subir con la rueda: aparece «Ir al final»; click → baja.
2. Subir, mandar una pregunta y quedarse arriba mientras responde: la pastilla dice
   «Nuevos mensajes» con el punto latiendo; el chat no se mueve solo.
3. Pasar el mouse por un mensaje: la hora al lado de Copiar.

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
