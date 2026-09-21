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


def test_ca22_el_prompt_incluye_los_turnos_recientes_hasta_llenar_el_presupuesto():
    """El corte es por TAMAÑO, no por cantidad: entran los turnos más recientes hasta
    llenar el presupuesto de caracteres, y los más viejos se caen primero.

    Antes eran 5 registros —dos o tres intercambios— y Johan le pidió "mejorá ese mensaje"
    a un agente que ya no tenía el mensaje.
    """
    turnos = [{"role": "user", "content": f"turno {i} " + "x" * 90} for i in range(7)]

    acotados = reasoning_loop.acotar_turnos(turnos, presupuesto=520)
    prompt = reasoning_loop._build_prompt("y entonces?", [], acotados)

    assert "turno 0 " not in prompt and "turno 1 " not in prompt
    for i in range(2, 7):
        assert f"turno {i} " in prompt
    assert "Mensaje actual del usuario: y entonces?" in prompt


def test_un_mensaje_largo_no_se_descarta_se_recorta_con_marca():
    """Un mensaje pegado por el usuario es justo lo que después pide que se mejore."""
    turnos = [{"role": "user", "content": "a" * 10_000}]
    acotados = reasoning_loop.acotar_turnos(turnos, presupuesto=16_000, por_turno=6_000)
    assert len(acotados) == 1
    assert acotados[0]["content"].endswith(" [...]")
    assert len(acotados[0]["content"]) == 6_000 + len(" [...]")


def test_la_respuesta_del_asistente_se_guarda_entera_y_no_cortada_a_200():
    """Con 200 caracteres, "corregí el segundo punto" trabajaba sobre un recorte."""
    assert reasoning_loop.MAX_RESPUESTA_GUARDADA >= 4_000


def test_run_usa_los_turnos_de_la_conversacion_abierta_si_se_los_dan():
    """El escritorio pasa la conversación ABIERTA: el contexto por usuario mezclaba
    conversaciones y el agente citaba cosas de otro chat."""
    final_response = LLMToolResponse(text="listo", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=final_response) as mock_gen,          patch("core.reasoning_loop._load_prior_turns") as mock_global,          patch("core.reasoning_loop.agent_context_manager"):
        reasoning_loop.run("mejorá ese mensaje", "desktop", "johan",
                           prior_turns=[{"role": "assistant", "content": "el mensaje entero"}])

    mock_global.assert_not_called()
    prompt = str(mock_gen.call_args_list[0])
    assert "el mensaje entero" in prompt


def test_run_le_pasa_la_imagen_del_turno_al_modelo_en_cada_vuelta_y_en_el_cierre(tmp_path):
    """REQ-054: en el escritorio la imagen adjunta no llegaba al modelo (solo su ruta en el
    texto). `image_path` viaja en cada `generate_response` de la vuelta y también en la
    llamada de cierre —es el mismo turno—, igual que por Telegram."""
    from unittest.mock import ANY

    from ai.llm_provider import ToolCallRequest

    ruta = str(tmp_path / "captura.png")
    pide_tool = LLMToolResponse(text="", tool_calls=[
        ToolCallRequest(id="c1", name="get_time", arguments={}),
    ])

    with patch("core.reasoning_loop.generate_response", return_value=pide_tool) as mock_gen, \
         patch("core.reasoning_loop.execute_tool", return_value="12:00"), \
         patch("core.reasoning_loop.cerrar_sin_herramientas", return_value="redactado") as mock_cierre, \
         patch("core.reasoning_loop.agent_context_manager"):
        resultado = reasoning_loop.run("¿qué hora marca la captura?", "desktop", "u1",
                                       image_path=ruta)

    assert resultado == "redactado"
    assert mock_gen.call_count >= 1
    for llamada in mock_gen.call_args_list:
        assert llamada.kwargs["image_path"] == ruta
    assert mock_cierre.call_args.kwargs["image_path"] == ruta


def test_run_sin_imagen_manda_image_path_none():
    final = LLMToolResponse(text="listo", tool_calls=[])
    with patch("core.reasoning_loop.generate_response", return_value=final) as mock_gen, \
         patch("core.reasoning_loop.agent_context_manager"):
        reasoning_loop.run("hola", "desktop", "u1")
    assert mock_gen.call_args.kwargs["image_path"] is None


