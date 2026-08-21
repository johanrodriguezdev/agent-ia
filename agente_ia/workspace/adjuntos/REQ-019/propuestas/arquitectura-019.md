# Arquitectura REQ-019 — Configuración de niveles de seguridad por el usuario

**Agente:** orion-architect
**Fecha:** 2026-08-20
**Basado en:** `REQ-019-context.md`, `spec/SPEC-019.md` (28 CA), `origen/baseline-019.md` — releído
línea por línea del código real (`core/security_manager.py`, `config_manager.py`,
`ui/webview/bridge.py`, `ui/webview/frontend/js/app.js`, `agents/tool_registry.py`,
`agents/skill_tools.py`, `tests/test_security_manager.py`), sin tomar como dada la
investigación de agentes previos.

**Nota de proceso — no negociable (CA-28):** esta arquitectura NO se entrega a `orion-dev`
al aprobarse. El siguiente paso obligatorio es `@orion-security`, ya fijado por la SPEC.

---

## Desvío documentado de un ASUMIDO de SPEC-019 (requiere tu confirmación explícita)

SPEC-019 marcó como ASUMIDO (aprobado por vos "tal cual") que la persistencia usa
`config.json`/`config_manager.py`, dejando explícitamente abierta la puerta a que
`orion-architect` proponga una alternativa "si encuentra una razón técnica de peso,
documentada como decisión suya".

**Propongo NO extender `config.json`** y usar en cambio un archivo nuevo y dedicado,
`security_overrides.json`, gestionado por un módulo nuevo `core/security_config.py`
(nunca tocando `config_manager.py`). Razón concreta, con evidencia de baseline:

- `config_manager.py::load_config()` (líneas 55-57) es "todo o nada": si el JSON está
  corrupto por CUALQUIER motivo (p. ej. el usuario edita `weather_city` a mano y rompe la
  sintaxis), la función sobreescribe el archivo COMPLETO con `DEFAULT_CONFIG`. Si los
  overrides de seguridad vivieran ahí, una corrupción de una clave que no tiene nada que
  ver con seguridad borraría también la configuración de seguridad guardada. No es un
  agujero de seguridad (el sistema cae a nivel de código, que sigue siendo seguro — CA-06),
  pero sí una pérdida de datos silenciosa e inesperada para el usuario, evitable.
- `config_manager.py::save_config()` (líneas 60-65) no usa escritura atómica. Reforzar
  esa garantía para TODO `config.json` es un cambio de alcance grande (lo usan
  `agent_name`, `display_name`, `weather_city`, `ui_theme` — ningún CA de esta SPEC lo
  pide). Aislar los overrides de seguridad en su propio archivo permite dar escritura
  atómica exactamente donde importa (CA-11) sin tocar el resto del sistema de config.
- Aislar el archivo también aísla el radio de impacto en la dirección inversa: un
  `security_overrides.json` corrupto nunca puede tumbar `ui_theme`/`display_name`/etc.

Esto **no cambia ningún CA en su espíritu** (todos siguen cubiertos, ver tabla abajo) —
cambia el nombre de archivo que CA-06/CA-09 mencionan implícitamente. Si preferís mantener
todo en `config.json` tal como decía el ASUMIDO original, es un ajuste menor y te lo
adapto antes de pasar a `orion-security`.

---

## Cobertura de criterios de la SPEC (28 CA)

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-01 | `_RISK_LEVEL_ORDER: Dict[RiskLevel, int]` nuevo en `core/security_manager.py` (ranking explícito, ver "Núcleo de seguridad" §1). |
| CA-02 | `SecurityManager._merge_with_override()` nuevo: `effective = override if rank(override) >= rank(base) else base`, aplicado dentro de `register_action()` en cada registro. Test estructural con acción YELLOW + override GREEN → `require_confirmation()` sigue pidiendo confirmación. |
| CA-03 | Mismo mecanismo de CA-02, sin caso especial para RED — `max()` por ranking ya cubre RED de forma genérica (no hace falta lógica aparte). |
| CA-04 | `_merge_with_override()` llama `_log_audit(..., "override_bajada_ignorada", ...)` cuando descarta un intento de bajada detectado al aplicar overrides persistidos; `SecurityManager.log_override_attempt()` (nuevo, público) audita cada intento de guardado desde el bridge, aceptado o rechazado. |
| CA-05 | El bridge sólo acepta un `row_id` del catálogo v1 fijo (`_SECURITY_ROWS_V1`); antes de escribir valida `security_manager.classify_action(key) is not None` para cada clave interna — si no está clasificada, se ignora con `logger.warning` y no se persiste nada. |
| CA-06 | `core/security_config.py::load_security_overrides()` nunca crashea: archivo inexistente → `{}`; JSON corrupto/IO error → `{}` + `logger.warning`; no es dict → `{}` + warning; clave no-string o valor fuera de `{green,yellow,red}` → se descarta esa entrada puntual + warning, el resto del archivo se sigue respetando. Fallback siempre es "sin overrides" = nivel de código puro, nunca "sin restricción". |
| CA-07 | `_merge_with_override()` no recibe ni consulta `channel` en ningún punto — el nivel efectivo es el mismo para los 5 `ChannelType`; `CHANNEL_ALLOWED_LEVELS` no se toca. |
| CA-08 | El catálogo `_SECURITY_ROWS_V1` es una lista fija de 8 filas, ninguna cubre las 10 claves RED de REQ-005 — no hay forma de que aparezcan en la UI porque nunca se agregan al catálogo (no es un filtro en runtime, es la propia composición estática de la lista). |
| CA-09 | El override persiste en `security_overrides.json` en disco; `SecurityManager` lo relee al construirse (`__new__` → `_load_and_parse_overrides()`), que ocurre una vez por proceso — sobrevive a cerrar/abrir la app. |
| CA-10 | `security_override_saved` (señal nueva) llega a `settings_panel.js`, que muestra un banner inline "Este cambio se aplicará la próxima vez que abras la app." — nunca implícito. Ver §5. |
| CA-11 | `core/security_config.py::save_security_overrides()` escribe con `os.replace()` (atómico en Windows/POSIX) ANTES de que `Bridge._save_security_override_flow()` emita `security_override_saved`; la UI solo muestra "guardado" después de recibir esa señal — no hay hueco entre "aviso visual" y "dato en disco". |
| CA-12 | Botón `#settings-btn` nuevo en `index.html`, mismo `class="sidebar-action-btn"` que `#tasks-btn`/`#projects-btn`; wiring en `app.js`, no en `sidebar.js` (corrección confirmada por baseline). |
| CA-13 | `settings_panel.js` monta un modal con nav lateral (secciones) + panel de tarjetas a la derecha, mismo patrón WorkBuddy AI de la SPEC — ver §4. |
| CA-14 | Sección "Seguridad" en la nav lateral — única sección poblada en v1, estructura ya preparada para agregar más sin rediseño. |
| CA-15 | Una tarjeta con una fila por cada una de las 8 entradas del catálogo v1: label + nivel efectivo a la izquierda, `<select>` a la derecha. |
| CA-16 | El payload del bridge ya viene con `options` recortado (`_LEVEL_ORDER[current_idx:]`) — el `<select>` de JS SOLO renderiza esas opciones, nunca construye la lista completa ni permite un nivel inferior, ni oculto ni deshabilitado. |
| CA-17 | Todo texto de `settings_panel.js` que viene de Python usa `textContent`/`setAttribute`; `settings_panel.js` se agrega a la lista `_MUST_NOT_USE_INNERHTML` de `tests/test_webview_safe_dom_insertion.py`. |
| CA-18 | No existe estado "pendiente sin guardar": cada cambio de `<select>` dispara `saveSecurityOverride()` de inmediato (modelo "aplicar al elegir", no "elegir y confirmar aparte") — cerrar el modal nunca puede descartar algo que ya se envió. Ver §4 para el porqué de esta decisión. |
| CA-19 | `requestSecurityOverrides()` se llama solo dentro de `openSettingsPanel()`, nunca desde `request_initial_state()` — mismo criterio que CA-12 de SPEC-016 para Tareas. |
| CA-20 | Docstring de `ui/webview/bridge.py` (líneas 1-33) extendido con la whitelist de los 2 slots y 3 señales nuevas. |
| CA-21 | `Bridge._save_security_override_flow()` recalcula `classify_action(key)` y compara contra el nivel pedido con `_RISK_LEVEL_ORDER` ANTES de escribir, sin importar qué mandó JS — un script que invoque `save_security_override()` directo desde DevTools con un nivel inferior es rechazado igual, con el mismo `log_override_attempt(..., accepted=False)`. |
| CA-22 | JS nunca calcula rank ni hace `max()` — solo pinta `options`/`effective_level` tal cual llegan y reenvía la intención (`row_id`, `level` elegido) al bridge. |
| CA-23 | `python -m py_compile` sobre los 3 módulos nuevos/modificados (`core/security_manager.py`, `core/security_config.py`, `ui/webview/bridge.py`) — a verificar por `orion-dev`/`orion-tester`. |
| CA-24 | Suite completa se reejecuta contra el baseline de 420 passed/2 failed (pre-existentes, ajenos). |
| CA-25 | `register_action()` conserva firma y contrato públicos: sigue devolviendo `False` y sin aplicar el cambio cuando `current_base == RED` y `level != RED` — la protección de RED se mueve a operar sobre `self._base_levels` (nuevo) en vez de `self._actions`, pero el resultado observable para `test_register_action_cannot_downgrade_red` es idéntico (ver §1.3). |
| CA-26 | Los overrides son únicamente `{clave_interna: "green"\|"yellow"\|"red"}` — ninguna estructura nueva admite texto libre, tokens ni paths. |
| CA-27 | Nueva sección en `.claude/rules/security-levels.md`, mismo patrón que "REQ-005 — deny-list Rojo aplicada en código" — contenido especificado en §7. |
| CA-28 | Ya reflejado en el banner de este documento y en el handoff final: siguiente paso es `@orion-security`, no `@orion-dev`. |

