# Baseline REQ-012 v2 — re-baseline post-migración a webview

**Fecha:** 2026-09-07
**Agente:** orion-baseline (segunda pasada — la primera, `baseline-012.md`, documentó el
sistema el 2026-08-05 contra una GUI PyQt6 que ya no existe; se deja como referencia
histórica y NO se sobreescribe)
**Motivo de este re-baseline:** `orion-tester` (2026-09-07, `pruebas/test-results-012.md`)
encontró que los 2 de los 3 archivos de alcance de `arquitectura-012.md`
(`ui/widgets/weather_card.py`, `ui/widgets/center_panel.py`, más
`tests/test_gui_widgets.py`) fueron **borrados** el 2026-08-21 en el commit `9f4235f`
("Mejora visual UI"), que reemplazó la GUI de widgets PyQt6 por la interfaz webview
(`ui/webview/frontend/`). La arquitectura aprobada apunta a código inexistente — hace
falta redocumentar el estado real antes de que `orion-architect` vuelva a proponer
diseño.

**Continuación autorizada bajo "autorización nocturna en bloque del 2026-09-06"** (Johan
dio permiso para seguir el pipeline de REQs ya aprobados/en curso sin pedir confirmación
puntual mientras dormía; no aplica a `git commit`/`push` ni a acciones 🔴 Rojo, que
siguen prohibidas).

Todo lo documentado abajo fue **verificado directamente sobre el código actual** en esta
pasada (lectura de archivo, grep, `py_compile`, `pytest`) — no se asumió nada de lo que
reportó `orion-tester`, aunque coincide con su hallazgo.

## 1. Estado actual del sistema (hoy, 2026-09-07)

### 1.1 `config_manager.py` — intacto, CA-01/CA-02 en verde, pero huérfano de consumidor GUI

Verificado leyendo el archivo completo:

- `DEFAULT_CONFIG` (línea 17-24) incluye `"weather_city": ""`.
- `load_config()` hace backfill de `weather_city` para configs viejas (línea 66-67):
  `if "weather_city" not in config: config["weather_city"] = DEFAULT_CONFIG["weather_city"]`.
- `get_weather_city()` (línea 153-161) y `set_weather_city()` (línea 164-167) existen,
  con el mismo patrón que `get_display_name()`/`set_display_name()` (`.strip()`, sin
  normalizar mayúsculas) — exactamente lo que pedían CA-01/CA-02.
- `python -m pytest tests/test_config_manager_weather_city.py -v` → **4 passed** (re-
  ejecutado en esta pasada, mismo resultado que reportó `orion-tester`).
- **Huérfano confirmado por grep:** `grep -ri "weather|clima" ui/webview/` (recursivo,
  sobre `ui/webview/frontend/` y `ui/webview/bridge.py`) → **cero resultados**. Ningún
  archivo de la GUI activa importa `config_manager.get_weather_city()` ni
  `get_weather_structured()`. La función existe, persiste correctamente, pero hoy no la
  lee nada en el camino de ejecución real de la app.

**Conclusión:** CA-01/CA-02 no requieren ningún cambio. Quedan disponibles tal cual para
que lo que se decida en arquitectura (recrear el panel de clima, o no) los consuma.

### 1.2 Panel de clima — no existe en la GUI activa

`ui/widgets/weather_card.py` fue borrado (commit `9f4235f`, 2026-08-21).
`ui/widgets/` hoy solo contiene `__init__.py` (confirmado con listado de directorio).

Búsqueda exhaustiva en `ui/webview/frontend/` (HTML + todo `js/*.js`) y en
`ui/webview/bridge.py` por "weather"/"clima" (case-insensitive): **sin coincidencias**.
No hay ningún elemento del DOM, señal del bridge, ni slot Python relacionado con clima
en la interfaz webview. El panel de clima no fue migrado — simplemente dejó de existir
cuando se reemplazó la GUI.

**Implicación para el bug original ("el clima muestra la ubicación equivocada"):** la
causa raíz (falta de ciudad configurable) fue corregida en `config_manager.py`, pero el
efecto visible que motivó el REQ (un panel de clima mostrando mal la ciudad) ya no tiene
dónde manifestarse — no hay panel de clima, ni bien ni mal. El bug, tal como fue
reportado originalmente, no tiene objeto hoy. Esto es una decisión de producto, no
técnica: **queda para que `orion-architect`/el humano decidan** si (a) se da el bug 1 por
resuelto al haber desaparecido su causa visible, o (b) se recrea un panel de clima en la
webview reusando `get_weather_city()`/`get_weather_structured()`. No es rol de
`orion-baseline` proponer cuál.

