# Auditoría de seguridad REQ-019 — Configuración de niveles de seguridad por el usuario

**Agente:** orion-security
**Fecha:** 2026-08-20
**Entrada auditada:** `workspace/adjuntos/REQ-019/propuestas/arquitectura-019.md` (completa, 28 CA
cubiertos, ✅ APROBADA por Johan) + `REQ-019-context.md` completo + `spec/SPEC-019.md` (28 CA) +
`origen/baseline-019.md` + código real: `core/security_manager.py` (387 líneas, completo),
`agents/tool_registry.py:73`, `ui/webview/bridge.py:1-40` (docstring/imports), `ui/gui_workers.py`
(`CallableWorker.run()`, `run_async()`), `tests/test_security_manager.py:116-120`. Verificado línea
por línea contra el código real del repo, no contra el texto de la propuesta — incluye ejecutar
mentalmente el pseudocódigo de `arquitectura-019.md` contra los 8 puntos del handoff de
`orion-architect`.

## Resumen ejecutivo

El diseño central del merge código+config (`_RISK_LEVEL_ORDER` + `_merge_with_override()` dentro de
`register_action()`) está bien resuelto: cubre los 3 niveles de forma simétrica (no solo RED), se
verificó que la comparación de rank es matemáticamente equivalente a `max(base, override)` para
cualquier combinación de niveles, y que se aplica en el único punto de entrada real por el que pasan
los 4 momentos de registro del sistema (`core/security_manager.py` ×3 + `agents/tool_registry.py:73`
×1) sin depender de orden de import. El catálogo `_SECURITY_ROWS_V1` en el bridge es una lista
estática cerrada de 8 filas que nunca incluye ninguna de las 10 claves 🔴 Rojo de REQ-005 — esto
excluye esas acciones de forma estructural (no es un filtro en runtime que se pueda saltar), y se
confirmó además una segunda capa de protección independiente en `_merge_with_override()`: incluso si
alguien edita `security_overrides.json` a mano e inyecta una entrada para `format_disk`, el propio
core la descarta por rank sin necesidad del catálogo del bridge. Es defensa en profundidad real, no
solo de UI, como pedía el punto 3 del handoff.

Sin embargo, se encontró **un hallazgo bloqueante** directamente en el punto 2 del handoff
(fail-closed ante datos corruptos): el manejo de excepciones propuesto en
`core/security_config.py::load_security_overrides()` no cubre todos los tipos de corrupción de
archivo que pueden ocurrir en la práctica — específicamente `UnicodeDecodeError`, que no es
subclase de `IOError`/`OSError` ni de `json.JSONDecodeError`. Como esta función se invoca de forma
síncrona en `SecurityManager.__new__()` (a nivel de import del módulo,
`core/security_manager.py:297`), una excepción no capturada ahí no degrada solo la pantalla de
Configuración — **crashea el import de `core/security_manager.py` y por lo tanto el arranque
completo de O.R.I.O.N.**, exactamente el escenario que el punto 2 del handoff pide descartar
explícitamente ("nunca crashea el arranque completo del sistema"). Es un ajuste acotado (ampliar una
cláusula `except`), no un rediseño.

También se encontró un bug de pseudocódigo (no de seguridad — su efecto es fail-closed, no
fail-open) en `ui/webview/bridge.py::_save_security_override_flow()`: referencia una constante
`_RISK_LEVEL_ORDER_LOCAL` que la propuesta nunca define. Se verificó contra `ui/gui_workers.py` que
cualquier excepción ahí (incluido un `NameError` por nombre indefinido) es capturada por
`CallableWorker.run()` y enrutada a `on_error` — es decir, tal como está escrito el pseudocódigo, el
mecanismo completo de guardado fallaría siempre de forma segura (rechazo total), no de forma
insegura. No es bloqueante, pero si `orion-dev` lo copia literalmente sin resolverlo, la función
"subir de nivel" quedaría inoperante — se deja como requisito obligatorio con la corrección concreta
(una sola fuente de verdad para el ranking, reusando `core.security_manager._RISK_LEVEL_ORDER` en
vez de inventar una segunda representación en `bridge.py`).

