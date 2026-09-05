"""
tests/modelo_falso.py
Un sustituto de `core/reasoning_loop.py::run()` para las pruebas de resolución.

No es un test: pytest no lo recoge (no empieza por `test_`).

Desde que el modelo lee primero (`core/resolution.py::RESOLVERS`), todo lo que no sea la
respuesta a un diálogo pendiente termina en el bucle de razonamiento. Un test que solo
PROHIBIERA la llamada real moriría en la prohibición y no probaría nada; uno que devolviera
una cadena fija dejaría de ejercitar las herramientas, el gate y el canal, que es
justamente lo que esas pruebas verifican.

Así que acá vive un modelo falso que decide como decidiría el real: reconoce un
recordatorio, una rutina del usuario o una orden del sistema, y llama a la herramienta que
corresponde — la de verdad, con su gate. Lo que no reconoce, lo contesta hablando.

Es deliberadamente simple y determinista. No imita la redacción de un modelo (eso no se
puede probar), imita su DECISIÓN, que es lo único de lo que depende el resto del sistema.
"""

from core.security_manager import security_manager

_RECORDATORIO = ("recuérdame", "recuerdame", "recordarme", "recordatorio", "no olvides")
_LISTAR_TAREAS = ("mis tareas", "tareas pendientes", "listado de tareas")
_COMPLETAR_TODAS = ("completa todas", "completé todas", "complete todas", "ya completé todas",
                    "ya complete todas", "todas las pendientes", "marca todas")
_COMPLETAR_UNA = ("ya completé", "ya complete", "ya hice", "completa la tarea")

RESPUESTA_HABLADA = "respuesta del modelo a: {}"


def _rutina_nombrada(texto: str):
    """El nombre de la rutina del usuario que aparezca en el texto, o `None`."""
    try:
        from learning.routines_engine import _load_routines
    except Exception:
        return None

    for nombre, rutina in _load_routines().items():
        for disparador in rutina.get("triggers", [nombre]):
            if str(disparador).lower() in texto:
                return nombre
    return None


def run(task, channel, user_id="default", agent_name="reasoning_loop", estado=None):
    """Misma firma que `core.reasoning_loop.run()`."""
    from agents.tool_registry import execute_tool, has_explicit_task_id
    from core.security_manager import ActionDenied
    from intent.classifier import classify_command
    from intent.intentions import Intent

    texto = (task or "").lower()
    canal = security_manager.resolve_channel(channel)

    def _tool(nombre, params):
        try:
            return execute_tool(
                nombre, {**params, "channel": canal.value, "user_id": user_id}, canal, user_id,
            )
        except ActionDenied as e:
            # Igual que el bucle real (CA-08): corta, no reintenta, y lo deja anotado.
            if estado is not None:
                estado["denied"] = True
            return f"⛔ No puedo ejecutar esa acción: {e.reason or 'denegada'}."

    if any(p in texto for p in _RECORDATORIO):
        return _tool("task_create", {"text": task})
    # Las ramas de tareas exigen que el texto HABLE de tareas. Sin eso, `#92D050` —un
    # color dentro de un JSON— se leia como "la tarea #92" y el falso llamaba a
    # `task_complete`: exactamente la clase de error que la inversion existe para evitar,
    # cometida por el doble que deberia probarla.
    #
    # La prioridad es la que documentaba el resolver retirado (CA-05/CA-06): un ID
    # explicito gana sobre "todas", y "todas" gana sobre "listar".
    # El ID explicito es el unico que necesita que el texto HABLE de tareas: `#92D050` —un
    # color dentro de un JSON— se leia como "la tarea #92" y el falso llamaba a
    # `task_complete`. Las demas frases ("marca todas como completadas") ya son especificas
    # por si solas, y exigirles la palabra "tarea" romperia justamente lo que prueban.
    if has_explicit_task_id(texto) and any(p in texto for p in ("tarea", "pendiente")):
        return _tool("task_complete", {"text": task})
    if any(p in texto for p in _COMPLETAR_TODAS):
        return _tool("task_complete_all", {"text": task})
    if any(p in texto for p in _LISTAR_TAREAS):
        return _tool("task_list", {})
    if any(p in texto for p in _COMPLETAR_UNA):
        return _tool("task_complete", {"text": task})

    rutina = _rutina_nombrada(texto)
    if rutina:
        return _tool("routine_run", {"name": rutina})

    intent, _ = classify_command(task or "")
    nombre = intent.value if hasattr(intent, "value") else str(intent)
    if nombre != Intent.UNKNOWN.value:
        return _tool("dispatcher", {"task": task})

    return RESPUESTA_HABLADA.format(task)


def instalar(monkeypatch) -> None:
    """Pone el modelo falso en lugar del bucle, y prohíbe la llamada real."""
    def explotar(*a, **k):  # pragma: no cover - salta solo si algo se escapa
        raise AssertionError("un test intentó llamar al LLM real")

    monkeypatch.setattr("ai.llm_provider.generate_response", explotar)
    monkeypatch.setattr("core.reasoning_loop.run", run)


def instalar_sin_proveedor(monkeypatch) -> None:
    """Simula que NINGUN proveedor responde: caida de red, o sin claves configuradas.

    Se sustituye el bucle entero y no solo `generate_response()`, porque el modelo falso ya
    ocupa ese lugar. Lo que se imita es lo que hace el bucle real en esa situacion: devolver
    `SIN_PROVEEDOR` y dejar anotado `sin_modelo` en `estado`, que es la senal con la que
    `core/resolution.py` decide intentar el camino local.
    """
    from ai.llm_provider import SIN_PROVEEDOR

    def _sin_proveedor(task, channel, user_id="default", agent_name="reasoning_loop",
                       estado=None):
        if estado is not None:
            estado["sin_modelo"] = True
        return SIN_PROVEEDOR

    monkeypatch.setattr("core.reasoning_loop.run", _sin_proveedor)


def registrar_tools() -> None:
    """El catálogo que en producción arma `main.py` al arrancar.

    Sin esto, que `dispatcher` exista dependía de qué otro test hubiera corrido antes en la
    sesión, y una orden podía morir con "tool no registrado" según el orden de collection.
    """
    from agents.skill_tools import (register_dispatcher_tool, register_family_tools,
                                    register_skill_tools)
    from agents.user_defined_tools import register_user_defined_tools
    from skills.skill_manager import skill_manager

    register_dispatcher_tool()
    register_skill_tools(skill_manager)
    register_family_tools(skill_manager)
    register_user_defined_tools()