---

## 1. Núcleo de seguridad — `core/security_manager.py`

### 1.1 Ranking explícito (CA-01) — dict aparte, NO `IntEnum`

**Decisión y por qué NO `IntEnum`:** convertir `RiskLevel` a `IntEnum` cambiaría
`RiskLevel.GREEN.value` de `"green"` (string) a un entero. Verificado con evidencia
concreta que esto rompería un contrato ya en producción:
`ui/webview/frontend/js/composer.js:110` construye una clase CSS con
`` `chip-risk-${chip.risk_level}` `` a partir del JSON que emite
`ui/webview/bridge.py::_build_chips_payload()` (`entry["risk_level"] = level.value`) — esa
clase hoy es literalmente `chip-risk-green`/`chip-risk-yellow`/`chip-risk-red`. Con
`IntEnum` pasaría a ser `chip-risk-0`/`chip-risk-1`/`chip-risk-2`, rompiendo el chip de
riesgo del composer sin ningún CA de esta SPEC que lo pida arreglar.

Por eso, `RiskLevel` **no se toca** (sigue siendo `Enum` plano, líneas 14-17 intactas) y
se agrega, a nivel de módulo, un dict de orden separado:

```python
# core/security_manager.py — agregar cerca de RiskLevel/CHANNEL_ALLOWED_LEVELS
_RISK_LEVEL_ORDER: Dict[RiskLevel, int] = {
    RiskLevel.GREEN: 0,
    RiskLevel.YELLOW: 1,
    RiskLevel.RED: 2,
}
```

### 1.2 Distinción nivel-base vs. nivel-efectivo

`SecurityManager.__new__` agrega un segundo dict junto a `self._actions` (línea 115):

```python
cls._instance._actions: Dict[str, RiskLevel] = {}        # YA EXISTE — pasa a ser el nivel EFECTIVO
cls._instance._base_levels: Dict[str, RiskLevel] = {}     # NUEVO — nivel puro de código
cls._instance._config_overrides: Dict[str, RiskLevel] = _load_and_parse_overrides()  # NUEVO
```

`_load_and_parse_overrides()` (función privada de módulo, no método) importa
`core.security_config.load_security_overrides()` de forma perezosa (mismo estilo que el
resto del archivo, ej. `from core.confirmation import get_confirmation_adapter` dentro de
`require_confirmation()`) y convierte cada valor string a `RiskLevel` vía
`RiskLevel(value)` (el constructor por valor de `Enum` funciona porque los valores del
override (`"green"/"yellow"/"red"`) son textualmente los mismos que `RiskLevel.value`):

```python
def _load_and_parse_overrides() -> Dict[str, "RiskLevel"]:
    from core.security_config import load_security_overrides
    raw = load_security_overrides()   # ya viene limpio: solo entradas green/yellow/red válidas
    result: Dict[str, RiskLevel] = {}
    for name, value in raw.items():
        try:
            result[name] = RiskLevel(value)
        except ValueError:
            logger.warning(f"Nivel inválido en override de '{name}': {value!r} — ignorado")
    return result
```

Se llama **una sola vez por proceso**, dentro de `__new__` del singleton — esto es
justamente lo que resuelve el problema de timing (ver §1.4).

### 1.3 `register_action()` — extendido, mismo contrato público (CA-02, CA-03, CA-25)

No se crea una función nueva de nombre distinto: se **extiende el cuerpo** de
`register_action()` para que (a) siga protegiendo RED exactamente igual que hoy pero
operando sobre `_base_levels`, y (b) además calcule y guarde el nivel efectivo vía el
merge. Firma y tipo de retorno sin cambios:

```python
def register_action(self, name: str, level: RiskLevel) -> bool:
    """Registra la clasificación de código de una acción y recalcula su nivel efectivo
    (código + override de config, CA-02/CA-03). Rechaza (retorna False) cualquier intento
    de degradar el nivel BASE de una acción ya registrada como RED — comportamiento
    idéntico al de REQ-005, ahora aplicado sobre el nivel de código, no sobre el
    efectivo."""
    current_base = self._base_levels.get(name)
    if current_base == RiskLevel.RED and level != RiskLevel.RED:
        logger.critical(f"Intento de reclasificar acción ROJO '{name}' a '{level.value}' bloqueado")
        self._log_audit(name, ChannelType.UNKNOWN, "reclasificacion_bloqueada",
                         details=f"nivel_solicitado={level.value}")
        return False
    self._base_levels[name] = level
    self._actions[name] = self._merge_with_override(name, level)
    return True

def _merge_with_override(self, name: str, base_level: RiskLevel) -> RiskLevel:
    """CA-02/CA-03 — nivel efectivo = max(base, override), nunca min. Un override que
    intente bajar el nivel se ignora EN EFECTO pero queda auditado (CA-04)."""
    override = self._config_overrides.get(name)
    if override is None:
        return base_level
    if _RISK_LEVEL_ORDER[override] < _RISK_LEVEL_ORDER[base_level]:
        logger.warning(
            f"Override de config para '{name}' ({override.value}) intenta bajar el nivel "
            f"de código ({base_level.value}) — ignorado, se mantiene {base_level.value}"
        )
        self._log_audit(name, ChannelType.UNKNOWN, "override_bajada_ignorada",
                         details=f"nivel_codigo={base_level.value}, nivel_config_ignorado={override.value}")
        return base_level
    return override

def classify_action_base(self, name: str) -> Optional[RiskLevel]:
    """Nivel puro de código, sin overrides — para que la UI pueda mostrar 'nivel base'
    vs 'nivel efectivo' si hace falta (SPEC-019, sección núcleo de seguridad)."""
    return self._base_levels.get(name)

def log_override_attempt(self, name: str, requested_level: RiskLevel,
                          current_level: RiskLevel, accepted: bool) -> None:
    """CA-04/CA-21 — auditoría de un intento de GUARDADO desde el bridge (distinto de
    `_merge_with_override()`, que audita al aplicar overrides ya persistidos en el
    arranque). Público porque `ui/webview/bridge.py` es quien conoce el intento crudo,
    antes de que exista un próximo arranque que lo mergee."""
    result = "override_guardado" if accepted else "override_guardado_rechazado_bajada"
    self._log_audit(name, ChannelType.DESKTOP, result,
                     details=f"nivel_actual={current_level.value}, nivel_solicitado={requested_level.value}")
```

