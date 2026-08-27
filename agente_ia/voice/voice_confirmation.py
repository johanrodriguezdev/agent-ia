"""
voice/voice_confirmation.py
Confirmación hablada para las acciones que exigen permiso, cuando el manos libres está
activo.

El problema que resuelve. Hasta aquí, una acción 🟡 amarilla dictada por voz acababa
mostrando un **modal en pantalla**: las frases del webview se resuelven como canal de
escritorio, y el adaptador de escritorio es visual. En pleno manos libres eso significa
dejar de hablar e ir al ratón — y con la ventana de micrófono abierta, cualquiera en la
sala podía provocar ese modal esperando un clic distraído.

La confirmación hablada cierra ese hueco: el agente pregunta en voz alta y **exige una
palabra concreta**. Tomado del modelo de OpenClaw, que pide una confirmación hablada exacta
antes de acciones de alto impacto y la consume una sola vez.

Tres decisiones que sostienen la seguridad:

- **No vale un "sí".** Hay que decir *confirmo*. Un "sí" es una de las palabras más comunes
  del español y aparece en cualquier conversación de fondo; "confirmo" no se dice por
  accidente. Es la diferencia entre una confirmación y una coincidencia.
- **Fail-closed en todo lo demás.** Silencio, timeout, ruido, una frase distinta o no poder
  escuchar: todo eso deniega. Solo una cosa concede.
- **Un solo uso.** La respuesta se consume al leerla. No queda un "sí" flotando que autorice
  la siguiente acción.

Igual que `ConversationWindow`, este objeto es el canal entre dos hilos —el que ejecuta la
acción y el que tiene el micrófono— y ninguno espera al otro con un `join`: uno escribe una
petición, el otro deja una respuesta, y el primero espera sobre un `Event` con timeout.
"""

import logging
import threading
import unicodedata
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

#: Lo que hay que decir para autorizar. Se exige que la transcripción CONTENGA una de
#: estas, no que sea exactamente igual: el reconocedor añade muletillas ("eh, confirmo").
PALABRAS_DE_CONFIRMACION = ("confirmo", "confirmado")

#: Palabras que deniegan de inmediato sin esperar al timeout. No son necesarias para la
#: seguridad —cualquier cosa que no confirme ya deniega— pero evitan que el usuario tenga
#: que quedarse callado veinte segundos para cancelar algo.
PALABRAS_DE_RECHAZO = ("cancela", "cancelar", "no", "detente", "para", "olvidalo")

#: Segundos para responder. Suficiente para oír la pregunta y contestar; corto para que una
#: acción no quede colgada esperando a alguien que se fue.
TIMEOUT_SEGUNDOS = 20.0


def _normalizar(texto: str) -> str:
    """Minúsculas y sin acentos: el reconocedor es inconsistente con las tildes."""
    plano = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in plano if not unicodedata.combining(c))


def evalua_respuesta(texto: str) -> Optional[bool]:
    """Return True si autoriza, False si rechaza explícitamente, `None` si no decide.

    `None` es "no dijo ni una cosa ni otra": el caller lo trata como denegación, pero se
    distingue para poder registrar por qué se denegó.
    """
    plano = _normalizar(texto)
    if not plano.strip():
        return None

    palabras = set(plano.split())

    if any(p in plano for p in PALABRAS_DE_CONFIRMACION):
        return True
    if palabras & set(PALABRAS_DE_RECHAZO):
        return False
    return None


@dataclass
class _Peticion:
    action_name: str
    evento: threading.Event
    respuesta: Optional[str] = None


class VoiceConfirmation:
    """Canal entre el hilo que ejecuta la acción y el hilo del micrófono.

    Solo puede haber UNA confirmación pendiente a la vez: dos preguntas habladas
    simultáneas no se podrían distinguir en la respuesta.
    """

    def __init__(self, timeout_s: float = TIMEOUT_SEGUNDOS) -> None:
        self._timeout_s = timeout_s
        self._lock = threading.Lock()
        self._peticion: Optional[_Peticion] = None

    # ── Lado del que ejecuta la acción ──────────────────────────────

    def solicitar(self, action_name: str) -> bool:
        """Bloquea hasta que el usuario responda o expire el plazo. Return si autoriza.

        Corre en el hilo worker que ejecuta la acción, nunca en el de la interfaz.
        """
        with self._lock:
            if self._peticion is not None:
                logger.warning(
                    f"Ya hay una confirmación hablada en curso; se deniega '{action_name}'"
                )
                return False
            peticion = _Peticion(action_name=action_name, evento=threading.Event())
            self._peticion = peticion

        try:
            respondio = peticion.evento.wait(timeout=self._timeout_s)
            if not respondio:
                logger.warning(
                    f"Confirmación hablada de '{action_name}' denegada: nadie respondió "
                    f"en {self._timeout_s:.0f}s"
                )
                return False

            veredicto = evalua_respuesta(peticion.respuesta or "")
            if veredicto is True:
                logger.info(f"Confirmación hablada de '{action_name}': AUTORIZADA")
                return True

            motivo = "rechazo explícito" if veredicto is False else "respuesta no reconocida"
            logger.warning(
                f"Confirmación hablada de '{action_name}' denegada ({motivo}): "
                f"'{(peticion.respuesta or '')[:40]}'"
            )
            return False
        finally:
            # Un solo uso: pase lo que pase, la petición se retira.
            with self._lock:
                if self._peticion is peticion:
                    self._peticion = None

    # ── Lado del micrófono ──────────────────────────────────────────

    def hay_pendiente(self) -> bool:
        """Return True si el bucle de escucha debe entregar lo próximo que oiga."""
        with self._lock:
            return self._peticion is not None

    def accion_pendiente(self) -> str:
        with self._lock:
            return self._peticion.action_name if self._peticion else ""

    def responder(self, texto: str) -> bool:
        """Entrega lo que se oyó. Return True si había una petición esperándolo."""
        with self._lock:
            peticion = self._peticion
            if peticion is None:
                return False
            peticion.respuesta = texto
        peticion.evento.set()
        return True

    def cancelar(self) -> None:
        """Cierra cualquier petición en curso — al apagar el manos libres, por ejemplo."""
        with self._lock:
            peticion = self._peticion
            self._peticion = None
        if peticion is not None:
            peticion.respuesta = ""
            peticion.evento.set()


#: Instancia compartida, mismo patrón que el resto de singletons del proyecto.
voice_confirmation = VoiceConfirmation()


def mensaje_hablado(action_name: str, mensaje: str) -> str:
    """Return lo que el agente debe pronunciar para pedir la confirmación.

    Incluye SIEMPRE qué se va a hacer: una confirmación a ciegas ("¿confirma?") no es una
    confirmación. Es el equivalente hablado de ligar el permiso a la acción concreta.
    """
    detalle = (mensaje or "").strip() or f"ejecutar la acción {action_name}"
    return f"{detalle}. Si está de acuerdo, diga: confirmo."
