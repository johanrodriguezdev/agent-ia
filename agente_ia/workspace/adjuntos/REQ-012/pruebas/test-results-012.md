# Resultados de pruebas — REQ-012

**Fecha:** 2026-09-07
**Agente:** orion-tester
**SPEC de referencia:** `workspace/adjuntos/REQ-012/spec/SPEC-012.md` (CA-01 a CA-10)
**Arquitectura de referencia:** `workspace/adjuntos/REQ-012/propuestas/arquitectura-012.md`
**Desarrollo de referencia:** `workspace/adjuntos/REQ-012/propuestas/desarrollo-log-012.md` (orion-dev, 2026-08-05, 226 passed/0 failed en su momento)

## Veredicto

**❌ FAIL** — no por un error de implementación de `orion-dev` (su código, tal como lo entregó
el 2026-08-05, cumplía la arquitectura aprobada), sino porque **el código que implementaba CA-03,
CA-04 y CA-06 a CA-09 fue borrado del repositorio 16 días después**, en un commit ajeno a este REQ.

## Hallazgo crítico — el suelo se movió debajo de REQ-012

```
git log --diff-filter=D --summary -- ui/widgets/weather_card.py ui/widgets/center_panel.py
  commit 9f4235f160dcdb8f168477f67a199d95f2dca29
  Author: soporte_sigaind <soporte@sigag.com>
  Date:   Fri Aug 21 12:16:17 2026 -0500
      Mejora visual UI
   delete mode 100644 agente_ia/ui/widgets/center_panel.py
   delete mode 100644 agente_ia/ui/widgets/weather_card.py
   delete mode 100644 agente_ia/tests/test_gui_widgets.py
```

El mismo commit reemplazó la GUI JARVIS basada en widgets PyQt6 (`ui/widgets/*`) por una interfaz
webview (`ui/webview/frontend/index.html` + `ui/webview/frontend/js/app.js` + `ui/webview/bridge.py`).
`orion-dev` implementó y probó su fix el 2026-08-05 contra la GUI PyQt6 vieja; el REQ quedó parado
en `EN_PRUEBAS` desde entonces (sin que nadie lo señalara) y para cuando `orion-tester` lo retoma
hoy (2026-09-07), los tres archivos de alcance de la SPEC ya no son tres — son uno:

| Archivo de alcance (SPEC-012) | Estado hoy |
|---|---|
| `config_manager.py` | Existe. Cambios de `orion-dev` intactos (`weather_city`, `get_weather_city()`, `set_weather_city()`). |
| `ui/widgets/weather_card.py` | **Borrado** (commit 9f4235f, 2026-08-21). No hay panel de clima en la GUI actual. |
| `ui/widgets/center_panel.py` | **Borrado** (commit 9f4235f, 2026-08-21). No hay `QTimer` de saludo en la GUI actual. |

Verificado con `grep` en `ui/`: no queda ninguna referencia funcional a `get_weather_structured`
ni a `config_manager.get_weather_city()` desde la interfaz activa — `get_weather_structured` solo
lo usan ya `os_integration/weather_data.py` (su propia definición) y `tests/test_weather_data.py`.
El panel de clima, como widget de la GUI, ya no existe en absoluto.

**El bug 2 (saludo congelado) reapareció, sin el fix, en la interfaz nueva.** La GUI webview
reimplementó el saludo de forma independiente, en JavaScript, en
`ui/webview/frontend/js/app.js:60-69,81`:

```js
const GREETINGS_BY_HOUR = [
  { from: 5, to: 12, text: "Buenos días" },
  { from: 12, to: 19, text: "Buenas tardes" },
];
function timeBasedGreeting() {
  const hour = new Date().getHours();
  const match = GREETINGS_BY_HOUR.find((slot) => hour >= slot.from && hour < slot.to);
  return match ? match.text : "Buenas noches";
}
...
document.getElementById("empty-state-greeting").textContent = timeBasedGreeting();  // línea 81
```

