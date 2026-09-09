# Log de desarrollo REQ-027 — Bucle de razonamiento de nivel agente

**Fecha:** 2026-09-08
**Rama:** `feature/REQ-027-reasoning-loop-nativo` (creada desde `feature/mcp-correo-flujos`)
**Implementado por:** conversación principal (pipeline acortado por decisión de Johan:
`orion-spec` + `orion-architect` con aprobación humana, después implementación directa)
**Base:** `arquitectura-027.md` (aprobada sin ajustes) + `SPEC-027.md` (aprobada sin ajustes)

---

## Por qué la rama no salió de `main`

Johan eligió "rama nueva desde `main`", pero al verificarlo en git resultó inviable:
`main` está en `b6b3cd6` y **no contiene REQ-026**. `git cat-file -e main:core/composer_modes.py`
falla, y ese archivo es donde CA-12 cuelga los presupuestos por modo — una rama desde `main`
habría nacido sin la dependencia.

`feature/mcp-correo-flujos` estaba exactamente **1 commit por delante de `main`**, y ese
commit es `d75008a` (REQ-026): o sea que, pese al nombre, hoy equivale a `main + REQ-026`.
Johan confirmó ramificar desde ahí.

---

## Orden de implementación

Se siguió el orden de 8 pasos de `arquitectura-027.md` §11, que deja la suite en verde en
cada paso.

| Paso | Qué | Archivos |
|---|---|---|
| 1 | Módulo neutral + sus tests | `core/tool_history.py` (nuevo), `tests/test_tool_history.py` (nuevo) |
| 2 | `MAX_TOKENS_SALIDA = 4096` | `ai/llm_provider.py` |
| 3 | Traductores + aplanado + caché | `ai/llm_provider.py` |
| 4 | Presupuesto por modo, `MAX_TOOL_ROUNDS` | `core/composer_modes.py`, `ai/claude_brain.py` |
| 5 | Encabezado, presupuesto, `_build_prompt` envoltorio | `core/reasoning_loop.py` |
| 6 | `_ejecutar_vuelta()` + historial neutral en `run()` | `core/reasoning_loop.py` |
| 7 | `_llamada_de_cierre()` + tests actualizados | `core/reasoning_loop.py`, `tests/test_reasoning_loop.py` |
| 8 | Suite completa contra el baseline | — |

---

## Archivos tocados

**Nuevos (2):**
- `core/tool_history.py` — formato neutral del historial. Módulo hoja: no importa nada del
  proyecto, así que el bucle y la capa de proveedores pueden depender de él sin ciclo.
- `tests/test_tool_history.py` — 23 tests.

**Modificados (5):**
- `ai/llm_provider.py` — constante `MAX_TOKENS_SALIDA`, los traductores
  `_mensajes_para_anthropic()` / `_mensajes_para_openai()` (+ dos helpers), `_debe_cachear()`,
  el aplanado en `_uncached_call()`, y los 4 adaptadores pasando a usar los traductores.
- `core/reasoning_loop.py` — presupuesto variable, historial neutral, ejecución de las N
  tool calls, llamada de cierre.
- `core/composer_modes.py` — campo `presupuesto` (obligatorio) y sus 4 valores.
- `ai/claude_brain.py` — `MAX_TOOL_ROUNDS` 3 → 5. Nada más (P-3 de Johan).
- `tests/test_reasoning_loop.py`, `tests/test_composer_modes.py` — tests nuevos y los 3
  actualizados.

**Sin dependencias nuevas.** `requirements.txt` no se toca.

---

## Desviaciones respecto de `arquitectura-027.md`

Dos, ninguna de diseño:

### 1. `_llamada_de_cierre()` no recibe `modo_def`

La arquitectura lista la firma con `modo_def` entre los parámetros, pero al implementarla
quedó sin ningún uso: lo único que el modo aporta a esa llamada es el `system_prompt` y la
`tarea`, y las dos ya se le pasan resueltas desde `run()` (donde se calculan una sola vez
por turno, D-10). Se omitió en vez de arrastrar un parámetro muerto. Es un helper privado,
no lo referencia ningún test ni ningún otro módulo.

### 2. El id sintético defensivo vive en `core/tool_history.py`, no en cada traductor

D-5 dice que el bucle normaliza el `id` y que "los traductores llevan además un respaldo
defensivo". Ese respaldo se implementó como `tool_history.con_ids_normalizados()`, una sola
función que ambos traductores llaman al entrar, en vez de dos copias de la misma lógica.
Motivo: si cada traductor numerara por su cuenta, dos proveedores podrían asignar ids
distintos al mismo historial, que es exactamente el problema que D-5 quiere evitar. El
módulo neutral es el que sabe cómo se emparejan llamada y resultado, así que es su trabajo.

---

## Detalles de implementación que vale registrar

### El primer mensaje de cada turno es byte a byte el de antes

`_mensajes_del_turno(task, prior_turns, [])` produce `[{"role": "user", "content":
_encabezado_de_tarea(task, prior_turns, False)}]`, y `_encabezado_de_tarea(..., False)` es
literalmente la rama "sin historial" del `_build_prompt()` anterior. O sea que la PRIMERA
llamada al modelo de cualquier turno sale idéntica a antes de REQ-027 — el cambio solo se
nota de la segunda vuelta en adelante.

