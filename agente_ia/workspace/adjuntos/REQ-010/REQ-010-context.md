# Contexto REQ-010 — Branding visual Noddoo (íconos + colores GUI)

## Resumen ejecutivo
Reemplazar el ícono genérico de Python por el logo de Noddoo (N azul con degradé) en el ícono
de ventana, la barra de tareas de Windows y la bandeja del sistema. Aplicar los colores del
degradé de forma consistente en los acentos visuales ya existentes de la GUI JARVIS de REQ-008
(botón activo, ícono de estado, etc.), sin rediseñar el layout ya hecho.

## Estado actual
- **Estado tracker:** ARQUITECTURA_APROBADA
- **Último agente:** orion-architect
- **Fecha última actualización:** 2026-08-05
- **Rama git:** feature/REQ-010-branding-noddoo
- **Categoría:** UI
- **Tipo de cambio:** MEJORA

## Decisiones tomadas
2026-08-05 | orion-coordinador | REQ creado — categoría=UI | Palabras clave: "GUI", "ícono", "bandeja del sistema", "PyQt6", "interfaz" (ver categoría UI en CLAUDE.md)
2026-08-05 | orion-coordinador | Split en dos REQs independientes (REQ-010 branding / REQ-011 auto-inicio) | Confirmado explícitamente por Johan vía pregunta relayada por la sesión orquestadora — criaterios de aceptación, testing y bloqueos distintos entre ambas features
2026-08-05 | orion-coordinador | Alcance = SOLO branding/colores sobre la GUI ya existente de REQ-008, NO rediseño de layout | Confirmado explícitamente por Johan (vía AskUserQuestion, relayado por la sesión orquestadora)
2026-08-05 | orion-coordinador | Logo va en TODOS los íconos: ventana, taskbar Y bandeja del sistema | Confirmado explícitamente por Johan
2026-08-05 | orion-spec | Formato de ícono Windows: generar `.ico` multi-resolución (16/32/48/256px) con Pillow a partir de `noddoo-icon-mark.png` durante `orion-dev` | Confirmado explícitamente por Johan, relayado por la sesión orquestadora
2026-08-05 | orion-spec | Caché de ícono de Windows: se documenta como limitación conocida del SO en "Casos borde" de la SPEC, no bloqueante, sin criterio de aceptación automatizado | Decisión técnica razonable por defecto, aplicada por la sesión orquestadora sin necesidad de preguntarle a Johan
2026-08-05 | orion-spec | Tono exacto de azul del degradé: sin valor hex fijo en la SPEC (Johan no lo proveyó) — `orion-dev` lo extrae de `noddoo-icon-mark.png` en desarrollo y lo fija como constante; validación de consistencia visual queda para QA/prueba manual, no test automatizado de hex exacto | Confirmado explícitamente por Johan
2026-08-05 | orion-spec | Recoloreo de wake word (REQ-009): opción (b) — se mantienen los emojis (`🎙`/`🟢`) sin cambios, solo se ajusta el color de fondo QSS del estado "escuchando" (`LISTENING_WAKE`, hoy `#4fc3ff`) al tono de marca; el verde de "despierto" (`#00e08a`) no se toca | Confirmado explícitamente por Johan
2026-08-05 | orion-spec | Alcance de acentos existentes confirmado: usos de `#4fc3ff` en `header_bar.py`, `center_panel.py` y `sidebar.py`; quedan fuera los verdes semánticos (`#33d17a`, `#00e08a`) y los grises de texto | Confirmado explícitamente por Johan
2026-08-05 | orion-spec | Ícono de bandeja del sistema: estático (siempre `noddoo-icon-mark.png`), sin variantes por estado — reactividad queda fuera de este REQ, evaluable como REQ futuro | Confirmado explícitamente por Johan
2026-08-05 | orion-spec | SPEC-010 aprobada tal cual, sin ajustes | Aprobado por Johan, relayado por la sesión orquestadora
2026-08-05 | orion-baseline | 6 archivos identificados a modificar (5 confirmados + 1 candidato) | Ver origen/baseline-010.md
2026-08-05 | orion-baseline | Hallazgo: `ui/widgets/system_status_card.py:41` usa el mismo azul `#4fc3ff`/`rgb(79,195,255)` (arco de progreso, `QPen` en código) pero SPEC-010 no lo lista en "Módulos afectados" ni CA-06 | Se documenta como candidato para que `orion-architect` decida explícitamente si entra en el alcance de recoloreo — no se asume ninguna respuesta
2026-08-05 | orion-baseline | py_compile limpio y pytest 197/197 pasando (0 fallos preexistentes) sobre los 6 módulos afectados | Ver origen/baseline-010.md, sección "Fallos pre-existentes"

