# Auditoría QA REQ-014 — Rediseño completo desde cero UI escritorio NODDOO

**Agente:** orion-qa
**Fecha:** 2026-08-19
**Punto de partida:** `REQ-014-context.md` (historial completo: coordinador, spec con 8 rondas
de clarificación, baseline, arquitectura con 3 confirmaciones humanas explícitas,
desarrollo-log-014.md con 2 hallazgos propios), `SPEC-014.md` (43 CA), `arquitectura-014.md`
(494 líneas), `test-results-014.md` (43/43 PASS, verificado de forma independiente por
orion-tester, 366 passed/2 failed pre-existentes). Verificación realizada leyendo el código
real de los archivos tocados — no se da por buena ninguna cifra reportada por agentes previos
sin confirmarla acá.

---

## Seguridad

### `delete_conversation()` (`ai/memory_manager.py:502-526`)
Leída completa. Verificado:
- **Filtrado por `user_id` en el WHERE**: `DELETE FROM memories WHERE conversation_id = ? AND
  user_id = ?`, con `(conversation_id, user_id)` — no puede borrar conversaciones de otro
  usuario aunque adivinara el `conversation_id` (uuid4).
- **No lanza sobre conversación inexistente/ya borrada**: `cur.rowcount` en 0 retorna `False`
  sin excepción; el bloque `try/except Exception as e: logger.error(...); return False` cubre
  cualquier fallo de la conexión/consulta.
- **Logging**: `logger.info` en éxito (con conteo de filas), `logger.error` en fallo — ninguno
  de los dos casos es silencioso.
- **Confirmación de UI (CA-09)**: `ui/sidebar.py:Sidebar._on_delete_requested()` llama
  `self._confirm_delete()` ANTES de invocar `delete_conversation()`; `_confirm_delete()`
  levanta un `QMessageBox` con botón "Eliminar" en `DestructiveRole` y "Cancelar" en
  `RejectRole`, y solo retorna `True` si el botón clickeado es el de eliminar. Si el usuario no
  confirma, `_on_delete_requested()` retorna temprano sin tocar memoria. Cumple el espíritu del
  patrón amarillo aunque `delete_conversation()` en sí no pase por
  `security_manager.require_confirmation()` (ver nota de clasificación abajo).
- **Siempre vía `run_async()`**: nunca bloquea el hilo de Qt, confirmado en la llamada de
  `_on_delete_requested()`.
- **Caso borde (conversación activa borrada)**: `MainWindow._on_conversation_deleted()`
  dispara `_on_new_conversation()` si el id borrado coincide con el activo — estado consistente
  confirmado por lectura de código, con test dedicado (`test_conversation_deleted_activa_...`).

**Sobre la clasificación 🟢 Verde sin pasar por `orion-security`:** de acuerdo con la
decisión de `orion-architect` de tratarla como el mismo patrón que `clear_user_memory()`
(tampoco gateada por `security_manager`), con la siguiente precisión: la clasificación es
razonable dado el precedente ya existente y no cuestionado en el código actual, PERO técnicamente
"borrar una conversación completa" encaja mejor en la lista 🟡 Amarillo de
`.claude/rules/security-levels.md` ("Borrar archivos o carpetas" — análogo funcional a borrar
filas persistentes del usuario) que en 🟢 Verde. La mitigación real aquí es que la UI SÍ exige
confirmación explícita (`QMessageBox`) antes de invocar la función, que es exactamente lo que
`security-levels.md` pide para 🟡 Amarillo — solo que implementado a nivel de UI en vez de a
nivel del gate central (`security_manager.require_confirmation()`). Como esto reproduce
literalmente un patrón ya presente y no cuestionado en producción (`clear_user_memory()`), y la
decisión de no invocar `orion-security` fue razonada explícitamente por `orion-architect` y
aprobada por el humano, **no es motivo de rechazo** — se registra como observación no
bloqueante para un REQ futuro que revise el gateo consistente de todas las operaciones
destructivas de `ai/memory_manager.py` (`clear_user_memory`, `delete_conversation`) a través de
`security_manager`, en vez de depender de que cada UI individual recuerde confirmar.

### Chips del input bar (CA-40/CA-41) — `ui/input_bar.py`
Leído completo. Verificado:
- Los chips `kind="action"` (`take_screenshot`, `open_browser`) se ejecutan EXCLUSIVAMENTE vía
  `run_async(execute_action, self._on_action_done, self._on_action_error, chip["payload"],
  channel=ChannelType.DESKTOP, user_id="default")` (`_on_chip_clicked`, líneas 315-332). No hay
  ningún import ni invocación directa de la función subyacente en este archivo.
- El badge de color (`_risk_color()` + `_paint_risk_dot()`) es **puramente informativo**: pinta
  un `QLabel` de 8x8px con `setStyleSheet(f"background-color: {color}; ...")`. No participa en
  ninguna rama condicional que decida si la acción se ejecuta o no — el gate real sigue siendo
  `execute_action()` → `security_manager` en la capa de `agents/action_registry.py`, fuera de
  este REQ y sin tocar.
- `_risk_color()` es fail-closed: acción no clasificada → `danger`, nunca verde por defecto.
  Consistente con el resto del sistema.
- Confirmado con `test_input_bar.py`: el test de chips verifica `call_count == 0` de la función
  directa, solo pasa por `run_async(execute_action, ...)`.

**Conclusión: el badge no reemplaza el gate real. CA-40/CA-41 cumplidos correctamente.**

