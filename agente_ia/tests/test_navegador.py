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
    monkeypatch.setattr(navegador, "_asegurar_visible", lambda hwnd, e: e)
    monkeypatch.setattr(navegador, "_dentro_de_la_ventana", lambda hwnd, e: True)
    monkeypatch.setattr(navegador, "_firma_de_pagina", lambda hwnd: ("Antes", 100))
    monkeypatch.setattr(navegador, "_esperar_a_que_cambie",
                        lambda hwnd, antes, **kw: ("Antes", 100))
    monkeypatch.setattr(navegador, "_elemento_por_nombre", lambda hwnd, n: None)
    # Por defecto se prueba el camino FISICO: sin control, no hay patrón que invocar.
    monkeypatch.setattr(navegador, "_control_por_nombre", lambda hwnd, n: None)
    monkeypatch.setattr(navegador, "_enfocar", lambda c: False)
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
    assert "quedó igual" in respuesta      # la firma no cambio en este montaje


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

def test_se_pulsa_por_el_patron_y_no_por_coordenadas_cuando_se_puede(monkeypatch):
    """Invocar el elemento no depende de qué ventana esté delante ni de que nada lo tape.

    Es lo que arregla el caso de Wikipedia: al traer el enlace a la vista quedaba debajo de
    la cabecera pegada de arriba, y el clic por coordenadas habría pulsado la cabecera.
    """
    clics, _ = _preparar_accion(monkeypatch, [_elemento("Historia de Python")])
    invocado = _Patron()
    monkeypatch.setattr(navegador, "_control_por_nombre", lambda hwnd, n: object())
    monkeypatch.setattr(navegador, "_patron",
                        lambda c, n: invocado if n == "InvokePattern" else None)

    navegador.accionar("Historia de Python")

    assert invocado.llamadas == ["Invoke"]
    assert clics == []                       # no se tocó el ratón


def test_si_el_patron_falla_se_pulsa_a_mano(monkeypatch):
    class _Roto:
        def Invoke(self):
            raise RuntimeError("el elemento no acepta Invoke")

    clics, _ = _preparar_accion(monkeypatch, [_elemento("Aceptar", x=50, y=60)])
    monkeypatch.setattr(navegador, "_control_por_nombre", lambda hwnd, n: object())
    monkeypatch.setattr(navegador, "_patron",
                        lambda c, n: _Roto() if n == "InvokePattern" else None)

    navegador.accionar("Aceptar")

    assert clics == [(50, 60)]


def test_escribir_enfoca_el_campo_sin_hacer_clic(monkeypatch):
    clics, escrito = _preparar_accion(monkeypatch, [_elemento("Usuario", tipo="EditControl")])
    monkeypatch.setattr(navegador, "_control_por_nombre", lambda hwnd, n: object())
    monkeypatch.setattr(navegador, "_enfocar", lambda c: True)

    navegador.accionar("Usuario", "johan")

    assert escrito == ["johan"]
    assert clics == []


def test_lo_que_el_tope_recorta_igual_se_puede_pulsar(monkeypatch):
    """Wikipedia tiene 507 enlaces: la lista va acotada, pero pulsar no puede estarlo.

    Paso de verdad — «Historia de Python» estaba en la pagina y el agente respondia "no lo
    encontre" porque no habia entrado en la muestra.
    """
    escondido = _elemento("Historia de Python", x=300, y=500)
    clics, _ = _preparar_accion(monkeypatch, [_elemento("Portada")])
    monkeypatch.setattr(navegador, "_elemento_por_nombre",
                        lambda hwnd, n: escondido if n == "Historia de Python" else None)

    respuesta = navegador.accionar("Historia de Python")

    assert clics == [(300, 500)]
    assert "Historia de Python" in respuesta


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

    for nombre in ("browser_open", "browser_page", "browser_act", "browser_text",
                   "browser_tabs", "browser_tab_switch", "browser_tab_close"):
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

    for verde in ("browser_open", "browser_page", "browser_text", "browser_tabs",
                  "browser_tab_switch"):
        assert security_manager.classify_action(verde) == RiskLevel.GREEN, verde