### 1.3 Saludo dinámico — el bug 2 sigue vivo, reimplementado en JS

`ui/widgets/center_panel.py` fue borrado (mismo commit). El saludo de la GUI activa vive
en `ui/webview/frontend/js/app.js`, leído completo en esta pasada (215 líneas). Estructura
relevante:

```js
// líneas 60-63
const GREETINGS_BY_HOUR = [
  { from: 5, to: 12, text: "Buenos días" },
  { from: 12, to: 19, text: "Buenas tardes" },
];

// líneas 65-69
function timeBasedGreeting() {
  const hour = new Date().getHours();
  const match = GREETINGS_BY_HOUR.find((slot) => hour >= slot.from && hour < slot.to);
  return match ? match.text : "Buenas noches";
}

// líneas 71-82 — setAgentIdentity(name)
function setAgentIdentity(name) {
  const agentName = (name || window.__ORION_AGENT_NAME__ || "ORION").trim();
  const upper = agentName.toUpperCase();
  document.getElementById("agent-name-label").textContent = upper;
  document.getElementById("empty-state-avatar").textContent = agentName.charAt(0).toUpperCase();
  document.getElementById("empty-state-greeting").textContent = timeBasedGreeting();  // línea 81
}
```

`setAgentIdentity()` (y por tanto `timeBasedGreeting()`) se invoca en **dos** puntos, no
uno solo — matiz que agrega esta pasada sobre lo que reportó `orion-tester`:

1. `bootstrap()` línea 85: `setAgentIdentity();` — al cargar la página, una única vez.
2. `onProfileLoaded(...)` línea 188-192: cada vez que llega la señal `profile_loaded`
   del bridge (se dispara al abrir la sección "Perfil" de Configuración, y de nuevo al
   guardar cambios ahí) se vuelve a llamar `setAgentIdentity(profile.agent_name)`, lo que
   recalcula `timeBasedGreeting()` de paso — efecto secundario no buscado, no un timer.

Ninguno de los dos casos es un refresco periódico. El saludo queda "congelado" con el
valor de la última vez que se abrió/guardó la página o la pantalla de Perfil — que en la
práctica, para una ventana que se deja abierta sin tocar Configuración, es la carga
inicial. Confirma exactamente el hallazgo de `orion-tester`: el mismo defecto que
describía SPEC-012 para `CenterPanel._build_ui()`, reintroducido en `app.js`.

**Ciclo de vida JS relevante para que `orion-architect` diseñe el refresco:**
`bootstrap()` (líneas 84-214) es un único `async function` que se autoinvoca al final del
módulo (línea 214: `bootstrap();`). Hace `await connectBridge()` (línea 95) antes de
cablear listeners y pedir estado inicial. No hay ningún framework de componentes ni
ciclo de "unmount" — es una sola página que vive mientras la ventana esté abierta, sin
recreación de DOM. Esto simplifica el diseño de un timer: no hace falta lógica de
cleanup equivalente a CA-09 (destrucción de `QTimer` al destruir un widget PyQt6) porque
no hay "destrucción" de este contexto JS en la vida de la ventana — solo se cierra la
app entera.

**Sin precedente de timer periódico en el código JS del proyecto:**
`grep -r "setInterval" ui/webview/frontend/js/` (los 16 archivos `.js` de esa carpeta) →
**cero resultados**. A diferencia de la GUI PyQt6 vieja (que sí tenía el patrón
`QTimer(self)` de `system_status_card.py` citado en `baseline-012.md`), no existe hoy
ningún módulo JS del proyecto que haga refresco periódico del DOM. `orion-architect`
parte de diseño nuevo en este punto, no de un patrón a replicar — vale la pena que quede
explícito para que no se asuma un precedente que no existe.

## 2. Archivos que serán modificados (previsión, sujeta a lo que decida `orion-architect`)

- `ui/webview/frontend/js/app.js` — único archivo confirmado que necesita cambio para el
  bug 2 (saludo congelado): agregar el mecanismo de refresco periódico (candidato natural:
  `setInterval` que vuelva a llamar `timeBasedGreeting()` y actualice
  `#empty-state-greeting` solo si el texto cambió, análogo a CA-06/CA-07 de SPEC-012 pero
  del lado JS).
