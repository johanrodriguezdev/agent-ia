# SPEC-012 — Fix ubicación de clima y saludo dinámico congelado en GUI JARVIS

**Estado:** ✅ APROBADO (Johan, 2026-08-05 — asumidos confirmados: refresco de saludo 60s, sin UI de configuración de ciudad en este REQ, sin unificar con skills/weather_skill.py)
**Categoría:** UI
**Tipo:** BUG_FIX
**Fecha:** 2026-08-05

## Objetivo
La GUI JARVIS (REQ-008, actualmente EN_QA) tiene dos bugs de comportamiento: (1) el panel de
clima siempre depende de geolocalización por IP porque no existe forma de fijar una ciudad, lo
que muestra una ubicación incorrecta; (2) el saludo dinámico se calcula una sola vez al construir
la ventana y nunca se reevalúa, por lo que queda "congelado" (p. ej. sigue diciendo "Buenos días"
de noche si la app quedó abierta desde la mañana). Esta SPEC corrige ambos causas raíz.

## Alcance
- Incluye:
  - Nueva ciudad configurable para el panel de clima (`config_manager.get_weather_city()` /
    `set_weather_city()`), análoga a `display_name`.
  - `WeatherCard` usa la ciudad configurada si existe; si no, cae al comportamiento actual
    (detección por IP vía `get_weather_structured("")`).
  - Refresco periódico del saludo dinámico en `CenterPanel` mediante `QTimer`, sin acción del
    usuario, mientras la ventana permanece abierta.
- No incluye:
  - UI para que el usuario edite la ciudad desde la propia GUI (solo se agrega el mecanismo de
    config; cómo se setea — settings screen, comando de voz/texto, etc. — queda fuera de esta
    SPEC salvo que el humano indique lo contrario en arquitectura).
  - Cambiar el proveedor de clima (`wttr.in`) ni su formato de respuesta.
  - Tocar `skills/weather_skill.py` (skill conversacional) — su fallback por IP es intencional y
    no está en discusión aquí.
  - Cambiar los rangos horarios ni la lógica interna de `get_time_based_greeting()` — ya está
    correctamente implementada y testeada (`tests/test_personality_greeting.py`).

## Módulos afectados
- `config_manager.py` — agregar `get_weather_city()` / `set_weather_city()` y la clave
  `weather_city` en `DEFAULT_CONFIG`, siguiendo el mismo patrón que `display_name`.
- `ui/widgets/weather_card.py` — `_fetch()` debe pasar la ciudad configurada a
  `get_weather_structured(city)` en vez de invocarla sin argumento.
- `ui/widgets/center_panel.py` — agregar un `QTimer` que reevalúe y actualice
  `_greeting_label` periódicamente mientras el widget existe.
- `os_integration/weather_data.py` — sin cambios de lógica esperados (ya acepta `city` como
  parámetro); solo pasa a recibir un valor no vacío cuando hay ciudad configurada.
- `ui/personality.py` — sin cambios (lógica de franja horaria ya correcta).

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| `WeatherCard` siempre llama `get_weather_structured()` sin ciudad → depende 100% de geolocalización por IP de wttr.in. | `WeatherCard` usa `config_manager.get_weather_city()`; si hay valor, lo pasa a `get_weather_structured(city)`. Si está vacío, mantiene el fallback actual por IP (sin cambio de comportamiento para quien no configure nada). |
| No existe ninguna clave de configuración de ciudad/ubicación en `config_manager.py`. | `config_manager.py` expone `get_weather_city()` / `set_weather_city()`, con clave `weather_city` en `DEFAULT_CONFIG` (default `""`), mismo patrón que `display_name`. |
| El saludo (`get_time_based_greeting()`) se calcula una única vez en `CenterPanel._build_ui()` y nunca se vuelve a evaluar mientras la ventana está abierta. | `CenterPanel` arranca un `QTimer` que reevalúa el saludo periódicamente (cada 60 segundos) y actualiza `_greeting_label` solo cuando el texto resultante cambia respecto al mostrado. |
| Si la app queda abierta cruzando el límite de una franja horaria (p. ej. de mañana a tarde, o de tarde a noche), el saludo mostrado no coincide con la hora real. | El saludo mostrado siempre coincide con la franja horaria vigente en un plazo máximo de 60 segundos desde que se cruza el límite, sin que el usuario tenga que interactuar ni reabrir la ventana. |

