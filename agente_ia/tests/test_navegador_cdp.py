"""
tests/test_navegador_cdp.py
Pruebas de `os_integration/navegador_cdp.py` — REQ-069, el navegador fuera de Windows.

Lo que protege esta suite:

- **Windows no cambió.** Las siete funciones públicas de `navegador.py` solo delegan
  cuando NO se está en Windows; en Windows siguen entrando en el código de UI Automation.
- **La delegación es completa.** Si una función pública se olvidara de delegar, en Linux
  ejecutaría código de UI Automation y reventaría con un error incomprensible. Se comprueba
  que las siete la tienen.
- **El protocolo se habla bien**: listar, abrir, activar y cerrar por HTTP; leer y pulsar
  por WebSocket; y cada fallo —sin navegador instalado, sin la dependencia, sin pestañas—
  responde con una frase que se le puede decir al usuario, no con una excepción.

No se abre ningún navegador: se simulan el proceso y las respuestas del protocolo.
"""

import json

import pytest

from os_integration import navegador, navegador_cdp


@pytest.fixture(autouse=True)
def _sin_navegador_de_verdad(monkeypatch):
    """Ningún test puede lanzar un Chrome real ni dejar uno vivo."""
    monkeypatch.setattr(navegador_cdp, "_proceso", None)
    monkeypatch.setattr(navegador_cdp, "_puerto", None)
    monkeypatch.setattr(navegador_cdp, "_perfil", None)
    yield


class _ProcesoVivo:
    def poll(self):
        return None


@pytest.fixture
def navegador_levantado(monkeypatch):
    """Simula que el agente ya tiene su ventana abierta, en el puerto 9999."""
    monkeypatch.setattr(navegador_cdp, "_proceso", _ProcesoVivo())
    monkeypatch.setattr(navegador_cdp, "_puerto", 9999)
    return 9999


def _pestana(id_, titulo, url="https://ejemplo.com"):
    return {"id": id_, "type": "page", "title": titulo, "url": url,
            "webSocketDebuggerUrl": f"ws://127.0.0.1:9999/devtools/page/{id_}"}


# ------------------------------------------------------------------ la delegación

def test_en_windows_no_se_delega_nunca():
    """La garantía de que este REQ no tocó Windows."""
    import os as _os

    if _os.name != "nt":
        pytest.skip("solo tiene sentido comprobarlo en Windows")
    assert navegador._ES_WINDOWS is True


def test_las_siete_funciones_publicas_delegan_fuera_de_windows():
    """Una que se olvide ejecutaría UI Automation en Linux y fallaría sin explicar nada."""
    import inspect

    publicas = ("abrir", "resumen_de_pagina", "accionar", "texto_de_pagina",
                "listar_pestanas", "cambiar_de_pestana", "cerrar_pestana")
    for nombre in publicas:
        fuente = inspect.getsource(getattr(navegador, nombre))
        assert "_ES_WINDOWS" in fuente, f"{nombre} no delega fuera de Windows"
        assert f"_cdp().{nombre}(" in fuente, f"{nombre} no llama a su equivalente de CDP"


def test_el_adaptador_ofrece_todo_lo_que_la_fachada_le_pide():
    for nombre in ("abrir", "resumen_de_pagina", "accionar", "texto_de_pagina",
                   "listar_pestanas", "cambiar_de_pestana", "cerrar_pestana"):
        assert callable(getattr(navegador_cdp, nombre)), nombre


# ------------------------------------------------------------------ sin navegador

def test_sin_chrome_instalado_se_dice_en_vez_de_fallar(monkeypatch):
    monkeypatch.setattr(navegador_cdp, "_ejecutable", lambda: None)

    respuesta = navegador_cdp.abrir("ejemplo.com")

    assert "no encontré" in respuesta.lower()
    assert "chrome" in respuesta.lower() or "chromium" in respuesta.lower()


