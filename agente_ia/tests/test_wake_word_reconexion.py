"""
tests/test_wake_word_reconexion.py

REQ-028 — el modo manos libres sobrevive a que otra aplicación tome el micrófono.

Hasta acá, un `OSError` de PyAudio salía del `with sr.Microphone()`, cerraba el
dispositivo y terminaba el worker: el manos libres se apagaba en silencio y no volvía ni
cuando el micrófono quedaba libre. Estos tests fijan lo contrario — que la sesión se corta,
se espera con backoff y se abre otra— y los dos límites que evitan que el remedio sea peor:
no reintentar para siempre cuando directamente no hay micrófono (CA-07) y no dejar el hilo
colgado 30 segundos cuando el usuario apaga el manos libres (CA-06).

Sin micrófono real, sin PyAudio, sin red y sin dormir de verdad: `sr.Microphone` y
`Recognizer.listen` van mockeados y la espera se sustituye por un espía
(.claude/rules/testing.md, CA-12).
"""

import inspect
import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

import config_manager
import voice.wake_word as wake_word_module


# ─────────────────────────────────────────────
#  Dobles de prueba
# ─────────────────────────────────────────────

class MicrofonoFalso:
    """Micrófono de mentira, con control sobre cuántas aperturas fallan.

    `fallos_al_abrir` simula el dispositivo ausente o tomado desde antes; `None` significa
    "falla siempre", que es el caso de no tener ningún micrófono conectado.
    """

    def __init__(self, fallos_al_abrir: int = 0) -> None:
        self.fallos_al_abrir = fallos_al_abrir
        self.aperturas = 0

    def __enter__(self):
        self.aperturas += 1
        if self.fallos_al_abrir is None or self.aperturas <= self.fallos_al_abrir:
            raise OSError(-9996, "Invalid device")
        return MagicMock()

    def __exit__(self, *args) -> bool:
        return False


class EsperaEspia:
    """Reemplaza a `_esperar_troceado()`: anota cuánto se pidió esperar y no duerme nada.

    `cortar_en` deja terminar el bucle igual que lo haría el `stop_event` del usuario, para
    que un test de reconexión no se quede corriendo para siempre.
    """

    def __init__(self, cortar_en: int = 50) -> None:
        self.esperas: list[float] = []
        self.cortar_en = cortar_en

    def __call__(self, segundos: float, stop_event) -> bool:
        self.esperas.append(segundos)
        return len(self.esperas) < self.cortar_en


@pytest.fixture
def perfil(monkeypatch):
    """Nombre de agente fijo, para que la wake word no dependa de la config del equipo."""
    monkeypatch.setattr(config_manager, "get_agent_name", lambda: "O.R.I.O.N")
    monkeypatch.setattr(config_manager, "get_agent_pronunciation", lambda: "orion")


def _recognizer_falso(guion) -> MagicMock:
    """Recognizer cuyo `listen()` sigue `guion`: una lista de excepciones o de `None`."""
    recognizer = MagicMock()
    pasos = list(guion)
    estado = {"n": 0}

    def listen(source, timeout=None, phrase_time_limit=None):
        paso = pasos[estado["n"]] if estado["n"] < len(pasos) else pasos[-1]
        estado["n"] += 1
        if isinstance(paso, BaseException):
            raise paso
        return MagicMock()

    recognizer.listen.side_effect = listen
    return recognizer


def _correr(mic, recognizer, estados=None, espera=None, stop_event=None, frase=None):
    """Corre `listen_for_wake_word()` con todo mockeado. Devuelve (resultado, espera)."""
    espera = espera or EsperaEspia()
    stop_event = stop_event if stop_event is not None else threading.Event()

    if frase is not None:
        def transcribir(audio, language=None):
            stop_event.set()          # una frase y se corta, como en test_mic_window
            return frase

        recognizer.recognize_google.side_effect = transcribir

    with patch.object(wake_word_module.sr, "Microphone", lambda *a, **k: mic), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=recognizer), \
         patch.object(wake_word_module, "_esperar_troceado", espera), \
         patch.object(wake_word_module, "speak"):
        resultado = wake_word_module.listen_for_wake_word(
            stop_event=stop_event,
            wake_state_callback=(estados.append if estados is not None else None),
        )
    return resultado, espera


# ─────────────────────────────────────────────
#  CA-03 — la escalera de backoff (función pura)
# ─────────────────────────────────────────────

def test_ca03_la_espera_crece_y_tiene_techo():
    esperas = [wake_word_module.siguiente_espera(i) for i in range(1, 9)]

    assert esperas == [1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 30.0, 30.0]


