"""
tests/test_reasoning_loop.py

Cobertura de `core/reasoning_loop.py` (REQ-007, CA-02, CA-06 a CA-11, CA-13).

Convenciones (.claude/rules/testing.md): sin red, sin tocar la DB real de contexto
(`agent_context_manager` siempre mockeado o con `update_context` interceptado),
`generate_response`/`execute_tool` siempre mockeados — este módulo nunca debe golpear un
proveedor LLM real ni ejecutar un tool real en tests.
"""
from pathlib import Path
from unittest.mock import patch

from agents.tool_registry import ToolSpec, register_tool
from ai.llm_provider import LLMToolResponse, ToolCallRequest
from core import reasoning_loop
from core.security_manager import ActionDenied, RiskLevel


def test_ca22_sin_historial_el_prompt_es_el_de_siempre():
    """REQ-021/CA-22: sin tools ejecutadas y sin turnos previos, `_build_prompt` devuelve
    la tarea tal cual — el prompt de antes de REQ-021, byte a byte."""
    assert reasoning_loop._build_prompt("qué hora es", []) == "qué hora es"
    assert reasoning_loop._build_prompt("qué hora es", [], None) == "qué hora es"
    assert reasoning_loop._build_prompt("qué hora es", [], []) == "qué hora es"


def test_ca22_el_prompt_incluye_los_ultimos_n_turnos():
    """REQ-021/CA-22: con 7 turnos en `agent_context`, el prompt lleva los últimos 5 y no
    los 2 primeros."""
    turnos = [{"role": "user", "content": f"turno {i}"} for i in range(7)]

    prompt = reasoning_loop._build_prompt(
        "y entonces?", [], turnos[-reasoning_loop.CONTEXT_TURNS:]
    )

    assert "turno 0" not in prompt
    assert "turno 1" not in prompt
    for i in range(2, 7):
        assert f"turno {i}" in prompt
    assert "Mensaje actual del usuario: y entonces?" in prompt


def test_ca22_los_turnos_previos_conviven_con_el_historial_de_tools():
    prompt = reasoning_loop._build_prompt(
        "sigue", [{"tool": "task_list", "params": {}, "result": "2 tareas"}],
        [{"role": "assistant", "content": "le queda una tarea"}],
    )

    assert "le queda una tarea" in prompt
    assert "task_list" in prompt
    assert "Tarea original del usuario: sigue" in prompt


def test_ca22_un_fallo_de_la_db_de_contexto_no_tumba_el_loop():
    """Leer el contexto es best-effort: si la DB falla, el loop sigue sin historial."""
    with patch("core.reasoning_loop.agent_context_manager") as mock_ctx:
        mock_ctx.get_context.side_effect = RuntimeError("db caída")
        assert reasoning_loop._load_prior_turns("reasoning_loop", "u1") == []


def test_ca22_los_turnos_leidos_son_estrictamente_anteriores():
    """El contexto se lee UNA vez, antes del bucle; las escrituras del turno actual pasan
    al final de `run()`, así que el turno en curso nunca se ve a sí mismo."""
    import inspect

    src = inspect.getsource(reasoning_loop.run)
    lectura = src.index("_load_prior_turns")
    escritura = src.index("update_context")
    assert lectura < escritura


def test_build_tool_list_expone_parameters_schema_sin_modificar():
    """CA-02: un ToolSpec registrado aparece en `_build_tool_list()` con su
    `parameters_schema` intacto."""
    schema = {
        "type": "object",
        "properties": {"foo": {"type": "string"}},
        "required": ["foo"],
    }
    register_tool(ToolSpec(
        name="test_ca02_tool",
        description="tool de prueba CA-02",
        parameters_schema=schema,
        risk_level=RiskLevel.GREEN,
        invoke=lambda params: "ok",
    ))

    tools = reasoning_loop._build_tool_list()
    entry = next(t for t in tools if t["name"] == "test_ca02_tool")

    assert entry["description"] == "tool de prueba CA-02"
    assert entry["parameters_schema"] == schema


