"""
core/reasoning_loop.py
Bucle de razonamiento real con LLM (REQ-007, CA-01 a CA-13; REQ-027, CA-01 a CA-45).

Reemplaza el for-loop de `_DynamicAgentInstance.execute()` (que probaba tools en orden fijo
sin ningún criterio) por un ciclo decide->ejecuta->evalúa dirigido por el LLM, con ejecución
de tools EXCLUSIVAMENTE vía `agents/tool_registry.py::execute_tool()` (CA-06) — nunca
`ToolSpec.invoke` directo.

REQ-027 cambió tres cosas que hasta entonces limitaban el bucle a encadenar cuatro
herramientas por turno:

1. **El historial viaja nativo.** Antes, cada llamada al modelo era un mensaje único y
   autocontenido con las herramientas ya ejecutadas reescritas como texto. Ahora el turno
   es una conversación de verdad: el modelo ve sus propias llamadas y los resultados como
   lo que son. El formato dentro del bucle es NEUTRAL (`core/tool_history.py`) y cada
   adaptador de `ai/llm_provider.py` lo traduce, porque `generate_response()` puede cambiar
   de proveedor a mitad de turno por cooldown o respaldo (REQ-022).
2. **El presupuesto depende del modo activo** (`_presupuesto_de_llamadas()`), con techo
   fijo en todo canal que no sea escritorio. Cuenta llamadas al modelo, no herramientas.
3. **Se ejecutan TODAS las tool calls de una vuelta**, en secuencia y cada una por su
   propio gate (`_ejecutar_vuelta()`). Antes se ejecutaba la primera y el resto se
   descartaba, así que el modelo tenía que volver a pedirlas gastando otra vuelta.

Más una llamada de cierre sin herramientas (`_llamada_de_cierre()`) que redacta la
respuesta con lo reunido cuando el presupuesto se agota o una acción se deniega.
"""
import logging
import os
from typing import Optional

from agents.tool_registry import execute_tool
from core import streaming, tool_history
from core.cancelacion import abortar_si_cancelado
from ai.llm_provider import (
    MAX_TOKENS_SALIDA, LLMToolResponse, con_aviso_de_cambio, es_respuesta_de_fallo,
    generate_response, tope_de_salida,
)
from config_manager import get_agent_name, get_display_name, get_user_title
from core.agent_context import agent_context_manager
from core.security_manager import ActionDenied, ChannelType, security_manager
from core.address import momento_actual, vocative, vocative_start
from core.composer_modes import ModoComposer, get_mode
from core.progress import report as progress_report
from core.identity import build_identity_block
from core import estilo_respuesta

logger = logging.getLogger(__name__)

#: REQ-027/CA-11 — presupuesto por defecto (escritorio, sin modo estratégico activo).
#: Cuenta LLAMADAS AL MODELO, no herramientas: una vuelta que ejecuta cuatro herramientas
#: gasta una sola unidad. Era 5, y con 5 una cadena normal ("buscá → leé → resumí →
#: respondé") ya gastaba las 4 herramientas disponibles: cualquier callejón sin salida
#: reventaba el techo antes de terminar.
MAX_LLM_CALLS = 8

#: REQ-027/CA-15 — techo de todo canal que no sea escritorio: el valor de antes de
#: REQ-027, o sea cero regresión. Escrito como "todo lo que no sea DESKTOP tiene techo" y
#: no como una lista de canales remotos: así un canal en el que nadie pensó (`API`,
#: `EMAIL`, `UNKNOWN`) hereda el comportamiento de hoy y nunca el 40. En voz, además, un
#: turno largo es silencio que nadie puede cortar — el botón de detener es de escritorio.
TECHO_CANAL_NO_ESCRITORIO = 5

#: REQ-047 — Telegram y Discord ya pueden frenar un turno (`/detener`, `!detener`), que
#: era el único motivo del techo de 5. Pasan al presupuesto del escritorio sin modo. Voz,
#: API, correo y desconocido siguen en 5: ahí sigue sin haber forma de parar.
TECHO_CANAL_REMOTO_CON_STOP = MAX_LLM_CALLS

#: REQ-044 (P-4 de REQ-027) — techo de tokens de salida cuando la respuesta va a leerse en
#: voz alta. Con 4096 una respuesta larga por TTS son minutos que no se pueden cortar; 500
#: son unos 40 segundos de lectura, que ya es mucho para una conversación hablada. Aplica
#: solo a las llamadas que producen LA respuesta (bucle y cierre), no a las herramientas
#: que consulten al modelo por su cuenta dentro del turno.
MAX_TOKENS_VOZ = 500