**Por qué esto satisface CA-25 sin modificar el comportamiento observable:**
`classify_action("format_disk")` sigue devolviendo `RiskLevel.RED` (porque `_actions` es
el efectivo, y RED sin override sigue siendo RED); `register_action("format_disk", GREEN)`
sigue evaluando `current_base == RED` → `True` → sigue devolviendo `False` sin tocar
nada. `test_register_action_cannot_downgrade_red` (línea 116-120) pasa sin ninguna
modificación de su propio código.

**Por qué NO se reutiliza `register_action()` "tal cual" para aplicar el override** (tal
como pide la SPEC explícitamente): la aplicación del override NUNCA pasa por una llamada
recursiva a `register_action(name, override_level)` — eso sería exactamente el bug que
señaló `orion-spec` (un override YELLOW→GREEN se aplicaría sin resistencia, porque la
protección original solo mira RED). En cambio, `_merge_with_override()` es un método
interno nuevo, con su propia comparación de rank para los 3 niveles, invocado desde
DENTRO de `register_action()` — nunca expuesto como un segundo punto de entrada público
que alguien pueda llamar salteándose la protección de RED.

`require_confirmation()` y `classify_action()` **no se tocan en absoluto** — ya leen
`self._actions`, que ahora contiene el nivel efectivo por construcción. Esto es
deliberado: minimiza el área de cambio en el punto central de decisión (líneas 211-294).

### 1.4 Punto exacto donde se resuelve el problema de timing (3+ momentos de registro)

Baseline confirmó que además de los 3 registros de `core/security_manager.py` (líneas
385-387), `agents/tool_registry.py::register_tool()` (línea 73) también llama
`security_manager.register_action(spec.name, spec.risk_level)` — para `task_create`,
`task_list`, `task_complete` (líneas 152-190 de ese archivo) y, indirectamente, para cada
intent de skill vía `agents/skill_tools.py::register_skill_tools()` (llamado desde
`main.py:65`).

Como el merge vive **dentro de `register_action()`**, y **todo** camino de registro del
sistema (los 3 de `security_manager.py` + el de `tool_registry.py`, sin excepción) pasa
por esa misma función, el merge se aplica automáticamente a los 4 momentos sin tocar
`agents/tool_registry.py`, `agents/skill_tools.py` ni `main.py` — confirmando la
previsión de baseline de que "no se tocan salvo que orion-architect determine
explícitamente que hace falta". No hace falta: el punto de entrada único ya existente
(`register_action()`) es también el punto de aplicación único del merge, sin importar en
qué módulo ni en qué momento del arranque se invoque. Esto es preferible a "aplicar el
override una sola vez al final de `security_manager.py`" (la alternativa que
`orion-spec` había puesto sobre la mesa): esa alternativa sí dependía del orden de
importación entre módulos; esta no depende de orden en absoluto.

`_config_overrides` se carga una única vez por proceso (constructor del singleton), así
que el efecto es "aplica en cada arranque, a todo lo que se registre en ese proceso" —
exactamente el comportamiento de CA-10 (requiere reiniciar para tomar efecto).

---

## 2. Persistencia — `core/security_config.py` (módulo nuevo)

```python
"""
core/security_config.py
Persistencia de los overrides de seguridad que el usuario sube desde la pantalla
"Configuración" (REQ-019). Archivo propio (`security_overrides.json`, sibling de
`config.json`/`audit.db` — mismo patrón de ruta que AUDIT_DB en
core/security_manager.py:72), deliberadamente SEPARADO de config_manager.py.

Ver arquitectura-019.md, sección "Desvío documentado de un ASUMIDO", para el porqué:
aísla el radio de impacto de una corrupción de archivo en ambas direcciones, y permite
escritura atómica exactamente donde la integridad importa más (fallback ante archivo
inválido = SIEMPRE "sin overrides" = nivel de código, nunca "sin restricciones").
"""
import json
import logging
import os
import tempfile
from typing import Dict

logger = logging.getLogger(__name__)

SECURITY_OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), "..", "security_overrides.json")
_VALID_LEVEL_VALUES = {"green", "yellow", "red"}


def load_security_overrides() -> Dict[str, str]:
    """Devuelve {clave_interna: nivel_str}. Nunca crashea, nunca interpreta un archivo
    inválido como 'sin restricciones' — el peor caso posible es dict vacío (CA-06)."""
    if not os.path.exists(SECURITY_OVERRIDES_FILE):
        return {}
    try:
        with open(SECURITY_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"security_overrides.json corrupto/ilegible — se ignora por "
                        f"completo, fallback a nivel de código: {e}")
        return {}
    if not isinstance(raw, dict):
        logger.warning("security_overrides.json no es un objeto JSON — se ignora")
        return {}

    result: Dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or value not in _VALID_LEVEL_VALUES:
            logger.warning(f"Entrada inválida en security_overrides.json ignorada: {key!r}={value!r}")
            continue
        result[key] = value
    return result


def save_security_overrides(overrides: Dict[str, str]) -> None:
    """Persiste TODAS las entradas de `overrides` (clave_interna → nivel) en UNA sola
    escritura atómica — deliberado: una fila de negocio puede cubrir 2 claves internas
    (ej. open_app + OPEN_APP) y deben quedar sincronizadas en un único swap de archivo,
    nunca en N operaciones separadas que dejarían una ventana de estado a medias si el
    proceso muere entre la primera y la segunda (CA-11)."""
    current = load_security_overrides()
    current.update(overrides)
    _atomic_write(current)


def _atomic_write(data: Dict[str, str]) -> None:
    directory = os.path.dirname(os.path.abspath(SECURITY_OVERRIDES_FILE)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".security_overrides_", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, SECURITY_OVERRIDES_FILE)  # atómico en Windows (MoveFileEx) y POSIX
    except IOError as e:
        logger.error(f"No se pudo guardar security_overrides.json: {e}")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
```

`os.replace()` es atómico tanto en POSIX como en Windows (usa `MoveFileEx` con
`MOVEFILE_REPLACE_EXISTING`) — verificado, es el mecanismo estándar de Python para esto
y funciona en el entorno de este proyecto (Windows 11).

---

## 3. Bridge nuevo — `ui/webview/bridge.py`

### 3.1 Catálogo de la categoría v1 (nuevo, mismo patrón que `_CHIPS`)

Vive en `bridge.py` (no en `security_manager.py`) porque es contenido de presentación
—labels en español, agrupación de negocio— igual que `_CHIPS` (líneas 58-65), no lógica
de seguridad. `security_manager.py` se mantiene "puro" (mecanismo, no producto).

```python
_SECURITY_ROWS_V1: List[Dict[str, Any]] = [
    {"id": "open_app", "label": "Abrir aplicaciones",
     "description": "Abrir cualquier aplicación reconocida por su nombre.",
     "keys": ["open_app", "OPEN_APP"]},          # CA-mapeo: misma fila, 2 claves internas
    {"id": "open_chrome", "label": "Abrir Chrome",
     "description": "Abrir el navegador Google Chrome.", "keys": ["open_chrome"]},
    {"id": "open_notepad", "label": "Abrir Bloc de notas",
     "description": "Abrir el Bloc de notas de Windows.", "keys": ["open_notepad"]},
    {"id": "open_explorer", "label": "Abrir Explorador de archivos",
     "description": "Abrir el explorador de archivos de Windows.", "keys": ["open_explorer"]},
    {"id": "open_calculator", "label": "Abrir Calculadora",
     "description": "Abrir la calculadora de Windows.", "keys": ["open_calculator"]},
    {"id": "open_browser", "label": "Abrir navegador",
     "description": "Abrir el navegador predeterminado.", "keys": ["open_browser"]},
    {"id": "open_spotify", "label": "Abrir Spotify",
     "description": "Abrir la aplicación de Spotify.", "keys": ["open_spotify"]},
    {"id": "open_url", "label": "Abrir una URL", 
     "description": "Abrir una dirección web específica.", "keys": ["open_url"]},
]
_SECURITY_ROW_BY_ID: Dict[str, Dict[str, Any]] = {row["id"]: row for row in _SECURITY_ROWS_V1}
_LEVEL_ORDER = ["green", "yellow", "red"]  # espejo local del ranking de security_manager, en string
```

