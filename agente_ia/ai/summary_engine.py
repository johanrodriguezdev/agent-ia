import logging
from typing import List

logger = logging.getLogger(__name__)

SUMMARY_INTERVAL = 10


class SummaryEngine:
    def __init__(self):
        self._session_counts: dict = {}

    def should_summarize(self, user_id: str, current_count: int) -> bool:
        last = self._session_counts.get(user_id, 0)
        if current_count > 0 and current_count % SUMMARY_INTERVAL == 0 and current_count != last:
            self._session_counts[user_id] = current_count
            return True
        return False

    def generate_partial_summary(self, conversation: List[dict]) -> str:
        if not conversation:
            return ""
        recent = conversation[-SUMMARY_INTERVAL:]
        text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')[:200]}"
            for m in recent
        )
        result = self._call_llm(
            "Resume en 2-3 líneas los temas clave de esta conversación:\n\n"
            f"{text}\n\nResumen:"
        )
        if result:
            return result[:300]
        lines = []
        for m in recent[-5:]:
            content = m.get("content", "")[:80]
            if content:
                lines.append(f"- {m.get('role', 'user')}: {content}")
        return "Resumen parcial:\n" + "\n".join(lines) if lines else ""

    def generate_final_summary(self, session_history: List[dict]) -> str:
        if not session_history:
            return ""
        text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')[:150]}"
            for m in session_history[-20:]
        )
        result = self._call_llm(
            "Genera un resumen final de esta sesión en 3-5 líneas. "
            "Incluye temas tratados, decisiones tomadas y cualquier "
            "información importante sobre el usuario:\n\n"
            f"{text}\n\nResumen final:"
        )
        if result:
            return result[:500]
        total = len(session_history)
        return f"Sesión con {total} interacciones. Usa el comando 'qué recuerdas de mí' para más detalles."

    def _call_llm(self, prompt: str) -> str:
        try:
            from ai.llm_provider import generate_response
            messages = [{"role": "user", "content": prompt}]
            return generate_response(messages, system_prompt="Eres un asistente que resume conversaciones de forma concisa.")
        except Exception as e:
            logger.warning(f"Error llamando LLM en summary: {e}")
            return ""

    def reset_count(self, user_id: str):
        self._session_counts.pop(user_id, None)


summary_engine = SummaryEngine()