## Descartado (y por qué)
- Rediseño de layout de la GUI JARVIS (REQ-008): descartado explícitamente por Johan — el alcance es solo branding/colores consistentes, no un rediseño visual.
- Un solo REQ combinando branding + auto-inicio: descartado — Johan confirmó partir en dos REQs (ver REQ-011) por tener bloqueos, testing y ciclos de vida distintos.

## Asumidos pendientes de confirmar
- Ninguno pendiente de la etapa de coordinación. `orion-spec` deberá definir con Johan detalles finos como: tamaños/resoluciones exactas de ícono requeridas por Windows (.ico multi-resolución vs .png), y si el tray icon debe reaccionar visualmente a estados (activo/escuchando/inactivo) usando variantes del logo o solo el logo estático.

## Riesgos activos
- Confirmado por `orion-baseline`: `assets/branding/` sigue sin existir en el repo (no aparece en
  ningún `Glob`) — el bloqueo de `orion-dev` descrito abajo sigue vigente sin cambios.
- **BLOQUEANTE PARA DESARROLLO (no para spec/arquitectura):** los 2 archivos de imagen del logo real
  (`assets/branding/noddoo-logo-full.png` con texto "Noddoo", y `assets/branding/noddoo-icon-mark.png`
  solo la "N") todavía NO existen en el repo. Johan los va a guardar en `assets/branding/` (carpeta
  que no existe todavía) recién al llegar a la etapa de `orion-dev`. `orion-spec` y `orion-architect`
  deben asumir que esos 2 archivos existirán ahí antes del desarrollo. `orion-dev` DEBE verificar su
  existencia antes de escribir código — si no están, reportar como bloqueado, NUNCA inventar o
  generar un logo placeholder.
- No hay empaquetado con PyInstaller/.spec en el repo (se corre `python main.py` directo) — esto
  puede limitar cómo se aplica el ícono a nivel de barra de tareas de Windows (asociación de
  ícono de proceso vs. ícono de ventana vía `setWindowIcon()`). `orion-architect` debe evaluar el
  impacto y documentar la solución técnica (p.ej. `ctypes` AppUserModelID para icono de taskbar
  correcto en python.exe sin empaquetar).

