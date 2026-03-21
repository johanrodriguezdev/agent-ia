from intent.intentions import Intent
from executor import handlers
from executor import system_action_handlers

def dispatch(intent: Intent, params: dict) -> str:
    """Enruta la intención al handler dinámico correcto."""
    
    # Patrón de Command Router
    routes = {
        Intent.OPEN_APP: handlers.handle_open_app,
        Intent.SEARCH_WEB: handlers.handle_search_web,
        Intent.OPEN_FOLDER: handlers.handle_open_folder,
        Intent.LIST_FILES: handlers.handle_list_files,
        Intent.CREATE_FILE: handlers.handle_create_file,
        
        # Nuevas rutas
        Intent.GET_TIME: handlers.handle_get_time,
        Intent.SYS_VOL_UP: handlers.handle_sys_vol_up,
        Intent.SYS_VOL_DOWN: handlers.handle_sys_vol_down,
        Intent.SYS_MUTE: handlers.handle_sys_mute,
        Intent.TAKE_SCREENSHOT: handlers.handle_take_screenshot,
        Intent.SYS_POWER_OFF: handlers.handle_sys_power_off,
        Intent.WIKIPEDIA_SUMMARY: handlers.handle_wikipedia_summary,
        Intent.RECALL_MEMORY: handlers.handle_recall_memory,
        
        Intent.PC_CLICK: handlers.handle_pc_click,
        Intent.PC_TYPE: handlers.handle_pc_type,
        Intent.PC_SCROLL: handlers.handle_pc_scroll,
        
        # System Actions (funciones reales sin simulación de GUI)
        Intent.CALCULATE:    system_action_handlers.handle_calculate,
        Intent.SEARCH_FILES: system_action_handlers.handle_search_files,
        Intent.FOLDER_SIZE:  system_action_handlers.handle_folder_size,
        Intent.FIND_LARGEST: system_action_handlers.handle_find_largest,
        Intent.SYSTEM_INFO:  system_action_handlers.handle_system_info,
        Intent.CPU_INFO:     system_action_handlers.handle_cpu_info,
        Intent.RAM_INFO:     system_action_handlers.handle_ram_info,
        
        Intent.UNKNOWN: handlers.handle_unknown
    }
    
    # Obtenemos el handler seguro por la intención detectada
    handler = routes.get(intent, handlers.handle_unknown)
    
    # Lo ejecutamos y retornamos la respuesta final
    return handler(params)
