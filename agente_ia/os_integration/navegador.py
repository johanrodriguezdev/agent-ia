"""
os_integration/navegador.py
REQ-038 — Que el agente pueda VER la página, no solo la ventana del navegador.

`ui_tree.py` le pregunta al sistema dónde está cada control, y con eso el agente maneja
Excel o el Bloc de notas con precisión exacta. Con el navegador se quedaba ciego: veía la
barra de herramientas de Chrome y nada del contenido. Para pulsar un enlace tenía que
estimar coordenadas sobre una captura, y con veinte píxeles de error esa es la diferencia
entre "Aceptar" y "Cancelar".

**Cómo se resolvió, y por qué el camino obvio estaba mal.**

La primera conclusión de este REQ fue que hacía falta arrancar Chrome con
`--force-renderer-accessibility` y que, como ese flag no se puede encender en caliente,
había que pedirle al usuario que cerrara el navegador. Medido en esta máquina, sobre la
misma página de Wikipedia, parecía sólido: 33-45 elementos sin el flag, 4.000 con él.

Era falso, y el error estaba en el medidor. Recorrer el árbol nodo por nodo desde Python
—`GetChildren()` recursivo, que es lo que hace `ui_tree`— tarda decenas de segundos en una
página real, así que el recorrido se quedaba sin presupuesto de tiempo dentro de la barra
de herramientas y nunca llegaba al contenido. Lo que se medía como "Chrome no publica la
página" era "mi recorrido no llegó".

Pidiéndoselo a UI Automation con `FindAll` —una sola llamada COM, resuelta dentro de
Windows en vez de a golpe de round-trips— el mismo Chrome del usuario, **sin flag ninguno y
sin reiniciar nada**, devuelve el documento entero en 0,1-0,3 segundos. Chromium construye
el árbol del contenido web cuando detecta que alguien lo está leyendo; tarda unos segundos
en hacerlo (medido: ~9 s desde que se abre la página), y por eso acá se espera y se
reintenta en lugar de dar un veredicto al primer intento.

Consecuencia práctica: **el agente no necesita cerrarle el navegador a nadie**. Sigue sin
cerrar nada por su cuenta —esa parte de la política de Johan no cambia— pero ya no hay
ningún motivo para pedírselo.
"""

import ctypes
import ctypes.wintypes as wt
import logging
import os
import subprocess
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Navegadores que se reconocen, por el texto que ponen en el título de su ventana, y dónde
#: buscarlos. El orden importa: se prefiere el primero que esté instalado.
NAVEGADORES = (
    ("Google Chrome", (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )),
    ("Microsoft Edge", (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )),
)

#: Enciende la accesibilidad del contenido web desde el arranque. NO es lo que hace posible
#: leer la página —eso fue el error de la primera versión de este módulo—, pero cuando es el
#: agente quien abre el navegador ahorra la espera a que Chromium se decida. Solo aplica al
#: proceso que se lanza: contra un navegador ya abierto se ignora.
FLAG_ACCESIBILIDAD = "--force-renderer-accessibility"

#: `TreeScope_Descendants` de UI Automation. Es una constante de la API de Windows, no un
#: número elegido acá.
TREE_DESCENDANTS = 4

#: Cuántos nodos tienen que colgar del documento para dar por publicada la página.
#:
#: Se cuenta el documento y no la ventana entera, porque la ventana pasa de cualquier
#: umbral solo con la barra de Chrome de un usuario real —marcadores, extensiones,
#: pestañas—.
#:
#: El número sale de medir los dos extremos, no de estimarlo:
#:
#:     documento interno vacío de Chromium    0 o 1 nodos, y sin nombre
#:     example.com (una página mínima real)   3 nodos, llamada «Example Domain»
#:     una página normal                      92 y 362 en el Chrome de esta máquina
#:     Wikipedia                              4.749
#:
#: El primer umbral fue 10 y dejaba fuera a `example.com`: una página corta de verdad
#: existe, y decir "no la veo" es peor que quedarse corto de elementos.
MINIMO_NODOS_DE_PAGINA = 3