def test_sin_navegador_abierto_las_lecturas_lo_dicen():
    for respuesta in (navegador_cdp.listar_pestanas(),
                      navegador_cdp.texto_de_pagina(),
                      navegador_cdp.resumen_de_pagina(),
                      navegador_cdp.accionar("aceptar")):
        assert "no hay ninguna ventana" in respuesta.lower()


def test_firefox_no_se_usa_para_cdp(monkeypatch):
    """Firefox habla otro protocolo de depuración: elegirlo sería prometer algo falso."""
    monkeypatch.setattr(navegador, "NAVEGADORES",
                        (("Mozilla Firefox", ("firefox",)),
                         ("Google Chrome", ("google-chrome",))))
    monkeypatch.setattr(navegador_cdp.shutil, "which",
                        lambda n: f"/usr/bin/{n}")

    nombre, _ruta = navegador_cdp._ejecutable()
    assert nombre == "Google Chrome"


# ------------------------------------------------------------------ las pestañas (HTTP)

def test_listar_pestanas_marca_la_que_esta_delante(navegador_levantado, monkeypatch):
    monkeypatch.setattr(navegador_cdp, "_pedir", lambda ruta: [
        _pestana("1", "Wikipedia"), _pestana("2", "Correo"),
        {"id": "3", "type": "service_worker", "title": "no es una pestaña"},
    ])

    respuesta = navegador_cdp.listar_pestanas()

    assert "«Wikipedia»  ← la que estás viendo" in respuesta
    assert "«Correo»" in respuesta
    assert "no es una pestaña" not in respuesta      # los service workers no son pestañas


def test_cambiar_de_pestana_por_titulo(navegador_levantado, monkeypatch):
    pedidos = []

    def _pedir(ruta):
        pedidos.append(ruta)
        if ruta == "/json/list":
            return [_pestana("1", "Wikipedia"), _pestana("2", "Correo de Johan")]
        return "Target activated"

    monkeypatch.setattr(navegador_cdp, "_pedir", _pedir)
    respuesta = navegador_cdp.cambiar_de_pestana("correo")

    assert "/json/activate/2" in pedidos
    assert "Correo de Johan" in respuesta


def test_cambiar_de_pestana_por_numero(navegador_levantado, monkeypatch):
    pedidos = []

    def _pedir(ruta):
        pedidos.append(ruta)
        if ruta == "/json/list":
            return [_pestana("1", "Wikipedia"), _pestana("2", "Correo")]
        return "ok"

    monkeypatch.setattr(navegador_cdp, "_pedir", _pedir)
    navegador_cdp.cambiar_de_pestana("2")

    assert "/json/activate/2" in pedidos


def test_una_pestana_que_no_existe_se_dice(navegador_levantado, monkeypatch):
    monkeypatch.setattr(navegador_cdp, "_pedir",
                        lambda ruta: [_pestana("1", "Wikipedia")] if ruta == "/json/list" else "ok")

    assert "no encontré" in navegador_cdp.cambiar_de_pestana("banco").lower()
    assert "no encontré" in navegador_cdp.cerrar_pestana("banco").lower()


def test_cerrar_pestana(navegador_levantado, monkeypatch):
    pedidos = []

    def _pedir(ruta):
        pedidos.append(ruta)
        return [_pestana("7", "Wikipedia")] if ruta == "/json/list" else "ok"

    monkeypatch.setattr(navegador_cdp, "_pedir", _pedir)
    respuesta = navegador_cdp.cerrar_pestana("wikipedia")

    assert "/json/close/7" in pedidos
    assert "Cerré «Wikipedia»" in respuesta


# ------------------------------------------------------------------ la página (WebSocket)

def test_el_texto_de_la_pagina_se_recorta_y_se_avisa(navegador_levantado, monkeypatch):
    monkeypatch.setattr(navegador_cdp, "_evaluar", lambda js, p=None: ("hola " * 4000, ""))

    respuesta = navegador_cdp.texto_de_pagina(100)

    assert len(respuesta) < 200
    assert "texto cortado" in respuesta