def test_build_tool_list_no_filtra_por_channel():
    """CA-11 revisado: el filtro por canal NO es el control de seguridad.

    `_build_tool_list()` ahora acepta `channel` y omite lo que ese canal no podría
    ejecutar. Es presentación: ofrecerle a Telegram `terminal_run_command` solo le hace
    gastar una vuelta en pedir algo que le van a denegar. Lo que CA-11 protege —que el
    filtro real viva en `execute_tool()` y no en la lista— sigue en pie, y lo fija
    `test_el_filtro_de_la_lista_no_es_el_control_de_acceso`.

    Sin `channel` el comportamiento es el de siempre: el catálogo entero.
    """
    register_tool(ToolSpec(
        name="test_ca11_yellow",
        description="tool amarillo",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.YELLOW,
        invoke=lambda params: "ok",
    ))
    register_tool(ToolSpec(
        name="test_ca11_green",
        description="tool verde",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.GREEN,
        invoke=lambda params: "ok",
    ))

    names = {t["name"] for t in reasoning_loop._build_tool_list()}
    assert "test_ca11_yellow" in names
    assert "test_ca11_green" in names


def test_la_lista_por_canal_omite_lo_que_ese_canal_no_puede():
    """Por voz solo se permiten acciones verdes: una amarilla en la lista es una promesa
    que el gate va a romper."""
    from core.security_manager import ChannelType

    register_tool(ToolSpec(
        name="test_canal_yellow", description="amarillo",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.YELLOW, invoke=lambda params: "ok",
    ))

    por_voz = {t["name"] for t in reasoning_loop._build_tool_list(ChannelType.VOICE)}
    en_escritorio = {t["name"] for t in reasoning_loop._build_tool_list(ChannelType.DESKTOP)}

    assert "test_canal_yellow" in en_escritorio
    assert "test_canal_yellow" not in por_voz


def test_el_filtro_de_la_lista_no_es_el_control_de_acceso():
    """Lo que de verdad protege CA-11: aunque una tool se cuele en la lista de un canal
    que no puede ejecutarla, `execute_tool()` la deniega igual. El filtro ahorra vueltas;
    el gate es el que manda."""
    from agents.tool_registry import execute_tool
    from core.security_manager import ActionDenied, ChannelType

    register_tool(ToolSpec(
        name="test_gate_manda", description="amarillo",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.YELLOW, invoke=lambda params: "se ejecuto",
    ))

    try:
        execute_tool("test_gate_manda", {}, ChannelType.VOICE, "u1")
        raise AssertionError("el gate dejó pasar una amarilla por voz")
    except ActionDenied:
        pass


def test_ca06_reasoning_loop_nunca_llama_invoke_directo():
    """CA-06: verificable por grep estático — `core/reasoning_loop.py` nunca llama
    `.invoke(` directo, todo tool se ejecuta vía `execute_tool()`."""
    source = Path(reasoning_loop.__file__).read_text(encoding="utf-8")
    assert ".invoke(" not in source


def test_ca07_agota_5_llamadas_sin_una_sexta():
    """Si el LLM nunca da una respuesta final (siempre pide una tool), `run()` hace
    exactamente MAX_LLM_CALLS llamadas y retorna el mensaje de límite, nunca una 6ª."""
    always_tool_call = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="test_ca02_tool", arguments={})],
    )

    with patch("core.reasoning_loop.generate_response", return_value=always_tool_call) as mock_gen, \
         patch("core.reasoning_loop.execute_tool", return_value="resultado parcial"), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("tarea sin fin", "desktop", "u1")

    assert mock_gen.call_count == reasoning_loop.MAX_LLM_CALLS
    assert "no pude completar la tarea" in result.lower()


def test_ca08_action_denied_corta_de_inmediato():
    """CA-08: ante ActionDenied, el loop corta sin reintentar — `generate_response` se
    llamó solo 1 vez."""
    tool_call_response = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="algo_denegado", arguments={})],
    )

    with patch("core.reasoning_loop.generate_response", return_value=tool_call_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool",
               side_effect=ActionDenied("algo_denegado", "desktop", "denegado por security_manager")), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("haz algo prohibido", "desktop", "u1")

    assert mock_gen.call_count == 1
    assert "no puedo ejecutar esa acción" in result.lower()


