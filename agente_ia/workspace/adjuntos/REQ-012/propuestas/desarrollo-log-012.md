# Desarrollo REQ-012

**Fecha:** 2026-08-05
**Agente:** orion-dev
**Arquitectura de referencia:** `workspace/adjuntos/REQ-012/propuestas/arquitectura-012.md` (aprobada, sin ajustes)

## Archivos modificados

- `agente_ia/config_manager.py` — `weather_city` agregada a `DEFAULT_CONFIG`, backfill
  en `load_config()`, funciones nuevas `get_weather_city()` / `set_weather_city()`
  (CA-01, CA-02).
- `agente_ia/ui/widgets/weather_card.py` — import de `config_manager`; `_fetch()` lee
  `config_manager.get_weather_city()` y la pasa como argumento posicional extra a
  `run_async(get_weather_structured, self._on_done, self._on_error, city)` (CA-03,
  CA-04).
- `agente_ia/ui/widgets/center_panel.py` — import de `QTimer`; `_GREETING_REFRESH_MS =
  60_000` a nivel de módulo; `_build_ui()` captura `self._display_name` (antes variable
  local) y arranca `self._greeting_timer = QTimer(self)` al final del método; método
  nuevo `_refresh_greeting()` que reevalúa el saludo con `self._display_name` y solo
  llama `setText()` si el texto cambió (CA-06, CA-07, CA-08, CA-09).

## Archivos de test modificados/creados

- `agente_ia/tests/test_config_manager_weather_city.py` (nuevo) — 4 tests: default
  vacío (CA-01), persistencia con `.strip()` (CA-02), backfill de config vieja sin
  `weather_city` (CA-01), y `DEFAULT_CONFIG["weather_city"] == ""`. Mismo patrón que
  `tests/test_config_manager_display_name.py` (redirige `CONFIG_FILE` a `tmp_path`).
- `agente_ia/tests/test_gui_widgets.py` — agregados en las secciones correspondientes
  (sin tocar la sección `REQ-011/CA-04` al final del archivo, que sigue sin commitear
  de otro REQ):
  - Sección `WeatherCard`: 2 tests nuevos (CA-03, CA-04) que parchean
    `ui.widgets.weather_card.run_async` y monkeypatchean
    `config_manager.get_weather_city`, verificando el último argumento posicional
    recibido por `run_async`.
  - Sección `CenterPanel`: 4 tests nuevos — timer arranca activo con intervalo 60000ms
    (CA-06), timer parenteado al widget (CA-09), `_refresh_greeting()` no repinta si el
    texto no cambió (CA-07), y `_refresh_greeting()` actualiza el label al disparar
    manualmente `timeout.emit()` simulando cruce de franja horaria (CA-08).

## Dependencias agregadas

Ninguna. `requirements.txt` sin cambios (`QTimer` ya es parte de `PyQt6.QtCore`, ya
usado en `ui/widgets/system_status_card.py`).

## Decisiones de implementación

Ninguna desviación respecto a `arquitectura-012.md` — los snippets literales de la
propuesta (config_manager.py, weather_card.py, center_panel.py) se implementaron tal
cual, incluyendo la decisión de diseño ya aprobada por Johan de reusar
`self._display_name` capturado una sola vez en `_build_ui()` sin releer config en cada
tick del `QTimer`.

## Verificación local

```
python -m py_compile config_manager.py ui/widgets/weather_card.py \
    ui/widgets/center_panel.py tests/test_config_manager_weather_city.py \
    tests/test_gui_widgets.py
```
→ compila sin errores (5/5 módulos).

```
python -m pytest tests/ --tb=short -q
```
→ **226 passed, 0 failed, 3 warnings** (mismas 3 advertencias pre-existentes
documentadas en `baseline-012.md`: 2 `DeprecationWarning` de `speech_recognition`
en librería de terceros, 1 `PytestReturnNotNoneWarning` en
`tests/test_agents.py::test_ca1_orchestrator`, fuera de alcance de este REQ).

Comparado contra el baseline (216 passed, 0 failed): **+10 tests nuevos, 0
regresiones** — 4 de `test_config_manager_weather_city.py` + 2 de `WeatherCard` + 4 de
`CenterPanel` en `test_gui_widgets.py`.

## Checklist DoD (`.claude/rules/definition-of-done.md` — `orion-dev`)

- [x] Solo se implementó lo aprobado en arquitectura
- [x] Sin API keys/tokens hardcodeados
- [x] Sin `except: pass` silencioso
- [x] Sin prints de debug en código final
- [x] Sin dependencias nuevas (`requirements.txt` sin cambios)
- [x] No se tocaron skills (`BaseSkill` no aplica a este REQ)
- [x] Banner mostrado antes de escribir código
- [x] `desarrollo-log-012.md` generado (este archivo)
- [x] NO se ejecutó `git commit`
- [x] Mensaje de commit sugerido entregado (ver handoff)
