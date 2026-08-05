# Baseline REQ-008 — Rediseño GUI estilo "JARVIS" a pantalla completa

**Fecha:** 2026-08-04
**Agente:** orion-baseline
**SPEC de referencia:** `workspace/adjuntos/REQ-008/spec/SPEC-008.md` (CA-01 a CA-17)

## Estado actual del sistema

### `ui/gui.py` (237 líneas)
Widget PyQt6 único, `JarvisGUI(QWidget)`:
- `setFixedSize(400, 400)`, `FramelessWindowHint | WindowStaysOnTopHint`,
  `WA_TranslucentBackground` — ventana flotante sin bordes, siempre encima, NO maximizada,
  NO tiene layouts (`QHBoxLayout`/`QVBoxLayout`/`QGridLayout`) ni sidebar ni tarjetas.
- Toda la UI se dibuja a mano en `paintEvent()` con `QPainter`: rejilla hexagonal, glow
  circular, anillos HUD, "núcleo de energía", línea de escaneo y texto de estado —
  ~150 líneas de dibujo custom que el rediseño reemplaza por completo.
- Estado cross-thread: variable global module-level `GLOBAL_STATE = "IDLE"` (línea 16),
  mutada por `update_gui_state(new_state)` (llamada desde el hilo daemon en `main.py:154-157`
  dentro de un `try/except Exception` que solo hace `logger.debug` si la GUI no está
  disponible) y leída cada 100ms por `self.state_poll` (`QTimer`, línea 44-46) → método
  `poll_state()` (polling puro, ninguna señal Qt cross-thread). Los 4 estados válidos son
  literales de string: `"IDLE"`, `"LISTENING"`, `"PROCESSING"`, `"RESPONDING"` (dict `colors`
  en `paintEvent`, línea 95-100).
- `_setup_tray_icon()`: crea `QSystemTrayIcon` con menú "Mostrar/Ocultar" / "Salir".
  `closeEvent()` (línea 210-218) hace `event.ignore()` + `self.hide()` + notificación de
  bandeja — el botón "×" nunca termina el proceso; solo el ítem "Salir" del menú de bandeja
  (`QApplication.instance().quit`) lo hace.
- Arrastre manual de ventana vía `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`
  (necesario hoy porque no hay barra de título nativa — el mockup SÍ trae barra de título
  estándar, así que este bloque queda obsoleto con el rediseño).
- Import de nivel de módulo: `from config_manager import get_agent_name` (línea 13), usado en
  `init_ui()` para el título de ventana y tooltip de bandeja — es la única dependencia externa
  real del archivo hoy.
- Bloque `__main__` (línea 233-237): permite correr `python ui/gui.py` standalone para
  pruebas visuales aisladas.

### `ui/cli.py` (44 líneas)
Clase `CLI` sin relación de herencia ni imports compartidos con `ui/gui.py` — dos
implementaciones completamente independientes de "interfaz". Expone
`get_input_method()/get_text_command()/get_voice_command()/display_output()`. Importa
`ui.stt.transcriber`, `ui.tts_engine`, `ui.personality.format_response`,
`config_manager.get_agent_name`. SPEC-008 excluye explícitamente tocar este archivo (fuera de
alcance) — confirmado que no comparte estado ni lógica con `ui/gui.py`, por lo que el
rediseño de la GUI no debería tener efectos colaterales aquí.

### `main.py` — construcción de ventana e hilos
- `if __name__ == "__main__":` (línea 182-221): parsea `--headless`. Si NO headless (bloque
  línea 189-197), importa `from ui.gui import QApplication, JarvisGUI`, construye
  `QApplication(sys.argv)` y `JarvisGUI()`, y llama `window.show()` — **todo en el hilo
  principal**, dentro de un `try/except Exception` que degrada a headless si la GUI falla al
  construirse (p. ej. sin entorno gráfico).
- La lógica del asistente (`main()`, el loop CLI/voz) se lanza en
  `threading.Thread(target=jarvis_runner, daemon=True)` (línea 199-216) — **hilo separado**,
  nunca el principal.
- `app.exec()` (línea 219) solo se llama si `not headless`; si headless, se hace
  `jarvis_mind.join()` (línea 221) y no se construye ningún objeto Qt — confirma CA-15
  (modo headless sin cambios de comportamiento) como comportamiento ya vigente hoy.
- Único punto de comunicación hilo-trabajador → GUI ya localizado: línea 153-157
  (`from ui.gui import update_gui_state; update_gui_state("PROCESSING")`), envuelto en
  `try/except Exception` — es el patrón que cualquier GUI nueva debe seguir replicando (o
  evolucionando sin romper), nunca instanciar widgets Qt fuera del hilo principal.
- `memory.store(...)` se llama dos veces por interacción (categoría `"interaction"` y
  `"semantic"`, líneas 166-172) — relevante para CA-09: la fuente de datos de "Actividad
  reciente" ya existe y se puebla en cada turno, solo falta el método de lectura por
  recencia.

