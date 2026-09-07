"""
tests/test_llm_provider.py

Cobertura de la extensión de tool-calling en `ai/llm_provider.py` (REQ-007, CA-03, CA-04,
CA-05, CONFIRMADO 1, CA-09). No existía antes de este REQ (confirmado por
origen/baseline-007.md).

Convenciones (.claude/rules/testing.md): sin red real — SDKs de `anthropic`/`openai` (este
último no instalado en el entorno de desarrollo, ver desarrollo-log-007.md) siempre
mockeados; nunca se usa una API key real.
"""
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

from ai import llm_provider
from ai.llm_provider import LLMToolResponse, ToolCallRequest, generate_response

_TOOLS = [{
    "name": "mi_tool",
    "description": "una tool de prueba",
    "parameters_schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
}]


def _fake_anthropic_module(fake_client) -> ModuleType:
    """Inyecta un módulo `anthropic` falso en sys.modules.

    El SDK está comentado en requirements.txt (es opcional: solo hace falta si el humano
    elige Anthropic como proveedor), así que `patch("anthropic.Anthropic")` fallaba con
    ModuleNotFoundError y dejaba estos dos tests en rojo permanente — con la suite siempre
    en rojo, un fallo de verdad no se distingue del ruido de fondo.
    """
    module = ModuleType("anthropic")
    module.Anthropic = MagicMock(return_value=fake_client)
    return module


def _fake_openai_module(fake_client) -> ModuleType:
    """Inyecta un módulo `openai` falso en sys.modules — el SDK real no está instalado en
    este entorno (confirmado por `python -c "import openai"` fallando con
    ModuleNotFoundError), así que `from openai import OpenAI` dentro de
    `_ask_openai`/`_ask_deepseek` necesita este stub para poder importar en absoluto."""
    module = ModuleType("openai")
    module.OpenAI = MagicMock(return_value=fake_client)
    return module


def test_ca03_generate_response_sin_tools_comportamiento_no_roto(monkeypatch):
    """CA-03: generate_response() sin `tools=` sigue exactamente el camino de antes de
    este REQ — usa `_cached_call()`, nunca `_uncached_call()`."""
    monkeypatch.setattr(llm_provider, "get_provider_config", lambda: ("anthropic", "", "", ""))

    with patch("ai.llm_provider._cached_call", return_value="respuesta normal") as mock_cached, \
         patch("ai.llm_provider._uncached_call") as mock_uncached:
        result = generate_response([{"role": "user", "content": "hola"}], "system")

    assert result == "respuesta normal"
    mock_cached.assert_called_once()
    mock_uncached.assert_not_called()


