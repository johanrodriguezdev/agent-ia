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
            # ── Detectar tareas/recordatorios en conversación natural ──
            task_result = self._try_create_task(message, session)
            if task_result:
                return task_result

            # ── Detectar consulta de tareas pendientes/listado ──
            list_result = self._try_list_tasks(message, session)
            if list_result:
                return list_result

            # ── Detectar finalización de tareas ──
            complete_result = self._try_complete_task(message, session)
            if complete_result:
                return complete_result

            from intent.classifier import classify_command
            from intent.intentions import Intent
            from router.dispatcher import dispatch
            from core.orchestrator import orchestrator

            intent, params = classify_command(text)

            # Captura de pantalla → enviar como imagen al chat
            if intent == Intent.TAKE_SCREENSHOT:
                return self._handle_screenshot(session, text)

            # UNKNOWN → Claude Brain personalizado por usuario
            if intent == Intent.UNKNOWN or message.msg_type == MessageType.IMAGE:
                result = self._ask_claude_for_user(message, session)
            else:
                params["channel"] = message.channel
                result = orchestrator.process_task(
                    text=text,
                    channel=message.channel,
                    user_id=message.user_id
                )

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

    def _try_create_task(self, message: GlassMessage, session) -> 'GlassResponse | None':
        """
        Detecta si el mensaje del usuario es una solicitud de tarea/recordatorio.
        Si lo es, crea la tarea y retorna una GlassResponse con la confirmación.
        Si no, retorna None para que el flujo normal continúe.
        """
        text_lower = message.text.lower().strip()

        # Triggers que indican intención de tarea
        task_triggers = [
            "recuérdame", "recuerdame", "recordarme", "recordatorio",
            "agrega tarea", "agregar tarea", "nueva tarea", "crear tarea",
            "no olvidar", "no olvides", "pendiente:", "tarea:"
        ]

        # Triggers que podrían ser tarea pero necesitan confirmación
        # (como "tengo que" o "debo") — estos los dejamos para el LLM
        is_explicit_task = any(trigger in text_lower for trigger in task_triggers)
        if not is_explicit_task:
            return None

        try:
            from tasks.task_manager import task_manager
            result = task_manager.create_from_natural(
                message.text,
                user_id=message.user_id,
                channel=message.channel
            )
            if result:
                confirmation = task_manager.format_task_created(result)
                # Guardar en memoria del usuario
                session.save_memory(message.text, confirmation)
                return GlassResponse(text=confirmation, speak=True)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error creando tarea: {e}")

        return None

    def _try_list_tasks(self, message: GlassMessage, session) -> 'GlassResponse | None':
        """Detecta si el usuario pide ver sus tareas."""
        text_lower = message.text.lower().strip()
        triggers = ["mis tareas", "tareas pendientes", "tareas programadas", "listado de tareas", "lista de tareas", "ver tareas", "qué tareas", "que tareas", "dime mis tareas", "cuáles son mis tareas", "cuales son mis tareas"]
        
        if any(trigger in text_lower for trigger in triggers):
            try:
                from tasks.task_manager import task_manager
                summary = task_manager.get_task_summary(message.user_id)
                session.save_memory(message.text, summary)
                return GlassResponse(text=summary, speak=True)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error listando tareas: {e}")
        return None

    def _try_complete_task(self, message: GlassMessage, session) -> 'GlassResponse | None':
        """Detecta si el usuario está indicando que completó una tarea."""
        text_lower = message.text.lower().strip()
        triggers = ["ya complete la tarea", "ya completé la tarea", "tarea terminada", "tarea completada", "marcar tarea", "ya termine la tarea", "ya terminé la tarea", "listo complete la tarea", "listo termine la tarea"]
        
        is_complete = any(trigger in text_lower for trigger in triggers)
        if not is_complete:
            # Revisa variaciones con "listo" y "tarea"
            if ("tarea" in text_lower or "recordatorio" in text_lower) and ("listo" in text_lower or "hecho" in text_lower or "completad" in text_lower or "terminad" in text_lower):
                is_complete = True
                
        if not is_complete:
            return None
            
        try:
            import re
            from tasks.task_manager import task_manager
            
            # Buscar si el usuario mencionó un ID (ej: "tarea 5")
            match = re.search(r'(?:tarea|numero|número|id)\s*#?(\d+)', text_lower)
            task_id = int(match.group(1)) if match else None
            
            if task_id is not None:
                success = task_manager.complete_task(task_id, message.user_id)
                if success:
                    resp = f"☑️ *Excelente, Señor.* He marcado la tarea #{task_id} como completada."
                else:
                    resp = f"No encontré ninguna tarea pendiente con el ID #{task_id}, Señor."
                session.save_memory(message.text, resp)
                return GlassResponse(text=resp, speak=True)
                
            # Si no hay ID, buscar cuántas pendientes tiene
            pending_tasks = task_manager.list_tasks(message.user_id, status="pending")
            
            if not pending_tasks:
                resp = "No tiene ninguna tarea pendiente en este momento, Señor."
                session.save_memory(message.text, resp)
                return GlassResponse(text=resp, speak=True)
                
            if len(pending_tasks) == 1:
                # ¡Magia! Solo hay una, completarla automáticamente
                task = pending_tasks[0]
                task_manager.complete_task(task["id"], message.user_id)
                resp = f"☑️ *¡Trabajo terminado!* He deducido que se refería a la tarea *'{task['title']}'* y la he marcado como completada."
                session.save_memory(message.text, resp)
                return GlassResponse(text=resp, speak=True)
                
            # Si hay más de una, pedir aclaración
            resp = "He notado que tiene varias tareas pendientes, Señor. ¿Podría indicarme el número de la tarea que completó? (Ej: 'listo tarea 2')\n\nSus tareas pendientes:\n"
            for t in pending_tasks:
                resp += f"• #{t['id']} - {t['title']}\n"
            session.save_memory(message.text, resp)
            return GlassResponse(text=resp, speak=True)
            
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error completando tarea: {e}")
            
        return None

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
            from ai.memory_manager import memory
            content = f"Pregunta: {text} | Respuesta: {result}"
            memory.store(content, user_id=session.user_id, category="semantic", importance=0.5)
        except Exception:
            pass
