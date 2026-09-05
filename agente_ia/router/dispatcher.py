"""
router/dispatcher.py
Enruta cada intención al handler correcto.

✅ ACTUALIZADO: Se agregó Intent.CHAT como ruta explícita
   hacia el cerebro conversacional de Claude.
   Intent.UNKNOWN ahora también redirige a handle_chat
   en lugar de mostrar el mensaje genérico de error.
"""

import logging

from intent.intentions import Intent
from executor import handlers
from executor import system_action_handlers
from core.security_manager import security_manager, format_details, ActionDenied

logger = logging.getLogger(__name__)

def dispatch(intent: Intent, params: dict) -> str:
    routes = {
        Intent.OPEN_APP:      handlers.handle_open_app,
        Intent.CLOSE_APP:     handlers.handle_close_app,
        Intent.SEARCH_WEB:    handlers.handle_search_web,
        Intent.OPEN_FOLDER:   handlers.handle_open_folder,
        Intent.LIST_FILES:    handlers.handle_list_files,
        Intent.CREATE_FILE:   handlers.handle_create_file,
        Intent.GET_TIME:      handlers.handle_get_time,
        Intent.SYS_VOL_UP:    handlers.handle_sys_vol_up,
        Intent.SYS_VOL_DOWN:  handlers.handle_sys_vol_down,
        Intent.SYS_MUTE:      handlers.handle_sys_mute,
        Intent.TAKE_SCREENSHOT: handlers.handle_take_screenshot,
        Intent.SYS_POWER_OFF: handlers.handle_sys_power_off,
        Intent.WIKIPEDIA_SUMMARY: handlers.handle_wikipedia_summary,
        Intent.RECALL_MEMORY:     handlers.handle_recall_memory,
        Intent.PC_CLICK:      handlers.handle_pc_click,
        Intent.PC_TYPE:       handlers.handle_pc_type,
        Intent.PC_SCROLL:     handlers.handle_pc_scroll,
        Intent.CALCULATE:     system_action_handlers.handle_calculate,
        Intent.SEARCH_FILES:  system_action_handlers.handle_search_files,
        Intent.FOLDER_SIZE:   system_action_handlers.handle_folder_size,
        Intent.FIND_LARGEST:  system_action_handlers.handle_find_largest,
        Intent.SYSTEM_INFO:   system_action_handlers.handle_system_info,
        Intent.CPU_INFO:      system_action_handlers.handle_cpu_info,
        Intent.RAM_INFO:      system_action_handlers.handle_ram_info,
        Intent.CHAT:          handlers.handle_chat,
        Intent.UNKNOWN:       handlers.handle_unknown,
    }

    action_name = intent.value if hasattr(intent, "value") else str(intent)

    # Gate ÚNICO para los dos caminos de ejecución (skill moderna y handler legacy).
    # Se evalúa ANTES de elegir camino, a propósito: su decisión es la autoridad. Ninguna
    # ruta —incluida la de excepción de abajo— puede ejecutar nada si acá se denegó, ni
    # volver a preguntar si acá ya se confirmó.
    if not security_manager.require_confirmation(
        action_name,
        params.get("channel"),
        details=format_details(f"dispatch:{action_name}", params),
    ):
        raise ActionDenied(action_name, params.get("channel"), "denegado por security_manager")

    skill_manager = None
    try:
        from skills.skill_manager import skill_manager as _skill_manager
        skill_manager = _skill_manager
    except Exception as e:
        logger.error(f"subsistema de skills no disponible, se usa el handler legacy: {e}")

    if skill_manager is not None:
        try:
            if skill_manager.handles_intent(intent):
                return skill_manager.execute(intent, params)
        except Exception as e:
            # Fallback deliberado: una skill rota no debe dejar al usuario sin la función,
            # que es la razón por la que este camino de excepción existe. Lo que NO hace es
            # volver a pedir confirmación: la decisión del gate de arriba ya rige para esta
            # invocación, y si hubiera denegado ya habríamos retornado.
            logger.error(
                f"skill de '{action_name}' falló tras pasar el gate, "
                f"se cae al handler legacy: {e}"
            )

    handler = routes.get(intent, handlers.handle_unknown)
    return handler(params)


def dispatch_as_tool(params: dict) -> str:
    from intent.classifier import classify_command as classifier
    text = params.get("task", params.get("query", ""))
    if not text:
        return "No hay texto para procesar."

    try:
        intent, intent_params = classifier(text)

        # Segundo intento con lo que dijo el humano, tal cual.
        #
        # El modelo reformula: "Abre la calculadora" le llega al despachador como "abrir la
        # calculadora de windows". Y el clasificador esta entrenado con imperativos, que es
        # como habla la gente, asi que el infinitivo no lo reconoce — medido sobre el modelo
        # entrenado, "abre la calculadora" puntua +0.66 con margen 1.10, y "abrir la
        # calculadora" queda en -0.27. Con la reformulacion, la orden no se resolvia por
        # aca, el modelo probaba una herramienta mas pesada, y abrir la calculadora acababa
        # pidiendo confirmacion (logs/orion.log, 2026-09-04 22:15).
        original = str(params.get("texto_original", "")).strip()
        if intent == Intent.UNKNOWN and original and original != text:
            intent_bis, params_bis = classifier(original)
            if intent_bis != Intent.UNKNOWN:
                logger.info(
                    f"dispatcher: '{text[:40]}' no se reconocio; se usa lo que dijo el "
                    f"usuario: '{original[:40]}' -> {intent_bis}"
                )
                intent, intent_params = intent_bis, params_bis

        intent_params["channel"] = params.get("channel")
        return dispatch(intent, intent_params)
    except ActionDenied:
        # Se deja subir a proposito. `core/reasoning_loop.py` tiene una rama propia para
        # esto (CA-08): corta el bucle, no reintenta y avisa que fue denegada. Devolverla
        # como texto la convertia en "un resultado mas": el modelo la leia, la interpretaba
        # como un fallo tecnico y probaba otra herramienta para conseguir lo mismo. Con el
        # modelo leyendo primero, este es el camino normal de CUALQUIER orden, asi que la
        # diferencia dejo de ser teorica.
        raise
    except Exception as e:
        logger.warning(f"dispatch_as_tool fallo con '{text[:60]}': {e}")
        return f"Error en dispatch: {e}"