## Criterios de aceptación
- [ ] CA-01: `config_manager.get_weather_city()` retorna `""` por defecto (config nueva o
      existente sin la clave `weather_city`), sin romper `load_config()` para configs guardadas
      antes de este REQ (mismo patrón de migración que `display_name` en REQ-008).
- [ ] CA-02: `config_manager.set_weather_city("Bogotá")` persiste el valor (con `.strip()`, mismo
      criterio que `set_display_name()`) y `get_weather_city()` lo devuelve en una llamada
      posterior.
- [ ] CA-03: Con `weather_city` configurada (ej. `"Medellín"`), `WeatherCard._fetch()` invoca
      `get_weather_structured("Medellín")` — verificable con test que mockea
      `config_manager.get_weather_city` y espía la llamada a `get_weather_structured`.
- [ ] CA-04: Con `weather_city` vacía (default), `WeatherCard._fetch()` invoca
      `get_weather_structured("")` — comportamiento idéntico al actual, sin regresión.
- [ ] CA-05: `get_time_based_greeting()` no cambia de firma ni de lógica — los tests existentes
      de `tests/test_personality_greeting.py` siguen pasando sin modificación.
- [ ] CA-06: `CenterPanel` arranca un `QTimer` al construirse que dispara una reevaluación del
      saludo (llama a `get_time_based_greeting(display_name)` de nuevo) cada 60 segundos mientras
      el widget existe.
- [ ] CA-07: Si el texto del saludo reevaluado es igual al mostrado, `_greeting_label` no se
      toca (evitar renders innecesarios); si cambió (cruce de franja), se actualiza.
- [ ] CA-08: Test que simule el reloj cruzando un límite de franja (mock de `datetime.now()` +
      disparo manual del callback del timer) confirma que `_greeting_label` pasa de un saludo a
      otro sin recrear el widget ni requerir foco/reapertura de la ventana.
- [ ] CA-09: El `QTimer` se detiene correctamente si `CenterPanel` se destruye (sin timers
      huérfanos ni crecimiento de memoria en tests que crean/destruyen el widget repetidamente).
- [ ] CA-10: `pytest tests/` completo sigue en verde (sin nuevas regresiones sobre lo que ya
      pasaba en el baseline de este REQ).

## Casos borde
- Ciudad configurada con espacios o mayúsculas/minúsculas mixtas (`"  bogotá  "`) — se persiste
  con `.strip()`, sin normalizar mayúsculas (igual que `display_name`; wttr.in ya tolera esto).
- Ciudad configurada que wttr.in no reconoce — `get_weather_structured()` ya maneja esto
  (retorna `None` en cualquier fallo); `WeatherCard` ya muestra "Clima no disponible." — sin
  cambios necesarios ahí.
- App abierta exactamente en el segundo del cruce de franja (ej. 18:59:59 → 19:00:00) — el
  criterio de aceptación es "coincide en un plazo máximo de 60 segundos", no instantáneo.
- Widget `CenterPanel` destruido/recreado (ej. si la GUI se reconstruye) — el timer anterior no
  debe seguir corriendo en segundo plano apuntando a un label ya destruido (CA-09).
- Usuario sin `weather_city` configurada y sin conexión a internet — comportamiento sin cambios
  respecto al actual (`WeatherCard.set_data(None)`).

## Asumidos
- ASUMIDO: el intervalo de refresco del saludo es 60 segundos — suficiente para el requisito de
  "corregirse en un momento razonable" sin generar carga innecesaria; confirmar antes de
  implementar si se prefiere otro intervalo (p. ej. cada 5 minutos, o recalcular solo en los
  minutos exactos de cruce de franja: 05:00, 12:00, 19:00).
- ASUMIDO: no se agrega UI (campo de texto, comando de voz) para que el usuario configure
  `weather_city` en esta SPEC — solo el mecanismo de config. Si `orion-architect` considera que
  no tiene sentido agregar una config sin forma de setearla desde la app, debe señalarlo antes de
  implementar.
- ASUMIDO: la ciudad configurada aplica solo al panel de clima de la GUI (`WeatherCard`), no a
  `skills/weather_skill.py` (skill conversacional) — confirmar que no se espera unificar ambos
  orígenes de ciudad en este REQ.