def test_sin_turnos_de_fuera_run_cae_al_contexto_por_usuario():
    """Voz y CLI no tienen conversación propia: siguen con `agent_context`."""
    final_response = LLMToolResponse(text="listo", tool_calls=[])

    with patch("core.reasoning_loop.generate_response", return_value=final_response),          patch("core.reasoning_loop._load_prior_turns", return_value=[]) as mock_global,          patch("core.reasoning_loop.agent_context_manager"):
        reasoning_loop.run("hola", "desktop", "johan")

    mock_global.assert_called_once()


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
    """Si el LLM nunca da una respuesta final (siempre pide una tool), `run()` gasta
    exactamente el presupuesto en vueltas CON herramientas y no una más.

    REQ-027/CA-30: desde REQ-027 hay además una llamada de cierre SIN herramientas, fuera
    del presupuesto — de ahí el `+ 1`. Se asevera sobre las llamadas que llevaron `tools`
    porque es lo que el criterio significa ("como máximo el presupuesto de ese modo") y no
    se rompe si mañana cambia el mecanismo de cierre.
    """
    always_tool_call = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="test_ca02_tool", arguments={})],
    )

    with patch("core.reasoning_loop.generate_response", return_value=always_tool_call) as mock_gen, \
         patch("core.reasoning_loop.execute_tool", return_value="resultado parcial"), \
         patch("core.reasoning_loop.agent_context_manager"):
        result = reasoning_loop.run("tarea sin fin", "desktop", "u1")

    con_tools = [c for c in mock_gen.call_args_list if c.kwargs.get("tools")]
    assert len(con_tools) == reasoning_loop.MAX_LLM_CALLS
    assert mock_gen.call_count == reasoning_loop.MAX_LLM_CALLS + 1

    # El cierre va sin herramientas: sin ellas, "no sigas encadenando" es estructural.
    assert mock_gen.call_args_list[-1].kwargs.get("tools") is None

    # El cierre devolvió un `LLMToolResponse` con tool_calls (el mock siempre lo hace), que
    # no sirve como respuesta — se cae al enlatado de siempre (CA-31).
    assert "no pude completar la tarea" in result.lower()


def test_ca08_action_denied_corta_de_inmediato():
    """CA-08: ante ActionDenied, el loop corta sin reintentar la acción ni probar otra.

    REQ-027/CA-29: `generate_response` pasa de 1 a 2 llamadas porque ahora hay una llamada
    de cierre para redactar la respuesta con lo que ya se averiguó. Lo que CA-08 protege
    —que no se reintente— queda garantizado POR CONSTRUCCIÓN y no por una frase del
    prompt: esa segunda llamada va con `tools=None`, así que no hay ninguna herramienta
    que el modelo pueda volver a pedir.
    """
    tool_call_response = LLMToolResponse(
        text=None,
        tool_calls=[ToolCallRequest(id="1", name="algo_denegado", arguments={})],
    )

    with patch("core.reasoning_loop.generate_response", return_value=tool_call_response) as mock_gen, \
         patch("core.reasoning_loop.execute_tool",
               side_effect=ActionDenied("algo_denegado", "desktop", "denegado por security_manager")), \
         patch("core.reasoning_loop.agent_context_manager"):
        estado: dict = {}
        result = reasoning_loop.run("haz algo prohibido", "desktop", "u1", estado=estado)

    assert mock_gen.call_count == 2
    con_tools = [c for c in mock_gen.call_args_list if c.kwargs.get("tools")]
    assert len(con_tools) == 1, "solo la primera vuelta lleva herramientas"
    assert mock_gen.call_args_list[-1].kwargs.get("tools") is None

    # CA-32: la denegación se marca igual, haya cierre o no.
    assert estado.get("denied") is True
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
        presupuesto=8, tarea=None, prompt_hint="hint de prueba",
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


# ─────────────────────────────────────────────
#  REQ-027 — presupuesto, varias tool calls por vuelta y llamada de cierre
# ─────────────────────────────────────────────

def _respuesta_con(*nombres, texto=None):
    """Un `LLMToolResponse` que pide las herramientas nombradas, en ese orden."""
    return LLMToolResponse(
        text=texto,
        tool_calls=[ToolCallRequest(id=f"id{i}", name=n, arguments={})
                    for i, n in enumerate(nombres)],
    )