#: Turnos previos que ve el modelo. Eran 5 registros —dos o tres intercambios— y la
#: respuesta del asistente se guardaba cortada a 200 caracteres: Johan le pidió "mejorá
#: ese mensaje" y el agente no podía, porque solo veía las dos primeras líneas de lo que
#: él mismo acababa de escribir. Ahora manda el TAMAÑO y no la cantidad: se incluyen los
#: turnos más recientes hasta llenar `CONTEXT_CARACTERES`, y ninguno va cortado a menos
#: que él solo supere `CONTEXT_CARACTERES_POR_TURNO`.
CONTEXT_TURNS = 24
CONTEXT_CARACTERES = 16_000
CONTEXT_CARACTERES_POR_TURNO = 6_000

#: Cuánto de la respuesta del asistente se guarda en `agent_context`. Era 200. Con eso,
#: cualquier "resumime lo que dijiste" o "corregí el segundo punto" trabajaba sobre un
#: recorte, y el agente contestaba como si no hubiera dicho nada.
MAX_RESPUESTA_GUARDADA = 6_000

#: REQ-027/CA-28/CA-29 — lo que se le pide al modelo en la llamada de cierre, que va
#: SIEMPRE sin herramientas. Sin herramientas, "no reintentes" es una garantía estructural
#: y no una frase que el modelo pueda desobedecer.
_INSTRUCCION_CIERRE_PRESUPUESTO = (
    "Se agotaron los intentos disponibles. Responde ahora al usuario con la mejor "
    "respuesta posible a partir de lo que ya averiguaste, sin usar más herramientas. "
    "Si quedó algo sin resolver, dilo con claridad."
)
_INSTRUCCION_CIERRE_DENEGACION = (
    "La acción fue denegada y la secuencia se detuvo. Informa al usuario de que no "
    "puedes ejecutarla y por qué, con lo que ya averiguaste. No la reintentes ni "
    "propongas un rodeo para conseguir lo mismo."
)

#: REQ-027/D-6 — resultado de una herramienta que la denegación dejó sin ejecutar. No es
#: cortesía con el modelo: Anthropic y el SDK `openai` rechazan con 400 un turno en el que
#: un `tool_use` se queda sin su `tool_result`, así que el par tiene que existir igual.
_NO_EJECUTADA = "No ejecutada: la secuencia se cortó por una acción denegada."


def _addressing_clause() -> str:
    """Describe al LLM cómo debe dirigirse al usuario, según lo configurado."""
    parts = []
    title = get_user_title().strip()
    if title:
        parts.append(f"se dirige al usuario como '{title}'")
    full_name = get_display_name().strip()
    if full_name:
        parts.append(f"el nombre completo del usuario es {full_name}")
    return f", {', '.join(parts)}" if parts else ""


def _bloque_de_lo_definido_por_el_usuario() -> str:
    """Rutinas y comandos aprendidos, nombrados en el prompt de sistema.

    Sin esto, el modelo tendria que adivinar que existen o gastar una vuelta entera en
    `routine_list`/`learned_command_list` antes de poder usarlos. Nombrarlos cuesta unas
    pocas decenas de tokens y hace que "modo trabajo" se resuelva en la PRIMERA llamada.

    Se arma en cada turno, no una vez al importar: una rutina creada hace un minuto tiene
    que estar disponible en el turno siguiente, sin reiniciar.
    """
    partes = []
    try:
        from learning.routines_engine import list_routine_names

        nombres = [n for n in list_routine_names() if n][:20]
        if nombres:
            partes.append("Rutinas que el usuario definio: " + ", ".join(nombres)
                          + ". Para ejecutar una, usa `routine_run`.")
    except Exception as e:
        logger.debug(f"No se pudieron leer las rutinas para el prompt: {e}")

    try:
        from learning.command_learning import get_custom_commands

        frases = [f for f in get_custom_commands() if f][:20]
        if frases:
            partes.append("Comandos que el usuario enseño: " + ", ".join(frases)
                          + ". Para ejecutar uno, usa `learned_command_run`.")
    except Exception as e:
        logger.debug(f"No se pudieron leer los comandos aprendidos para el prompt: {e}")

    return ("\n\n" + "\n".join(partes)) if partes else ""


