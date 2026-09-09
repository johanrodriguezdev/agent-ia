import speech_recognition as sr
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional, Union
import numpy as np
from ui.tts_engine import speak
from nlp.parser import clean_text
from config_manager import (
    get_wake_words, get_agent_name, get_agent_pronunciation, normalize_for_match,
)
from core.address import vocative
from core.notificaciones import notificar

logger = logging.getLogger(__name__)

_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        try:
            import whisper
            _whisper_model = whisper.load_model("base", device="cpu")
            print("[Whisper] Modelo local cargado para wake word (fallback offline)")
        except Exception:
            _whisper_model = False
    return _whisper_model if _whisper_model is not False else None

def _transcribe_whisper(audio_data: sr.AudioData) -> str:
    try:
        model = _get_whisper()
        if model is None:
            return ""
        raw = audio_data.get_raw_data()
        audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        result = model.transcribe(audio_np, language="es", fp16=False)
        return result.get("text", "").strip()
    except Exception:
        return ""

def parse_wake_command(text: str) -> tuple[bool, str]:
    """Detecta la wake word en `text` y devuelve `(detectada, comando_restante)`.

    Ambos lados se normalizan con `normalize_for_match()` —la misma función que ya usa
    `get_wake_words()`— para que la comparación sea simétrica. Con `clean_text()` no lo
    era: un nombre deletreado por el reconocedor ("O.R.I.O.N.") quedaba como "o r i o n"
    y no coincidía con "orion".
    """
    text_clean = normalize_for_match(text)
    wake_words = get_wake_words()
    wake_words.extend([name.replace("j", "y") for name in wake_words if "j" in name])

    for word in wake_words:
        pos = text_clean.find(word)
        if pos != -1:
            command = text_clean[pos + len(word):].strip()
            return True, command
    return False, ""

def _transcribe(recognizer: sr.Recognizer, audio: sr.AudioData) -> str:
    """Transcribe con Google y cae a Whisper local si falla, sin tragarse el motivo."""
    try:
        return recognizer.recognize_google(audio, language="es-ES")
    except sr.UnknownValueError:
        logger.info(
            "[Wake word] Google Speech no pudo transcribir el audio "
            "(UnknownValueError); probando fallback local"
        )
    except sr.RequestError as e:
        logger.warning(
            f"[Wake word] Fallo de conexion con la API de Google Speech ({e}); "
            "probando fallback local"
        )
    return _transcribe_whisper(audio)


def _listen_for_followup(recognizer: sr.Recognizer, source) -> str:
    """Captura el comando que sigue a la wake word cuando se dijo el nombre a secas.

    Reusa el `source` del micrófono ya abierto por `listen_for_wake_word()`: abrir un
    segundo `sr.Microphone()` anidado deja el dispositivo tomado y falla en Windows.
    """
    try:
        audio = recognizer.listen(source, timeout=6, phrase_time_limit=12)
    except sr.WaitTimeoutError:
        logger.info("[Wake word] Nadie dictó un comando tras despertar")
        return ""
    except Exception as e:
        logger.error(f"[Wake word] fallo escuchando el comando posterior: {e}")
        return ""

    text = _transcribe(recognizer, audio)
    if not text:
        logger.info("[Wake word] El comando posterior no se pudo transcribir")
    return text.strip()


def _report_state(
    wake_state_callback: Optional[Callable[[str], None]], state: str,
) -> None:
    """Reportar un estado por el canal de REQ-009/CA-04, nunca silenciado."""
    if wake_state_callback is None:
        return
    try:
        wake_state_callback(state)
    except Exception as e:
        logger.error(f"fallo en wake_state_callback: {e}")


#: Palabras que deben coincidir con lo que el agente está diciendo para considerar que lo
#: captado es su propio eco. Con dos basta: la transcripción del eco es imperfecta, pero
#: rara vez acierta dos palabras seguidas por casualidad.
_ECO_MIN_PALABRAS_COMUNES = 2

