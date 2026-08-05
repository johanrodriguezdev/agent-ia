# Auditoría QA REQ-008 — Rediseño GUI estilo "JARVIS" a pantalla completa

**Fecha:** 2026-08-05
**Agente:** orion-qa
**Metodología:** lectura directa del código real de los 27 archivos tocados/creados
(no solo los resúmenes de `desarrollo-log-008.md`/`test-results-008.md`), más
verificación independiente de compilación y suite de tests.

## Seguridad

- **Gate único reutilizado, sin caminos nuevos.** `ui/widgets/quick_actions_card.py:_run_action()`
  llama exclusivamente `run_async(execute_action, ..., action_name, channel=ChannelType.DESKTOP,
  user_id="default")`. Ninguno de los 6 botones importa ni invoca directo `open_notepad`,
  `open_explorer`, etc. — confirmado leyendo el archivo completo (23 líneas de lógica,
  un solo punto de entrada). `agents/action_registry.py:execute_action()` (línea 277) es el
  único punto de ejecución: resuelve por nombre en `ACTION_REGISTRY`, llama
  `security_manager.require_confirmation()` **antes** de invocar `fn`, y solo entonces ejecuta
  la función subyacente. No hay ningún bypass.
- **Doble registro de `open_spotify` verificado en el código, no solo reportado.**
  - `agents/action_registry.py:245` — entrada en `ACTION_REGISTRY` (`"category": "app"`).
  - `core/security_manager.py:362` — `"open_spotify"` dentro de la lista `green_actions` de
    `_register_action_registry_actions()`, junto a las demás acciones de apertura de apps ya
    auditadas en REQ-005. Ninguna otra clasificación (YELLOW/RED) existente fue tocada.
  - Sin este segundo registro, `require_confirmation()` clasificaría `open_spotify` como
    `None` (sin registrar) y el gate fail-closed de REQ-005 la bloquearía — confirmado leyendo
    `require_confirmation()` línea 249-253. El hallazgo de `orion-baseline` está correctamente
    resuelto.
  - `tests/test_security_manager.py::test_green_actions_regression_free[open_spotify]` y
    `tests/test_action_registry_spotify.py::test_open_spotify_executes_via_execute_action_on_desktop`
    ejercitan el punto de entrada real (`execute_action`/`require_confirmation`), no solo la
    función suelta — verificado leyendo ambos tests completos, no son triviales
    (`assert True` / mocks vacíos).
- **`open_spotify()` en sí (agents/action_registry.py:108-128):** solo prueba 3 rutas de
  instalación conocidas y, si no existe ninguna, `webbrowser.open("https://open.spotify.com")`.
  Sin credenciales, sin control de reproducción, sin privilegios elevados — coincide
  exactamente con el patrón GREEN ya auditado en REQ-005 para acciones equivalentes
  (`open_chrome`, `open_browser`). Excepción capturada con `logger.error()` + mensaje de error
  al usuario, nunca `except: pass`.
- **Barra de comando (CA-12):** `ui/gui.py:_handle_command()` fija `channel=ChannelType.DESKTOP`
  de forma incondicional en el código, nunca lo infiere de `text` — respeta el invariante de
  seguridad documentado en `core/security_manager.py:239-246` (no se lee `channel` desde
  `extract_params()` de una skill/texto libre).
- **Regla de hilos del patrón `run_async()` nuevo (riesgo señalado por el architect):**
  revisados los 3 usos reales (`QuickActionsCard._run_action`, `WeatherCard._fetch`,
  `JarvisMainWindow._handle_command`) — en los tres casos `on_done`/`on_error` son métodos
  vinculados (`self._on_action_done`, `self._on_done`, `self._on_command_done`, etc.) de un
  `QFrame`/`QMainWindow` que vive en el hilo de la GUI, nunca funciones sueltas ni `lambda`
  que mute un widget desde fuera. `CallableWorker.run()` (leído completo,
  `ui/gui_workers.py:43-50`) ejecuta únicamente `fn(*args, **kwargs)` — jamás instancia ni
  toca un `QWidget`. Cumple la regla de diseño de `arquitectura-008.md`.
- **Restricción de hilo (CA-14):** `main.py:189-197` construye `QApplication`/
  `JarvisMainWindow` exclusivamente en el hilo principal, dentro del mismo bloque
  `if not headless:` de siempre; `jarvis_runner` (lógica del asistente) sigue en
  `threading.Thread(daemon=True)`. Sin cambios de este invariante.