def test_cerrar_una_pestana_pide_permiso_y_no_llega_de_lejos():
    """Lo que se pierde al cerrar no vuelve: un formulario a medio llenar, un borrador."""
    from core.security_manager import ChannelType, RiskLevel, security_manager

    assert security_manager.classify_action("browser_tab_close") == RiskLevel.YELLOW
    assert not security_manager.is_action_allowed("browser_tab_close", ChannelType.TELEGRAM)


def test_cerrar_una_pestana_se_lee_en_voz_alta():
    from core.acciones_legibles import _DESCRIPCIONES

    assert "pestaña" in _DESCRIPCIONES["browser_tab_close"]


def test_la_confirmacion_muestra_sobre_que_se_va_a_pulsar_y_que_se_escribe():
    """Autorizar «hacer clic en la página» sin ver el objetivo sería autorizar a ciegas."""
    from core.security_manager import format_details

    detalle = format_details("browser_act", {"objetivo": "Eliminar cuenta",
                                             "texto": "confirmar"})
    assert "Eliminar cuenta" in detalle
    assert "confirmar" in detalle


# =========================================================================== pestañas
#
# Las pestañas se operan con patrones de UI Automation, no con el ratón: seleccionar una
# pestaña con `SelectionItemPattern` no roba el foco ni exige acertarle a un objetivo de
# veinte píxeles de alto. Estas pruebas fijan eso.

class _Patron:
    """Un patrón de UI Automation simulado: registra si lo llamaron."""

    def __init__(self, seleccionada=False):
        self.CurrentIsSelected = seleccionada
        self.llamadas = []

    def Select(self):
        self.llamadas.append("Select")

    def Invoke(self):
        self.llamadas.append("Invoke")

    def ScrollIntoView(self):
        self.llamadas.append("ScrollIntoView")


class _Pestana:
    def __init__(self, nombre, seleccionada=False, con_boton=True):
        self.Name = nombre
        self.ControlTypeName = "TabItemControl"
        self.seleccion = _Patron(seleccionada)
        self.cerrar = _Patron()
        self._con_boton = con_boton

    def GetChildren(self):
        if not self._con_boton:
            return []
        boton = _Pestana("Cerrar")
        boton.ControlTypeName = "ButtonControl"
        boton.invocar = self.cerrar
        return [boton]


def _montar_pestanas(monkeypatch, pestanas):
    monkeypatch.setattr(navegador, "ventanas_de_navegador",
                        lambda: [(7, "Ventana", "Google Chrome")])
    monkeypatch.setattr(navegador, "_pestanas_de", lambda hwnd: pestanas)

    def _patron(control, nombre):
        if nombre == "SelectionItemPattern":
            return getattr(control, "seleccion", None)
        if nombre == "InvokePattern":
            return getattr(control, "invocar", None)
        return None

    monkeypatch.setattr(navegador, "_patron", _patron)
    monkeypatch.setattr(navegador, "esperar_pagina", lambda hwnd, **kw: True)


def test_listar_pestanas_marca_la_que_se_esta_viendo(monkeypatch):
    _montar_pestanas(monkeypatch, [_Pestana("Correo"), _Pestana("Factura", seleccionada=True)])
    salida = navegador.listar_pestanas()

    assert "«Correo»" in salida
    assert "«Factura»" in salida
    assert salida.splitlines()[2].endswith("la que estás viendo")


def test_cambiar_de_pestana_no_usa_el_raton(monkeypatch):
    factura = _Pestana("Factura")
    _montar_pestanas(monkeypatch, [_Pestana("Correo"), factura])

    respuesta = navegador.cambiar_de_pestana("Factura")

    assert factura.seleccion.llamadas == ["Select"]
    assert "Factura" in respuesta