def test_ca03_la_espera_no_se_dispara_con_un_intento_absurdo():
    """El techo es techo: ni un reintento número mil espera más de 30 segundos."""
    assert wake_word_module.siguiente_espera(1000) == 30.0
    # Un intento 0 o negativo no puede devolver un índice raro ni una espera negativa.
    assert wake_word_module.siguiente_espera(0) == 1.0
    assert wake_word_module.siguiente_espera(-5) == 1.0


# ─────────────────────────────────────────────
#  CA-06 — la espera es troceada y atiende al stop_event
# ─────────────────────────────────────────────

def test_ca06_la_espera_consulta_el_stop_event_en_cada_trozo():
    consultas = []

    class EventoEspia:
        def wait(self, timeout=None):
            consultas.append(timeout)
            return False

    assert wake_word_module._esperar_troceado(2.0, EventoEspia()) is True
    # 2 s en trozos de 0.5 s: cuatro consultas, ninguna de 2 s de largo.
    assert consultas == [0.5, 0.5, 0.5, 0.5]
    assert max(consultas) <= wake_word_module._PASO_DE_ESPERA


def test_ca06_apagar_el_manos_libres_corta_la_espera_en_menos_de_un_segundo():
    """Sin trocear, apagar durante el último escalón tardaría los 30 s enteros."""
    stop_event = threading.Event()
    threading.Timer(0.05, stop_event.set).start()

    inicio = time.monotonic()
    siguio = wake_word_module._esperar_troceado(30.0, stop_event)
    transcurrido = time.monotonic() - inicio

    assert siguio is False, "debe avisar que hay que parar, no seguir reconectando"
    assert transcurrido < 1.0, f"tardó {transcurrido:.2f}s en atender el apagado"


def test_ca06_sin_stop_event_la_espera_igual_termina():
    """El camino headless llama sin `stop_event`: la espera no puede colgarse ahí."""
    inicio = time.monotonic()
    assert wake_word_module._esperar_troceado(0.1, None) is True
    assert time.monotonic() - inicio < 1.0


def test_ca06_el_apagado_durante_la_espera_termina_listen_for_wake_word(perfil):
    """Si la espera dice "hay que parar", el bucle de sesiones retorna en vez de reabrir."""
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed")])

    resultado, espera = _correr(mic, recognizer, espera=EsperaEspia(cortar_en=1))

    assert resultado is None
    assert mic.aperturas == 1, "no debía abrir una sesión nueva después del apagado"


# ─────────────────────────────────────────────
#  CA-01 / CA-05 — perder el micrófono leyendo no mata la función
# ─────────────────────────────────────────────

def test_ca01_un_oserror_al_leer_abre_una_sesion_nueva_y_sigue_escuchando(perfil):
    """El fallo exacto del reporte: `-9988 Stream closed` en mitad de una reunión."""
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed"), None])

    resultado, espera = _correr(mic, recognizer, frase="orión abre chrome")

    assert resultado == "abre chrome", "la función siguió viva y entregó el comando"
    assert mic.aperturas == 2, "cerró la sesión caída y abrió una nueva"
    assert espera.esperas == [1.0], "esperó una sola vez, el primer escalón"


def test_ca01_el_error_del_host_de_audio_tambien_reconecta(perfil):
    """-9999 "Unanticipated host error" es el otro `OSError` que tira PyAudio."""
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9999, "Unanticipated host error"), None])

    resultado, _ = _correr(mic, recognizer, frase="orión que hora es")

    assert resultado == "que hora es"


def test_ca05_al_reconectar_vuelve_a_listening_wake_sin_tocar_nada(perfil):
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed"), None])
    estados = []

    resultado, _ = _correr(mic, recognizer, estados=estados, frase="orión abre chrome")

    assert resultado == "abre chrome"
    assert "RECONNECTING" in estados
    assert estados.index("RECONNECTING") < estados.index("LISTENING_WAKE"), \
        "primero reconectando, y recién cuando el micrófono responde, escuchando"


def test_ca01_un_error_de_codigo_no_queda_tapado_por_los_reintentos(perfil):
    """Solo se captura `OSError`. Un bug del propio código tiene que seguir muriendo."""
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([TypeError("bug de verdad")])

    with pytest.raises(TypeError, match="bug de verdad"):
        _correr(mic, recognizer)


# ─────────────────────────────────────────────
#  CA-02 — el fallo al ABRIR el micrófono tampoco mata la función
# ─────────────────────────────────────────────

def test_ca02_un_oserror_al_abrir_el_microfono_reintenta_y_se_recupera(perfil):
    mic = MicrofonoFalso(fallos_al_abrir=1)
    recognizer = _recognizer_falso([None])

    resultado, espera = _correr(mic, recognizer, frase="orión abre chrome")

    assert resultado == "abre chrome"
    assert mic.aperturas == 2
    assert espera.esperas == [1.0]