### `ui/gui.py` — shim de compatibilidad
Leído completo (33 líneas). Contiene únicamente `GLOBAL_STATE`, `WAKE_STATE`,
`update_gui_state()`, `update_wake_state()` — cero lógica de UI real (no hay clases `QWidget`,
no hay `JarvisMainWindow`, no hay `WakeWordWorker`, ambos movidos a `ui/main_window.py` y
`ui/workers.py` respectivamente). No quedó nada que debería haberse movido y no se movió.
Confirmado que `ui/main_window.py` lo importa con `import ui.gui as gui_state` (nunca `from
ui.gui import GLOBAL_STATE`), consistente con la necesidad de leer el valor mutado en vivo.

### `render_markdown()` / `QTextBrowser` (CA-12)
`ui/message_bubble.py:89` fija `setOpenExternalLinks(False)` explícitamente en el
`QTextBrowser` de `role="assistant"` — un link dentro de una respuesta de la IA no puede abrir
el navegador sin pasar por el gate de seguridad (comentario explícito "CA-41 — nunca navega
directo"). `render_markdown()` genera HTML autocontenido (CSS inline, sin `<script>`, sin
carga de recursos externos) — `QTextBrowser.setHtml()` no ejecuta JavaScript. Superficie de
riesgo acotada correctamente.

### Secretos
`grep` dirigido (patrón `(api[_-]?key|secret|password|token)\s*=\s*['"]`) sobre los 9 archivos
nuevos de `ui/` + `ui/components/*.py` + los 6 archivos modificados (`ai/memory_manager.py`,
`main.py`, `ui/gui.py`, `ui/theme.py`, `ui/widgets/*.py` borrados, `requirements.txt`): **sin
hallazgos**. No se asumió que la revisión de `orion-dev` fuera suficiente.

### Niveles de riesgo — resumen
- **Verde (puede actuar):** navegación entre conversaciones, colapso de sidebar, cambio de
  tema, animaciones, renderizado de Markdown, drag&drop de metadata de archivo (sin leer
  contenido), toggle de modo manos libres (consumo de API pública existente).
- **Amarillo (debe confirmar):** `delete_conversation()` — SÍ implementa confirmación de UI
  (`QMessageBox`) antes de ejecutar, pese a no pasar por `security_manager` (ver observación no
  bloqueante arriba). Los chips `action` (`take_screenshot`, `open_browser`) heredan su
  clasificación real de `security_manager.classify_action()` sin cambios — ambos GREEN hoy, sin
  acción YELLOW/RED nueva expuesta desde esta UI (confirmado, coincide con lo declarado por
  arquitectura).
- **Rojo (no ejecuta):** ninguna acción roja nueva se expone desde esta UI.
- **Se implementaron confirmaciones:** sí, para `delete_conversation()` vía `QMessageBox`.

### Logging
- `except Exception as e: logger.error(...)` en `delete_conversation()`, en
  `WakeWordWorker.run()` (`ui/workers.py:52`), y en el resto de excepciones nuevas del REQ.
- El único `except:` sin `logger` encontrado en los archivos tocados por REQ-014 es
  `ui/sidebar.py:75` (`_relative_date()`, `except ValueError: return ""`) — parseo de un
  timestamp mal formado en una función auxiliar puramente cosmética (fecha relativa de un
  ítem del sidebar), sin impacto funcional ni de seguridad; no oculta un error real del sistema,
  solo un formato de fecha no reconocible. No se considera `except: pass` silencioso en el
  sentido que la regla busca prevenir (ocultar fallos operativos) — es un fallback de
  presentación. No bloqueante.
- `ai/memory_manager.py:459` (`get_recent_summaries`, `except Exception: return []`) es código
  **pre-existente**, no tocado por este REQ — confirmado con `git diff eb190b3 --
  ai/memory_manager.py`, que muestra únicamente la adición de `delete_conversation()` (26
  líneas). Fuera del alcance de esta auditoría (CA-29 prohíbe explícitamente tocar el resto del
  archivo).
- `main.py:173-174` (`except Exception: pass`) y los 3 `print()` en `main.py:207/217/221` son
  también código pre-existente, confirmado con `git diff eb190b3 -- main.py`: el único cambio
  real en ese archivo es el bloque de import/creación de ventana (líneas 190-199) y el cambio de
  `showMaximized()` a `resize()+show()`. Fuera de alcance.

---

## Niveles de riesgo
- Verde (puede actuar): navegación UI, temas, animaciones, Markdown, drag&drop de metadata, voz (toggle, consumo de API existente).
- Amarillo (debe confirmar): `delete_conversation()` (confirmación de UI implementada).
- Rojo (no ejecuta): sin acciones rojas nuevas expuestas.
- Se implementaron confirmaciones: sí.

---

## Logging
Sin `except: pass` silencioso introducido por este REQ. Los 2 fixes propios de `orion-dev`
(autoscroll en `ui/chat_area.py`, crash de `fade_theme_transition()` en `ui/animations.py`)
están documentados con logging/comentarios adecuados y no introducen manejo de errores
silencioso — `fade_theme_transition()` deliberadamente no engancha `anim.finished` (decisión
razonada y documentada en el propio docstring, no un error tragado).

---

## Consistencia de código
- **Type hints:** presentes en todas las funciones públicas y privadas revisadas
  (`ui/main_window.py`, `ui/sidebar.py`, `ui/input_bar.py`, `ui/animations.py`,
  `ui/message_bubble.py`, `ui/components/markdown_renderer.py`, `ai/memory_manager.py:
  delete_conversation`).
- **Imports:** orden estándar → third-party → locales respetado en los archivos revisados
  (ejemplo: `ui/sidebar.py` — `logging`/`datetime`/`string`/`typing` → `PyQt6` → `config_manager`/
  `ui.*`).
