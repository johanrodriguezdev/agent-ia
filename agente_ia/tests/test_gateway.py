"""
tests/test_gateway.py
Cobertura REQ-024: logging + saneamiento de errores en GlassGateway.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from channels.gateway import GlassGateway, GlassMessage, MessageType


def _make_message(text="hola", msg_type=MessageType.TEXT, **kw):
    return GlassMessage(
        user_id="u1", user_name="Johan", text=text, channel="telegram",
        msg_type=msg_type, **kw
    )


class TestProcessErrorHandling:
    def test_process_loguea_error_con_exc_info(self, caplog):
        """CA: process() loguea con exc_info=True, usuario y canal, mensaje original."""
        gateway = GlassGateway()
        msg = _make_message(text="algo")
        session = MagicMock()
        with patch("ai.user_manager.registry.get_or_create", return_value=session), \
             patch("intent.classifier.classify_command", return_value=(None, {})), \
             patch("core.resolution.resolve", side_effect=RuntimeError("fuga-interna-marca-XYZ")):
            with caplog.at_level(logging.ERROR):
                gateway.process(msg)
        assert any("fuga-interna-marca-XYZ" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)
        assert any("usuario=u1" in r.message and "canal=telegram" in r.message
                    for r in caplog.records)

    def test_process_respuesta_sin_fragmentos_del_error(self):
        """CA: GlassResponse.text no contiene ningún fragmento de str(e)."""
        gateway = GlassGateway()
        msg = _make_message(text="algo")
        session = MagicMock()
        with patch("ai.user_manager.registry.get_or_create", return_value=session), \
             patch("intent.classifier.classify_command", return_value=(None, {})), \
             patch("core.resolution.resolve",
                    side_effect=RuntimeError("/ruta/absoluta/secreta/del/disco")):
            resp = gateway.process(msg)
        assert "/ruta/absoluta/secreta/del/disco" not in resp.text
        assert resp.text == (
            "Lo siento, he encontrado un inconveniente inesperado. "
            "Intente de nuevo en un momento."
        )

    def test_process_camino_feliz_sin_cambios(self):
        """No-regresión: sin excepción, process() responde con el resultado normal."""
        gateway = GlassGateway()
        msg = _make_message(text="hola")
        session = MagicMock()
        with patch("ai.user_manager.registry.get_or_create", return_value=session), \
             patch("intent.classifier.classify_command", return_value=(None, {})), \
             patch("core.resolution.resolve") as mock_resolve, \
             patch.object(GlassGateway, "_save_semantic"):
            mock_resolve.return_value = MagicMock(text="respuesta normal")
            resp = gateway.process(msg)
        assert resp.text == "respuesta normal"


class TestAskClaudeForUserErrorHandling:
    def test_loguea_error_con_exc_info(self, caplog):
        gateway = GlassGateway()
        msg = _make_message(msg_type=MessageType.IMAGE)
        session = MagicMock(conversation_history=[])
        with patch("ai.claude_brain.ask_claude", side_effect=RuntimeError("marca-ABC")):
            with caplog.at_level(logging.ERROR):
                gateway._ask_claude_for_user(msg, session)
        assert any("marca-ABC" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)

    def test_respuesta_sin_fragmentos_del_error(self):
        gateway = GlassGateway()
        msg = _make_message(msg_type=MessageType.IMAGE)
        session = MagicMock(conversation_history=[])
        with patch("ai.claude_brain.ask_claude", side_effect=RuntimeError("dato-interno-123")):
            result = gateway._ask_claude_for_user(msg, session)
        assert "dato-interno-123" not in result
        assert result == "Lo siento, no pude procesar esa solicitud en este momento. Intente de nuevo."

    def test_pop_de_historial_se_conserva(self):
        """No-regresión: la guarda de pop() sigue funcionando igual (lista real, sin mock)."""
        gateway = GlassGateway()
        msg = _make_message(msg_type=MessageType.IMAGE)
        session = MagicMock(conversation_history=[{"role": "user", "content": "x"}])
        with patch("ai.claude_brain.ask_claude", side_effect=RuntimeError("boom")):
            gateway._ask_claude_for_user(msg, session)
        assert session.conversation_history == []


class TestHandleScreenshotErrorHandling:
    def test_loguea_error_con_exc_info(self, caplog):
        gateway = GlassGateway()
        session = MagicMock(user_id="u1", channel="discord")
        with patch("pyautogui.screenshot", side_effect=RuntimeError("marca-DEF")):
            with caplog.at_level(logging.ERROR):
                gateway._handle_screenshot(session, "captura")
        assert any("marca-DEF" in r.message for r in caplog.records)
        assert any(r.exc_info for r in caplog.records)

    def test_respuesta_sin_fragmentos_del_error_y_conserva_vocative(self):
        gateway = GlassGateway()
        session = MagicMock(user_id="u1", channel="discord")
        with patch("pyautogui.screenshot", side_effect=RuntimeError("/tmp/ruta-secreta")):
            resp = gateway._handle_screenshot(session, "captura")
        assert "/tmp/ruta-secreta" not in resp.text
        assert "No pude tomar la captura" in resp.text
        assert "Intente de nuevo en un momento." in resp.text


class TestSaveSemanticNoRegression:
    def test_save_semantic_sigue_usando_warning(self, caplog):
        """No-regresión: _save_semantic() no se toca, sigue con logger.warning."""
        gateway = GlassGateway()
        session = MagicMock(user_id="u1")
        with patch("ai.memory_manager.memory.store", side_effect=RuntimeError("x")):
            with caplog.at_level(logging.WARNING):
                gateway._save_semantic(session, "texto", "resultado")
        assert any(r.levelname == "WARNING" for r in caplog.records)