- `config_manager.py` — **sin cambios previstos**; CA-01/CA-02 ya están completos y en
  verde, se documentan como reutilizables tal cual.
- Ningún archivo de panel de clima — no existe hoy ninguno que modificar. Si
  `orion-architect`/Johan deciden recrear un panel de clima en la webview, eso implica
  archivo(s) **nuevos** (posiblemente `ui/webview/frontend/js/weather_panel.js` o
  similar + una sección en `ui/webview/bridge.py` que exponga `get_weather_city()`/
  `get_weather_structured()` a la página) — alcance a definir en arquitectura, no en este
  baseline.
- `tests/_tmp_manual_verify_012.py` y `tests/_tmp_manual_verify_012b.py` — **a borrar**
  como parte de la limpieza de este REQ (ver §4). No se tocan en este baseline.
- Posible archivo de test nuevo para el refresco JS (p. ej. algo bajo
  `tests/test_webview_*.py` si el patrón de smoke test con `QWebEngineView` offscreen ya
  usado en el proyecto permite verificar el DOM tras simular el paso del tiempo) — decisión
  de `orion-architect`/`orion-dev`, no de este baseline.

## 3. Fallos pre-existentes (no atribuibles a REQ-012)

`python -m py_compile config_manager.py` → **OK**, sin errores (única unidad Python de
alcance confirmado; no hay `.py` de widgets que compilar porque no existen).

`python -m pytest tests/ --tb=short -q` (suite completa, re-ejecutada en esta pasada) →

```
2 failed, 1761 passed, 11 warnings in 87.34s
```

Distinto del `4 failed, 1759 passed` que reportó `orion-tester` hace unas horas — es lo
esperado por trabajo concurrente activo, no una regresión de REQ-012. Detalle:

| Test que falla | Relacionado con REQ-012 | Motivo |
|---|---|---|
| `tests/test_task_slots.py::test_la_hora_dicha_se_respeta` | No | Mismo flaky que ya documentó `orion-tester` — depende de la hora real de ejecución (compara contra `datetime.date.today()`). Ajeno a `tests/test_task_slots.py` (agenda), módulo no tocado por REQ-012. |
| `tests/test_webview_buttons.py::test_el_selector_de_modelo_muestra_el_activo_y_lo_cambia` | No | `git status` confirma `tests/test_webview_buttons.py`, `ai/llm_provider.py` y `ui/webview/bridge.py` **modificados sin commitear** — trabajo activo de REQ-022 (carpeta `workspace/adjuntos/REQ-022/` presente, sin commitear). El test falla monkeypacheando `destinos_de_tarea` (enrutado por tarea, área de REQ-022), no algo relacionado con clima/saludo. |

Los 3 fallos de `ai/llm_provider.py`/`ai/provider_health.py` que reportó `orion-tester`
(`test_provider_fallback.py`, 2x `test_provider_health.py`) **ya no fallan** en esta
pasada — consistente con que REQ-022 sigue en desarrollo activo y avanzó desde entonces.
Confirmado con `git status --short`: `ai/llm_provider.py`, `ai/claude_brain.py`,
`core/reasoning_loop.py`, `ui/tts_engine.py`, `ui/webview/bridge.py`,
`tests/test_provider_fallback.py`, `tests/test_provider_health.py`,
`tests/test_webview_buttons.py` están todos modificados sin commitear ahora mismo.
**Ninguno de estos 8 archivos está en el alcance de REQ-012** (`config_manager.py`,
`ui/webview/frontend/js/app.js` no aparecen en la lista de modificados).

**Cero fallos atribuibles a REQ-012.** Cualquier número de fallos distinto en una
ejecución futura de `pytest tests/` que involucre `ai/llm_provider.py`,
`ai/provider_health.py`, `core/reasoning_loop.py`, `ui/tts_engine.py` o
`ui/webview/bridge.py` debe contrastarse contra el estado de REQ-022 antes de
atribuírselo a este REQ.

## 4. Limpieza pendiente identificada (fuera del alcance de este baseline, a incluir por `orion-architect`)

