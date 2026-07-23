"""
router/dispatcher.py
Enruta cada intención al handler correcto.

✅ ACTUALIZADO: Se agregó Intent.CHAT como ruta explícita
   hacia el cerebro conversacional de Claude.
   Intent.UNKNOWN ahora también redirige a handle_chat
   en lugar de mostrar el mensaje genérico de error.
"""

from intent.intentions import Intent
from executor import handlers
from executor import system_action_handlers

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

    try:
        from skills.skill_manager import skill_manager
        if skill_manager.handles_intent(intent):
            return skill_manager.execute(intent, params)
    except Exception as e:
        print(f"[Dispatcher] Error ejecutando skill modular: {e}")

    handler = routes.get(intent, handlers.handle_unknown)
    return handler(params)


def dispatch_as_tool(params: dict) -> str:
    from intent.classifier import classify_command as classifier
    text = params.get("task", params.get("query", ""))
    if not text:
        return "No hay texto para procesar."

    try:
        intent, intent_params = classifier(text)
        intent_params["channel"] = params.get("channel", "desktop")
        return dispatch(intent, intent_params)
    except Exception as e:
        return f"Error en dispatch: {e}"
