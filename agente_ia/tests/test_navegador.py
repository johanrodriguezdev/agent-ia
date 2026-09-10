"""
tests/test_navegador.py
Pruebas de `os_integration/navegador.py` — REQ-038, ver la página y no solo la ventana.

La suite protege sobre todo dos cosas que ya salieron mal una vez:

1. **Que no se dé un veredicto al primer intento.** Chromium construye el árbol del
   contenido web cuando detecta que alguien lo lee, unos segundos después de abrir la
   página. La primera versión preguntaba una vez, veía cero y concluía "el navegador no
   publica la página" — y de ahí salió un diseño entero equivocado, que le pedía al usuario
   cerrar el navegador sin necesidad.
2. **Que el clic caiga donde se pidió.** Pidiendo «Historia» en Wikipedia, la coincidencia
   por "aparece dentro" elegía «Ver historial». Un clic en el sitio equivocado dentro de la
   sesión del usuario no es un detalle de precisión.

Ningún test abre un navegador ni depende de las ventanas que haya: todo va simulado.
"""

import pytest

from os_integration import navegador
from os_integration.ui_tree import Elemento


def _elemento(nombre, tipo="HyperlinkControl", x=10, y=10):
    return Elemento(nombre=nombre, tipo=tipo, x=x, y=y, ventana="Prueba")


# --------------------------------------------------------------------------- direcciones

def test_normalizar_url_agrega_esquema():
    assert navegador._normalizar_url("wikipedia.org") == "https://wikipedia.org"


def test_normalizar_url_respeta_el_esquema_que_venga():
    assert navegador._normalizar_url("http://local.test") == "http://local.test"


def test_normalizar_url_vacia_devuelve_vacio():
    assert navegador._normalizar_url("   ") == ""


# ------------------------------------------------------------------- elegir el elemento

def test_elegir_prefiere_el_nombre_exacto():
    elementos = [_elemento("Buscar cosas"), _elemento("Buscar")]
    elegido, _ = navegador._elegir("Buscar", elementos)
    assert elegido.nombre == "Buscar"


def test_elegir_no_parte_palabras():
    """«Historia» no puede terminar pulsando «Ver historial»: es otro enlace."""
    elementos = [_elemento("Ver historial"), _elemento("Historia de Python")]
    elegido, _ = navegador._elegir("Historia", elementos)
    assert elegido.nombre == "Historia de Python"


def test_elegir_cae_a_contiene_cuando_no_hay_palabra_entera():
    elementos = [_elemento("Ver historial")]
    elegido, _ = navegador._elegir("Historia", elementos)
    assert elegido.nombre == "Ver historial"


def test_elegir_entre_varios_gana_el_mas_corto():
    elementos = [_elemento("Cerrar sesión en todos los dispositivos"), _elemento("Cerrar sesión")]
    elegido, _ = navegador._elegir("Cerrar sesión", elementos)
    assert elegido.nombre == "Cerrar sesión"


def test_elegir_sin_coincidencia_devuelve_los_candidatos():
    elementos = [_elemento("Aceptar"), _elemento("Cancelar")]
    elegido, candidatos = navegador._elegir("Suscribirse", elementos)
    assert elegido is None
    assert len(candidatos) == 2


def test_elegir_sin_objetivo_no_elige_nada():
    elegido, _ = navegador._elegir("   ", [_elemento("Aceptar")])
    assert elegido is None


# ------------------------------------------------------------------ ¿se ve la página?

def test_ve_la_pagina_usa_el_umbral(monkeypatch):
    """1 nodo es un documento interno vacio de Chromium; 3 es example.com, una pagina real."""
    monkeypatch.setattr(navegador, "documento_de", lambda hwnd: (object(), 1))
    assert navegador.ve_la_pagina(1) is False
    monkeypatch.setattr(navegador, "documento_de", lambda hwnd: (object(), 3))
    assert navegador.ve_la_pagina(1) is True


def test_documento_de_se_queda_con_el_documento_mas_grande(monkeypatch):
    """Una ventana de Chrome tiene documentos vacíos además del de la página."""
    vacio, lleno = object(), object()
    monkeypatch.setattr(navegador, "disponible", lambda: True)
    monkeypatch.setattr(navegador, "_documentos_de", lambda ventana: [vacio, lleno])
    monkeypatch.setattr(navegador, "_nodos_bajo", lambda d: 1 if d is vacio else 4749)

    modulo = pytest.importorskip("uiautomation")
    monkeypatch.setattr(modulo, "ControlFromHandle", lambda hwnd: object())

    documento, tamano = navegador.documento_de(1)
    assert documento is lleno
    assert tamano == 4749