8 filas cubren las 9 claves confirmadas por baseline (`open_app` + `OPEN_APP` colapsadas
en la fila `open_app`, el resto 1:1) — coincide exactamente con el ASUMIDO de SPEC-019.

### 3.2 Señales nuevas

```python
security_overrides_loaded = pyqtSignal(str)       # json: [{row_id, label, description, effective_level, base_level, options}]
security_override_saved = pyqtSignal(str, str)     # row_id, nuevo_nivel — CA-10
security_override_save_rejected = pyqtSignal(str)  # row_id — CA-21
```

### 3.3 Slots nuevos

```python
@pyqtSlot()
def request_security_overrides(self) -> None:
    """CA-19 — carga perezosa: se llama solo al abrir la sección 'Seguridad' de la
    pantalla de Configuración, nunca desde request_initial_state()."""
    self.security_overrides_loaded.emit(json.dumps(_build_security_overrides_payload()))

@pyqtSlot(str, str)
def save_security_override(self, row_id: str, level: str) -> None:
    """CA-21 — defensa en profundidad: revalida rank server-side sin importar qué
    opciones ofreció el <select> de JS."""
    run_async(self._save_security_override_flow,
              lambda: self.security_override_saved.emit(row_id, level),
              self._on_security_override_error, row_id, level)
```

`_save_security_override_flow()` (privado, corre en el thread pool vía `run_async` —
mismo patrón que `_create_task_flow`/`_delete_conversation_flow`):

```python
def _save_security_override_flow(self, row_id: str, level: str) -> None:
    from core.security_manager import RiskLevel, security_manager
    from core.security_config import save_security_overrides

    row = _SECURITY_ROW_BY_ID.get(row_id)
    if row is None:
        logger.warning(f"save_security_override(): row_id desconocido: {row_id!r} — ignorado")
        raise ValueError("row_id desconocido")   # corta el callback de éxito (ver nota abajo)

    try:
        requested = RiskLevel(level)
    except ValueError:
        logger.warning(f"save_security_override(): nivel inválido: {level!r} — ignorado")
        raise

    accepted_keys = []
    all_ok = True
    for key in row["keys"]:
        current = security_manager.classify_action(key)
        if current is None:
            logger.warning(f"save_security_override(): clave '{key}' sin clasificar (CA-05) — se rechaza la fila")
            all_ok = False
            continue
        can_apply = _RISK_LEVEL_ORDER_LOCAL[requested] >= _RISK_LEVEL_ORDER_LOCAL[current]
        security_manager.log_override_attempt(key, requested, current, accepted=can_apply)
        if can_apply:
            accepted_keys.append(key)
        else:
            all_ok = False

    if not all_ok or not accepted_keys:
        # CA-21: todo o nada por fila — evita que open_app suba y OPEN_APP se quede
        # atrás si una de las dos claves fuera rechazada.
        raise PermissionError("nivel rechazado o fila incompleta")

    save_security_overrides({key: requested.value for key in accepted_keys})

def _on_security_override_error(self, message: str) -> None:
    # Cubre los 3 casos de raise de arriba (row_id inválido, nivel inválido, rechazo) —
    # un único camino de error hacia la señal "rejected".
    logger.warning(f"save_security_override() no aplicado: {message}")
```

Nota de implementación para `orion-dev`: `run_async(fn, on_success, on_error, ...)` en
este módulo pasa el valor de retorno de `fn` a `on_success` — como
`_save_security_override_flow()` no devuelve nada útil, `on_success` es un lambda que
ignora el argumento y emite `security_override_saved(row_id, level)`; cualquier
excepción levantada dentro de `_save_security_override_flow()` (row_id inválido, nivel
inválido, o el `PermissionError` de "todo o nada") debe enrutarse al callback de error, y
éste debe emitir `security_override_save_rejected(row_id)` — confirmar el mecanismo
exacto de `run_async()`/`ui/gui_workers.py` para no asumir la forma del mensaje de error.

### 3.4 `_build_security_overrides_payload()`

```python
def _build_security_overrides_payload() -> List[Dict[str, Any]]:
    from core.security_manager import security_manager

    result = []
    for row in _SECURITY_ROWS_V1:
        effective_levels = [security_manager.classify_action(k) for k in row["keys"]]
        if any(level is None for level in effective_levels):
            logger.warning(f"Fila de seguridad '{row['id']}' tiene una clave sin clasificar — omitida (CA-05)")
            continue
        # Defensivo: si por algún motivo las claves de una misma fila quedaran
        # desalineadas, se muestra la más conservadora (mínimo), nunca la más permisiva.
        effective = min(effective_levels, key=lambda l: _LEVEL_ORDER.index(l.value))
        base_levels = [security_manager.classify_action_base(k) for k in row["keys"] if security_manager.classify_action_base(k)]
        base = min(base_levels, key=lambda l: _LEVEL_ORDER.index(l.value)) if base_levels else effective
        current_idx = _LEVEL_ORDER.index(effective.value)
        result.append({
            "row_id": row["id"], "label": row["label"], "description": row["description"],
            "effective_level": effective.value,
            "base_level": base.value,
            "options": _LEVEL_ORDER[current_idx:],   # CA-16: nunca un nivel inferior al vigente
        })
    return result
```

### 3.5 Docstring del módulo (CA-20)

Extender el bloque de líneas 1-33 agregando, en el mismo estilo de la lista existente:

> ...y (REQ-019) 2 funciones de `core/security_manager.py`
> (`classify_action`/`classify_action_base`, ya existentes/nuevas) + 2 funciones de
> `core/security_config.py` (`load_security_overrides`, `save_security_overrides`) para
> los slots `request_security_overrides()`/`save_security_override()`. Ningún slot nuevo
> permite bajar el nivel efectivo de una acción — la validación vive en
> `security_manager` (rank) y se repite server-side en el propio slot, nunca confiando en
> las opciones que ofreció el `<select>` de JS (CA-21).

---

## 4. Frontend nuevo — pantalla "Configuración"

### 4.1 Punto de entrada (CA-12) — patrón confirmado por baseline, no el asumido original

`index.html` (junto a `tasks-btn`/`projects-btn`, líneas 55-62):
```html
<button type="button" id="settings-btn" class="sidebar-action-btn" title="Configuración">
  <span class="icon" aria-hidden="true">&#9881;</span>
  <span class="label">Configuración</span>
</button>
```

`app.js` — el wiring va acá, **no en `sidebar.js`** (baseline corrigió esta asunción con
evidencia: `tasks-btn`/`projects-btn` se cablean en `app.js:106-107`, un grep directo
sobre `sidebar.js` no encontró nada):
```js
import { openSettingsPanel, renderSecurityOverrides } from "./settings_panel.js";
// ...
document.getElementById("settings-btn").addEventListener("click", openSettingsPanel);
onSecurityOverridesLoaded((json) => renderSecurityOverrides(JSON.parse(json)));
onSecurityOverrideSaved((rowId, level) => handleSecurityOverrideSaved(rowId, level));
onSecurityOverrideSaveRejected((rowId) => handleSecurityOverrideRejected(rowId));
```