- **`os.system()`/`subprocess`:** sin hallazgos en los archivos tocados por este REQ.
- **Prints de debug:** sin hallazgos en código nuevo (los 3 `print()` de `main.py` son
  pre-existentes, fuera de alcance).
- **Dead code:** sin hallazgos — `ui/gui_workers.py` se dejó intacto deliberadamente (documentado,
  fusionarlo hubiera sido churn fuera de alcance); `voice_orb`/`VoiceOrb` solo aparece en
  comentarios documentando el retiro (confirmado por `orion-tester`, no re-verificado línea por
  línea acá porque no hay ambigüedad posible en un `grep` de texto).
- **`requirements.txt`:** actualizado correctamente con `markdown` y `Pygments`, sin pin de
  versión, consistente con el resto del archivo.
- **Cobertura de tests de `delete_conversation()`:** confirmada — 6 tests dedicados en
  `tests/test_conversation_memory.py` (borra todas las filas, filtra por `user_id`, no lanza
  sobre inexistente, no lanza sobre ya borrada, string vacío no toca la DB, no afecta otras
  conversaciones).

---

## Veredicto: ✅ COMPLETADO

Los 43 criterios de aceptación fueron verificados PASS de forma independiente por
`orion-tester` y no se encontró ningún hallazgo de seguridad, logging o convenciones que
justifique un rechazo. Los 3 puntos de atención señalados explícitamente en el handoff de este
REQ fueron verificados por lectura directa del código real (no solo por lo declarado en el
desarrollo-log):

1. `delete_conversation()` SÍ tiene confirmación de UI (`QMessageBox`) antes de ejecutarse y SÍ
   está restringida por `user_id` en el `WHERE` — no puede borrar conversaciones ajenas.
2. Los chips de acceso directo pasan exclusivamente por
   `run_async(execute_action, ..., channel=ChannelType.DESKTOP)`; el badge de color (CA-40) es
   puramente informativo y no participa en el gate real.
3. `ui/gui.py` quedó como shim genuino de ~33 líneas, sin lógica de UI residual.

Una observación no bloqueante queda registrada para consideración futura: la clasificación
🟢 Verde de `delete_conversation()` (heredada del precedente de `clear_user_memory()`) encaja
mejor conceptualmente en 🟡 Amarillo de `security-levels.md`; la mitigación real existe (UI
exige confirmación), pero vive fuera del gate central `security_manager`. No amerita rechazar
este REQ porque reproduce un patrón ya presente y no cuestionado en producción, y la decisión de
no invocar `orion-security` fue razonada y aprobada explícitamente por el humano — se deja
constancia para un REQ de seguridad futuro que unifique el gateo de operaciones destructivas de
`ai/memory_manager.py`.

**Siguiente paso: validación manual del humano antes de LISTO_PARA_COMMIT.**

---
---

# Auditoría QA REQ-014 — addendum §7 (2ª pasada)

**Agente:** orion-qa
**Fecha:** 2026-08-19
**Punto de partida:** Johan rechazó la validación manual de la 1ª pasada (43/43 CA, QA
✅ COMPLETADO arriba) por un bug visual real (panel derecho con texto superpuesto y
bleed-through del escritorio) + pidió eliminar el panel derecho y un refinamiento visual
medible contra 4 referencias (WorkBuddy AI, DeepSeek, ChatGPT, Claude). `orion-architect`
redactó el addendum §7 de `arquitectura-014.md` (líneas 498-825), aprobado por Johan tal
cual con 2 confirmaciones explícitas (`git rm` de las 5 tarjetas/panel, tema claro como
default). `orion-dev` lo implementó (`desarrollo-log-014.md`, sección "addendum §7 (2ª
pasada)"), `orion-tester` lo re-verificó — 8/8 puntos de máxima atención PASS
(`pruebas/test-results-014.md`, sección "addendum §7 (2ª pasada)"). Esta sección **no
reescribe nada de la auditoría de la 1ª pasada arriba** — audita solo lo nuevo de esta 2ª
pasada, sobre los 4 puntos señalados explícitamente en el handoff, más el checklist
estándar. Verificación hecha por lectura directa del código real y comandos propios — no
se dio por buena ninguna cifra reportada por agentes previos sin confirmarla acá.

## 1. Fix del bug (§7.1) — `WA_StyledBackground`

Leído `ui/main_window.py` completo alrededor de la creación de `root`/`WindowRoot`
(líneas 220-226) y `body`/`WindowBody` (líneas 235-241).

- **Es la causa raíz, no un parche que oculta el síntoma.** El diagnóstico de
  `arquitectura-014.md` §7.1 es verificable en el propio framework Qt: un `QWidget` base
  no pinta `background-color`/`border`/`border-radius` de su QSS salvo que se le fije
  `Qt.WidgetAttribute.WA_StyledBackground = True` (comportamiento documentado de Qt, no
  una peculiaridad de este código). `root`/`body` son instancias planas de `QWidget`
  (`root = QWidget()`, línea 220; `body = QWidget()`, línea 235) — ninguna subclase, sin
  `paintEvent()` propio que ya compensara la ausencia del atributo (confirmado con grep:
  cero `def paintEvent` en `ui/main_window.py`). El fix (`setAttribute(...,
  WA_StyledBackground, True)` en ambos, líneas 225/240) actúa exactamente en el punto
  donde Qt decide si pinta o no el fondo declarado — no enmascara el síntoma con, por
  ejemplo, un color forzado por código o un widget adicional superpuesto. Es la
  corrección correcta al nivel correcto.