`tests/_tmp_manual_verify_012.py` y `tests/_tmp_manual_verify_012b.py` — confirmado que
siguen presentes en el árbol (listado de directorio). Committeados desde el 2026-08-17
(`eb190b3`) con nota "se borra al terminar" nunca cumplida. Ambos importan
`ui.widgets.weather_card`/`ui.widgets.center_panel`, módulos que ya no existen;
`_tmp_manual_verify_012b.py` tiene además una línea con error de sintaxis. No rompen la
suite (no matchean el patrón `test_*.py` de descubrimiento de pytest — confirmado que no
aparecen en la colección de `pytest tests/ -q`), pero son código muerto que referencia
módulos borrados. `orion-baseline` no los borra — se documenta para que
`orion-architect` incluya su eliminación en el alcance del REQ, tal como recomendó
`orion-tester`.

## 5. Bloqueo detectado en el tracker — CSV no puede reflejar el estado real desde `EN_DESARROLLO`

La máquina de estados de `.claude/scripts/update-tracker.mjs` (`TRANSICIONES`) solo
permite, desde `EN_DESARROLLO` (estado actual, dejado por `orion-tester`), la transición
`EN_DESARROLLO → EN_PRUEBAS`. No existe ninguna transición válida hacia `EN_BASELINE` ni
`EN_ARQUITECTURA` desde `EN_DESARROLLO`. Verificado ejecutando el script:

```
node .claude/scripts/update-tracker.mjs --id REQ-012 --Estado "EN_BASELINE"
❌ Transición no permitida: EN_DESARROLLO → EN_BASELINE. Desde "EN_DESARROLLO" solo se permite: EN_PRUEBAS
```

El script rechaza la escritura (no queda CSV parcialmente modificado — confirmado
releyendo la fila de REQ-012 tras el intento, sin cambios). Siguiendo la regla
transversal de DoD ("si queda bloqueado: reportar el motivo y esperar al humano, no
asumir") y la regla de git/tracker ("Actualizar `requerimientos.csv` solo vía
`update-tracker.mjs`, nunca a mano"), **este baseline NO fuerza ni edita el CSV a mano**.
El tracker queda en `Estado=EN_DESARROLLO` (sin cambio) — refleja correctamente que el
REQ no completó su paso por `orion-dev`/`orion-tester` original, aunque no refleja que
en este momento el trabajo real en curso es de re-baseline/re-arquitectura.

**Queda para el humano/`orion-coordinador` decidir:** o bien se acepta que el CSV se
quede en `EN_DESARROLLO` durante este ciclo de re-baseline/re-arquitectura (el contexto
en `REQ-012-context.md` es la fuente de verdad narrativa mientras tanto), o bien hace
falta ampliar `TRANSICIONES` en `update-tracker.mjs` para admitir el caso "un REQ
aprobado en arquitectura resulta con su base de código borrada y necesita reingresar por
baseline/arquitectura sin pasar de nuevo por todo el pipeline desde `EN_SPEC`" — cambio
de herramienta, no de contenido, fuera del rol de `orion-baseline`.

## 6. Resumen para `orion-architect`

- Bug 1 (clima): causa raíz ya corregida en `config_manager.py` (CA-01/CA-02, sin tocar).
  No hay panel de clima en la GUI activa — decidir con Johan si se recrea o se da el bug
  por resuelto al no tener ya dónde manifestarse.
- Bug 2 (saludo): sigue activo, en `ui/webview/frontend/js/app.js`. Único archivo con
  cambio confirmado necesario. No hay precedente de `setInterval` en el proyecto — diseño
  nuevo, sin patrón JS existente que replicar (a diferencia de la vieja referencia
  `QTimer(self)` de `system_status_card.py`, que ya no aplica porque ese archivo también
  fue borrado junto con toda `ui/widgets/`).
- Limpieza de los 2 archivos huérfanos (`tests/_tmp_manual_verify_012*.py`) a incluir en
  el alcance.
- 2 fallos de suite hoy, ninguno atribuible a REQ-012 (1 flaky de hora del día, 1 de
  trabajo activo de REQ-022 sobre `ai/llm_provider.py`/`ui/webview/bridge.py`/
  `tests/test_webview_buttons.py`) — recontrastar contra REQ-022 si cambia el número en
  una corrida futura.
- CSV bloqueado en `EN_DESARROLLO` por la máquina de estados del tracker — no es un
  bloqueo de contenido, se documenta para el humano/coordinador.
