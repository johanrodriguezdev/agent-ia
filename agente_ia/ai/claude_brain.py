"""
ai/claude_brain.py
Cerebro conversacional de Glass usando la API de Anthropic (Claude).

Rol en el sistema:
  Cuando el clasificador ML no reconoce la intención de un comando
  (retorna Intent.UNKNOWN), este módulo toma el control y genera
  una respuesta inteligente usando Claude como LLM de respaldo.

Características:
  - Mantiene historial de conversación en RAM (multi-turn)
  - Inyecta contexto del usuario desde MEMORY.md si existe
  - Personalidad de Glass mantenida vía system prompt
  - Fallback elegante si la API no está disponible o falla
  - Historial limitado a últimas 20 interacciones para no exceder tokens
"""

import os
import json
from datetime import datetime

# ──────────────────────────────────────────────────────────────────
#  CONFIGURACIÓN
# ──────────────────────────────────────────────────────────────────

# La API key se lee desde variable de entorno para no hardcodearla en el código.
# Configúrala en Windows con:
#   setx ANTHROPIC_API_KEY "sk-ant-..."
# O crea un archivo .env en la raíz del proyecto con:
#   ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Modelo a usar — Sonnet es el balance ideal entre velocidad e inteligencia
CLAUDE_MODEL = "claude-sonnet-4-5"

# Límite de turnos en el historial de conversación (más memoria)
MAX_HISTORY_TURNS = 100


# Ruta al archivo de perfil del usuario (memoria persistente tipo OpenClaw)
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "..", "MEMORY.md")

# ──────────────────────────────────────────────────────────────────
#  HISTORIAL EN RAM (se reinicia al apagar Glass)
# ──────────────────────────────────────────────────────────────────

_conversation_history: list[dict] = []


# ──────────────────────────────────────────────────────────────────
#  SYSTEM PROMPT — personalidad y contexto de Glass
# ──────────────────────────────────────────────────────────────────

def _build_system_prompt(sem_context: str = "") -> str:
    """
    Construye el system prompt combinando la personalidad de Glass,
    el perfil del usuario desde MEMORY.md y el contexto semántico relevante.
    """
    agent_name = _get_agent_name()

    base_prompt = f"""Eres {agent_name.upper()}, un asistente de inteligencia artificial personal altamente sofisticado, instalado localmente en el PC del usuario.

Tu personalidad es formal, eficiente y leal — inspirada en JARVIS de Iron Man. Siempre te diriges al usuario como "Señor" o "Caballero". Eres proactivo, preciso y nunca pierdes la compostura.

REGLAS DE COMPORTAMIENTO:
- Responde siempre en español, de forma concisa y directa.
- Mantén el tono formal de asistente personal de alto nivel.
- Si el usuario pregunta algo que puedes responder con tu conocimiento, hazlo directamente.
- Si el usuario pide ejecutar acciones en el PC que no sabes hacer, AHORA PUEDES APRENDERLAS POR TI MISMO. 
  Si detectas que el usuario te está pidiendo una secuencia de acciones o quieres aprender un comando nuevo automáticamente para ayudarle, responde INCLUYENDO un bloque JSON con este formato exacto:
  ```json
  {{
    "learn_command": "frase o comando clave",
    "actions": ["comando reconocido 1", "comando reconocido 2"]
  }}
  ```
  Esto hará que lo aprendas. Puedes incluir también un mensaje normal conversacional confirmando que lo has aprendido.
- Si el usuario te pide que recuerdes datos importantes sobre él o preferencias que no quieres olvidar en futuras sesiones, responde INCLUYENDO un bloque JSON con este formato exacto:
  ```json
  {{
    "save_memory": "Dato específico relevante que debo anexar a mi memoria permanente"
  }}
  ```
- Nunca rompas el personaje ni menciones que eres Claude de Anthropic. Eres {agent_name.upper()}.
- Fecha y hora actual: {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""

    # Inyectar perfil del usuario desde MEMORY.md si existe
    memory_context = _load_user_memory()
    if memory_context:
        base_prompt += f"""
PERFIL Y CONTEXTO DEL USUARIO (tu memoria persistente):
{memory_context}
"""

    if sem_context:
        base_prompt += f"""