- **Sin efecto secundario de rendering en otros widgets.** `root`/`body` no tienen
  hijos que dependan de ver el escritorio o el widget padre a través suyo — su función es
  precisamente pintar el fondo opaco de la app (`root`) y de la zona de contenido
  (`body`, hoy transparente a propósito, documentado en el comentario de línea 237-239
  como tratamiento defensivo, no un cambio de comportamiento actual). `WA_TranslucentBackground`
  sigue aplicado solo a `self` (`MainWindow`, línea 198) — el fix no lo toca ni lo
  contradice, actúa en una capa distinta de la jerarquía (el widget central, no la
  ventana top-level), consistente con el patrón estándar de Qt para ventanas frameless
  con esquinas redondeadas (fondo translúcido a nivel ventana + un contenedor interno con
  `WA_StyledBackground` que pinta la forma real). Ningún otro widget de la jerarquía
  (`Sidebar`, `ChatArea`, `InputBar`, `_TitleBar`) es hijo directo de un widget cuyo
  atributo se tocó de forma que cambie su propio comportamiento de pintado — siguen
  siendo `QFrame`/subclases que ya pintaban su propio QSS antes del fix, sin relación con
  `WA_StyledBackground` de sus ancestros. Confirmado también por la captura
  `screenshot-addendum7-widget-grab.png` (abierta y revisada): sin artefactos de pintado
  nuevos en ningún widget visible (sidebar, burbujas, input, barra de título). **Sin
  hallazgos.**

## 2. `git rm` de los 5 archivos del panel derecho — limpieza confirmada

- **`git status --short`** confirma los 5 archivos (`ui/widgets/right_panel.py`,
  `system_status_card.py`, `quick_actions_card.py`, `recent_activity_card.py`,
  `weather_card.py`) en estado `D ` (staged deletion, `git rm` real).
- **Sin consumidores en código de producción.** `grep -rn` dirigido sobre
  `RightPanel|right_panel|SystemStatusCard|QuickActionsCard|RecentActivityCard|WeatherCard`
  contra todo `*.py` del repo: los únicos hits son `ui/theme.py`, `ui/main_window.py`,
  `ui/workers.py`, `tests/test_main_window.py`, `tests/test_theme.py`,
  `tests/test_wake_word_gui.py` — los 6 confirmados por lectura de línea como
  comentarios/docstrings que documentan el retiro (mismo patrón que ya vive en el código
  desde el retiro de `voice_orb`), ninguno es un import ni una invocación real. Único hit
  fuera de comentarios: `tests/_tmp_manual_verify_012.py` (`from
  ui.widgets.weather_card import WeatherCard`) — verificado con `git log --oneline` y
  `git status --short` sobre ese path específico: el archivo se commiteó en `eb190b3`
  (anterior a REQ-014), sin diferencias hoy respecto a ese commit, y no matchea el patrón
  `test_*.py` de pytest (nombre empieza con `_`, no recolectado) — confirmado que no es
  una regresión de este REQ ni un import roto que afecte la suite real. No bloqueante,
  mismo criterio ya aplicado a `_tmp_manual_verify_012b.py` en la 1ª pasada.
- **Las funciones de datos subyacentes siguen intactas y con sus tests propios sin
  tocar.** `git diff eb190b3 -- system_actions/system_info.py` y
  `git diff eb190b3 -- tests/test_system_info_numeric.py`: ambos **sin diferencias**,
  archivo y test exactamente iguales a antes de REQ-014. `ai/memory_manager.py:
  get_recent_summaries()` (líneas 451-460) leído completo — sigue presente, firma y
  cuerpo sin cambios; `git diff eb190b3 -- tests/test_memory_manager_recent.py`: también
  **sin diferencias**. El único cambio real de `ai/memory_manager.py` frente a `eb190b3`
  en todo el REQ (1ª + 2ª pasada) sigue siendo exclusivamente `delete_conversation()` (26
  líneas, confirmado con el diff completo del archivo) — nada del código que las
  tarjetas consumían fue tocado ni removido. Si un REQ futuro reactiva un panel de estado
  similar, la capa de datos está intacta y probada de forma independiente. (Nota
  incidental, no bloqueante: `get_recent_summaries()` usa `except Exception: return []`
  sin logging — es código pre-existente no tocado por REQ-014, ya señalado como fuera de
  alcance en la auditoría de la 1ª pasada arriba; se repite la constancia acá porque
  quedó de nuevo a la vista al verificar este punto, no es un hallazgo nuevo.)
  **Sin hallazgos bloqueantes.**

## 3. Incidente de privacidad (captura real accidental) — nota de trazabilidad

Durante la verificación visual manual del fix de §7.1, `orion-dev` reportó (ver
`REQ-014-context.md`, entrada 2026-08-19, y `desarrollo-log-014.md` "Decisiones de
implementación" #4) que un primer intento de captura usó `PIL.ImageGrab.grab()` (captura
real de pantalla del sistema operativo) y capturó por accidente contenido ajeno al
usuario — con apariencia de una videollamada de trabajo en curso — en vez de,o además de,
la ventana de la app. `orion-dev` reportó haber borrado el archivo de inmediato, sin
distribuirlo ni describir su contenido más allá de lo necesario para el registro, y
repitió la verificación con `QWidget.grab()` (`MainWindow.grab()`), que renderiza
exclusivamente el árbol de widgets propio de la app a través del pipeline de pintado de
Qt y nunca toca la pantalla real — captura final conservada en
`pruebas/screenshot-addendum7-widget-grab.png`.

