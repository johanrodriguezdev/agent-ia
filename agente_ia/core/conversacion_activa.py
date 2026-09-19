"""
core/conversacion_activa.py
Qué conversación del escritorio está abierta ahora mismo (REQ-051).

Existe para una sola cosa: que el agente pueda obedecer «guardá este chat en el proyecto
Tesis». La herramienta (`chat_project_assign_current`) corre dentro del turno, en el mismo
hilo que la resolución, y no recibe ningún identificador de conversación del modelo — ni
debe: el modelo no sabe cuál es y no tiene por qué decidirlo. Lo sabe el bridge del
escritorio, que lo deja acá antes de empezar a resolver.

Mismo molde chico que `core/progress.py` y `core/cancelacion.py`: un registro global
protegido por un lock. Es SOLO del escritorio —Telegram y Discord tienen su historial por
usuario y sus proyectos no se ven ahí—, así que un único valor alcanza: en el escritorio
hay un turno a la vez.
"""

import threading
from typing import Optional, Tuple

_lock = threading.Lock()
_actual: Optional[str] = None
#: (conversation_id, project_id) que una herramienta pidió asignar cuando el chat todavía
#: no tenía turnos guardados (el primer mensaje): el bridge lo aplica al guardar el turno.
_asignacion_pendiente: Optional[Tuple[str, int]] = None


def fijar(conversation_id: Optional[str]) -> None:
    """Deja anotada la conversación abierta (o `None` si no hay ninguna)."""
    global _actual
    with _lock:
        _actual = str(conversation_id) if conversation_id else None


def actual() -> Optional[str]:
    """Return la conversación abierta en el escritorio, o `None`."""
    with _lock:
        return _actual


def pedir_asignacion(conversation_id: str, project_id: int) -> None:
    """Deja anotado que `conversation_id` va al proyecto `project_id` cuando exista."""
    global _asignacion_pendiente
    with _lock:
        _asignacion_pendiente = (str(conversation_id), int(project_id))


def tomar_asignacion_pendiente() -> Optional[Tuple[str, int]]:
    """Return y olvida la asignación pendiente, si la hay."""
    global _asignacion_pendiente
    with _lock:
        pendiente, _asignacion_pendiente = _asignacion_pendiente, None
        return pendiente
