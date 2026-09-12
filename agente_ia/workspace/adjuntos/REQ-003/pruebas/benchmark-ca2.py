"""REQ-003/CA2 — ¿la búsqueda semántica tarda menos de 50 ms con 10.000+ recuerdos?

Nadie lo midió nunca. Se arma un índice de 10.000 embeddings falsos en memoria, sin tocar
la base real ni cargar el modelo de embeddings (que tardaría minutos y no es lo que se mide).
"""
import os
import sys
import tempfile
import time

import numpy as np

# Ruta relativa: este archivo vive en workspace/adjuntos/REQ-003/pruebas/, cuatro
# niveles por debajo de la raíz del proyecto.
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..")))

import ai.memory_manager as mm

# Base temporal: el benchmark no puede tocar unified_memory.db del usuario.
TMP = tempfile.mkdtemp(prefix="bench_mem_")
mm.DB_PATH = os.path.join(TMP, "unified_memory.db")  # nunca la base real

memoria = mm.UnifiedMemory()

DIMENSION = 384          # la del modelo que usa el proyecto (all-MiniLM)
CANTIDAD = 10_000

rng = np.random.default_rng(42)
vectores = rng.random((CANTIDAD, DIMENSION), dtype=np.float32)

memoria._embeddings = [v for v in vectores]
memoria._embedding_ids = list(range(1, CANTIDAD + 1))
memoria._embedding_user_ids = ["default"] * CANTIDAD

# El modelo real no se carga: lo que se mide es la búsqueda, no la codificación.
consulta = rng.random(DIMENSION, dtype=np.float32)
memoria._get_embedding = lambda texto: consulta

print(f"indice: {CANTIDAD} recuerdos x {DIMENSION} dimensiones")
print(f"memoria del indice: {vectores.nbytes / 1024 / 1024:.1f} MB\n")

# Una primera para no medir el calentamiento de numpy.
memoria.search_semantic("consulta de calentamiento", threshold=0.99)

tiempos = []
for _ in range(20):
    inicio = time.perf_counter()
    memoria.search_semantic("cuando fue la reunion con el banco", threshold=0.99)
    tiempos.append((time.perf_counter() - inicio) * 1000)

tiempos.sort()
print(f"  mediana : {tiempos[len(tiempos) // 2]:.1f} ms")
print(f"  p95     : {tiempos[int(len(tiempos) * 0.95) - 1]:.1f} ms")
print(f"  peor    : {tiempos[-1]:.1f} ms")
print(f"\n  CA2 (<50 ms): {'CUMPLE' if tiempos[int(len(tiempos) * 0.95) - 1] < 50 else 'NO CUMPLE'}")