def test_esperar_pagina_reintenta_y_no_se_rinde_al_primer_intento(monkeypatch):
    """El fallo que costó el primer diseño: concluir "no se ve" en la primera consulta."""
    intentos = {"n": 0}

    def _ve(_hwnd):
        intentos["n"] += 1
        return intentos["n"] >= 3

    monkeypatch.setattr(navegador, "ve_la_pagina", _ve)
    monkeypatch.setattr(navegador, "_despertar_accesibilidad", lambda hwnd: None)
    monkeypatch.setattr(navegador, "_tocar_arbol", lambda hwnd: None)
    monkeypatch.setattr(navegador.time, "sleep", lambda _s: None)

    assert navegador.esperar_pagina(1, segundos=10) is True
    assert intentos["n"] == 3


def test_esperar_pagina_se_rinde_con_un_limite(monkeypatch):
    monkeypatch.setattr(navegador, "ve_la_pagina", lambda _h: False)
    monkeypatch.setattr(navegador, "_despertar_accesibilidad", lambda hwnd: None)
    monkeypatch.setattr(navegador, "_tocar_arbol", lambda hwnd: None)
    monkeypatch.setattr(navegador.time, "sleep", lambda _s: None)

    assert navegador.esperar_pagina(1, segundos=0) is False


# ------------------------------------------------------------------------------ abrir

def test_abrir_sin_direccion_pide_la_direccion():
    assert "dirección" in navegador.abrir("")


def test_abrir_sin_navegador_instalado_lo_dice(monkeypatch):
    monkeypatch.setattr(navegador, "ruta_del_navegador", lambda nombre=None: None)
    assert "no encontré" in navegador.abrir("wikipedia.org").lower()


def _preparar_apertura(monkeypatch, abiertas, listo=True, elementos=None):
    lanzado = {}
    monkeypatch.setattr(navegador, "ruta_del_navegador",
                        lambda nombre=None: ("Google Chrome", "C:/chrome.exe"))
    monkeypatch.setattr(navegador, "ventanas_de_navegador", lambda: abiertas)
    monkeypatch.setattr(navegador.subprocess, "Popen",
                        lambda args, **kw: lanzado.update(args=args))
    monkeypatch.setattr(navegador, "_esperar_ventana",
                        lambda antes, segundos=15.0: (7, "Wikipedia", "Google Chrome"))
    monkeypatch.setattr(navegador, "esperar_pagina", lambda hwnd, **kw: listo)
    monkeypatch.setattr(navegador, "elementos_de_pagina",
                        lambda hwnd, **kw: elementos if elementos is not None else [])
    return lanzado


def test_abrir_sin_ventanas_arranca_el_navegador_con_accesibilidad(monkeypatch):
    lanzado = _preparar_apertura(monkeypatch, abiertas=[], elementos=[_elemento("Portada")])
    respuesta = navegador.abrir("wikipedia.org")

    assert navegador.FLAG_ACCESIBILIDAD in lanzado["args"]
    assert "--new-window" in lanzado["args"]
    assert "1 cosas" in respuesta


def test_abrir_con_el_navegador_ya_abierto_no_le_pone_el_flag(monkeypatch):
    """Sobre un proceso vivo el flag se ignora, y pedir ventana nueva le mueve el escritorio."""
    abiertas = [(3, "Algo - Google Chrome", "Google Chrome")]
    lanzado = _preparar_apertura(monkeypatch, abiertas, elementos=[_elemento("Portada")])
    navegador.abrir("wikipedia.org")

    assert navegador.FLAG_ACCESIBILIDAD not in lanzado["args"]
    assert "--new-window" not in lanzado["args"]


def test_abrir_avisa_cuando_la_pagina_no_llega_a_leerse(monkeypatch):
    _preparar_apertura(monkeypatch, abiertas=[], listo=False)
    respuesta = navegador.abrir("wikipedia.org")

    assert "no consigo leer" in respuesta.lower()
    # No se le pide al usuario que cierre nada: eso era el diseño viejo, y era innecesario.
    assert "cerrá" not in respuesta.lower()
    assert "captura" in respuesta.lower()


# --------------------------------------------------------------------------- accionar

def test_accionar_sin_objetivo_pide_el_nombre():
    assert "nombre" in navegador.accionar("")