`bridge_client.js` — mismo patrón delgado que el resto del archivo:
```js
export function requestSecurityOverrides() { _bridge.request_security_overrides(); }
export function saveSecurityOverride(rowId, level) { _bridge.save_security_override(rowId, level); }
export function onSecurityOverridesLoaded(cb) { _bridge.security_overrides_loaded.connect(cb); }
export function onSecurityOverrideSaved(cb) { _bridge.security_override_saved.connect(cb); }
export function onSecurityOverrideSaveRejected(cb) { _bridge.security_override_save_rejected.connect(cb); }
```

### 4.2 `ui/webview/frontend/js/settings_panel.js` (nuevo)

Mismo esqueleto que `tasks_panel.js` (`_panelOpen` guard, `renderShell()` sobre
`#panel-modal-root`, `replaceChildren()`), con dos diferencias estructurales:

1. **Layout de 2 columnas** (nav lateral + contenido), no lista simple — nuevo
   `.settings-layout` con `.settings-nav` (lista de secciones — solo "Seguridad" activa
   en v1, el resto de la estructura queda lista para futuras secciones sin rediseño) y
   `.settings-content` (tarjeta con las filas).
2. **Modelo "aplicar al elegir", sin botón de guardado separado** (decisión de diseño
   que resuelve CA-18 por construcción): cada fila es un `<select>` que al disparar
   `change` llama `saveSecurityOverride(rowId, value)` de inmediato. No existe un estado
   intermedio "elegido pero no guardado" que cerrar el modal pueda descartar — la SPEC
   pide explícitamente que "cerrar sin guardar no aplica cambios pendientes"; con este
   modelo no hay cambios pendientes posibles, cada cambio YA se envió en el momento en
   que ocurrió. Es más simple que un modelo de borrador+confirmar y evita inventar un
   segundo mecanismo de "descartar" que ningún otro panel del proyecto tiene.

```js
import { requestSecurityOverrides, saveSecurityOverride } from "./bridge_client.js";

let _panelOpen = false;
let _pendingRowId = null;   // guard contra doble click en la MISMA fila (caso borde SPEC-019)

export function openSettingsPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  renderShell();
  requestSecurityOverrides();   // CA-19: carga perezosa
}

export function closeSettingsPanel() {
  _panelOpen = false;
  _pendingRowId = null;
  document.getElementById("panel-modal-root").replaceChildren();
}

function renderShell() {
  // overlay + modal-box (clase nueva modal-box-settings) + .settings-nav (li "Seguridad",
  // activa) + .settings-content vacío con id="security-section-list" hasta que llegue
  // el payload — mismo patrón de header/close que tasks_panel.js.
}

export function renderSecurityOverrides(rows) {
  const list = document.getElementById("security-section-list");
  if (!list) return;   // panel ya cerrado antes de que llegara la respuesta
  list.replaceChildren();
  for (const row of rows) list.appendChild(buildSecurityRow(row));
}

function buildSecurityRow(row) {
  const item = document.createElement("div");
  item.className = "settings-row";
  item.dataset.rowId = row.row_id;

  const info = document.createElement("div");
  info.className = "settings-row-info";
  const labelEl = document.createElement("span");
  labelEl.className = "settings-row-label";
  labelEl.textContent = row.label;              // §10.1 — nunca innerHTML
  const descEl = document.createElement("span");
  descEl.className = "settings-row-desc";
  descEl.textContent = row.description;
  info.append(labelEl, descEl);

  const select = document.createElement("select");
  select.className = "settings-row-select";
  select.setAttribute("aria-label", `Nivel de confirmación para ${row.label}`);
  for (const opt of row.options) {               // CA-16: solo lo que Python ofrece
    const optionEl = document.createElement("option");
    optionEl.value = opt;
    optionEl.textContent = LEVEL_LABELS[opt] || opt;   // "Sin confirmar"/"Pide confirmación"/"Bloqueado"
    optionEl.selected = opt === row.effective_level;
    select.appendChild(optionEl);
  }
  select.addEventListener("change", () => {
    if (_pendingRowId === row.row_id) return;   // guard doble-click/doble-evento
    _pendingRowId = row.row_id;
    select.disabled = true;
    saveSecurityOverride(row.row_id, select.value);
  });

  item.append(info, select);
  return item;
}

export function handleSecurityOverrideSaved(rowId, level) {
  _pendingRowId = null;
  const row = document.querySelector(`.settings-row[data-row-id="${rowId}"]`);
  if (row) row.querySelector("select").disabled = false;
  showSettingsBanner("Cambio guardado. Se aplicará la próxima vez que abras la app.");   // CA-10
}

export function handleSecurityOverrideRejected(rowId) {
  _pendingRowId = null;
  requestSecurityOverrides();   // re-sincroniza TODA la sección con la verdad del backend
  showSettingsBanner("No se pudo aplicar ese cambio.", /* isError */ true);
}
```

(`showSettingsBanner()` es un helper trivial nuevo, banner de texto en la parte superior
del `.settings-content` — mismo criterio visual que cualquier mensaje de estado ya
existente en el proyecto; el detalle exacto de estilos queda a criterio de `orion-dev`.)

### 4.3 CSS nuevo — `css/settings_panel.css`

Archivo nuevo (no extiende `panels.css`) porque el layout es estructuralmente distinto:
`panels.css` es para listas de una columna (Tareas/Proyectos), esta pantalla es
nav-lateral + tarjetas (2 columnas), que es un patrón visual distinto que mezclarlo
en el mismo archivo. Reutiliza `.modal-overlay`/`.modal-box` de `modal.css` como raíz
(agrega variante `.modal-box-settings`, análoga a `.modal-box-wide` ya existente en
`panels.css`), montado sobre `#panel-modal-root` (nunca `#confirm-modal-root`, mismo
criterio §0.3 de `arquitectura-016.md`). Debe respetar el theme claro/oscuro existente
(variables `--text-primary`, `--border`, `--bg-input`, etc. ya usadas en `panels.css`) y
el contraste WCAG AA ya validado (CA-30 de SPEC-016) — sin inventar paleta nueva.

Agregar el `<link>` correspondiente en `index.html` junto a los demás CSS (después de
`css/panels.css`).

---

## 5. Reinicio para aplicar cambios (CA-10)

Comunicación al usuario, dos capas:
1. **Inmediata, al guardar:** banner inline en la propia pantalla de Configuración
   (`handleSecurityOverrideSaved()`, §4.2) — "Cambio guardado. Se aplicará la próxima vez
   que abras la app." Aparece apenas se confirma la escritura atómica en disco, no antes.
2. No se agrega un botón de "reiniciar ahora" en v1 — no fue pedido por ningún CA y
   agregaría superficie de riesgo/alcance no aprobado (reiniciar el proceso Qt desde JS).
   Si Johan lo quiere, es alcance adicional para un REQ futuro.

---

## 6. Inserción segura en el DOM (CA-17)

Mismo criterio ya establecido en `arquitectura-015.md §10.1` y extendido por
`arquitectura-016.md §10`: todo texto que llega del bridge (`label`, `description`,
`effective_level`/`base_level`, nombres de opción) se inserta vía `textContent` o
`setAttribute`, nunca `innerHTML`/`insertAdjacentHTML`. Aplica a `settings_panel.js`
completo (ver pseudocódigo §4.2 — cero usos de `innerHTML`).

Extensión de `tests/test_webview_safe_dom_insertion.py`:
```python
_MUST_NOT_USE_INNERHTML = [
    "sidebar.js", "composer.js", "confirm_modal.js", "tasks_panel.js", "projects_panel.js",
    "settings_panel.js",   # REQ-019
]
```
(El test `test_ningun_otro_archivo_js_del_frontend_usa_innerhtml()`, línea 70, ya
itera con un glob sobre TODO `js/*.js` — cubre `settings_panel.js` automáticamente sin
tocarlo, pero agregarlo a la lista explícita de arriba habilita también el contraste
positivo `test_archivo_usa_textcontent_para_insertar_texto()`.)

---

## 7. Contenido a agregar en `.claude/rules/security-levels.md` (CA-27)

