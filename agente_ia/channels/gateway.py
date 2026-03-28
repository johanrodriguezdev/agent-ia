"""
channels/gateway.py
Gateway central de Glass — aislamiento por usuario + acciones del PC.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


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
            from router.dispatcher import dispatch

            intent, params = classify_command(text)

            # Captura de pantalla → enviar como imagen al chat
            if intent == Intent.TAKE_SCREENSHOT:
                return self._handle_screenshot(session, text)

            # UNKNOWN → Claude Brain personalizado por usuario
            if intent == Intent.UNKNOWN:
                result = self._ask_claude_for_user(text, session)
            else:
                result = dispatch(intent, params)

            # Memoria aislada del usuario
            session.save_memory(text, result)

            try:
                self._save_semantic(session, text, result)
            except Exception:
                pass

            return GlassResponse(text=result, speak=True)

        except Exception as e:
            return GlassResponse(
                text=f"Lo siento, he encontrado un inconveniente: {str(e)[:80]}",
                speak=True
            )

    def _ask_claude_for_user(self, text: str, session) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return "Configure ANTHROPIC_API_KEY para activar la inteligencia conversacional, Señor."

        try:
            import anthropic
            import datetime
            from config_manager import get_agent_name

            agent = get_agent_name().upper()
            memory_context = session.get_memory_md()

            system = (
                f"Eres {agent}, asistente de IA personal formal tipo JARVIS. "
                f"Hablas siempre en español. Te diriges al usuario como 'Señor' o por su nombre.\n"
                f"Usuario: {session.user_name} | Canal: {session.channel}\n"
                f"Fecha: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            )
            if memory_context:
                system += f"\nPerfil del usuario:\n{memory_context}\n"

            session.add_to_history("user", text)

            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=system,
                messages=session.get_history()
            )
            result = response.content[0].text
            session.add_to_history("assistant", result)
            return result

        except ImportError:
            return "Instale la librería anthropic: pip install anthropic"
        except Exception as e:
            if session.conversation_history and session.conversation_history[-1]["role"] == "user":
                session.conversation_history.pop()
            return f"Error en inteligencia conversacional: {str(e)[:80]}"

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
                text="Aquí tiene la captura de pantalla, Señor.",
                speak=True,
                image_path=tmp_path
            )
        except Exception as e:
            return GlassResponse(
                text=f"No pude tomar la captura, Señor: {str(e)[:60]}",
                speak=True
            )

    def _save_semantic(self, session, text: str, result: str):
        try:
            import json
            import sqlite3
            from ai.embedding_engine import create_embedding

            content = f"Pregunta: {text} | Respuesta: {result}"
            embedding = create_embedding(content)
            conn = sqlite3.connect(str(session.sem_db_path))
            conn.execute(
                "INSERT INTO semantic_memories (text, embedding_json) VALUES (?, ?)",
                (content, json.dumps(embedding))
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
