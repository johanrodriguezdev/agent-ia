# Arquitectura REQ-012 — Fix ubicación de clima y saludo dinámico congelado en GUI JARVIS

**Fecha:** 2026-08-05
**Agente:** orion-architect
**SPEC de referencia:** `workspace/adjuntos/REQ-012/spec/SPEC-012.md` (CA-01 a CA-10)
**Baseline de referencia:** `workspace/adjuntos/REQ-012/origen/baseline-012.md`

## Decisión de fondo: replicar patrones ya existentes, sin código nuevo de infraestructura

Los dos bugs de REQ-012 tienen solución ya resuelta en el propio codebase:

1. El patrón `get_display_name()`/`set_display_name()` de `config_manager.py` (líneas 83-96) es
   exactamente lo que pide CA-01/CA-02 para `weather_city` — mismo `load_config().get(key, "")`,
   mismo `.strip()` sin `.lower()`, mismo `save_config()`.
2. El patrón `QTimer(self)` parentado al widget de `system_status_card.py` (líneas 61-64) es
   exactamente lo que pide CA-06/CA-09 para `CenterPanel` — Qt destruye y detiene el timer
   automáticamente cuando el widget padre se destruye, sin `closeEvent`/`__del__` manual.

Esta propuesta **no introduce ningún patrón nuevo**: aplica los dos ya validados por el propio
proyecto. Esto reduce superficie de riesgo (nada experimental) y mantiene consistencia de estilo
entre widgets.

### Decisión de diseño: el `QTimer` de `CenterPanel` reevalúa el saludo con el `display_name`
capturado en la construcción, no lo vuelve a leer de config cada 60s

SPEC-012 (CA-06) dice literalmente "llama a `get_time_based_greeting(display_name)` de nuevo" —
reutilizando el mismo `display_name`, no re-resolviéndolo. Se captura `self._display_name` una
sola vez en `_build_ui()` (vía `_resolve_display_name()`, sin cambios) y el callback del timer
reusa ese valor. Esto evita I/O de disco (`load_config()`) cada 60 segundos y evita un efecto
secundario no pedido por la SPEC (que el saludo cambie de nombre en caliente si el usuario edita
`display_name` mientras la ventana está abierta — fuera de alcance, no confirmado con Johan). Si
en el futuro se quiere que el nombre también se refresque, es un cambio de una línea, pero no es
lo que esta SPEC pide.

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `config_manager.get_weather_city() -> str` nueva, patrón idéntico a `get_display_name()`: `load_config().get("weather_city", "")`. `DEFAULT_CONFIG["weather_city"] = ""`. Backfill en `load_config()` (`if "weather_city" not in config: config["weather_city"] = DEFAULT_CONFIG["weather_city"]`) para configs guardados antes de este REQ, mismo mecanismo ya usado para `agent_name`/`agent_pronunciation`/`display_name`. |
| CA-02 | `config_manager.set_weather_city(city: str) -> None` nueva, patrón idéntico a `set_display_name()`: `config["weather_city"] = city.strip()` (sin `.lower()`) + `save_config(config)`. |
| CA-03 | `WeatherCard._fetch()` importa `config_manager`, lee `city = config_manager.get_weather_city()` y lo pasa como argumento posicional extra a `run_async(get_weather_structured, self._on_done, self._on_error, city)` — `run_async(fn, on_done, on_error, *args, **kwargs)` reenvía `city` a `fn(city)`, es decir `get_weather_structured(city)`. |
| CA-04 | Cuando `get_weather_city()` retorna `""` (default), se pasa igual como argumento posicional (`get_weather_structured("")`) — comportamiento idéntico al actual (`get_weather_structured` ya tiene default `city=""`), sin rama condicional adicional que pueda divergir. |
| CA-05 | `ui/personality.py` no se toca. `get_time_based_greeting()` mantiene firma y lógica; `tests/test_personality_greeting.py` no requiere ningún cambio. |
| CA-06 | `CenterPanel._build_ui()` agrega, al final del método, `self._greeting_timer = QTimer(self)`, `self._greeting_timer.timeout.connect(self._refresh_greeting)`, `self._greeting_timer.start(_GREETING_REFRESH_MS)` con `_GREETING_REFRESH_MS = 60_000` a nivel de módulo. `_refresh_greeting()` nuevo llama `get_time_based_greeting(self._display_name)`. |
| CA-07 | `_refresh_greeting()` compara el resultado contra `self._greeting_label.text()` antes de llamar `setText()` — si es igual, no toca el label (sin repintado innecesario). |
| CA-08 | `_refresh_greeting()` es un método normal invocable directamente en tests (sin depender de que pase tiempo real) y el timer expone `.timeout` como señal pública — un test puede hacer `panel._greeting_timer.timeout.emit()` para simular el disparo, o llamar `panel._refresh_greeting()` directo, tras mockear `ui.widgets.center_panel.get_time_based_greeting` para devolver un valor distinto. |
| CA-09 | `QTimer(self)` parentado al widget — mismo mecanismo ya en producción en `system_status_card.py` (líneas 61-64): Qt destruye (y por tanto detiene) el `QTimer` automáticamente cuando `CenterPanel` se destruye. Sin `closeEvent`/`__del__`/cleanup manual necesario. |
| CA-10 | Ningún cambio de este REQ toca lógica fuera de los 3 archivos de alcance; los cambios son aditivos (nuevas funciones/nuevo timer) sin modificar firmas ni comportamiento de funciones ya testeadas (`get_weather_structured`, `get_time_based_greeting`, `get_display_name`). `pytest tests/` debe seguir en 216+N passed (N = tests nuevos de este REQ), 0 regresiones. |