Este handoff indica que ya se verificó de forma **independiente y fuera de este
pipeline** (humano/Claude Code) que no quedó ningún archivo de ese incidente en el
repositorio ni en ubicaciones típicas de capturas/temporales del sistema, y que no hace
falta que `orion-qa` re-verifique ese punto. Se deja esta nota explícita únicamente para
que el incidente quede trazado en el historial del REQ, en línea con
`.claude/rules/python-style.md` (seguridad en código) y el espíritu de
`.claude/rules/security-levels.md` (privacidad de terceros no es una acción clasificable
verde/amarillo/rojo del propio sistema, pero el manejo — detectar, borrar, no distribuir,
no describir de más, cambiar de método — es exactamente la respuesta esperada ante una
exposición accidental de datos ajenos). **No es un hallazgo que rechace este REQ — ya
está resuelto y cerrado.** Se registra por transparencia, no como pendiente.

## 4. Tema claro como default — `config.json` como dato persistido

- **Mismo argumento ya validado en REQ-013 5ta pasada, re-verificado acá contra el
  código real de REQ-014, no asumido por precedente.** `ui/theme.py:resolve_theme_name()`
  (líneas 158-169) leída completa: normaliza cualquier valor no confiable proveniente de
  `config.json` (`raw = config_manager.get_ui_theme()`) contra el allowlist estricto
  `THEMES` — cualquier valor fuera de ese diccionario cae a `DEFAULT_THEME` con
  `logger.warning(...)`, nunca deja pasar un string arbitrario hacia la selección de
  paleta. Esta función **no fue tocada** por el addendum §7 — el único cambio real es el
  valor de `DEFAULT_THEME` (línea 149: `"dark"` → `"light"`), que es exactamente el
  fallback que usa `resolve_theme_name()` cuando el valor no es válido, no una ruta nueva
  de validación.
- **Los 3 puntos confirmados con grep + lectura directa:** `ui/theme.py:149`
  (`DEFAULT_THEME = "light"`), `config_manager.py:21`
  (`DEFAULT_CONFIG["ui_theme"] = "light"`, única línea tocada del diccionario, confirmado
  que `get_ui_theme()`/`set_ui_theme()` —líneas ~130 y ~136 — no cambiaron de lógica) y
  `config.json:10` (`"ui_theme": "light"`, el dato real persistido en el repo).
- **No introduce ningún vector nuevo.** Cambiar `config.json` es tocar un archivo de
  datos/runtime, no solo código — pero es el mismo mecanismo que `set_ui_theme()`/CA-37
  ya usa para persistir la preferencia del usuario; no se inventa un canal nuevo de
  entrada, se fija el valor inicial una sola vez, y sigue pasando por el mismo
  `resolve_theme_name()` de siempre en cada lectura. Reversible con un clic en el toggle
  de tema ya existente en `_TitleBar`. **Sin hallazgos.**

## Checklist estándar (2ª pasada) — secretos, `except: pass`, logging, convenciones

- **Secretos:** `grep` dirigido (patrón `(api[_-]?key|secret|password|token)\s*=\s*['"]`)
  sobre los archivos tocados en esta 2ª pasada (`ui/main_window.py`, `ui/chat_area.py`,
  `ui/input_bar.py`, `ui/theme.py`, `ui/components/avatar.py`, `config_manager.py`,
  `config.json`): sin hallazgos.
- **`except: pass` silencioso:** `grep -n "except"` sobre los mismos 6 archivos de
  código: `ui/main_window.py`, `ui/chat_area.py`, `ui/input_bar.py`, `ui/theme.py`,
  `ui/components/avatar.py` — **cero bloques `except` nuevos** (ninguno de los 5 archivos
  tiene manejo de excepciones propio en esta pasada). `config_manager.py` solo tiene los
  3 `except` ya pre-existentes (líneas 8, 56, 65), sin relación con el cambio de esta
  pasada (que se limita a una línea de `DEFAULT_CONFIG`) — todos con logging o
  recuperación explícita, ninguno nuevo.
- **Logging:** sin operaciones nuevas que requieran logging adicional en esta pasada —
  `WA_StyledBackground` es una propiedad de rendering sin rama de error posible,
  `git rm`/eliminación de archivos no ejecuta código en runtime, y los cambios de QSS/
  paleta/avatar son valores estáticos sin camino de fallo.
- **Convenciones de código:** type hints, orden de imports y ausencia de `os.system()`/
  `subprocess` sin validar ya verificados en la 1ª pasada para los archivos base; los
  cambios de esta 2ª pasada son ediciones puntuales (atributos Qt, constantes, valores de
  QSS/paleta/config) sin funciones nuevas que requieran type hints propios, salvo
  `ui/components/avatar.py` donde el cálculo de `_DEFAULT_TEXT` reutiliza
  `config_manager.get_agent_name()[:1].upper()` (ya tipado en su origen). Sin dead code
  ni `print()` de debug introducidos — confirmado por lectura directa de los 6 archivos.
- **Compilación:** `python -m py_compile ui/main_window.py ui/chat_area.py
  ui/input_bar.py ui/theme.py ui/components/avatar.py config_manager.py` corrido por
  este agente: **OK**, sin errores.

## Niveles de riesgo (2ª pasada)
- Verde (puede actuar): todo lo tocado en esta pasada — rendering de fondo
  (`WA_StyledBackground`), eliminación de un panel puramente informativo sin gate de
  seguridad propio, ajustes de QSS/tipografía/espaciado, valor inicial de tema (siempre
  filtrado por `resolve_theme_name()`), avatar con inicial derivada de configuración
  existente. Ninguno introduce una acción ejecutable nueva.
- Amarillo (debe confirmar): ninguno nuevo en esta pasada — `delete_conversation()` (ya
  auditado en la 1ª pasada arriba) no fue tocada (`git diff eb190b3 --
  ai/memory_manager.py` idéntico a la 1ª pasada).
- Rojo (no ejecuta): ninguno.
- Se implementaron confirmaciones: N/A para esta pasada — sin acciones destructivas
  nuevas que confirmar (`git rm` es una operación de desarrollo, no una acción del
  sistema en runtime).