### El texto del aviso de DeepSeek se extrajo del archivo, no se reescribió

`_ask_deepseek` concatenaba un aviso literal cuando llegaba una imagen. Al migrarlo al
traductor compartido, ese string se extrajo programáticamente del propio archivo y se pasó
como `aviso_sin_vision=`, en vez de volver a teclearlo: CA-08 exige que la llamada con el
formato viejo salga byte a byte igual, y un acento distinto habría bastado para romperlo.

### `_ejecutar_vuelta()` es una función aparte y no un bloque dentro de `run()`

Porque es lo que permite testear D-6 directamente (`len(llamadas) == len(resultados)` con
una denegación en medio) sin montar un turno completo. Ese invariante es el que decide si
esto funciona contra un proveedor real o solo contra mocks.

---

## Tests

### Los 3 que cambiaron de expectativa (previstos en `arquitectura-027.md` §7)

1. **`test_ca07_agota_5_llamadas_sin_una_sexta`** — pasa a aseverar sobre las llamadas que
   llevaron `tools` (== presupuesto) más el total (== presupuesto + 1, por el cierre).
   Aseverar sobre "las llamadas con herramientas" y no sobre el total expresa lo que el
   criterio significa y no se rompe si mañana cambia el mecanismo de cierre.
2. **`test_ca08_action_denied_corta_de_inmediato`** — `call_count` 1 → 2. **Es el único
   test de un camino de seguridad que este REQ modifica**, y Johan lo aprobó explícitamente
   (P-1). Se le agregaron dos asserts que antes no existían: que la segunda llamada va con
   `tools=None`, y que `estado["denied"]` sigue en `True`. Lo que CA-08 protegía —que no se
   reintente— queda ahora garantizado por construcción, no por una frase del prompt.
3. **`test_build_tool_list_con_modo_def_prioriza_sin_filtrar`** — construye un
   `ModoComposer` a mano y necesita el `presupuesto` nuevo.

### Correcciones a mis propios tests durante el desarrollo

- **CA-15 se mide por vueltas, no por "llamadas con `tools`".** En el canal `EMAIL` el
  catálogo por canal queda vacío, así que `tools` llega falsy y contar llamadas con
  herramientas mediría otra cosa. Lo que el presupuesto acota son las vueltas.
- La excepción de cancelación se llama `TurnoCancelado`, no `CancelacionSolicitada`.
- CA-31 tiene que usar una marca real de `_MARCAS_DE_FALLO` (`"no está configurada"`); un
  string de error inventado no lo detecta `es_respuesta_de_fallo()` y el test medía otra cosa.

---

## Resultado de la suite

Baseline (`origen/baseline-027.md`, mismo commit `d75008a`): **1828 passed, 0 failed**.

**Resultado: `1875 passed, 0 failed, 11 warnings` en 257s.**

+47 tests, cero regresiones. Los 11 warnings son los mismos del baseline (numpy/joblib en el
classifier, un `return` en `test_agents.py`) — ruido preexistente, no lo toca este REQ.

### Un fallo real encontrado en el camino (y por qué importa)

La primera corrida completa dio 2 fallos. Uno era un artefacto —se editó el docstring del
módulo MIENTRAS la suite corría, lo que corrió los números de línea y volvió loco a
`inspect.getsource()`—, pero **el otro era legítimo**:

`tests/test_skill_tools.py::test_el_texto_original_lo_pone_el_bucle_no_el_modelo` hace grep
sobre el fuente de `run()` buscando `params["texto_original"] = task`. Este REQ movió esa
línea a `_ejecutar_vuelta()`. El invariante de seguridad seguía intacto —de hecho ahora se
aplica a las N herramientas de la vuelta y no a una sola— pero **el test estaba mirando una
función donde el dato ya no estaba, y habría seguido "protegiendo" nada**.

Se corrigió apuntándolo a `_ejecutar_vuelta()` y, sobre todo, agregándole una verificación
de comportamiento que no depende de dónde esté escrita la línea: se le pasa un
`ToolCallRequest` con `texto_original="lo que nunca dijo"` y se verifica que quede pisado
por lo que dijo el usuario de verdad, en TODAS las llamadas de la vuelta. Un test estático
de seguridad que se puede romper moviendo una línea de lugar no es una garantía; ahora hay
las dos.

---

## Verificación de la DoD de `orion-dev`

- [x] Solo se implementó lo aprobado en arquitectura (2 desviaciones documentadas arriba)
- [x] Sin API keys ni tokens hardcodeados
- [x] Sin `except: pass` silencioso — verificado por grep en los 4 módulos tocados
- [x] Sin prints de debug — verificado por grep
- [x] Sin dependencias nuevas: `requirements.txt` sin cambios
- [x] No se tocaron skills (no aplica `BaseSkill`)
- [x] NO se ejecutó `git commit`
- [ ] Prueba manual de Johan (CA-35, CA-45) — pendiente