2026-08-05 | orion-architect | Ícono taskbar (CA-02): ctypes `SetCurrentProcessExplicitAppUserModelID` en main.py antes de crear QApplication + `setWindowIcon()` a nivel QApplication y QMainWindow, sin PyInstaller | Técnica estándar para PyQt no empaquetado en Windows; no garantiza 100% de casos — CA-02 ya es verificación manual en la SPEC. Fallback (PyInstaller) documentado pero NO recomendado activamente en este REQ; pendiente de confirmación de Johan solo si la prueba manual falla
2026-08-05 | orion-architect | Color de marca centralizado en módulo nuevo `ui/theme.py`: `BRAND_ACCENT_RGB` como única fuente de verdad, `BRAND_ACCENT_HEX` derivado programáticamente, `brand_accent_rgba(alpha)` para el caso de sidebar.py | Evita duplicar hex en 3 archivos QSS (CA-06) y evita que hex/rgb diverjan al mantenerse por separado
2026-08-05 | orion-architect | Extracción del tono de azul: script Pillow de un solo uso (dev-time) con promedio de color ponderado por canal alfa sobre `noddoo-icon-mark.png`, valor resultante copiado a mano como constante en `ui/theme.py` (no se recalcula en cada arranque) | Método determinista y reproducible, documentable en desarrollo-log-010.md, evita elegir un tono "a ojo"
2026-08-05 | orion-architect | `.ico` multi-resolución: `assets/branding/noddoo-icon.ico` generado con Pillow (`Image.save(format="ICO", sizes=[16,32,48,256])`) desde `noddoo-icon-mark.png` en modo RGBA (preserva alfa); reutilizado tanto para ícono de ventana como de bandeja | Cumple CA-04; un solo archivo, un solo punto de carga (`ui/theme.py::WINDOW_ICON_PATH`/`TRAY_ICON_PATH`)
2026-08-05 | orion-architect | Pillow ya está en requirements.txt — NO se agrega ninguna dependencia nueva | Confirmado leyendo requirements.txt (línea del bloque "Automatización del PC (pyautogui)")
2026-08-05 | orion-architect | `noddoo-logo-full.png` no tiene ningún consumidor de código en este REQ (solo se verifica su existencia por CA-05); únicamente `noddoo-icon-mark.png` alimenta el `.ico` | Evita que orion-dev asuma que debe insertar el logo-full en algún widget sin que la SPEC lo pida
2026-08-05 | orion-architect | Recomendación (pendiente de confirmación de Johan): incluir `ui/widgets/system_status_card.py:41` en el recoloreo por consistencia visual, aunque no está en "Módulos afectados" ni CA-06 de SPEC-010 aprobada | Es el mismo acento `#4fc3ff` que los otros 3 archivos migrados; dejarlo fuera crearía inconsistencia visual directa contra el objetivo de la SPEC. No se agrega como aprobado — orion-architect no expande unilateralmente el alcance de una SPEC ya aprobada
2026-08-05 | orion-architect | Arquitectura APROBADA por Johan tal cual, sin ajustes | Aprobación humana explícita relayada por la sesión orquestadora
2026-08-05 | orion-architect | RESUELTO — Johan confirmó explícitamente incluir `ui/widgets/system_status_card.py:41` en el recoloreo de REQ-010, como expansión de alcance respecto de SPEC-010 (no listado en "Módulos afectados" ni CA-06 de la SPEC aprobada) | Confirmación explícita de Johan al aprobar la arquitectura, relayada por la sesión orquestadora — `system_status_card.py` pasa de candidato/condicional a módulo confirmado a modificar; actualizado en propuestas/arquitectura-010.md (Módulos a modificar, CA-06, Punto 4, tabla de riesgos, pruebas sugeridas)

## Asumidos pendientes de confirmar
- 2026-08-05 | orion-architect | Si CA-02 (ícono de taskbar) falla en la prueba manual del humano pese al mecanismo ctypes+setWindowIcon propuesto, la única alternativa técnica adicional conocida es empaquetar con PyInstaller — decisión explícitamente diferida a Johan, no se implementa en este REQ salvo autorización posterior. **Sigue pendiente** (solo se activa si la prueba manual de CA-02 falla).
- 2026-08-05 | orion-architect | ~~Inclusión de `system_status_card.py` en el recoloreo~~ — **RESUELTO 2026-08-05**: Johan confirmó explícitamente la inclusión al aprobar la arquitectura (ver Decisiones tomadas). Ya no está pendiente.

## Log de transiciones
2026-08-05 | — → NUEVO | orion-coordinador | REQ creado, split confirmado por Johan, handoff a orion-spec
2026-08-05 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | Baseline documentado sin fallos preexistentes, handoff a orion-architect
2026-08-05 | EN_ARQUITECTURA → EN_ARQUITECTURA (esperando aprobación) | orion-architect | Propuesta técnica completa redactada en propuestas/arquitectura-010.md; pendiente aprobación humana explícita de Johan (incluye 2 puntos a confirmar: fallback CA-02 si falla prueba manual, e inclusión de system_status_card.py)
2026-08-05 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Johan aprobó la arquitectura tal cual y confirmó explícitamente incluir system_status_card.py en el recoloreo (expansión de alcance documentada). Rama de trabajo asignada: feature/REQ-010-branding-noddoo. Handoff a orion-dev con arquitectura=workspace/adjuntos/REQ-010/propuestas/arquitectura-010.md. Recordatorio para orion-dev: verificar CA-05 (los 2 PNG de assets/branding/ aún no confirmados en el repo) antes de escribir código, y documentar en desarrollo-log-010.md el mecanismo usado para CA-02 (taskbar) y el valor de color extraído para CA-06.
