"""
tests/test_paridad_canales.py
REQ-044 — Telegram/Discord razonan como el escritorio, y la voz tiene techo de salida.

Lo que protege esta suite:
- `ai/claude_brain._resolver_con_tools()` manda los resultados de herramientas como
  historial NEUTRAL (`core/tool_history.py`), no como texto pegado (CA-02); ejecuta TODAS
  las tool calls de la vuelta (CA-03); usa el presupuesto del canal (CA-04); cierra sin
  herramientas al agotar o ante denegación (CA-05); no depende del botón de detener del
  escritorio (CA-06); y no persiste bloques en el historial por usuario (CA-07).
- `ai/llm_provider.tope_de_salida()` acota los tokens en el hilo y solo dentro del bloque
  (CA-09); `reasoning_loop.run()` lo aplica en VOICE y en ningún otro canal (CA-10/11).

Sin red: `generate_response` y `execute_tool` se reemplazan; `catalogo_para_modelo`
devuelve un catálogo mínimo para que el canal remoto tenga algo que pedir.
"""

import threading
from unittest.mock import patch

import pytest

from ai import claude_brain, llm_provider
from ai.llm_provider import LLMToolResponse, ToolCallRequest
from core import cancelacion, reasoning_loop, tool_history
from core.security_manager import ActionDenied, ChannelType

CATALOGO = [{"name": "web_search", "description": "busca", "parameters_schema": {}}]
HISTORIA = [{"role": "user", "content": "buscá el clima y la hora"}]


def _llamada(nombre, i=0, **args):
    return ToolCallRequest(id=f"c{i}", name=nombre, arguments=args)


def _resolver(respuestas, ejecutar=None):
    """Corre `_resolver_con_tools` con un modelo que responde `respuestas` en orden.

    Return `(texto, llamadas_al_modelo, ejecuciones)`.
    """
    llamadas = []
    ejecuciones = []

    def fake_generate(messages, system_prompt, image_path=None, tools=None, tarea="general",
                      aviso=None):
        llamadas.append({"messages": list(messages), "tools": tools})
        indice = min(len(llamadas) - 1, len(respuestas) - 1)
        return respuestas[indice]

    def fake_execute(nombre, params, canal, user_id):
        ejecuciones.append((nombre, dict(params)))
        if ejecutar is not None:
            return ejecutar(nombre, params)
        return f"resultado de {nombre}"

    # Las dos vías al modelo: el bucle importa `generate_response` dentro de la función
    # (vía `ai.llm_provider`) y el cierre compartido la tiene ligada en `core.reasoning_loop`.
    with patch("ai.llm_provider.generate_response", side_effect=fake_generate), \
         patch("core.reasoning_loop.generate_response", side_effect=fake_generate), \
         patch("agents.tool_registry.catalogo_para_modelo", return_value=CATALOGO), \
         patch("core.reasoning_loop.execute_tool", side_effect=fake_execute):
        texto = claude_brain._resolver_con_tools(
            history=list(HISTORIA), system_prompt="system", image_path=None,
            channel="telegram", user_id="u1",
        )
    return texto, llamadas, ejecuciones


# ── CA-02 / CA-03: historial neutral y todas las tool calls ─────────

def test_los_resultados_viajan_como_historial_neutral_y_no_como_texto():
    texto, llamadas, _ = _resolver([
        LLMToolResponse(text=None, tool_calls=[_llamada("web_search", 0, q="clima")]),
        LLMToolResponse(text="llueve", tool_calls=[]),
    ])

    assert texto == "llueve"
    assert len(llamadas) == 2
    segunda = llamadas[1]["messages"]
    assert segunda[0] == HISTORIA[0]                          # la conversación, tal cual
    assert tool_history.tiene_historial_de_herramientas(segunda)
    assert not any("[Resultado de" in str(m.get("content")) for m in segunda)


def test_se_ejecutan_todas_las_tool_calls_de_la_vuelta_en_orden():
    _, llamadas, ejecuciones = _resolver([
        LLMToolResponse(text=None, tool_calls=[
            _llamada("web_search", 0, q="clima"), _llamada("web_search", 1, q="hora"),
        ]),
        LLMToolResponse(text="listo", tool_calls=[]),
    ])

    assert [e[0] for e in ejecuciones] == ["web_search", "web_search"]
    assert [e[1]["q"] for e in ejecuciones] == ["clima", "hora"]
    assert len(llamadas) == 2                                 # una sola vuelta para las dos
    resultados = tool_history.pares_de(llamadas[1]["messages"])
    assert len(resultados) == 2