## Veredicto (addendum §7, 2ª pasada): ✅ COMPLETADO

Los 4 puntos de máxima atención señalados en el handoff se verificaron por lectura
directa del código real, no por confianza en lo reportado por `orion-dev`/`orion-tester`:
(1) `WA_StyledBackground` es la causa raíz corregida en el punto exacto donde Qt decide
pintar o no el fondo declarado por QSS — no un parche cosmético — y no tiene efecto
secundario de rendering sobre ningún otro widget de la jerarquía (root/body son
`QWidget` planos sin `paintEvent` propio ni hijos que dependieran de verlos a través).
(2) El `git rm` de los 5 archivos del panel derecho es limpio — cero consumidores reales
en código de producción, y las funciones de datos subyacentes
(`system_actions/system_info.py`, `ai/memory_manager.py:get_recent_summaries`) están
intactas con sus tests propios sin ninguna diferencia respecto al commit base, listas
para un REQ futuro que quiera reactivar un panel similar. (3) El incidente de privacidad
de la captura de pantalla accidental queda documentado y trazado en esta auditoría por
transparencia — ya resuelto y cerrado, verificado de forma independiente fuera de este
pipeline, no bloquea este REQ. (4) El tema claro como default en `config.json` no abre
ningún vector nuevo: sigue pasando por el mismo allowlist estricto de
`resolve_theme_name()`, que no fue tocado por esta pasada — solo cambia el valor inicial
de fallback. Checklist estándar (secretos, `except: pass`, logging, convenciones) sin
hallazgos nuevos sobre los 6 archivos tocados en esta 2ª pasada. Compilación limpia.

**Sin hallazgos bloqueantes. No se ejecutó `git commit`.**

**Siguiente paso: pedir a Johan que repita la prueba manual final — misma
captura+4 referencias que motivaron el addendum, esta vez con la app visible en un
escritorio real (el único punto que `QWidget.grab()` no puede confirmar por sí solo). Al
recibir OK, se mueve a `LISTO_PARA_COMMIT` y se entrega el mensaje de commit sugerido.**

---
---

# Auditoría QA REQ-014 — fix bloqueante "no puedo escribir instrucciones" (3ª pasada)

**Agente:** orion-qa
**Fecha:** 2026-08-19
**Punto de partida:** Johan rechazó la 2ª validación manual (addendum §7 ya con QA
✅ COMPLETADO arriba) reportando un bug funcional bloqueante nuevo: "no puedo escribir
instrucciones". `orion-dev` investigó sobre la app real (descartó por revisión estática +
`QTest` que `_ComposerTextEdit`/`InputBar` tuvieran algún defecto) y encontró la causa
raíz real, geométrica: `DEFAULT_WINDOW_SIZE = (1280, 800)` fijo en `ui/main_window.py`
nunca se validaba contra `screen().availableGeometry()`; en pantallas con menos de 800px
lógicos de alto disponibles, la ventana frameless se abre más alta que el área visible e
`InputBar` (pegado al borde inferior) queda fuera del área clickeable. Fix: nuevo método
`MainWindow.fit_size_to_screen()`, usado por `main.py` antes de `resize()`. `orion-tester`
re-verificó — 9/9 PASS (`pruebas/test-results-014.md`, sección "fix bloqueante ... (3ª
pasada)"). Esta sección audita **solo** este fix puntual — no reescribe nada de las 2
auditorías anteriores (43 CA + addendum §7, ambas ✅ COMPLETADO, sin re-tocar).

Verificación hecha por lectura directa del código real (`ui/main_window.py`, `main.py`,
`tests/test_main_window.py`, `tests/test_main.py`) y grep propios — no se dio por buena
ninguna cifra reportada por `orion-dev`/`orion-tester` sin confirmarla acá, y se agregaron
los 3 chequeos puntuales pedidos explícitamente en el handoff (caso degenerado de tamaño
0/negativo, proporcionalidad del alcance, residuos de instrumentación de diagnóstico).

## 1. `fit_size_to_screen()` no puede producir tamaño 0 o negativo

Leído completo (`ui/main_window.py:497-530`):
```python
available = self.screen().availableGeometry()
min_size = self.minimumSize()
clamped_width = max(min_size.width(), min(width, available.width()))
clamped_height = max(min_size.height(), min(height, available.height()))
return clamped_width, clamped_height
```
- El resultado siempre pasa por un `max(min_size.<dim>(), ...)` como última operación —
  **estructuralmente no puede devolver menos que `minimumSize()`**, sin importar qué
  devuelva `available.width()`/`available.height()`. Si `availableGeometry()` devolviera
  un valor degenerado (0, negativo, o cualquier valor menor al mínimo — el escenario
  exacto que pide auditar el handoff), `min(width, available.width())` bajaría hasta ese
  valor degenerado, pero el `max()` exterior lo vuelve a subir hasta `min_size.width()`
  antes de retornar. No hay ninguna rama de código posterior a este cálculo que pueda
  volver a bajarlo.
- `minimumSize()` en sí **no puede ser 0** en este punto de ejecución:
  `_init_ui()` (línea 223, primera línea del método, se ejecuta antes que cualquier otra
  cosa en `__init__`) fija `self.setMinimumSize(1024, 640)` de forma incondicional, sin
  ninguna rama que lo deje sin fijar — confirmado que no cambió en este fix (`git diff` de
  esta pasada no toca esa línea, es la misma desde la 1ª pasada de REQ-014). Por lo tanto
  `min_size.width()`/`min_size.height()` en `fit_size_to_screen()` son siempre `1024`/`640`
  como piso mínimo real.