def _corrida(respuestas, canal="desktop", modo=None, execute=None, estado=None):
    """Corre `run()` con `generate_response` devolviendo `respuestas` en orden (la última
    se repite si el bucle sigue pidiendo). Return `(resultado, mock_gen, mock_exec)`."""
    secuencia = list(respuestas)

    def _siguiente(*a, **k):
        return secuencia.pop(0) if len(secuencia) > 1 else secuencia[0]

    with patch("core.reasoning_loop.generate_response", side_effect=_siguiente) as mock_gen, \
         patch("core.reasoning_loop.execute_tool",
               side_effect=execute or (lambda *a, **k: "ok")) as mock_exec, \
         patch("core.reasoning_loop.agent_context_manager"):
        resultado = reasoning_loop.run(
            "tarea", canal, "u1", modo=modo, estado=estado,
        )
    return resultado, mock_gen, mock_exec


def _llamadas_con_tools(mock_gen):
    return [c for c in mock_gen.call_args_list if c.kwargs.get("tools")]


def test_ca11_el_presupuesto_por_defecto_es_8():
    """CA-11: sin modo y en escritorio, 8 llamadas al modelo con herramientas."""
    assert reasoning_loop.MAX_LLM_CALLS == 8

    _, mock_gen, _ = _corrida([_respuesta_con("test_ca02_tool")])
    assert len(_llamadas_con_tools(mock_gen)) == 8


def test_ca13_con_modo_el_presupuesto_es_el_del_modo():
    """CA-13: Investigación 25, Código 40."""
    _, mock_gen, _ = _corrida([_respuesta_con("test_ca02_tool")], modo="investigacion")
    assert len(_llamadas_con_tools(mock_gen)) == 25

    _, mock_gen, _ = _corrida([_respuesta_con("test_ca02_tool")], modo="codigo")
    assert len(_llamadas_con_tools(mock_gen)) == 40


def test_ca14_modo_vacio_o_desconocido_cae_en_el_default():
    """CA-14: fail-safe — un frontend cacheado con un catálogo viejo nunca hereda 40."""
    for modo in (None, "", "no_existe_este_modo"):
        _, mock_gen, _ = _corrida([_respuesta_con("test_ca02_tool")], modo=modo)
        assert len(_llamadas_con_tools(mock_gen)) == reasoning_loop.MAX_LLM_CALLS, modo


def test_ca15_todo_canal_que_no_sea_escritorio_tiene_techo():
    """CA-15: cero regresión fuera del escritorio, y fail-closed para canales nuevos.

    Se prueba con `modo="codigo"` (presupuesto 40) a propósito: el techo tiene que ganar
    aunque llegue un modo con presupuesto alto desde donde sea.

    REQ-047: Telegram y Discord tienen `/detener`, así que su techo es el del escritorio
    sin modo (8); voz, correo y desconocido siguen en 5 porque ahí no hay forma de parar.
    """
    techos = {"voice": 5, "email": 5, "unknown": 5, "telegram": 8, "discord": 8}
    for canal, techo in techos.items():
        _, mock_gen, mock_exec = _corrida(
            [_respuesta_con("test_ca02_tool")], canal=canal, modo="codigo",
        )
        # Se cuentan VUELTAS (una herramienta por vuelta en esta simulacion) y no llamadas
        # con `tools`: en EMAIL el catalogo por canal queda vacio y `tools` llega falsy,
        # que mediria otra cosa. Lo que el presupuesto acota son las vueltas.
        assert mock_exec.call_count == techo, canal
        assert mock_gen.call_count == techo + 1, canal   # + la llamada de cierre (CA-30)


def test_ca15_el_escritorio_no_tiene_ese_techo():
    _, mock_gen, mock_exec = _corrida([_respuesta_con("test_ca02_tool")], canal="desktop")
    assert mock_exec.call_count == 8
    assert len(_llamadas_con_tools(mock_gen)) == 8


def test_ca17_la_firma_de_run_no_cambio():
    """CA-17: `tests/modelo_falso.py` instala un `run()` falso que es una función PLANA,
    no un MagicMock: un kwarg nuevo explotaría con TypeError en decenas de tests ajenos
    (pasó en REQ-026). El presupuesto se deriva de `modo` y `channel`, que ya existían."""
    import inspect

    parametros = list(inspect.signature(reasoning_loop.run).parameters)
    # `prior_turns` e `image_path` (REQ-054) se sumaron igual que `modo`: `resolve()` solo
    # los pasa cuando vienen, así que un doble con la firma vieja sigue sin recibir kwargs
    # que no espera.
    assert parametros == ["task", "channel", "user_id", "agent_name", "estado", "modo",
                          "prior_turns", "image_path"]