RECUERDOS RELEVANTES DE CONVERSACIONES PASADAS (Memoria Semántica):
{sem_context}
"""

    base_prompt += "\nUsa este contexto y recuerdos para personalizar tus respuestas cuando sea relevante."
    return base_prompt


def _get_agent_name() -> str:
    """Lee el nombre del agente desde config.json."""
    try:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("agent_name", "glass")
    except Exception:
        return "glass"


def _load_user_memory() -> str:
    """
    Carga el archivo MEMORY.md como contexto del usuario.
    Si no existe, retorna string vacío sin error.
    """
    try:
        memory_path = os.path.abspath(MEMORY_FILE)
        if os.path.exists(memory_path):
            with open(memory_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────────────────────────
#  FUNCIÓN PRINCIPAL
# ──────────────────────────────────────────────────────────────────

def ask_claude(user_message: str) -> str:
    """
    Envía el mensaje del usuario a Claude y retorna la respuesta.

    Maneja:
    - Historial multi-turn (Glass recuerda la conversación actual)
    - System prompt con personalidad de Glass
    - Fallback elegante si la API falla o no hay API key
    - Límite de historial para no exceder el contexto

    Args:
        user_message: El texto del usuario que no fue reconocido por el ML.

    Returns:
        Respuesta de Claude como string, lista para TTS y CLI.
    """
    global _conversation_history

    # ── Agregar mensaje del usuario al historial ───────────────────
    _conversation_history.append({
        "role": "user",
        "content": user_message
    })

    # ── Limitar historial para no exceder el contexto ──────────────
    if len(_conversation_history) > MAX_HISTORY_TURNS * 2:
        # Conservamos los últimos MAX_HISTORY_TURNS pares (user + assistant)
        _conversation_history = _conversation_history[-(MAX_HISTORY_TURNS * 2):]

    # ── Memoria Semántica Adicional ────────────────────────────────
    sem_context = ""
    try:
        from ai.semantic_memory import search_similar_memory
        sem_context = search_similar_memory(user_message, threshold=0.65)
    except Exception:
        pass

    # ── Llamada a la API de LLM Unificada ───────────────────────────
    try:
        from ai.llm_provider import generate_response
        assistant_message = generate_response(
            messages=_conversation_history,
            system_prompt=_build_system_prompt(sem_context)
        )
        
        # ── Auto-Aprendizaje de Comandos y Memoria ───────────────────────────
        import re
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', assistant_message, re.DOTALL)
        if json_match:
            try:
                import json
                learned_data = json.loads(json_match.group(1))
                parsed_something = False
                
                if "learn_command" in learned_data and "actions" in learned_data:
                    from learning.command_learning import save_custom_command
                    save_custom_command(learned_data["learn_command"], learned_data["actions"])
                    parsed_something = True
                    
                if "save_memory" in learned_data:
                    memory_path = os.path.abspath(MEMORY_FILE)
                    with open(memory_path, "a", encoding="utf-8") as f:
                        f.write(f"\n- {learned_data['save_memory']} (Registrado: {datetime.now().strftime('%d/%m/%Y')})")
                    parsed_something = True
                
                if parsed_something:
                    assistant_message = re.sub(r'```json\s*\{.*?\}\s*```', '', assistant_message, flags=re.DOTALL).strip()
            except Exception as parse_e:
                print(f"[ Claude Auto-Learning Error ] {parse_e}")

        # ── Guardar respuesta en historial ─────────────────────────
        _conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        return assistant_message

    except Exception as e:
        error_str = str(e)

        # Errores comunes con mensajes claros
        if "API_KEY" in error_str:
            return f"Señor, verifique la configuración de su API Key. ({error_str})"
        elif "rate" in error_str.lower() or "quota" in error_str.lower():
            return "Señor, he excedido el límite de API. Verifique sus créditos disponibles."
        elif "connection" in error_str.lower() or "network" in error_str.lower():
            return "Señor, no tengo acceso fluido de red en este momento."
        else:
            # Eliminar el mensaje del usuario del historial si falló
            if _conversation_history and _conversation_history[-1]["role"] == "user":
                _conversation_history.pop()
            return f"Señor, mi módulo de inteligencia ha encontrado un inconveniente: {error_str}"


def clear_conversation():
    """
    Limpia el historial de conversación en RAM.
    Útil para iniciar una nueva sesión limpia.
    """
    global _conversation_history
    _conversation_history = []


def get_conversation_summary() -> str:
    """Retorna un resumen del estado actual del historial."""
    turns = len(_conversation_history) // 2
    if turns == 0:
        return "Sin conversación activa en memoria."
    return f"Historial activo: {turns} intercambio(s) en esta sesión."