- **Sin secretos hardcodeados:** `grep -i "api[_-]?key|token\s*=|secret|password\s*="` sobre
  `ui/`, `ui/widgets/`, `os_integration/weather_data.py` → sin resultados. `config_manager.py`
  solo mapea *nombres* de variables de entorno (`_ENV_KEY_MAP`), nunca valores literales.
  `weather_data.py` no usa ninguna API key (wttr.in sin autenticación, igual que la skill
  conversacional existente).
- **Sin el string "Johan" hardcodeado:** `grep -i "Johan"` sobre `ui/` → sin resultados.
  Verificado independientemente, no solo repetido del reporte de `orion-tester`.
- **Acciones destructivas / niveles de riesgo:** REQ-008 no introduce ninguna acción
  YELLOW/RED nueva. Las clasificaciones RED (10 categorías de REQ-005) y YELLOW existentes en
  `core/security_manager.py` no fueron alteradas — solo se agregó una línea a `green_actions`.
  Confirmado por lectura directa del archivo completo (líneas 300-353 intactas).

## Niveles de riesgo

- **Verde (puede actuar):** los 6 accesos rápidos de la GUI (`open_explorer`, `open_browser`,
  `open_notepad`, `open_calculator`, `take_screenshot`, `open_spotify` — nuevo), lectura de
  estado del sistema (CPU/RAM/Disco/Red vía `psutil`), consulta de clima (wttr.in, sin
  credenciales), lectura de memoria reciente (`get_recent()`, solo lectura SQLite local).
- **Amarillo (debe confirmar):** ninguno nuevo en este REQ.
- **Rojo (no ejecuta):** ninguno nuevo en este REQ; las 10 categorías existentes de REQ-005
  quedan intactas y sin modificar.
- **Se implementaron confirmaciones:** no aplica — ninguna acción nueva de este REQ requiere
  confirmación (todas GREEN). El gate (`require_confirmation()`) se invoca igual para todas,
  simplemente retorna `True` sin UI de confirmación para GREEN — comportamiento correcto y
  sin caminos que lo evadan.

## Logging

- `agents/action_registry.py:open_spotify()` — `logger.error()` en el único `except`, con
  mensaje descriptivo, nunca `except: pass`.
- `os_integration/weather_data.py:get_weather_structured()` — `logger.error()` en el único
  `except Exception as e`, retorna `None` explícito (nunca inventa datos).
- `ui/gui_workers.py:CallableWorker.run()` — `logger.error()` antes de emitir la señal
  `error`, con el nombre de la función fallida.
- `system_actions/system_info.py` (4 funciones nuevas) — cada una hace `logger.error()` antes
  de degradar a `0.0`/`(0, 0)`.
- `ai/memory_manager.py:get_recent()` — `logger.error()` en el `except`, retorna `[]`.
- Búsqueda global de `except:` / `except Exception:` sin cuerpo o con solo `pass` en los 27
  archivos del REQ: **sin resultados**. (Se encontraron `except Exception:` en otros módulos
  del repo — `channels/telegram_bot.py`, `ai/claude_brain.py`, `voice/wake_word.py`, etc. —
  ninguno tocado por REQ-008, fuera de alcance de esta auditoría.)
- Nota menor, no bloqueante: `ai/memory_manager.py:get_recent_summaries()` (línea 265, método
  preexistente NO tocado por este REQ) tiene un `except Exception: return []` sin logging —
  preexistente, no introducido ni modificado por REQ-008, no corresponde corregirlo en este QA.

## Consistencia de código

- Type hints presentes en prácticamente toda función/método público nuevo
  (`get_cpu_percent() -> float`, `get_weather_structured(city: str = "") -> Optional[WeatherData]`,
  `get_recent(self, user_id: str = "default", limit: int = 4, category: str = "interaction") ->
  List[MemoryItem]`, etc.). Los métodos `__init__(self, parent=None)` de los widgets Qt dejan
  `parent` sin anotar — es el patrón idiomático de PyQt6 en todo el ecosistema (incluido el
  `JarvisGUI` original preexistente), no una desviación real de `python-style.md`; se anota
  como observación cosmética, no bloqueante.
- Naming consistente: `snake_case` en funciones/variables, `PascalCase` en las ~10 clases
  nuevas (`JarvisMainWindow`, `CircularProgress`, `WorkerSignals`, `CallableWorker`, etc.),
  `UPPER_CASE` en constantes de módulo (`_QUICK_ACTIONS`, `_STATE_COLORS`, `_CARD_QSS`).
- Imports ordenados (estándar → third-party PyQt6 → locales) en los archivos revisados
  (`weather_data.py`, `gui_workers.py`, `quick_actions_card.py`, `center_panel.py`, `gui.py`).
