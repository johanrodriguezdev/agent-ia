"""
tests/test_orchestrator.py

Cobertura de `core/orchestrator.py::_decompose()` (REQ-007, CA-12) — fix del bug de
substring (p.ej. "y" matcheando dentro de "hoy") vía `\\b` word boundary + safety net de
longitud mínima por parte.

También cubre CA-17: `AgentOrchestrator` ya no tiene `register_tool()`/`self._tools` tras
la migración a `agents/tool_registry.py` (ver `agents/skill_tools.py`).
"""
from core.orchestrator import AgentOrchestrator


def test_ca12_no_descompone_cuando_el_trigger_es_substring():
    """"y" no debe matchear dentro de "Yolanda" — antes del fix, `"y" in text.lower()`
    partía "me llamo Yolanda" en fragmentos sin sentido."""
    orch = AgentOrchestrator()
    result = orch._decompose("me llamo Yolanda")
    assert result == ["me llamo Yolanda"]


def test_ca12_descompone_con_trigger_como_palabra_completa():
    orch = AgentOrchestrator()
    result = orch._decompose("compra pan y luego café")
    # El trigger "y" está primero en `_DECOMPOSE_TRIGGERS` y ya matchea (\by\b) antes de
    # llegar a "luego" — el split ocurre en el primer trigger que produce un resultado
    # válido, no necesariamente el "más específico".
    assert len(result) == 2
    assert result[0] == "compra pan"
    assert result[1] == "luego café"


def test_ca12_red_de_seguridad_descarta_partes_triviales():
    """"él y tú vamos" matchea `\\by\\b` pero produce partes de 2-3 caracteres — el safety
    net `all(len(p) > 3 for p in parts)` descarta el split y retorna el texto completo."""
    orch = AgentOrchestrator()
    result = orch._decompose("él y tú vamos")
    assert result == ["él y tú vamos"]


def test_ca17_orchestrator_ya_no_tiene_register_tool():
    """CA-17: `register_tool()`/`self._tools` se eliminan de `AgentOrchestrator` — el
    catálogo de tools ahora vive únicamente en `agents/tool_registry.py`."""
    orch = AgentOrchestrator()
    assert not hasattr(orch, "register_tool")
    assert not hasattr(orch, "_tools")


# --------------------------------------------------------------------------- cerebro

def test_el_orquestador_llega_al_modelo_cuando_nadie_registro_un_cerebro(monkeypatch):
    """Bug encontrado en vivo (2026-09-03, log de las 21:48).

    El orquestador se pasaba a sí mismo como `claude_fn`, y como `register_claude_brain()`
    no se llama en ningún lado de la aplicación, toda tarea que llegaba al resolver
    'claude' moría con "No hay agente disponible ni Claude configurado" sin tocar el
    modelo: los disparos proactivos devolvían ese texto en 0.07 segundos, sin red de por
    medio. Ahora, sin cerebro registrado no se inyecta nada y `_try_claude()` usa el bucle
    de razonamiento con el canal real — el mismo camino del chat del escritorio.
    """
    from types import SimpleNamespace

    import core.resolution as resolution_module
    from core.orchestrator import AgentOrchestrator

    capturado = {}

    def _resolve_falso(text, channel, user_id, claude_fn=None):
        capturado["claude_fn"] = claude_fn
        return SimpleNamespace(text="respuesta del modelo", matched_by="claude")

    monkeypatch.setattr(resolution_module, "resolve", _resolve_falso)

    orquestador = AgentOrchestrator()
    resultado = orquestador.process_task("¿necesita algo?", channel="desktop")

    assert capturado["claude_fn"] is None, "sin cerebro registrado no se inyecta nada"
    assert resultado == "respuesta del modelo"
    assert "No hay agente disponible" not in resultado


def test_si_alguien_registra_un_cerebro_el_orquestador_lo_usa(monkeypatch):
    """El punto de inyección sigue existiendo: lo que se arregló es que no se inyectara un
    callable que no lleva a ninguna parte."""
    from types import SimpleNamespace

    import core.resolution as resolution_module
    from core.orchestrator import AgentOrchestrator

    capturado = {}

    def _resolve_falso(text, channel, user_id, claude_fn=None):
        capturado["claude_fn"] = claude_fn
        return SimpleNamespace(text=claude_fn(text) if claude_fn else "sin cerebro",
                               matched_by="claude")

    monkeypatch.setattr(resolution_module, "resolve", _resolve_falso)

    orquestador = AgentOrchestrator()
    orquestador.register_claude_brain(lambda t: f"cerebro propio: {t}")
    resultado = orquestador.process_task("hola", channel="desktop")

    assert capturado["claude_fn"] is not None
    assert resultado == "cerebro propio: hola"


def test_el_fallback_sin_cerebro_avisa_en_el_log(caplog):
    """Ya no es alcanzable desde `process_task()`, pero si alguien lo llama a mano tiene
    que quedar dicho por qué no respondió, en vez de devolver un texto que parece una
    respuesta del agente."""
    import logging

    from core.orchestrator import AgentOrchestrator

    orquestador = AgentOrchestrator()
    with caplog.at_level(logging.WARNING, logger="core.orchestrator"):
        respuesta = orquestador.fallback_to_claude("cualquier cosa")

    assert "No hay agente disponible" in respuesta
    assert any("sin cerebro registrado" in r.message for r in caplog.records)


def test_la_tarea_del_orquestador_llega_al_bucle_de_razonamiento(monkeypatch):
    """Prueba de la cadena entera, que es donde estaba el corte: orquestador -> resolve()
    -> resolver 'claude' -> bucle de razonamiento, con el canal real. Antes se detenia en
    el segundo salto."""
    import core.reasoning_loop as reasoning_module
    from core.orchestrator import AgentOrchestrator
    from core.security_manager import ChannelType

    llamadas = []

    def _razonar_falso(task, channel, user_id="default", agent_name="reasoning_loop"):
        llamadas.append((task, channel, user_id))
        return "lo resolvio el modelo"

    monkeypatch.setattr(reasoning_module, "run", _razonar_falso)

    resultado = AgentOrchestrator().process_task("¿todo en orden?", channel="desktop")

    assert resultado == "lo resolvio el modelo"
    assert len(llamadas) == 1
    # El canal llega RESUELTO, no como string: es lo que decide que permisos aplican.
    assert llamadas[0][1] == ChannelType.DESKTOP
