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

# Límite de turnos en el historial de conversación (para no exceder el contexto)
MAX_HISTORY_TURNS = 20

# Ruta al archivo de perfil del usuario (memoria persistente tipo OpenClaw)
MEMORY_FILE = os.path.join(os.path.dirname(__file__), "..", "MEMORY.md")

# ──────────────────────────────────────────────────────────────────
#  HISTORIAL EN RAM (se reinicia al apagar Glass)
# ──────────────────────────────────────────────────────────────────

_conversation_history: list[dict] = []


# ──────────────────────────────────────────────────────────────────
#  SYSTEM PROMPT — personalidad y contexto de Glass
# ──────────────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    """
    Construye el system prompt combinando la personalidad de Glass
    con el perfil del usuario desde MEMORY.md si existe.
    """
    agent_name = _get_agent_name()

    base_prompt = f"""Eres {agent_name.upper()}, un asistente de inteligencia artificial personal altamente sofisticado, instalado localmente en el PC del usuario.

Tu personalidad es formal, eficiente y leal — inspirada en JARVIS de Iron Man. Siempre te diriges al usuario como "Señor" o "Caballero". Eres proactivo, preciso y nunca pierdes la compostura.

REGLAS DE COMPORTAMIENTO:
- Responde siempre en español, de forma concisa y directa.
- Mantén el tono formal de asistente personal de alto nivel.
- Si el usuario pregunta algo que puedes responder con tu conocimiento, hazlo directamente.
- Si el usuario pide ejecutar acciones en el PC (abrir apps, buscar archivos, etc.), indícale que puedes hacerlo si reformula el comando de forma más específica.
- Nunca rompas el personaje ni menciones que eres Claude de Anthropic. Eres {agent_name.upper()}.
- Fecha y hora actual: {datetime.now().strftime('%d/%m/%Y %H:%M')}
"""

    # Inyectar perfil del usuario desde MEMORY.md si existe
    memory_context = _load_user_memory()
    if memory_context:
        base_prompt += f"""
PERFIL Y CONTEXTO DEL USUARIO (tu memoria persistente):
{memory_context}

Usa este contexto para personalizar tus respuestas cuando sea relevante.
"""

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

    # ── Verificar API key ──────────────────────────────────────────
    if not ANTHROPIC_API_KEY:
        return (
            "Señor, mi módulo de inteligencia conversacional no está configurado. "
            "Por favor establezca la variable de entorno ANTHROPIC_API_KEY para activarlo."
        )

    # ── Importar Anthropic (instalación opcional) ──────────────────
    try:
        import anthropic
    except ImportError:
        return (
            "Señor, la librería 'anthropic' no está instalada. "
            "Ejecute 'pip install anthropic' para activar el cerebro conversacional."
        )

    # ── Agregar mensaje del usuario al historial ───────────────────
    _conversation_history.append({
        "role": "user",
        "content": user_message
    })

    # ── Limitar historial para no exceder el contexto ──────────────
    if len(_conversation_history) > MAX_HISTORY_TURNS * 2:
        # Conservamos los últimos MAX_HISTORY_TURNS pares (user + assistant)
        _conversation_history = _conversation_history[-(MAX_HISTORY_TURNS * 2):]

    # ── Llamada a la API de Claude ─────────────────────────────────
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=_build_system_prompt(),
            messages=_conversation_history
        )

        # Extraer texto de la respuesta
        assistant_message = response.content[0].text

        # ── Guardar respuesta en historial ─────────────────────────
        _conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        return assistant_message

    except Exception as e:
        error_str = str(e)

        # Errores comunes con mensajes claros
        if "authentication" in error_str.lower() or "api_key" in error_str.lower():
            return "Señor, la clave de API de inteligencia no es válida. Verifique ANTHROPIC_API_KEY."
        elif "rate_limit" in error_str.lower():
            return "Señor, he excedido el límite de consultas por minuto. Permítame un momento antes de continuar."
        elif "connection" in error_str.lower() or "network" in error_str.lower():
            return "Señor, no tengo acceso a internet en este momento. No puedo procesar consultas de inteligencia avanzada."
        else:
            # Eliminar el mensaje del usuario del historial si falló (para no corromperlo)
            if _conversation_history and _conversation_history[-1]["role"] == "user":
                _conversation_history.pop()
            return f"Señor, mi módulo de inteligencia ha encontrado un inconveniente: {error_str[:100]}"


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