def test_accionar_sin_pagina_legible_lo_explica(monkeypatch):
    monkeypatch.setattr(navegador, "ventana_con_pagina", lambda: None)
    respuesta = navegador.accionar("Aceptar")
    assert "no puedo leer" in respuesta.lower()


def _preparar_accion(monkeypatch, elementos):
    clics, escrito = [], []
    monkeypatch.setattr(navegador, "ventana_con_pagina",
                        lambda: (7, "Wikipedia", "Google Chrome"))
    monkeypatch.setattr(navegador, "_al_frente", lambda hwnd: True)
    monkeypatch.setattr(navegador, "_sigue_ahi", lambda e: True)
    monkeypatch.setattr(navegador, "elementos_de_pagina", lambda hwnd, **kw: elementos)
    monkeypatch.setattr(navegador.time, "sleep", lambda _s: None)

    import automation.pc_controller as pc

    monkeypatch.setattr(pc, "click_position", lambda x, y: clics.append((x, y)))
    monkeypatch.setattr(pc, "type_text", lambda t: escrito.append(t))
    return clics, escrito


def test_accionar_pulsa_en_la_posicion_del_elemento(monkeypatch):
    elementos = [_elemento("Iniciar sesión", x=880, y=120)]
    clics, escrito = _preparar_accion(monkeypatch, elementos)

    respuesta = navegador.accionar("Iniciar sesión")

    assert clics == [(880, 120)]
    assert escrito == []
    assert "Iniciar sesión" in respuesta


def test_accionar_escribe_cuando_le_pasan_texto(monkeypatch):
    elementos = [_elemento("Usuario", tipo="EditControl", x=400, y=300)]
    clics, escrito = _preparar_accion(monkeypatch, elementos)

    navegador.accionar("Usuario", "johan")

    assert clics == [(400, 300)]
    assert escrito == ["johan"]


def test_accionar_que_no_encuentra_ofrece_lo_que_si_hay(monkeypatch):
    elementos = [_elemento("Aceptar"), _elemento("Cancelar")]
    clics, _ = _preparar_accion(monkeypatch, elementos)

    respuesta = navegador.accionar("Suscribirse")

    assert clics == []               # no se pulsa nada a lo loco
    assert "Aceptar" in respuesta and "Cancelar" in respuesta


# ------------------------------------------------------------------------- el resumen

def test_accionar_no_pulsa_si_la_ventana_no_llega_al_frente(monkeypatch):
    """El clic va por coordenadas: sin foco aterrizaria en la app que si lo tenga."""
    clics, _ = _preparar_accion(monkeypatch, [_elemento("Aceptar")])
    monkeypatch.setattr(navegador, "_al_frente", lambda hwnd: False)

    respuesta = navegador.accionar("Aceptar")

    assert clics == []
    assert "al frente" in respuesta


def test_accionar_no_pulsa_si_el_elemento_se_movio(monkeypatch):
    """Entre leer la pagina y pulsar, un banner puede empujar el contenido."""
    clics, _ = _preparar_accion(monkeypatch, [_elemento("Aceptar")])
    monkeypatch.setattr(navegador, "_sigue_ahi", lambda e: False)

    respuesta = navegador.accionar("Aceptar")

    assert clics == []
    assert "se movió" in respuesta


# ------------------------------------------------------------------------- el resumen

def test_resumen_sin_navegador_abierto(monkeypatch):
    monkeypatch.setattr(navegador, "ventanas_de_navegador", lambda: [])
    assert "ninguna ventana" in navegador.resumen_de_pagina()


def test_resumen_lista_lo_accionable(monkeypatch):
    monkeypatch.setattr(navegador, "ventanas_de_navegador",
                        lambda: [(7, "Wikipedia", "Google Chrome")])
    monkeypatch.setattr(navegador, "ventana_con_pagina",
                        lambda: (7, "Wikipedia", "Google Chrome"))
    monkeypatch.setattr(navegador, "elementos_de_pagina",
                        lambda hwnd, **kw: [_elemento("Portada"),
                                            _elemento("Entrar", tipo="ButtonControl")])
    resumen = navegador.resumen_de_pagina()

    assert "Wikipedia" in resumen
    assert "Hyperlink «Portada»" in resumen
    assert "Button «Entrar»" in resumen