Ningún otro punto de los 8 del handoff arrojó un hallazgo bloqueante. El resto son observaciones no
bloqueantes documentadas abajo.

## Clasificación de riesgos implementados

| Punto auditado (handoff) | Nivel | ¿Confirmación? | Estado |
|---|---|---|---|
| 1. Merge simétrico 3 niveles — `_RISK_LEVEL_ORDER` + `_merge_with_override()` | 🟡 Amarillo (núcleo de seguridad) | Verificado matemáticamente equivalente a `max(base, override)` para GREEN/YELLOW/RED, no solo RED | ✅ |
| 1b. `register_action()` sigue protegiendo degradación de RED a nivel BASE (contrato original) | 🟡 Amarillo | Sí, sobre `_base_levels`, comportamiento observable idéntico a hoy | ✅ verificado contra `test_register_action_cannot_downgrade_red` (líneas 116-120) |
| 2. Fail-closed ante `security_overrides.json` corrupto/clave desconocida/valor inválido | 🔴 Rojo (afecta arranque completo si falla) | Diseñado, pero manejo de excepciones incompleto | ❌ REQUIERE CAMBIO — ver Hallazgo A |
| 3. Defensa en profundidad server-side en el bridge (CA-21) | 🟡 Amarillo | Diseño correcto (revalida rank sin confiar en el `<select>` de JS) | ⚠️ bug de pseudocódigo (nombre indefinido) — ver Hallazgo B, efecto es fail-closed no fail-open |
| 3b. Defensa en profundidad adicional en el núcleo (no pedida explícitamente, encontrada en la auditoría) | 🟢 Verde (protección extra) | `_merge_with_override()` bloquea downgrade de CUALQUIER acción aunque el archivo se edite a mano fuera del catálogo del bridge | ✅ hallazgo positivo |
| 4. Acciones sin clasificar (`classify_action() is None`) inalcanzables por este mecanismo | 🟡 Amarillo | Verificado en 2 puntos: `_build_security_overrides_payload()` (omite fila) y `_save_security_override_flow()` (rechaza clave) | ✅ |
| 5. Las 10 acciones RED de REQ-005 no configurables ni "reconfirmables" | 🔴 Rojo (mecanismo de PIN) | Catálogo `_SECURITY_ROWS_V1` estático sin ninguna clave RED + protección independiente en el core (ver 3b) | ✅ |
| 6. Auditoría sin caminos silenciosos | 🟡 Amarillo | `log_override_attempt()` (guardado, aceptado/rechazado) + `_log_audit()` en `_merge_with_override()` (downgrade ignorado) | ✅ |
| 7. `security_overrides.json` — superficie de escritura de archivos | 🟡 Amarillo | Ruta estática derivada de `__file__`, sin interpolación de input de usuario; claves de escritura acotadas al catálogo fijo | ✅ |
| 8. Inserción segura en el DOM (`settings_panel.js`) | 🟢 Verde | Solo `textContent`/`setAttribute`/`createElement` en el pseudocódigo; test estructural glob ya cubre el archivo nuevo | ✅ |

## Hallazgo A (bloqueante) — `load_security_overrides()` no cubre todos los tipos de corrupción de archivo; puede crashear el arranque completo

**Punto 2 del handoff, verificado contra el código propuesto en `arquitectura-019.md` §2:**

```python
try:
    with open(SECURITY_OVERRIDES_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
except (json.JSONDecodeError, IOError) as e:
    logger.warning(...)
    return {}
```

`IOError` es un alias de `OSError` en Python 3, así que esta cláusula cubre `PermissionError`,
`FileNotFoundError`, `IsADirectoryError`, etc. Y `json.JSONDecodeError` cubre JSON sintácticamente
inválido pero decodificable como texto. **Lo que no cubre:** `UnicodeDecodeError`, que es subclase de
`ValueError`, no de `OSError` ni de `json.JSONDecodeError`. `open(..., encoding="utf-8")` +
`json.load(f)` invoca `TextIOWrapper.read()` internamente, que lanza `UnicodeDecodeError` si el
archivo contiene bytes que no son UTF-8 válido — exactamente el tipo de corrupción más probable en la
práctica (un archivo truncado a mitad de escritura por un corte de energía, un editor que guardó con
otra codificación, bytes basura). Es un escenario de corrupción más realista que "JSON válido en UTF-8
pero con sintaxis rota", y el diseño actual no lo cubre.