def test_el_canal_y_el_usuario_los_pone_el_caller_en_cada_llamada():
    _, _, ejecuciones = _resolver([
        LLMToolResponse(text=None, tool_calls=[
            _llamada("web_search", 0, q="a", channel="desktop", user_id="otro"),
            _llamada("web_search", 1, q="b"),
        ]),
        LLMToolResponse(text="listo", tool_calls=[]),
    ])

    for _, params in ejecuciones:
        assert params["channel"] == "telegram"
        assert params["user_id"] == "u1"
        assert params["texto_original"] == HISTORIA[0]["content"]


# ── CA-04 / CA-05: presupuesto y cierre ─────────────────────────────

def test_el_presupuesto_es_el_del_canal_y_el_cierre_va_sin_herramientas():
    pide_siempre = LLMToolResponse(text=None, tool_calls=[_llamada("web_search", 0)])
    texto, llamadas, _ = _resolver([pide_siempre] * 20 + [])

    con_tools = [l for l in llamadas if l["tools"]]
    sin_tools = [l for l in llamadas if not l["tools"]]
    assert len(con_tools) == reasoning_loop.TECHO_CANAL_REMOTO_CON_STOP
    assert len(sin_tools) == 1                                # el cierre, fuera del presupuesto
    assert llamadas[-1]["tools"] is None
    assert not hasattr(claude_brain, "MAX_TOOL_ROUNDS")


def test_el_cierre_redacta_con_lo_reunido_al_agotar_el_presupuesto():
    pide = LLMToolResponse(text=None, tool_calls=[_llamada("web_search", 0)])
    cierre = LLMToolResponse(text="con lo que encontré: llueve", tool_calls=[])
    texto, llamadas, _ = _resolver([pide] * reasoning_loop.TECHO_CANAL_REMOTO_CON_STOP + [cierre])

    assert texto == "con lo que encontré: llueve"
    ultimo = llamadas[-1]["messages"][-1]
    assert reasoning_loop._INSTRUCCION_CIERRE_PRESUPUESTO in str(ultimo)


def test_una_denegacion_corta_y_el_cierre_lo_explica():
    def ejecutar(nombre, params):
        raise ActionDenied("web_search", reason="no por Telegram")

    cierre = LLMToolResponse(text="no puedo hacer eso desde acá", tool_calls=[])
    texto, llamadas, ejecuciones = _resolver([
        LLMToolResponse(text=None, tool_calls=[
            _llamada("web_search", 0), _llamada("web_search", 1),
        ]),
        cierre,
    ], ejecutar=ejecutar)

    assert texto == "no puedo hacer eso desde acá"
    assert len(ejecuciones) == 1                              # la segunda no se ejecuta
    assert len(llamadas) == 2                                 # una vuelta + el cierre
    assert llamadas[-1]["tools"] is None
    assert reasoning_loop._INSTRUCCION_CIERRE_DENEGACION in str(llamadas[-1]["messages"][-1])
    resultados = tool_history.pares_de(llamadas[-1]["messages"])
    assert len(resultados) == 2                               # D-6: la no ejecutada tiene resultado


def test_si_el_cierre_falla_tras_una_denegacion_queda_el_texto_literal():
    def ejecutar(nombre, params):
        raise ActionDenied("web_search", reason="no por Telegram")

    texto, _, _ = _resolver([
        LLMToolResponse(text=None, tool_calls=[_llamada("web_search", 0)]),
        LLMToolResponse(text="", tool_calls=[]),              # cierre vacío: no sirve
    ], ejecutar=ejecutar)

    assert texto == "No puedo ejecutar esa accion: no por Telegram."


def test_un_proveedor_sin_tool_calling_sigue_respondiendo_en_texto():
    texto, llamadas, ejecuciones = _resolver(["respuesta plana"])

    assert texto == "respuesta plana"
    assert len(llamadas) == 1 and ejecuciones == []


# ── CA-06: el botón de detener del escritorio no alcanza a Telegram ─

def test_un_turno_de_escritorio_cancelado_no_aborta_el_camino_remoto():
    turno = cancelacion.nuevo_turno()
    try:
        cancelacion.cancelar(turno)
        assert cancelacion.esta_cancelado()

        texto, _, ejecuciones = _resolver([
            LLMToolResponse(text=None, tool_calls=[_llamada("web_search", 0)]),
            LLMToolResponse(text="listo", tool_calls=[]),
        ])
    finally:
        cancelacion.cerrar_turno(turno)

    assert texto == "listo"
    assert len(ejecuciones) == 1


