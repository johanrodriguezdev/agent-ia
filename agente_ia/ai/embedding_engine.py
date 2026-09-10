import logging

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Load model locally optimized for CPU. It takes a second during first boot to download.
_model = None

def get_model():
    global _model
    if _model is None:
        # Antes esto era un `print()` con un emoji. En una consola cp1252 —la de Windows por
        # defecto— ese print lanzaba UnicodeEncodeError, la carga del modelo moría con él, y
        # `create_embedding()` fallaba en silencio: la búsqueda semántica devolvía cero
        # resultados SIEMPRE, con la base llena de vectores perfectamente válidos.
        # `logging` no arrastra ese fallo y además es lo que pide python-style.md.
        logger.info("Cargando modelo semántico 'all-MiniLM-L6-v2' en RAM (CPU)...")
        # cpu para que no colapse sistemas sin buena GPU.
        #
        # `local_files_only=True` primero: sin eso, cada arranque sale a huggingface.co a
        # verificar el cache aunque el modelo ya esté descargado —~20 peticiones HTTP y 45
        # segundos medidos en un arranque real (log del 2026-09-03)— y sin conexión se
        # queda esperando a que expiren los timeouts. Con el modelo ya en cache, esto lo
        # resuelve en disco y no toca la red.
        #
        # La primera vez de todas no hay cache: ahí falla y se cae a la descarga normal,
        # que es exactamente lo que hacía antes.
        try:
            _model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu', local_files_only=True)
            logger.info("Modelo semántico cargado desde el caché local (sin red)")
        except Exception as e:
            logger.info(f"Modelo no disponible en caché ({e}); se descarga del hub")
            _model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
    return _model

def create_embedding(text: str) -> list[float]:
    """Crea y retorna el embedding (vector numérico multidimensional) del texto dado."""
    model = get_model()
    # encode as numpy array para eficiencia, luego convertimos a list nativa.
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def create_embeddings(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Crea los embeddings de varios textos de una vez. Return uno por cada entrada.

    Existe para el índice de código (REQ-034): indexar un repositorio son miles de
    fragmentos, y llamar `create_embedding()` uno por uno desperdicia la mayor parte del
    tiempo en encender y apagar el modelo para cada texto. En lote, el modelo aprovecha la
    vectorización y la diferencia es de un orden de magnitud.

    Con la lista vacía devuelve lista vacía sin cargar el modelo: indexar un repositorio
    donde no cambió nada no tiene por qué costar los segundos de carga.
    """
    if not texts:
        return []
    model = get_model()
    matriz = model.encode(texts, convert_to_numpy=True, batch_size=batch_size,
                          show_progress_bar=False)
    return [vector.tolist() for vector in matriz]