def test_resumen_avisa_del_tope(monkeypatch):
    monkeypatch.setattr(navegador, "ventanas_de_navegador",
                        lambda: [(7, "Wikipedia", "Google Chrome")])
    monkeypatch.setattr(navegador, "ventana_con_pagina",
                        lambda: (7, "Wikipedia", "Google Chrome"))
    monkeypatch.setattr(navegador, "elementos_de_pagina",
                        lambda hwnd, **kw: [_elemento(f"Enlace {i}") for i in range(10)])
    resumen = navegador.resumen_de_pagina(maximo=4)

    assert "y 6 elementos más" in resumen


# ---------------------------------------------------------------- herramientas y riesgo

def test_resumen_avisa_cuando_no_puede_leer_ninguna_pestana(monkeypatch):
    monkeypatch.setattr(navegador, "ventanas_de_navegador",
                        lambda: [(7, "Algo", "Google Chrome")])
    monkeypatch.setattr(navegador, "ventana_con_pagina", lambda: None)
    assert "no puedo leer" in navegador.resumen_de_pagina().lower()


# ------------------------------------------------- sobre QUE ventana se actua

def test_se_prefiere_la_ventana_que_abrio_el_agente(monkeypatch):
    """Un tramite son varios pasos y todos tienen que caer en la MISMA pagina.

    Sin esto, "la primera ventana legible" podia ser el WhatsApp abierto en otra ventana,
    y el clic aterrizaba ahi.
    """
    abiertas = [(1, "WhatsApp", "Google Chrome"), (2, "Tramite", "Google Chrome")]
    monkeypatch.setattr(navegador, "ventanas_de_navegador", lambda: abiertas)
    monkeypatch.setattr(navegador, "ve_la_pagina", lambda hwnd: True)
    monkeypatch.setattr(navegador, "_ultima_ventana", 2)

    assert navegador.ventana_con_pagina()[0] == 2


def test_si_la_ventana_del_agente_ya_no_esta_se_usa_otra(monkeypatch):
    abiertas = [(1, "WhatsApp", "Google Chrome")]
    monkeypatch.setattr(navegador, "ventanas_de_navegador", lambda: abiertas)
    monkeypatch.setattr(navegador, "ve_la_pagina", lambda hwnd: True)
    monkeypatch.setattr(navegador, "_ultima_ventana", 99)

    assert navegador.ventana_con_pagina()[0] == 1


def test_sin_ninguna_ventana_legible_no_se_inventa_una(monkeypatch):
    monkeypatch.setattr(navegador, "ventanas_de_navegador",
                        lambda: [(1, "WhatsApp", "Google Chrome")])
    monkeypatch.setattr(navegador, "ve_la_pagina", lambda hwnd: False)

    assert navegador.ventana_con_pagina() is None


def test_abrir_recuerda_la_ventana_para_los_pasos_siguientes(monkeypatch):
    _preparar_apertura(monkeypatch, abiertas=[], elementos=[_elemento("Portada")])
    navegador.abrir("wikipedia.org")
    assert navegador._ultima_ventana == 7


def test_las_tres_herramientas_estan_registradas():
    from agents.tool_registry import get_tool

    for nombre in ("browser_open", "browser_page", "browser_act"):
        assert get_tool(nombre) is not None, nombre


def test_actuar_en_una_pagina_es_amarillo_y_solo_de_escritorio():
    """Un clic dentro de la sesión del usuario puede comprar, borrar o enviar."""
    from core.security_manager import ChannelType, RiskLevel, security_manager

    assert security_manager.classify_action("browser_act") == RiskLevel.YELLOW
    assert security_manager.is_action_allowed("browser_act", ChannelType.DESKTOP)
    assert not security_manager.is_action_allowed("browser_act", ChannelType.TELEGRAM)
    assert not security_manager.is_action_allowed("browser_act", ChannelType.VOICE)


def test_mirar_la_pagina_es_verde():
    from core.security_manager import RiskLevel, security_manager

    assert security_manager.classify_action("browser_open") == RiskLevel.GREEN
    assert security_manager.classify_action("browser_page") == RiskLevel.GREEN


def test_la_confirmacion_muestra_sobre_que_se_va_a_pulsar_y_que_se_escribe():
    """Autorizar «hacer clic en la página» sin ver el objetivo sería autorizar a ciegas."""
    from core.security_manager import format_details

    detalle = format_details("browser_act", {"objetivo": "Eliminar cuenta",
                                             "texto": "confirmar"})
    assert "Eliminar cuenta" in detalle
    assert "confirmar" in detalle
