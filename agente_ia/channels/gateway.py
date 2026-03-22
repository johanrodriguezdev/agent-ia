"""
channels/gateway.py
Gateway central de Glass — normaliza mensajes de cualquier canal
(Telegram, Discord, CLI, Web) al mismo formato interno.

El núcleo de Glass nunca sabe de dónde viene el mensaje.
Todos los canales entregan un GlassMessage y reciben un GlassResponse.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class MessageType(Enum):
    TEXT  = "text"
    VOICE = "voice"   # Audio de voz → se transcribe con Whisper/Google STT
    IMAGE = "image"   # Imagen → se describe con Claude Vision
    FILE  = "file"    # Archivo adjunto


@dataclass
class GlassMessage:
    """
    Mensaje normalizado que cualquier canal entrega al núcleo.
    El núcleo solo trabaja con este formato, sin importar el origen.
    """
    user_id:    str                        # ID único del usuario (telegram_id, discord_id, etc.)
    user_name:  str                        # Nombre del usuario para personalización
    text:       str                        # Texto del mensaje (ya transcrito si era voz)
    channel:    str                        # "telegram" | "discord" | "cli" | "web"
    msg_type:   MessageType = MessageType.TEXT
    audio_path: Optional[str] = None       # Ruta local al audio si msg_type == VOICE
    image_path: Optional[str] = None       # Ruta local a la imagen si msg_type == IMAGE
    raw_data:   dict = field(default_factory=dict)  # Datos crudos del canal (para uso avanzado)


@dataclass
class GlassResponse:
    """
    Respuesta normalizada que el núcleo devuelve a cualquier canal.
    Cada canal decide cómo renderizarla (texto, audio, imagen, etc.)
    """
    text:        str                       # Respuesta en texto siempre incluida
    speak:       bool = True               # Si el canal soporta voz, leerla en voz alta
    audio_path:  Optional[str] = None      # Ruta a audio generado (si TTS produjo archivo)
    extra:       dict = field(default_factory=dict)  # Datos extra por canal


class GlassGateway:
    """
    Punto de entrada central para todos los canales.
    Recibe un GlassMessage, lo procesa con el núcleo de Glass,
    y devuelve un GlassResponse.
    """

    def __init__(self):
        # Importaciones lazy para no bloquear el arranque si algo falla
        self._classifier = None
        self._dispatcher = None

    def _get_core(self):
        """Inicializa el núcleo de Glass solo cuando se necesita (lazy)."""
        if self._classifier is None:
            from intent.classifier import classify_command
            from router.dispatcher import dispatch
            self._classifier = classify_command
            self._dispatcher = dispatch
        return self._classifier, self._dispatcher

    def process(self, message: GlassMessage) -> GlassResponse:
        """
        Procesa un mensaje de cualquier canal y retorna la respuesta.
        Este es el único punto de integración entre canales y núcleo.
        """
        from ui.personality import format_response
        from ai.memory_manager import save_memory
        from ai.claude_brain import ask_claude

        text = message.text.strip()
        if not text:
            return GlassResponse(
                text="Dígame, estoy escuchando.",
                speak=True
            )

        try:
            classify, dispatch = self._get_core()

            # 1. Clasificar intención
            from intent.intentions import Intent
            intent, params = classify(text)

            # 2. Si es UNKNOWN → Claude como cerebro conversacional
            if intent == Intent.UNKNOWN:
                # Inyectar contexto del usuario en el mensaje para personalización
                params["query"] = text
                from executor.handlers import handle_chat
                result = handle_chat({"query": text})
            else:
                result = dispatch(intent, params)

            # 3. Guardar en memoria
            save_memory(text, result)

            # 4. Guardar embedding semántico (sin bloquear si falla)
            try:
                from ai.semantic_memory import store_memory as sem_store
                sem_store(f"[{message.channel}] {message.user_name}: {text} → {result}")
            except Exception:
                pass

            return GlassResponse(text=result, speak=True)

        except Exception as e:
            error_msg = f"Lo siento, he encontrado un inconveniente procesando su solicitud: {str(e)[:80]}"
            return GlassResponse(text=error_msg, speak=True)
