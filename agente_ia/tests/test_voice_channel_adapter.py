"""
tests/test_voice_channel_adapter.py
REQ-048 — el modo consola por voz (canal VOICE) confirma hablando, y las herramientas MCP
se pueden habilitar para voz.

Lo que protege esta suite:
- Solo «confirmo» autoriza; silencio, «sí», un rechazo, un fallo del TTS o del micrófono
  deniegan (mismo criterio que el manos libres del escritorio).
- La pregunta se pronuncia ANTES de escuchar, e incluye qué se va a hacer — para una
  herramienta MCP, con su nombre y su servidor.
- `main.py` registra el adaptador para `ChannelType.VOICE`.
- En el escritorio con manos libres, una herramienta MCP (amarilla) se confirma hablando,
  no con el modal: ya funcionaba por el canal escritorio, y queda fijado.

Sin micrófono ni altavoces: `hablar`/`escuchar` se inyectan.
"""

from unittest.mock import MagicMock, patch

import pytest

from voice.voice_channel_adapter import VoiceChannelConfirmationAdapter


def _adapter(respuesta, hablado=None, hablar_falla=False, escuchar_falla=False):
    hablado = hablado if hablado is not None else []

    def hablar(texto):
        if hablar_falla:
            raise RuntimeError("sin altavoz")
        hablado.append(texto)

    def escuchar():
        if escuchar_falla:
            raise RuntimeError("sin micrófono")
        return respuesta

    return VoiceChannelConfirmationAdapter(hablar=hablar, escuchar=escuchar), hablado


@pytest.mark.parametrize("dicho", ["confirmo", "eh, confirmo", "Confirmado"])
def test_solo_confirmo_autoriza(dicho):
    adapter, _ = _adapter(dicho)
    assert adapter.confirm("mcp__notion__search", "") is True


@pytest.mark.parametrize("dicho", ["sí", "si", "dale", "", "   ", "no", "cancela", "confirmar mañana no"])
def test_todo_lo_demas_deniega(dicho):
    adapter, _ = _adapter(dicho)
    assert adapter.confirm("mcp__notion__search", "") is False


def test_la_pregunta_se_pronuncia_antes_de_escuchar_y_dice_que_se_va_a_hacer():
    orden = []

    def hablar(texto):
        orden.append(("habla", texto))

    def escuchar():
        orden.append(("escucha", None))
        return "confirmo"

    adapter = VoiceChannelConfirmationAdapter(hablar=hablar, escuchar=escuchar)
    assert adapter.confirm("mcp__notion__search", "") is True

    assert [o[0] for o in orden] == ["habla", "escucha"]
    pregunta = orden[0][1]
    assert "search" in pregunta and "notion" in pregunta
    assert "confirmo" in pregunta


def test_si_falla_el_tts_deniega_sin_escuchar():
    escuchado = []
    adapter = VoiceChannelConfirmationAdapter(
        hablar=lambda t: (_ for _ in ()).throw(RuntimeError("sin altavoz")),
        escuchar=lambda: escuchado.append(1) or "confirmo",
    )
    assert adapter.confirm("accion", "") is False
    assert escuchado == []


def test_si_falla_el_microfono_deniega():
    adapter, _ = _adapter("confirmo", escuchar_falla=True)
    assert adapter.confirm("accion", "") is False


def test_main_registra_el_adaptador_para_el_canal_voz():
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    assert "register_confirmation_adapter(ChannelType.VOICE, voice_channel_confirmation_adapter.confirm)" in fuente


def test_voz_es_habilitable_para_mcp():
    from core.mcp_config import CANALES_HABILITABLES

    assert "voice" in CANALES_HABILITABLES


def test_en_manos_libres_del_escritorio_una_herramienta_mcp_se_confirma_hablando():
    """El pedido por voz en la app corre como canal ESCRITORIO: el adaptador del webview
    pregunta hablando cuando el manos libres está activo. Una herramienta MCP (amarilla)
    va por ese camino, no por el modal."""
    from ui.webview.confirmation_adapter import WebViewConfirmationAdapter

    bridge = MagicMock()
    bridge._hands_free_active.return_value = True
    adapter = WebViewConfirmationAdapter(bridge)

    with patch.object(adapter, "_confirmar_hablando", return_value=True) as hablado:
        resultado = adapter.confirm("mcp__notion__search", "¿Quiere que use search?")

    assert resultado is True
    hablado.assert_called_once()
    bridge.confirmation_requested.emit.assert_not_called()     # nada de modal