def test_ca02_dos_fallos_al_abrir_seguidos_todavia_se_recuperan(perfil):
    """El techo de CA-07 es 3: con dos fallos todavía tiene que reconectar, no rendirse."""
    mic = MicrofonoFalso(fallos_al_abrir=2)
    recognizer = _recognizer_falso([None])

    resultado, espera = _correr(mic, recognizer, frase="orión abre chrome")

    assert resultado == "abre chrome"
    assert espera.esperas == [1.0, 2.0], "el backoff creció entre los dos reintentos"


# ─────────────────────────────────────────────
#  CA-04 — RECONNECTING no es INACTIVE
# ─────────────────────────────────────────────

def test_ca04_mientras_reintenta_el_estado_es_reconnecting_y_no_inactive(perfil):
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed")])
    estados = []

    _correr(mic, recognizer, estados=estados, espera=EsperaEspia(cortar_en=3))

    assert "RECONNECTING" in estados
    assert "INACTIVE" not in estados, \
        "INACTIVE significa 'lo apagaste vos'; el botón no puede mentir sobre por qué calla"


# ─────────────────────────────────────────────
#  CA-07 — sin micrófono no hay bucle infinito
# ─────────────────────────────────────────────

def test_ca07_sin_microfono_se_rinde_tras_tres_intentos_y_queda_inactive(perfil):
    mic = MicrofonoFalso(fallos_al_abrir=None)      # no hay dispositivo, nunca abre
    recognizer = _recognizer_falso([None])
    estados = []

    resultado, espera = _correr(
        mic, recognizer, estados=estados, espera=EsperaEspia(cortar_en=99),
    )

    assert resultado is None
    assert mic.aperturas == wake_word_module._MAX_APERTURAS_SIN_MICROFONO == 3
    assert estados[-1] == "INACTIVE", "se apaga de verdad, no queda reconectando de adorno"
    assert espera.esperas == [1.0, 2.0], "esperó entre los 3 intentos, no después del último"


def test_ca07_lo_que_alguna_vez_funciono_se_reintenta_indefinidamente(perfil):
    """La distinción del REQ: perder el micrófono en uso NO es lo mismo que no tenerlo.

    El dispositivo respondió una vez (un timeout es una lectura buena: se leyó silencio),
    así que aunque después no vuelva a abrir nunca, el manos libres sigue esperándolo.
    """
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([
        wake_word_module.sr.WaitTimeoutError(),      # el micrófono anduvo
        OSError(-9988, "Stream closed"),             # y acá se lo llevaron
    ])
    espera = EsperaEspia(cortar_en=8)

    resultado, espera = _correr(mic, recognizer, espera=espera)

    assert resultado is None                          # terminó por el apagado del espía
    assert mic.aperturas > wake_word_module._MAX_APERTURAS_SIN_MICROFONO, \
        "un micrófono que alguna vez funcionó no se abandona a los 3 intentos"


def test_ca07_el_backoff_no_se_reinicia_si_el_microfono_no_responde(perfil):
    """Abrir no es recuperarse: en Windows el dispositivo tomado se deja abrir igual.

    Si bastara con abrir para dar por terminada la caída, el backoff volvería a 1 s en cada
    vuelta y el resultado sería el bucle golpeando PyAudio una vez por segundo que el REQ
    vino a evitar.
    """
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([
        wake_word_module.sr.WaitTimeoutError(),      # una lectura buena, para no rendirse
        OSError(-9988, "Stream closed"),
    ])

    _, espera = _correr(mic, recognizer, espera=EsperaEspia(cortar_en=7))

    assert espera.esperas == [1.0, 2.0, 4.0, 8.0, 15.0, 30.0, 30.0]


# ─────────────────────────────────────────────
#  CA-08 — el log no se inunda
# ─────────────────────────────────────────────

def test_ca08_el_primer_fallo_es_error_y_los_reintentos_son_debug(perfil, caplog):
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([
        wake_word_module.sr.WaitTimeoutError(),
        OSError(-9988, "Stream closed"),
    ])

    with caplog.at_level(logging.DEBUG, logger=wake_word_module.logger.name):
        _correr(mic, recognizer, espera=EsperaEspia(cortar_en=6))

    errores = [r for r in caplog.records if r.levelno == logging.ERROR]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]

    assert len(errores) == 1, f"una reunión de una hora no puede dejar N errores: {errores}"
    assert "perdió el acceso al micrófono" in errores[0].message
    assert len(debugs) >= 4, "los reintentos igual quedan registrados, pero en debug"


def test_ca08_recuperar_el_microfono_se_loguea_como_info(perfil, caplog):
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed"), None])

    with caplog.at_level(logging.INFO, logger=wake_word_module.logger.name):
        _correr(mic, recognizer, frase="orión abre chrome")

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("Micrófono recuperado" in r.message for r in infos)


# ─────────────────────────────────────────────
#  CA-09 — el usuario se entera
# ─────────────────────────────────────────────