#: Cuánto puede durar UNA frase dictada. Estaba en 6 segundos, y con eso una instrucción
#: normal se partía por la mitad: en la sesión del 2026-09-04 21:28, "orion, ¿me escuchas?
#: hazme un análisis del precio del dólar en los últimos 6 meses" llegó como
#: `'orion Me escuchas Hazme un'`, y el resto entró después como una frase suelta sin wake
#: word, que se descartó. El propio usuario terminó dictando "se está cortando el audio".
#:
#: `pause_threshold` cierra la frase ~0.8 s después de que dejás de hablar, así que este
#: límite solo actúa sobre quien habla de corrido más que eso.
_LIMITE_DE_FRASE = 15

#: El límite MIENTRAS el agente habla, que es un caso distinto: por los altavoces el
#: micrófono oye voz continua, así que la frase nunca se cierra por silencio y se estira
#: hasta el tope. Con 15 s ahí, una interrupción tardaría hasta 15 s en transcribirse y
#: llegar al barge-in. Cuando el agente habla no hace falta capturar una instrucción larga:
#: hace falta oír "para" rápido.
_LIMITE_MIENTRAS_HABLA = 5


def _limite_de_frase() -> int:
    """Cuántos segundos puede durar la captura, según si el agente está hablando."""
    try:
        from ui.tts_engine import is_speaking

        return _LIMITE_MIENTRAS_HABLA if is_speaking() else _LIMITE_DE_FRASE
    except Exception as e:
        logger.debug(f"No se pudo consultar el estado del TTS: {e}")
        return _LIMITE_DE_FRASE

#: Con qué se corta una locución en curso. Cortas a propósito: se dicen ENCIMA de la voz
#: del agente, en el hueco entre dos palabras suyas.
_FRASES_DE_CORTE = frozenset({
    "para", "pare", "pará", "detente", "deténgase", "detengase", "basta", "stop",
    "cállate", "callate", "cállese", "callese", "silencio", "espera", "espere",
    "ya está", "ya esta", "suficiente",
})


def _es_eco_del_agente(texto: str, dicho: str, contexto: str = "Micrófono") -> bool:
    """Return True si `texto` es lo que el propio agente está diciendo, captado por el mic.

    La comparación es por palabras y no por subcadena porque la transcripción del eco nunca
    es exacta —le faltan sílabas, cambia acentos— pero conserva las palabras largas.

    Vive aparte porque hacen falta DOS lectores. El barge-in ya lo usaba; la confirmación
    hablada no, y por eso el agente terminaba contestándose a sí mismo: preguntaba en voz
    alta "¿está seguro de que quiere ejecutar...?", el micrófono lo oía, y esa frase entraba
    como la respuesta del usuario. Al no ser un "confirmo", contaba como rechazo — antes de
    que el humano abriera la boca (logs/orion.log, 2026-09-04 22:18:47 y 22:20:48).
    """
    captadas = {p for p in normalize_for_match(texto).split() if len(p) > 3}
    pronunciadas = {p for p in normalize_for_match(dicho).split() if len(p) > 3}
    if not captadas:
        return False        # ruido sin palabras con contenido: no es nadie hablando

    comunes = captadas & pronunciadas

    # Dos condiciones, cualquiera basta. La segunda cubre el caso de que el micrófono solo
    # alcance a captar una palabra suelta de la locución: si TODO lo que se oyó está dentro
    # de lo que el agente está diciendo, no hay nada que sugiera una voz distinta.
    es_eco = len(comunes) >= _ECO_MIN_PALABRAS_COMUNES or captadas <= pronunciadas
    if es_eco:
        logger.info(
            f"[{contexto}] Descartado: es el eco del propio agente "
            f"(coinciden {sorted(comunes)[:4]})"
        )
    return es_eco