def test_cambiar_de_pestana_no_parte_palabras(monkeypatch):
    """Mismo criterio que los enlaces: «Factura» no puede llevar a «Facturación anual»."""
    exacta = _Pestana("Factura")
    _montar_pestanas(monkeypatch, [_Pestana("Facturación anual"), exacta])

    navegador.cambiar_de_pestana("Factura")

    assert exacta.seleccion.llamadas == ["Select"]


def test_cambiar_a_una_pestana_que_no_existe_ofrece_las_que_hay(monkeypatch):
    _montar_pestanas(monkeypatch, [_Pestana("Correo"), _Pestana("Factura")])
    respuesta = navegador.cambiar_de_pestana("Banco")

    assert "no encontré" in respuesta.lower()
    assert "«Correo»" in respuesta and "«Factura»" in respuesta


def test_cerrar_pestana_invoca_su_boton_cerrar(monkeypatch):
    factura = _Pestana("Factura")
    _montar_pestanas(monkeypatch, [_Pestana("Correo"), factura])

    respuesta = navegador.cerrar_pestana("Factura")

    assert factura.cerrar.llamadas == ["Invoke"]
    assert "Cerré" in respuesta


def test_cerrar_pestana_sin_boton_no_pulsa_a_ciegas(monkeypatch):
    """Ctrl+W cerraría la pestaña ACTIVA, que puede no ser la que se pidió."""
    sin_boton = _Pestana("Factura", con_boton=False)
    _montar_pestanas(monkeypatch, [sin_boton])

    respuesta = navegador.cerrar_pestana("Factura")

    assert "no la cierro" in respuesta.lower()


def test_cerrar_pestana_sin_nombre_no_cierra_nada():
    assert "necesito" in navegador.cerrar_pestana("").lower()


# ==================================================== desplazar hasta lo que se va a pulsar

def test_un_elemento_fuera_de_la_ventana_no_se_pulsa(monkeypatch):
    """Medido en Wikipedia: 474 de 507 enlaces están fuera de la vista, uno a y=31449."""
    lejano = _elemento("Referencias", y=31449)
    clics, _ = _preparar_accion(monkeypatch, [lejano])
    monkeypatch.setattr(navegador, "_asegurar_visible", lambda hwnd, e: e)
    monkeypatch.setattr(navegador, "_dentro_de_la_ventana", lambda hwnd, e: False)

    respuesta = navegador.accionar("Referencias")

    assert clics == []
    assert "no consigo traerlo a la vista" in respuesta


def test_se_pulsa_en_la_posicion_NUEVA_despues_de_desplazar(monkeypatch):
    lejano = _elemento("Referencias", y=31449)
    cerca = _elemento("Referencias", y=603)
    clics, _ = _preparar_accion(monkeypatch, [lejano])
    monkeypatch.setattr(navegador, "_asegurar_visible", lambda hwnd, e: cerca)

    navegador.accionar("Referencias")

    assert clics == [(cerca.x, 603)]


def test_asegurar_visible_no_desplaza_lo_que_ya_se_ve(monkeypatch):
    monkeypatch.setattr(navegador, "_dentro_de_la_ventana", lambda hwnd, e: True)
    visible = _elemento("Aceptar", y=300)

    assert navegador._asegurar_visible(7, visible) is visible


# ============================================== esperar a que la página termine de cambiar

def test_esperar_a_que_cambie_devuelve_la_pagina_nueva(monkeypatch):
    """Sin esto el agente lee la página VIEJA y decide el paso siguiente sobre ella."""
    firmas = [("Antes", 100), ("Después", 50), ("Después", 900), ("Después", 900)]
    monkeypatch.setattr(navegador, "_firma_de_pagina", lambda hwnd: firmas.pop(0))
    monkeypatch.setattr(navegador.time, "sleep", lambda _s: None)

    assert navegador._esperar_a_que_cambie(7, ("Antes", 100), segundos=30) == ("Después", 900)