def _build_system_prompt(modo_def: Optional[ModoComposer] = None) -> str:
    """Arma el prompt de sistema con el nombre configurado del agente.

    Se resuelve en cada llamada (no una vez al importar) para que renombrar al agente o
    cambiar el tratamiento en la pantalla de Configuración tenga efecto inmediato, sin
    reiniciar el proceso ni dejar al agente presentándose con el nombre viejo.

    `modo_def` (REQ-026): si el composer tiene un modo estratégico activo, su
    `prompt_hint` se agrega SIEMPRE al final, justo antes del bloque de fecha/hora — nunca
    en medio del prompt — para no romper el cacheo de prefijo de los proveedores que lo
    soportan salvo cuando el usuario realmente cambia de modo (mismo criterio que ya
    aplica el bloque de fecha/hora unas líneas más abajo).
    """
    agent_name = get_agent_name()

    # La personalidad ya no se describe acá. Antes, este prompt decía solo
    # "personalidad estilo JARVIS: educado, directo", mientras que `ai/claude_brain.py`
    # (Telegram/Discord) traía 40 líneas de carácter: el mismo agente sonaba distinto según
    # el canal, y el canal más usado —escritorio y voz— era el que menos personalidad
    # tenía. Ahora ambos leen los mismos documentos.
    identity_block = build_identity_block(agent_name)

    # REQ-071: la economía de la respuesta va ANTES de las reglas de herramientas y
    # después de la identidad. Antes solo se pedía «concisa y directa» en una línea suelta,
    # y medido no se cumplía: la mitad de las respuestas pasaba de 400 caracteres. Un
    # contrato con el contraste de lo que está mal y lo que está bien se cumple; un
    # adjetivo, no.
    from core.estilo_respuesta import bloque_para_el_prompt

    operating_rules = bloque_para_el_prompt() + "\n\n" + (
        "Tienes acceso a herramientas para ejecutar acciones reales en el sistema del "
        "usuario. Usa una herramienta solo si el pedido la requiere de verdad; si puedes "
        "responder directamente con lo que ya sabes, hazlo sin llamar a ninguna "
        "herramienta. Si el resultado de una herramienta indica que la acción fue "
        "denegada, no la reintentes ni intentes una alternativa — infórmalo y detente."
    ) + _bloque_de_lo_definido_por_el_usuario()

    # REQ-026: la pista del modo activo va al final de las reglas, DESPUÉS del bloque de
    # rutinas/comandos aprendidos y ANTES del de fecha/hora — mismo motivo de caché que
    # `momento` un poco más abajo.
    if modo_def is not None and modo_def.prompt_hint:
        operating_rules += f"\n\n{modo_def.prompt_hint}"

    # La fecha y hora va AL FINAL, nunca en el cuerpo — mismo criterio que
    # `ai/claude_brain.py`: los proveedores con caché de prefijo solo reutilizan lo que no
    # cambia desde el principio, y con la hora al minuto en medio se recalcularía todo lo
    # que viene detrás cada 60 segundos.
    #
    # Sin esta línea el modelo no sabe qué hora es y lo resuelve como puede: a las 23:30
    # saludaba con "buenos días" mientras la pantalla —que sí mira el reloj— decía "buenas
    # noches". `claude_brain` ya se lo decía a Telegram; el escritorio y la voz, que son
    # los canales más usados, eran justo los que no.
    momento = f"\n\nFecha y hora actual: {momento_actual()}"

    if identity_block:
        return (
            f"Eres el núcleo de razonamiento de {agent_name}{_addressing_clause()}."
            f"{identity_block}\n\n{operating_rules}{momento}"
        )

    # Sin documentos de identidad, el prompt queda igual que antes de este cambio.
    return (
        f"Eres el núcleo de razonamiento de {agent_name}, un asistente con "
        f"personalidad estilo JARVIS: educado, directo{_addressing_clause()}. "
        f"{operating_rules}{momento}"
    )


def _reordenar_priorizando(catalogo: list[dict], tool_names: tuple) -> list[dict]:
    """REQ-026 — mueve al frente de `catalogo` las entradas cuyo `"name"` está en
    `tool_names`, preservando el orden relativo dentro de cada grupo. NUNCA filtra: el
    catálogo completo se conserva, solo cambia el orden. Es intencional (arquitectura-026,
    riesgo "reordenar, no filtrar") — un mensaje que llega con un modo activo pero que no
    tiene nada que ver con él tiene que seguir pudiendo usar cualquier otra tool.
    """
    priorizadas = [t for t in catalogo if t.get("name") in tool_names]
    resto = [t for t in catalogo if t.get("name") not in tool_names]
    return priorizadas + resto


def _build_tool_list(channel=None, modo_def: Optional[ModoComposer] = None) -> list[dict]:
    """CA-02 — lo que se le ofrece al modelo, ya filtrado por canal.

    La lista la arma `agents/tool_registry.py::catalogo_para_modelo()`, que es de donde la
    lee tambien `ai/claude_brain.py`: con una copia por motor, la reduccion del catalogo
    aplicaba en escritorio y no en Telegram. El filtro NO es el control de seguridad — ese
    sigue dentro de `execute_tool()` (CA-11).

    `modo_def` (REQ-026): si hay un modo estratégico activo, sus `tool_names` se
    priorizan (reordenan al frente) vía `_reordenar_priorizando()` — nunca se filtra el
    resto del catálogo.
    """
    from agents.tool_registry import catalogo_para_modelo

    catalogo = catalogo_para_modelo(channel)
    if modo_def is not None and modo_def.tool_names:
        catalogo = _reordenar_priorizando(catalogo, modo_def.tool_names)
    return catalogo


