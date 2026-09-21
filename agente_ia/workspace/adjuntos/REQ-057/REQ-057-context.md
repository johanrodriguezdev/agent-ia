# Contexto REQ-057 — El momento de la respuesta: la marca piensa y avisa si no estás mirando

## Resumen ejecutivo
Dos cosas sobre el rato entre que preguntás y llega la respuesta, en el estilo que Johan
aprobó en REQ-052 («lo del modo futurista me gustó, sigue mejorando en ese estilo»):

1. **La marca piensa.** Los tres puntos genéricos del indicador de escritura se
   reemplazan por la marca (los anillos de REQ-052) girando en segundos en vez de en
   minutos, con un halo que respira detrás. La línea de estado («Buscando en internet:
   …») lleva un brillo que la recorre despacio con los tonos de la marca, y el botón de
   detener late con un anillo suave mientras el agente trabaja. Todo se apaga con
   `prefers-reduced-motion`.
2. **Aviso si no estás mirando.** Si la respuesta tardó (≥ 8 s) y la ventana no está al
   frente (otra app activa, minimizada o en la bandeja), llega un aviso del sistema
   «Respuesta lista» con la primera línea. Pedirle algo largo y pasar a otra cosa es el
   uso normal; hasta acá había que volver a mirar para saber si terminó.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI
- **Tipo:** MEJORA

## Origen
Noche del 2026-09-20, aprobación en bloque de Johan y su indicación de seguir en el
estilo futurista de REQ-052.

## Decisiones tomadas
2026-09-20 | conversación principal | La marca del indicador se monta con `crearMarca()` (marca.js), la misma geometría que la barra y el icono; solo cambia la velocidad (`.marca-pensando`) | Una animación distinta para "pensando" sería un segundo lenguaje visual. Es el mismo pulso de "vivo", acelerado porque está trabajando.
2026-09-20 | conversación principal | El brillo del texto de progreso y el latido del botón usan los tokens `--marca-*`, no colores nuevos | Es lo que hace que el tema oscuro y el claro salgan bien sin tocar nada más (REQ-052).
2026-09-20 | conversación principal | El aviso solo si el turno tardó ≥ 8 s y la ventana no está activa | Una respuesta rápida se ve llegar; un aviso por cada «hola» sería ruido. Alt-tab de un segundo tampoco lo dispara si la respuesta fue rápida.
2026-09-20 | conversación principal | Va por `core/notificaciones.py` (bandeja + aviso dentro de la ventana), no por una notificación propia | Es la infraestructura que ya usan los flujos; una segunda vía sería duplicar.

## Archivos
- Tocados: `index.html` (`#typing-marca`), `js/chat.js` (`initChat` monta la marca),
  `css/chat.css` (marca pensando, brillo del progreso), `css/composer.css` (latido del
  botón de detener), `ui/webview/bridge.py` (`_turno_inicio`, `_ventana_a_la_vista`,
  `_avisar_si_no_esta_mirando`).
- Tests: `tests/test_aviso_respuesta_lista.py` (6, nuevo).

## Qué puede hacer ahora
- Mientras el agente trabaja: la marca gira debajo del último mensaje con la línea de
  estado brillando; el botón de detener late.
- Pedir algo largo, cambiar de ventana: al terminar, aviso «Respuesta lista: …» en la
  bandeja.

## Verificación
- Suite completa: ver `pruebas/suite-057.txt`.
- Capturas offscreen: `pruebas/pensando_dark.png`, `pruebas/pensando_light.png` (marca
  girando + línea de estado + botón de detener).

## Prueba manual sugerida (Johan)
1. Preguntar algo que use herramientas y mirar el indicador: la marca gira, el texto
   «Buscando en internet…» brilla, el botón de detener late.
2. Pedir algo que tarde («investigá X a fondo») y pasar a otra ventana: al terminar
   llega el aviso del sistema con la primera línea.
3. Con la ventana al frente no llega ningún aviso.

## Log de transiciones
2026-09-20 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
