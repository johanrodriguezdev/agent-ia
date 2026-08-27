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
        # cpu para que no colapse sistemas sin buena GPU
        _model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
    return _model

def create_embedding(text: str) -> list[float]:
    """Crea y retorna el embedding (vector numérico multidimensional) del texto dado."""
    model = get_model()
    # encode as numpy array para eficiencia, luego convertimos a list nativa.
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()
