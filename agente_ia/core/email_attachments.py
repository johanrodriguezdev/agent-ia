"""
core/email_attachments.py
Adjuntos de correo: describirlos sin tocarlos, y guardarlos solo con autorización.

El flujo tiene dos mitades separadas a propósito, y la separación ES la seguridad:

1. **Describir** (`describir()`): al revisar el buzón se lee únicamente la METADATA de cada
   adjunto —nombre, tipo, tamaño—. Los bytes no se descargan, no tocan el disco y no entran
   en el resumen. Esto corre en `ChannelType.EMAIL`, que no puede ejecutar nada.

2. **Guardar** (`guardar()`): descargar el archivo es una acción AMARILLA
   (`save_email_attachment`) que se confirma desde un canal de confianza. El canal del
   correo no puede iniciarla ni queriendo: su política de niveles está vacía.

O sea que un correo nunca puede hacer que un archivo aterrice en tu disco. Como mucho puede
hacer que O.R.I.O.N. te diga "vino un archivo llamado X" y esperar a que vos digas que sí.

Tres defensas en el guardado, porque el nombre del archivo lo eligió un desconocido:

- **Sin travesía de rutas.** Un adjunto llamado `..\\..\\Windows\\System32\\evil.dll` se
  guarda como `evil.dll` dentro del directorio de descargas. Nunca fuera.
- **Los ejecutables se marcan.** `.exe`, `.bat`, `.ps1` y compañía se avisan en el propio
  texto de confirmación, para que "sí" sea una decisión informada y no un reflejo.
- **Tope de tamaño**, para que un adjunto gigante no llene el disco.
"""

import logging
import os
import re
import sys
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


def icono(simbolo: str, respaldo: str) -> str:
    """Return `simbolo` si la salida sabe representarlo, o `respaldo` en texto plano.

    La consola de Windows en cp1252 no puede codificar emoji y `print()` LANZA
    `UnicodeEncodeError`. Los adjuntos se listan cada vez que llega un correo con
    archivos, así que un emoji fijo ahí sería un crash rutinario en esa consola. En
    Telegram y en el webview, que son UTF-8, se ve el ícono.
    """
    codificacion = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        simbolo.encode(codificacion)
    except (UnicodeEncodeError, LookupError):
        return respaldo
    return simbolo


_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIRECTORIO_DESCARGAS = os.path.join(_RAIZ, "descargas_correo")

MAX_BYTES_DEFAULT = 25 * 1024 * 1024

#: Extensiones que Windows puede ejecutar con un doble clic. No se bloquean —el usuario es
#: el dueño de su máquina— pero se dicen en voz alta antes de pedirle que confirme.
EXTENSIONES_PELIGROSAS = frozenset({
    ".exe", ".com", ".scr", ".pif", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".hta", ".cpl", ".jar", ".reg",
    ".lnk", ".dll", ".sys", ".apk", ".app", ".sh",
})

_RE_INSEGURO = re.compile(r"[^A-Za-z0-9._ ()\-]")
_MAX_LARGO_NOMBRE = 120


@dataclass(frozen=True)
class Adjunto:
    """Lo que se sabe de un adjunto SIN haberlo descargado."""
    nombre: str
    tipo: str
    tamano: int

    @property
    def peligroso(self) -> bool:
        return es_peligroso(self.nombre)

    def describir(self) -> str:
        """Una línea legible para el resumen y para el pedido de confirmación."""
        marca = icono("📎", "[adjunto]")
        aviso = f"  {icono('⚠️', '(!)')} EJECUTABLE" if self.peligroso else ""
        return f"{marca} {self.nombre} ({self.tipo}, {tamano_legible(self.tamano)}){aviso}"


def tamano_legible(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.0f} KB"
    return f"{bytes_ / (1024 * 1024):.1f} MB"


def es_peligroso(nombre: str) -> bool:
    """Return True si el nombre termina en una extensión ejecutable."""
    _, extension = os.path.splitext((nombre or "").strip().lower())
    return extension in EXTENSIONES_PELIGROSAS


def nombre_seguro(nombre: str) -> str:
    """Convierte el nombre elegido por un desconocido en algo seguro de escribir.

    Se queda solo con el nombre base —`os.path.basename` sobre las dos convenciones de
    separador, porque un remitente puede mandar barras de Unix aunque estemos en Windows— y
    después limpia lo que quede. Nunca devuelve cadena vacía ni algo que apunte a un padre.
    """
    crudo = (nombre or "").strip().replace("\\", "/")
    base = crudo.rsplit("/", 1)[-1]
    base = _RE_INSEGURO.sub("_", base).strip(" .")

    if not base or base in (".", ".."):
        return "adjunto_sin_nombre"
    if len(base) > _MAX_LARGO_NOMBRE:
        raiz, extension = os.path.splitext(base)
        base = raiz[:_MAX_LARGO_NOMBRE - len(extension)] + extension
    return base