- Sin `print()` de debug en ningún archivo del REQ — confirmado por grep dirigido sobre
  `ui/` (los `print()` existentes están en `ui/tts_engine.py`/`ui/stt/transcriber.py`/`ui/cli.py`,
  ninguno tocado por REQ-008).
- Una clase principal por archivo respetada en `ui/widgets/` (excepción justificada:
  `system_status_card.py` tiene `CircularProgress` + `SystemStatusCard`, documentado en
  arquitectura-008.md como "clases auxiliares pequeñas permitidas en el mismo archivo").
- Desviación menor documentada y aceptable: `_make_card_frame()` no se implementó como helper
  compartido (cada tarjeta se auto-estiliza) — justificación técnica razonable (testabilidad
  aislada), no afecta seguridad ni funcionalidad, documentada correctamente en
  desarrollo-log-008.md.

## Verificación de los 2 bugs preexistentes corregidos

1. **`config_manager.py:load_config()`** (líneas 35-48) — ambas ramas ("no existe archivo",
   "corrupto") ahora retornan `dict(DEFAULT_CONFIG)` (copia) en vez de `DEFAULT_CONFIG`
   (referencia al dict global). Cambio de una línea x2, estrictamente defensivo. No se coló
   ningún cambio adicional no aprobado — el resto de la función es idéntico a lo esperado por
   `arquitectura-008.md` (agrega solo `display_name` al esquema).
2. **`os_integration/weather_data.py`** (líneas 53-62) — `area_name[0].get("value", "")` en
   vez de `area_name[0]["value"]`, con comentario inline explicando el motivo. Alcance mínimo:
   solo la resolución de `city_name`/`region_name`/`country_name` usa `.get()` con default,
   el resto de la función (parseo de `temp_C`, `condition`, `time_str`/`date_str`) no fue
   tocado por esta corrección.
   - **Confirmada la observación no bloqueante de `orion-tester`:** el test
     `test_get_weather_structured_never_fabricates_default_city` usa `"nearest_area": [{}]`
     (área vacía), lo que hace que `area_name = area.get("areaName") or []` sea `[]` — la rama
     que realmente ejercita `.get("value", "")` (línea 60, cuando `areaName` está presente pero
     con una clave distinta a `"value"`) no se cubre con un caso de test exacto. El código sí
     es correcto por construcción (`.get()` con default nunca lanza `KeyError`
     independientemente de qué claves falten). No amerita RECHAZO — es una mejora de test
     recomendada, no un defecto de producción. Queda anotada para un REQ/ajuste futuro si se
     quiere cobertura exacta del caso límite.

Ninguna de las dos correcciones altera comportamiento aprobado en `arquitectura-008.md` ni
introduce alcance no pedido por `SPEC-008.md`.

## Verificación independiente (no solo repetición de reportes previos)

- `python -m py_compile` sobre los 11 archivos núcleo del REQ (`ui/gui.py`, `ui/gui_workers.py`,
  `ui/personality.py`, los 9 archivos de `ui/widgets/`, `main.py`,
  `system_actions/system_info.py`, `ai/memory_manager.py`, `agents/action_registry.py`,
  `core/security_manager.py`, `config_manager.py`, `os_integration/weather_data.py`) ejecutado
  de nuevo por `orion-qa`: **sin errores**.
- `python -m pytest tests/ --tb=short -q` ejecutado de nuevo por `orion-qa`, de forma
  independiente: **175 passed, 0 failed** — coincide exactamente con lo reportado por
  `orion-dev` y `orion-tester`.

## Veredicto: ✅ COMPLETADO

Seguridad revisada explícitamente y sin hallazgos bloqueantes: el gate de seguridad existente
(`execute_action()` → `security_manager.require_confirmation()`) se reutiliza sin excepción en
"Accesos rápidos", incluido `open_spotify`, con el doble registro (`ACTION_REGISTRY` +
`green_actions`) correctamente resuelto y cubierto por test de regresión. Sin secretos
hardcodeados, sin `except: pass` silencioso, sin acciones destructivas nuevas sin gate.
Logging adecuado en todo el código nuevo. Convenciones de `python-style.md` respetadas. Los
dos bugs preexistentes corregidos son reales, de alcance mínimo y no introducen desviación de
lo aprobado en arquitectura. Compilación y suite de tests (175/175) verificadas de forma
independiente por este agente, no solo repetidas de reportes anteriores.

Se solicita la prueba manual final del humano antes de emitir el mensaje de commit sugerido —
no se ejecuta `git commit` en ningún caso.
