"""REQ-034 — Medicion real: indexar codigo de verdad con el modelo de verdad."""
import os
import sys
import tempfile
import time

# Ruta relativa: este archivo vive cuatro niveles por debajo de la raiz.
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..")))

import core.code_index as ci

# La base va a un temporal: el benchmark no deja rastro en el proyecto.
TMP = tempfile.mkdtemp(prefix="bench_idx_")
ci.DB_PATH = os.path.join(TMP, "code_index.db")

RAIZ = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "core"))

# El modelo se carga ANTES de medir: si no, sus segundos se cuentan como
# indexado y la cifra que sale es tres veces peor que la real.
from ai.embedding_engine import get_model
get_model()

print(f"indexando: {RAIZ}")
print("(carga el modelo all-MiniLM real, la primera vez tarda unos segundos)\n")

t0 = time.perf_counter()
r1 = ci.indexar(RAIZ, tope_segundos=600)
t1 = time.perf_counter() - t0

print("== primer indexado ==")
print(f"  archivos      : {r1.archivos_nuevos}")
print(f"  fragmentos    : {r1.fragmentos}")
print(f"  tiempo        : {t1:.1f}s")
if t1 > 0 and r1.fragmentos:
    print(f"  ritmo         : {r1.fragmentos / t1:.0f} fragmentos/s")
tamano = os.path.getsize(ci.DB_PATH) / 1024 / 1024
print(f"  base en disco : {tamano:.1f} MB")
if r1.archivos_nuevos:
    print(f"  proyeccion 1000 archivos: {t1 / r1.archivos_nuevos * 1000 / 60:.1f} min")

print("\n== reindexar sin cambios ==")
t0 = time.perf_counter()
r2 = ci.indexar(RAIZ)
print(f"  sin cambios: {r2.archivos_sin_cambios} archivos en {time.perf_counter() - t0:.2f}s")

print("\n== busquedas reales (en castellano, sobre codigo en ingles/espanol) ==")
CONSULTAS = [
    "donde se decide si una accion necesita confirmacion del usuario",
    "como se guarda la memoria en la base de datos",
    "el confinamiento de rutas de los archivos",
    "reconexion del microfono cuando falla",
]
for consulta in CONSULTAS:
    t0 = time.perf_counter()
    resultados = ci.buscar(consulta, RAIZ, top_k=3)
    ms = (time.perf_counter() - t0) * 1000
    print(f"\n  «{consulta}»  ({ms:.0f} ms)")
    for r in resultados:
        print(f"    {os.path.basename(r.ruta)}:{r.linea_inicio}-{r.linea_fin} "
              f"[{r.simbolo or '-'}] {r.puntaje:.2f}")