def _es_su_propia_pregunta(texto: str) -> bool:
    """Return True si lo captado es el agente pronunciando su propia petición de permiso.

    Dos candados, porque el eco llega en dos momentos distintos: mientras todavía habla
    (`is_speaking()`), y en el chunk que se estaba capturando justo cuando terminó, que ya
    no lo detecta `is_speaking()` pero sigue conteniendo su voz.
    """
    from ui.tts_engine import current_speech_text
    from voice.voice_confirmation import PALABRAS_DE_CONFIRMACION, PALABRAS_DE_RECHAZO

    dicho = current_speech_text()
    if not dicho:
        return False

    # El vocabulario de respuesta se quita de LAS DOS partes antes de comparar. Es
    # imprescindible: la pregunta dice "diga confirmo para ejecutar", así que un "confirmo"
    # a secas está contenido en ella palabra por palabra y se descartaba como eco — el
    # filtro contra el agente habría acabado ignorando justo la respuesta del humano.
    #
    # Lo que queda después de quitarlo es lo que de verdad distingue quién habló: si TODO
    # eso está dentro de la pregunta, la dijo el agente.
    respuestas = set(PALABRAS_DE_CONFIRMACION) | set(PALABRAS_DE_RECHAZO)
    sin_respuestas = " ".join(
        p for p in normalize_for_match(texto).split() if p not in respuestas
    )
    if not sin_respuestas.strip():
        return False        # solo dijo "confirmo" / "no": es una respuesta, no un eco

    return _es_eco_del_agente(sin_respuestas, dicho, contexto="Confirmación")


def _es_interrupcion_real(texto: str) -> bool:
    """Return True si `texto` es el usuario interrumpiendo, y no el eco del propio agente.

    El micrófono capta los altavoces. Sin esta comprobación, cualquier respuesta hablada se
    interrumpía a sí misma: el bucle oía al agente, asumía que era el usuario, y cortaba la
    locución a los pocos segundos de empezar.

    La comparación es por palabras y no por subcadena porque la transcripción del eco nunca
    es exacta —le faltan sílabas, cambia acentos— pero conserva las palabras largas.
    """
    from ui.tts_engine import current_speech_text, is_speaking

    if not is_speaking():
        return False        # nadie está hablando: no hay nada que interrumpir

    dicho = current_speech_text()
    if not dicho:
        return True         # está hablando pero no sabemos qué: se respeta la interrupción

    if _es_eco_del_agente(texto, dicho, contexto="Barge-in"):
        return False

    # No basta con que NO sea el agente: tiene que ser alguien hablándole A ÉL.
    #
    # Antes alcanzaba con cualquier cosa transcrita, y el micrófono capta la habitación
    # entera. En la sesión del 2026-09-04 21:29, seis segundos después de terminar un
    # análisis del precio del dólar, un anuncio de radio —"95.3 perfecto para combatir el
    # encrespamiento"— cortó la respuesta hablada a mitad. Desde afuera eso se vive como
    # que el agente no contesta en audio.
    #
    # Cortar de más y cortar de menos no cuestan lo mismo: si de verdad querés
    # interrumpirlo y no reconoce la frase, lo repetís; si corta solo, perdés la respuesta
    # entera y no hay forma de recuperarla salvo volver a preguntar.
    if not _pide_la_palabra(texto):
        logger.info(f"[Barge-in] Descartado: ruido de fondo mientras habla — '{texto[:50]}'")
        return False

    return True


def _pide_la_palabra(texto: str) -> bool:
    """Return True si `texto` es alguien pidiéndole al agente que se calle o atienda.

    Dos formas, las dos deliberadas: el nombre del agente (que es como se le habla) o una
    frase de corte explícita ("para", "espera"). Cualquier otra cosa dicha mientras habla
    es la habitación, no una orden.
    """
    # Al PRINCIPIO de la frase, no en cualquier parte. Quien interrumpe abre con la palabra
    # de corte ("espera, quiero preguntarte otra cosa"); un anuncio la lleva enterrada en
    # medio — "95.3 perfecto PARA combatir el encrespamiento" cortaba la locución cuando
    # esto se buscaba como subcadena.
    limpio = normalize_for_match(texto).strip()
    if limpio in _FRASES_DE_CORTE:
        return True
    if any(limpio.startswith(f"{frase} ") for frase in _FRASES_DE_CORTE):
        return True
    try:
        es_wake, _ = parse_wake_command(texto)
        return bool(es_wake)
    except Exception as e:
        # Sin poder decidir, se respeta la interrupción: es el comportamiento de antes.
        logger.warning(f"No se pudo evaluar la wake word para el barge-in: {e}")
        return True


