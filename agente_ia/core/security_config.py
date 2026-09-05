"""
core/security_config.py
Persistencia de los overrides de seguridad que el usuario sube desde la pantalla
"Configuración" (REQ-019). Archivo propio (`security_overrides.json`, sibling de
`config.json`/`audit.db` — mismo patrón de ruta que AUDIT_DB en
core/security_manager.py:72), deliberadamente SEPARADO de config_manager.py.

Ver arquitectura-019.md, sección "Desvío documentado de un ASUMIDO", para el porqué:
aísla el radio de impacto de una corrupción de archivo en ambas direcciones, y permite
escritura atómica exactamente donde la integridad importa más (fallback ante archivo
inválido = SIEMPRE "sin overrides" = nivel de código, nunca "sin restricciones").

Manejo de excepciones (arquitectura-019.md §11.1, respuesta al Hallazgo A de
security-audit-019.md): `load_security_overrides()` usa `except Exception` amplio en vez
de enumerar tipos concretos (`json.JSONDecodeError`/`OSError` no cubrían
`UnicodeDecodeError`, subclase de `ValueError` — el escenario de corrupción más realista
en la práctica: archivo truncado a mitad de escritura, bytes no-UTF-8). Permitido por
`.claude/rules/python-style.md` siempre que se loguee — no es un `except: pass` silencioso.
"""

import json
import logging
import os
import tempfile
from typing import Dict

logger = logging.getLogger(__name__)

SECURITY_OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), "..", "security_overrides.json")
_VALID_LEVEL_VALUES = {"green", "yellow", "red"}


def load_security_overrides() -> Dict[str, str]:
    """Devuelve {clave_interna: nivel_str}. Nunca crashea, nunca interpreta un archivo
    inválido como 'sin restricciones' — el peor caso posible es dict vacío (CA-06)."""
    if not os.path.exists(SECURITY_OVERRIDES_FILE):
        return {}
    try:
        with open(SECURITY_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        # except Exception amplio (arquitectura-019.md §11.1, Hallazgo A de
        # security-audit-019.md): json.JSONDecodeError/OSError no cubrían
        # UnicodeDecodeError (subclase de ValueError) — no depende de anticipar cada
        # subtipo posible de error de I/O/decodificación.
        logger.warning(
            f"security_overrides.json corrupto/ilegible ({type(e).__name__}) — se ignora "
            f"por completo, fallback a nivel de código: {e}"
        )
        return {}
    if not isinstance(raw, dict):
        logger.warning("security_overrides.json no es un objeto JSON — se ignora")
        return {}

    result: Dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or value not in _VALID_LEVEL_VALUES:
            logger.warning(f"Entrada inválida en security_overrides.json ignorada: {key!r}={value!r}")
            continue
        result[key] = value
    return result


def save_security_overrides(overrides: Dict[str, str]) -> None:
    """Persiste TODAS las entradas de `overrides` (clave_interna → nivel) en UNA sola
    escritura atómica — deliberado: una fila de negocio puede cubrir 2 claves internas
    (ej. open_app + OPEN_APP) y deben quedar sincronizadas en un único swap de archivo,
    nunca en N operaciones separadas que dejarían una ventana de estado a medias si el
    proceso muere entre la primera y la segunda (CA-11)."""
    current = load_security_overrides()
    current.update(overrides)
    _atomic_write(current)


def _atomic_write(data: Dict[str, str]) -> None:
    directory = os.path.dirname(os.path.abspath(SECURITY_OVERRIDES_FILE)) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".security_overrides_", dir=directory)
    except OSError as e:
        logger.error(f"No se pudo crear archivo temporal para guardar security_overrides.json: {e}")
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, SECURITY_OVERRIDES_FILE)  # atómico en Windows (MoveFileEx) y POSIX
    except OSError as e:
        logger.error(f"No se pudo guardar security_overrides.json: {e}")
        try:
            os.remove(tmp_path)
        except OSError as e:
            # El fallo principal ya quedo registrado arriba; esto es solo el temporal que
            # no se pudo limpiar. Igual se deja dicho: si empiezan a quedar .tmp sueltos
            # al lado del archivo de configuracion, este es el unico rastro.
            logger.debug(f"quedo un temporal sin borrar: {e}")