## Módulos a modificar

- `config_manager.py` — agregar clave `weather_city` a `DEFAULT_CONFIG`, backfill en
  `load_config()`, dos funciones nuevas `get_weather_city()`/`set_weather_city()`.
- `ui/widgets/weather_card.py` — importar `config_manager`; `_fetch()` lee la ciudad configurada
  y la reenvía a `get_weather_structured()` vía `run_async()`.
- `ui/widgets/center_panel.py` — importar `QTimer` de `PyQt6.QtCore`; capturar `display_name` en
  un atributo de instancia; agregar timer de refresco de 60s y su callback.

Sin cambios en `os_integration/weather_data.py` ni `ui/personality.py` (confirmado por baseline:
ya soportan lo que esta SPEC necesita).

## Nuevas clases/funciones

### `config_manager.py`

```python
DEFAULT_CONFIG = {
    "agent_name": "noddoo",
    "agent_pronunciation": "nodo",
    "display_name": "",
    "weather_city": "",
}
```

En `load_config()`, después del backfill de `display_name` (línea 47):
```python
if "weather_city" not in config:
    config["weather_city"] = DEFAULT_CONFIG["weather_city"]
```

Funciones nuevas (ubicar junto a `get_display_name()`/`set_display_name()`, líneas 83-96):
```python
def get_weather_city() -> str:
    """Return the configured city for the GUI weather panel (REQ-012/CA-01).

    Acceso de configuración puro — igual que `get_display_name()`. El fallback a
    geolocalización por IP cuando no hay ciudad configurada vive en
    `os_integration/weather_data.py` (`city=""`), no acá.
    """
    config = load_config()
    return config.get("weather_city", "")


def set_weather_city(city: str) -> None:
    config = load_config()
    config["weather_city"] = city.strip()
    save_config(config)
```

### `ui/widgets/weather_card.py`

```python
import config_manager
```
(agregado a los imports, junto a `os_integration.weather_data` y `ui.gui_workers`)

```python
def _fetch(self) -> None:
    city = config_manager.get_weather_city()
    run_async(get_weather_structured, self._on_done, self._on_error, city)
```

### `ui/widgets/center_panel.py`

```python
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
```
(agrega `QTimer` al import existente)

```python
_GREETING_REFRESH_MS = 60_000  # REQ-012/CA-06 — intervalo confirmado por Johan en SPEC-012
```
(constante a nivel de módulo, junto a `_STATE_STATUS_TEXT`)

En `_build_ui()`, reemplazar las líneas 65-66 actuales:
```python
display_name = _resolve_display_name()
greeting = get_time_based_greeting(display_name)
```
por:
```python
self._display_name = _resolve_display_name()
greeting = get_time_based_greeting(self._display_name)
```
(único cambio: pasa de variable local a atributo de instancia, para que
`_refresh_greeting()` pueda reusarlo sin releer config).

Al final de `_build_ui()` (después de `self.setStyleSheet(_CENTER_QSS)`, línea 116):
```python
self._greeting_timer = QTimer(self)
self._greeting_timer.timeout.connect(self._refresh_greeting)
self._greeting_timer.start(_GREETING_REFRESH_MS)
```