def test_ca18_una_vuelta_es_una_llamada_aunque_el_presupuesto_sea_40():
    """CA-18: el presupuesto es un techo, nunca un objetivo."""
    _, mock_gen, _ = _corrida([LLMToolResponse(text="listo", tool_calls=[])], modo="codigo")
    assert mock_gen.call_count == 1


def test_ca20_se_ejecutan_las_n_tool_calls_en_orden():
    """CA-20: antes se ejecutaba `tool_calls[0]` y las demás se descartaban."""
    respuestas = [_respuesta_con("t_a", "t_b", "t_c"),
                  LLMToolResponse(text="listo", tool_calls=[])]
    _, _, mock_exec = _corrida(respuestas)

    assert [c.args[0] for c in mock_exec.call_args_list] == ["t_a", "t_b", "t_c"]


def test_ca22_el_canal_y_el_usuario_se_inyectan_en_las_n():
    """CA-22 (invariante de REQ-005): el modelo no elige canal ni usuario en NINGUNA de
    las llamadas, ni siquiera proponiéndolos como argumentos."""
    respuesta = LLMToolResponse(text=None, tool_calls=[
        ToolCallRequest(id="a", name="t_a", arguments={"channel": "desktop", "user_id": "atacante"}),
        ToolCallRequest(id="b", name="t_b", arguments={}),
    ])
    _, _, mock_exec = _corrida([respuesta, LLMToolResponse(text="listo", tool_calls=[])],
                               canal="telegram")

    for llamada in mock_exec.call_args_list:
        params = llamada.args[1]
        assert params["user_id"] == "u1"
        assert params["channel"] == "telegram"
        assert params["texto_original"] == "tarea"


def test_ca24_una_vuelta_con_n_tools_consume_una_unidad():
    """CA-24: el presupuesto cuenta llamadas al modelo, no herramientas. Si contara
    herramientas, pedir 3 juntas costaría lo mismo que pedirlas de a una pero con 3 vueltas
    de latencia — un incentivo exactamente al revés del que este cambio busca."""
    _, mock_gen, mock_exec = _corrida([_respuesta_con("t_a", "t_b", "t_c")])

    assert len(_llamadas_con_tools(mock_gen)) == reasoning_loop.MAX_LLM_CALLS
    assert mock_exec.call_count == 3 * reasoning_loop.MAX_LLM_CALLS


def test_ca25_una_denegacion_corta_la_secuencia_de_la_vuelta():
    """CA-25: las herramientas siguientes de la MISMA vuelta no se ejecutan."""
    def _execute(nombre, *a, **k):
        if nombre == "t_b":
            raise ActionDenied("t_b", "desktop", "denegada por security_manager")
        return "ok"

    estado: dict = {}
    _, _, mock_exec = _corrida([_respuesta_con("t_a", "t_b", "t_c")],
                               execute=_execute, estado=estado)

    assert [c.args[0] for c in mock_exec.call_args_list] == ["t_a", "t_b"]
    assert estado.get("denied") is True


def test_ca25_las_no_ejecutadas_igual_tienen_resultado():
    """D-6: Anthropic y el SDK `openai` rechazan con 400 un turno donde un `tool_use` se
    queda sin su `tool_result`. Es EL punto que hace que esto funcione contra un proveedor
    real y no solo contra mocks."""
    from core import tool_history
    from core.security_manager import ChannelType

    def _execute(nombre, *a, **k):
        if nombre == "t_b":
            raise ActionDenied("t_b", "desktop", "denegada")
        return "ok"

    calls = [ToolCallRequest(id=f"id{i}", name=n, arguments={})
             for i, n in enumerate(("t_a", "t_b", "t_c"))]
    with patch("core.reasoning_loop.execute_tool", side_effect=_execute):
        llamadas, resultados, denegacion = reasoning_loop._ejecutar_vuelta(
            calls, 1, ChannelType.DESKTOP, "u1", "tarea",
        )

    assert denegacion is not None
    assert len(llamadas) == len(resultados) == 3
    assert [b["id"] for b in llamadas] == [b["id"] for b in resultados]
    assert resultados[2]["salida"] == reasoning_loop._NO_EJECUTADA
    assert all(b["salida"] for b in resultados), "ningún resultado puede ir vacío"
    assert tool_history.SIN_SALIDA not in [b["salida"] for b in resultados[:2]]


