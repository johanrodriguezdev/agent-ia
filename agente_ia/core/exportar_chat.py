"""
core/exportar_chat.py
REQ-056 — una conversación del chat como archivo Markdown.

Lo que se conversó con el agente termina muchas veces siendo el borrador de otra cosa: un
informe, una nota, un correo. Hasta ahora la única salida era copiar burbuja por burbuja.
Acá se arma un `.md` legible —título, fecha, cada turno con quién habló— a partir de lo
guardado en la base, y se escribe donde van los demás documentos que produce el agente
(`core/documentos.py`: el Escritorio, o una carpeta dentro de la personal o de un espacio
de trabajo).

Los marcadores de adjunto («[Imagen adjunta: C:\\…\\captura.png]») no se copian tal cual:
se convierten en una línea «📎 captura.png» al final del mensaje. La ruta completa es del
equipo del usuario, no del documento.
"""

import logging
import os
import re
from datetime import datetime
from typing import List, Optional

from core.imagenes import separar_adjunto

logger = logging.getLogger(__name__)

#: Caracteres que no van en un nombre de archivo (Windows es el más estricto).
_NO_VALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_MAX_NOMBRE = 60


def nombre_de_archivo(titulo: str, cuando: Optional[datetime] = None) -> str:
    """Return un nombre `.md` seguro a partir del título: «2026-09-20 Bibliografía de la tesis.md»."""
    cuando = cuando or datetime.now()
    limpio = _NO_VALIDOS.sub(" ", titulo or "")
    limpio = " ".join(limpio.split()).strip(". ")
    if not limpio:
        limpio = "Conversación"
    if len(limpio) > _MAX_NOMBRE:
        limpio = limpio[:_MAX_NOMBRE].rstrip()
    return f"{cuando.strftime('%Y-%m-%d')} {limpio}.md"


def _fecha_legible(timestamp: str) -> str:
    """«20 de septiembre de 2026, 01:15» a partir del ISO guardado; vacío si no se puede."""
    if not timestamp:
        return ""
    try:
        momento = datetime.fromisoformat(str(timestamp)[:19])
    except ValueError:
        return str(timestamp)
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
             "septiembre", "octubre", "noviembre", "diciembre"]
    return f"{momento.day} de {meses[momento.month - 1]} de {momento.year}, {momento:%H:%M}"


def _turno_a_markdown(rol: str, texto: str, quien_usuario: str, quien_agente: str) -> str:
    cuerpo, ruta = separar_adjunto(texto or "")
    quien = quien_agente if rol == "assistant" else quien_usuario
    lineas = [f"**{quien}:**", "", cuerpo.strip() or "_(sin texto)_"]
    if ruta:
        lineas += ["", f"📎 {os.path.basename(ruta)}"]
    return "\n".join(lineas)


def conversacion_a_markdown(turnos: List, titulo: str, *, quien_usuario: str = "Yo",
                            quien_agente: str = "Agente") -> str:
    """Return el Markdown de una conversación.

    `turnos` son `MemoryItem` (o cualquier objeto con `role`, `text`, `timestamp`) en orden
    cronológico, como los devuelve `memory.get_conversation_turns()`.
    """
    utiles = [t for t in turnos if getattr(t, "role", None) in ("user", "assistant")]
    primera = _fecha_legible(getattr(utiles[0], "timestamp", "") if utiles else "")
    ultima = _fecha_legible(getattr(utiles[-1], "timestamp", "") if utiles else "")

    partes = [f"# {titulo.strip() or 'Conversación'}", ""]
    if primera:
        partes.append(f"_{primera}_" if primera == ultima or not ultima else f"_{primera} — {ultima}_")
        partes.append("")
    partes.append(f"{len(utiles)} mensajes.")
    partes.append("")
    partes.append("---")
    partes.append("")
    for turno in utiles:
        partes.append(_turno_a_markdown(turno.role, turno.text, quien_usuario, quien_agente))
        partes.append("")
        partes.append("---")
        partes.append("")
    return "\n".join(partes).rstrip() + "\n"


def exportar(conversation_id: str, user_id: str, carpeta: Optional[str] = None,
             nombre: Optional[str] = None) -> str:
    """Escribe la conversación como `.md` y return la ruta. Levanta `DocumentoRechazado`
    si la carpeta no es válida o la conversación no existe."""
    from ai.memory_manager import memory
    from config_manager import get_agent_name, get_display_name
    from core.documentos import DocumentoRechazado, carpeta_de_salida, ruta_libre

    turnos = memory.get_conversation_turns(conversation_id, user_id=user_id, limit=100000)
    if not turnos:
        raise DocumentoRechazado("Esa conversación no tiene mensajes guardados.")

    titulo = memory.get_conversation_title(conversation_id, user_id=user_id)
    if not titulo:
        primero = next((t.text for t in turnos if getattr(t, "role", None) == "user"), "")
        titulo = " ".join(separar_adjunto(primero)[0].split())[:80] or "Conversación"

    try:
        quien_usuario = get_display_name() or "Yo"
    except Exception:
        quien_usuario = "Yo"
    try:
        quien_agente = get_agent_name() or "Agente"
    except Exception:
        quien_agente = "Agente"

    contenido = conversacion_a_markdown(
        turnos, titulo, quien_usuario=quien_usuario, quien_agente=quien_agente,
    )
    destino = carpeta_de_salida(carpeta)
    archivo = (nombre or "").strip() or nombre_de_archivo(titulo)
    if not archivo.lower().endswith(".md"):
        archivo += ".md"
    ruta = ruta_libre(destino, archivo)
    ruta.write_text(contenido, encoding="utf-8")
    logger.info(f"conversación {conversation_id} exportada a {ruta}")
    return str(ruta)