def test_ca10_update_context_se_llama_exactamente_dos_veces():
    """CA-10: sin importar cuántas iteraciones internas hubo (3 tool-calls simuladas acá),
    `agent_context_manager.update_context()` se llama exactamente 2 veces en total."""
    tool_call_response = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="test_ca02_tool", arguments={})],
    )
    final_response = LLMToolResponse(text="tarea completada", tool_calls=[])

    with patch("core.reasoning_loop.generate_response",
               side_effect=[tool_call_response, tool_call_response, final_response]), \
         patch("core.reasoning_loop.execute_tool", return_value="resultado ok"), \
         patch("core.reasoning_loop.agent_context_manager") as mock_ctx:
        reasoning_loop.run("tarea con 3 iteraciones", "desktop", "u1")

    assert mock_ctx.update_context.call_count == 2
    roles = [call.args[2]["role"] for call in mock_ctx.update_context.call_args_list]
    assert roles == ["user", "assistant"]


def test_ca13_exception_generica_no_crashea_y_sigue_el_loop():
    """CA-13: si `execute_tool` levanta una excepción genérica (no ActionDenied), el loop
    no crashea — se registra como resultado fallido y continúa a la siguiente iteración."""
    tool_call_response = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="test_ca02_tool", arguments={})],
    )
    final_response = LLMToolResponse(text="me recuperé del error", tool_calls=[])

    with patch("core.reasoning_loop.generate_response",
               side_effect=[tool_call_response, final_response]), \
         patch("core.reasoning_loop.execute_tool", side_effect=KeyError("boom")), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("tarea con error interno", "desktop", "u1")

    assert result == "me recuperé del error"