def _report_awake(wake_state_callback: Optional[Callable[[str], None]]) -> None:
    """Reportar el estado 'AWAKE' por el canal nuevo (REQ-009/CA-04), nunca silenciado."""
    _report_state(wake_state_callback, "AWAKE")


# --------------------------------------------------------------- REQ-028: reconexión
# El manos libres era UNA sesión de micrófono con un bucle adentro: si el dispositivo se
# caía, se caía todo. Ahora es un BUCLE DE SESIONES — cuando otra aplicación se lleva el
# micrófono (una reunión, una llamada), se cierra esa sesión, se espera, y se abre otra.


class _MicrofonoPerdido(Exception):
    """El dispositivo de audio dejó de estar disponible durante una sesión de escucha.

    Interna al módulo: nunca sale de `listen_for_wake_word()`. Existe para cortar la sesión
    en curso sin matar la función, que es justo lo que hacía el `OSError` crudo de PyAudio.

    `al_abrir` separa los dos fallos que se tratan distinto: no haber podido tomar nunca el
    micrófono (puede que no haya ninguno conectado — CA-07, techo de 3 intentos) de haberlo
    perdido con la sesión ya andando (CA-01, se reintenta mientras el usuario lo quiera).
    """

    def __init__(self, mensaje: str, al_abrir: bool) -> None:
        super().__init__(mensaje)
        self.al_abrir = al_abrir


#: Escalera de espera entre reintentos, en segundos. Crece para no golpear a PyAudio una
#: vez por segundo durante una reunión de una hora, y tiene techo para que recuperar el
#: micrófono nunca tarde más de medio minuto desde que queda libre.
_ESPERAS_DE_RECONEXION: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)

#: En qué trozos se consume la espera. `stop_event` se consulta en cada uno: apagar el
#: manos libres mientras reintenta no puede tardar los 30 s del último escalón (CA-06).
_PASO_DE_ESPERA = 0.5

#: Cuántas aperturas fallidas seguidas, sin haber leído nunca el dispositivo, bastan para
#: concluir que no hay micrófono. Distinto de perderlo estando en uso: eso no se rinde.
_MAX_APERTURAS_SIN_MICROFONO = 3


def siguiente_espera(intento: int) -> float:
    """Return los segundos a esperar antes del reintento número `intento` (1 = el primero).

    Función pura a propósito: la escalera de backoff se puede fijar por test sin dormir ni
    tocar el micrófono (mismo criterio que `fit_size_to_screen()` y `resolver_maximizado()`).
    """
    if intento < 1:
        intento = 1
    return _ESPERAS_DE_RECONEXION[min(intento, len(_ESPERAS_DE_RECONEXION)) - 1]


def _esperar_troceado(
    segundos: float, stop_event: Optional[threading.Event],
) -> bool:
    """Esperar `segundos` en trozos de `_PASO_DE_ESPERA`. Return False si hay que parar.

    Sin esto, apagar el manos libres durante el último escalón del backoff tardaría hasta
    30 segundos en tomar efecto, y el usuario vería un botón que dice "apagado" con un hilo
    todavía vivo detrás (REQ-028/CA-06).
    """
    restante = float(segundos)
    while restante > 0:
        paso = min(_PASO_DE_ESPERA, restante)
        if stop_event is not None:
            if stop_event.wait(paso):
                return False
        else:
            time.sleep(paso)
        restante -= paso
    return True