def test_ca04_ask_anthropic_parsea_tool_use_en_llmtoolresponse(monkeypatch):
    """CA-04: `_ask_anthropic(..., tools=[...])` parsea un bloque `tool_use` de
    `response.content` en `LLMToolResponse`/`ToolCallRequest`."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    tool_use_block = SimpleNamespace(type="tool_use", id="call_1", name="mi_tool", input={"x": 1})
    fake_response = SimpleNamespace(content=[tool_use_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch.dict(sys.modules, {"anthropic": _fake_anthropic_module(fake_client)}):
        result = llm_provider._ask_anthropic(
            [{"role": "user", "content": "usa la tool"}], "system", None, "", tools=_TOOLS,
        )

    assert isinstance(result, LLMToolResponse)
    assert result.tool_calls == [ToolCallRequest(id="call_1", name="mi_tool", arguments={"x": 1})]

    sent_kwargs = fake_client.messages.create.call_args.kwargs
    assert sent_kwargs["tools"] == [
        {"name": "mi_tool", "description": "una tool de prueba",
         "input_schema": _TOOLS[0]["parameters_schema"]}
    ]


def test_ca04_ask_anthropic_sin_tools_comportamiento_no_roto(monkeypatch):
    """Regresión: `_ask_anthropic()` sin `tools=` sigue retornando `str` plano, no
    `LLMToolResponse`."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    text_block = SimpleNamespace(type="text", text="respuesta de siempre")
    fake_response = SimpleNamespace(content=[text_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch.dict(sys.modules, {"anthropic": _fake_anthropic_module(fake_client)}):
        result = llm_provider._ask_anthropic(
            [{"role": "user", "content": "hola"}], "system", None, "",
        )

    assert result == "respuesta de siempre"
    assert "tools" not in fake_client.messages.create.call_args.kwargs


def test_ca05_ask_openai_parsea_tool_calls_en_llmtoolresponse(monkeypatch):
    """CA-05: `_ask_openai(..., tools=[...])` parsea `message.tool_calls` en
    `LLMToolResponse`/`ToolCallRequest`."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    fake_tool_call = SimpleNamespace(
        id="call_1", function=SimpleNamespace(name="mi_tool", arguments='{"x": 1}')
    )
    fake_message = SimpleNamespace(content=None, tool_calls=[fake_tool_call])
    fake_response = SimpleNamespace(choices=[SimpleNamespace(message=fake_message)])
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    fake_module = _fake_openai_module(fake_client)
    with patch.dict(sys.modules, {"openai": fake_module}):
        result = llm_provider._ask_openai(
            [{"role": "user", "content": "usa la tool"}], "system", None, "", tools=_TOOLS,
        )

    assert isinstance(result, LLMToolResponse)
    assert result.tool_calls == [ToolCallRequest(id="call_1", name="mi_tool", arguments={"x": 1})]

    sent_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert sent_kwargs["tools"] == [{
        "type": "function",
        "function": {"name": "mi_tool", "description": "una tool de prueba",
                      "parameters": _TOOLS[0]["parameters_schema"]},
    }]


def test_ca05_ask_deepseek_parsea_tool_calls_en_llmtoolresponse(monkeypatch):
    """CA-05: mismo parseo para `_ask_deepseek()` (comparte SDK `openai` con
    `_ask_openai`)."""
    monkeypatch.setattr("config_manager.get_deepseek_api_key", lambda: "test-key")

    fake_tool_call = SimpleNamespace(
        id="call_2", function=SimpleNamespace(name="mi_tool", arguments='{"x": 2}')
    )
    fake_message = SimpleNamespace(content=None, tool_calls=[fake_tool_call])
    fake_response = SimpleNamespace(choices=[SimpleNamespace(message=fake_message)])
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_response

    fake_module = _fake_openai_module(fake_client)
    with patch.dict(sys.modules, {"openai": fake_module}):
        result = llm_provider._ask_deepseek(
            [{"role": "user", "content": "usa la tool"}], "system", None, "", tools=_TOOLS,
        )

    assert isinstance(result, LLMToolResponse)
    assert result.tool_calls == [ToolCallRequest(id="call_2", name="mi_tool", arguments={"x": 2})]


def test_confirmado1_gemini_ignora_tools_en_silencio(monkeypatch):
    """CONFIRMADO 1: con `active_provider="gemini"` y `tools=[...]`, `generate_response()`
    llega a `_ask_gemini()` SIN tools (degradación silenciosa, vía `_cached_call()` — no
    fuerza el bypass de CA-09 porque gemini no soporta tool-calling) y retorna `str`,
    nunca `LLMToolResponse`."""
    monkeypatch.setattr(llm_provider, "get_provider_config", lambda: ("gemini", "", "", ""))

    # `generate_response()` decide entre `_cached_call()`/`_uncached_call()` ANTES de
    # llegar a `_ask_gemini()` — se mockean ambos puntos de entrada para verificar cuál
    # de los dos elige (CA-09 solo fuerza `_uncached_call` directo cuando
    # `effective_tools` es verdadero, y para gemini siempre es `None`).
    with patch("ai.llm_provider._cached_call", return_value="respuesta de gemini") as mock_cached, \
         patch("ai.llm_provider._uncached_call") as mock_uncached:
        result = generate_response(
            [{"role": "user", "content": "hola"}], "system", tools=_TOOLS,
        )

    mock_cached.assert_called_once()
    mock_uncached.assert_not_called()
    assert result == "respuesta de gemini"
    assert not isinstance(result, LLMToolResponse)


def test_confirmado1_uncached_call_no_reenvia_tools_a_gemini():
    """`_uncached_call()` solo reenvía `tools` a los proveedores que lo soportan — gemini
    se llama con la firma de siempre, sin `tools`."""
    with patch("ai.llm_provider._ask_gemini", return_value="ok") as mock_gemini:
        result = llm_provider._uncached_call("gemini", [], "system", None, "modelo", tools=_TOOLS)

    mock_gemini.assert_called_once_with([], "system", None, "modelo")
    assert result == "ok"


def test_ca09_generate_response_bypassa_cache_con_tools(monkeypatch):
    """CA-09: cuando `tools` está presente y el proveedor lo soporta, `generate_response()`
    usa `_uncached_call()` en las DOS llamadas (nunca `_cached_call()`), incluso con el
    mismo `messages`/`system_prompt` — nunca se cachea una decisión de tool-calling."""
    monkeypatch.setattr(llm_provider, "get_provider_config", lambda: ("anthropic", "", "", ""))

    messages = [{"role": "user", "content": "misma pregunta"}]
    with patch("ai.llm_provider._uncached_call", return_value="resp") as mock_uncached, \
         patch("ai.llm_provider._cached_call") as mock_cached:
        generate_response(messages, "system", tools=_TOOLS)
        generate_response(messages, "system", tools=_TOOLS)

    assert mock_uncached.call_count == 2
    mock_cached.assert_not_called()


# --------------------------------------------------------------------- REQ-022: aviso de cambio
#
# `texto_aviso_cambio()`/`con_aviso_de_cambio()` son públicas (sin prefijo `_`) y hasta
# ahora no tenían ningún test commiteado (test-results-022.md, hallazgo de orion-tester) —
# son el núcleo de las Decisiones 3/4 de SPEC-022.md (CA-12 a CA-18): el aviso de cambio de
# modelo dentro del texto de la respuesta, y su forma corta para voz.

def test_ca13_sin_cambio_de_destino_el_texto_no_se_toca():
    """CA-13: `aviso` sin `proveedor_hacia` (o `None`/`{}`) — ni `texto_aviso_cambio()` ni
    `con_aviso_de_cambio()` agregan nada."""
    assert llm_provider.texto_aviso_cambio(None) == ""
    assert llm_provider.texto_aviso_cambio({}) == ""
    assert llm_provider.texto_aviso_cambio({"proveedor_desde": "deepseek"}) == ""

    assert llm_provider.con_aviso_de_cambio("la respuesta", None) == "la respuesta"
    assert llm_provider.con_aviso_de_cambio("la respuesta", {}) == "la respuesta"


def test_ca12_17_con_cambio_la_forma_larga_lleva_proveedor_y_modelo():
    """CA-12/CA-17: con un cambio real, la forma larga menciona proveedor y modelo de
    origen y destino, y `con_aviso_de_cambio()` la agrega al FINAL del texto original."""
    aviso = {
        "proveedor_desde": "deepseek", "modelo_desde": "deepseek-chat",
        "proveedor_hacia": "openrouter", "modelo_hacia": "openrouter/free",
    }

    frase = llm_provider.texto_aviso_cambio(aviso)

    assert frase == "Cambié a openrouter (openrouter/free) porque deepseek (deepseek-chat) no respondió."
    assert llm_provider.con_aviso_de_cambio("la respuesta", aviso) == f"la respuesta\n\n{frase}"


def test_ca16_con_cambio_y_corto_no_lleva_nombres_tecnicos():
    """CA-16: `corto=True` (canal de voz) devuelve siempre `AVISO_CAMBIO_CORTO`, sin
    importar los proveedores/modelos involucrados."""
    aviso = {
        "proveedor_desde": "deepseek", "modelo_desde": "deepseek-chat",
        "proveedor_hacia": "openrouter", "modelo_hacia": "openrouter/free",
    }

    frase = llm_provider.texto_aviso_cambio(aviso, corto=True)

    assert frase == llm_provider.AVISO_CAMBIO_CORTO
    assert "deepseek" not in frase and "openrouter" not in frase
    assert llm_provider.con_aviso_de_cambio("la respuesta", aviso, corto=True) == (
        f"la respuesta\n\n{llm_provider.AVISO_CAMBIO_CORTO}"
    )


def test_aviso_cambio_re_reconoce_exactamente_lo_que_arma_texto_aviso_cambio():
    """Auto-consistencia (riesgo documentado en arquitectura-022.md): `AVISO_CAMBIO_RE` —
    que usa `ui/tts_engine.py::prepare_for_speech()` para acortar la forma larga (CA-18) —
    tiene que reconocer exactamente lo que arma `texto_aviso_cambio()`, para que un cambio
    de redacción en uno no desincronice al otro sin que ningún test lo note."""
    aviso = {
        "proveedor_desde": "ollama", "modelo_desde": "qwen3:8b",
        "proveedor_hacia": "openai", "modelo_hacia": "gpt-4o-mini",
    }
    texto_con_aviso = llm_provider.con_aviso_de_cambio("hola", aviso)

    assert llm_provider.AVISO_CAMBIO_RE.search(texto_con_aviso)

    acortado = llm_provider.AVISO_CAMBIO_RE.sub(f"\n\n{llm_provider.AVISO_CAMBIO_CORTO}", texto_con_aviso)
    assert acortado == f"hola\n\n{llm_provider.AVISO_CAMBIO_CORTO}"


def test_ca06_07_con_openrouter_api_key_configurada_se_intenta_antes_que_ollama(monkeypatch):
    """CA-06/CA-07, caso positivo (el hallazgo menor de test-results-022.md): con
    `OPENROUTER_API_KEY` configurada, la cadena de respaldo por defecto ofrece OpenRouter
    ANTES que Ollama — hasta ahora solo estaba commiteado el lado "sin clave"."""
    import config_manager

    monkeypatch.setattr(config_manager, "get_api_key", lambda p: "sk-or-test" if p == "openrouter" else "")

    cadena = llm_provider._cadena_de_respaldo_por_defecto("deepseek")

    assert cadena == [
        ("openrouter", "openrouter/free"),
        ("ollama", llm_provider._MODELO_POR_PROVEEDOR["ollama"]),
    ]
