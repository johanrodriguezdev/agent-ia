"""
tests/test_claude_brain.py

Cobertura de `ai/claude_brain.py::_resolver_con_tools()` — el segundo punto de ensamblado
de la respuesta del agente (Telegram/Discord), en paralelo a `core/reasoning_loop.py::run()`
para el escritorio/voz.

Este módulo no tenía NINGÚN test propio en el repo antes de este archivo — confirmado en
`test-results-022.md` (hallazgo de orion-tester, "hallazgo agravado"): ni siquiera existía
`tests/test_claude_brain.py`. Se crea ahora, con la cobertura mínima que pide
`.claude/rules/testing.md` para el CA-15 de REQ-022 (el aviso de cambio de modelo también
se propaga en este camino, con el mismo mecanismo que `reasoning_loop.run()`).

Convenciones (.claude/rules/testing.md): sin red — `generate_response`/`execute_tool`/
`catalogo_para_modelo` siempre mockeados, este módulo nunca debe golpear un proveedor LLM
real ni ejecutar una tool real en tests.
"""
from unittest.mock import patch

from ai import claude_brain


def _fake_generate_response_con_aviso(aviso_a_rellenar):
    """`generate_response(..., aviso=un_dict_vacio)` en la vida real RELLENA ese dict
    in-place cuando hubo un swap de proveedor. Este fake reproduce ese contrato — mismo
    patrón que `tests/test_reasoning_loop.py`."""

    def _fake(*args, **kwargs):
        aviso = kwargs.get("aviso")
        if aviso is not None:
            aviso.update(aviso_a_rellenar)
        return "la respuesta es 42"

    return _fake


def test_ca15_el_aviso_de_cambio_se_propaga_igual_que_en_reasoning_loop():
    """REQ-022/CA-15: `_resolver_con_tools()` usa el mismo `con_aviso_de_cambio()`/
    `generate_response(..., aviso=...)` que `reasoning_loop.run()` — el mismo aviso de
    cambio de modelo tiene que quedar en el texto final por este camino también
    (Telegram/Discord), no solo por escritorio."""
    aviso = {
        "proveedor_desde": "deepseek", "modelo_desde": "deepseek-chat",
        "proveedor_hacia": "openrouter", "modelo_hacia": "openrouter/free",
    }
    fake_gen = _fake_generate_response_con_aviso(aviso)

    with patch("ai.llm_provider.generate_response", side_effect=fake_gen) as mock_gen, \
         patch("agents.tool_registry.catalogo_para_modelo", return_value=[]), \
         patch("agents.tool_registry.execute_tool") as mock_exec:
        resultado = claude_brain._resolver_con_tools(
            history=[{"role": "user", "content": "cuánto es 6x7"}],
            system_prompt="system", image_path=None, channel="telegram", user_id="u1",
        )

    assert resultado == (
        "la respuesta es 42\n\n"
        "Cambié a openrouter (openrouter/free) porque deepseek (deepseek-chat) no respondió."
    )
    mock_gen.assert_called_once()
    mock_exec.assert_not_called()


def test_ca15_sin_cambio_de_destino_el_texto_no_lleva_aviso():
    """Contracara de CA-13 en este mismo camino: sin swap, el texto no gana ninguna línea."""
    fake_gen = _fake_generate_response_con_aviso({})

    with patch("ai.llm_provider.generate_response", side_effect=fake_gen), \
         patch("agents.tool_registry.catalogo_para_modelo", return_value=[]), \
         patch("agents.tool_registry.execute_tool"):
        resultado = claude_brain._resolver_con_tools(
            history=[{"role": "user", "content": "cuánto es 6x7"}],
            system_prompt="system", image_path=None, channel="discord", user_id="u1",
        )

    assert resultado == "la respuesta es 42"
    assert "Cambié" not in resultado
