"""
channels/gateway.py
Gateway central de Glass — aislamiento por usuario + acciones del PC.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from core.address import vocative, vocative_start

logger = logging.getLogger(__name__)


class MessageType(Enum):
    TEXT  = "text"
    VOICE = "voice"
    IMAGE = "image"
    FILE  = "file"


@dataclass
class GlassMessage:
    user_id:    str
    user_name:  str
    text:       str
    channel:    str
    msg_type:   MessageType = MessageType.TEXT
    audio_path: Optional[str] = None
    image_path: Optional[str] = None
    raw_data:   dict = field(default_factory=dict)


@dataclass
class GlassResponse:
    text:       str
    speak:      bool = True
    image_path: Optional[str] = None  # Captura de pantalla para enviar al chat
    audio_path: Optional[str] = None
    extra:      dict = field(default_factory=dict)


class GlassGateway:

    def process(self, message: GlassMessage) -> GlassResponse:
        """REQ-006/CA-01, CA-02: delega a `core/resolution.py:resolve()`, el punto único de
        resolución compartido con `main.py` y `core/orchestrator.py`. Reemplaza los tres
        métodos `_try_create_task`/`_try_list_tasks`/`_try_complete_task` que existían acá
        antes de este REQ (H3: llamaban a `tasks/task_manager.py` directo, sin pasar por
        ningún gate) — ese caso ahora vive en `core/resolution.py::_try_task_tool`, que
        resuelve vía `agents/tool_registry.py:execute_tool()` (gateado)."""
        from ai.user_manager import registry

        # Sesión aislada por usuario
        session = registry.get_or_create(
            user_id=message.user_id,
            user_name=message.user_name,
            channel=message.channel
        )

        text = message.text.strip()
        if not text:
            return GlassResponse(text="Dígame, estoy escuchando.", speak=True)

        try:
            from intent.classifier import classify_command
            from intent.intentions import Intent
            from core.resolution import resolve

            # Mensaje con imagen adjunta → Claude Brain personalizado por usuario, directo
            # (soporte de imágenes). Es una excepción legítima al orden uniforme de CA-03:
            # ningún resolver de `resolve()` (routine/autopilot/learned/task_tool/
            # capability/intent) sabe operar sobre una imagen, todos trabajan sobre `text`,
            # así que no hay orden que preservar acá — es un tipo de entrada distinto, no
            # un canal distinto.
            if message.msg_type == MessageType.IMAGE:
                result = self._ask_claude_for_user(message, session)
            else:
                # Captura de pantalla → enviar como imagen al chat (se preclasifica solo
                # para detectar este caso especial, igual que TEACH_COMMAND en main.py;
                # resolve() no conoce este feature de adjuntar imagen al chat de
                # Telegram/Discord). El resto del texto pasa por `resolve()` completo,
                # que desde la inversión es `pending_dialog → claude`: el mismo camino que
                # main.py (CA-03 sigue exigiendo que los tres canales resuelvan igual).
                # `classify_command()` sobrevive acá SOLO como preclasificación para este
                # caso especial — no decide la resolución, decide si la respuesta se manda
                # como imagen.
                pre_intent, _pre_params = classify_command(text)
                if pre_intent == Intent.TAKE_SCREENSHOT:
                    return self._handle_screenshot(session, text)

                resolution = resolve(
                    text, message.channel, message.user_id,
                    claude_fn=lambda t: self._ask_claude_for_user(message, session),
                )
                result = resolution.text

            # Memoria aislada del usuario
            session.save_memory(text, result)
            self._save_semantic(session, text, result)

            return GlassResponse(text=result, speak=True)

        except Exception as e:
            return GlassResponse(
                text=f"Lo siento, he encontrado un inconveniente: {str(e)[:80]}",
                speak=True
            )

    def _ask_claude_for_user(self, message: GlassMessage, session) -> str:
        text = message.text
        try:
            from ai.claude_brain import ask_claude

            if message.image_path and os.path.exists(message.image_path):
                if not text or len(text.strip()) < 2:
                    text = "Analiza en detalle esta imagen y dime todo lo que ves e investiga su contexto."
                else:
                    text = f"Analiza esta imagen con la siguiente petición: {text}. Investiga en profundidad y actúa como experto."

            session.add_to_history("user", text)

            result = ask_claude(
                user_message=text,
                user_id=message.user_id,
                user_name=session.user_name,
                channel=message.channel,
                image_path=message.image_path or "",
            )

            session.add_to_history("assistant", result)
            return result

        except Exception as e:
            if session.conversation_history and session.conversation_history[-1]["role"] == "user":
                session.conversation_history.pop()
            return f"Error en inteligencia conversacional: {str(e)}"

    def _handle_screenshot(self, session, text: str) -> GlassResponse:
        """Toma captura y la devuelve para enviar como imagen en Telegram."""
        try:
            import pyautogui
            import tempfile
            import time

            time.sleep(1.5)
            screenshot = pyautogui.screenshot()

            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False, prefix="glass_cap_"
            ) as f:
                tmp_path = f.name

            screenshot.save(tmp_path)
            session.save_memory(text, "Captura de pantalla enviada al chat")

            return GlassResponse(
                text=f"Aquí tiene la captura de pantalla{vocative()}.",
                speak=True,
                image_path=tmp_path
            )
        except Exception as e:
            return GlassResponse(
                text=f"No pude tomar la captura{vocative()}: {str(e)[:60]}",
                speak=True
            )

    def _save_semantic(self, session, text: str, result: str):
        try:
            from ai.memory_manager import memory
            content = f"Pregunta: {text} | Respuesta: {result}"
            memory.store(content, user_id=session.user_id, category="semantic", importance=0.5)
        except Exception as e:
            logger.warning(f"Error guardando memoria semántica: {e}")
