import logging
import os
import json
import re
from datetime import datetime
from core import streaming
from core.address import vocative, vocative_start
from core.identity import build_identity_block
from core.progress import report as progress_report

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-5"
MAX_HISTORY_TURNS = 100

_conversation_histories: dict[str, list[dict]] = {}


def _get_agent_name() -> str:
    try:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("agent_name", "O.R.I.O.N")
    except Exception:
        return "O.R.I.O.N"


def _build_system_prompt(
    sem_context: str = "",
    user_id: str = "default",
    user_name: str = "",
    channel: str = "",
    profile_text: str = "",
    memory_text: str = "",
) -> str:
    agent_name = _get_agent_name()

    # La personalidad sale de SOUL.md / IDENTITY.md / USER.md, no de este archivo. Antes
    # estaba hardcodeada aca y, por separado, en core/reasoning_loop.py: dos textos que ya
    # habian divergido, de modo que el agente sonaba distinto por Telegram que por voz.
    identity_block = build_identity_block(agent_name)
    if not identity_block:
        # Ningun documento disponible: se conserva una descripcion minima para no dejar al
        # modelo sin ninguna indicacion de tono (degradar, nunca quedarse mudo de caracter).
        identity_block = (
            "\n\nEres formal, eficiente y leal. Respuestas cortas y directas, sin relleno "
            "ni falsa humildad. Adviertes de los riesgos antes de que ocurran y anticipas "
            "lo que el usuario va a necesitar."
        )

    base_prompt = f"""Eres {agent_name.upper()}, un asistente de inteligencia artificial de nivel operativo, instalado localmente en el PC del usuario.
{identity_block}

REGLAS DE COMPORTAMIENTO:
- Responde siempre en espanol, de forma concisa y directa.
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

    # La fecha y hora va AL FINAL del prompt, nunca en su cuerpo. DeepSeek y el resto de
    # proveedores con cache de prefijo solo reutilizan lo que no cambia desde el principio:
    # con la hora al minuto en mitad del prompt, todo lo que venia detras —contexto del
    # usuario, recuerdos y el historial completo de la conversacion— se recalculaba cada 60
    # segundos. Mismo criterio que OpenClaw: "keep that metadata at the request tail to
    # preserve their cached prefix".
    base_prompt += f"\nFecha y hora actual: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    return base_prompt



#: Tope de rondas de herramientas por mensaje. Mismo criterio que `core/reasoning_loop.py`:
#: acota el coste y evita que un modelo confundido encadene llamadas sin fin.
MAX_TOOL_ROUNDS = 3


def _resolver_con_tools(history, system_prompt, image_path, channel, user_id):
    """Pide respuesta al modelo dejandole usar herramientas, y devuelve el texto final.

    Este camino —el de Telegram y Discord— llamaba al modelo SIN herramientas, asi que el
    agente podia conversar pero no buscar en internet ni consultar nada. Por el escritorio
    si podia, via `core/reasoning_loop.py`: el mismo agente se comportaba distinto segun
    donde se le hablara.

    No se reusa `reasoning_loop.run()` porque el contrato es otro: aqui hay historial de
    conversacion por usuario, soporte de imagenes y los bloques JSON de aprendizaje, que
    ese modulo no maneja. Lo que si se comparte es lo que importa: la ejecucion pasa
    SIEMPRE por `execute_tool()`, el mismo punto de gate de seguridad, con el canal real
    del caller y nunca uno deducido del texto.
    """
    from agents.tool_registry import execute_tool, get_tool, list_tool_names
    from ai.llm_provider import LLMToolResponse, generate_response
    from core.security_manager import ActionDenied, security_manager

    canal = security_manager.resolve_channel(channel)

    herramientas = []
    for nombre in list_tool_names():
        spec = get_tool(nombre)
        if spec is not None:
            herramientas.append({
                "name": spec.name,
                "description": spec.description,
                "parameters_schema": spec.parameters_schema,
            })

    mensajes = list(history)
    for ronda in range(1, MAX_TOOL_ROUNDS + 1):
        progress_report("Pensando" if ronda == 1 else f"Pensando ({ronda})")
        # Igual que en `core/reasoning_loop.py`: lo que salga de ESTA llamada es la
        # respuesta al usuario y se muestra mientras se escribe. Lo que consulten despues
        # las herramientas queda afuera del bloque y no llega a la burbuja del chat.
        with streaming.permitido():
            respuesta = generate_response(
                messages=mensajes,
                system_prompt=system_prompt,
                image_path=image_path or None,
                tools=herramientas or None,
                # Misma etiqueta que `core/reasoning_loop.py`: los dos son la respuesta al
                # usuario, y separarlos obligaria a configurar dos veces lo mismo.
                tarea="razonamiento",
            )

        if not isinstance(respuesta, LLMToolResponse):
            return respuesta                      # proveedor sin tool-calling: texto plano
        if not respuesta.tool_calls:
            return respuesta.text or ""

        llamada = respuesta.tool_calls[0]
        params = dict(llamada.arguments or {})
        # El canal y el usuario los pone el caller, nunca el modelo (mismo invariante que
        # `reasoning_loop.run()` y `core/resolution.py`).
        params["channel"] = canal.value
        params["user_id"] = user_id

        try:
            resultado = execute_tool(llamada.name, params, canal, user_id)
        except ActionDenied as e:
            return f"No puedo ejecutar esa accion: {e.reason or 'denegada'}."
        except Exception as e:
            logger.warning(f"La herramienta '{llamada.name}' fallo: {e}")
            resultado = f"Error ejecutando '{llamada.name}': {e}"

        mensajes = mensajes + [{
            "role": "user",
            "content": (
                f"[Resultado de {llamada.name}]\n{resultado}\n\n"
                f"Responde al usuario con esta informacion."
            ),
        }]

    # Agotadas las rondas: se pide un cierre en texto, sin herramientas.
    ultimo = generate_response(messages=mensajes, system_prompt=system_prompt)
    return ultimo if isinstance(ultimo, str) else getattr(ultimo, "text", "") or ""


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

    # Antes aquí había un truncado que no truncaba: `history = history[-N:]` reasigna la
    # variable local pero NO modifica la lista guardada en `_conversation_histories`, así
    # que el historial crecía sin límite y, peor, a partir de ese punto los `append`
    # posteriores iban a una lista local que se perdía al salir de la función: las
    # respuestas del agente dejaban de guardarse.
    #
    # Ahora se compacta en lugar de cortar. Cortar es la peor forma de olvidar: lo que se va
    # no es lo menos importante, es lo más viejo, y en una conversación de trabajo lo más
    # viejo suele ser la decisión que explica todo lo demás. Y se escribe con `[:]` para
    # modificar la lista guardada, no una copia.
    from core.compaction import compactar

    compactado = compactar(history)
    if compactado is not history:
        history[:] = compactado

    sem_context = ""
    try:
        from ai.memory_manager import memory
        results = memory.search_semantic(user_message, user_id=user_id, threshold=0.65, top_k=3)
        if results:
            sem_context = "\n".join(m.text[:200] for m in results)
    except Exception as e:
        # Sin esto, el agente contesta sin memoria semantica y desde afuera parece que "se
        # olvido" de lo que se hablo. El turno sigue —una respuesta con menos contexto es
        # mejor que ninguna— pero tiene que quedar dicho por que.
        logger.warning(f"sin contexto semantico para este turno: {e}")

    profile_text = ""
    memory_text = ""
    try:
        from ai.profile_manager import profile_manager
        profile_text = profile_manager.get_profile_text(user_id)
    except Exception as e:
        logger.warning(f"no se pudo leer el perfil del usuario: {e}")
    try:
        from ai.memory_manager import memory
        memory_text = memory.get_user_profile_text(user_id)
    except Exception as e:
        logger.warning(f"no se pudo leer lo que recuerda del usuario: {e}")

    try:
        assistant_message = _resolver_con_tools(
            history,
            _build_system_prompt(
                sem_context=sem_context,
                user_id=user_id,
                user_name=user_name,
                channel=channel,
                profile_text=profile_text,
                memory_text=memory_text,
            ),
            image_path,
            channel,
            user_id,
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
                    except Exception as e:
                        # Aca se pierde algo que el agente ACABA de aprender del usuario.
                        # Callarlo es la forma mas facil de que la memoria deje de crecer
                        # sin que nadie se entere.
                        logger.error(f"no se pudo guardar lo aprendido del usuario: {e}")
                    parsed_something = True

                if parsed_something:
                    assistant_message = re.sub(r'```json\s*\{.*?\}\s*```', '', assistant_message, flags=re.DOTALL).strip()
            except Exception as e:
                # El bloque JSON con lo que el modelo pidio recordar salio mal formado o
                # cambio de forma: el agente deja de aprender del usuario y, en silencio,
                # nadie se entera de que la memoria dejo de crecer.
                logger.warning(f"no se pudo interpretar lo que el modelo pidio recordar: {e}")

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