# ── CA-07: el historial por usuario sigue siendo texto ──────────────

def test_el_historial_por_usuario_no_recibe_bloques_de_herramientas():
    historia = list(HISTORIA)
    with patch("ai.llm_provider.generate_response", side_effect=[
            LLMToolResponse(text=None, tool_calls=[_llamada("web_search", 0)]),
            LLMToolResponse(text="listo", tool_calls=[]),
         ]), \
         patch("core.reasoning_loop.generate_response", return_value="no debería llegar acá"), \
         patch("agents.tool_registry.catalogo_para_modelo", return_value=CATALOGO), \
         patch("core.reasoning_loop.execute_tool", return_value="ok"):
        claude_brain._resolver_con_tools(
            history=historia, system_prompt="s", image_path=None, channel="telegram", user_id="u",
        )

    assert historia == HISTORIA
    assert all(isinstance(m["content"], str) for m in historia)


# ── CA-09: tope_de_salida ───────────────────────────────────────────

def test_el_tope_solo_vale_dentro_del_bloque_y_nunca_supera_el_general():
    assert llm_provider._max_tokens_salida() == llm_provider.MAX_TOKENS_SALIDA
    with llm_provider.tope_de_salida(500):
        assert llm_provider._max_tokens_salida() == 500
        with llm_provider.tope_de_salida(99999):
            assert llm_provider._max_tokens_salida() == llm_provider.MAX_TOKENS_SALIDA
        assert llm_provider._max_tokens_salida() == 500
    assert llm_provider._max_tokens_salida() == llm_provider.MAX_TOKENS_SALIDA


def test_el_tope_es_por_hilo():
    visto = {}

    def otro_hilo():
        visto["otro"] = llm_provider._max_tokens_salida()

    with llm_provider.tope_de_salida(500):
        hilo = threading.Thread(target=otro_hilo)
        hilo.start()
        hilo.join()

    assert visto["otro"] == llm_provider.MAX_TOKENS_SALIDA


def test_los_adaptadores_leen_el_tope_y_no_la_constante():
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent / "ai" / "llm_provider.py").read_text(encoding="utf-8")
    assert "max_tokens=MAX_TOKENS_SALIDA" not in fuente
    assert fuente.count("max_tokens=_max_tokens_salida()") >= 5
    # Gemini y Ollama no pasaban ningún techo: el tope de voz no valía para ellos.
    assert '"max_output_tokens": _max_tokens_salida()' in fuente
    assert '"num_predict": _max_tokens_salida()' in fuente


# ── CA-10 / CA-11: voz acotada, el resto no ─────────────────────────

def _correr_run(canal, respuestas):
    topes = []

    def fake_generate(messages, system_prompt, image_path=None, tools=None, tarea="general",
                      aviso=None):
        topes.append(llm_provider._max_tokens_salida())
        return respuestas[min(len(topes) - 1, len(respuestas) - 1)]

    with patch("core.reasoning_loop.generate_response", side_effect=fake_generate), \
         patch("core.reasoning_loop._load_prior_turns", return_value=[]), \
         patch("core.reasoning_loop.agent_context_manager"), \
         patch("core.reasoning_loop.execute_tool", return_value="ok"):
        reasoning_loop.run("qué hora es", canal, "u")
    return topes


def test_en_voz_la_respuesta_y_el_cierre_van_acotados():
    pide = LLMToolResponse(text=None, tool_calls=[_llamada("web_search", 0)])
    cierre = LLMToolResponse(text="son las tres", tool_calls=[])
    topes = _correr_run(ChannelType.VOICE, [pide] * 10 + [cierre])

    assert topes                                              # bucle + cierre
    assert all(t == reasoning_loop.MAX_TOKENS_VOZ for t in topes)


@pytest.mark.parametrize("canal", [ChannelType.DESKTOP, ChannelType.TELEGRAM])
def test_fuera_de_voz_el_tope_es_el_general(canal):
    topes = _correr_run(canal, [LLMToolResponse(text="listo", tool_calls=[])])

    assert topes == [llm_provider.MAX_TOKENS_SALIDA]


def test_el_tope_de_voz_esta_fijado():
    """Moverlo cambia cuánto habla el agente sin que nadie pueda cortarlo."""
    assert reasoning_loop.MAX_TOKENS_VOZ == 500
