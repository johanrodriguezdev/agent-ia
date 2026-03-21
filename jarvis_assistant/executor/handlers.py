from os_integration import process_mgr, browser, file_system, system_ctrl, wiki_api
from ai import memory_manager
from automation import pc_controller

# Importación condicional de memoria semántica (puede no estar cargada todavía)
try:
    from ai import semantic_memory as _sem_mem
    SEMANTIC_MEMORY_AVAILABLE = True
except Exception:
    SEMANTIC_MEMORY_AVAILABLE = False

def handle_open_app(params: dict) -> str:
    app_name = params.get("app_name", "")
    if app_name:
        # De acuerdo al requerimiento, la invocación de App ahora debe venir simulada por humano a la GUI
        return pc_controller.open_application(app_name)
    return "No entendí el nombre del programa a abrir."

def handle_search_web(params: dict) -> str:
    query = params.get("query", "")
    if query:
        return browser.search_google(query)
    return "Necesitas indicarme qué deseas buscar en internet."

def handle_open_folder(params: dict) -> str:
    path = params.get("path", "")
    return file_system.open_folder(path)
    
def handle_list_files(params: dict) -> str:
    path = params.get("path", ".")
    return file_system.list_files(path)
    
def handle_create_file(params: dict) -> str:
    filename = params.get("filename", "")
    if filename:
        return file_system.create_file(filename)
    return "Faltó proveer un nombre válido para el archivo."
    
def handle_get_time(params: dict) -> str:
    return system_ctrl.get_current_time()
    
def handle_sys_vol_up(params: dict) -> str:
    return system_ctrl.volume_up()

def handle_sys_vol_down(params: dict) -> str:
    return system_ctrl.volume_down()

def handle_sys_mute(params: dict) -> str:
    return system_ctrl.volume_mute()

def handle_take_screenshot(params: dict) -> str:
    return system_ctrl.take_screenshot()

def handle_sys_power_off(params: dict) -> str:
    return system_ctrl.shutdown_pc()

def handle_wikipedia_summary(params: dict) -> str:
    query = params.get("query", "")
    if query:
        return wiki_api.get_wikipedia_summary(query)
    return "¿Sobre qué tema deseas que consulte en Wikipedia?"

def handle_recall_memory(params: dict) -> str:
    query = params.get("query", "")
    if not query:
        return "¿Sobre qué quieres que haga el recuerdo?"

    # 1. Búsqueda semántica (por significado, no coincidencia exacta)
    if SEMANTIC_MEMORY_AVAILABLE:
        try:
            resultado_sem = _sem_mem.search_similar_memory(query, threshold=0.75)
            if resultado_sem:
                return f"Usando memoria semántica: {resultado_sem}"
        except Exception as e:
            print(f"[Aviso] Fallo en búsqueda semántica: {e}")

    # 2. Fallback a búsqueda por texto exacto (LIKE en SQLite)
    memoria_previa = memory_manager.search_memory(query)
    if memoria_previa:
        return f"Revisando mis registros, encontré esto: {memoria_previa}"

    return f"Mi memoria está en blanco con respecto a '{query}'. No encontré eventos pasados similares."

def handle_pc_click(params: dict) -> str:
    x = params.get("x")
    y = params.get("y")
    if x is not None and y is not None:
        return pc_controller.click_position(x, y)
    return "No me dijiste las coordenadas (X e Y) para hacer el clic, señor."

def handle_pc_type(params: dict) -> str:
    text = params.get("text", "")
    if text:
        return pc_controller.type_text(text)
    return "¿Qué deseas que escriba en el teclado?"

def handle_pc_scroll(params: dict) -> str:
    direction = params.get("direction", "abajo")
    return pc_controller.scroll(direction)

def handle_unknown(params: dict) -> str:
    return "Lo siento, ese comando no está programado ni reconocido en mis rutinas actuales."
