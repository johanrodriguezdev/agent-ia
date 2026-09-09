"""
workspace/adjuntos/REQ-028/origen/reproduccion-mic-ocupado.py
Reproduccion del fallo de REQ-028 SIN necesidad de una reunion real.

Simula lo que lanza PyAudio cuando otra app se lleva el microfono (o Windows cambia el
dispositivo por defecto) y mide dos cosas:
  1) que `listen_for_wake_word()` no lo captura y lo propaga, cerrando el microfono;
  2) que `WakeWordWorker.run()` termina, dejando el manos libres en INACTIVE sin reintentar.

Uso (desde la raiz del proyecto):
    python workspace/adjuntos/REQ-028/origen/reproduccion-mic-ocupado.py

Cuando el REQ este implementado, este mismo script tiene que terminar con el worker VIVO
y reintentando, no con `run()` retornado.
"""

import os
import sys
import types
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

import speech_recognition as sr

import voice.wake_word as ww

llamadas = {"listen": 0}


class MicFalso:
    """Microfono que abre bien y despues lo toma otra app."""

    def __enter__(self):
        print("   [mic] stream abierto", flush=True)
        return self

    def __exit__(self, *a):
        print("   [mic] stream CERRADO (sale del with)", flush=True)
        return False


def listen_falso(self, source, timeout=None, phrase_time_limit=None):
    llamadas["listen"] += 1
    if llamadas["listen"] == 1:
        raise sr.WaitTimeoutError("silencio")
    # Lo que lanza PyAudio cuando pierde el dispositivo.
    raise OSError(-9988, "Stream closed")


def _parches():
    return (
        patch.object(sr, "Microphone", lambda *a, **k: MicFalso()),
        patch.object(sr.Recognizer, "listen", listen_falso),
        patch.object(sr.Recognizer, "adjust_for_ambient_noise", lambda *a, **k: None),
    )


print("== 1) llamada directa a listen_for_wake_word() ==")
p1, p2, p3 = _parches()
with p1, p2, p3:
    try:
        resultado = ww.listen_for_wake_word()
        print(f"   -> retorno normal: {resultado!r}  (el REQ esta implementado)")
    except BaseException as e:
        print(f"   -> PROPAGA la excepcion: {type(e).__name__}: {e}")

print()
print("== 2) el worker de la GUI (WakeWordWorker.run) ==")
estados = []
with patch.dict(sys.modules, {"ui.webview.gui_state": types.SimpleNamespace(
        update_wake_state=lambda e: estados.append(e))}):
    from ui.webview.wake_word_worker import WakeWordWorker

    llamadas["listen"] = 0
    worker = WakeWordWorker()
    p1, p2, p3 = _parches()
    with p1, p2, p3, patch("ui.webview.wake_word_worker.update_wake_state",
                           lambda e: estados.append(e)):
        worker.run()

print(f"   estados reportados a la interfaz: {estados}")
print(f"   veces que se intento escuchar: {llamadas['listen']}")
print("   run() retorno -> el manos libres quedo apagado sin reintentar")
