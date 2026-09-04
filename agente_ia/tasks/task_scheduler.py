"""
tasks/task_scheduler.py
Scheduler de recordatorios para O.R.I.O.N..

Corre en un hilo background y cada 60 segundos revisa si hay tareas
cuyo remind_at ya pasó. Si las hay, envía la notificación por Telegram
(u otros canales en el futuro).

El scheduler es independiente del bot — se conecta vía callback.
"""

import asyncio
import threading
import time
import logging
from typing import Callable, Optional
from core.address import vocative, vocative_start

logging.basicConfig(
    format="%(asctime)s [Scheduler] %(levelname)s: %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TaskScheduler:
    """
    Revisa tareas pendientes cada CHECK_INTERVAL segundos
    y ejecuta callbacks para notificar al usuario.
    """

    CHECK_INTERVAL = 60  # segundos entre cada revisión

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._telegram_app = None  # Se inyecta después de que el bot arranca
        self._notify_callbacks: list[Callable] = []

    def set_telegram_app(self, app):
        """Inyecta la instancia del bot de Telegram para enviar mensajes."""
        self._telegram_app = app
        logger.info("Telegram app inyectada al scheduler")

    def add_notify_callback(self, callback: Callable):
        """Agrega un callback que se ejecuta cuando hay tareas pendientes."""
        self._notify_callbacks.append(callback)

    def start(self):
        """Inicia el scheduler en un hilo background."""
        if self._running:
            logger.warning("Scheduler ya está corriendo")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="TaskScheduler"
        )
        self._thread.start()
        logger.info("Scheduler de tareas iniciado (cada %ds)", self.CHECK_INTERVAL)

    def stop(self):
        """Detiene el scheduler."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Scheduler detenido")

    def _run_loop(self):
        """Loop principal del scheduler."""
        # Esperar un poco para que los bots arranquen primero
        time.sleep(10)
        logger.info("Scheduler activo — comenzando revisión periódica")

        while self._running:
            try:
                self._check_due_tasks()
            except Exception as e:
                logger.error(f"Error en ciclo del scheduler: {e}")

            time.sleep(self.CHECK_INTERVAL)

    def _check_due_tasks(self):
        """Revisa si hay tareas cuyo recordatorio debe enviarse."""
        from tasks.task_manager import task_manager

        due_tasks = task_manager.get_due_reminders()
        if not due_tasks:
            return

        logger.info(f"Encontradas {len(due_tasks)} tarea(s) pendiente(s) de notificación")

        for task in due_tasks:
            try:
                self._send_notification(task)
                task_manager.mark_notified(task["id"])

                # Si es recurrente, crear la siguiente ocurrencia
                if task.get("recurrence"):
                    task_manager.handle_recurrence(task)
                    logger.info(
                        f"Tarea recurrente #{task['id']} "
                        f"'{task['title']}' — próxima ocurrencia creada"
                    )
            except Exception as e:
                logger.error(
                    f"Error notificando tarea #{task['id']}: {e}"
                )

    def _send_notification(self, task: dict):
        """Envía la notificación de recordatorio al usuario."""
        channel = task.get("channel", "telegram")
        user_id = task.get("user_id", "")
        title = task.get("title", "Tarea sin título")
        task_id = task.get("id", "?")

        priority_icons = {
            "urgent": "🔴 URGENTE",
            "high": "🟠 Alta prioridad",
            "normal": "",
            "low": ""
        }
        priority_text = priority_icons.get(task.get("priority", ""), "")
        priority_line = f"\n{priority_text}" if priority_text else ""

        message = (
            f"⏰ *RECORDATORIO*{priority_line}\n\n"
            f"📋 *{title}*\n"
            f"🆔 Tarea #{task_id}\n\n"
            f"{vocative_start()}es momento de atender esta tarea.\n"
            f"Use /completar {task_id} cuando la finalice."
        )

        # Enviar por Telegram
        if channel == "telegram" and self._telegram_app:
            try:
                self._send_telegram_message(user_id, message)
                logger.info(f"Recordatorio enviado a {user_id}: {title}")
            except Exception as e:
                logger.error(f"Error enviando por Telegram: {e}")
        
        # Ejecutar callbacks adicionales
        for callback in self._notify_callbacks:
            try:
                callback(task, message)
            except Exception as e:
                logger.error(f"Error en callback de notificación: {e}")

        # Notificación local (TTS + Windows Toast)
        if channel == "desktop" or channel == "telegram":
            self._notify_local(title, task_id)

    def _notify_local(self, title: str, task_id):
        """Avisa de un recordatorio vencido: en voz, y por pantalla.

        El aviso visual va primero por el canal de la aplicación
        (`core/notificaciones.py`): si la ventana está abierta, el recordatorio aparece
        ahí, con el mismo aspecto que el resto de los avisos. El globo de Windows
        —levantar PowerShell para dibujarlo— queda SOLO para cuando no hay ventana
        escuchando: con la app abierta era un segundo aviso, del sistema, para lo mismo.
        """
        try:
            from ui.tts_engine import speak
            speak(f"{vocative_start()}recuerde: {title}")
        except Exception as e:
            # Antes esto era un `except: pass`: si el recordatorio no sonaba, no quedaba
            # rastro de por qué (va contra `.claude/rules/python-style.md`).
            logger.warning(f"no se pudo pronunciar el recordatorio '{title}': {e}")

        try:
            from core.notificaciones import hay_notificador, notificar

            notificar("Recordatorio", title, "info")
            if hay_notificador():
                return          # la ventana ya lo mostró; el globo del sistema sobra
        except Exception as e:
            logger.warning(f"no se pudo avisar del recordatorio '{title}': {e}")

        try:
            import subprocess
            ps_script = (
                f'[Windows.UI.Notifications.ToastNotificationManager,'
                f' Windows.UI.Notifications, ContentType=WindowsRuntime]::CreateToastNotifier("Noddoo").Show('
                f'(New-Object Windows.UI.Notifications.ToastNotification('
                f'[Windows.Data.Xml.Dom.XmlDocument]::LoadXml('
                f"'<toast><visual><binding template=\"ToastText02\"><text id=\"1\">⏰ RECORDATORIO</text>"
                f"<text id=\"2\">{title}</text></binding></visual></toast>'"
                f'))));'
                f'Start-Sleep -Seconds 5'
            )
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=10)
        except Exception as e:
            logger.warning(f"no se pudo mostrar el globo de Windows para '{title}': {e}")

    def _send_telegram_message(self, chat_id: str, text: str):
        """Envía un mensaje de Telegram mediante petición HTTP directa."""
        import requests
        import os
        import json
        from pathlib import Path
        
        # Recuperar token
        from config_manager import get_telegram_token
        token = get_telegram_token()

        if not token:
            logger.warning("No hay token de Telegram configurado para enviar recordatorios.")
            return
            
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        try:
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code != 200:
                logger.error(f"Error de Telegram API: {r.text}")
        except Exception as e:
            logger.error(f"Error enviando petición HTTP POST a Telegram: {e}")


# ── Instancia global ──────────────────────────────────────────────
task_scheduler = TaskScheduler()
