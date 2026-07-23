# Regla: Estilo Python — O.R.I.O.N.

## Convenciones generales
- Python 3.12+. Usar type hints en todas las funciones nuevas.
- Naming: `snake_case` para funciones y variables, `PascalCase` para clases, `UPPER_CASE` para constantes.
- Imports en orden: estándar → third-party → locales. Separar grupos con una línea en blanco.
- Longitud máxima de línea: 100 caracteres.

## Type hints
```python
from typing import Optional, List, Dict, Any

def process_command(text: str, context: Optional[Dict[str, Any]] = None) -> str:
    ...
```

## Manejo de errores
- **Nunca** usar `except: pass` o `except Exception: pass` sin logging.
- Siempre registrar el error antes de ignorarlo:
```python
try:
    result = risky_operation()
except Exception as e:
    logger.error(f"fallo en risky_operation: {e}")
    return ""
```

## Estructura de archivos
- Una clase principal por archivo. Clases auxiliares pequeñas permitidas en el mismo archivo.
- `__init__.py` solo para exports, sin lógica.

## Docstrings
- Funciones públicas: docstring de una línea o varias si es necesario.
- Funciones privadas (`_`): docstring opcional si la lógica no es obvia.
- Formato: imperativo ("Return X", no "Returns X").

## Logging
- Usar el módulo `logging` de Python, no `print()`.
- Configurar una vez al inicio del módulo o usar un logger compartido:
```python
import logging
logger = logging.getLogger(__name__)
```

## Seguridad en código
- No hardcodear API keys, tokens o contraseñas. Leer de variables de entorno o `.env`.
- Acciones destructivas (shutdown, borrar archivos) deben pedir confirmación.
- Validar inputs en handlers y skills antes de usarlos en `os.system()` o `subprocess`.