`timeBasedGreeting()` se llama una única vez, dentro de `setAgentIdentity()`, invocada desde
`bootstrap()` al cargar la página — no hay ningún `setInterval`/refresco periódico en `app.js`. Es
exactamente el mismo defecto que describe SPEC-012 ("se calcula una sola vez... y nunca se
reevalúa"), reintroducido en una capa distinta (JS en vez de Python/`QTimer`), completamente ajena
al fix de `orion-dev` (que vive en un `ui/widgets/center_panel.py` que ya no existe). Además esta
reimplementación en JS ni siquiera comparte lógica con `ui/personality.py:get_time_based_greeting()`
(CA-05 asumía que esa función seguía siendo la única fuente de verdad del saludo — ya no lo es).

## Resultado por criterio de aceptación

| CA | Descripción | Resultado | Evidencia |
|----|---|---|---|
| CA-01 | `get_weather_city()` retorna `""` por defecto, con backfill para configs viejas | ✅ PASS | `python -m pytest tests/test_config_manager_weather_city.py -v` → 4 passed (incluye `test_get_weather_city_default_is_empty` y `test_load_config_backfills_weather_city_for_old_config`). Código verificado en `config_manager.py:153-161` y backfill en `load_config()` línea 66-67. |
| CA-02 | `set_weather_city("Bogotá")` persiste con `.strip()` | ✅ PASS | `test_set_weather_city_persists_and_strips_whitespace` PASSED. Código en `config_manager.py:164-167` idéntico al patrón de `set_display_name()`. |
| CA-03 | `WeatherCard._fetch()` invoca `get_weather_structured("Medellín")` con ciudad configurada | ❌ FAIL (no verificable) | `ui/widgets/weather_card.py` **no existe** — borrado en commit 9f4235f (2026-08-21). No hay ningún `WeatherCard` en la GUI activa (`ui/webview/`) para probar. |
| CA-04 | `WeatherCard._fetch()` invoca `get_weather_structured("")` sin ciudad configurada | ❌ FAIL (no verificable) | Mismo motivo que CA-03. |
| CA-05 | `get_time_based_greeting()` no cambia firma/lógica, tests existentes siguen pasando | ✅ PASS (con salvedad) | `python -m pytest tests/test_personality_greeting.py -q` → 12 passed. La función en sí sigue intacta. **Salvedad:** ya no es la fuente del saludo mostrado en la GUI activa — ver hallazgo crítico arriba. |
| CA-06 | `CenterPanel` arranca un `QTimer` que reevalúa el saludo cada 60s | ❌ FAIL (no verificable / regresión funcional) | `ui/widgets/center_panel.py` **no existe**. El saludo de la GUI activa (`app.js`) no tiene ningún timer de refresco — el bug original sigue presente en producción. |
| CA-07 | No repinta si el texto no cambió | ❌ FAIL (no verificable) | Mismo motivo — no hay código de refresco que auditar. |
| CA-08 | Test que simula cruce de franja confirma actualización sin recrear el widget | ❌ FAIL (no verificable) | El test que lo cubría (`tests/test_gui_widgets.py`) fue borrado junto con `center_panel.py`. |
| CA-09 | El `QTimer` se detiene al destruirse `CenterPanel` (sin timers huérfanos) | ❌ FAIL (no verificable) | No aplica — no existe ningún `QTimer` de saludo en el código actual. |
| CA-10 | `pytest tests/` completo sin regresiones nuevas atribuibles a REQ-012 | ✅ PASS (con 4 fallos ajenos documentados) | Ver sección siguiente. |

## CA-10 — Suite completa

```
python -m pytest tests/ --tb=short -q
→ 4 failed, 1759 passed, 11 warnings in 92.13s
```

Los 4 fallos **no tocan** los archivos de alcance de REQ-012 (`config_manager.py`,
`ui/widgets/weather_card.py` — inexistente —, `ui/widgets/center_panel.py` — inexistente):

- `tests/test_provider_fallback.py::test_sin_respaldo_se_devuelve_el_error_del_principal`
- `tests/test_provider_health.py::test_sin_respaldo_configurado_se_usa_el_principal_aunque_este_apartado`
- `tests/test_provider_health.py::test_cuando_el_proveedor_revive_se_lo_deja_de_apartar`

  Los tres son de `ai/llm_provider.py` / `ai/provider_health.py` (proveedores/fallback de modelo),
  que la tarea marcó explícitamente como **fuera de mi alcance** (REQ-022 en desarrollo activo,
  `ai/llm_provider.py` aparece modificado sin commitear en `git status`). No se investigan ni se
  tocan, por instrucción explícita.

- `tests/test_task_slots.py::test_la_hora_dicha_se_respeta`

  Falla por dependencia de la hora real de ejecución (`assert fecha.date() ==
  datetime.date.today()` compara la fecha resuelta de "diga la hora" contra "hoy"; al ejecutarse
  después de cierta hora del día, el parser de horario relativo interpreta la hora dicha como "ya
  pasó hoy" y la resuelve para el día siguiente). Reproducido en aislado, mismo resultado. No
  pertenece al alcance de REQ-012 (`tests/test_task_slots.py`, agenda de tareas — módulo no
  tocado por este REQ) y es intermitente por diseño del test, no una regresión de este cambio.

**Ninguno de los 4 fallos está relacionado con `config_manager.py`, `weather_city`,
`get_weather_city`/`set_weather_city`, `WeatherCard` ni `CenterPanel`.** Cero regresiones nuevas
atribuibles a REQ-012.

## Compilación

```
python -m py_compile config_manager.py
→ OK
```

`ui/widgets/weather_card.py` y `ui/widgets/center_panel.py` no se pueden compilar: no existen.

## Hallazgo adicional (no bloqueante, pero a limpiar) — archivos de verificación manual huérfanos

`tests/_tmp_manual_verify_012.py` y `tests/_tmp_manual_verify_012b.py` quedaron committeados desde
el 2026-08-17 (commit `eb190b3`, "Fix mejora interfaz visual Agente IA") con la nota "NO forma
parte de la suite oficial - se borra al terminar" — nunca se borraron. Ambos importan
`ui.widgets.weather_card`/`ui.widgets.center_panel`, que ya no existen, y `_tmp_manual_verify_012b.py`
tiene además una línea con error de sintaxis (`import sip if False else None`, línea 37) y termina
sin completar el segundo test. **No rompen la suite actual** porque no calzan con el patrón de
descubrimiento `test_*.py` de pytest (confirmado: no aparecen en la colección de
`pytest tests/ -q`), pero son código muerto que referencia módulos borrados y deberían eliminarse
en la próxima iteración de este REQ para evitar confusión futura.

## Conclusión y handoff

REQ-012 no puede cerrarse como está. El trabajo de `orion-dev` del 2026-08-05 es correcto contra
la arquitectura que se le aprobó, pero esa arquitectura apuntaba a una GUI que ya no existe. Se
necesita retrabajo real, no un ajuste menor:

1. **Bug 1 (ubicación de clima):** el panel de clima fue eliminado de la GUI en la migración a
   webview. `config_manager.get_weather_city()`/`set_weather_city()` siguen funcionando pero no
   los usa nadie. Hay que decidir con el humano si el panel de clima vuelve a existir en la GUI
   webview (y si es así, diseñar cómo `ui/webview/bridge.py`/`app.js` lo consumen) o si el bug se
   da por resuelto al haber desaparecido su causa.
2. **Bug 2 (saludo congelado):** sigue activo, ahora en `ui/webview/frontend/js/app.js` — el
   saludo se calcula una sola vez en `bootstrap()`/`setAgentIdentity()` (línea 81) y nunca se
   reevalúa. El fix original (`QTimer` en un `CenterPanel` de PyQt6) no aplica a este código; hace
   falta un mecanismo equivalente en JS (`setInterval` reevaluando `timeBasedGreeting()`), lo cual
   es una arquitectura distinta a la aprobada en `arquitectura-012.md`.

Dado que el alcance técnico cambió de raíz (los 3 módulos de la SPEC ya no son los módulos que
implementan estas dos funciones en la GUI real), la recomendación de `orion-tester` es que este
REQ vuelva a `orion-dev` primero para diagnóstico impacto — pero probablemente requiera pasar antes
por `orion-baseline`/`orion-architect` para redefinir CA-03/04/06-09 contra `ui/webview/` en vez
de `ui/widgets/`, ya que la arquitectura aprobada quedó obsoleta y no es un simple "arreglalo de
nuevo" para `orion-dev`. Se documenta esta recomendación en el contexto; la decisión de por dónde
reingresa al pipeline queda para el humano/`orion-coordinador`.

**Handoff formal:** `EN_PRUEBAS → EN_DESARROLLO` (transición válida más cercana disponible en el
tracker). Detalle específico para quien retome:
- No repetir el trabajo en `ui/widgets/` — esa carpeta está vacía salvo `__init__.py`.
- El punto de entrada real de la GUI hoy es `ui/webview/frontend/js/app.js` (saludo) y no hay
  panel de clima que reemplazar (evaluar si corresponde re-crearlo).
- Los cambios en `config_manager.py` (CA-01/CA-02) NO requieren tocarse — siguen correctos y
  reutilizables tal cual desde donde sea que se consuma la ciudad configurada.
- Limpiar `tests/_tmp_manual_verify_012.py` y `tests/_tmp_manual_verify_012b.py` (código muerto,
  ver hallazgo adicional arriba).