- **No hay ninguna excepción posible en el cuerpo del método** que pudiera propagarse sin
  capturar: `self.screen()` es un método de `QWidget` que en PyQt6 devuelve el `QScreen`
  actual (nunca `None` para una ventana ya con `show()`/`_init_ui()` corrido — y en el
  único punto donde se llama, `main.py:204`, ya se llamó `MainWindow()` completo antes),
  `availableGeometry()`/`minimumSize()` son getters de Qt que no lanzan, y `max()`/`min()`
  sobre ints no lanzan. No hace falta (ni sobra) un `try/except` acá — no hay operación
  arriesgada que envolver.
- **Verificado también empíricamente, no solo por lectura**: el propio `orion-tester`
  corrió el caso pantalla `(800, 480)` — más chica que `minimumSize()` en ambas
  dimensiones — y confirmó `(1024, 640)` como resultado exacto
  (`test_fit_size_to_screen_nunca_baja_del_minimo`, releído completo por este agente,
  líneas 239-248 de `tests/test_main_window.py`). Es el caso más cercano al escenario
  degenerado que pide el handoff, y el piso funciona. Ningún test ejercita
  `availableGeometry()` devolviendo directamente `(0, 0)` o negativo, pero dado que la
  garantía viene de la estructura algebraica del `max()` exterior (no de que
  `available.width()` sea razonable), no hace falta un test específico para ese caso —
  agregar uno sería redundante con lo que ya prueba la lógica, no una laguna real. **Sin
  hallazgos: no hay ningún camino, ni con datos degenerados de `availableGeometry()`, que
  produzca un tamaño 0/negativo o una excepción sin capturar en el arranque.**

## 2. Proporcionalidad del fix — alcance no se sobre-corrigió

- **Diff de esta pasada acotado exactamente a lo necesario**: `git status --short`
  confirma que, de los archivos de producción, solo `ui/main_window.py` y `main.py`
  aparecen modificados en esta 3ª pasada (el resto de archivos `M`/`D`/`??` del working
  tree pertenecen a las 2 pasadas previas de REQ-014, ya auditadas). Dentro de
  `ui/main_window.py`, el cambio real es: (a) el método nuevo `fit_size_to_screen()`
  (34 líneas, casi todas de docstring documentando la causa raíz — 9 líneas de código
  real), y (b) un comentario ampliado sobre `DEFAULT_WINDOW_SIZE` (línea 59-66,
  sin cambiar el valor `(1280, 800)` en sí). **Ningún otro método de `MainWindow` se
  tocó** — confirmado leyendo `resize_edge_at()`, `_init_ui()`, `changeEvent()`,
  `mousePressEvent()`/`mouseMoveEvent()` (resize/move de ventana), `_TitleBar`: idénticos
  a la 2ª pasada, sin relación con el bug geométrico.
- **En `main.py`, un solo cambio de una línea**: `window.resize(*DEFAULT_WINDOW_SIZE)` →
  `window.resize(*window.fit_size_to_screen(*DEFAULT_WINDOW_SIZE))` (línea 204), dentro
  del bloque `if not tray_mode:` ya existente. `--tray` sin cambios (no llama
  `resize()`/`show()`, correcto: el bug geométrico no aplica a ese modo, confirmado
  leyendo el bloque completo líneas 190-213). **No se tocó ningún otro punto de
  `main.py`** — ni el resto del arranque, ni `_desktop_confirm`, ni el loop principal.
- **Nada de layout/posicionamiento se tocó fuera de lo estrictamente necesario para el
  tamaño de ventana** (chequeo explícito pedido por el handoff): `grep -n "setGeometry\|
  move(\|setFixedSize\|resizeEvent"` sobre `ui/main_window.py` de esta pasada muestra que
  `resizeEvent()`, `changeEvent()`, `resize_edge_at()`, `mousePressEvent`/`mouseMoveEvent`
  (drag/resize de ventana) son exactamente los mismos que en la 2ª pasada — sin
  modificaciones. `ChatArea`/`InputBar`/`Sidebar` (donde vive el layout real de contenido)
  no aparecen en el diff de esta pasada en absoluto. El fix es puramente "qué tamaño le
  pido a `resize()`", no "cómo se distribuye el contenido dentro de ese tamaño" — el
  alcance correcto para un bug puramente geométrico de apertura. **Sin sobre-corrección:
  el fix es proporcional exactamente al problema diagnosticado.**

## 3. Sin instrumentación/diagnóstico residual de las mediciones Win32

El handoff señala específicamente que `orion-dev` usó mediciones Win32 (`GetWindowRect`,
etc.) para diagnosticar el bug — riesgo de que quedara código de instrumentación temporal
olvidado en producción.

- `grep -rn "win32\|ctypes\|GetWindowRect\|pyautogui\|ImageGrab\|breakpoint(" ui/main_window.py main.py`:
  **cero resultados** en ambos archivos. No hay imports de `win32gui`/`win32api`/
  `ctypes`/`pyautogui`, ni llamadas sueltas a APIs de diagnóstico.
- `grep -n "print(" ui/main_window.py`: cero resultados — sin `print()` de debug nuevo.
  `main.py` conserva sus 3 `print()` pre-existentes (líneas ~211/217/221, confirmados
  fuera de alcance de REQ-014 desde la 1ª auditoría) — ninguno nuevo de esta pasada.
- `grep -n "except" ui/main_window.py`: cero resultados — el archivo completo no tiene
  ningún bloque `except` (consistente con que `fit_size_to_screen()` es cálculo puro sin
  rama de error, ver punto 1). `main.py` conserva el único `except Exception as e:
  print(...)` ya auditado en la 1ª pasada (línea ~210, fallback de importación de GUI a
  modo headless) — pertenece al bloque `try` que ya envolvía `window.resize(...)` antes
  de este fix, no es código nuevo de instrumentación.
