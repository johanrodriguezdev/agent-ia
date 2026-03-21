from sentence_transformers import SentenceTransformer

# Load model locally optimized for CPU. It takes a second during first boot to download.
_model = None

def get_model():
    global _model
    if _model is None:
        print("\n[🧠 Cargando modelo semántico 'all-MiniLM-L6-v2' en memoria RAM (CPU)...]")
        # cpu para que no colapse sistemas sin buena GPU
        _model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
    return _model

def create_embedding(text: str) -> list[float]:
    """Crea y retorna el embedding (vector numérico multidimensional) del texto dado."""
    model = get_model()
    # encode as numpy array para eficiencia, luego convertimos a list nativa.
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()