@contextmanager
def _sesion_de_microfono(recognizer: sr.Recognizer, agent_label: str) -> Iterator[Any]:
    """Abrir el micrófono para UNA sesión de escucha, traduciendo el fallo del dispositivo.

    Es un context manager y no una función suelta porque el stream se abre en el `__enter__`
    de `sr.Microphone`: envolver solo la construcción dejaría fuera justo el punto donde
    PyAudio falla cuando otra aplicación ya tiene el dispositivo tomado.

    Todo lo que ocurre antes del `yield` —construir, abrir el stream y calibrar el ruido
    ambiente, que ya lee del dispositivo durante un segundo— cuenta como "al abrir".
    """
    abriendo = True
    try:
        with sr.Microphone() as source:
            print(f"\n[Modo Manos Libres]: Escuchando... Di \"{agent_label}\" para activarme")
            recognizer.adjust_for_ambient_noise(source, duration=1)
            abriendo = False
            yield source
    except OSError as e:
        raise _MicrofonoPerdido(str(e), al_abrir=abriendo) from e


def listen_for_wake_word(
    stop_event: Optional[threading.Event] = None,
    wake_state_callback: Optional[Callable[[str], None]] = None,
    conversation_window=None,
) -> Union[str, bool, None]:
    """Escuchar hasta detectar la wake word, o retornar por cancelación/KeyboardInterrupt.

    Retorna: `str` con el comando extraído tras la wake word, `True` si se detectó la wake
    word sin comando extra, `False` si se interrumpió con `KeyboardInterrupt`, o `None` si
    `stop_event` fue señalado (REQ-009/CA-05 — parada cooperativa, best-effort). Desde
    REQ-028 `None` cubre además el caso de que no haya ningún micrófono con el que escuchar
    (CA-07): para quien llama significa lo mismo de siempre —el bucle terminó solo y no hay
    comando que ejecutar—, y tanto `main.py` como `WakeWordWorker` ya lo tratan igual.

    `stop_event`/`wake_state_callback` son opcionales (`None` por defecto): sin ellos, el
    comportamiento es idéntico al existente antes de REQ-009 (uso desde `ui/cli.py` en
    modo headless, CA-07). Cuando se pasa `wake_state_callback` (uso desde la GUI), esta
    función omite la mutación de `GLOBAL_STATE` vía `update_gui_state()` para no hacer
    parpadear la píldora "Modo activo" existente con el ciclo del modo manos libres
    (REQ-009, ver "Decisión: no reusar GLOBAL_STATE desde la GUI").

    `conversation_window` (REQ-021, pieza 6) es opcional y por defecto `None`: sin él, el
    comportamiento es exactamente el de antes de REQ-021 —siempre hace falta la wake
    word—, así que el uso headless desde `ui/cli.py` no cambia. Cuando se pasa (lo hace
    `ui/webview/wake_word_worker.py`), una frase transcrita durante la ventana abierta se
    acepta SIN wake word y se devuelve por este mismo `return`: mismo camino, misma señal
    `command_detected`, mismo `resolve()`, mismo gate de seguridad.

    REQ-028: perder el micrófono ya no termina la función. Cada vuelta del `while` es una
    sesión de micrófono completa; si el dispositivo se cae, se espera con backoff y se abre
    otra. La reconexión vive acá y no en `WakeWordWorker` porque el camino headless
    (`main.py`, opción 3) no pasa por el worker y tenía exactamente el mismo problema.
    """
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False
    recognizer.energy_threshold = 400

    agent_label = get_agent_pronunciation() or get_agent_name()

    intento = 0                 # reintentos de la caída EN CURSO; 0 = no hay caída
    aperturas_fallidas = 0      # fallos seguidos sin llegar a leer: ¿hay micrófono siquiera?
    hubo_lectura_buena = False  # ¿este dispositivo llegó a responder alguna vez?
    perdido = False             # ¿ya se le avisó al usuario de la caída en curso?

    def al_leer_bien() -> None:
        """El dispositivo respondió: se da por terminada la caída, si es que había una.

        La señal de recuperación es una LECTURA, no una apertura. Un micrófono tomado por
        otra aplicación se deja abrir igual en Windows y falla recién al leerlo: dar por
        recuperada la sesión al abrirla reiniciaría el backoff en cada vuelta y el
        resultado sería el bucle de reintentos a máxima velocidad que este REQ evita.
        """
        nonlocal intento, aperturas_fallidas, hubo_lectura_buena, perdido
        hubo_lectura_buena = True
        aperturas_fallidas = 0
        if not perdido:
            return
        perdido = False
        intento = 0
        logger.info("[Wake word] Micrófono recuperado; el modo manos libres vuelve a escuchar")
        notificar(
            "Micrófono recuperado",
            "El modo manos libres volvió a escuchar.",
            "ok",
        )
        _report_state(wake_state_callback, "LISTENING_WAKE")

    while True:
        if stop_event is not None and stop_event.is_set():
            return None

        try:
            return _escuchar_en_sesion(
                recognizer, agent_label, stop_event, wake_state_callback,
                conversation_window, al_leer_bien,
            )
        except _MicrofonoPerdido as fallo:
            if fallo.al_abrir:
                aperturas_fallidas += 1
            intento += 1

            # CA-08: el primer fallo se grita, los reintentos se susurran. Una reunión de
            # una hora dejaría 120 líneas de `error` con el techo de 30 s, y el log del
            # agente serviría para nada más que para eso.
            if not perdido:
                perdido = True
                logger.error(
                    f"[Wake word] Se perdió el acceso al micrófono ({fallo}); "
                    f"el modo manos libres va a reconectarse solo"
                )
                notificar(
                    "Micrófono no disponible",
                    "Otra aplicación tomó el micrófono. El modo manos libres se "
                    "reconectará solo en cuanto vuelva a quedar libre.",
                    "error",
                )
            else:
                logger.debug(
                    f"[Wake word] Reintento {intento} de conexión al micrófono: {fallo}"
                )

            # CA-07: no haber podido abrir NUNCA el dispositivo es un caso distinto de
            # haberlo perdido en uso. Sin micrófono conectado no hay nada que esperar, y
            # reintentar para siempre sería un hilo vivo golpeando PyAudio de por vida.
            if (fallo.al_abrir and not hubo_lectura_buena
                    and aperturas_fallidas >= _MAX_APERTURAS_SIN_MICROFONO):
                logger.error(
                    f"[Wake word] No se pudo abrir ningún micrófono en "
                    f"{aperturas_fallidas} intentos; se apaga el modo manos libres"
                )
                notificar(
                    "Sin micrófono",
                    "No se encontró ningún micrófono disponible. El modo manos libres "
                    "quedó apagado.",
                    "error",
                )
                _report_state(wake_state_callback, "INACTIVE")
                return None

            # CA-04: "reconectando" no es "apagado". `INACTIVE` significa que lo apagaste
            # vos, y el botón no puede mentir sobre por qué dejó de escuchar.
            _report_state(wake_state_callback, "RECONNECTING")
            if not _esperar_troceado(siguiente_espera(intento), stop_event):
                return None