def test_ca26_una_excepcion_no_corta_la_secuencia():
    """CA-26: solo la denegación corta. Una tool que falla se informa y las demás siguen."""
    def _execute(nombre, *a, **k):
        if nombre == "t_b":
            raise RuntimeError("se rompió")
        return "ok"

    respuestas = [_respuesta_con("t_a", "t_b", "t_c"),
                  LLMToolResponse(text="listo", tool_calls=[])]
    _, _, mock_exec = _corrida(respuestas, execute=_execute)

    assert [c.args[0] for c in mock_exec.call_args_list] == ["t_a", "t_b", "t_c"]


def test_ca27_la_cancelacion_se_evalua_entre_herramientas():
    """CA-27: con varias herramientas por vuelta, esperar a la vuelta siguiente sería
    esperar a que terminen todas."""
    from core.cancelacion import TurnoCancelado
    from core.security_manager import ChannelType

    llamadas_vistas = []

    def _abortar(motivo):
        llamadas_vistas.append(motivo)
        if "t_c" in motivo:
            raise TurnoCancelado("detenido")

    calls = [ToolCallRequest(id=f"id{i}", name=n, arguments={})
             for i, n in enumerate(("t_a", "t_b", "t_c"))]
    with patch("core.reasoning_loop.execute_tool", return_value="ok"), \
         patch("core.reasoning_loop.abortar_si_cancelado", side_effect=_abortar):
        try:
            reasoning_loop._ejecutar_vuelta(calls, 1, ChannelType.DESKTOP, "u1", "tarea")
        except TurnoCancelado:
            pass

    assert any("t_a" in m for m in llamadas_vistas)
    assert any("t_c" in m for m in llamadas_vistas)


def test_ca28_agotado_el_presupuesto_hay_una_llamada_de_cierre_sin_tools():
    """CA-28: agotar 40 vueltas y devolver el enlatado tiraría a la basura 39 vueltas de
    trabajo ya pagado."""
    secuencia = [_respuesta_con("t_a")] * reasoning_loop.MAX_LLM_CALLS + ["con lo que vi, esto"]

    def _siguiente(*a, **k):
        return secuencia.pop(0)

    with patch("core.reasoning_loop.generate_response", side_effect=_siguiente) as mock_gen, \
         patch("core.reasoning_loop.execute_tool", return_value="ok"), \
         patch("core.reasoning_loop.agent_context_manager"):
        resultado = reasoning_loop.run("tarea", "desktop", "u1")

    assert mock_gen.call_count == reasoning_loop.MAX_LLM_CALLS + 1
    assert mock_gen.call_args_list[-1].kwargs.get("tools") is None
    assert resultado == "con lo que vi, esto"


def test_ca30_el_cierre_no_encadena():
    """CA-30: es como máximo UNA llamada por turno y está fuera del presupuesto — si el
    cierre pudiera encadenar, el techo no sería un techo."""
    secuencia = [_respuesta_con("t_a")] * reasoning_loop.MAX_LLM_CALLS + [
        _respuesta_con("t_b"),          # el cierre "pide" otra tool: no debe ejecutarse
    ]

    def _siguiente(*a, **k):
        return secuencia.pop(0) if secuencia else "no deberia llegar aca"

    with patch("core.reasoning_loop.generate_response", side_effect=_siguiente) as mock_gen, \
         patch("core.reasoning_loop.execute_tool", return_value="ok") as mock_exec, \
         patch("core.reasoning_loop.agent_context_manager"):
        resultado = reasoning_loop.run("tarea", "desktop", "u1")

    assert mock_gen.call_count == reasoning_loop.MAX_LLM_CALLS + 1
    assert mock_exec.call_count == reasoning_loop.MAX_LLM_CALLS, "el cierre no ejecutó nada"
    assert "no pude completar la tarea" in resultado.lower()


def test_ca31_si_el_cierre_falla_vuelve_el_texto_enlatado():
    """CA-31: proveedor caído o texto vacío — se cae al mensaje de siempre, no a nada."""
    for respuesta_de_cierre in ("Error: ANTHROPIC_API_KEY no está configurada.", "", None):
        secuencia = ([_respuesta_con("t_a")] * reasoning_loop.MAX_LLM_CALLS
                     + [respuesta_de_cierre])

        def _siguiente(*a, **k):
            return secuencia.pop(0)

        with patch("core.reasoning_loop.generate_response", side_effect=_siguiente), \
             patch("core.reasoning_loop.execute_tool", return_value="ok"), \
             patch("core.reasoning_loop.agent_context_manager"):
            resultado = reasoning_loop.run("tarea", "desktop", "u1")

        assert "no pude completar la tarea" in resultado.lower(), respuesta_de_cierre


