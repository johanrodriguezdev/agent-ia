# Auditoría QA REQ-022 — Selector de modelo del chat + fallback automático

**Fecha:** 2026-09-07
**Agente:** orion-qa
**Entradas leídas completas:** `SPEC-022.md`, `propuestas/arquitectura-022.md`,
`propuestas/desarrollo-log-022.md` (incluida la nota de interrupción por rate-limit y la
sección "Segunda vuelta"), `pruebas/test-results-022.md` (ambas vueltas de
`orion-tester`), `REQ-022-context.md` completo (incluida la nota de que la arquitectura se
aprobó bajo autorización nocturna en bloque, no revisión puntual).

No me basé en los reportes de `orion-dev`/`orion-tester` sin comprobarlo: leí yo mismo el
diff real de los 6 archivos de producto tocados (`ai/llm_provider.py`,
`core/reasoning_loop.py`, `ai/claude_brain.py`, `ui/tts_engine.py`, `ui/webview/bridge.py`,
`ui/webview/frontend/js/composer.js`) y de los 7 archivos de test tocados/creados en la
segunda vuelta (`tests/test_llm_provider.py`, `tests/test_reasoning_loop.py`,
`tests/test_claude_brain.py`, `tests/test_speech_prep.py`, `tests/test_webview_bridge.py`,
`tests/test_provider_fallback.py`, `tests/test_provider_health.py`,
`tests/test_webview_buttons.py`) vía `git diff`, y corrí de forma independiente la suite
dirigida (195 tests, `test_llm_provider.py` + `test_reasoning_loop.py` +
`test_claude_brain.py` + `test_speech_prep.py` + `test_webview_bridge.py` +
`test_provider_fallback.py` + `test_provider_health.py`): **195/195 OK**, sin fallos.

## Seguridad

- **Sin API keys/tokens hardcodeados.** Grep dirigido a los 6 archivos de producto tocados
  (`sk-`, `api_key=`, `API_KEY=`, `Bearer <token>`) sin resultados. El nuevo camino de
  OpenRouter usa exclusivamente `config_manager.get_api_key("openrouter")` — el mismo punto
  único ya auditado que usa `_avisos_de_claves()` en `bridge.py` — nunca una clave en
  texto plano ni en un log (`_intentar_respaldos()`/`_cadena_de_respaldo_por_defecto()` solo
  registran nombres de proveedor y modelo, nunca el valor de la clave).
- **Sin exposición de errores crudos al usuario (CA-11).** Confirmado por lectura directa:
  la rama `if not cadena:` de `_intentar_respaldos()` (antes `return f"Error ({activo}):
  {error_original}"`) ahora devuelve siempre la constante `SIN_PROVEEDOR` — verifiqué el
  contenido exacto de esa constante (línea 485-488 de `ai/llm_provider.py`): texto genérico
  en español, sin traceback, sin nombre de excepción ni de módulo Python. El detalle técnico
  real sigue yendo solo a `logger.error(...)`, nunca al texto de respuesta.
- **Acciones destructivas / niveles de riesgo:** este REQ no introduce ninguna acción nueva
  clasificable en verde/amarillo/rojo — es selección/respaldo de proveedor LLM (lectura y
  enrutamiento interno), no una acción del catálogo de `security-levels.md`. Concuerda con
  la recomendación de `orion-architect`/`orion-coordinador` de no convocar a
  `orion-security` para este REQ, que confirmo por mi cuenta: no hay `os.system()`,
  `subprocess`, borrado de archivos, ni escritura de credenciales en ninguno de los 6
  archivos tocados.
- **`set_model()` (CA-03/CA-04):** el gate real del lado servidor —el que importa, porque el
  slot es invocable desde cualquier script de la página (mismo criterio que
  `delete_conversation`, REQ-015/§10.2)— retorna antes de tocar `config.json` y antes de
  emitir `notice_shown` cuando hay un destino fijado por tarea. Verificado por lectura
  directa de `bridge.py:1062-1077` y por los 3 tests nuevos de `tests/test_webview_bridge.py`
  que invocan el slot directamente (no vía UI), que corrí yo mismo — 195/195 en la suite
  dirigida, incluidos estos.
- **Sin `except: pass` silencioso introducido por este REQ.** Grep de `except.*:$` en los 5
  archivos de producto Python: todos los `except` capturan con `as e` y registran (`logger.
  error`/`logger.warning`) o son excepciones específicas manejadas explícitamente (p. ej.
  `requests.exceptions.ConnectionError`, `json.JSONDecodeError`). Encontré dos
  `except Exception: return <default>` sin logging (`ai/llm_provider.py:82`,
  `ai/claude_brain.py:26`) — **son código preexistente, fuera del diff de este REQ**
  (confirmado: no aparecen en `git diff` de este cambio), así que no son un hallazgo de
  REQ-022; los dejo anotados para que quede en el historial, sin bloquear este REQ.

## Niveles de riesgo

- Verde (puede actuar): selección/enrutamiento de proveedor LLM, lectura de
  `config.json`/`get_api_key()`, armado del aviso de cambio de modelo — todas lecturas o
  decisiones internas sin efecto en el sistema del usuario.
- Amarillo (debe confirmar): ninguna acción nueva de este REQ cae en esta categoría.
- Rojo (no ejecuta): ninguna acción nueva de este REQ cae en esta categoría.
- Se implementaron confirmaciones: N/A — este REQ no introduce ninguna acción que las
  requiera.

## Logging

