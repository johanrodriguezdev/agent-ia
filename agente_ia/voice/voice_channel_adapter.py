"""
voice/voice_channel_adapter.py
Adaptador de confirmación para `ChannelType.VOICE`: el modo consola por voz (REQ-048).

Hasta REQ-048 la voz tenía dos caras. En la app de escritorio, con el manos libres activo,
un pedido por voz corre como canal ESCRITORIO y `ui/webview/confirmation_adapter.py` pide
la confirmación hablando («… Si está de acuerdo, diga: confirmo»). En el modo consola
(`python main.py`, opciones 2 y 3) el pedido corre como canal VOICE, y ese canal no tenía
a quién preguntar: toda acción amarilla —y toda herramienta MCP— se denegaba fail-closed.

Este adaptador es la misma confirmación hablada para la consola: pronuncia la pregunta por
TTS y escucha UNA captura del micrófono; solo «confirmo» autoriza (`voice_confirmation.
evalua_respuesta`, los mismos criterios que en el manos libres). Silencio, ruido, un «sí»,
un fallo del micrófono o del TTS: todo deniega.

Corre en el mismo hilo que ejecuta la acción, que en la consola es el hilo principal —el
mismo que entre turnos abre el micrófono con `listen_command()`—, así que no hay dos
lectores del micrófono a la vez.

`hablar` y `escuchar` se inyectan para los tests; por defecto son el TTS y el reconocedor
de la consola.
"""

import logging
from typing import Callable, Optional

from voice.voice_confirmation import evalua_respuesta, mensaje_hablado

logger = logging.getLogger(__name__)


def _hablar_por_defecto(texto: str) -> None:
    from ui.tts_engine import prepare_for_speech, speak

    speak(prepare_for_speech(texto))


def _escuchar_por_defecto() -> str:
    from ui.stt.transcriber import listen_command

    return listen_command() or ""


class VoiceChannelConfirmationAdapter:
    """(action_name, mensaje) -> bool para ChannelType.VOICE."""

    def __init__(
        self,
        hablar: Optional[Callable[[str], None]] = None,
        escuchar: Optional[Callable[[], str]] = None,
    ) -> None:
        self._hablar = hablar or _hablar_por_defecto
        self._escuchar = escuchar or _escuchar_por_defecto

    def confirm(self, action_name: str, message: str) -> bool:
        """Pregunta en voz alta y escucha una vez. Fail-closed en todo lo demás."""
        pregunta = mensaje_hablado(action_name, message)
        try:
            # Se pronuncia ANTES de abrir la escucha: si se abriera antes, el micrófono
            # capturaría la propia pregunta como si fuera la respuesta.
            self._hablar(pregunta)
        except Exception as e:
            # Sin voz no hay confirmación hablada posible, y adivinar no es una opción.
            logger.error(f"No se pudo pronunciar la confirmación de '{action_name}': {e}")
            return False

        try:
            respuesta = self._escuchar() or ""
        except Exception as e:
            logger.error(f"No se pudo escuchar la confirmación de '{action_name}': {e}")
            return False

        veredicto = evalua_respuesta(respuesta)
        if veredicto is True:
            logger.info(f"Confirmación hablada (consola) de '{action_name}': AUTORIZADA")
            return True
        motivo = "rechazo explícito" if veredicto is False else "respuesta no reconocida"
        logger.warning(
            f"Confirmación hablada (consola) de '{action_name}' denegada ({motivo}): "
            f"'{respuesta[:40]}'"
        )
        return False


voice_channel_confirmation_adapter = VoiceChannelConfirmationAdapter()