Método nuevo (ubicar junto a `set_state()`/`show_response()`):
```python
def _refresh_greeting(self) -> None:
    """Reevalúa el saludo cada `_GREETING_REFRESH_MS` (REQ-012/CA-06..CA-08).

    Reusa `self._display_name` capturado en `_build_ui()` — solo la franja horaria
    puede cambiar entre disparos, no el nombre. Solo repinta si el texto cambió
    (CA-07), para evitar renders innecesarios.
    """
    greeting = get_time_based_greeting(self._display_name)
    if greeting != self._greeting_label.text():
        self._greeting_label.setText(greeting)
```

## Flujo de datos

**Bug 1 — ciudad del clima:**
```
config.json (weather_city)
  → config_manager.get_weather_city()          [lectura de disco, hilo GUI, síncrona]
  → WeatherCard._fetch()                        [arma la llamada]
  → run_async(get_weather_structured, ..., city) [dispara worker en QThreadPool]
  → get_weather_structured(city)                 [hilo worker — I/O de red a wttr.in]
  → WorkerSignals.finished(WeatherData | None)   [señal Qt, entregada de vuelta al hilo GUI]
  → WeatherCard._on_done() → set_data()          [hilo GUI — actualiza labels]
```
Sin ciudad configurada, el flujo es idéntico al actual (`city=""` → wttr.in geolocaliza por IP)
— cero regresión para quien no configure nada.

**Bug 2 — saludo congelado:**
```
CenterPanel._build_ui()
  → _resolve_display_name() [una sola vez, se guarda en self._display_name]
  → get_time_based_greeting(display_name) → texto inicial en self._greeting_label
  → QTimer(self, 60000ms).start()

cada 60s, en el hilo de la GUI (QTimer vive y dispara en el mismo hilo que lo creó):
  → timeout signal → _refresh_greeting()
  → get_time_based_greeting(self._display_name)  [puro, usa datetime.now() interno]
  → compara con texto actual → setText() solo si cambió
```
No hay cruce de hilos en este flujo (a diferencia del clima) — `QTimer` normal (no
`QTimer` de otro hilo) emite `timeout` en el mismo hilo del event loop de Qt que lo inició, que
es el hilo de la GUI donde vive `CenterPanel`. No aplica el mecanismo de `run_async`/
`QThreadPool` usado para I/O de red.

## Archivos a modificar

- `config_manager.py`
- `ui/widgets/weather_card.py`
- `ui/widgets/center_panel.py`

## Dependencias nuevas

Ninguna. `QTimer` ya es parte de `PyQt6.QtCore`, ya usado en el proyecto
(`ui/widgets/system_status_card.py`). No se toca `requirements.txt`.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Timer huérfano de `CenterPanel` sobreviviendo a la destrucción del widget (fuga de memoria / callback contra un label ya destruido) | `QTimer(self)` parentado — mismo patrón ya en producción en `system_status_card.py`. Qt destruye y detiene el timer al destruirse el padre; no requiere `closeEvent` manual. Se agrega test que verifica `panel._greeting_timer.parent() is panel` como garantía estructural. |
| Thread-safety del `QTimer` de `CenterPanel` | No aplica cruce de hilos: a diferencia de `run_async`/`QThreadPool` (usado para I/O de red en `WeatherCard`), un `QTimer` estándar arrancado en el hilo de la GUI emite `timeout` en ese mismo hilo — no hay entrega "queued" entre hilos distintos ni necesidad de los cuidados de `ui/gui_workers.py`. Riesgo descartado, documentado para que `orion-dev` no agregue protección innecesaria. |
| `config_manager.get_weather_city()` agrega una lectura de disco síncrona en el hilo de la GUI antes de disparar `run_async()` | Mismo patrón ya aceptado hoy: `_resolve_display_name()` en `center_panel.py` ya hace `config_manager.get_display_name()` síncrono en el hilo de la GUI al construir el widget. Es una lectura de un `config.json` pequeño, sin impacto perceptible. No se propone cachear. |
| Backfill de `weather_city` mal ubicado rompe configs viejos (regresión de CA-01) | Backfill sigue el mismo bloque secuencial ya usado para las 3 claves existentes (líneas 42-47 de `config_manager.py`), agregado como cuarta condición — mismo test de regresión que ya existe para `display_name` (`test_load_config_backfills_display_name_for_old_config`) se replica para `weather_city`. |
| Confusión sobre si el saludo debe re-leer `display_name` de config en cada tick | Resuelto explícitamente arriba ("Decisión de diseño") — se captura una sola vez, coherente con la redacción literal de CA-06. Si Johan prefiere que también se refresque el nombre en caliente, es un ajuste de una línea a señalar en la aprobación. |
| Archivo compartido `tests/test_gui_widgets.py` con cambios sin commitear de REQ-011 (bandeja del sistema) | Ya identificado por `orion-baseline`. `orion-dev` debe agregar los tests nuevos de REQ-012 en las secciones correspondientes (`WeatherCard`, `CenterPanel`) sin tocar las líneas de REQ-011 al final del archivo. No requiere cambio de diseño, solo disciplina al editar. |
| Regresión en `test_center_panel_greeting_matches_personality_helper` (test existente, línea 153 de `tests/test_gui_widgets.py`) | El cambio de `display_name` (variable local → `self._display_name`) no altera el valor devuelto por `_build_ui()` en la primera evaluación — el test sigue pasando sin modificación, ya que solo lee `panel._greeting_label.text()` inmediatamente después de construir. |