### `system_actions/system_info.py`
Todas las funciones (`get_cpu_info`, `get_ram_info`, `get_disk_info`, `get_network_info`, …)
devuelven **strings multilínea formateados para voz/chat**, ninguna devuelve un valor
numérico puro reutilizable por un widget. `_has_psutil()` (línea 15-20) ya contempla el caso
de `psutil` no instalado, contemplado también en los casos borde de SPEC-008. Confirmado:
`psutil` SÍ está instalado (v7.2.2, ya validado por `orion-spec`, revalidado ahora indirectamente
por el `py_compile` limpio de este módulo). No existe hoy ninguna función que devuelva
CPU/RAM/Disco/Red como `float`/`dict` — habrá que agregarlas sin tocar las funciones de texto
existentes (usadas por la skill conversacional y comandos de voz).

### `skills/weather_skill.py`
`WeatherSkill(BaseSkill)` con intent `GET_WEATHER`. `execute()` llama a
`https://wttr.in/{city}?format=3` (solo texto plano de una línea, timeout=5s,
`except Exception` genérico que devuelve un mensaje de error amigable). No usa `format=j1`
(JSON) en ningún punto del archivo — confirmado que la variante estructurada
(temperatura/condición/ciudad/hora/fecha por separado) no existe todavía, tal como asumía
SPEC-008.

### `ai/memory_manager.py`
Singleton `UnifiedMemory` (patrón `__new__` + `_initialized`), expuesto como instancia
`memory` a nivel de módulo (línea 295, `memory = UnifiedMemory()`) — es el objeto que ya
importa `main.py`. Métodos de lectura existentes: `search_semantic()`, `search_keyword()`,
`get_important_memories()`, `get_summary()`, `get_recent_summaries()` (esta última es la más
cercana en nombre pero es de **resúmenes**, tabla `summaries`, no de interacciones crudas de
la tabla `memories`). Confirmado: no existe ningún método que devuelva "las N filas más
recientes de `memories` para un `user_id`, sin filtro de query ni umbral de `importance`" — el
método `get_recent()` que pide SPEC-008/CA-09 es 100% nuevo. La tabla `memories` ya tiene
columna `timestamp` (ISO, línea 118) y `category`/`source`, suficientes para construir el
query (`ORDER BY timestamp DESC LIMIT N`) sin cambios de esquema.

### `agents/action_registry.py`
`ACTION_REGISTRY: dict[str, dict]` (línea 212-240) con 18 acciones registradas. Confirmado
que `open_notepad`, `open_explorer`, `open_calculator`, `open_browser`, `take_screenshot` ya
existen y siguen el patrón `{"fn": ..., "desc": ..., "category": ...}`. `execute_action()`
(línea 250-266) es el único punto de ejecución: resuelve por nombre, llama
`security_manager.require_confirmation()` con `channel` pasado explícitamente por el caller
(nunca inferido de `params`) y solo entonces invoca la función. No existe ninguna acción
`open_spotify` ni ninguna referencia a Spotify en el archivo — confirmado que es 100% nueva,
tal como indica SPEC-008.

**Hallazgo relevante para orion-architect (no cubierto explícitamente por SPEC-008):**
`core/security_manager.py` mantiene, además de `ACTION_REGISTRY`, su propia lista independiente
de acciones clasificadas por nivel de riesgo. La función `_register_action_registry_actions()`
(`core/security_manager.py:355-370`) registra explícitamente como `RiskLevel.GREEN` cada
nombre literal de `ACTION_REGISTRY` (`open_chrome`, `open_notepad`, `open_explorer`,
`open_calculator`, `open_browser`, `close_window`, etc. — lista cerrada de 18 nombres, líneas
360-364). Desde REQ-005 el sistema es **fail-closed**: toda acción no clasificada
explícitamente se bloquea por defecto en `require_confirmation()`. Esto significa que agregar
`open_spotify` únicamente a `ACTION_REGISTRY` (como describe el módulo afectado en SPEC-008)
**no es suficiente** — si `orion-architect`/`orion-dev` no agregan también
`"open_spotify"` a la lista `green_actions` de `core/security_manager.py:360-364`, el botón de
Spotify quedará bloqueado por el gate fail-closed pese a estar registrado en
`ACTION_REGISTRY`, y CA-08 fallaría en la práctica. Se documenta como archivo adicional a
modificar (ver más abajo) — no estaba listado explícitamente entre los "Módulos afectados" de
SPEC-008.

### `ui/personality.py`
Módulo de frases fijas en español (`GREETINGS`, `ACKNOWLEDGEMENTS`, `ERROR_MESSAGES`, etc.) y
`get_random_greeting()` (línea 90-91): `random.choice(GREETINGS)`, sin ninguna lógica de hora
del día. `format_response()` (usado por `ui/cli.py`) es independiente y no se ve afectado por
este REQ. Confirmado: no existe ninguna función `Buenos días/tardes/noches` en el proyecto —
es funcionalidad 100% nueva, tal como asumía SPEC-008.

