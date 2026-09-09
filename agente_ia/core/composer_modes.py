"""
core/composer_modes.py
REQ-026 — catálogo único de los 4 "modos estratégicos" del composer (Código/script,
Investigación, Nodos/flujos, Tareas). Vive en `core/` (no en `ui/webview/bridge.py`)
porque lo consumen dos capas distintas sin relación entre sí: `bridge.py` (arma el
payload que ve el frontend) y `core/reasoning_loop.py` (reordena tools y arma el system
prompt) — un único lugar evita mantener el mapeo modo→capacidad duplicado en dos capas
(arquitectura-026.md §"Nuevas clases/funciones").

Cada modo prioriza tools que YA EXISTEN — este módulo no crea ninguna capacidad nueva,
solo nombra cuáles priorizar y, opcionalmente, a qué `tarea` (de `task_providers` en
`config.json`) rutear el turno mientras el modo está activo.

`get_mode()` es fail-safe a propósito (nunca lanza): un `modo_id` desconocido u obsoleto
—p. ej. un frontend cacheado tras cambiar este catálogo— se trata como "sin modo", nunca
como un error que le impida al usuario mandar el mensaje.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ModoComposer:
    """Definición de un modo estratégico del composer.

    `tool_names`: tools que se mueven al frente del catálogo que ve el modelo
    (`core/reasoning_loop.py::_reordenar_priorizando()`) — nunca se filtra el resto.
    `presupuesto` (REQ-027/CA-12): cuantas llamadas al modelo puede gastar un turno
    mientras el modo esta activo. Cuenta LLAMADAS, no herramientas: una vuelta que ejecuta
    cuatro herramientas gasta una sola unidad, porque el costo y la latencia los pone la
    llamada al modelo. La llamada de cierre va aparte, fuera del presupuesto (CA-30).
    Sin default a proposito: un modo nuevo que se olvide de declararlo tiene que explotar
    al importar, no heredar en silencio el presupuesto mas bajo.
    `tarea`: si no es `None`, reemplaza `tarea="razonamiento"` en la llamada a
    `generate_response()` mientras el modo está activo (rutea a `task_providers[tarea]`
    si existe una entrada; si no, se comporta igual que "razonamiento" sin fijar).
    `prompt_hint`: frase que se agrega al final de `_build_system_prompt()`, redactada a
    propósito de forma defensiva — nunca una orden ciega, siempre con la salida de "si no
    aplica, respondé con normalidad".
    """

    id: str
    label: str
    tool_names: Tuple[str, ...]
    presupuesto: int
    tarea: Optional[str]
    prompt_hint: str


# Orden fijo: es el orden en que `ui/webview/bridge.py::_build_modes_payload()` los
# emite y en el que `composer.js::renderModes()` los pinta (arquitectura-026.md, tabla de
# módulos a modificar).
_MODOS: Tuple[ModoComposer, ...] = (
    ModoComposer(
        id="codigo",
        label="Código/script",
        # REQ-029/CA-15 — las 8 herramientas de repositorio van PRIMERO, y `EXECUTE_CODE`
        # queda al final: en este modo lo habitual es trabajar sobre un repo que ya
        # existe (leer, buscar, editar, mirar el git), no generar un script suelto y
        # ejecutarlo. El orden de esta tupla es el orden en que el modelo ve el catálogo
        # (`reasoning_loop._reordenar_priorizando()`), y dentro de ellas también importa:
        # buscar y leer antes que escribir, porque editar sin haber leído es adivinar.
        # `presupuesto=40` (REQ-027) no se toca: editar un repo son ~20 pasos.
        tool_names=(
            # REQ-032 — el orden sigue el de un trabajo real: primero entender la forma del
            # proyecto, despues leer, despues cambiar, y despues COMPROBAR corriendolo.
            # `project_run` va detras de las escrituras porque correr sin haber cambiado
            # nada es gastar una vuelta.
            "project_tree",
            "file_search", "file_read", "file_list", "file_edit", "file_write",
            "project_run",
            "git_status", "git_diff", "git_log", "EXECUTE_CODE",
        ),
        presupuesto=40,
        tarea="modo_codigo",
        prompt_hint=(
            "Modo activo: Código/script. Trabajás sobre repositorios reales: orientate "
            "con 'file_search' y 'file_list', leé con 'file_read' antes de cambiar nada, "
            "cambiá con 'file_edit' (o 'file_write' si el archivo es nuevo) y mirá el "
            "estado del repo con 'git_status', 'git_diff' y 'git_log'. Solo podés tocar "
            "las carpetas que el usuario habilitó: si una ruta se rechaza, decíselo en "
            "vez de insistir por otro camino. Para generar y correr un script suelto está "
            "'EXECUTE_CODE'. Si el pedido no tiene que ver con código, respondé con "
            "normalidad sin forzar esas herramientas."
        ),
    ),
    ModoComposer(
        id="investigacion",
        label="Investigación",
        tool_names=("web_search", "web_read", "wikipedia_search", "BROWSE_WEB"),
        presupuesto=25,
        tarea="modo_investigacion",
        prompt_hint=(
            "Modo activo: Investigación. Priorizá buscar y leer información con "
            "'web_search', 'web_read', 'wikipedia_search' o 'BROWSE_WEB' cuando el "
            "pedido lo amerite. Si el pedido no tiene que ver con investigar algo, "
            "respondé con normalidad sin forzar esas herramientas."
        ),
    ),
    ModoComposer(
        id="flujos",
        label="Nodos/flujos",
        tool_names=("flujo", "CREATE_FLOW"),
        presupuesto=12,
        tarea=None,
        prompt_hint=(
            "Modo activo: Nodos/flujos. Priorizá trabajar con flujos (listar, ejecutar, "
            "reanudar, cancelar con 'flujo'; crear uno nuevo con 'CREATE_FLOW') cuando "
            "el pedido lo amerite. Si el pedido no tiene que ver con flujos, respondé "
            "con normalidad sin forzar esas herramientas."
        ),
    ),
    ModoComposer(
        id="tareas",
        label="Tareas",
        tool_names=("task_create", "task_list", "task_complete", "task_complete_all"),
        presupuesto=10,
        tarea=None,
        prompt_hint=(
            "Modo activo: Tareas. Priorizá crear, listar y completar tareas con "
            "'task_create', 'task_list', 'task_complete' o 'task_complete_all' cuando "
            "el pedido lo amerite. Si el pedido no tiene que ver con tareas, respondé "
            "con normalidad sin forzar esas herramientas."
        ),
    ),
)

_MODOS_POR_ID = {modo.id: modo for modo in _MODOS}


def listar_modos() -> Tuple[ModoComposer, ...]:
    """Return los 4 modos, en el orden fijo que ve la UI."""
    return _MODOS


def get_mode(modo_id: Optional[str]) -> Optional[ModoComposer]:
    """Resuelve `modo_id` → `ModoComposer`, o `None` si está vacío/es desconocido.

    Fail-safe a propósito: nunca lanza. Un id vacío (`""`/`None`) es "sin modo" —el
    camino normal, idéntico al de antes de REQ-026—; un id desconocido (frontend
    cacheado con un catálogo viejo) se trata exactamente igual, nunca como error.
    """
    if not modo_id:
        return None
    return _MODOS_POR_ID.get(modo_id)