## Pruebas sugeridas

- **CA-01** — `tests/test_config_manager_weather_city.py` (nuevo, mismo patrón que
  `tests/test_config_manager_display_name.py`): `test_get_weather_city_default_is_empty`
  (redirige `CONFIG_FILE` a `tmp_path`, sin escribir nada, `get_weather_city() == ""`).
- **CA-01 (backfill)** — `test_load_config_backfills_weather_city_for_old_config` — escribe un
  `config.json` sin `weather_city`, `load_config()["weather_city"] == ""`.
- **CA-02** — `test_set_weather_city_persists_and_strips_whitespace` — `set_weather_city("  Bogotá  ")`
  → `get_weather_city() == "Bogotá"` y el JSON en disco tiene `"weather_city": "Bogotá"`.
- **CA-03** — en `tests/test_gui_widgets.py`, sección `WeatherCard`: `with patch(
  "ui.widgets.weather_card.run_async") as mock_run_async:` + `monkeypatch.setattr(
  "ui.widgets.weather_card.config_manager.get_weather_city", lambda: "Medellín")`, construir
  `WeatherCard()`, `assert mock_run_async.call_args.args[-1] == "Medellín"` (mismo patrón ya
  usado en `test_quick_actions_card_click_calls_execute_action_via_channel`, líneas 84-94).
- **CA-04** — mismo test que CA-03 pero sin monkeypatchear `get_weather_city` (default `""`),
  `assert mock_run_async.call_args.args[-1] == ""`.
- **CA-05** — sin test nuevo: `tests/test_personality_greeting.py` se ejecuta sin modificar
  (parte de CA-10, suite completa en verde).
- **CA-06** — `test_center_panel_greeting_timer_starts_on_construction` — construir `CenterPanel`,
  `assert panel._greeting_timer.isActive()` y `assert panel._greeting_timer.interval() == 60_000`.
- **CA-07** — `test_center_panel_refresh_greeting_noop_if_unchanged` — monkeypatchear
  `ui.widgets.center_panel.get_time_based_greeting` para devolver el mismo texto que ya está en
  `_greeting_label`; espiar `_greeting_label.setText` (o comparar identidad del texto) y verificar
  que no se llama / no cambia.
- **CA-08** — `test_center_panel_refresh_greeting_updates_on_franja_change` — monkeypatchear
  `ui.widgets.center_panel.get_time_based_greeting` con un `MagicMock(side_effect=["Buenas tardes",
  "Buenas noches"])`, construir `CenterPanel` (consume el primer valor), luego
  `panel._greeting_timer.timeout.emit()` (disparo manual, sin esperar 60s reales) y
  `assert panel._greeting_label.text() == "Buenas noches"`.
- **CA-09** — `test_center_panel_greeting_timer_parented_to_widget` —
  `assert panel._greeting_timer.parent() is panel` (garantía estructural del mecanismo de
  auto-destrucción de Qt, mismo patrón aceptado para `system_status_card.py`).
- **CA-10** — `python -m pytest tests/ --tb=short` completo, ejecutado por `orion-tester`: debe
  reportar 0 fallos nuevos sobre el baseline de 216 passed.
