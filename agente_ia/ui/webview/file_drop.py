"""
ui/webview/file_drop.py
`validate_dropped_file()` — validación del archivo soltado nativamente sobre `MainWindow`
(REQ-015/CA-23, arquitectura-015.md §5.3). Solo stdlib, sin dependencias nuevas.

Chromium no expone la ruta absoluta de un `File` soltado vía la API web estándar — el
drop se captura a nivel de `QMainWindow` (`QDropEvent.mimeData().urls()`, rutas reales),
y esta función es la única responsable de decidir si esa ruta se acepta.
"""

import logging
import os
from typing import Tuple

logger = logging.getLogger(__name__)

# Allowlist deliberada (no denylist) — extensiones de texto/documento/imagen razonables
# para adjuntar a una conversación. Todo lo demás se rechaza por defecto.
ALLOWED_EXTENSIONS = frozenset({
    ".txt", ".md", ".py", ".json", ".csv", ".log",
    ".pdf", ".docx", ".xlsx",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
})

# 20 MB — suficiente para adjuntos razonables sin dejar que un archivo enorme bloquee al
# leerlo más adelante.
MAX_SIZE_BYTES = 20 * 1024 * 1024


def validate_dropped_file(path: str) -> Tuple[bool, str]:
    """Valida un archivo soltado nativamente. Retorna `(aceptado, motivo)`.

    `motivo` es siempre un string legible: razón del rechazo, o cadena vacía si fue
    aceptado. Nunca lanza — cualquier error de filesystem se trata como rechazo.
    """
    if not path:
        return False, "Ruta vacía."

    try:
        if not os.path.isfile(path):
            return False, "El archivo no existe o no es un archivo regular."

        _, ext = os.path.splitext(path)
        ext = ext.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return False, f"Extensión no permitida: '{ext or '(sin extensión)'}'."

        size = os.path.getsize(path)
        if size > MAX_SIZE_BYTES:
            size_mb = size / (1024 * 1024)
            max_mb = MAX_SIZE_BYTES / (1024 * 1024)
            return False, f"Archivo demasiado grande: {size_mb:.1f} MB (máximo {max_mb:.0f} MB)."

        return True, ""
    except OSError as e:
        logger.warning(f"Error validando archivo soltado '{path}': {e}")
        return False, "No se pudo leer el archivo."
