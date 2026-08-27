"""
core/identity.py
Carga los documentos de identidad del agente y los prepara para inyectarlos en el prompt
de sistema.

Antes de este módulo, `SOUL.md`, `IDENTITY.md` y `USER.md` existían en la raíz del proyecto
pero **ningún camino de ejecución los leía**: la personalidad vivía hardcodeada y duplicada
en `ai/claude_brain.py::_build_system_prompt()` (versión larga, usada por Telegram/Discord)
y en `core/reasoning_loop.py::_build_system_prompt()` (una línea, usada por escritorio y
voz). Las dos ya habían divergido entre sí. Este módulo es la única fuente de esos
documentos, para que los dos constructores de prompt digan lo mismo.

Decisiones:

- **El nombre configurado gana siempre.** Los documentos describen voz, rol y usuario; el
  nombre del agente sale de `config_manager.get_agent_name()`, que es editable desde la
  pantalla de Configuración. Si un documento quedó con un nombre viejo, la nota final del
  bloque le dice al modelo cuál es el vigente.
- **Un archivo ausente o ilegible no es un error.** Se omite, se registra, y el resto se
  inyecta igual. La identidad es una mejora del prompt, nunca un requisito para responder.
- **Presupuesto acotado.** El bloque entra en cada llamada al LLM, así que tiene un techo
  de caracteres por archivo y total. Truncar es preferible a inflar el coste de cada turno.
- **Relectura por mtime.** Editar `SOUL.md` tiene efecto en el turno siguiente sin
  reiniciar, igual que renombrar al agente. El disco solo se toca cuando el archivo cambió.
"""

import logging
import os
import threading
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Raíz del proyecto (`agente_ia/`), derivada del propio módulo: nunca una ruta absoluta
# hardcodeada (`.claude/rules/skills.md`).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Orden deliberado: primero quién es, después qué hace, después a quién sirve. Es el orden
# en que el modelo lo necesita para decidir el tono antes que el contenido.
IDENTITY_FILES: Tuple[Tuple[str, str], ...] = (
    ("SOUL.md", "TU VOZ Y TU CARÁCTER"),
    ("IDENTITY.md", "TU ROL Y TUS LÍMITES"),
    ("USER.md", "QUIÉN ES TU USUARIO"),
    # Va el último a propósito: es el único que cambia solo. `MemoryDigestSkill` reescribe
    # su bloque generado cada vez que el usuario pide "actualiza tu memoria", así que
    # ponerlo antes movería todo lo demás y tiraría el prefijo cacheado del proveedor.
    ("MEMORY.md", "LO QUE RECUERDAS"),
)

# Techos de presupuesto. Los tres archivos juntos rondan hoy las 145 líneas (~6 KB); el
# margen deja crecer los documentos sin que un descuido dispare el coste de cada turno.
MAX_CHARS_PER_FILE: int = 6000
MAX_CHARS_TOTAL: int = 14000

_TRUNCATION_NOTE = "\n[...documento truncado por presupuesto de contexto...]"

# Caché por ruta: (mtime, tamaño, contenido ya recortado). El tamaño acompaña al mtime
# porque en Windows la resolución de mtime puede no distinguir dos escrituras seguidas.
_cache: Dict[str, Tuple[float, int, str]] = {}
_cache_lock = threading.Lock()


def _truncate(text: str, limit: int) -> str:
    """Recorta `text` a `limit` caracteres por el último salto de línea que quepa."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind("\n")
    if cut > limit // 2:
        head = head[:cut]
    return head.rstrip() + _TRUNCATION_NOTE


def _read_identity_file(filename: str) -> Optional[str]:
    """Return el contenido de un documento de identidad, o `None` si no se puede usar.

    Ausente, vacío o ilegible son todos el mismo desenlace: se omite del bloque. Solo el
    caso ilegible se registra como advertencia — un archivo que el usuario no creó no es
    una anomalía.
    """
    path = os.path.join(_PROJECT_ROOT, filename)

    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning(f"No se pudo consultar '{filename}' para el prompt de identidad: {e}")
        return None

    with _cache_lock:
        cached = _cache.get(path)
        if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2] or None

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        logger.warning(f"No se pudo leer '{filename}' para el prompt de identidad: {e}")
        return None
    except UnicodeDecodeError as e:
        logger.warning(f"'{filename}' no es UTF-8 válido, se omite del prompt: {e}")
        return None

    content = _truncate(raw.strip(), MAX_CHARS_PER_FILE)

    with _cache_lock:
        _cache[path] = (stat.st_mtime, stat.st_size, content)

    return content or None


def _name_authority_note(agent_name: str) -> str:
    """La línea que resuelve un nombre viejo en los documentos sin tener que editarlos."""
    return (
        f"Tu nombre es {agent_name}. Si alguno de los documentos anteriores menciona otro "
        f"nombre para ti, está desactualizado: el nombre vigente es {agent_name}."
    )


def build_identity_block(agent_name: str) -> str:
    """Return el bloque de identidad listo para concatenar al prompt de sistema.

    Devuelve cadena vacía si no hay ningún documento disponible, para que el caller pueda
    concatenar sin condicionales y el prompt quede idéntico al de antes de este módulo.
    """
    sections: List[str] = []
    used = 0

    for filename, heading in IDENTITY_FILES:
        content = _read_identity_file(filename)
        if content is None:
            continue

        section = f"### {heading}\n{content}"
        if used + len(section) > MAX_CHARS_TOTAL:
            logger.info(
                f"Presupuesto de identidad agotado: '{filename}' no entra en el prompt "
                f"({used} de {MAX_CHARS_TOTAL} caracteres ya usados)"
            )
            break

        sections.append(section)
        used += len(section)

    if not sections:
        return ""

    body = "\n\n".join(sections)
    return (
        "\n\n--- IDENTIDAD ---\n"
        "Los siguientes documentos definen quién eres, cómo hablas y a quién sirves. "
        "Encárnalos: no los cites, no los menciones, no expliques que los tienes.\n\n"
        f"{body}\n\n"
        f"{_name_authority_note(agent_name)}\n"
        "--- FIN IDENTIDAD ---"
    )


def clear_cache() -> None:
    """Vacía la caché de documentos. Existe para los tests."""
    with _cache_lock:
        _cache.clear()