#: Cuánto se espera a que Chromium termine de construir el árbol. Medido: ~9 s desde que se
#: abre la página. Se deja margen para una página lenta o un equipo cargado.
SEGUNDOS_PARA_QUE_APAREZCA = 25

#: Tope de elementos que se leen de una página. Una de Wikipedia tiene 350 enlaces; pasarle
#: los 350 al modelo es gastar contexto sin que decida mejor.
MAX_ELEMENTOS_DE_PAGINA = 200

#: Tope por tipo. Cada elemento cuesta un par de llamadas a Windows, así que leerlos todos
#: para después recortar la lista es pagar el precio dos veces: medido, 350 enlaces son 7
#: segundos. Con este tope una página se lee en menos de tres.
MAX_POR_TIPO = 60

#: Lo que se le muestra al modelo de una página. Los nodos de texto sueltos se dejan fuera:
#: una página de Wikipedia tiene 3.338 y ninguno se puede pulsar. Lo que sirve para actuar
#: son los enlaces, los campos y los botones.
#:
#: El orden importa porque hay topes: primero lo que no se puede perder —los campos de un
#: formulario, los botones—, y los enlaces al final, que es lo que sobra en una página larga.
TIPOS_ACCIONABLES = (
    "EditControl", "ButtonControl", "ComboBoxControl", "CheckBoxControl",
    "RadioButtonControl", "TabItemControl", "MenuItemControl", "ListItemControl",
    "HyperlinkControl",
)

#: Mensajes de Windows para avisarle a Chromium que hay un cliente de accesibilidad. Son
#: constantes de la API del sistema (`winuser.h`), no números elegidos acá.
_WM_GETOBJECT = 0x003D
_OBJID_CLIENT = 0xFFFFFFFC
_SMTO_ABORTIFHUNG = 0x0002

_u32 = ctypes.windll.user32 if os.name == "nt" else None


def _ventanas_visibles() -> List[Tuple[int, str]]:
    """Return `(hwnd, título)` de todas las ventanas visibles con título."""
    if _u32 is None:
        return []
    encontradas: List[Tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hwnd, _):
        if not _u32.IsWindowVisible(hwnd):
            return True
        largo = _u32.GetWindowTextLengthW(hwnd)
        if largo:
            buf = ctypes.create_unicode_buffer(largo + 1)
            _u32.GetWindowTextW(hwnd, buf, largo + 1)
            encontradas.append((hwnd, buf.value))
        return True

    _u32.EnumWindows(_cb, 0)
    return encontradas


def ventanas_de_navegador() -> List[Tuple[int, str, str]]:
    """Return `(hwnd, título, navegador)` de las ventanas de navegador abiertas."""
    salida = []
    for hwnd, titulo in _ventanas_visibles():
        for nombre, _rutas in NAVEGADORES:
            if nombre in titulo:
                salida.append((hwnd, titulo, nombre))
                break
    return salida