def test_sin_la_dependencia_de_websocket_se_explica(navegador_levantado, monkeypatch):
    monkeypatch.setattr(navegador_cdp, "_evaluar",
                        lambda js, p=None: (None, "Falta la dependencia 'websocket-client' "
                                                  "para leer la página."))

    assert "websocket-client" in navegador_cdp.texto_de_pagina()


def test_el_resumen_numera_lo_accionable(navegador_levantado, monkeypatch):
    datos = json.dumps({
        "titulo": "Wikipedia", "url": "https://es.wikipedia.org",
        "elementos": [{"n": 1, "tipo": "a", "texto": "Portada"},
                      {"n": 2, "tipo": "input", "texto": "Buscar"}],
    })
    monkeypatch.setattr(navegador_cdp, "_evaluar", lambda js, p=None: (datos, ""))

    respuesta = navegador_cdp.resumen_de_pagina()

    assert "«Wikipedia»" in respuesta
    assert "1. [a] Portada" in respuesta
    assert "2. [input] Buscar" in respuesta
    assert "por su número" in respuesta


def test_una_pagina_sin_nada_accionable_lo_dice(navegador_levantado, monkeypatch):
    datos = json.dumps({"titulo": "Un PDF", "url": "file:///x.pdf", "elementos": []})
    monkeypatch.setattr(navegador_cdp, "_evaluar", lambda js, p=None: (datos, ""))

    assert "no encontré nada accionable" in navegador_cdp.resumen_de_pagina().lower()


def test_pulsar_devuelve_lo_que_se_pulso(navegador_levantado, monkeypatch):
    ejecutados = []

    def _evaluar(js, p=None):
        ejecutados.append(js)
        return json.dumps({"ok": True, "accion": "pulsar", "etiqueta": "Aceptar"}), ""

    monkeypatch.setattr(navegador_cdp, "_evaluar", _evaluar)
    monkeypatch.setattr(navegador_cdp.time, "sleep", lambda _s: None)

    respuesta = navegador_cdp.accionar("aceptar")

    assert "Pulsé «Aceptar»" in respuesta
    assert '"aceptar"' in ejecutados[0]               # el objetivo va escapado como JSON


def test_escribir_en_un_campo(navegador_levantado, monkeypatch):
    ejecutados = []

    def _evaluar(js, p=None):
        ejecutados.append(js)
        return json.dumps({"ok": True, "accion": "escribir", "etiqueta": "Buscar"}), ""

    monkeypatch.setattr(navegador_cdp, "_evaluar", _evaluar)
    monkeypatch.setattr(navegador_cdp.time, "sleep", lambda _s: None)

    respuesta = navegador_cdp.accionar("buscar", "palmas de aceite")

    assert "Escribí «palmas de aceite»" in respuesta
    assert '"palmas de aceite"' in ejecutados[0]


def test_lo_que_no_esta_en_la_pagina_se_dice_y_se_sugiere_como_mirarla(navegador_levantado,
                                                                       monkeypatch):
    monkeypatch.setattr(navegador_cdp, "_evaluar",
                        lambda js, p=None: (json.dumps({"ok": False, "motivo": "no encontrado"}), ""))

    respuesta = navegador_cdp.accionar("un botón que no existe")

    assert "no encontré" in respuesta.lower()
    assert "browser_page" in respuesta


def test_un_objetivo_con_comillas_no_rompe_el_javascript(navegador_levantado, monkeypatch):
    """Si el objetivo se pegara al código sin escapar, unas comillas lo partirían."""
    ejecutados = []
    monkeypatch.setattr(navegador_cdp, "_evaluar",
                        lambda js, p=None: (ejecutados.append(js) or
                                            json.dumps({"ok": True, "accion": "pulsar",
                                                        "etiqueta": "x"}), ""))
    monkeypatch.setattr(navegador_cdp.time, "sleep", lambda _s: None)

    navegador_cdp.accionar('botón "Aceptar" y \'cerrar\'')

    # Escapado como cadena JSON: el JavaScript sigue siendo válido.
    assert json.dumps('botón "Aceptar" y \'cerrar\'') in ejecutados[0]