def _escuchar_en_sesion(
    recognizer: sr.Recognizer,
    agent_label: str,
    stop_event: Optional[threading.Event],
    wake_state_callback: Optional[Callable[[str], None]],
    conversation_window,
    al_leer_bien: Callable[[], None],
) -> Union[str, bool, None]:
    """Una sesión de micrófono completa: el cuerpo que `listen_for_wake_word()` tenía dentro.

    Devuelve lo mismo que `listen_for_wake_word()`, o levanta `_MicrofonoPerdido` si el
    dispositivo se cae — que es la única diferencia de comportamiento respecto de REQ-021.
    """
    with _sesion_de_microfono(recognizer, agent_label) as source:
        while True:
            if stop_event is not None and stop_event.is_set():
                return None

            # REQ-021/CA-13: la ventana venció sin voz -> el estado visible vuelve solo a
            # "esperando la wake word". Se evalúa acá arriba y no al final del `while`
            # porque varias ramas del cuerpo salen por `continue`.
            if conversation_window is not None and conversation_window.expired_now():
                _report_state(wake_state_callback, "LISTENING_WAKE")

            try:
                # REQ-021/CA-14: se marca ANTES de escuchar. Un chunk que empezó a
                # capturarse mientras el agente hablaba no puede aceptarse sin wake word
                # aunque termine después de abrirse la ventana.
                listen_started_at = time.monotonic()
                try:
                    audio = recognizer.listen(
                        source, timeout=1, phrase_time_limit=_limite_de_frase(),
                    )
                except OSError as e:
                    # REQ-028/CA-01: esto es PyAudio quedándose sin dispositivo
                    # (-9988 "Stream closed", -9999 "Unanticipated host error") porque otra
                    # aplicación se lo llevó. Antes propagaba, cerraba el micrófono y
                    # terminaba el worker; ahora corta solo ESTA sesión y se abre otra.
                    #
                    # Se captura `OSError` y nunca `Exception`: un error de código tiene que
                    # seguir subiendo y muriendo ruidosamente, no quedar tapado detrás de
                    # reintentos infinitos.
                    raise _MicrofonoPerdido(str(e), al_abrir=False) from e
                al_leer_bien()

                if wake_state_callback is None:
                    try:
                        from ui.gui import update_gui_state
                        update_gui_state("LISTENING")
                    except Exception:
                        pass

                text = ""
                try:
                    text = recognizer.recognize_google(audio, language="es-ES")
                except sr.UnknownValueError:
                    # REQ-009 (hallazgo post-QA, prueba manual): logging de diagnostico
                    # minimo — Google Speech no pudo transcribir el audio capturado. No
                    # cambia el comportamiento (sigue intentando el fallback local), solo
                    # deja evidencia de por que no hubo texto en este ciclo.
                    logger.info(
                        "[Wake word] Google Speech no pudo transcribir el audio "
                        "(UnknownValueError); probando fallback local"
                    )
                    text = _transcribe_whisper(audio)
                except sr.RequestError as e:
                    # REQ-009 (hallazgo post-QA, prueba manual): idem, pero distingue el
                    # caso de fallo de conexion/cuota con la API de Google del caso de
                    # audio no reconocido — son causas raiz distintas para diagnosticar.
                    logger.warning(
                        f"[Wake word] Fallo de conexion con la API de Google Speech ({e}); "
                        "probando fallback local"
                    )
                    text = _transcribe_whisper(audio)

                # Barge-in: se decide sobre el TEXTO, no sobre el sonido. Antes bastaba
                # con que el micrófono captara algo mientras el agente hablaba, y por los
                # altavoces eso es SIEMPRE cierto: el agente se cortaba a sí mismo a mitad
                # de frase, en cada respuesta. Ahora hace falta una transcripción con
                # contenido que además no sea lo que él mismo está diciendo.
                if text and _es_interrupcion_real(text):
                    try:
                        from ui.tts_engine import signal_barge_in

                        signal_barge_in()
                        logger.info(f"[Barge-in] Interrupción del usuario: '{text[:50]}'")
                        print("[Barge-in] Usuario interrumpio")
                    except Exception as e:
                        logger.error(f"No se pudo señalar el barge-in: {e}")

                if not text:
                    # REQ-009 (hallazgo post-QA): ningun motor devolvio texto. Con el
                    # fallback local (Whisper) no instalado por defecto (ver
                    # requirements.txt), este es el desenlace normal de cualquier fallo de
                    # recognize_google — antes quedaba en silencio total, indistinguible de
                    # "no se dijo nada".
                    logger.info(
                        "[Wake word] Ningun motor de reconocimiento devolvio texto en este "
                        "ciclo (silencio, audio ambiguo, o fallback local no disponible)"
                    )
                    continue

                # Una confirmación hablada pendiente se lleva la siguiente frase, por
                # delante de todo lo demás: ni wake word, ni ventana de conversación, ni
                # comando nuevo. Mientras el agente espera un "confirmo", nada más puede
                # ocupar el micrófono — si no, la misma frase podría interpretarse a la vez
                # como respuesta y como orden.
                try:
                    from voice.voice_confirmation import voice_confirmation

                    if voice_confirmation.hay_pendiente():
                        accion = voice_confirmation.accion_pendiente()
                        # El agente pregunta EN VOZ ALTA y el micrófono lo oye. Sin este
                        # filtro, su propia pregunta entraba como la respuesta y, al no ser
                        # un "confirmo", se contaba como rechazo antes de que el humano
                        # dijera nada. Se descarta y se sigue escuchando: la petición
                        # queda viva hasta que responda alguien de verdad, o venza sola.
                        if not voice_confirmation.acepta(listen_started_at):
                            logger.info(
                                "[Confirmación] descartado: la captura empezó mientras el "
                                "agente todavía preguntaba"
                            )
                            continue
                        if _es_su_propia_pregunta(text):
                            continue
                        logger.info(
                            f"[Confirmación] respuesta hablada a '{accion}': {text[:40]!r}"
                        )
                        voice_confirmation.responder(text)
                        continue
                except Exception as e:
                    logger.error(f"Fallo atendiendo la confirmación hablada: {e}")

                # REQ-021/CA-12: dentro de la ventana de conversación, la frase se acepta
                # sin exigir la wake word. `consume()` la cierra en el acto: UNA frase por
                # ventana, aunque el ruido siga.
                if conversation_window is not None \
                        and conversation_window.accepts(listen_started_at):
                    conversation_window.consume()
                    _report_awake(wake_state_callback)
                    logger.info(f"[Ventana] frase aceptada sin wake word: {text!r}")
                    return text.strip()

                is_wake, extracted_cmd = parse_wake_command(text)
                if is_wake:
                    print(f"[{agent_label} detectado]: '{text}'")
                    if extracted_cmd:
                        _report_awake(wake_state_callback)
                        return extracted_cmd
                    # Se dijo el nombre a secas: se avisa y se escucha el comando en la
                    # misma sesión de micrófono. Antes se devolvía `True` y el comando que
                    # el usuario dictaba a continuación se perdía por completo.
                    speak(f"Lo escucho{vocative()}")
                    _report_awake(wake_state_callback)
                    followup = _listen_for_followup(recognizer, source)
                    return followup if followup else True
                else:
                    # REQ-009 (hallazgo post-QA, prueba manual de Johan: "Probe lo manos
                    # libres activando el audio pero no me escucha"): evidencia clave para
                    # la proxima prueba — deja registrado que SI transcribio, pero el texto
                    # no matcheo ninguna wake word configurada (ver diagnostico en
                    # desarrollo-log-009.md).
                    logger.info(
                        f"[Wake word] Texto reconocido no coincide con ninguna wake word "
                        f"configurada: '{text}'"
                    )

            except sr.WaitTimeoutError:
                # Silencio, no un fallo: el dispositivo se dejó leer durante el timeout
                # entero. Cuenta como lectura buena, así que da por cerrada una
                # reconexión en curso igual que una frase transcrita (REQ-028/CA-05).
                al_leer_bien()
            except sr.UnknownValueError:
                pass
            except sr.RequestError:
                text = _transcribe_whisper(audio) if 'audio' in dir() else ""
                if text:
                    is_wake, extracted_cmd = parse_wake_command(text)
                    if is_wake:
                        if extracted_cmd:
                            _report_awake(wake_state_callback)
                            return extracted_cmd
                        speak(f"Lo escucho{vocative()}")
                        _report_awake(wake_state_callback)
                        return True
                continue
            except KeyboardInterrupt:
                print("\nSaliendo de modo manos libres...")
                return False
            finally:
                if wake_state_callback is None:
                    try:
                        from ui.gui import update_gui_state
                        update_gui_state("IDLE")
                    except Exception:
                        pass

            time.sleep(0.05)