def test_run_responde_directo_sin_tool_calls():
    """Caso borde de SPEC: el LLM responde sin pedir ninguna herramienta — se acepta como
    respuesta final sin insistir."""
    direct_response = LLMToolResponse(text="la respuesta es 42", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=direct_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool") as mock_exec, \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("cuánto es 6x7", "desktop", "u1")

    assert result == "la respuesta es 42"
    assert mock_gen.call_count == 1
    mock_exec.assert_not_called()


def test_confirmado1_proveedor_sin_tool_calling_degrada_a_texto_plano():
    """CONFIRMADO 1: si `generate_response()` retorna un `str` plano (proveedor sin
    soporte de tool-calling), el loop lo acepta directamente como respuesta final."""
    with patch("core.reasoning_loop.generate_response", return_value="respuesta en texto plano") as mock_gen, \
         patch("core.reasoning_loop.execute_tool") as mock_exec, \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("tarea con proveedor sin tools", "desktop", "u1")

    assert result == "respuesta en texto plano"
    assert mock_gen.call_count == 1
    mock_exec.assert_not_called()


# ---------------------------------------------------------------------------
# REQ-022/CA-12, CA-13, CA-14, CA-16, CA-17 — aviso de cambio de modelo dentro del texto
# de la respuesta. `test-results-022.md` (hallazgo de orion-tester): ninguno de estos CA
# tenía test dedicado — `generate_response` se mockeaba siempre con `return_value` fijo,
# que nunca rellena el parámetro `aviso` que el loop le pasa por kwargs.
# ---------------------------------------------------------------------------

def _fake_generate_response_con_aviso(aviso_a_rellenar):
    """`generate_response(..., aviso=un_dict_vacio)` en la vida real RELLENA ese dict
    in-place cuando hubo un swap de proveedor. Este fake reproduce ese contrato."""

    def _fake(*args, **kwargs):
        aviso = kwargs.get("aviso")
        if aviso is not None:
            aviso.update(aviso_a_rellenar)
        return "la respuesta es 42"

    return _fake


def test_ca12_14_17_aviso_de_cambio_queda_en_el_texto_final_por_defecto():
    """CA-12/CA-14/CA-17: canal desktop (no VOICE) — la forma LARGA del aviso (con
    proveedor y modelo de origen/destino) queda pegada al final de `final_text`, el mismo
    valor que se guarda en `agent_context` y se le muestra al usuario."""
    aviso = {
        "proveedor_desde": "deepseek", "modelo_desde": "deepseek-chat",
        "proveedor_hacia": "openrouter", "modelo_hacia": "openrouter/free",
    }
    fake_gen = _fake_generate_response_con_aviso(aviso)

    with patch("core.reasoning_loop.generate_response", side_effect=fake_gen), \
         patch("core.reasoning_loop.execute_tool") as mock_exec, \
         patch("core.reasoning_loop.agent_context_manager") as mock_ctx:
        result = reasoning_loop.run("cuánto es 6x7", "desktop", "u1")

    assert result == (
        "la respuesta es 42\n\n"
        "Cambié a openrouter (openrouter/free) porque deepseek (deepseek-chat) no respondió."
    )
    mock_exec.assert_not_called()
    # CA-14: lo que se persiste en agent_context es el texto CON el aviso, no el crudo.
    ultima_escritura = mock_ctx.update_context.call_args_list[-1]
    assert "Cambié a" in ultima_escritura.args[2]["content"]


def test_ca13_sin_cambio_de_destino_el_texto_no_lleva_aviso():
    """CA-13: sin swap (aviso queda vacío), `final_text` no gana ninguna línea nueva."""
    fake_gen = _fake_generate_response_con_aviso({})

    with patch("core.reasoning_loop.generate_response", side_effect=fake_gen), \
         patch("core.reasoning_loop.execute_tool"), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("cuánto es 6x7", "desktop", "u1")

    assert result == "la respuesta es 42"
    assert "Cambié" not in result


def test_ca16_en_canal_voice_el_aviso_es_la_forma_corta_sin_nombres_tecnicos():
    """CA-16: `resolved_channel == ChannelType.VOICE` → forma corta, sin nombres de
    proveedor/modelo."""
    aviso = {
        "proveedor_desde": "deepseek", "modelo_desde": "deepseek-chat",
        "proveedor_hacia": "openrouter", "modelo_hacia": "openrouter/free",
    }
    fake_gen = _fake_generate_response_con_aviso(aviso)

    with patch("core.reasoning_loop.generate_response", side_effect=fake_gen), \
         patch("core.reasoning_loop.execute_tool"), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("cuánto es 6x7", "voice", "u1")

    assert result == "la respuesta es 42\n\nCambié de modelo."
    assert "deepseek" not in result
    assert "openrouter" not in result


# ---------------------------------------------------------------------------
# REQ-026 — modos estratégicos del composer: reorden de tools, prompt_hint y `tarea`
# derivada del modo activo. `test-results-026.md` (orion-tester): ninguna de estas piezas
# tenía cobertura — `core/composer_modes.py` es un módulo nuevo y `_reordenar_priorizando`/
# `modo_def` en `_build_tool_list`/`_build_system_prompt`/`run()` no se ejercitaban en
# ningún test existente.
# ---------------------------------------------------------------------------

def test_reordenar_priorizando_mueve_al_frente_sin_filtrar():
    catalogo = [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]

    resultado = reasoning_loop._reordenar_priorizando(catalogo, ("c", "a"))

    # Las priorizadas van al frente, preservando su orden relativo original (a antes que c).
    assert [t["name"] for t in resultado] == ["a", "c", "b", "d"]
    # NUNCA filtra: el catálogo completo se conserva.
    assert len(resultado) == len(catalogo)


def test_reordenar_priorizando_sin_coincidencias_no_cambia_el_orden():
    catalogo = [{"name": "a"}, {"name": "b"}]
    assert reasoning_loop._reordenar_priorizando(catalogo, ("z",)) == catalogo


def test_reordenar_priorizando_catalogo_vacio_no_rompe():
    assert reasoning_loop._reordenar_priorizando([], ("a",)) == []


def test_build_tool_list_con_modo_def_prioriza_sin_filtrar():
    from core.composer_modes import ModoComposer

    register_tool(ToolSpec(
        name="req026_tool_a", description="a",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.GREEN, invoke=lambda params: "ok",
    ))
    register_tool(ToolSpec(
        name="req026_tool_b", description="b",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.GREEN, invoke=lambda params: "ok",
    ))
    modo_def = ModoComposer(
        id="req026_test_modo", label="Test", tool_names=("req026_tool_b",),
        tarea=None, prompt_hint="hint de prueba",
    )

    sin_modo = reasoning_loop._build_tool_list()
    con_modo = reasoning_loop._build_tool_list(modo_def=modo_def)

    # Nunca filtra: mismo conjunto de nombres con y sin modo.
    assert {t["name"] for t in con_modo} == {t["name"] for t in sin_modo}
    nombres = [t["name"] for t in con_modo]
    assert nombres.index("req026_tool_b") < nombres.index("req026_tool_a")


def test_build_tool_list_sin_modo_def_no_reordena_nada():
    """Regresión: `modo_def=None` (default) es idéntico al comportamiento de antes de
    REQ-026 — mismo catálogo, mismo orden."""
    assert (
        [t["name"] for t in reasoning_loop._build_tool_list()]
        == [t["name"] for t in reasoning_loop._build_tool_list(None, None)]
    )


def test_build_system_prompt_sin_modo_no_agrega_ninguna_frase():
    """Regresión: sin modo activo (default `None`), el prompt no menciona ningún modo —
    idéntico a antes de REQ-026."""
    assert "Modo activo" not in reasoning_loop._build_system_prompt()
    assert "Modo activo" not in reasoning_loop._build_system_prompt(None)


def test_build_system_prompt_agrega_prompt_hint_al_final_antes_de_fecha_hora():
    from core.composer_modes import get_mode

    modo_def = get_mode("codigo")
    prompt = reasoning_loop._build_system_prompt(modo_def)

    assert modo_def.prompt_hint in prompt
    # arquitectura-026.md: el hint va SIEMPRE al final, antes del bloque de fecha/hora —
    # nunca en medio del prompt, para no romper el prefix-caching.
    assert prompt.index(modo_def.prompt_hint) < prompt.index("Fecha y hora actual:")


def test_run_con_modo_codigo_activo_fija_tarea_modo_codigo_y_agrega_el_hint():
    direct_response = LLMToolResponse(text="listo", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=direct_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool"), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("escribime un script", "desktop", "u1", modo="codigo")

    assert result == "listo"
    assert mock_gen.call_args.kwargs["tarea"] == "modo_codigo"
    assert "Modo activo: Código/script" in mock_gen.call_args.args[1]


def test_run_con_modo_sin_tarea_fijada_sigue_usando_razonamiento():
    """Nodos/flujos y Tareas (arquitectura-026.md §3) no fijan `tarea` — el ruteo de
    modelo sigue siendo el de siempre aunque el modo esté activo."""
    direct_response = LLMToolResponse(text="ok", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=direct_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool"), \
         patch("core.reasoning_loop.agent_context_manager"):
        reasoning_loop.run("creá un flujo nuevo", "desktop", "u1", modo="flujos")

    assert mock_gen.call_args.kwargs["tarea"] == "razonamiento"
    assert "Modo activo: Nodos/flujos" in mock_gen.call_args.args[1]


def test_run_sin_modo_activo_es_identico_a_antes_de_req026():
    """Caso de no-regresión explícito de SPEC-026: un mensaje sin ningún modo activo se
    comporta exactamente igual que hoy."""
    direct_response = LLMToolResponse(text="ok", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=direct_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool"), \
         patch("core.reasoning_loop.agent_context_manager"):
        reasoning_loop.run("qué hora es", "desktop", "u1")

    assert mock_gen.call_args.kwargs["tarea"] == "razonamiento"
    assert "Modo activo" not in mock_gen.call_args.args[1]


def test_run_con_modo_id_desconocido_no_rompe_el_turno():
    """Fail-safe (`get_mode()`): un `modo_id` inválido u obsoleto —p. ej. un frontend
    cacheado tras cambiar el catálogo— se trata como 'sin modo', nunca como un error que
    le impida al usuario mandar el mensaje."""
    direct_response = LLMToolResponse(text="ok", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=direct_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool"), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("hola", "desktop", "u1", modo="modo_que_no_existe")

    assert result == "ok"
    assert mock_gen.call_args.kwargs["tarea"] == "razonamiento"