def acotar_turnos(turnos: list[dict], presupuesto: int = CONTEXT_CARACTERES,
                  por_turno: int = CONTEXT_CARACTERES_POR_TURNO) -> list[dict]:
    """Return los turnos más recientes que caben en `presupuesto` caracteres, en orden.

    Se recorre de atrás hacia adelante —lo más reciente pesa más— y se corta cuando ya no
    cabe el siguiente. Un turno más largo que `por_turno` se recorta por el final con una
    marca, en vez de descartarse: un mensaje largo pegado por el usuario es justamente lo
    que después va a pedir que se mejore.
    """
    elegidos: list[dict] = []
    usado = 0
    for turno in reversed(turnos):
        if not isinstance(turno, dict):
            continue
        contenido = str(turno.get("content") or "")
        if len(contenido) > por_turno:
            contenido = contenido[:por_turno] + " [...]"
        if usado + len(contenido) > presupuesto and elegidos:
            break
        elegidos.append({**turno, "content": contenido})
        usado += len(contenido)
    elegidos.reverse()
    return elegidos


def _load_prior_turns(agent_name: str, user_id: str) -> list[dict]:
    """Return los últimos turnos ya cerrados de `agent_context` (CA-22), acotados por tamaño.

    Se lee UNA sola vez, antes del bucle: las dos escrituras de contexto ocurren al final
    de `run()`, así que lo leído es estrictamente anterior al turno en curso. Un fallo de
    la DB de contexto no puede tumbar el loop — se sigue sin historial.

    Es el respaldo para los canales sin conversación propia (voz, CLI). El escritorio pasa
    los turnos de la conversación ABIERTA por `prior_turns`, porque este contexto es por
    usuario y mezclaba lo último de cualquier conversación con la actual.
    """
    try:
        context = agent_context_manager.get_context(agent_name, user_id)
        conversation = getattr(context, "conversation", None)
        if not isinstance(conversation, list):
            return []
        return acotar_turnos([t for t in conversation[-CONTEXT_TURNS:] if isinstance(t, dict)])
    except Exception as e:
        logger.warning(f"No se pudo leer el contexto previo de {agent_name}/{user_id}: {e}")
        return []


def _tope_de_salida_del_canal(canal):
    """Return el context manager que acota la salida en voz; en el resto, no acota nada."""
    if canal == ChannelType.VOICE:
        return tope_de_salida(MAX_TOKENS_VOZ)
    return tope_de_salida(MAX_TOKENS_SALIDA)


def _presupuesto_de_llamadas(modo_def: Optional[ModoComposer], canal) -> int:
    """Return cuántas llamadas al modelo puede gastar este turno (REQ-027/CA-13/14/15).

    `presupuesto = min(techo_del_canal, presupuesto_del_modo_o_default)`. El `min()` no
    recorta nada en la práctica —un `modo` solo llega desde el composer de escritorio—,
    pero está para que sea estructuralmente imposible que un canal remoto termine con 40
    llamadas si mañana alguien propaga un modo desde otro lado.

    La llamada de cierre NO sale de acá: va aparte, fuera del presupuesto (CA-30).
    """
    del_modo = modo_def.presupuesto if modo_def is not None else MAX_LLM_CALLS
    if canal == ChannelType.DESKTOP:
        return del_modo
    if canal in (ChannelType.TELEGRAM, ChannelType.DISCORD):
        return min(TECHO_CANAL_REMOTO_CON_STOP, del_modo)
    return min(TECHO_CANAL_NO_ESCRITORIO, del_modo)


def _encabezado_de_tarea(
    task: str, prior_turns: Optional[list[dict]], con_historial: bool,
) -> str:
    """La parte del prompt anterior al historial de herramientas (REQ-021/CA-22).

    `con_historial` decide entre "Mensaje actual del usuario:" y "Tarea original del
    usuario:". Es la misma distinción que hacía `_build_prompt()` antes de REQ-027, y es lo
    que permite que el aplanado de CA-07 salga byte a byte igual que antes sin retocar ni
    un string.
    """
    if not con_historial and not prior_turns:
        return task

    if prior_turns:
        lines = ["Turnos anteriores de esta conversación:"]
        for turn in prior_turns:
            role = "Usuario" if turn.get("role") == "user" else "Asistente"
            lines.append(f"- {role}: {turn.get('content', '')}")
        lines.append("")
        if not con_historial:
            lines.append(f"Mensaje actual del usuario: {task}")
            return "\n".join(lines)
        lines.append(f"Tarea original del usuario: {task}")
        lines.append("")
        lines.append("Acciones ya ejecutadas en este intento:")
        return "\n".join(lines)

    return "\n".join(
        [f"Tarea original del usuario: {task}", "", "Acciones ya ejecutadas en este intento:"]
    )


def _build_prompt(
    task: str, history: list[dict], prior_turns: Optional[list[dict]] = None,
) -> str:
    """Envoltorio de compatibilidad: firma y salida idénticas a las de antes de REQ-027.

    Ya no lo usa `run()` —desde REQ-027 el historial viaja nativo dentro de `messages`—,
    pero sigue siendo la definición de "cómo se ve un turno aplanado", y los tests que
    fijan ese texto (`test_ca22_*`) lo siguen ejerciendo tal cual (CA-10).
    """
    encabezado = _encabezado_de_tarea(task, prior_turns, bool(history))
    if not history:
        return encabezado
    lines = [encabezado]
    tool_history.lineas_de_historial(lines, history)
    return "\n".join(lines)


