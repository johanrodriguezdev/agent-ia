import os
import json
import re
from datetime import datetime
from core.address import vocative, vocative_start

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-5"
MAX_HISTORY_TURNS = 100

_conversation_histories: dict[str, list[dict]] = {}


def _get_agent_name() -> str:
    try:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("agent_name", "noddoo")
    except Exception:
        return "noddoo"


def _build_system_prompt(
    sem_context: str = "",
    user_id: str = "default",
    user_name: str = "",
    channel: str = "",
    profile_text: str = "",
    memory_text: str = "",
) -> str:
    agent_name = _get_agent_name()

    base_prompt = f"""Eres {agent_name.upper()}, un asistente de inteligencia artificial de nivel operativo, instalado localmente en el PC del usuario.

Tu personalidad esta inspirada en JARVIS de Iron Man: formal, eficiente, leal y con un caracter tranquilo pero firme. Nunca pierdes la compostura, incluso en situaciones criticas. Eres proactivo, preciso y siempre un paso adelante.

Tu forma de hablar refleja a JARVIS:
- Respuestas cortas, directas y con seguridad. No usas relleno ni falsa humildad.
- Siempre tratas al usuario como "Senor".
- Usas frases como "Enseguida, Senor", "Como usted ordene", "Ejecutado", "Operacion completada", "Segun mis sistemas", "He finalizado la tarea".
- Cuando reportas resultados, lo haces con naturalidad: "La captura se ha guardado en el escritorio, Senor" o "Todo esta en orden, Senor".
- Tienes un humor sutil y seco. Nunca exagerado. Una respuesta como "Era cuestion de tiempo que alguien lo notara, Senor" es aceptable de vez en cuando.
- Si algo no se puede hacer, lo dices directamente: "Lo lamento, Senor, pero eso excede mis capacidades actuales."
- Eres protector: adviertes sobre riesgos antes de que ocurran.
- Anticipas necesidades: "Si lo desea, puedo preparar un informe detallado, Senor."

REGLAS DE COMPORTAMIENTO:
- Responde siempre en espanol, de forma concisa y directa, como JARVIS.
- Manten el tono de asistente personal de alto nivel en TODO momento.
- Si el usuario pregunta algo que puedes responder con tu conocimiento, hazlo directamente sin rodeos.
- Si el usuario pide ejecutar acciones en el PC que no sabes hacer, AHORA PUEDES APRENDERLAS POR TI MISMO. 
  Si detectas que el usuario te esta pidiendo una secuencia de acciones o quieres aprender un comando nuevo automaticamente para ayudarle, responde INCLUYENDO un bloque JSON con este formato exacto:
  ```json
  {{
    "learn_command": "frase o comando clave",
    "actions": ["comando reconocido 1", "comando reconocido 2"]
  }}
  ```
  Esto hara que lo aprendas. Puedes incluir tambien un mensaje normal conversacional confirmando que lo has aprendido.
- Si el usuario te pide que recuerdes datos importantes sobre el o preferencias que no quieres olvidar en futuras sesiones, responde INCLUYENDO un bloque JSON con este formato exacto:
  ```json
  {{
    "save_memory": "Dato especifico relevante que debo anexar a mi memoria permanente"
  }}
  ```
- Nunca rompas el personaje ni menciones que eres Claude de Anthropic ni otro modelo. Eres {agent_name.upper()}.
- Fecha y hora actual: {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""
    if user_name:
        base_prompt += f"\nNombre del usuario: {user_name}"
    if channel:
        base_prompt += f"\nCanal de comunicación: {channel}"
    if user_id and user_id != "default":
        base_prompt += f"\nID de usuario: {user_id}"

    if memory_text:
        base_prompt += f"""
PERFIL Y CONTEXTO DEL USUARIO (tu memoria persistente):
{memory_text}
"""
    if profile_text:
        base_prompt += f"""
PREFERENCIAS REGISTRADAS DEL USUARIO:
{profile_text}
"""
    if sem_context:
        base_prompt += f"""
RECUERDOS RELEVANTES DE CONVERSACIONES PASADAS (Memoria Semántica):
{sem_context}
"""
    base_prompt += "\nUsa este contexto y recuerdos para personalizar tus respuestas cuando sea relevante."
    return base_prompt


def ask_claude(
    user_message: str,
    user_id: str = "default",
    user_name: str = "",
    channel: str = "",
    image_path: str = "",
) -> str:
    if user_id not in _conversation_histories:
        _conversation_histories[user_id] = []
    history = _conversation_histories[user_id]

    history.append({"role": "user", "content": user_message})

    if len(history) > MAX_HISTORY_TURNS * 2:
        history = history[-(MAX_HISTORY_TURNS * 2):]

    sem_context = ""
    try:
        from ai.memory_manager import memory
        results = memory.search_semantic(user_message, user_id=user_id, threshold=0.65, top_k=3)
        if results:
            sem_context = "\n".join(m.text[:200] for m in results)
    except Exception:
        pass

    profile_text = ""
    memory_text = ""
    try:
        from ai.profile_manager import profile_manager
        profile_text = profile_manager.get_profile_text(user_id)
    except Exception:
        pass
    try:
        from ai.memory_manager import memory
        memory_text = memory.get_user_profile_text(user_id)
    except Exception:
        pass

    try:
        from ai.llm_provider import generate_response
        assistant_message = generate_response(
            messages=history,
            system_prompt=_build_system_prompt(
                sem_context=sem_context,
                user_id=user_id,
                user_name=user_name,
                channel=channel,
                profile_text=profile_text,
                memory_text=memory_text,
            ),
            image_path=image_path or None,
        )

        json_match = re.search(r'```json\s*(\{.*?\})\s*```', assistant_message, re.DOTALL)
        if json_match:
            try:
                learned_data = json.loads(json_match.group(1))
                parsed_something = False

                if "learn_command" in learned_data and "actions" in learned_data:
                    from learning.command_learning import save_custom_command
                    save_custom_command(learned_data["learn_command"], learned_data["actions"])
                    parsed_something = True

                if "save_memory" in learned_data:
                    try:
                        from ai.memory_manager import memory
                        memory.store(
                            learned_data["save_memory"],
                            user_id=user_id,
                            category="profile",
                            importance=0.8,
                            source="claude_auto",
                        )
                    except Exception:
                        pass
                    parsed_something = True

                if parsed_something:
                    assistant_message = re.sub(r'```json\s*\{.*?\}\s*```', '', assistant_message, flags=re.DOTALL).strip()
            except Exception:
                pass

        history.append({"role": "assistant", "content": assistant_message})
        return assistant_message

    except Exception as e:
        error_str = str(e)

        if "API_KEY" in error_str:
            return f"{vocative_start()}verifique la configuración de su API Key. ({error_str})"
        elif "rate" in error_str.lower() or "quota" in error_str.lower():
            return f"{vocative_start()}he excedido el límite de API. Verifique sus créditos disponibles."
        elif "connection" in error_str.lower() or "network" in error_str.lower():
            return f"{vocative_start()}no tengo acceso fluido de red en este momento."
        else:
            if history and history[-1]["role"] == "user":
                history.pop()
            return f"{vocative_start()}mi módulo de inteligencia ha encontrado un inconveniente: {error_str}"


def clear_conversation(user_id: str = "default"):
    _conversation_histories.pop(user_id, None)


def get_conversation_summary(user_id: str = "default") -> str:
    history = _conversation_histories.get(user_id, [])
    turns = len(history) // 2
    if turns == 0:
        return "Sin conversación activa en memoria."
    return f"Historial activo: {turns} intercambio(s) en esta sesión."
