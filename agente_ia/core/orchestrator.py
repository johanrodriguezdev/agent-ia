import logging
import re
import time
from typing import Dict, List, Optional
from core.base_agent import BaseAgent, DynamicAgentFactory
from core.agent_context import agent_context_manager

logger = logging.getLogger(__name__)

MAX_CHAIN_DEPTH = 5
AGENT_TIMEOUT = 30

_DECOMPOSE_TRIGGERS = [
    "y", "luego", "después", "además", "también",
    "al mismo tiempo", "mientras", "and", "then",
]


class AgentOrchestrator:
    def __init__(self):
        self._factory = DynamicAgentFactory()
        self._legacy_dispatcher = None
        self._classifier = None
        self._claude_brain = None

    def register_legacy_dispatcher(self, dispatch_func):
        self._legacy_dispatcher = dispatch_func
        logger.info("Dispatcher legacy registrado en orquestador")

    def register_classifier(self, classifier_func):
        self._classifier = classifier_func

    def register_claude_brain(self, claude_func):
        self._claude_brain = claude_func

    def process_task(self, text: str, channel: str = "desktop", user_id: str = "default") -> str:
        """REQ-006/CA-01: delega al punto único de resolución (`core/resolution.py`) en vez
        de la cascada `_try_quick_dispatch` → `_process_with_agents` que tenía antes de este
        REQ. `_try_quick_dispatch`, `_process_with_agents` y el resto de métodos de esta
        clase se conservan sin cambios: `_try_quick_dispatch` sigue siendo invocado
        directamente por callers que necesitan clasificar/despachar con un
        classifier/dispatcher inyectado sin pasar por `resolve()` (ver
        `tests/test_security_manager.py::test_extract_params_channel_key_ignored_by_gate`),
        y `_process_with_agents`/`_execute_single_agent`/`_execute_agent_chain` quedan
        disponibles para uso directo por quien los necesite explícitamente."""
        start = time.time()
        logger.info(f"Orquestador procesando tarea (canal={channel}, user={user_id}): {text[:80]}")

        from core.resolution import resolve
        result = resolve(text, channel, user_id, claude_fn=self.fallback_to_claude)

        elapsed = time.time() - start
        logger.info(f"Tarea resuelta via '{result.matched_by}' en {elapsed:.2f}s")
        return result.text

    def _try_quick_dispatch(self, text: str, channel: str, user_id: str) -> Optional[str]:
        if not self._classifier or not self._legacy_dispatcher:
            return None

        try:
            from intent.intentions import Intent
            intent, params = self._classifier(text)
            params["channel"] = channel

            if intent == Intent.UNKNOWN:
                return None

            handler = self._legacy_dispatcher(intent, params)
            agent_context_manager.update_context("orchestrator", user_id, {
                "role": "user", "content": text,
                "dispatch": intent.value
            })
            agent_context_manager.update_context("orchestrator", user_id, {
                "role": "assistant", "content": handler[:100]
            })
            return handler
        except Exception as e:
            logger.debug(f"Quick dispatch falló: {e}")
            return None

    def _process_with_agents(self, text: str, channel: str, user_id: str) -> str:
        subtasks = self._decompose(text)
        if len(subtasks) <= 1:
            return self._execute_single_agent(text, channel, user_id)

        if len(subtasks) > MAX_CHAIN_DEPTH:
            logger.warning(f"Tarea descompuesta en {len(subtasks)} pasos, limitando a {MAX_CHAIN_DEPTH}")
            subtasks = subtasks[:MAX_CHAIN_DEPTH]

        return self._execute_agent_chain(subtasks, channel, user_id)

    def _decompose(self, text: str) -> List[str]:
        """CA-12: fix del bug de substring (p.ej. "y" matcheando dentro de "hoy") — usa
        `\\b` word boundary vía regex y un safety net (`len(p) > 3`) para no partir en
        fragmentos vacíos o triviales."""
        for trigger in _DECOMPOSE_TRIGGERS:
            pattern = r'\b' + re.escape(trigger) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                parts = [p.strip() for p in re.split(pattern, text, flags=re.IGNORECASE) if p.strip()]
                if len(parts) >= 2 and all(len(p) > 3 for p in parts):
                    logger.info(f"Tarea descompuesta en {len(parts)} sub-tareas vía '{trigger}'")
                    return parts
        return [text]

    def _execute_single_agent(self, task: str, channel: str, user_id: str) -> str:
        agent = self._factory.create_agent(task, [])
        agent_context_manager.update_context(agent.name, user_id, {
            "role": "user", "content": task
        })

        context_data = {
            "conversation": agent_context_manager.get_context(agent.name, user_id).conversation[-5:],
            "channel": channel,
            "user_id": user_id
        }

        result = agent.execute(task, context_data)
        agent_context_manager.update_context(agent.name, user_id, {
            "role": "assistant", "content": result[:200]
        })
        return result

    def _execute_agent_chain(self, subtasks: List[str], channel: str, user_id: str) -> str:
        previous_result = None
        final_result = ""

        for i, subtask in enumerate(subtasks):
            enriched_task = subtask
            if previous_result:
                enriched_task = f"{subtask}\n\nResultado previo: {previous_result}"

            agent = self._factory.create_agent(enriched_task, [])
            context_data = {
                "channel": channel,
                "user_id": user_id,
                "step": i + 1,
                "total_steps": len(subtasks),
                "previous_result": previous_result
            }

            step_result = agent.execute(enriched_task, context_data)
            final_result = step_result

            agent_context_manager.update_context(agent.name, user_id, {
                "role": "user", "content": subtask
            })
            agent_context_manager.update_context(agent.name, user_id, {
                "role": "assistant", "content": step_result[:200]
            })

            msg = agent.communicate(step_result, f"agent_step_{i+2}" if i + 1 < len(subtasks) else "final")
            previous_result = msg["result"]

        return final_result

    def fallback_to_claude(self, text: str) -> str:
        if self._claude_brain:
            try:
                logger.info("Usando Claude Brain como fallback")
                return self._claude_brain(text)
            except Exception as e:
                logger.error(f"Claude Brain falló: {e}")
        return f"No pude procesar: '{text[:60]}'. No hay agente disponible ni Claude configurado."


orchestrator = AgentOrchestrator()