def _append_history_lines(lines: list[str], history: list[dict]) -> None:
    """Añade a `lines` el detalle de las tools ya ejecutadas y la instrucción de cierre.

    El cuerpo se mudó a `core/tool_history.py` para que exista UNA sola copia del texto:
    si derivara entre el camino nativo y el aplanado, dos proveedores verían historiales
    distintos del mismo turno. Se conserva el nombre porque hay tests que lo llaman.
    """
    tool_history.lineas_de_historial(lines, history)


def _mensajes_del_turno(
    task: str, prior_turns: list[dict], historial: list[dict],
) -> list[dict]:
    """Return lo que se le manda a `generate_response()` en esta vuelta (REQ-027/CA-01).

    El encabezado como único mensaje plano, seguido del historial neutral de herramientas.
    Los adaptadores de `ai/llm_provider.py` lo traducen al protocolo de cada proveedor —o
    lo aplanan a texto si la llamada no lleva herramientas.
    """
    encabezado = _encabezado_de_tarea(task, prior_turns, bool(historial))
    return [{"role": "user", "content": encabezado}] + historial


def ejecutar_vuelta(
    tool_calls: list, numero_de_vuelta: int, canal, user_id: str, task: str,
    cancelable: bool = True, control=None,
) -> tuple[list[dict], list[dict], Optional[str]]:
    """Ejecuta EN SECUENCIA todas las tool calls de una vuelta (REQ-027/CA-20 a CA-27).

    Return `(llamadas, resultados, motivo_de_denegacion)`.

    Pública desde REQ-044: es la misma vuelta para el escritorio y para Telegram/Discord
    (`ai/claude_brain.py`), que antes ejecutaba solo `tool_calls[0]` y descartaba el resto.
    `cancelable=False` es para el camino remoto: el botón de detener es del escritorio, y
    `abortar_si_cancelado()` mira un estado de proceso — un turno de escritorio cancelado
    no puede abortar un mensaje de Telegram que corre en otro hilo. Desde REQ-047 ese
    camino pasa su propio punto de control en `control` (un callable `(donde) -> None` que
    levanta `TurnoCancelado`, ver `core/cancelacion.control_remoto`): `/detener` frena el
    turno de ESE usuario entre dos herramientas, igual que el botón en el escritorio.

    `llamadas` y `resultados` tienen SIEMPRE la misma longitud y los mismos ids, incluso
    cuando la secuencia se cortó: a las que no llegaron a ejecutarse se les registra un
    resultado sintético. No es cortesía con el modelo — Anthropic y el SDK `openai`
    rechazan con 400 un turno donde un `tool_use` se queda sin su `tool_result` (D-6 de
    arquitectura-027.md). Sin esto, la llamada de cierre pasaría los tests con mocks y
    fallaría siempre contra un proveedor real.

    Nunca ejecuta en paralelo: una confirmación humana concurrente con otra ejecución es
    exactamente lo que el gate de REQ-005 no debe permitir.

    INVARIANTE DE SEGURIDAD: `canal` y `user_id` son los del caller confiable y se
    inyectan en CADA una de las N llamadas, nunca solo en la primera — el modelo no
    negocia sobre qué canal ni como qué usuario se ejecuta nada.
    """
    llamadas: list[dict] = []
    resultados: list[dict] = []
    denegacion: Optional[str] = None

    for i, call in enumerate(tool_calls):
        # El id lo normaliza el bucle y no el adaptador (D-5): si viniera vacío del modelo
        # —pasa con modelos gratuitos de OpenRouter— y cada adaptador se inventara el suyo,
        # no habría con qué emparejar la llamada con su resultado. Además, así el mismo id
        # sobrevive a un cambio de proveedor a mitad de turno (REQ-022).
        id_llamada = call.id or f"tc_{numero_de_vuelta}_{i}"
        params = dict(call.arguments or {})
        params["channel"] = canal.value
        params["user_id"] = user_id
        # Lo que dijo el humano, TAL CUAL. Igual que `channel` y `user_id`, lo pone el
        # caller y no el modelo: es un dato de la invocación, no un argumento negociable.
        # `dispatcher` lo usa como segundo intento cuando el modelo reformula la orden y la
        # reformulación no la reconoce el clasificador — ver `router/dispatcher.py`.
        params["texto_original"] = task
        llamadas.append(tool_history.bloque_llamada(id_llamada, call.name, params))

        if denegacion is not None:
            # CA-25: la denegación corta la secuencia. La herramienta no se ejecuta, pero
            # su resultado existe igual (D-6).
            resultados.append(
                tool_history.bloque_resultado(id_llamada, call.name, _NO_EJECUTADA)
            )
            continue

        # CA-27: el botón de detener se evalúa ENTRE herramientas, no solo entre vueltas.
        # Con varias herramientas por vuelta, esperar a la vuelta siguiente sería esperar a
        # que terminen todas.
        donde = f"reasoning_loop, vuelta {numero_de_vuelta}, antes de '{call.name}'"
        if control is not None:
            control(donde)
        elif cancelable:
            abortar_si_cancelado(donde)

        try:
            resultado = execute_tool(call.name, params, canal, user_id)
        except ActionDenied as e:
            denegacion = e.reason or "denegada"
            resultados.append(
                tool_history.bloque_resultado(
                    id_llamada, call.name, f"Denegada: {denegacion}"
                )
            )
            continue
        except Exception as e:
            # CA-26: una tool que falla no corta la secuencia — se informa como resultado
            # fallido y las demás siguen. Solo la denegación corta.
            logger.warning(f"Tool '{call.name}' falló en la vuelta {numero_de_vuelta}: {e}")
            resultado = f"Error ejecutando '{call.name}': {e}"

        resultados.append(tool_history.bloque_resultado(id_llamada, call.name, resultado))

    return llamadas, resultados, denegacion


