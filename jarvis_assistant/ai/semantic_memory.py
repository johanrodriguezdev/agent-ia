import sqlite3
import json
import os
import numpy as np
from ai.embedding_engine import create_embedding

DB_PATH = os.path.join(os.path.dirname(__file__), 'semantic_memory.db')

def _init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS semantic_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            embedding_json TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

# Llamado de inicialización para que configure la BD cuando se importa el módulo
_init_db()

def cosine_similarity(v1, v2):
    """Calcula la distancia de cosenos entre dos vectores de representación lineal."""
    dot_product = np.dot(v1, v2)
    norm_a = np.linalg.norm(v1)
    norm_b = np.linalg.norm(v2)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot_product / (norm_a * norm_b))

def store_memory(text: str):
    """Guarda un texto y su representación semántica vectorial en SQLite."""
    if not text or not text.strip():
        return
        
    try:
        embedding = create_embedding(text)
        embedding_str = json.dumps(embedding)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO semantic_memories (text, embedding_json) VALUES (?, ?)",
            (text, embedding_str)
        )
        conn.commit()
    except Exception as e:
        print(f"[Aviso] No se pudo guardar memoria semántica en '{DB_PATH}': {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def search_similar_memory(query: str, threshold: float = 0.75) -> str:
    """
    Busca el recuerdo más similar en la tabla semántica calculando la similitud del coseno.
    Retorna el texto exacto recuperado de la base de datos si su 'score' supera el umbral (default 0.75).
    """
    if not query or not query.strip():
        return ""
        
    try:
        query_embedding = create_embedding(query)
        v1 = np.array(query_embedding)
        
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT text, embedding_json FROM semantic_memories")
        rows = cursor.fetchall()
        
        best_match_text = ""
        highest_score = -1.0
        
        for text, emb_json in rows:
            memory_embedding = json.loads(emb_json)
            v2 = np.array(memory_embedding)
            score = cosine_similarity(v1, v2)
            
            if score > highest_score:
                highest_score = score
                best_match_text = text
                
        if highest_score >= threshold:
            print(f"[🧠 Vínculo Semántico Detectado | Exactitud de Concepto: {highest_score*100:.2f}%]")
            return best_match_text
            
        return ""
    except Exception as e:
        print(f"[Aviso] Falló la búsqueda de memoria semántica: {e}")
        return ""
    finally:
        if 'conn' in locals():
            conn.close()
    
    return ""
