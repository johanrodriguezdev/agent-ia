"""
workspace/adjuntos/REQ-028/origen/reproduccion-mic-ocupado.py
Reproduccion del fallo de REQ-028 SIN necesidad de una reunion real.

Simula lo que lanza PyAudio cuando otra app se lleva el microfono (o Windows cambia el
dispositivo por defecto) y mide dos cosas:
  1) que `listen_for_wake_word()` sobrevive al fallo y abre una sesion nueva, en vez de
     propagarlo y dejar el microfono cerrado;
  2) que `WakeWordWorker.run()` sigue VIVO reintentando, en vez de retornar y dejar el
     manos libres en INACTIVE sin aviso.

Uso (desde la raiz del proyecto):
    python workspace/adjuntos/REQ-028/origen/reproduccion-mic-ocupado.py

ANTES de REQ-028 esto terminaba asi:
    -> PROPAGA la excepcion: OSError: [Errno -9988] Stream closed
    estados reportados a la interfaz: ['LISTENING_WAKE', 'INACTIVE']
    veces que se intento escuchar: 2
    run() retorno -> el manos libres quedo apagado sin reintentar

DESPUES de REQ-028 tiene que terminar con el worker vivo y reintentando con backoff. La
espera va parcheada por un espia (se anota cuanto se pidio esperar y no se duerme), asi que
el script termina en segundos en vez de en minuto y medio; los numeros que imprime son los
segundos reales que el backoff pidio.
"""

import os
import sys
import threading
import time
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


class EsperaEspia:
    """Reemplaza a `_esperar_troceado()`: anota el backoff pedido y casi no duerme.

    `tope` corta el bucle despues de N reintentos, que es lo que haria el `stop_event` del
    usuario al apagar el manos libres: sin algo que lo corte el script correria para
    siempre, que es justamente la prueba de que el REQ funciona.

    `aviso` se levanta a los `aviso_en` reintentos y NO corta nada: sirve para que el hilo
    principal sepa que el worker ya esta reintentando y pueda comprobar que sigue vivo.
    """

    def __init__(self, tope=None, aviso=None, aviso_en=3):
        self.esperas = []
        self.tope = tope
        self.aviso = aviso
        self.aviso_en = aviso_en

    def __call__(self, segundos, stop_event):
        self.esperas.append(segundos)
        if self.aviso is not None and len(self.esperas) >= self.aviso_en:
            self.aviso.set()
        if self.tope is not None and len(self.esperas) >= self.tope:
            return False
        # Un trocito real de espera: sin esto el bucle girazia en vacio quemando CPU
        # mientras el hilo principal comprueba que el worker sigue vivo.
        if stop_event is not None:
            return not stop_event.wait(0.01)
        time.sleep(0.01)
        return True


def _parches(espera):
    return (
        patch.object(sr, "Microphone", lambda *a, **k: MicFalso()),
        patch.object(sr.Recognizer, "listen", listen_falso),
        patch.object(sr.Recognizer, "adjust_for_ambient_noise", lambda *a, **k: None),
        patch.object(ww, "_esperar_troceado", espera),
    )


print("== 1) llamada directa a listen_for_wake_word() ==")
espera1 = EsperaEspia(tope=4)
p1, p2, p3, p4 = _parches(espera1)
with p1, p2, p3, p4:
    try:
        resultado = ww.listen_for_wake_word()
        print(f"   -> retorno normal: {resultado!r}  (no propago la excepcion)")
    except BaseException as e:
        print(f"   -> PROPAGA la excepcion: {type(e).__name__}: {e}")
print(f"   sesiones de microfono reintentadas: {len(espera1.esperas)}")
print(f"   backoff pedido (segundos): {espera1.esperas}")

print()
print("== 2) el worker de la GUI (WakeWordWorker.run) ==")
estados = []
reintentando = threading.Event()
with patch.dict(sys.modules, {"ui.webview.gui_state": types.SimpleNamespace(
        update_wake_state=lambda e: estados.append(e))}):
    from ui.webview.wake_word_worker import WakeWordWorker

    llamadas["listen"] = 0
    worker = WakeWordWorker()
    espera2 = EsperaEspia(aviso=reintentando, aviso_en=3)
    p1, p2, p3, p4 = _parches(espera2)
    with p1, p2, p3, p4, patch("ui.webview.wake_word_worker.update_wake_state",
                               lambda e: estados.append(e)):
        # El worker corre en un hilo aparte a proposito: despues del REQ `run()` ya NO
        # retorna solo, y llamarlo en linea colgaria el script para siempre.
        hilo = threading.Thread(target=worker.run, daemon=True)
        hilo.start()
        vivo = reintentando.wait(timeout=15)
        sigue_vivo = hilo.is_alive()
        worker.stop_event.set()          # lo mismo que apagar el toggle en la ventana
        hilo.join(timeout=15)

resumen = []
for estado in estados:                    # se colapsan las repeticiones seguidas
    if not resumen or resumen[-1] != estado:
        resumen.append(estado)

print(f"   llego a reintentar: {vivo}")
print(f"   worker VIVO mientras reintentaba: {sigue_vivo}")
print(f"   estados reportados a la interfaz: {resumen}")
print(f"   veces que se intento escuchar: {llamadas['listen']}")
print(f"   backoff pedido (segundos): {espera2.esperas[:8]}")
print(f"   worker terminado tras apagar el toggle: {not hilo.is_alive()}")

print()
if vivo and sigue_vivo and "RECONNECTING" in estados:
    print("RESULTADO: el manos libres sobrevivio al microfono ocupado y siguio reintentando.")
else:
    print("RESULTADO: FALLA — el manos libres murio al perder el microfono (bug de REQ-028).")
    sys.exit(1)