Nueva sección, mismo formato que "REQ-005 — deny-list Rojo aplicada en código":

> ## REQ-019 — override de configuración de usuario (solo subir, nunca bajar)
> Desde REQ-019, el usuario puede subir (nunca bajar) el nivel de confirmación de una
> categoría acotada de acciones (v1: apertura de aplicaciones y navegación) desde la
> pantalla "Configuración" del webview de escritorio. El nivel efectivo de cualquier
> acción es siempre `max(nivel_código, nivel_config)` — nunca `min` —, calculado en
> `core/security_manager.py::SecurityManager._merge_with_override()` cada vez que se
> registra una acción (`register_action()`), sin importar en qué de los 4 puntos de
> registro del sistema ocurra. El override se persiste en `security_overrides.json`
> (`core/security_config.py`), archivo separado de `config.json` para que una
> corrupción de configuración general nunca borre ni afecte la configuración de
> seguridad, ni viceversa. Un archivo de overrides ausente, corrupto, o con una clave/
> valor inválido se trata SIEMPRE como "sin overrides" (nivel de código puro) — nunca
> como "sin restricciones". El cambio requiere reiniciar la app para tomar efecto
> (no hay aplicación en caliente en v1). Las acciones sin clasificar y las 10 acciones
> 🔴 Rojo de REQ-005 quedan completamente fuera de este mecanismo.

---

## Módulos a modificar / crear

- `core/security_manager.py` — `_RISK_LEVEL_ORDER`, `_base_levels`, `_config_overrides`,
  `_load_and_parse_overrides()`, `register_action()` extendido, `_merge_with_override()`,
  `classify_action_base()`, `log_override_attempt()`. `classify_action()` y
  `require_confirmation()` sin cambios de código.
- `core/security_config.py` (**nuevo**) — `load_security_overrides()`,
  `save_security_overrides()`, `_atomic_write()`.
- `ui/webview/bridge.py` — `_SECURITY_ROWS_V1`, `_SECURITY_ROW_BY_ID`, 2 slots nuevos, 3
  señales nuevas, `_build_security_overrides_payload()`, `_save_security_override_flow()`,
  docstring extendido.
- `ui/webview/frontend/index.html` — botón `#settings-btn`, `<link>` a
  `css/settings_panel.css`.
- `ui/webview/frontend/js/app.js` — import + `addEventListener` + wiring de 3 señales.
- `ui/webview/frontend/js/bridge_client.js` — 2 wrappers JS→Python, 3 wrappers Python→JS.
- `ui/webview/frontend/js/settings_panel.js` (**nuevo**).
- `ui/webview/frontend/css/settings_panel.css` (**nuevo**).
- `.claude/rules/security-levels.md` — sección nueva (§7 arriba).
- `tests/test_security_manager.py` — tests nuevos (ver "Pruebas sugeridas").
- `tests/test_security_config.py` (**nuevo**).
- `tests/test_webview_bridge.py` — tests nuevos para los 2 slots.
- `tests/test_webview_safe_dom_insertion.py` — agregar `"settings_panel.js"` a la lista.

**No se modifican** (confirmado, ningún hallazgo obliga a tocarlos):
`agents/tool_registry.py`, `agents/skill_tools.py`, `main.py`, `config_manager.py`.

## Dependencias nuevas

Ninguna. `tempfile`/`json`/`os` son de librería estándar, ya usados en el proyecto.

---

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| `RiskLevel` sin orden nativo | `_RISK_LEVEL_ORDER` dict explícito — se descarta `IntEnum` por evidencia concreta de que rompería `composer.js:110` (clase CSS `chip-risk-${value}`). |
| `register_action()` original solo protegía RED | `_merge_with_override()` compara rank para los 3 niveles, invocado desde dentro de `register_action()` — nunca se llama recursivamente con el nivel de config como si fuera un registro de código nuevo. |
| Registro de acciones en 4 momentos/módulos distintos | El merge vive dentro de `register_action()`, el único punto por el que pasan los 4 — cero dependencia de orden de import, cero cambios en `tool_registry.py`/`skill_tools.py`/`main.py`. |
| `config.json` "todo o nada" ante corrupción (riesgo de baseline) | Archivo separado `security_overrides.json`, nunca comparte blast radius con `config.json`. |
| `save_config()` sin escritura atómica (riesgo de baseline) | `core/security_config.py::_atomic_write()` usa `os.replace()` (write-temp-then-rename), aplicado solo donde la integridad es crítica — sin retrofit-ear todo `config_manager.py` (fuera de alcance). |
| Escritura multi-clave de una misma fila de negocio en operaciones de archivo separadas dejando estado a medias | `save_security_overrides()` recibe TODAS las claves de la fila y las persiste en una única escritura atómica, nunca N escrituras secuenciales. |
| Un script en DevTools invoca `save_security_override()` directo, sin pasar por el `<select>` | Revalidación server-side completa en `_save_security_override_flow()` — el rank se recalcula ahí, no se confía en lo que ofreció el frontend (CA-21). |
| Override huérfano (apunta a una clave que ya no existe en código) | Nunca se aplica (el merge solo corre cuando ESA clave se registra); no rompe el arranque; queda en `_config_overrides` sin efecto. Diagnóstico best-effort: se puede loguear en `request_security_overrides()` si `_config_overrides` tiene claves fuera de `_base_levels`, pero no es bloqueante (no lo pide ningún CA explícitamente). |
| Doble click rápido sobre el mismo `<select>` | Guard `_pendingRowId` en `settings_panel.js` + `select.disabled = true` mientras la escritura está en vuelo. |
| Fila desalineada (una clave subió, la otra no, por un estado previo a este REQ) | `_build_security_overrides_payload()` muestra el MÍNIMO (más conservador) entre las claves de la fila, nunca el máximo. |

---

## Pruebas sugeridas (una por CA + estructurales pedidas explícitamente)

### `tests/test_security_manager.py` (extensión)
- CA-01: `_RISK_LEVEL_ORDER[RiskLevel.GREEN] < _RISK_LEVEL_ORDER[RiskLevel.YELLOW] < _RISK_LEVEL_ORDER[RiskLevel.RED]`.
- CA-02 (estructural, YELLOW): registrar una acción de prueba en `register_action("test_yellow_action", RiskLevel.YELLOW)`, inyectar `security_manager._config_overrides["test_yellow_action"] = RiskLevel.GREEN`, volver a llamar `register_action("test_yellow_action", RiskLevel.YELLOW)` (simula el re-registro en el arranque) y verificar `classify_action(...) == RiskLevel.YELLOW` — el override NO bajó nada. `require_confirmation()` sigue pidiendo confirmación (mock del adapter).
- CA-03 (estructural, RED — no solo YELLOW): mismo patrón con una acción RED de verdad (`format_disk`) y un override GREEN inyectado — `classify_action("format_disk")` sigue en `RED`, `require_confirmation()` sigue bloqueando/pidiendo PIN.
- **Estructural adicional pedida explícitamente (RED/YELLOW/GREEN, no solo RED):** parametrizar un test único `test_override_nunca_baja_el_nivel(base, override_attempt)` con las 6 combinaciones donde `override_attempt < base` (GREEN es base sin bajada posible, así que son: YELLOW→GREEN, RED→GREEN, RED→YELLOW) y confirmar que el nivel efectivo resultante es siempre `base`, nunca `override_attempt`, para los 3 niveles de base.
- CA-04: con `isolated_audit_db`, verificar que un intento de bajada (vía `_merge_with_override` o vía `log_override_attempt(accepted=False)`) deja una fila en `audit_log` con `result` conteniendo `"bajada"`/`"rechazad"`.
- CA-06: `security_manager._config_overrides` se calcula a partir de `_load_and_parse_overrides()` — test aparte en `test_security_config.py` para el archivo; acá un test de que un valor de `RiskLevel(value)` inválido nunca entra al dict (ya cubierto indirectamente, pero vale un test explícito de `_load_and_parse_overrides()` con un mock de `load_security_overrides()` devolviendo `{"x": "purple"}`).
- CA-07: parametrizar `require_confirmation()` con los 5 `ChannelType` sobre una acción con override aplicado y confirmar que el nivel efectivo (y por lo tanto el comportamiento) es el mismo en los 5.
- CA-08: `all(row_key not in [r["id"] for r in RED_CATEGORIES-equivalent] ...)` — más simple: test dedicado en `test_webview_bridge.py` (ver abajo) ya que el catálogo vive ahí, no en `security_manager.py`.
- CA-25: `test_register_action_cannot_downgrade_red` existente — no se toca, debe seguir pasando literal.