**Por qué es bloqueante y no una observación menor:** `load_security_overrides()` se invoca desde
`core.security_manager._load_and_parse_overrides()`, que a su vez se llama **dentro de
`SecurityManager.__new__()`** (arquitectura-019.md §1.2) — es decir, en la construcción del singleton
que ocurre al ejecutar `security_manager = SecurityManager()` a nivel de módulo
(`core/security_manager.py:297`, **tiempo de import**). `core/security_manager.py` es importado
transitivamente por prácticamente todo el sistema (dispatcher, action_registry, bridge, main.py). Una
excepción no capturada acá no se queda contenida en "la pantalla de Configuración no carga" — tumba el
import del módulo de seguridad completo, y con él el arranque de toda la aplicación. Esto es
precisamente el escenario que el handoff pide descartar de forma explícita ("nunca crashea el arranque
completo del sistema") y que la propia arquitectura declara como objetivo en su docstring de §2
("el peor caso posible es dict vacío") — el código tal como está escrito no logra ese objetivo en todos
los casos.

**Ajuste requerido (acotado, no rediseño):**
1. En `core/security_config.py::load_security_overrides()`, ampliar la cláusula `except` para cubrir
   también errores de decodificación, por ejemplo:
   ```python
   except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
       logger.warning(f"security_overrides.json corrupto/ilegible — se ignora por completo, "
                       f"fallback a nivel de código: {e}")
       return {}
   ```
   (`OSError` en vez de `IOError` es equivalente — son el mismo tipo en Python 3 — se sugiere el
   nombre canónico para dejar explícito qué se captura). Alternativamente, dado que el propio
   `.claude/rules/python-style.md` permite un `except Exception` amplio siempre que se loguee (no es
   un `except: pass` silencioso), es aceptable envolver todo el bloque de lectura+parseo en
   `except Exception as e:` con el mismo `logger.warning` — es la opción más robusta porque no
   depende de anticipar cada subtipo de excepción posible de I/O/decodificación.
2. Recomendado como defensa en profundidad adicional (no bloqueante en sí, pero de bajo costo dado lo
   crítico del punto): envolver también la llamada a `load_security_overrides()` dentro de
   `_load_and_parse_overrides()` (en `core/security_manager.py`) en un `try/except Exception` propio,
   con fallback a `{}` — así, incluso si en un REQ futuro se modifica `security_config.py` y se
   reintroduce un hueco de excepción no capturada, el punto de construcción del singleton (el lugar
   más caro para fallar de todo el sistema) queda protegido por dos capas independientes.

Ninguna de las demás decisiones de `arquitectura-019.md` §2 (archivo separado, escritura atómica,
fallback a "sin overrides" nunca a "sin restricciones", filtrado de claves/valores inválidos) requiere
cambios — el hallazgo es puntual sobre la cobertura de la cláusula `except`.

## Hallazgo B (no bloqueante, requisito obligatorio para orion-dev) — Nombre indefinido en la validación server-side del bridge; unificar la fuente de verdad del ranking

`arquitectura-019.md` §3.3, dentro de `_save_security_override_flow()`:

```python
can_apply = _RISK_LEVEL_ORDER_LOCAL[requested] >= _RISK_LEVEL_ORDER_LOCAL[current]
```

`_RISK_LEVEL_ORDER_LOCAL` no está definido en ningún punto de la propuesta. §3.1 solo define
`_LEVEL_ORDER = ["green", "yellow", "red"]` (lista de strings, usada en `_build_security_overrides_payload()`
vía `.index()`), que es una representación distinta (y con nombre distinto) de la que usa este bloque
(`requested`/`current` son instancias de `RiskLevel`, no strings). Verificado contra
`ui/gui_workers.py::CallableWorker.run()` (líneas 46-48): cualquier excepción dentro de
`_save_security_override_flow()` —incluido un `NameError` por este nombre indefinido— es capturada por
un `except Exception` genérico y enrutada a `on_error`, que por diseño de la propia arquitectura emite
`security_override_save_rejected`. **Confirmado: el efecto de este bug, tal cual está escrito, es
fail-closed (todo guardado se rechaza), nunca fail-open.** No es un hallazgo de seguridad — es un
hallazgo de completitud del pseudocódigo que, sin corregir, dejaría el mecanismo de "subir de nivel"
completamente inoperante en la práctica.

**Recomendación concreta para `orion-dev`:** no definir una tercera representación del ranking en
`bridge.py`. Importar directamente `core.security_manager._RISK_LEVEL_ORDER` (o exponer un helper
público, ej. `security_manager.rank(level: RiskLevel) -> int`) y usarlo tanto para la comparación de
`_save_security_override_flow()` como, si se quiere, para construir `options` en
`_build_security_overrides_payload()` en vez de mantener `_LEVEL_ORDER` (lista de strings) como una
segunda fuente de verdad paralela. Tener dos representaciones del mismo orden en dos módulos distintos
es exactamente el tipo de duplicación que, en un REQ futuro, puede hacer que una se actualice y la otra
no (ej. si algún día se agrega un nivel intermedio) — reabriendo silenciosamente un hueco de
downgrade en la validación que hoy es el punto CA-21 más crítico de todo el diseño. Resolver esto no
requiere volver a `orion-architect`: es una precisión de implementación, no un cambio de diseño.

## Hallazgo C (no bloqueante, observación) — Catálogo v1 permite subir una acción Verde directo a Rojo

`_build_security_overrides_payload()` construye `options` como `_LEVEL_ORDER[current_idx:]` — para
una fila hoy GREEN (todas las de la categoría v1: abrir Chrome, Bloc de notas, etc.), esto ofrece
`["green", "yellow", "red"]`, es decir, el `<select>` permite llevar directamente "Abrir Chrome" a
🔴 Rojo. Esto no viola ningún CA (CA-16 solo exige "nunca un nivel inferior al vigente", y RED es
superior) ni abre ningún hueco de seguridad (subir nunca es inseguro, por definición del propio
mecanismo). Pero sí puede producir un auto-bloqueo confuso: si el usuario sube "Abrir Chrome" a Rojo y
no tiene `ORION_AUTH_PIN` configurado (`has_pin()` devuelve `False`),
`require_confirmation()` (líneas 283-293) deja esa acción permanentemente bloqueada sin ninguna vía de
recuperación desde la UI — la única salida sería editar `security_overrides.json` a mano. No es un
hallazgo de seguridad (el sistema se vuelve más restrictivo, no menos) y ningún CA de la SPEC pide
evitarlo, así que no lo marco bloqueante — pero dado que el objetivo explícito de v1 (SPEC-019, ASUMIDO
de categoría) es demostrar "Verde→Amarillo" y nada pide alcanzar Rojo desde esta pantalla, sugiero a
`orion-architect`/`orion-dev` evaluar acotar `options` a un techo de `yellow` para la categoría v1
(ej. `_LEVEL_ORDER[current_idx : _LEVEL_ORDER.index("red")]` cuando el nivel base sea GREEN), o al
menos que Johan lo confirme explícitamente si prefiere dejarlo abierto a RED. Queda a criterio de
`orion-dev` resolverlo sin volver a `orion-architect`, ya que no cambia ningún contrato del backend, solo
el recorte de `options` que ya construye la propia función.

## Secretos

- Los overrides son exclusivamente `{clave_interna_de_acción: "green"|"yellow"|"red"}` — verificado
  contra el esquema completo de `_SECURITY_ROWS_V1`, `load_security_overrides()` y
  `save_security_overrides()`: ninguna estructura nueva admite texto libre, tokens, ni paths (CA-26).
- `security_overrides.json` no contiene ni puede contener API keys/tokens por construcción — el único
  tipo de valor válido es uno de los 3 strings de nivel.
- No se introduce ninguna dependencia nueva (`json`/`os`/`tempfile` son librería estándar), no hay
  superficie nueva de credenciales.
- Sin hallazgos de secretos expuestos.

## Validación de inputs

- `SECURITY_OVERRIDES_FILE` es una ruta estática derivada de `os.path.dirname(__file__)` en tiempo de
  import — no depende de `row_id`, `level`, ni de ningún valor proveniente de JS/usuario. No hay
  interpolación de rutas ni riesgo de path traversal (punto 7 del handoff, confirmado).
- El lado de escritura (`save_security_overrides()`) solo persiste `accepted_keys`, derivadas
  exclusivamente de `row["keys"]` del catálogo estático `_SECURITY_ROWS_V1` — el `row_id`/`level`
  crudos que llegan desde JS nunca se usan directamente como clave de escritura, siempre se resuelven
  primero contra el catálogo fijo.
- `save_security_override(row_id: str, level: str)` valida `row_id` contra `_SECURITY_ROW_BY_ID` (lookup
  en dict cerrado, `None` si no existe) y `level` contra `RiskLevel(level)` (lanza `ValueError` si no es
  `green`/`yellow`/`red`) antes de cualquier otro procesamiento — ambos casos de input inválido cortan el
  flujo sin persistir nada.
- El rank server-side se recalcula en el propio slot sin confiar en `options` (lo que ofreció el
  `<select>` de JS) — confirmado que un intento directo por DevTools con un nivel inferior al vigente
  se rechaza igual, con el mismo audit trail que un intento normal (punto 3 del handoff, CA-21).
- No hay `os.system()`/`subprocess` en ningún punto de este REQ.

## Recomendaciones (resumen)

1. **[Bloqueante — Hallazgo A]** Ampliar la cláusula `except` de
   `core/security_config.py::load_security_overrides()` para cubrir `UnicodeDecodeError` (o adoptar un
   `except Exception` amplio con logging) — el fallback a `{}` debe ser alcanzable ante CUALQUIER forma
   de corrupción de archivo, no solo JSON sintácticamente inválido. Recomendado (no bloqueante en sí)
   agregar una segunda capa de `try/except` en `_load_and_parse_overrides()` dado lo crítico del punto
   de construcción del singleton.
2. **[No bloqueante — Hallazgo B, requisito obligatorio para orion-dev]** Resolver
   `_RISK_LEVEL_ORDER_LOCAL` (nombre indefinido) reusando `core.security_manager._RISK_LEVEL_ORDER`
   como única fuente de verdad del ranking, en vez de mantener una segunda representación paralela en
   `ui/webview/bridge.py`.
3. **[No bloqueante — Hallazgo C]** Evaluar si el catálogo v1 debe limitar `options` a un techo de
   `yellow` (evitar autobloqueo por salto directo a Rojo sin PIN configurado) o confirmar
   explícitamente con Johan que RED es una opción válida desde esta pantalla en v1.
4. **[No bloqueante]** En `core/security_config.py::_atomic_write()`, la llamada a
   `tempfile.mkstemp()` queda fuera del bloque `try/except IOError` — en la práctica no crashea nada
   (se ejecuta en el hilo de `run_async`, que captura `Exception` de forma genérica y enruta a
   `on_error`), pero para un mensaje de error más específico se sugiere mover `mkstemp()` dentro del
   `try` y ampliar el `except` a `OSError`.
5. **[No bloqueante]** Los tests sugeridos en la propia arquitectura para CA-02/CA-03 inyectan
   directamente `security_manager._config_overrides[name] = ...` sobre el singleton compartido de
   `pytest` — recomendar a `orion-tester` que cada test de este tipo limpie la entrada inyectada al
   finalizar (fixture con `pop`/`teardown`), para evitar contaminación entre tests que reutilizan el
   mismo singleton dentro de la misma sesión de pytest.

## Veredicto: ❌ REQUIERE CAMBIOS

El diseño central (merge de 3 niveles, catálogo estático que excluye RED de REQ-005, defensa en
profundidad server-side, separación de `security_overrides.json`, auditoría de intentos de bajada y de
guardados) es sólido y no requiere rediseño — de hecho se verificó una capa de protección adicional
(el propio `_merge_with_override()` bloquea downgrade de cualquier acción, no solo las del catálogo del
bridge) que ni la SPEC ni la arquitectura pedían explícitamente. El único hallazgo bloqueante
(Hallazgo A) es un ajuste puntual y acotado a una cláusula `except` en un único archivo nuevo
(`core/security_config.py`), consistente con el patrón de "ajuste, no rediseño" ya usado en
`security-audit-015.md`. Se recomienda que `orion-architect` incorpore la corrección de Hallazgo A a
`arquitectura-019.md` §2 (y, si lo considera de bajo costo, también la recomendación de segunda capa en
`_load_and_parse_overrides()`) antes de pasar a `orion-dev`. Los Hallazgos B y C no requieren volver a
`orion-architect` — quedan como requisitos concretos para que `orion-dev` los resuelva directamente
durante la implementación.

---

## Re-auditoría — 2da pasada orion-security (verificación del addendum §11 de `arquitectura-019.md`)

**Agente:** orion-security · **Fecha:** 2026-08-20
**Origen:** handoff de `orion-architect` tras agregar el §11 "Ajustes de seguridad post-auditoría" a
`arquitectura-019.md`, respondiendo punto por punto a los 3 hallazgos de la 1ra pasada (A bloqueante,
B y C no bloqueantes). Entrada auditada: `arquitectura-019.md` completa — confirmado que §1-§10 no
cambiaron (el addendum es exclusivamente §11, sin ediciones retroactivas al resto del documento) —
más este mismo `security-audit-019.md` (1ra pasada) y `REQ-019-context.md` completo.

**Nota de alcance:** este REQ todavía no pasó por `orion-dev` — confirmado que `core/security_config.py`
no existe en el repo y que `core/security_manager.py` no tiene ningún símbolo de REQ-019
(`_RISK_LEVEL_ORDER`, `_base_levels`, `_config_overrides`, `_merge_with_override`, etc.; el único
diff pendiente sobre ese archivo es de REQ-015/016, ajeno a este REQ). Por lo tanto esta verificación
es sobre el pseudocódigo del addendum §11 tal como quedó redactado, no sobre un diff de código real —
mismo criterio que ya aplicó la 1ra pasada sobre §1-§10.

### 1. Hallazgo A (bloqueante) — CERRADO

`arquitectura-019.md` §11.1 reemplaza el `except (json.JSONDecodeError, IOError)` original por
`except Exception as e:` alrededor de `open()`+`json.load()`, con `logger.warning` que incluye
`type(e).__name__` y el mensaje — exactamente la opción que esta auditoría había ofrecido como
alternativa válida ("es aceptable envolver todo el bloque... en `except Exception as e:`... permitido
por `.claude/rules/python-style.md` siempre que se loguee"). Esto cubre `UnicodeDecodeError` (el caso
concreto que faltaba) y cualquier otro tipo de excepción no anticipada de la misma naturaleza
(I/O, decodificación), sin excepción silenciosa: **no se traga nada sin loguear**, cumple el requisito
que pedí explícitamente para no introducir un problema nuevo al cerrar este hallazgo.

Segunda capa adoptada tal cual se recomendó: `core/security_manager.py::_load_and_parse_overrides()`
envuelve la llamada a `load_security_overrides()` en su propio `try/except Exception`, también con
`logger.warning` (mismo criterio, no silencioso), fallback a `raw = {}`. Con las dos capas, ningún tipo
de corrupción de `security_overrides.json` puede propagarse hasta `SecurityManager.__new__()` — el
peor caso queda garantizado en "sin overrides" (nivel de código puro), nunca un crash del import. El
escenario original (arranque completo de O.R.I.O.N. caído por un archivo con bytes no-UTF-8) queda
cerrado por construcción, no por casualidad de qué excepciones se anticiparon.

**Una observación no bloqueante, nueva en esta pasada:** en `_load_and_parse_overrides()` (§11.1), la
línea `from core.security_config import load_security_overrides` queda FUERA del `try/except` que le
sigue — un `ImportError`/`SyntaxError` real en el módulo nuevo `core/security_config.py` (ej. un bug
introducido por `orion-dev` al escribirlo) no quedaría cubierto por esta segunda capa. No lo marco como
extensión del Hallazgo A porque es una clase de falla distinta: Hallazgo A trata corrupción de *datos*
en tiempo de ejecución (el archivo `.json`, que un usuario puede corromper sin tocar código), mientras
que un fallo de import es un *bug de código* que `python -m py_compile` (CA-23, parte obligatoria del
DoD de `orion-dev`/`orion-tester`) atraparía antes de que el REQ avance — no es algo contra lo que el
manejo de excepciones en runtime deba defender. Además es el mismo patrón de import perezoso sin guardia
que ya usa el resto de `security_manager.py` hoy (ej. `from core.confirmation import
get_confirmation_adapter` dentro de `require_confirmation()`, sin try/except alrededor). Se deja
anotado para que `orion-tester` confirme el `py_compile` de `core/security_config.py` como parte de
CA-23, no como acción para `orion-dev`.

### 2. Hallazgo B (no bloqueante) — CERRADO

`arquitectura-019.md` §11.2 elimina `_LEVEL_ORDER` (lista de strings) y el nombre indefinido
`_RISK_LEVEL_ORDER_LOCAL`, y hace que `bridge.py` importe directo
`from core.security_manager import RiskLevel, _RISK_LEVEL_ORDER` — la opción de "una sola fuente de
verdad" que esta auditoría había recomendado como preferible a exponer un helper público nuevo.
`_ORDERED_LEVEL_VALUES` se deriva del propio `_RISK_LEVEL_ORDER` (`sorted(...)` por rank + `.value`),
nunca se mantiene a mano en paralelo — verificado que el resultado es idéntico al `_LEVEL_ORDER`
original (`["green", "yellow", "red"]`) para el único uso que le da el bridge. La comparación de
`_save_security_override_flow()` pasa a `_RISK_LEVEL_ORDER[requested] >= _RISK_LEVEL_ORDER[current]`
sobre el dict importado — el `NameError` desaparece, la función de "subir de nivel" queda operativa.

Verifiqué además que importar un símbolo con prefijo `_` de `core.security_manager` a nivel de módulo
en `bridge.py` no es un patrón nuevo ni introduce riesgo de import circular: el propio
`ui/webview/bridge.py` real (línea 43) ya hace `from core.security_manager import ChannelType` a nivel
de módulo hoy — mismo tipo de símbolo (dato/tipo, no el singleton `security_manager`, que sí se importa
perezoso dentro de cada función). El addendum sigue exactamente ese precedente.

**Observación no bloqueante, nueva en esta pasada (cosmética, no de seguridad):** el pseudocódigo
original de §3.3 seguía teniendo `from core.security_manager import RiskLevel, security_manager` como
import perezoso dentro de `_save_security_override_flow()`; con el import de módulo nuevo de §11.2
(`RiskLevel` también top-level), ese `RiskLevel` local queda redundante (un rebind que no rompe nada,
pero es duplicación de la misma importación en dos lugares). Anotado para que `orion-dev` lo limpie al
implementar (dejar el import local solo con `security_manager`, ya que `RiskLevel` viene del import de
módulo) — no bloquea el avance.

### 3. Hallazgo C (no bloqueante) — CERRADO, con una inconsistencia de documentación a señalar

`arquitectura-019.md` §11.3 adopta la sugerencia de esta auditoría: `_V1_MAX_OFFERABLE_LEVEL =
RiskLevel.YELLOW`, aplicado en **ambos lados**, tal como pedía el punto 3 del handoff original:

- **Lado UI** (`_build_security_overrides_payload()`): `options = _ORDERED_LEVEL_VALUES[current_rank :
  max(current_rank, ceiling_rank) + 1]`. Verifiqué la aritmética para los 3 casos posibles del
  catálogo v1: GREEN → `["green", "yellow"]` (nunca `"red"`); YELLOW (ya en el techo) →
  `["yellow"]` (sin opción de subida, correcto para v1); y el caso borde documentado explícitamente
  por el propio addendum (si un REQ futuro reclasificara el código base a RED) → el `max()` evita que
  el recorte quede por debajo del nivel vigente, preservando CA-16 en cualquier escenario. Sin hueco.
- **Lado servidor** (`_save_security_override_flow()`): chequeo adicional que rechaza (`all_ok = False`,
  mismo camino de auditoría que un intento de bajada) cualquier `requested` por encima del techo v1,
  sin depender de qué `options` haya ofrecido el `<select>` de JS — exactamente la defensa en
  profundidad server-side que pedí, no solo un recorte cosmético en el payload.

No es un hueco de seguridad en ninguna dirección: el sistema queda MÁS restrictivo en v1 (nunca permite
Rojo desde esta pantalla), nunca menos.

**Hallazgo nuevo, no bloqueante — inconsistencia de documentación a resolver antes de `orion-tester`:**
la sección "Pruebas sugeridas" de `arquitectura-019.md` (previa al addendum, sin actualizar) todavía
dice, para CA-16: *"para una fila con `effective_level == "yellow"`, `options == ["yellow", "red"]`
(nunca incluye `"green"`)"*. Con el techo de §11.3 ya adoptado, ese resultado esperado quedó **obsoleto
y contradictorio**: una fila con `effective_level == "yellow"` ahora debe producir `options ==
["yellow"]` (sin `"red"`, el techo v1 ya está alcanzado). Si `orion-tester` (o `orion-dev` al escribir
el test) sigue la redacción literal pre-§11 sin cruzarla contra §11.3, escribiría una aserción que
contradice el comportamiento correcto y recién exigido por esta misma auditoría. No reabre el diseño
(la corrección de código en §11.3 es la que manda) — dejo la nota explícita para que `orion-dev` use
`["yellow"]` como resultado esperado de ese caso, ignorando el valor literal de la sección "Pruebas
sugeridas" pre-addendum en ese punto puntual.

### 4. Verificación cruzada final — nada del addendum reabre lo ya aprobado

Confirmado contra §11.5 ("Qué NO cambia") y contra lectura propia de §1-§10: el mecanismo central
(`_RISK_LEVEL_ORDER`, `_merge_with_override()` dentro de `register_action()`, distinción base/efectivo),
la decisión de archivo separado `security_overrides.json` ya aprobada por Johan, el catálogo de 8 filas/
9 claves, el frontend (§4), la inserción segura en el DOM (§6) y el contenido nuevo de
`.claude/rules/security-levels.md` (§7) no tienen ningún cambio en el addendum — coincide con lo
declarado. Ninguno de los 3 cierres introduce una acción nueva sin clasificar, un secreto expuesto, ni
un camino de escritura de archivo que dependa de input crudo de JS/usuario — se mantienen las mismas
conclusiones de las secciones "Secretos" y "Validación de inputs" de la 1ra pasada, sin cambios.

### Veredicto: ✅ APROBADO

Los 3 hallazgos de la 1ra pasada quedan cerrados en el addendum §11 de `arquitectura-019.md`:
Hallazgo A (bloqueante) cerrado por construcción con doble capa de `except Exception` + logging no
silencioso; Hallazgo B cerrado con una única fuente de verdad del ranking (`_RISK_LEVEL_ORDER`
importado directo, mismo patrón ya usado hoy en `bridge.py` para `ChannelType`); Hallazgo C cerrado
con techo `yellow` aplicado en ambos lados (UI y servidor), sin hueco de seguridad en ningún escenario
verificado. No se encontró ningún hallazgo bloqueante nuevo. Quedan 3 notas no bloqueantes para
`orion-dev`/`orion-tester` (import de `core/security_config.py` sin guardia — cubierto por CA-23;
limpieza de un import local redundante en `bridge.py`; y la aserción de test CA-16 obsoleta en la
sección "Pruebas sugeridas" pre-addendum, que debe usar `["yellow"]` en vez de `["yellow", "red"]`
para el caso `effective_level == "yellow"`). El REQ pasa a `@orion-dev`.