def describir(mensaje) -> List[Adjunto]:
    """Return la metadata de los adjuntos de `mensaje`. NO descarga ningún byte."""
    adjuntos: List[Adjunto] = []
    try:
        partes = list(mensaje.iter_attachments())
    except Exception as e:
        logger.warning(f"No se pudieron enumerar los adjuntos: {e}")
        return []

    for parte in partes:
        try:
            nombre = parte.get_filename() or "(sin nombre)"
            carga = parte.get_payload(decode=True) or b""
            adjuntos.append(Adjunto(
                nombre=nombre,
                tipo=parte.get_content_type(),
                tamano=len(carga),
            ))
        except Exception as e:
            logger.warning(f"No se pudo describir un adjunto: {e}")
    return adjuntos


def texto_de_confirmacion(adjunto: Adjunto, remitente: str) -> str:
    """El mensaje que ve el usuario antes de decir que sí. Tiene que alcanzar para decidir."""
    lineas = [
        f"Guardar el adjunto «{adjunto.nombre}»",
        f"de {remitente} ({adjunto.tipo}, {tamano_legible(adjunto.tamano)})",
    ]
    if adjunto.peligroso:
        lineas.append(
            f"{icono('⚠️', '(!)')} ATENCIÓN: es un archivo EJECUTABLE. Si no lo "
            f"esperabas, no lo guardes."
        )
    lineas.append(f"Se guardaría en: {DIRECTORIO_DESCARGAS}")
    return "\n".join(lineas)


def ruta_destino(nombre: str) -> str:
    """Return dónde se guardaría `nombre`, ya saneado y sin pisar nada.

    Si el archivo existe se numera (`informe (2).pdf`) en vez de sobreescribir: un correo
    no puede reemplazarte un archivo que ya tenías.
    """
    seguro = nombre_seguro(nombre)
    destino = os.path.join(DIRECTORIO_DESCARGAS, seguro)
    if not os.path.exists(destino):
        return destino

    raiz, extension = os.path.splitext(seguro)
    for indice in range(2, 1000):
        candidato = os.path.join(DIRECTORIO_DESCARGAS, f"{raiz} ({indice}){extension}")
        if not os.path.exists(candidato):
            return candidato
    return os.path.join(DIRECTORIO_DESCARGAS, f"{raiz} ({os.getpid()}){extension}")


def guardar(mensaje, nombre_pedido: str, max_bytes: int = MAX_BYTES_DEFAULT) -> str:
    """Escribe en disco el adjunto `nombre_pedido` de `mensaje`. Return la ruta o lanza.

    Se llama SOLO después de que `security_manager` confirmó la acción amarilla: este
    módulo no consulta el gate, lo hace quien lo llama (`skills/email_skill.py`), que es
    quien conoce el canal real.
    """
    objetivo = None
    for parte in mensaje.iter_attachments():
        if (parte.get_filename() or "") == nombre_pedido:
            objetivo = parte
            break
    if objetivo is None:
        raise ValueError(f"el correo no tiene ningún adjunto llamado «{nombre_pedido}»")

    datos = objetivo.get_payload(decode=True) or b""
    if len(datos) > max_bytes:
        raise ValueError(
            f"«{nombre_pedido}» pesa {tamano_legible(len(datos))} y el tope es "
            f"{tamano_legible(max_bytes)}"
        )

    os.makedirs(DIRECTORIO_DESCARGAS, exist_ok=True)
    destino = ruta_destino(nombre_pedido)

    # Cinturón y tirantes: aunque `nombre_seguro()` ya limpió el nombre, se comprueba que
    # la ruta final siga cayendo dentro del directorio de descargas. Si alguna vez alguien
    # afloja el saneado, esto sigue impidiendo escribir fuera.
    if os.path.commonpath([os.path.abspath(destino),
                           os.path.abspath(DIRECTORIO_DESCARGAS)]) != \
            os.path.abspath(DIRECTORIO_DESCARGAS):
        raise ValueError("la ruta de destino se sale del directorio de descargas")

    with open(destino, "wb") as f:
        f.write(datos)
    logger.info(f"Adjunto guardado: {destino} ({tamano_legible(len(datos))})")
    return destino


def buscar(adjuntos: List[Adjunto], pedido: str) -> Optional[Adjunto]:
    """Encuentra un adjunto por nombre, tolerando que el usuario lo escriba a medias."""
    if not pedido:
        return None
    objetivo = pedido.strip().lower()
    for adjunto in adjuntos:
        if adjunto.nombre.lower() == objetivo:
            return adjunto
    for adjunto in adjuntos:
        if objetivo in adjunto.nombre.lower():
            return adjunto
    return None
