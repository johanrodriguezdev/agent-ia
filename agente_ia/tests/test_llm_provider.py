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


# ─────────────────────────────────────────────
#  REQ-054 — la imagen del turno: tipo real y copia reducida
# ─────────────────────────────────────────────

def _png_de_prueba(tmp_path, nombre="captura.png", lado=8):
    import pytest as _pytest

    _pytest.importorskip("PIL")
    from PIL import Image

    ruta = tmp_path / nombre
    Image.new("RGB", (lado, lado), (255, 0, 0)).save(ruta, format="PNG")
    return str(ruta)


def test_anthropic_declara_el_media_type_real_de_la_imagen(tmp_path):
    """Una captura pegada es PNG. Antes el bloque decía siempre `image/jpeg` y la API la
    rechazaba por no coincidir con el contenido; las fotos de Telegram (JPEG) pasaban."""
    ruta = _png_de_prueba(tmp_path)

    salida = llm_provider._mensajes_para_anthropic(
        [{"role": "user", "content": "¿qué dice?"}], ruta,
    )

    bloque = salida[0]["content"][0]
    assert bloque["type"] == "image"
    assert bloque["source"]["media_type"] == "image/png"
    assert bloque["source"]["data"]


def test_openai_declara_el_media_type_real_en_el_data_url(tmp_path):
    ruta = _png_de_prueba(tmp_path)

    mensaje = llm_provider._ultimo_mensaje_openai(
        {"role": "user", "content": "¿qué dice?"}, ruta, imagen_como_bloque=True,
        aviso_sin_vision="",
    )

    assert mensaje["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_generate_response_reduce_la_imagen_antes_de_elegir_destino(monkeypatch, tmp_path):
    """Una imagen de 4K supera lo que aceptan los proveedores: `generate_response` la pasa
    por `preparar_para_el_modelo` y el adaptador recibe la copia reducida."""
    from core import imagenes

    ruta = _png_de_prueba(tmp_path, "4k.png", lado=8)
    monkeypatch.setattr(imagenes, "preparar_para_el_modelo",
                        lambda r: str(tmp_path / "reducida.png") if r == ruta else r)
    monkeypatch.setattr(llm_provider, "get_provider_config",
                        lambda: ("anthropic", "", "", "modelo-x"))
    monkeypatch.setattr(llm_provider, "destinos_de_tarea", lambda tarea: [])
    recibidas = []

    def _uncached(prov, messages, system_prompt, image_path, model_name, tools=None):
        recibidas.append(image_path)
        return "ok"

    monkeypatch.setattr(llm_provider, "_uncached_call", _uncached)
    monkeypatch.setattr(llm_provider, "_debe_cachear", lambda tools, messages: False)
    monkeypatch.setattr(llm_provider.provider_health, "ordenar_por_disponibilidad", lambda c: c)
    monkeypatch.setattr(llm_provider.provider_health, "registrar_exito", lambda *a, **k: None)

    respuesta = generate_response([{"role": "user", "content": "hola"}], "sys", image_path=ruta)

    assert respuesta == "ok"
    assert recibidas == [str(tmp_path / "reducida.png")]


# ─────────────────────────────────────────────
#  REQ-061 — «Ver imágenes» como tarea configurable
# ─────────────────────────────────────────────

def _png_chico(tmp_path):
    import pytest as _pytest

    _pytest.importorskip("PIL")
    from PIL import Image

    ruta = tmp_path / "captura.png"
    Image.new("RGB", (4, 4), (0, 0, 0)).save(ruta, format="PNG")
    return str(ruta)


def test_con_la_tarea_vision_configurada_la_imagen_va_a_esos_modelos(monkeypatch, tmp_path):
    """Configuración → Modelos → «Ver imágenes» manda, con su lista de rotación."""
    ruta = _png_chico(tmp_path)
    monkeypatch.setattr(llm_provider, "destinos_de_tarea",
                        lambda tarea: [("anthropic", "claude-x"), ("gemini", "")] if tarea == "vision" else [])

    destinos = llm_provider._destinos_iniciales("razonamiento", "deepseek", "deepseek-chat", "gemini", ruta)

    assert destinos[0] == ("anthropic", "claude-x")
    assert destinos[1][0] == "gemini" and destinos[1][1]     # modelo por defecto del proveedor


def test_sin_tarea_vision_vale_el_vision_provider_de_siempre(monkeypatch, tmp_path):
    ruta = _png_chico(tmp_path)
    monkeypatch.setattr(llm_provider, "destinos_de_tarea", lambda tarea: [])

    destinos = llm_provider._destinos_iniciales("razonamiento", "deepseek", "deepseek-chat", "gemini", ruta)

    assert len(destinos) == 1 and destinos[0][0] == "gemini"


def test_sin_imagen_la_tarea_vision_no_interviene(monkeypatch):
    monkeypatch.setattr(llm_provider, "destinos_de_tarea",
                        lambda tarea: [("anthropic", "claude-x")] if tarea == "vision" else [])

    destinos = llm_provider._destinos_iniciales("razonamiento", "deepseek", "deepseek-chat", "gemini", None)

    assert destinos == [("deepseek", "deepseek-chat")]


def test_sin_vision_provider_ni_tarea_la_imagen_va_al_modelo_general(monkeypatch, tmp_path):
    ruta = _png_chico(tmp_path)
    monkeypatch.setattr(llm_provider, "destinos_de_tarea", lambda tarea: [])

    destinos = llm_provider._destinos_iniciales("razonamiento", "deepseek", "deepseek-chat", "", ruta)

    assert destinos == [("deepseek", "deepseek-chat")]


# ─────────────────────────────────────────────
#  REQ-063 — varias imágenes en una misma llamada
# ─────────────────────────────────────────────

def test_rutas_de_imagen_acepta_una_ruta_una_lista_o_nada(tmp_path):
    a = _png_de_prueba(tmp_path, "a.png")
    b = _png_de_prueba(tmp_path, "b.png")
    assert llm_provider.rutas_de_imagen(None) == []
    assert llm_provider.rutas_de_imagen("") == []
    assert llm_provider.rutas_de_imagen(a) == [a]
    assert llm_provider.rutas_de_imagen([a, b]) == [a, b]
    assert llm_provider.rutas_de_imagen([a, str(tmp_path / "no.png")]) == [a]   # la que no está no viaja


def test_anthropic_manda_un_bloque_por_imagen_antes_del_texto(tmp_path):
    a = _png_de_prueba(tmp_path, "a.png")
    b = _png_de_prueba(tmp_path, "b.png")

    salida = llm_provider._mensajes_para_anthropic([{"role": "user", "content": "¿cuál es mejor?"}], [a, b])

    tipos = [bloque["type"] for bloque in salida[0]["content"]]
    assert tipos == ["image", "image", "text"]


def test_openai_manda_un_image_url_por_imagen(tmp_path):
    a = _png_de_prueba(tmp_path, "a.png")
    b = _png_de_prueba(tmp_path, "b.png")

    mensaje = llm_provider._ultimo_mensaje_openai(
        {"role": "user", "content": "¿cuál?"}, [a, b], imagen_como_bloque=True, aviso_sin_vision="",
    )

    assert [c["type"] for c in mensaje["content"]] == ["text", "image_url", "image_url"]


def test_generate_response_prepara_cada_imagen_y_una_sola_sigue_siendo_string(monkeypatch, tmp_path):
    from core import imagenes

    a = _png_de_prueba(tmp_path, "a.png")
    b = _png_de_prueba(tmp_path, "b.png")
    monkeypatch.setattr(imagenes, "preparar_para_el_modelo", lambda r: r + ".mini")
    monkeypatch.setattr(llm_provider, "get_provider_config", lambda: ("anthropic", "", "", "modelo-x"))
    monkeypatch.setattr(llm_provider, "destinos_de_tarea", lambda tarea: [])
    recibidas = []
    monkeypatch.setattr(llm_provider, "_uncached_call",
                        lambda prov, messages, sp, image_path, model, tools=None: recibidas.append(image_path) or "ok")
    monkeypatch.setattr(llm_provider, "_debe_cachear", lambda tools, messages: False)
    monkeypatch.setattr(llm_provider.provider_health, "ordenar_por_disponibilidad", lambda c: c)
    monkeypatch.setattr(llm_provider.provider_health, "registrar_exito", lambda *a, **k: None)

    generate_response([{"role": "user", "content": "hola"}], "sys", image_path=[a, b])
    generate_response([{"role": "user", "content": "hola"}], "sys", image_path=a)

    assert recibidas == [[a + ".mini", b + ".mini"], a + ".mini"]