### `tests/test_security_config.py` (nuevo)
- Archivo inexistente → `load_security_overrides() == {}`.
- Archivo con JSON corrupto (`tmp_path`) → `{}` + no crashea.
- Archivo con valor inválido (`{"open_chrome": "purple"}`) → esa entrada se descarta, resto se conserva.
- Archivo que no es un dict (`[1,2,3]`) → `{}`.
- `save_security_overrides({"a": "yellow", "b": "red"})` seguido de `load_security_overrides()` → ambas claves presentes con el valor correcto.
- Verificar que tras `save_security_overrides()` no queda ningún archivo temporal (`.security_overrides_*`) en el directorio (limpieza correcta del `mkstemp`).
- Simular fallo de escritura (monkeypatch `os.replace` para lanzar `IOError`) → no propaga excepción, loguea error, el archivo original (si existía) queda intacto.

### `tests/test_webview_bridge.py` (extensión)
- CA-05: `save_security_override("open_app", "yellow")` con una clave del catálogo intencionalmente no registrada (mock `classify_action` devolviendo `None` para una de las 2 claves de la fila) → no se persiste nada, se emite `security_override_save_rejected`.
- CA-08: iterar `_SECURITY_ROWS_V1`, ninguna clave interna de ninguna fila coincide con las 10 claves RED de `core/security_manager.py` (`format_disk`, `delete_database`, etc.).
- CA-16: `_build_security_overrides_payload()` — para una fila con `effective_level == "yellow"`, `options == ["yellow", "red"]` (nunca incluye `"green"`).
- CA-21: invocar `save_security_override("open_chrome", "green")` cuando el nivel efectivo actual ya es `"yellow"` (simulando un intento de bajada directo al slot, sin pasar por el `<select>`) → rechazado, `security_override_save_rejected` emitido, `classify_action("open_chrome")` sigue en `"yellow"`.
- Atomicidad de fila: mockear `save_security_overrides` y verificar que se llama exactamente UNA vez con un dict que contiene TODAS las claves de la fila (`open_app` y `OPEN_APP` juntas), nunca en dos llamadas separadas.

### `tests/test_webview_safe_dom_insertion.py` (extensión)
- `settings_panel.js` agregado a `_MUST_NOT_USE_INNERHTML` — cubierto por los 2 tests parametrizados existentes sin escribir código nuevo.

---

## Definition of Done — autochequeo

```
[x] Propuesta referencia cada criterio de la SPEC (tabla de 28 CA)
[x] Módulos, clases y funciones especificados (firmas exactas §1-4)
[x] Flujo de datos documentado (§1.4 timing, §3 bridge, §4 frontend)
[x] Dependencias nuevas identificadas (ninguna)
[x] Riesgos con mitigación documentados (tabla dedicada)
[x] Pruebas sugeridas listadas (una por CA + estructurales RED/YELLOW/GREEN pedidas)
[x] Aprobación humana explícita — recibida (Johan, vía orion-coordinador): desvío de
    persistencia (`security_overrides.json` separado) aprobado, resto tal cual
[x] Contexto actualizado, CSV actualizado (Estado → ARQUITECTURA_APROBADA)
```

---

## 11. Ajustes de seguridad post-auditoría (2026-08-20) — respuesta a `security-audit-019.md`

**Motivo:** `orion-security` auditó esta arquitectura (`pruebas/security-audit-019.md`, veredicto
❌ REQUIERE CAMBIOS) y devolvió 1 hallazgo bloqueante (A) más 2 no bloqueantes (B, C). El diseño
central (merge de 3 niveles, exclusión estructural de RED, defensa en profundidad server-side,
archivo separado) **no se reabre** — la propia auditoría lo confirmó sólido. Esta sección es una
extensión, mismo patrón que el addendum §10 de `arquitectura-015.md`; no se reescribe nada de §1-§10.

Leído completo antes de responder: `pruebas/security-audit-019.md` íntegro (los 3 hallazgos, la
tabla de clasificación de riesgos, y las 5 recomendaciones).

### 11.1 Hallazgo A (bloqueante) — `load_security_overrides()` no cubre `UnicodeDecodeError`

Corrección en `core/security_config.py::load_security_overrides()` (reemplaza el bloque `try/except`
de §2 — el resto de la función, `SECURITY_OVERRIDES_FILE`, `save_security_overrides()` y
`_atomic_write()`, queda sin cambios):

```python
def load_security_overrides() -> Dict[str, str]:
    if not os.path.exists(SECURITY_OVERRIDES_FILE):
        return {}
    try:
        with open(SECURITY_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        # Se adopta `except Exception` amplio (permitido por .claude/rules/python-style.md
        # siempre que se loguee — no es un `except: pass` silencioso) en vez de enumerar
        # tipos: json.JSONDecodeError/OSError NO cubrían UnicodeDecodeError (subclase de
        # ValueError), que es el escenario de corrupción más realista en la práctica —
        # archivo truncado a mitad de escritura, bytes no-UTF-8. `except Exception` no
        # depende de anticipar cada subtipo posible (security-audit-019.md, Hallazgo A).
        logger.warning(
            f"security_overrides.json corrupto/ilegible ({type(e).__name__}) — se ignora "
            f"por completo, fallback a nivel de código: {e}"
        )
        return {}
    if not isinstance(raw, dict):
        logger.warning("security_overrides.json no es un objeto JSON — se ignora")
        return {}
    # ... resto sin cambios (filtrado de claves/valores inválidos, §2)
```

Segunda capa de defensa (recomendación de la auditoría, adoptada por ser de bajo costo dado lo
crítico del punto de construcción del singleton): `core/security_manager.py::_load_and_parse_overrides()`
(§1.2) también envuelve la llamada:

```python
def _load_and_parse_overrides() -> Dict[str, "RiskLevel"]:
    from core.security_config import load_security_overrides
    try:
        raw = load_security_overrides()
    except Exception as e:
        # Defensa en profundidad adicional: si un REQ futuro modifica security_config.py
        # y reintroduce un hueco de excepción no capturada, el punto más caro para fallar
        # de todo el sistema (SecurityManager.__new__, tiempo de import) queda protegido
        # por una segunda capa independiente.
        logger.warning(f"Fallback de emergencia en _load_and_parse_overrides() "
                        f"({type(e).__name__}) — se continúa sin overrides: {e}")
        raw = {}
    result: Dict[str, RiskLevel] = {}
    for name, value in raw.items():
        try:
            result[name] = RiskLevel(value)
        except ValueError:
            logger.warning(f"Nivel inválido en override de '{name}': {value!r} — ignorado")
    return result
```

Con esto, ningún tipo de corrupción de `security_overrides.json` (sintaxis JSON rota, bytes no-UTF-8,
permiso denegado, o cualquier excepción no anticipada) puede propagarse fuera de
`_load_and_parse_overrides()` — el peor caso queda garantizado en "sin overrides" (nivel de código
puro), nunca un crash del import de `core/security_manager.py`.

### 11.2 Hallazgo B (no bloqueante) — fuente única de verdad del ranking en `bridge.py`

