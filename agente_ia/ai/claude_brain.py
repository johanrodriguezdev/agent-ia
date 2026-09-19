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
    # Con la zona horaria: decir "22:30" sin decir de dónde deja al modelo adivinando si el
    # usuario está de noche, que es justo lo que necesita para saludar bien.
    from core.address import momento_actual

    base_prompt += f"\nFecha y hora actual: {momento_actual()}"
    return base_prompt



def _ultimo_mensaje_del_usuario(history) -> str:
    """Return lo que dijo el humano en este turno: el último `user` del historial."""
    for mensaje in reversed(history):
        if mensaje.get("role") == "user":
            contenido = mensaje.get("content")
            return contenido if isinstance(contenido, str) else str(contenido or "")
    return ""


def _cerrar_sin_herramientas(mensajes, instruccion, system_prompt, image_path):
    """Una última llamada con `tools=None` para redactar con lo reunido (REQ-044/CA-05).

    Misma pieza que `core/reasoning_loop._llamada_de_cierre()`: la instrucción se cuelga
    del último mensaje —con historial de herramientas es el de resultados, también de rol
    `user`, y Anthropic exige alternancia estricta— y sin herramientas la garantía de "no
    reintenta la acción denegada" es estructural, no una frase del prompt. Return
    `(texto_o_None, aviso_de_cambio)`.
    """
    from ai.llm_provider import LLMToolResponse, es_respuesta_de_fallo, generate_response
    from core import tool_history

    ultimo = mensajes[-1]
    if tool_history.es_estructurado(ultimo):
        mensajes = mensajes[:-1] + [tool_history.con_texto_agregado(ultimo, instruccion)]
    else:
        mensajes = mensajes[:-1] + [
            {**ultimo, "content": f"{ultimo.get('content', '')}\n\n{instruccion}"}
        ]

    aviso: dict = {}
    with streaming.permitido():
        respuesta = generate_response(
            messages=mensajes, system_prompt=system_prompt, image_path=image_path or None,
            tools=None, tarea="razonamiento", aviso=aviso,
        )
    if isinstance(respuesta, LLMToolResponse):
        texto = respuesta.text if not respuesta.tool_calls else None
    else:
        texto = respuesta
    if not texto or es_respuesta_de_fallo(texto):
        return None, aviso
    return texto, aviso


