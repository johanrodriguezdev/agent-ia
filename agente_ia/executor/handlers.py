"""
executor/handlers.py
Handlers que conectan las intenciones con las funciones reales del sistema.

✅ ACTUALIZADO: Se agregó handle_chat() que usa Claude como cerebro
   conversacional cuando el clasificador ML retorna Intent.UNKNOWN.
"""

from os_integration import process_mgr, browser, file_system, system_ctrl, wiki_api
from ai import memory_manager
from automation import pc_controller

# Importación condicional de memoria semántica
try:
    from ai import semantic_memory as _sem_mem
    SEMANTIC_MEMORY_AVAILABLE = True
except Exception:
    SEMANTIC_MEMORY_AVAILABLE = False

# ✅ NUEVO: Importación condicional del cerebro Claude
# Si la librería anthropic no está instalada o la API key no está configurada,
# Glass simplemente no usará este módulo sin romper el flujo.
try:
    from ai.claude_brain import ask_claude
    CLAUDE_AVAILABLE = True
except Exception:
    CLAUDE_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────
#  HANDLERS EXISTENTES (sin cambios)
# ──────────────────────────────────────────────────────────────────

def handle_open_app(params: dict) -> str:
    app_name = params.get("app_name", "")
    if app_name:
        return pc_controller.open_application(app_name)
    return "No entendí el nombre del programa a abrir."

def handle_close_app(params: dict) -> str:
    app_name = params.get("app_name", "")
    if app_name:
        return system_ctrl.close_app(app_name)
    return "No me indicó qué programa cerrar, Señor."

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

    if SEMANTIC_MEMORY_AVAILABLE:
        try:
            resultado_sem = _sem_mem.search_similar_memory(query, threshold=0.75)
            if resultado_sem:
                return f"Usando memoria semántica: {resultado_sem}"
        except Exception as e:
            print(f"[Aviso] Fallo en búsqueda semántica: {e}")

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


# ──────────────────────────────────────────────────────────────────
#  ✅ NUEVO: HANDLER DE CHAT INTELIGENTE (Claude como cerebro)
# ──────────────────────────────────────────────────────────────────

def handle_chat(params: dict) -> str:
    """
    Handler para Intent.UNKNOWN y cualquier pregunta conversacional.

    Flujo de fallback en cascada:
      1. Intenta buscar en memoria semántica (¿respondimos algo similar antes?)
      2. Si no encuentra nada relevante → pregunta a Claude
      3. Si Claude no está disponible → respuesta genérica elegante

    Args:
        params: dict con clave "query" conteniendo el texto original del usuario.
    """
    query = params.get("query", "")

    if not query:
        return "Dígame, Señor. Estoy a su disposición."

    # ── Paso 1: Buscar en memoria semántica ────────────────────────
    # Si Glass ya respondió algo muy similar antes, lo recupera sin
    # gastar tokens de API. Umbral más bajo (0.85) para mayor precisión.
    if SEMANTIC_MEMORY_AVAILABLE:
        try:
            resultado_sem = _sem_mem.search_similar_memory(query, threshold=0.85)
            if resultado_sem:
                print(f"[🧠 Memoria semántica] Respuesta recuperada sin API")
                return resultado_sem
        except Exception:
            pass

    # ── Paso 2: Consultar a Claude ─────────────────────────────────
    if CLAUDE_AVAILABLE:
        print(f"[🤖 Claude Brain] Procesando: '{query[:50]}...' " if len(query) > 50 else f"[🤖 Claude Brain] Procesando: '{query}'")
        response = ask_claude(query)
        return response

    # ── Paso 3: Fallback sin Claude ────────────────────────────────
    # Si anthropic no está instalado o no hay API key, Glass responde
    # de forma elegante en lugar de un error feo.
    return (
        "Señor, ese comando no está en mis protocolos actuales. "
        "Para activar mi inteligencia conversacional avanzada, "
        "configure la variable ANTHROPIC_API_KEY e instale la librería anthropic."
    )


# ──────────────────────────────────────────────────────────────────
#  HANDLER LEGACY (mantenido por compatibilidad)
# ──────────────────────────────────────────────────────────────────

def handle_unknown(params: dict) -> str:
    """
    Handler legacy para Intent.UNKNOWN.
    ✅ Ahora redirige automáticamente a handle_chat para respuesta inteligente
    en lugar de mostrar el mensaje de error anterior.
    """
    # Reconstruir el query desde params si viene del clasificador
    query = params.get("query", params.get("app_name", params.get("path", "")))
    return handle_chat({"query": query})