- El docstring de `fit_size_to_screen()` documenta la investigación (escalado 150%,
  `devicePixelRatio`, coordenadas Win32) **en texto**, no en código ejecutable — es
  documentación permanente para que un REQ futuro no repita la investigación, consistente
  con lo que el propio dev-log recomienda ("Docstring con el detalle completo... para que
  un REQ futuro no la repita"). No es instrumentación olvidada, es la causa raíz
  documentada a propósito.
- Tests nuevos (`tests/test_main_window.py:220-248`, releídos completos): usan
  `monkeypatch.setattr(window, "screen", lambda: _fake_screen(...))` con un
  `MagicMock`/`QRect` — mecanismo de mock estándar de pytest, no queda ninguna llamada
  real a una API de Windows en la suite. **Sin hallazgos: ningún resto de instrumentación
  de diagnóstico en los archivos de producción ni en los tests.**

## Checklist estándar (3ª pasada) — secretos, `except: pass`, logging, convenciones

- **Secretos**: `grep` dirigido (patrón `(api[_-]?key|secret|password|token)\s*=\s*['"]`)
  sobre `ui/main_window.py`, `main.py`, `tests/test_main_window.py`, `tests/test_main.py`:
  sin hallazgos.
- **`except: pass` silencioso**: `ui/main_window.py` no tiene ningún bloque `except` (ver
  punto 3). El único `except` de `main.py` en el camino tocado por esta pasada
  (`except Exception as e: print(f"[GUI] No disponible, modo headless: {e}"); headless =
  True`) es pre-existente, ya auditado como fuera de alcance en la 1ª pasada, y de todos
  modos **no es silencioso** — registra el error vía `print()` y cambia de forma explícita
  a modo headless en vez de tragarse la excepción. No introduce nada nuevo esta pasada.
- **Logging**: sin operaciones nuevas que requieran logging — `fit_size_to_screen()` es
  cálculo puro sin rama de error posible (mismo razonamiento que la 2ª pasada aplicó a
  `WA_StyledBackground`).
- **Convenciones de código**: `fit_size_to_screen(self, width: int, height: int) ->
  tuple` tiene type hints en los parámetros; el tipo de retorno anotado como `tuple` (sin
  parametrizar `tuple[int, int]`) es menos preciso que el resto del archivo pero no
  incumple la regla (`python-style.md` pide type hints, no exige genéricos
  parametrizados) — no bloqueante. Imports sin cambios (no se agregó ningún import
  nuevo). Sin dead code: `DEFAULT_WINDOW_SIZE` se sigue usando activamente como valor de
  entrada de `fit_size_to_screen()`, no quedó huérfano.
- **Compilación**: `python -m py_compile ui/main_window.py main.py
  tests/test_main_window.py tests/test_main.py` corrido por este agente: **OK**, sin
  errores.

## Niveles de riesgo (3ª pasada)
- Verde (puede actuar): todo lo tocado en esta pasada — cálculo de tamaño de ventana en el
  arranque, sin ninguna acción ejecutable ni acceso a datos del usuario. No introduce
  superficie de riesgo nueva.
- Amarillo (debe confirmar): ninguno nuevo — `delete_conversation()` no fue tocada en esta
  pasada (fuera del diff de `ui/main_window.py`/`main.py`).
- Rojo (no ejecuta): ninguno.
- Se implementaron confirmaciones: N/A — sin acciones destructivas en esta pasada.

## Veredicto (fix bloqueante, 3ª pasada): ✅ COMPLETADO

Los 3 puntos de máxima atención señalados explícitamente en el handoff se verificaron por
lectura directa del código real: (1) `fit_size_to_screen()` no puede producir un tamaño
0/negativo ni una excepción sin capturar en ningún escenario, incluido uno degenerado de
`availableGeometry()` — la garantía es estructural (`max()` exterior contra
`minimumSize()`, que a su vez está fijado incondicionalmente a `(1024, 640)` antes de que
el método pueda invocarse), no dependiente de que la pantalla real se comporte bien; un
crash acá dejaría a Johan sin poder abrir la app, y ese escenario queda descartado por
construcción del código, no solo por los tests. (2) El fix es proporcional al problema:
el diff de esta pasada se limita a un método nuevo de cálculo puro en
`ui/main_window.py` y una línea en `main.py` que lo invoca antes de `resize()` — ningún
otro método toca layout/posicionamiento, y `ChatArea`/`InputBar`/`Sidebar` (donde vive el
contenido real) no aparecen en el diff de esta pasada. (3) Sin residuos de la
instrumentación Win32 usada para diagnosticar: sin imports de `win32gui`/`ctypes`/
`pyautogui`, sin `print()` de debug nuevo, sin `except` nuevo en `ui/main_window.py` (el
archivo no tiene ninguno) — el detalle de la investigación quedó documentado como texto
en el docstring, no como código ejecutable olvidado. Checklist estándar (secretos,
`except: pass`, logging, convenciones) sin hallazgos nuevos. Compilación limpia.

**Sin hallazgos bloqueantes. No se ejecutó `git commit`.**

**Siguiente paso: pedir a Johan la 3ª validación manual final — que pueda efectivamente
escribir y enviar un mensaje en la app real. Al recibir OK, se mueve a
`LISTO_PARA_COMMIT` y se entrega el mensaje de commit sugerido. Si el bug persistiera,
`desarrollo-log-014.md` ya deja preparado qué pedirle a Johan (resolución de pantalla +
% de escalado de Windows) para reproducir con el mismo `fit_size_to_screen()` exacto.**