def _resolver_con_tools(history, system_prompt, image_path, channel, user_id):
    """Pide respuesta al modelo dejandole usar herramientas, y devuelve el texto final.

    Este camino —el de Telegram y Discord— llamaba al modelo SIN herramientas, asi que el
    agente podia conversar pero no buscar en internet ni consultar nada. Por el escritorio
    si podia, via `core/reasoning_loop.py`: el mismo agente se comportaba distinto segun
    donde se le hablara.

    Desde REQ-044 razona igual que el escritorio (REQ-027): los resultados de las
    herramientas viajan como historial NEUTRAL de `core/tool_history.py` —que cada
    adaptador traduce a `tool_use`/`tool_result` de su proveedor— y no como texto pegado
    en un mensaje `user`; se ejecutan TODAS las tool calls de la vuelta, en secuencia y
    por `execute_tool()`, con el canal y el usuario del caller; y al agotar el presupuesto
    o ante una denegacion hay una llamada de cierre sin herramientas que redacta con lo
    reunido, en vez del texto enlatado.

    No se reusa `reasoning_loop.run()` entero porque el contrato es otro: aqui hay
    historial de conversacion por usuario, soporte de imagenes y los bloques JSON de
    aprendizaje. Lo que si se comparte es lo que importa: la vuelta
    (`reasoning_loop.ejecutar_vuelta`), el formato del historial, el presupuesto del canal
    (`TECHO_CANAL_NO_ESCRITORIO`) y las instrucciones de cierre. `cancelable=False`: el
    boton de detener es del escritorio y mira un estado de proceso; un turno de escritorio
    cancelado no puede abortar un mensaje de Telegram en otro hilo.
    """
    from agents.tool_registry import catalogo_para_modelo
    from ai.llm_provider import LLMToolResponse, con_aviso_de_cambio, generate_response
    from core import tool_history
    from core.reasoning_loop import (
        _INSTRUCCION_CIERRE_DENEGACION, _INSTRUCCION_CIERRE_PRESUPUESTO,
        TECHO_CANAL_NO_ESCRITORIO, ejecutar_vuelta,
    )
    from core.security_manager import security_manager

    canal = security_manager.resolve_channel(channel)

    # Mismo catalogo que el escritorio, y filtrado por ESTE canal. Antes esta lista se
    # armaba aparte, asi que por Telegram seguian apareciendo las herramientas agrupadas y
    # las amarillas que este canal nunca puede ejecutar: el modelo las pedia y el gate se
    # las denegaba, gastando una vuelta cada vez.
    herramientas = catalogo_para_modelo(canal)
    tarea_del_usuario = _ultimo_mensaje_del_usuario(history)

    #: El historial de herramientas del turno, en formato neutral. Es del turno: el
    #: historial por usuario (`history`) sigue guardando solo texto (CA-07).
    historial: list = []
    denegacion = None
    ultimo_aviso: dict = {}

    for ronda in range(1, TECHO_CANAL_NO_ESCRITORIO + 1):
        progress_report("Pensando" if ronda == 1 else f"Pensando ({ronda})")
        aviso_cambio: dict = {}   # REQ-022/CA-12 — vacío otra vez en cada ronda
        # Igual que en `core/reasoning_loop.py`: lo que salga de ESTA llamada es la
        # respuesta al usuario y se muestra mientras se escribe. Lo que consulten despues
        # las herramientas queda afuera del bloque y no llega a la burbuja del chat.
        with streaming.permitido():
            respuesta = generate_response(
                messages=list(history) + historial,
                system_prompt=system_prompt,
                image_path=image_path or None,
                tools=herramientas or None,
                # Misma etiqueta que `core/reasoning_loop.py`: los dos son la respuesta al
                # usuario, y separarlos obligaria a configurar dos veces lo mismo.
                tarea="razonamiento",
                aviso=aviso_cambio,   # REQ-022/CA-12
            )
        if aviso_cambio:
            ultimo_aviso = aviso_cambio

        if not isinstance(respuesta, LLMToolResponse):
            # proveedor sin tool-calling: texto plano. `corto` queda en su default `False`
            # (CA-15): este camino nunca resuelve ChannelType.VOICE.
            return con_aviso_de_cambio(respuesta, aviso_cambio)
        if not respuesta.tool_calls:
            return con_aviso_de_cambio(respuesta.text or "", aviso_cambio)

        # REQ-044/CA-03: todas las que pidio, en orden. Antes se ejecutaba solo
        # `tool_calls[0]` y el resto se descartaba: el modelo tenia que volver a pedirlas
        # gastando otra vuelta entera del presupuesto.
        llamadas, resultados, denegacion = ejecutar_vuelta(
            respuesta.tool_calls, ronda, canal, user_id, tarea_del_usuario, cancelable=False,
        )
        historial.append(tool_history.mensaje_de_llamadas(respuesta.text, llamadas))
        historial.append(tool_history.mensaje_de_resultados(resultados))
        if denegacion is not None:
            break

    # Presupuesto agotado o denegacion: una llamada de cierre sin herramientas, fuera del
    # presupuesto, con la misma instruccion que el escritorio (CA-05).
    instruccion = (
        _INSTRUCCION_CIERRE_DENEGACION if denegacion is not None
        else _INSTRUCCION_CIERRE_PRESUPUESTO
    )
    texto, aviso_cierre = _cerrar_sin_herramientas(
        list(history) + historial, instruccion, system_prompt, image_path,
    )
    if texto:
        return con_aviso_de_cambio(texto, aviso_cierre or ultimo_aviso)
    if denegacion is not None:
        return f"No puedo ejecutar esa accion: {denegacion}."
    return con_aviso_de_cambio(
        f"No pude completar la tarea en el número de intentos disponibles{vocative()}. "
        "¿Quiere que lo intente de otra forma?",
        ultimo_aviso,
    )


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