### `config_manager.py`
`load_config()`/`save_config()` sobre `config.json` (junto al módulo) + fallback a variables de
entorno vía `_ENV_KEY_MAP` para credenciales. `DEFAULT_CONFIG = {"agent_name": "glass"}` — el
único campo de identidad hoy es `agent_name` (default `"glass"`, no `"JARVIS"`). No existe
ninguna clave de config para el nombre del usuario a mostrar en el saludo (`display_name` o
similar) — confirmado que es una decisión 100% de `orion-architect`, tal como señala SPEC-008.

## Archivos que serán modificados (previsión)

Según los 17 CA de SPEC-008 y la verificación de código real de este baseline:

- `ui/gui.py` — reemplazo completo de la clase de ventana (CA-01, CA-02, CA-05, CA-11, CA-13,
  CA-14).
- `main.py` — actualizar el bloque de construcción de ventana (líneas ~189-197) a la nueva
  clase; preservar hilo principal/daemon (CA-14, CA-15).
- `system_actions/system_info.py` — agregar funciones numéricas nuevas (CPU/RAM/Disco/Red)
  sin tocar las funciones de texto existentes (CA-06).
- `skills/weather_skill.py` y/o `os_integration/weather_data.py` (nuevo) — función que
  consulta `format=j1` y devuelve campos estructurados (CA-10).
- `ai/memory_manager.py` — nuevo método `get_recent(user_id, limit)` (CA-09).
- `agents/action_registry.py` — nueva función `open_spotify` + entrada en `ACTION_REGISTRY`
  (CA-07, CA-08).
- **`core/security_manager.py`** — nueva entrada `"open_spotify"` en `green_actions` dentro de
  `_register_action_registry_actions()` (línea ~360-364); requerido para que CA-08/CA-16 no
  queden bloqueados por el gate fail-closed de REQ-005. **No estaba en la lista de módulos
  afectados de SPEC-008** — se señala explícitamente a `orion-architect` para que lo incorpore
  al diseño.
- `ui/personality.py` — nueva función de saludo dinámico por hora, sin tocar
  `get_random_greeting()` (CA-03).
- `config_manager.py` — posible nueva entrada de configuración para el nombre de usuario
  mostrado en el saludo (CA-04); fuente exacta a decidir por `orion-architect`.

No se prevé tocar: `ui/cli.py`, `voice/wake_word.py`, `core/resolution.py`,
`router/dispatcher.py`, `intent/classifier.py` — SPEC-008 los referencia como consumidos
(no modificados) por la barra de comando (CA-12) y `execute_action()` (CA-07).

Total de archivos previstos: **9** (8 explícitos en SPEC-008 + 1 hallazgo de este baseline:
`core/security_manager.py`).

## Fallos pre-existentes (no atribuibles a este REQ)

- **Ninguno.** `python -m py_compile` sobre los 10 módulos relevantes (los 8 de SPEC-008 +
  `core/security_manager.py` + `core/resolution.py`) terminó sin errores.
- `python -m pytest tests/ --tb=short` → **123 passed, 0 failed, 3 warnings** (advertencias de
  deprecación de `aifc`/`audioop` en la librería `speech_recognition`, no del código propio;
  y un `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator` por un
  `return` en vez de `assert` — preexistente, no relacionado con REQ-008).

**Observación de cobertura (no es un fallo, pero es relevante para `orion-tester`/DoD):**
Ninguno de los 8 módulos que este REQ va a modificar tiene hoy tests en formato pytest
(`test_*` recolectable). Existen `tests/test_autopilot.py` y `tests/test_memory.py`, pero son
scripts legacy con función `run_tests()` — pytest los recolecta con **0 items** (no fallan,
simplemente no se ejecutan como parte de la suite). En particular, `ai/memory_manager.py`
(donde se agregará `get_recent()`) solo tiene ese script legacy como cobertura indirecta. Esto
significa que el criterio CA-17 ("pytest no introduce ningún fallo nuevo") se mide sobre una
base de 123 tests que **no cubren directamente** ninguno de los archivos que van a cambiar —
`orion-dev`/`orion-tester` deberán escribir tests nuevos pytest-compatibles para el código
nuevo, por regla de `testing.md` ("nuevo código: toda función pública debe tener al menos un
test"), no solo confiar en que la suite actual siga en verde.

## Comportamiento actual de la funcionalidad (resumen ejecutable)

Hoy, al correr `python main.py` (sin `--headless`), aparece un HUD circular de 400x400,
sin bordes, siempre-encima, en la esquina donde Qt decida posicionarlo por defecto (sin
lógica de centrado/pantalla explícita en el código), que solo cambia de color/velocidad de
pulso según 4 estados y se puede arrastrar con el mouse. No hay sidebar, no hay tarjetas, no
hay accesos rápidos, no hay barra de comando en la GUI (los comandos de texto solo entran por
`ui/cli.py` en la consola). Cerrar la ventana la oculta a la bandeja; el proceso sigue vivo.
Este es el estado que SPEC-008 reemplaza por completo.
