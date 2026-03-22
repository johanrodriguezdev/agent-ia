"""
intent/intentions.py
Enumeración de todas las intenciones que Glass puede reconocer.

✅ ACTUALIZADO: Se agregó Intent.CHAT para conversación general
   con Claude como cerebro conversacional.
"""

from enum import Enum

class Intent(Enum):
    # ── Aplicaciones y sistema de archivos ──────────────────────────
    OPEN_APP    = "OPEN_APP"
    SEARCH_WEB  = "SEARCH_WEB"
    OPEN_FOLDER = "OPEN_FOLDER"
    LIST_FILES  = "LIST_FILES"
    CREATE_FILE = "CREATE_FILE"
    
    # ── Sistema operativo ────────────────────────────────────────────
    GET_TIME      = "GET_TIME"
    SYS_VOL_UP    = "SYS_VOL_UP"
    SYS_VOL_DOWN  = "SYS_VOL_DOWN"
    SYS_MUTE      = "SYS_MUTE"
    TAKE_SCREENSHOT = "TAKE_SCREENSHOT"
    SYS_POWER_OFF = "SYS_POWER_OFF"
    
    # ── Conocimiento e información ───────────────────────────────────
    WIKIPEDIA_SUMMARY = "WIKIPEDIA_SUMMARY"
    RECALL_MEMORY     = "RECALL_MEMORY"
    TEACH_COMMAND     = "TEACH_COMMAND"
    
    # ── Control del PC ───────────────────────────────────────────────
    PC_CLICK  = "PC_CLICK"
    PC_TYPE   = "PC_TYPE"
    PC_SCROLL = "PC_SCROLL"
    
    # ── Agente autónomo ──────────────────────────────────────────────
    AUTOPILOT = "AUTOPILOT"
    
    # ── System Actions (sin simulación de GUI) ───────────────────────
    CALCULATE    = "CALCULATE"
    SEARCH_FILES = "SEARCH_FILES"
    FOLDER_SIZE  = "FOLDER_SIZE"
    FIND_LARGEST = "FIND_LARGEST"
    SYSTEM_INFO  = "SYSTEM_INFO"
    CPU_INFO     = "CPU_INFO"
    RAM_INFO     = "RAM_INFO"
    
    # ✅ NUEVO: Chat conversacional con Claude
    # Se activa cuando el usuario hace una pregunta abierta, charla,
    # o cualquier cosa que el clasificador ML no reconoce como comando.
    # Ejemplos: "¿cómo mejoro mi código?", "cuéntame sobre Python",
    #           "¿qué hago si mi PC está lenta?", "háblame de IA"
    CHAT = "CHAT"
    
    # ── Fallback ─────────────────────────────────────────────────────
    # UNKNOWN ahora redirige a Claude en handlers.py en lugar de
    # mostrar el mensaje genérico de error anterior.
    UNKNOWN = "UNKNOWN"