def test_ca09_avisa_al_perder_y_al_recuperar_el_microfono(perfil):
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed"), None])
    avisos = []

    with patch.object(wake_word_module, "notificar",
                      lambda t, m="", n="info": avisos.append((t, n))):
        _correr(mic, recognizer, frase="orión abre chrome")

    titulos = [t for t, _ in avisos]
    assert titulos == ["Micrófono no disponible", "Micrófono recuperado"]
    assert [n for _, n in avisos] == ["error", "ok"]


def test_ca09_no_avisa_una_vez_por_reintento(perfil):
    """Un aviso por caída, no uno cada 30 segundos durante toda la reunión."""
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed")])
    avisos = []

    with patch.object(wake_word_module, "notificar",
                      lambda t, m="", n="info": avisos.append(t)):
        _correr(mic, recognizer, espera=EsperaEspia(cortar_en=6))

    assert avisos == ["Micrófono no disponible"]


def test_ca09_quedarse_sin_microfono_tambien_avisa(perfil):
    mic = MicrofonoFalso(fallos_al_abrir=None)
    recognizer = _recognizer_falso([None])
    avisos = []

    with patch.object(wake_word_module, "notificar",
                      lambda t, m="", n="info": avisos.append(t)):
        _correr(mic, recognizer)

    assert avisos == ["Micrófono no disponible", "Sin micrófono"]


# ─────────────────────────────────────────────
#  CA-10 / CA-11 — el camino headless y la firma pública
# ─────────────────────────────────────────────

def test_ca10_el_camino_headless_sin_callback_reconecta_igual(perfil):
    """`main.py` (opción 3) llama sin `wake_state_callback` y no pasa por el worker."""
    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([OSError(-9988, "Stream closed"), None])

    resultado, espera = _correr(mic, recognizer, estados=None, frase="orión abre chrome")

    assert resultado == "abre chrome"
    assert mic.aperturas == 2
    assert espera.esperas == [1.0]


def test_ca11_la_firma_publica_de_listen_for_wake_word_no_cambio():
    firma = inspect.signature(wake_word_module.listen_for_wake_word)

    assert list(firma.parameters) == [
        "stop_event", "wake_state_callback", "conversation_window",
    ]
    assert all(p.default is None for p in firma.parameters.values())


def test_ca11_el_stop_event_ya_seteado_sigue_retornando_none_sin_abrir_el_microfono():
    """Comportamiento de REQ-009 intacto: el bucle de sesiones no lo pisa."""
    stop_event = threading.Event()
    stop_event.set()
    mic = MicrofonoFalso()
    recognizer = MagicMock()

    with patch.object(wake_word_module.sr, "Microphone", lambda *a, **k: mic), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=recognizer):
        resultado = wake_word_module.listen_for_wake_word(stop_event=stop_event)

    assert resultado is None
    assert mic.aperturas == 0
    recognizer.listen.assert_not_called()


# ─────────────────────────────────────────────
#  CA-13 — el worker de la GUI queda vivo, que es el antes/después del REQ
# ─────────────────────────────────────────────

def test_ca13_el_worker_de_la_gui_no_termina_por_perder_el_microfono(perfil):
    """Antes de REQ-028 `run()` retornaba al primer `OSError` y el toggle volvía a INACTIVE.

    Acá se corre el worker en un hilo aparte y se comprueba que sigue vivo reintentando; se
    lo apaga con su propio `stop_event`, que es como lo apaga el usuario desde la ventana.
    """
    from ui.webview.wake_word_worker import WakeWordWorker

    mic = MicrofonoFalso()
    recognizer = _recognizer_falso([
        wake_word_module.sr.WaitTimeoutError(),
        OSError(-9988, "Stream closed"),
    ])
    reintentos = threading.Event()
    esperas: list[float] = []

    def espera_falsa(segundos, stop_event):
        esperas.append(segundos)
        if len(esperas) >= 3:
            reintentos.set()
        return not (stop_event is not None and stop_event.is_set())

    worker = WakeWordWorker()
    with patch.object(wake_word_module.sr, "Microphone", lambda *a, **k: mic), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=recognizer), \
         patch.object(wake_word_module, "_esperar_troceado", espera_falsa), \
         patch.object(wake_word_module, "speak"):
        hilo = threading.Thread(target=worker.run, daemon=True)
        hilo.start()
        assert reintentos.wait(timeout=10), "el worker no llegó a reintentar"
        assert hilo.is_alive(), "el worker murió al perder el micrófono (el bug de REQ-028)"
        worker.stop_event.set()
        hilo.join(timeout=10)

    assert not hilo.is_alive(), "el apagado tiene que terminar el worker"
    assert esperas[:3] == [1.0, 2.0, 4.0], "reintentó con backoff, no a máquina"