def test_esperar_a_que_cambie_se_rinde_si_nada_cambia(monkeypatch):
    monkeypatch.setattr(navegador, "_firma_de_pagina", lambda hwnd: ("Antes", 100))
    monkeypatch.setattr(navegador.time, "sleep", lambda _s: None)

    assert navegador._esperar_a_que_cambie(7, ("Antes", 100), segundos=0) == ("Antes", 100)


def test_el_clic_cuenta_en_que_pagina_quedaste(monkeypatch):
    clics, _ = _preparar_accion(monkeypatch, [_elemento("Siguiente")])
    monkeypatch.setattr(navegador, "_esperar_a_que_cambie",
                        lambda hwnd, antes, **kw: ("Paso 2 de 3", 800))

    respuesta = navegador.accionar("Siguiente")

    assert clics
    assert "Paso 2 de 3" in respuesta


def test_escribir_no_espera_un_cambio_de_pagina(monkeypatch):
    """Escribir en un campo no cambia de pantalla: esperar sería regalar doce segundos."""
    clics, escrito = _preparar_accion(monkeypatch, [_elemento("Usuario", tipo="EditControl")])
    llamadas = []

    def _no_deberia(hwnd, antes, **kw):
        llamadas.append(1)
        return ("x", 1)

    monkeypatch.setattr(navegador, "_esperar_a_que_cambie", _no_deberia)

    navegador.accionar("Usuario", "johan")

    assert escrito == ["johan"]
    assert llamadas == []


# ========================================================== el texto de la página (y el PDF)

class _Rango:
    def __init__(self, texto):
        self._texto = texto

    def GetText(self, tope):
        return self._texto[:tope]


class _PatronTexto:
    def __init__(self, texto):
        self.DocumentRange = _Rango(texto)


def _montar_texto(monkeypatch, texto, patron=True):
    monkeypatch.setattr(navegador, "ventana_con_pagina",
                        lambda: (7, "Informe anual", "Google Chrome"))
    monkeypatch.setattr(navegador, "documento_de", lambda hwnd: (object(), 500))
    monkeypatch.setattr(navegador, "_patron",
                        lambda c, n: _PatronTexto(texto) if patron else None)


def test_texto_de_pagina_devuelve_el_contenido(monkeypatch):
    _montar_texto(monkeypatch, "Primera línea\n\n  \nSegunda línea")
    salida = navegador.texto_de_pagina()

    assert "Informe anual" in salida
    assert "Primera línea" in salida and "Segunda línea" in salida


def test_texto_de_pagina_corta_lo_muy_largo(monkeypatch):
    _montar_texto(monkeypatch, "x" * 9000)
    salida = navegador.texto_de_pagina(maximo_caracteres=500)

    assert "cortado" in salida
    assert len(salida) < 1200


def test_sin_texto_se_ofrece_la_captura(monkeypatch):
    """Un lienzo o un vídeo no tienen texto que leer: ahí sí hace falta mirar."""
    _montar_texto(monkeypatch, "")
    monkeypatch.setattr(navegador, "elementos_de_pagina", lambda hwnd, **kw: [])
    salida = navegador.texto_de_pagina()

    assert "captura" in salida


def test_texto_sin_pagina_legible_lo_dice(monkeypatch):
    monkeypatch.setattr(navegador, "ventana_con_pagina", lambda: None)
    assert "no puedo leer" in navegador.texto_de_pagina().lower()


# ================================================================== Firefox, sin medir

def test_firefox_esta_reconocido_pero_no_probado():
    """Se deja abrirlo; que publique la página no se pudo medir (no está instalado acá)."""
    nombres = [n for n, _rutas in navegador.NAVEGADORES]
    assert "Mozilla Firefox" in nombres
    # Último de la lista: se prefieren los navegadores contra los que sí se midió.
    assert nombres.index("Mozilla Firefox") == len(nombres) - 1
