import unicodedata
import re

# Mapa de variantes coloquiales comunes → forma canónica
_COLLOQUIAL_MAP = {
    # Números en letras → dígitos
    "cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4",
    "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9",
    "diez": "10", "once": "11", "doce": "12", "veinte": "20",
    "treinta": "30", "cuarenta": "40", "cincuenta": "50",
    "sesenta": "60", "setenta": "70", "ochenta": "80", "noventa": "90",
    "cien": "100", "ciento": "100", "doscientos": "200",
    "mil": "1000",

    # Operadores en letras → símbolos textuales
    "entre": "entre", "dividido por": "entre", "dividido entre": "entre",
    "por": "por", "veces": "por", "mas": "mas", "menos": "menos",

    # Alias de aplicaciones
    "notepad": "bloc de notas",
    "chrome": "google chrome",
    "cmd": "terminal",
}

def clean_text(text: str) -> str:
    """
    Pipeline completo de normalización de texto para el clasificador NLP:
    1. Minúsculas
    2. Elimina acentos / diacríticos
    3. Elimina caracteres especiales no alfanuméricos
    4. Comprime espacios múltiples
    """
    # 1. Minúsculas
    text = text.lower().strip()
    
    # 2. Eliminar acentos / diacríticos
    text = ''.join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    
    # 3. Eliminar caracteres especiales conservando espacios y dígitos
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    
    # 4. Comprimir espacios múltiples
    text = re.sub(r"\s+", " ", text).strip()
    
    return text


def normalize_numbers(text: str) -> str:
    """
    Convierte números escritos en letras a dígitos.
    Útil para comandos de cálculo: "cuanto es cuatro por cinco" → "cuanto es 4 por 5"
    """
    words = text.split()
    result = []
    for word in words:
        result.append(_COLLOQUIAL_MAP.get(word, word))
    return " ".join(result)


def extract_numbers(text: str) -> list[float]:
    """Extrae todos los números (enteros o decimales) de un texto en orden."""
    return [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)?", text)]


def extract_quoted(text: str) -> str:
    """Extrae texto entre comillas simples o dobles."""
    m = re.search(r'["\'](.+?)["\']', text)
    return m.group(1) if m else ""