def test_ca31_si_el_cierre_falla_tras_denegacion_vuelve_el_texto_de_denegacion():
    def _execute(*a, **k):
        raise ActionDenied("t_a", "desktop", "denegada por security_manager")

    secuencia = [_respuesta_con("t_a"), ""]

    def _siguiente(*a, **k):
        return secuencia.pop(0)

    with patch("core.reasoning_loop.generate_response", side_effect=_siguiente), \
         patch("core.reasoning_loop.execute_tool", side_effect=_execute), \
         patch("core.reasoning_loop.agent_context_manager"):
        estado: dict = {}
        resultado = reasoning_loop.run("tarea", "desktop", "u1", estado=estado)

    assert "no puedo ejecutar esa acción" in resultado.lower()
    assert "denegada por security_manager" in resultado
    assert estado.get("denied") is True


def test_ca32_denied_queda_en_true_aunque_el_cierre_redacte_una_respuesta_normal():
    """CA-32: `core/resolution.py` necesita saber que hubo denegación para no colgarle
    recordatorios ni repreguntas al turno, aunque el texto final suene normal."""
    def _execute(*a, **k):
        raise ActionDenied("t_a", "desktop", "denegada")

    secuencia = [_respuesta_con("t_a"), "No puedo hacer eso, pero te cuento lo que sí vi."]

    def _siguiente(*a, **k):
        return secuencia.pop(0)

    with patch("core.reasoning_loop.generate_response", side_effect=_siguiente), \
         patch("core.reasoning_loop.execute_tool", side_effect=_execute), \
         patch("core.reasoning_loop.agent_context_manager"):
        estado: dict = {}
        resultado = reasoning_loop.run("tarea", "desktop", "u1", estado=estado)

    assert estado.get("denied") is True
    assert resultado == "No puedo hacer eso, pero te cuento lo que sí vi."


# ─────────────────────────────────────────────
#  REQ-027 — el historial que emite el bucle es NEUTRAL
# ─────────────────────────────────────────────

def test_ca01_la_vuelta_siguiente_lleva_llamadas_y_resultados_correlacionados():
    """CA-01: el modelo ve sus propias llamadas y los resultados, no un texto reescrito."""
    from core import tool_history

    respuestas = [_respuesta_con("t_a", "t_b"), LLMToolResponse(text="listo", tool_calls=[])]
    _, mock_gen, _ = _corrida(respuestas)

    messages = mock_gen.call_args_list[1].args[0]
    llamadas = [b for m in messages if tool_history.es_estructurado(m)
                for b in m["content"] if b["tipo"] == tool_history.TIPO_LLAMADA]
    resultados = [b for m in messages if tool_history.es_estructurado(m)
                  for b in m["content"] if b["tipo"] == tool_history.TIPO_RESULTADO]

    assert [b["nombre"] for b in llamadas] == ["t_a", "t_b"]
    assert [b["id"] for b in llamadas] == [b["id"] for b in resultados]


def test_ca02_el_historial_que_emite_el_bucle_es_neutral():
    """CA-02: el bucle no habla el dialecto de ningún proveedor — si lo hiciera, un cambio
    de proveedor a mitad de turno (REQ-022) mandaría bloques que el nuevo no entiende."""
    import json

    respuestas = [_respuesta_con("t_a"), LLMToolResponse(text="listo", tool_calls=[])]
    _, mock_gen, _ = _corrida(respuestas)

    messages = mock_gen.call_args_list[1].args[0]
    serializado = json.dumps(messages, ensure_ascii=False, default=str)
    for clave_nativa in ("tool_use", "tool_result", "tool_calls", "tool_call_id"):
        assert clave_nativa not in serializado


def test_el_texto_original_no_se_le_reenvia_al_modelo():
    """D-7: con presupuesto 40 y varias herramientas por vuelta, el mensaje entero del
    usuario se repetiría más de cien veces en el prompt."""
    from core import tool_history

    respuestas = [_respuesta_con("t_a"), LLMToolResponse(text="listo", tool_calls=[])]
    _, mock_gen, _ = _corrida(respuestas)

    messages = mock_gen.call_args_list[1].args[0]
    bloque = [b for m in messages if tool_history.es_estructurado(m)
              for b in m["content"] if b["tipo"] == tool_history.TIPO_LLAMADA][0]

    # El bloque guarda el dict completo (CA-07 lo necesita)...
    assert "texto_original" in bloque["argumentos"]
    # ...pero lo que se le manda al modelo va sin las claves inyectadas.
    assert tool_history.argumentos_para_el_modelo(bloque) == {}
