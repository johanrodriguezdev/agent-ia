import logging
import threading
import time
from typing import Dict, Callable, List
from datetime import datetime, time as dt_time

from core.base_agent import BaseAgent
from core.security_manager import security_manager, ChannelType

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 60


class ProactiveTrigger:
    def __init__(self, agent: BaseAgent, schedule: str, action: str, user_id: str = "default"):
        self.agent = agent
        self.schedule = schedule
        self.action = action
        self.user_id = user_id
        self.last_fired = None
        self.active = True


class ProactiveEngine:
    def __init__(self):
        self._triggers: List[ProactiveTrigger] = []
        self._running = False
        self._thread: threading.Thread = None
        self._global_active = True
        self._notify_callback: Callable = None
        # Los triggers dejaron de registrarse solo al arrancar: un flujo programado se
        # puede crear en caliente mientras el bucle está recorriendo la lista. Modificar
        # una lista mientras otro hilo la itera es corrupción silenciosa, así que toda
        # lectura y escritura de `_triggers` pasa por acá.
        self._lock = threading.RLock()

    def set_notify_callback(self, callback: Callable):
        self._notify_callback = callback

    def register_trigger(self, agent: BaseAgent, schedule: str, action: str,
                         user_id: str = "default") -> ProactiveTrigger:
        trigger = ProactiveTrigger(agent, schedule, action, user_id)
        with self._lock:
            self._triggers.append(trigger)
        logger.info(f"Trigger proactivo registrado: {agent.name} @ {schedule}")
        return trigger

    def unregister_trigger(self, agent_name: str) -> int:
        """Quita los triggers de `agent_name`. Return cuántos se quitaron.

        Hace falta para que un flujo cancelado o borrado deje de dispararse sin esperar a
        que se reinicie la app.
        """
        with self._lock:
            antes = len(self._triggers)
            self._triggers = [t for t in self._triggers if t.agent.name != agent_name]
            quitados = antes - len(self._triggers)
        if quitados:
            logger.info(f"Triggers de '{agent_name}' dados de baja: {quitados}")
        return quitados

    def triggers_activos(self) -> List[ProactiveTrigger]:
        """Copia de la lista, para iterar sin bloquear ni exponer el estado interno."""
        with self._lock:
            return list(self._triggers)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ProactiveEngine")
        self._thread.start()
        logger.info("ProactiveEngine iniciado")

    def stop(self):
        self._running = False
        logger.info("ProactiveEngine detenido")

    @property
    def is_active(self) -> bool:
        return self._global_active

    @is_active.setter
    def is_active(self, value: bool):
        self._global_active = value
        logger.info(f"Proactividad global {'activada' if value else 'desactivada'}")

    def _run_loop(self):
        time.sleep(15)
        logger.info(f"ProactiveEngine activo — {len(self._triggers)} triggers registrados")

        while self._running:
            try:
                if self._global_active:
                    self._check_triggers()
            except Exception as e:
                logger.error(f"Error en ciclo proactivo: {e}")
            time.sleep(CHECK_INTERVAL)

    def _check_triggers(self):
        now = datetime.now()

        # Se itera una copia: un flujo programado puede registrarse mientras esto corre.
        for trigger in self.triggers_activos():
            if not trigger.active:
                continue

            if not self._should_fire(trigger, now):
                continue

            if trigger.last_fired and (now - trigger.last_fired).total_seconds() < 300:
                continue

            logger.info(f"Trigger proactivo disparado: {trigger.agent.name} - {trigger.action}")
            action_key = "proactive_trigger"

            if not security_manager.is_action_allowed(action_key, ChannelType.DESKTOP):
                logger.warning(f"Acción proactiva bloqueada por seguridad: {action_key}")
                continue

            try:
                result = trigger.agent.execute(trigger.action, {
                    "proactive": True,
                    "user_id": trigger.user_id
                })

                if self._notify_callback:
                    self._notify_callback(result)

                trigger.last_fired = now
                logger.info(f"Acción proactiva completada: {trigger.action[:60]}")
            except Exception as e:
                logger.error(f"Error en acción proactiva '{trigger.action}': {e}")

    def _should_fire(self, trigger: ProactiveTrigger, now: datetime) -> bool:
        sched = trigger.schedule.lower().strip()

        if sched == "startup":
            return trigger.last_fired is None

        if sched == "hourly":
            return trigger.last_fired is None or (now - trigger.last_fired).total_seconds() >= 3600

        if sched.startswith("daily:"):
            try:
                # `sched.split(":")` sobre "daily:08:00" da ['daily','08','00'], así que
                # `[1]` ya es la hora sola y volver a partirla por ":" devolvía una lista
                # de un elemento: el desempaquetado a dos variables lanzaba ValueError, el
                # `except` de abajo se lo tragaba, y este `return False` hacía que NINGÚN
                # trigger diario disparara nunca. Se toman las dos partes de una vez.
                _, hour, minute = sched.split(":", 2)
                target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)

                if trigger.last_fired:
                    if trigger.last_fired.date() == now.date():
                        return False

                elapsed = (now - target).total_seconds()
                return 0 <= elapsed < CHECK_INTERVAL
            except (ValueError, IndexError):
                return False

        return False


proactive_engine = ProactiveEngine()