- `_intentar_respaldos()` registra `logger.warning` en cada intento de respaldo fallido y
  `logger.error` cuando la cadena está vacía o todos fallan — el detalle de la excepción
  original va siempre al log, nunca se pierde silenciosamente.
- El swap preventivo por cooldown en `generate_response()` sigue registrando
  `logger.info` con el motivo (segundos restantes de cooldown) antes de rellenar `aviso`.
- `set_model()` registra `logger.info` cuando ignora la invocación por destino fijado —
  no es un fallo silencioso, queda trazado por qué no tuvo efecto.
- Ningún camino nuevo traga una excepción sin registrarla.

## Consistencia de código

- Convenciones de `.claude/rules/python-style.md`: type hints presentes en las funciones
  públicas/nuevas más relevantes (`_cadena_de_respaldo_por_defecto(activo: str) ->
  List[Tuple[str, str]]`, `texto_aviso_cambio(aviso: Optional[dict], corto: bool = False)
  -> str`, `con_aviso_de_cambio(...)`, `generate_response(..., aviso: Optional[dict] =
  None)`); `_resolver_cadena_de_respaldo(activo, fallback_config)` queda sin anotar sus dos
  parámetros — inconsistencia menor, no bloqueante.
- **Hallazgo menor de estilo:** una línea nueva excede el límite de 100 caracteres —
  `ai/llm_provider.py`, la línea `candidatos = [(activo, modelo_explicito)] +
  _resolver_cadena_de_respaldo(activo, fallback_provider)` (107 caracteres). Verificado con
  un diff acotado a las líneas efectivamente agregadas por este REQ en los 5 archivos
  Python de producto — es la única violación introducida. No afecta legibilidad de forma
  material ni es un riesgo funcional; queda anotado, no bloqueante.
- Sin dead code ni `print()` de debug: grep de `print(`/`console.log`/`debugger` sobre las
  líneas agregadas en los 6 archivos de producto — sin resultados.
- Logging usa el módulo `logging` estándar consistentemente, sin `print()`.
- La arquitectura documenta explícitamente (y correctamente, verificado por lectura) que
  `_cadena_de_respaldo()` no cambió de firma — los 14 tests preexistentes de
  `test_provider_fallback.py` siguen intactos salvo el único que documentaba el bug que
  CA-11 corrige a propósito (renombrado y reescrito, revisado: la nueva aserción
  (`resultado == SIN_PROVEEDOR`) es la correcta para el comportamiento nuevo).
- Los 2 tests de `test_provider_health.py` modificados (`test_sin_respaldo_configurado_...`
  y `test_cuando_el_proveedor_revive_...`) cambian de fixture porque el comportamiento que
  documentaban (fail-open sin alternativa) ya no aplica con el default de CA-06 activo —
  leí el razonamiento en los comentarios del diff y es correcto: antes "sin respaldo" ya no
  es cierto con el default agregado, así que había que mover el escenario a un proveedor
  (`ollama`) para el que el default no ofrece alternativa. No es una regresión oculta.
- Los 15 tests nuevos de la segunda vuelta (5 archivos) y los tests de GUI reescritos en
  `test_webview_buttons.py` los leí completos: ninguno es tautológico, todos comparan
  contenido concreto (strings exactos, listas vacías/no vacías) contra el resultado de
  invocar código de producto real, con mocks solo en el límite de red/proveedor —
  coincide con lo que reportó `orion-tester` en su segunda vuelta, confirmado por mi
  propia lectura, no solo por su reporte.
- `requirements.txt`: el único diff presente (paquete `openai`) es previo a este REQ y ya
  documentado como corregido fuera de su alcance (`SPEC-022.md`, sección "No incluye") —
  confirmado que no hay ninguna dependencia nueva introducida por REQ-022.

## Verificación independiente de pruebas

```
python -m pytest tests/test_llm_provider.py tests/test_reasoning_loop.py \
    tests/test_claude_brain.py tests/test_speech_prep.py tests/test_webview_bridge.py \
    tests/test_provider_fallback.py tests/test_provider_health.py --tb=short -q
→ 195 passed, 2 warnings (deprecations de speech_recognition, no relacionadas)
```

Coincide con lo reportado por `orion-tester` en su segunda vuelta (154 de los 5 archivos
core de REQ-022 + los de `test_provider_fallback.py`/`test_provider_health.py` que también
tocó este REQ). No repetí la suite completa de 1779 tests por costo/tiempo — `orion-tester`
ya la corrió dos veces (primera y segunda vuelta) con resultado 1779/1779, y mi corrida
dirigida de los 7 archivos más directamente relacionados con este REQ, con verificación de
contenido de cada test, es suficiente para el gate de QA sobre lo que este REQ cambia.

## Veredicto: ✅ COMPLETADO

Los 18 CA de `SPEC-022.md` están cubiertos en comportamiento (verificado en ambas vueltas de
`orion-tester`, no solo tomado por bueno) y ahora también en cobertura de tests commiteada.
Sin hallazgos de seguridad: no hay secretos hardcodeados, el error crudo del proveedor ya no
llega al usuario (CA-11), no se introduce ninguna acción destructiva ni un patrón nuevo de
manejo de credenciales, y el logging registra lo necesario sin tragar excepciones en
silencio. Los dos hallazgos de esta auditoría son menores y no bloqueantes: una línea que
excede el límite de 100 caracteres en `ai/llm_provider.py`, y dos `except Exception:` sin
logging que son código preexistente ajeno a este REQ. Ninguno de los dos es un riesgo de
seguridad ni afecta el comportamiento funcional.

Corresponde continuar con la prueba manual del humano antes de entregar el mensaje de
commit — ver solicitud abajo.