#: Nombre anterior, conservado para los tests de REQ-027 que lo referencian.
_ejecutar_vuelta = ejecutar_vuelta


def _llamada_de_cierre(
    task: str, prior_turns: list[dict], historial: list[dict], instruccion: str,
    system_prompt: str, tarea: str, aviso: dict, canal=None, image_path: Optional[str] = None,
) -> Optional[str]:
    """Una última llamada al modelo SIN herramientas para que redacte con lo que reunió.

    Arma los mensajes del turno de escritorio y delega en `cerrar_sin_herramientas()`, que
    es la pieza que comparte con `ai/claude_brain.py` (REQ-044): el mismo contrato de
    cierre para los dos caminos.
    """
    return cerrar_sin_herramientas(
        _mensajes_del_turno(task, prior_turns, historial), instruccion,
        system_prompt, tarea, aviso, canal=canal, image_path=image_path,
    )


def cerrar_sin_herramientas(
    mensajes: list[dict], instruccion: str, system_prompt: str, tarea: str, aviso: dict,
    canal=None, image_path: Optional[str] = None,
) -> Optional[str]:
    """Una última llamada al modelo SIN herramientas sobre `mensajes` ya armados.

    Return el texto, o `None` si no sirve —proveedor caído, texto vacío, o una respuesta
    que igual trajo tool calls—, en cuyo caso el caller usa el mensaje enlatado de siempre
    (CA-31).

    Va con `tools=None` a propósito y no por ahorro: sin herramientas, la garantía de "no
    reintenta la acción denegada" es estructural y no depende de que el modelo obedezca una
    frase del prompt (CA-29). Está FUERA del presupuesto y es como máximo una por turno
    (CA-30), así que no puede encadenar.

    La instrucción se cuelga del último mensaje en vez de ir como un `user` aparte: con
    historial, el último mensaje es el de resultados —también de rol `user`— y Anthropic
    exige alternancia estricta de roles.
    """
    ultimo = mensajes[-1]
    if tool_history.es_estructurado(ultimo):
        mensajes = mensajes[:-1] + [tool_history.con_texto_agregado(ultimo, instruccion)]
    else:
        mensajes = mensajes[:-1] + [
            {**ultimo, "content": f"{ultimo.get('content', '')}\n\n{instruccion}"}
        ]

    # `permitido()`: esto ES la respuesta al usuario, así que se muestra mientras se
    # escribe, igual que la de una vuelta normal.
    with streaming.permitido(), _tope_de_salida_del_canal(canal):
        respuesta = generate_response(
            mensajes, system_prompt, image_path=image_path, tools=None, tarea=tarea, aviso=aviso,
        )

    if isinstance(respuesta, LLMToolResponse):
        # Sin `tools` no debería pedir herramientas; si igual lo hace, no hay respuesta que
        # mostrar y se cae al enlatado en vez de inventar una.
        texto = respuesta.text if not respuesta.tool_calls else None
    else:
        texto = respuesta

    if not texto or es_respuesta_de_fallo(texto):
        return None
    return texto