Corrección al pseudocódigo de §3.1/§3.3/§3.4: se elimina `_LEVEL_ORDER` (lista de strings mantenida
a mano) y el nombre indefinido `_RISK_LEVEL_ORDER_LOCAL`. `bridge.py` importa y reusa directamente
`core.security_manager._RISK_LEVEL_ORDER` (el mismo dict `RiskLevel → int` de §1.1) como única
fuente de verdad — evita que en un REQ futuro (ej. un nivel intermedio nuevo) una de las dos
representaciones se actualice y la otra no, lo que reabriría en silencio un hueco en CA-21.

```python
# ui/webview/bridge.py — reemplaza la constante _LEVEL_ORDER de §3.1
from core.security_manager import RiskLevel, _RISK_LEVEL_ORDER

# Derivada de _RISK_LEVEL_ORDER, nunca mantenida a mano en paralelo — única lista de
# strings ordenada, usada solo para construir el JSON de `options` hacia JS.
_ORDERED_LEVEL_VALUES: List[str] = [
    level.value for level in sorted(_RISK_LEVEL_ORDER, key=lambda lvl: _RISK_LEVEL_ORDER[lvl])
]
```

- En `_build_security_overrides_payload()` (§3.4): todo `min(..., key=lambda l: _LEVEL_ORDER.index(l.value))`
  pasa a `min(..., key=lambda l: _RISK_LEVEL_ORDER[l])` (compara directo sobre `RiskLevel`, sin pasar
  por string); `_LEVEL_ORDER.index(effective.value)` pasa a `_ORDERED_LEVEL_VALUES.index(effective.value)`
  (mismo resultado, fuente derivada).
- En `_save_security_override_flow()` (§3.3): `_RISK_LEVEL_ORDER_LOCAL[requested] >= _RISK_LEVEL_ORDER_LOCAL[current]`
  pasa a `_RISK_LEVEL_ORDER[requested] >= _RISK_LEVEL_ORDER[current]` — el nombre indefinido
  desaparece, se usa directo el dict importado.

**Nota para `orion-dev`:** esto es un requisito obligatorio de implementación (no opcional), aunque
no bloquea el avance a `orion-dev` en sí — confirmado por `orion-security` que, tal como estaba
escrito el pseudocódigo original, el efecto de no resolverlo es fail-closed (guardado siempre
rechazado por `NameError`), nunca fail-open; aun así, dejarlo sin resolver inutilizaría la función
completa de "subir de nivel" en la práctica.

### 11.3 Hallazgo C (no bloqueante) — techo de `yellow` en el catálogo v1 (decisión: SÍ, se acota)

Se adopta la sugerencia de la auditoría: las 8 filas del catálogo v1 (categoría "apertura de
aplicaciones y navegación", SPEC-019 ASUMIDO) nunca ofrecen `red` como opción. Motivo: el propio
ASUMIDO de la SPEC dice explícitamente que esta categoría se eligió para demostrar "subir de Verde a
Amarillo" — nada pide alcanzar Rojo desde esta pantalla — y permitir el salto directo Verde→Rojo sin
`ORION_AUTH_PIN` configurado produce un auto-bloqueo sin vía de recuperación desde la UI (`has_pin()`
en `False` dentro de `require_confirmation()`, líneas 283-293, deja la acción permanentemente
bloqueada). No es un hallazgo de seguridad (subir nunca es inseguro) — es una decisión de producto
conservadora dentro del margen que la SPEC ya deja a criterio de `orion-architect`/`orion-dev`
("detalle visual exacto... queda a criterio"), no un cambio de alcance que amerite volver a Johan.

Ceiling aplicado en **ambos lados** (no solo en las `options` que arma el payload — también
revalidado server-side en el slot de guardado, mismo criterio CA-21/CA-22 de no confiar únicamente
en lo que ofreció la UI):

```python
# ui/webview/bridge.py — nueva constante junto a _SECURITY_ROWS_V1 (§3.1)
_V1_MAX_OFFERABLE_LEVEL = RiskLevel.YELLOW   # política del catálogo v1, no del core

# Dentro de _build_security_overrides_payload() (§3.4) — reemplaza la línea de `options`:
current_rank = _RISK_LEVEL_ORDER[effective]
ceiling_rank = max(current_rank, _RISK_LEVEL_ORDER[_V1_MAX_OFFERABLE_LEVEL])
options = _ORDERED_LEVEL_VALUES[current_rank:ceiling_rank + 1]
# GREEN → ["green", "yellow"] (nunca "red")
# YELLOW (ya en el techo v1) → ["yellow"] (sin subida disponible en este catálogo)
# Caso borde: si un REQ futuro reclasifica el código base a RED, `max(current_rank, ceiling_rank)`
# nunca recorta por debajo del nivel vigente — CA-16 sigue intacto en cualquier escenario.
```

```python
# Dentro de _save_security_override_flow() (§3.3) — chequeo adicional antes de aplicar:
if row_id in _SECURITY_ROW_BY_ID and _RISK_LEVEL_ORDER[requested] > _RISK_LEVEL_ORDER[_V1_MAX_OFFERABLE_LEVEL]:
    logger.warning(f"save_security_override(): '{level}' excede el techo v1 (yellow) para "
                    f"'{row_id}' — rechazado (política de catálogo, no de core)")
    all_ok = False   # mismo camino de rechazo + auditoría que un intento de bajada (§3.3)
```

Deliberadamente **no** se toca `core/security_manager.py` para esto — el techo es una política del
catálogo v1 en `bridge.py` (dato de producto), no una invariante del núcleo de seguridad; una
categoría futura con acciones YELLOW podría necesitar llegar a RED sin que eso implique reabrir
`_merge_with_override()`.

### 11.4 Riesgos y mitigación (addendum)

| Riesgo | Mitigación |
|--------|-----------|
| `UnicodeDecodeError` no capturado en `load_security_overrides()` podía crashear el arranque completo de O.R.I.O.N. | `except Exception` amplio + segunda capa en `_load_and_parse_overrides()` — ver §11.1. |
| Segunda representación del ranking (`_LEVEL_ORDER` string list) podía desalinearse de `_RISK_LEVEL_ORDER` en un REQ futuro | `bridge.py` importa `_RISK_LEVEL_ORDER` directo de `security_manager`; `_ORDERED_LEVEL_VALUES` se deriva de ese dict, nunca se mantiene a mano en paralelo — ver §11.2. |
| Auto-bloqueo del usuario al subir una acción GREEN directo a RED sin PIN configurado, sin vía de recuperación desde la UI | Techo de `yellow` en el catálogo v1, aplicado en `options` (UI) y revalidado server-side (§11.3) — política de catálogo, no del core. |

### 11.5 Qué NO cambia

- El mecanismo central §1 (`_RISK_LEVEL_ORDER`, `_merge_with_override()` dentro de `register_action()`,
  distinción base/efectivo) — confirmado sólido por la auditoría, cero cambios.
- La decisión de persistencia en archivo separado (§2, ya aprobada por Johan) — solo se amplía el
  `except`, la decisión de arquitectura (archivo propio + escritura atómica) no se reabre.
- El catálogo de 8 filas / 9 claves internas (§3.1) y el mapeo `open_app`+`OPEN_APP` — sin cambios,
  solo se le agrega un techo de opciones.
- El frontend (§4), CA-17/§6, y el contenido de `.claude/rules/security-levels.md` (§7) — sin cambios.

---

## Resumen para el humano — AJUSTES DE SEGURIDAD (§11)

`orion-security` encontró 1 ajuste bloqueante (manejo de excepciones incompleto en la lectura de
`security_overrides.json` — podía crashear el arranque completo de la app, no solo la pantalla de
Configuración) y 2 no bloqueantes (duplicación de la lista de ranking en el bridge; techo de nivel en
el catálogo v1 para evitar auto-bloqueo). Los 3 están resueltos en §11, sin reabrir el diseño central
ni ninguna decisión ya aprobada. Por ser correcciones técnicas de seguridad (no un cambio de alcance
ni de política de producto nueva), esto vuelve directo a `@orion-security` para el re-chequeo — no
requiere pasar de nuevo por vos salvo que prefieras revisarlo igual.