def ruta_del_navegador(nombre: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """Return `(nombre, ruta)` del primer navegador instalado, o None."""
    for candidato, rutas in NAVEGADORES:
        if nombre and candidato != nombre:
            continue
        for ruta in rutas:
            if os.path.exists(ruta):
                return candidato, ruta
    return None


def disponible() -> bool:
    """Return True si se puede consultar el árbol de accesibilidad en este equipo."""
    from os_integration.ui_tree import disponible as _disponible_ui

    return _disponible_ui()


def _cliente_uia():
    """Return el cliente `IUIAutomation`, que es lo que hace viable leer una página.

    Se reusa la instancia que `uiautomation` ya tiene creada en vez de crear otra: abrir un
    segundo cliente COM en el mismo proceso funciona, pero duplica el coste de cada
    consulta sin ganar nada.

    Es API privada de la librería (`_AutomationClient`). Si una versión futura la mueve,
    esto devuelve None y el módulo sigue funcionando por el camino lento — más despacio y
    con menos alcance, pero sin romperse.
    """
    try:
        from uiautomation.uiautomation import _AutomationClient

        return _AutomationClient.instance().IUIAutomation
    except Exception as e:
        logger.warning(f"UI Automation no expone el cliente nativo, se usa el camino lento: {e}")
        return None


def _documentos_de(control) -> List:
    """Return los nodos de documento de esa ventana: es donde cuelga el contenido web."""
    import uiautomation as auto

    cliente = _cliente_uia()
    if cliente is None:
        return _documentos_lento(control)
    try:
        condicion = cliente.CreatePropertyCondition(
            auto.PropertyId.ControlTypeProperty, auto.ControlType.DocumentControl,
        )
        encontrados = control.Element.FindAll(TREE_DESCENDANTS, condicion)
        return [auto.Control.CreateControlFromElement(encontrados.GetElement(i))
                for i in range(encontrados.Length)]
    except Exception as e:
        logger.debug(f"FindAll de documentos falló, se prueba el camino lento: {e}")
        return _documentos_lento(control)


def _documentos_lento(control, profundidad: int = 0) -> List:
    """Camino de respaldo: recorre el árbol a mano buscando documentos.

    Solo se usa si `FindAll` no está disponible. Es el método que hizo fracasar la primera
    versión de este módulo, así que va acotado en profundidad y devuelve lo que alcance.
    """
    if profundidad > 12:
        return []
    salida = []
    try:
        hijos = control.GetChildren()
    except Exception:
        return salida
    for hijo in hijos:
        try:
            if hijo.ControlTypeName == "DocumentControl":
                salida.append(hijo)
                continue
        except Exception:
            continue
        salida.extend(_documentos_lento(hijo, profundidad + 1))
    return salida


def _nodos_bajo(control) -> int:
    """Return cuántos nodos cuelgan de un control."""
    cliente = _cliente_uia()
    if cliente is None:
        try:
            return len(control.GetChildren())
        except Exception as e:
            logger.debug(f"no se pudo contar el contenido del documento: {e}")
            return 0
    try:
        return control.Element.FindAll(TREE_DESCENDANTS, cliente.CreateTrueCondition()).Length
    except Exception as e:
        logger.debug(f"no se pudo contar el contenido del documento: {e}")
        return 0


def documento_de(hwnd: int) -> Tuple[Optional[object], int]:
    """Return `(documento, cuántos nodos tiene)` de la página de esa ventana.

    Una ventana de navegador tiene varios nodos de documento —el de la página, y otros
    vacíos que Chromium usa por dentro—. Se queda con el que más contenido tiene: el
    primero que aparece en el árbol suele ser uno de los vacíos, y quedarse con ese fue lo
    que hacía que la detección dijera "no veo nada" con la página delante.
    """
    if not disponible():
        return None, 0
    import uiautomation as auto

    try:
        ventana = auto.ControlFromHandle(hwnd)
    except Exception as e:
        logger.warning(f"no se pudo abrir la ventana {hwnd} para leerla: {e}")
        return None, 0

    mejor, mejor_tamano = None, 0
    for documento in _documentos_de(ventana):
        tamano = _nodos_bajo(documento)
        if tamano > mejor_tamano:
            mejor, mejor_tamano = documento, tamano
    return mejor, mejor_tamano


def tamano_de_pagina(hwnd: int) -> int:
    """Return cuántos nodos publica la página de esa ventana. 0 = no se ve nada."""
    return documento_de(hwnd)[1]


def ve_la_pagina(hwnd: int) -> bool:
    """Return True si esa ventana está publicando el contenido de su página."""
    return tamano_de_pagina(hwnd) >= MINIMO_NODOS_DE_PAGINA


def _despertar_accesibilidad(hwnd: int) -> None:
    """Le avisa a Chromium que hay alguien leyendo, que es cuando publica la página.

    Chromium no construye el árbol del contenido web mientras nadie lo pida: espera un
    `WM_GETOBJECT` sobre la ventana donde dibuja la página. Es exactamente lo que hace un
    lector de pantalla al arrancar, y sin esto la página aparece unas veces sí y otras no
    —medido: en varias pruebas seguidas, con el mismo código, unas veces 4.749 nodos y
    otras cero—.

    Se manda con tiempo límite: si el navegador está ocupado, se sigue sin bloquear al
    agente esperando una respuesta.
    """
    if _u32 is None:
        return

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def _cb(hijo, _):
        clase = ctypes.create_unicode_buffer(128)
        _u32.GetClassNameW(hijo, clase, 128)
        if "RenderWidgetHost" in clase.value or "Legacy" in clase.value:
            resultado = ctypes.c_ulong()
            _u32.SendMessageTimeoutW(hijo, _WM_GETOBJECT, 0, _OBJID_CLIENT,
                                     _SMTO_ABORTIFHUNG, 250, ctypes.byref(resultado))
        return True

    try:
        _u32.EnumChildWindows(hwnd, _cb, 0)
    except Exception as e:
        logger.debug(f"no se pudo avisar al navegador de que hay un lector: {e}")


def _tocar_arbol(hwnd: int) -> None:
    """Recorre dos niveles del árbol de la ventana. Es lo que termina de despertarlo.

    Suena raro que haga falta, y se descubrió por diferencia: el mismo código que esperaba
    25 segundos sin ver nada, veía la página a los 3 en cuanto el diagnóstico —que sí
    recorría— corría al lado. `FindAll` sobre la ventana se lo responde el proceso del
    navegador con lo que ya tiene; recorrer los hijos obliga a preguntarle de verdad al
    proceso que dibuja la página, y es ahí donde Chromium decide construir el árbol.

    Son dos niveles y nada más: la barra de herramientas y poco más, milisegundos.
    """
    if not disponible():
        return
    import uiautomation as auto

    try:
        for hijo in auto.ControlFromHandle(hwnd).GetChildren():
            hijo.GetChildren()
    except Exception as e:
        logger.debug(f"no se pudo recorrer el árbol de la ventana {hwnd}: {e}")


def esperar_pagina(hwnd: int, segundos: float = SEGUNDOS_PARA_QUE_APAREZCA) -> bool:
    """Espera a que la página sea legible. Return True si llegó a serlo.

    Hace falta esperar porque Chromium construye el árbol del contenido web cuando detecta
    que hay alguien leyéndolo, no al cargar la página: preguntar una sola vez y concluir
    "no se ve" es la equivocación que costó la primera versión de este módulo.
    """
    limite = time.monotonic() + max(0.0, segundos)
    while True:
        _despertar_accesibilidad(hwnd)
        _tocar_arbol(hwnd)
        if ve_la_pagina(hwnd):
            return True
        if time.monotonic() >= limite:
            return False
        time.sleep(1.0)


def _leer_control(control) -> Optional[Tuple[str, str, int, int]]:
    """Return `(nombre, tipo, x, y)` de un control, o None si no sirve para actuar."""
    nombre = (control.Name or "").strip()
    if not nombre:
        return None
    rect = control.BoundingRectangle
    # Sin área no se puede pulsar: ocupa sitio en la lista y el modelo podría intentar
    # hacerle clic igual.
    if not rect or rect.width() <= 0 or rect.height() <= 0:
        return None
    return nombre, control.ControlTypeName, rect.xcenter(), rect.ycenter()


def _agregar(elementos: List, vistos: set, ventana: str,
             nombre: str, tipo: str, x: int, y: int) -> None:
    """Suma un elemento a la lista si no estaba ya. La misma página repite nombres."""
    from os_integration.ui_tree import Elemento

    clave = (nombre, x, y)
    if clave in vistos:
        return
    vistos.add(clave)
    elementos.append(Elemento(nombre=nombre, tipo=tipo, x=x, y=y, ventana=ventana))


def elementos_de_pagina(hwnd: int, maximo: int = MAX_ELEMENTOS_DE_PAGINA) -> List:
    """Return lo accionable de la página: enlaces, campos y botones, con su posición.

    Se pide por tipo en vez de recorrer el árbol: son nueve consultas a Windows en lugar de
    miles de idas y vueltas, que es la diferencia entre 0,3 segundos y no terminar nunca.
    """
    from os_integration.ui_tree import Elemento

    documento, _tamano = documento_de(hwnd)
    if documento is None:
        return []

    import uiautomation as auto

    cliente = _cliente_uia()
    titulo = ""
    try:
        titulo = (auto.ControlFromHandle(hwnd).Name or "").strip()
    except Exception as e:
        logger.debug(f"no se pudo leer el título de la ventana {hwnd}: {e}")

    elementos: List[Elemento] = []
    vistos = set()

    if cliente is None:
        for control in _accionables_lento(documento):
            try:
                datos = _leer_control(control)
            except Exception as e:
                logger.debug(f"un elemento de la página no se pudo leer: {e}")
                continue
            if datos is not None:
                _agregar(elementos, vistos, titulo, *datos)
    else:
        # Una sola consulta para los nueve tipos, y con los nombres y las posiciones ya
        # incluidos. Las dos cosas son la diferencia entre una página que se lee en menos
        # de un segundo y una que tarda ocho: cada búsqueda recorre los 4.749 nodos de la
        # página por dentro de Windows, así que hacer nueve cuesta nueve veces; y pedir
        # cada nombre después es otro viaje por elemento.
        por_id = {}
        condiciones = []
        for nombre_tipo in TIPOS_ACCIONABLES:
            id_tipo = getattr(auto.ControlType, nombre_tipo, None)
            if id_tipo is None:
                continue
            por_id[id_tipo] = nombre_tipo
            condiciones.append(cliente.CreatePropertyCondition(
                auto.PropertyId.ControlTypeProperty, id_tipo,
            ))

        hallados = None
        if condiciones:
            try:
                condicion = condiciones[0]
                for otra in condiciones[1:]:
                    condicion = cliente.CreateOrCondition(condicion, otra)
                cache = cliente.CreateCacheRequest()
                cache.AddProperty(auto.PropertyId.NameProperty)
                cache.AddProperty(auto.PropertyId.BoundingRectangleProperty)
                cache.AddProperty(auto.PropertyId.ControlTypeProperty)
                hallados = documento.Element.FindAllBuildCache(
                    TREE_DESCENDANTS, condicion, cache,
                )
            except Exception as e:
                logger.debug(f"no se pudo pedir lo accionable de la página: {e}")

        por_tipo: dict = {}
        for i in range(hallados.Length if hallados is not None else 0):
            if len(elementos) >= maximo:
                break
            try:
                elemento = hallados.GetElement(i)
                nombre = (elemento.CachedName or "").strip()
                rect = elemento.CachedBoundingRectangle
                nombre_tipo = por_id.get(elemento.CachedControlType, "")
            except Exception as e:
                logger.debug(f"un elemento de la página no se pudo leer: {e}")
                continue
            if not nombre or rect is None or not nombre_tipo:
                continue
            if por_tipo.get(nombre_tipo, 0) >= MAX_POR_TIPO:
                continue
            ancho, alto = rect.right - rect.left, rect.bottom - rect.top
            if ancho <= 0 or alto <= 0:
                continue
            antes_de_agregar = len(elementos)
            _agregar(elementos, vistos, titulo, nombre, nombre_tipo,
                     rect.left + ancho // 2, rect.top + alto // 2)
            if len(elementos) > antes_de_agregar:
                por_tipo[nombre_tipo] = por_tipo.get(nombre_tipo, 0) + 1

    # En orden de lectura: arriba-abajo, izquierda-derecha. Al modelo le sirve el orden
    # visual, no el que tenga el árbol por dentro.
    elementos.sort(key=lambda e: (e.y, e.x))
    return elementos[:maximo]


def _accionables_lento(documento) -> List:
    """Respaldo sin `FindAll`: recorre el documento a mano, acotado."""
    salida, pendientes = [], [(documento, 0)]
    while pendientes and len(salida) < 400:
        control, profundidad = pendientes.pop(0)
        if profundidad > 12:
            continue
        try:
            hijos = control.GetChildren()
        except Exception:
            continue
        for hijo in hijos:
            try:
                if hijo.ControlTypeName in TIPOS_ACCIONABLES:
                    salida.append(hijo)
            except Exception:
                continue
            pendientes.append((hijo, profundidad + 1))
    return salida


#: La última ventana que abrió el agente. Un trámite son varios pasos —abrir, leer, escribir,
#: pulsar— y todos tienen que caer en la MISMA página. Sin esto, "la primera ventana legible"
#: podía ser el WhatsApp que el usuario tiene abierto en otra ventana, y el clic aterrizaba
#: ahí. Es una preferencia, no una atadura: si esa ventana se cerró, se sigue buscando.
_ultima_ventana: Optional[int] = None


def ventana_con_pagina() -> Optional[Tuple[int, str, str]]:
    """Return la ventana de navegador sobre la que hay que actuar.

    Por orden: la que abrió el agente, la que el usuario tiene delante, y recién después
    cualquiera que se pueda leer. El orden importa: con tres ventanas abiertas, "cualquiera"
    es una lotería, y la papeleta perdedora es un clic dentro de la sesión de otra página.
    """
    abiertas = ventanas_de_navegador()
    if not abiertas:
        return None

    al_frente = _u32.GetForegroundWindow() if _u32 is not None else 0
    preferidas = [d for d in abiertas if d[0] == _ultima_ventana]
    preferidas += [d for d in abiertas if d[0] == al_frente and d[0] != _ultima_ventana]
    resto = [d for d in abiertas if d not in preferidas]

    for datos in preferidas + resto:
        if ve_la_pagina(datos[0]):
            return datos
    return None


def _normalizar_url(url: str) -> str:
    direccion = str(url or "").strip()
    if not direccion:
        return ""
    if not direccion.startswith(("http://", "https://")):
        direccion = "https://" + direccion
    return direccion


def _esperar_ventana(antes: dict, segundos: float = 15.0) -> Optional[Tuple[int, str, str]]:
    """Espera la ventana donde acaba de abrirse la dirección.

    Puede ser una ventana nueva o una que ya existía y cambió de título —abrir en una
    pestaña de una ventana abierta es el caso normal—, así que se contemplan las dos.
    """
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        for hwnd, titulo, nombre in ventanas_de_navegador():
            if hwnd not in antes or antes[hwnd] != titulo:
                return hwnd, titulo, nombre
        time.sleep(0.5)
    return None


def abrir(url: str) -> str:
    """Abre `url` y espera a poder leerla. Return qué pasó, en lenguaje de usuario."""
    direccion = _normalizar_url(url)
    if not direccion:
        return "Necesito la dirección que querés abrir."

    instalado = ruta_del_navegador()
    if instalado is None:
        return "No encontré Chrome ni Edge instalados en este equipo."
    nombre_navegador, ruta = instalado

    antes = {hwnd: titulo for hwnd, titulo, _n in ventanas_de_navegador()}
    try:
        # Con el navegador ya abierto se deja que use una pestaña: es lo que el usuario
        # espera y no le reordena el escritorio. Si no hay ninguno, lo arranca el agente, y
        # ahí sí se pide una ventana nueva y se enciende la accesibilidad desde el
        # principio: es un proceso nuestro, recién creado, y el flag ahorra la espera a que
        # Chromium decida publicar la página. Sobre un navegador que ya está corriendo el
        # flag no sirve —el proceso vivo se reusa y se ignora—, por eso solo va acá.
        argumentos = ([ruta, direccion] if antes
                      else [ruta, FLAG_ACCESIBILIDAD, "--new-window", direccion])
        subprocess.Popen(argumentos)
    except Exception as e:
        logger.error(f"no se pudo abrir {direccion} en {nombre_navegador}: {e}")
        return f"No pude abrir {direccion}: {e}"

    ventana = _esperar_ventana(antes)
    if ventana is None:
        return (f"Abrí {direccion} en {nombre_navegador}, pero no encontré su ventana para "
                f"leerla. Puedo mirarla con una captura si la necesitás.")

    hwnd, titulo, _nombre = ventana
    global _ultima_ventana
    _ultima_ventana = hwnd

    if not esperar_pagina(hwnd):
        return (
            f"Abrí {direccion} en {nombre_navegador}, pero no consigo leer el contenido de la "
            f"página: el navegador no lo está publicando. Puedo mirarla con una captura y "
            f"actuar sobre lo que se vea, aunque con menos precisión."
        )

    accionables = elementos_de_pagina(hwnd)
    logger.info(f"[Navegador] {direccion} abierta y legible: {len(accionables)} elementos")
    return (f"Abrí {direccion}. Ya veo la página «{titulo}»: {len(accionables)} cosas sobre las "
            f"que puedo actuar. Pedime que pulse cualquiera por su nombre.")


def resumen_de_pagina(maximo: int = 40) -> str:
    """Return lo accionable de la página abierta: enlaces, campos y botones."""
    abiertas = ventanas_de_navegador()
    if not abiertas:
        return "No hay ninguna ventana de navegador abierta."

    # La misma ventana sobre la que actuaría `accionar`: describir una página y pulsar en
    # otra sería la peor manera de equivocarse, porque el modelo elige sobre lo que leyó.
    ventana = ventana_con_pagina()
    accionables = elementos_de_pagina(ventana[0]) if ventana else []
    if not ventana or not accionables:
        return (f"Tenés {abiertas[0][2]} abierto, pero no puedo leer el contenido de ninguna "
                f"pestaña. Puedo mirar la pantalla con una captura si querés.")

    _hwnd, titulo, nombre = ventana
    lineas = [f"En «{titulo}» ({nombre}) puedo accionar:"]
    for e in accionables[:maximo]:
        lineas.append(f"  {e.tipo.replace('Control', '')} «{e.nombre}»")
    if len(accionables) > maximo:
        lineas.append(f"  ... y {len(accionables) - maximo} elementos más "
                      f"(pedí uno concreto por su nombre).")
    return "\n".join(lineas)


def _al_frente(hwnd: int) -> bool:
    """Trae la ventana al frente. Return si de verdad quedó al frente.

    El valor de vuelta no es un detalle: el clic se hace por coordenadas de pantalla, así
    que si la ventana NO llegó al frente, el clic aterriza en la aplicación que sí lo esté
    —el Excel del usuario, su correo—. Windows puede negarse a cambiar el foco, así que
    esto se comprueba en vez de darlo por hecho.
    """
    if _u32 is None:
        return False
    _u32.keybd_event(0x12, 0, 0, 0)          # ALT sintético: levanta el bloqueo de foreground
    _u32.SetForegroundWindow(hwnd)
    _u32.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.4)
    return _u32.GetForegroundWindow() == hwnd


def _sigue_ahi(elemento) -> bool:
    """Return True si en ese punto de la pantalla sigue estando ese elemento.

    Entre leer la página y pulsar pasa un instante, y una página puede moverse sola: un
    banner que aparece, una imagen que termina de cargar y empuja el texto. `pc_click`
    resuelve lo mismo validando el fotograma de la captura; acá se le vuelve a preguntar al
    sistema qué hay justo debajo del punto.
    """
    if not disponible():
        return True                          # sin árbol no se puede comprobar; no se bloquea
    import uiautomation as auto

    try:
        bajo = auto.ControlFromPoint(elemento.x, elemento.y)
        if bajo is None:
            return False
        return (bajo.Name or "").strip() == elemento.nombre
    except Exception as e:
        logger.debug(f"no se pudo comprobar qué hay en ({elemento.x}, {elemento.y}): {e}")
        return True


def _elegir(objetivo: str, elementos: List) -> Tuple[Optional[object], List]:
    """Return el elemento que mejor coincide con `objetivo`, y los candidatos.

    De lo más estricto a lo más flexible: exacto, empieza por, la palabra entera, y recién
    al final "aparece dentro". El paso de la palabra entera no es un lujo: pidiendo
    «Historia» en Wikipedia, el paso de "aparece dentro" elegía «Ver historial», que está
    más arriba en la página y contiene esas letras. Un clic en el sitio equivocado.

    Entre varios candidatos gana el nombre más corto: es el que menos texto añade a lo que
    se pidió, o sea el más parecido.
    """
    import re

    from os_integration.ui_tree import _normalizar

    buscado = _normalizar(objetivo)
    if not buscado:
        return None, elementos

    palabra_entera = re.compile(r"(?<!\w)" + re.escape(buscado) + r"(?!\w)")
    for prueba in (lambda n: n == buscado,
                   lambda n: n.startswith(buscado),
                   lambda n: bool(palabra_entera.search(n)),
                   lambda n: buscado in n):
        coinciden = [e for e in elementos if prueba(_normalizar(e.nombre))]
        if coinciden:
            return min(coinciden, key=lambda e: len(e.nombre)), coinciden
    return None, elementos


def accionar(objetivo: str, texto: Optional[str] = None) -> str:
    """Hace clic en `objetivo` por su NOMBRE, y si hay `texto`, lo escribe ahí.

    Buscar por nombre en el árbol vivo es más seguro que las coordenadas de una captura: no
    hay ventana de tiempo entre mirar y pulsar, que es el riesgo que `pc_click` controla
    validando el fotograma. Acá el árbol se lee en el momento del clic.
    """
    from automation.pc_controller import click_position, type_text

    nombre_objetivo = str(objetivo or "").strip()
    if not nombre_objetivo:
        return "Necesito el nombre de lo que querés que pulse."

    ventana = ventana_con_pagina()
    if ventana is None:
        return ("No puedo leer el contenido de ninguna pestaña del navegador. Abrí la página "
                "que querés y pedímelo de nuevo, o decime que la abra yo.")

    hwnd, titulo, _nombre = ventana
    if not _al_frente(hwnd):
        return ("No pude traer la ventana del navegador al frente, así que no hago clic: "
                "el clic va por coordenadas de pantalla y aterrizaría en la aplicación que "
                "esté delante. Poné el navegador al frente y pedímelo de nuevo.")

    # Se lee DESPUÉS de traerla al frente: la página pudo cambiar mientras tanto.
    elementos = elementos_de_pagina(hwnd)
    elemento, candidatos = _elegir(nombre_objetivo, elementos)
    if elemento is None:
        nombres = ", ".join(f"«{c.nombre}»" for c in candidatos[:8])
        return (f"No encontré «{nombre_objetivo}» en la página. Lo que sí hay: {nombres}"
                if nombres else f"No encontré «{nombre_objetivo}» en la página.")

    if not _sigue_ahi(elemento):
        return (f"«{elemento.nombre}» se movió mientras miraba la página, así que no pulso "
                f"nada. Pedime la página otra vez y lo intento sobre lo que hay ahora.")

    click_position(elemento.x, elemento.y)
    logger.info(f"[Navegador] clic en «{elemento.nombre}» ({elemento.tipo}) de '{titulo[:40]}'")

    if texto is None:
        return f"Hice clic en «{elemento.nombre}»."

    time.sleep(0.3)
    type_text(texto)
    return f"Escribí «{texto}» en «{elemento.nombre}»."