def run(task: str, channel, user_id: str = "default", agent_name: str = "reasoning_loop",
        estado: Optional[dict] = None, modo: Optional[str] = None,
        prior_turns: Optional[list[dict]] = None,
        image_path: Optional[str] = None) -> str:
    """Punto de entrada del bucle de razonamiento.

    `estado`, si se pasa, es un dict que el bucle RELLENA: `{"denied": True}` cuando corto
    por una accion denegada, y `{"sin_modelo": True}` cuando no consiguio hablar con ningun
    proveedor. Lo que retorna sigue siendo el texto de siempre
    (CA-08), asi que ningun caller existente cambia; existe porque desde que el modelo lee
    primero, una denegacion llega por aca y no por el resolver que la ejecutaba, y
    `core/resolution.py` necesita saberlo para no colgarle recordatorios ni repreguntas a
    un mensaje de denegacion.

    INVARIANTE DE SEGURIDAD: `channel`/`user_id` son SIEMPRE los que pasa el caller
    confiable (nunca argumentos que el LLM decidió) — mismo invariante que
    `security_manager.py:239-246` y el patrón de `core/resolution.py::_try_intent()`. Los
    argumentos de un tool call que el LLM proponga para `channel`/`user_id` (si los
    propusiera) se descartan siempre a favor de estos dos parámetros.

    `modo` (REQ-026): id del modo estratégico activo del composer de escritorio, o `None`.
    Se resuelve acá mismo con `get_mode()` (fail-safe: un id vacío o desconocido equivale
    a "sin modo") y de ahí salen tanto el catálogo priorizado como la `tarea` que rutea
    esta llamada.

    `image_path` (REQ-054): la imagen que el usuario adjuntó o pegó en ESTE turno, o
    `None`. Va en cada vuelta y en el cierre, igual que por Telegram (`ai/claude_brain.py`):
    `generate_response` la pega al último mensaje de texto del usuario (CA-09 de REQ-027),
    nunca al de resultados de herramientas, y con ella de por medio el enrutado va al
    `vision_provider`. Solo el turno en que llega la ve; en los siguientes queda el
    marcador «[Imagen adjunta: …]» en el texto.
    """
    modo_def = get_mode(modo)
    resolved_channel = security_manager.resolve_channel(channel)
    tools = _build_tool_list(resolved_channel, modo_def)
    presupuesto = _presupuesto_de_llamadas(modo_def, resolved_channel)

    # D-10: UNA vez por turno, no una por vuelta. Con presupuesto 40 eran 40 lecturas de
    # disco y 40 prefijos distintos —la fecha y la hora cambian al minuto—, o sea que se
    # anulaba el cacheo de prefijo justo en el turno mas caro.
    system_prompt = _build_system_prompt(modo_def)
    # `tarea`: por defecto "razonamiento" —es LA respuesta al usuario, con herramientas y
    # varias vueltas—, salvo que el modo activo fije la suya (REQ-026, solo Codigo e
    # Investigacion lo hacen; Flujos y Tareas necesitan el modelo general de varias
    # vueltas). Quien quiera mandarla a un modelo distinto del general —uno gratuito con
    # tool-calling, por ejemplo— lo configura en `task_providers` sin tocar el resto.
    tarea = modo_def.tarea if modo_def and modo_def.tarea else "razonamiento"

    #: REQ-027/CA-01 — el historial de herramientas del turno, en formato NEUTRAL
    #: (`core/tool_history.py`). Va dentro de `messages` y cada adaptador lo traduce al
    #: protocolo de su proveedor, o lo aplana a texto si la llamada no lleva herramientas.
    #: Neutral y no ya traducido porque `generate_response()` puede cambiar de proveedor a
    #: mitad de turno por cooldown o respaldo (REQ-022).
    historial: list[dict] = []
    final_text: Optional[str] = None
    aviso_final: dict = {}   # REQ-022/CA-12 — se "fija" solo en la vuelta que gana
    ultimo_aviso: dict = {}  # REQ-027/CA-42 — el ultimo cambio visto, por si gana el cierre
    denegacion: Optional[str] = None
    # Los turnos de la conversación abierta, si el caller los trae (escritorio); si no, el
    # contexto por usuario de siempre. Lo que llega de fuera también se acota por tamaño.
    prior_turns = acotar_turnos(prior_turns) if prior_turns is not None \
        else _load_prior_turns(agent_name, user_id)

    if image_path:
        # REQ-054 — queda como paso del turno («1 paso · Mirando la imagen»): mirar una
        # imagen es algo que el agente hizo para contestar, igual que leer una página.
        progress_report(f"Mirando la imagen: {os.path.basename(image_path)}")

    for call_number in range(1, presupuesto + 1):
        # Punto de corte del boton de detener: antes de gastar otra llamada al modelo o
        # ejecutar otra herramienta. Es donde parar es seguro — no deja nada a medias.
        abortar_si_cancelado(f"reasoning_loop, vuelta {call_number}")

        # El silencio entre que el usuario pregunta y llega la respuesta era indistinguible
        # de un cuelgue. A partir de la segunda vuelta se numera: si el modelo encadena
        # herramientas, se ve que avanza en vez de parecer que se repite.
        progress_report("Pensando" if call_number == 1 else f"Pensando ({call_number})")

        aviso_cambio: dict = {}   # REQ-022/CA-12 — vacio otra vez en cada vuelta
        # `permitido()`: lo que salga de ESTA llamada es la respuesta al usuario y se
        # muestra mientras se escribe. Las herramientas que se ejecuten despues pueden
        # consultar al modelo por su cuenta (resumir un correo, leer una captura) y eso NO
        # tiene que aparecer en la burbuja del chat: quedan fuera del bloque.
        with streaming.permitido(), _tope_de_salida_del_canal(resolved_channel):
            response = generate_response(
                _mensajes_del_turno(task, prior_turns, historial), system_prompt,
                image_path=image_path,
                tools=tools,
                tarea=tarea,
                aviso=aviso_cambio,   # REQ-022/CA-12
            )
        if aviso_cambio:
            ultimo_aviso = aviso_cambio

        if not isinstance(response, LLMToolResponse):
            # CONFIRMADO 1 de REQ-007: degradacion silenciosa (proveedor sin tool-calling)
            # — texto plano, se acepta como respuesta final.
            final_text = response
            aviso_final = aviso_cambio
            break

        if not response.tool_calls:
            # El LLM respondio sin pedir ninguna tool: se acepta como final (caso borde de
            # SPEC — no confundir "no quiso usar herramientas" con "hay que insistir").
            final_text = response.text or f"No obtuve una respuesta útil del modelo{vocative()}."
            aviso_final = aviso_cambio
            break

        # REQ-027/CA-20: se ejecutan TODAS las que pidio, en orden y en secuencia. Antes
        # se ejecutaba solo `tool_calls[0]` y el resto se descartaba, asi que el modelo
        # tenia que volver a pedirlas gastando otra vuelta entera del presupuesto.
        llamadas, resultados, denegacion = ejecutar_vuelta(
            response.tool_calls, call_number, resolved_channel, user_id, task,
        )
        historial.append(tool_history.mensaje_de_llamadas(response.text, llamadas))
        historial.append(tool_history.mensaje_de_resultados(resultados))   # CA-23

        if denegacion is not None:
            # CA-32: se marca ANTES del cierre. `core/resolution.py` necesita saber que
            # hubo denegacion aunque el cierre redacte una respuesta normal.
            if estado is not None:
                estado["denied"] = True
            break

    if final_text is None:
        # CA-28/CA-29: una ultima llamada SIN herramientas para redactar con lo reunido.
        # Esta FUERA del presupuesto y es como maximo una por turno (CA-30). Antes, agotar
        # el presupuesto devolvia el texto enlatado y tiraba a la basura todas las vueltas
        # de trabajo ya pagadas.
        aviso_cierre: dict = {}
        cierre = _llamada_de_cierre(
            task, prior_turns, historial,
            _INSTRUCCION_CIERRE_DENEGACION if denegacion is not None
            else _INSTRUCCION_CIERRE_PRESUPUESTO,
            system_prompt, tarea, aviso_cierre, resolved_channel, image_path=image_path,
        )
        if cierre:
            final_text = cierre
            aviso_final = aviso_cierre or ultimo_aviso   # CA-42
        elif denegacion is not None:
            # CA-31: el cierre no sirvio — el texto literal de siempre.
            final_text = f"⛔ No puedo ejecutar esa acción{vocative()}: {denegacion}."
        else:
            final_text = (
                f"No pude completar la tarea en el número de intentos disponibles{vocative()}. "
                "¿Quiere que lo intente de otra forma?"
            )

    # Sin proveedor no hubo razonamiento, hubo un error de red o de configuración. Se
    # avisa para que `core/resolution.py` pueda intentar el camino local: sin conexión,
    # "sube el volumen" tiene que seguir funcionando.
    if estado is not None and es_respuesta_de_fallo(final_text):
        estado["sin_modelo"] = True

    # REQ-022/CA-12/13/14/16/17: se evalúa DESPUÉS de `es_respuesta_de_fallo()` — cuando
    # hubo un swap exitoso, `final_text` ya es una respuesta real (nunca `SIN_PROVEEDOR`),
    # así que el orden no cambia ese chequeo en ningún caso. Forma corta en VOICE, larga
    # (con proveedor y modelo) en cualquier otro canal.
    final_text = con_aviso_de_cambio(
        final_text, aviso_final, corto=(resolved_channel == ChannelType.VOICE),
    )

    # CA-10: un solo par user/assistant por invocación completa del loop, sin importar
    # cuántas iteraciones internas hubo.
    agent_context_manager.update_context(agent_name, user_id, {"role": "user", "content": task})
    agent_context_manager.update_context(
        agent_name, user_id, {"role": "assistant", "content": final_text[:MAX_RESPUESTA_GUARDADA]}
    )

    # REQ-071: se anota cuánto midió la respuesta —solo la longitud, el canal y si hubo
    # herramientas; nunca el texto—. Es lo que permite saber si el contrato de economía
    # sirvió, en vez de volver a pedir brevedad en prosa y no enterarse.
    estilo_respuesta.registrar(
        final_text, canal=getattr(resolved_channel, "value", str(resolved_channel)),
        con_herramientas=bool(historial),
    )

    return final_text
