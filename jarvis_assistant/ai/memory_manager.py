import sqlite3
import os
import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), 'memory.db')

# Memoria de sesión en RAM (se borra al apagar Jarvis, útil para retención inmediata)
SESSION_MEMORY = []

def _init_db():
    """Inicia la tabla 'memories' en sqlite3 si no está creada aún."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_input TEXT NOT NULL,
            jarvis_response TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Llamado de inicialización para que configure la BD cuando se importa el módulo
_init_db()

def save_memory(user_input: str, response: str):
    """Guarda la interacción en RAM (sesión) y presiste en la tabla memories (SQLite)."""
    if not user_input or not response:
         return
         
    # 1. Guardar en RAM
    SESSION_MEMORY.append({
        "user_input": user_input,
        "jarvis_response": response,
        "timestamp": datetime.datetime.now().isoformat()
    })
         
    # 2. Guardar en Persistencia SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO memories (user_input, jarvis_response, timestamp) VALUES (?, ?, ?)",
            (user_input, response, datetime.datetime.now().isoformat())
        )
        conn.commit()
    except Exception as e:
        print(f"[Aviso] No se pudo guardar recuerdo en memory.db: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def search_memory(query: str) -> str:
    """
    Busca contexto prioritariamente en la memoria RAM (sesión actual).
    Si no lo encuentra, consulta el historial SQLite (conversaciones importantes pasadas).
    """
    query_lower = query.lower()
    
    # 1. Búsqueda primero en RAM (Más rápido y reciente de esta sesión)
    for memory in reversed(SESSION_MEMORY):
        if query_lower in memory["user_input"].lower() or query_lower in memory["jarvis_response"].lower():
            return f"{memory['jarvis_response']} (Recuerdo de esta sesión RAM)"

    # 2. Búsqueda en disco SQLite pasado
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        query_like = f"%{query}%"
        cursor.execute(
            "SELECT jarvis_response FROM memories WHERE user_input LIKE ? OR jarvis_response LIKE ? ORDER BY timestamp DESC LIMIT 1",
            (query_like, query_like)
        )
        row = cursor.fetchone()
        
        if row:
            return f"{row[0]} (Recuperado de la base de datos persistente)"
        return ""
    except Exception as e:
        print(f"[Aviso] Falló la búsqueda en memoria.db: {e}")
        return ""
    finally:
        if 'conn' in locals():
            conn.close()
    
    return ""
