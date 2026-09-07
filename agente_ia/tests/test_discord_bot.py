"""
tests/test_discord_bot.py
Cobertura REQ-025: logging + saneamiento del error filtrado en _process_message().
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from channels.discord_bot import _get_agent_name, _process_message


class TestProcessMessageErrorHandling:
    def test_loguea_error_con_exc_info_y_contexto(self, caplog):
        """CA: logger.error con exc_info=True, incluye user_id, user_name, canal=discord."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError(
                "fuga-interna-marca-XYZ"
            )
            with caplog.at_level(logging.ERROR):
                _process_message("u1", "Johan", "hola")
        assert any("fuga-interna-marca-XYZ" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)
        assert any(
            "usuario=u1" in r.message and "Johan" in r.message and "canal=discord" in r.message
            for r in caplog.records
        )

    def test_retorno_sin_fragmentos_del_error(self):
        """CA: el string retornado no contiene ningún fragmento de str(e)."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError(
                "/ruta/absoluta/secreta/del/disco"
            )
            result = _process_message("u1", "Johan", "hola")
        assert "/ruta/absoluta/secreta/del/disco" not in result

    def test_texto_generico_exacto(self):
        """CA: el texto genérico devuelto es exactamente el fijado en SPEC-025."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = ValueError("boom")
            result = _process_message("u2", "Ana", "algo")
        assert result == (
            "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
        )

    def test_camino_feliz_sin_cambios(self):
        """No-regresión: sin excepción, _process_message() retorna response.text normal."""
        mock_response = MagicMock(text="respuesta normal")
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.return_value = mock_response
            result = _process_message("u1", "Johan", "hola")
        assert result == "respuesta normal"

    def test_str_error_vacio_igual_loguea_con_exc_info(self, caplog):
        """Caso borde: str(e) vacío — el log igual muestra el tipo vía exc_info=True."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError()
            with caplog.at_level(logging.ERROR):
                result = _process_message("u1", "Johan", "hola")
        assert any(r.exc_info for r in caplog.records)
        assert result == (
            "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
        )

    def test_user_name_con_caracteres_especiales_no_rompe(self):
        """Caso borde: user_name con emoji no rompe el log ni el retorno (f-string Unicode)."""
        with patch("channels.gateway.GlassGateway") as mock_gateway_cls:
            mock_gateway_cls.return_value.process.side_effect = RuntimeError("boom")
            result = _process_message("u3", "Ana 🎉", "hola")
        assert result == (
            "Lo siento, he encontrado un inconveniente inesperado. Intente de nuevo en un momento."
        )


class TestOtrosExceptSinModificar:
    def test_get_agent_name_no_modificado(self):
        """No-alcance: _get_agent_name() (línea 52) sigue devolviendo NODDOO por defecto en
        error, sin log nuevo — confirma que este REQ no tocó ese bloque."""
        with patch("config_manager.load_config", side_effect=RuntimeError("boom")):
            assert _get_agent_name() == "NODDOO"
