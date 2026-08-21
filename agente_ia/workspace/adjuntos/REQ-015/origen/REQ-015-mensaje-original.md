# REQ-015 — Mensaje original del humano (verbatim)

> Fecha: 2026-08-19
> Categoría: UI

---

Nuevo REQ, categoría UI: Migrar la capa visual del panel de escritorio de NODDOO de widgets nativos PyQt6/QSS a un WebView embebido (HTML/CSS/JS real), manteniendo el 100% de la lógica de negocio en Python.

## Motivo — por qué se abandona el enfoque de REQ-014 (widgets PyQt6 nativos)

REQ-014 (categoría UI, actualmente en `EN_QA`, NO llegar a tocar su fila del CSV — se documenta como antecedente, no se cierra/cancela, mismo criterio que se usó con REQ-013 cuando REQ-014 lo reemplazó) implementó un rediseño completo de la UI con QWidget + QSS puro, pasando por 3 ciclos completos de dev→tester→qa→prueba manual del humano, cada uno rechazado por un bug de renderizado distinto encontrado SOLO en la prueba manual real (nunca detectado por la suite de tests headless, que sí pasaba 100% en los 3 ciclos):
1. 1er ciclo: panel derecho con texto superpuesto y bleed-through del escritorio detrás de la ventana (causa raíz: `QWidget` plano sin `WA_StyledBackground`, combinado con `WA_TranslucentBackground` de una ventana frameless).
2. 2do ciclo (tras eliminar el panel derecho y refinar 7 aspectos visuales): la ventana abría más alta que el área disponible real de la pantalla del humano y no se reposicionaba sola (frameless, sin barra de título nativa de Windows que la ajuste) — el input bar completo quedaba literalmente detrás de la barra de tareas de Windows, inalcanzable con el mouse.
3. 3er ciclo (tras corregir el tamaño de ventana): el campo de texto del input bar seguía sin ser usable — en la captura del humano se ve directamente invisible (sin borde, sin placeholder, un espacio vacío entre el ícono de adjuntar y el de voz), un bug de renderizado QSS distinto a los 2 anteriores, no diagnosticado todavía.

Patrón identificado por el humano y confirmado por Claude Code: cada ciclo resuelve un síntoma de composición/renderizado de Qt (QSS sobre `QWidget` plano, ventanas frameless + translúcidas, efectos gráficos) y aparece otro relacionado, porque QSS+QWidget crudo es intrínsecamente frágil para alcanzar el nivel de pulido visual de referencias reales (ChatGPT, Claude, DeepSeek, WorkBuddy AI — las 4 capturas de referencia que el humano compartió en REQ-014, disponibles en `workspace/adjuntos/REQ-014/` si hace falta consultarlas). Esas 4 referencias SON aplicaciones web (HTML/CSS/JS) — reconstruir la interfaz con la misma tecnología real, en vez de intentar imitarla con QSS, es la vía directa para llegar al nivel de pulido buscado sin seguir cazando bugs de composición de Qt uno por uno.

## Alcance propuesto (a validar/ajustar por orion-spec)

- La capa visual (ventana de chat: sidebar con historial, área de burbujas con Markdown/código, input bar, animaciones, temas claro/oscuro) se reconstruye como HTML/CSS/JS renderizado dentro de un WebView embebido en la app de escritorio existente.
- Python conserva el 100% de la lógica: orquestación del agente, memoria/historial (`ai/memory_manager.py`, incluyendo `delete_conversation()` ya implementada en REQ-014), voz (STT/TTS), seguridad (niveles verde/amarillo/rojo), scheduler, etc. — nada de esto se toca ni se reimplementa en JS.
- Comunicación Python↔JS vía un bridge (candidatos a evaluar por orion-architect: `QWebChannel` si se usa `QWebEngineView` de PyQt6, o el mecanismo de `js_api` si se usa `pywebview`) — JS nunca ejecuta lógica de negocio, solo dispara eventos que Python resuelve y responde.
- Evaluar en arquitectura 2 candidatos concretos, con sus trade-offs, antes de decidir (no asumir uno):
  - **`QWebEngineView`** (paquete `PyQt6-WebEngine`): Chromium embebido completo (~150-200MB de dependencia nueva), pero se integra como un QWidget más dentro de la `QMainWindow` YA EXISTENTE — permitiría conservar tal cual toda la infraestructura que SÍ viene funcionando bien en REQ-008/009/010/011/012 y en el propio REQ-014 (ventana frameless con resize/move nativo, ícono de bandeja del sistema, autostart de Windows, los `QThread`/`QRunnable` workers de voz con `WakeWordWorker`/`run_async`) — el cambio quedaría acotado a reemplazar el contenido central (los widgets de chat) por un `QWebEngineView`, sin rehacer el shell de la app.
  - **`pywebview`**: usa el WebView nativo del sistema (WebView2 de Edge en Windows, ya presente por defecto en Windows 10/11 actualizado) en vez de bundlear Chromium — dependencia más liviana, pero maneja su propia ventana/loop de eventos con soporte más limitado para ventana frameless custom, bandeja del sistema y integración con `QThread` — probablemente implicaría reescribir bastante del shell de la app (tray, autostart, threading de voz) que hoy funciona sobre PyQt6.
- Empaquetado (PyInstaller) sigue fuera de alcance, igual que en REQ-013/REQ-014.
- Los 43 criterios de aceptación de SPEC-014 son mayormente reutilizables como requisitos DE COMPORTAMIENTO (agnósticos de tecnología: historial funcional, Markdown+código resaltado, animaciones de entrada, atajos de teclado, indicador de escritura, integración de voz, gate de seguridad de los chips, contraste WCAG AA) — orion-spec debe revisarlos uno por uno y decidir cuáles se heredan tal cual (como requisito de comportamiento, reimplementado en HTML/CSS/JS) y cuáles ya no aplican por ser específicos de la implementación en QWidget descartada.

## Restricciones que se mantienen

- No modificar `core/`, `intent/`, `ai/` (salvo lo que YA está aprobado y committeado de REQ-014, no se reabre), `skills/`, `agents/`, `voice/`, `channels/` — el bridge Python↔JS solo debe CONSUMIR sus APIs públicas existentes, igual que hacía la UI de widgets.
- Sin empaquetado como instalable en este REQ.
- Rama de trabajo: a confirmar con el humano antes de crear una — no asumir que se reutiliza `feature/REQ-014-rediseno-ui-escritorio` (esa rama tiene todo el código de widgets que probablemente se descarta/reemplaza; podría ameritar una rama nueva, decisión a confirmar explícitamente, nunca asumida).
