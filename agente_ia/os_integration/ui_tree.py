"""
os_integration/ui_tree.py
Lee el árbol de accesibilidad de Windows para saber qué hay en pantalla, y dónde.

Localizar un botón mirando una captura funciona, pero es adivinar: el modelo estima unas
coordenadas a ojo sobre una imagen y puede equivocarse por veinte píxeles, que con el ratón
es la diferencia entre "Aceptar" y "Cancelar". El sistema operativo, en cambio, **ya sabe**
dónde está cada control y cómo se llama — solo hay que preguntárselo. Es lo que hace
OpenClaw con `get_accessibility_tree`, y en Windows se llama UI Automation.

Cuando funciona es mejor en todo: exacto en vez de aproximado, milisegundos en vez de una
llamada al modelo, y gratis.

Pero no siempre funciona, y conviene saber cuándo. Medido sobre las aplicaciones abiertas en
la máquina real:

    Excel              436 elementos   0.56 s
    Bloc de notas      309 elementos   4.11 s   <- lento
    MySQL Workbench    181 elementos   0.55 s
    Chrome              77 elementos   0.12 s
    VS Code              7 elementos   0.02 s   <- casi nada

De ahí se concluyó que VS Code, como toda aplicación Electron, escondía su interfaz y no
publicaba el árbol salvo que se activara la accesibilidad en su configuración
(`electron_a11y.py`).

**Eso también era el medidor.** Vuelto a medir sobre la misma ventana de VS Code, sin
ningún ajuste en su configuración —comprobado: `settings.json` no tiene
`editor.accessibilitySupport`—:

    recorriendo hijo por hijo        7 elementos
    preguntándole a Windows      2.399 elementos

VS Code publicaba su interfaz entera desde el principio. Lo que no llegaba era el
recorrido. Es coherente con lo que el propio `electron_a11y.py` anotó al medirse: con el
ajuste puesto contaba 8 elementos en vez de 7, o sea que el ajuste no cambiaba nada — y aun
así se siguió recomendando. `pc_enable_tree` se deja porque puede servir en otra aplicación
o en otra versión, pero ya no se ofrece como la explicación de por qué no se ve algo.

De ahí las dos protecciones que lleva: un tope de tiempo, porque hay aplicaciones que tardan
segundos en responder, y un tope de elementos, porque una hoja de cálculo grande tiene miles
de celdas y ninguna es lo que se está buscando.

**Lo que cambió después (2026-09-11): preguntar de una vez en vez de recorrer.**

Las cifras de arriba se midieron recorriendo el árbol hijo por hijo, que es lo que hacía
`_recorrer`. Ese recorrido tiene un límite que no se ve en ninguna de las dos protecciones:
`MAX_PROFUNDIDAD`. El contenido de una ventana real cuelga más abajo de doce niveles, así
que el recorrido no llegaba — y no se cortaba por tiempo, así que **no había ningún aviso de
que faltara algo**. El agente simplemente decía que no encontraba lo que tenía delante.

Medido sobre la misma ventana de Chrome con una página cargada:

    recorriendo hijo por hijo       44 elementos
    preguntándole a Windows      3.467 elementos

`FindAll` busca en todo el subárbol, sin límite de profundidad, resuelto dentro de Windows,
y de paso trae nombres y posiciones en la misma llamada en vez de un viaje por propiedad.
El recorrido a mano queda de respaldo y se usa de verdad: si la librería no expone su
cliente nativo, o si algo no es como se espera, se cae ahí en vez de reventar.

Y el árbol no sirve solo para *mirar*: con él se puede **operar** un control sin el ratón
(`operar()`), que no depende de qué ventana esté delante ni falla porque algo tape el punto.
"""

import logging
import time
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Segundos máximos recorriendo el árbol. El Bloc de notas tardó 4 s en la medición: sin
#: tope, una aplicación lenta deja al usuario esperando sin saber por qué.
TIMEOUT_SEGUNDOS = 3.0

#: Elementos máximos a recoger. Una hoja de cálculo tiene miles de celdas y ninguna suele
#: ser lo que se busca.
MAX_ELEMENTOS = 400

#: Profundidad máxima del recorrido. Más allá suele haber detalle interno de la aplicación.
MAX_PROFUNDIDAD = 12

#: Tipos de control sobre los que tiene sentido hacer clic. Filtrar por esto quita el ruido
#: estructural —paneles, grupos, separadores— que no se puede pulsar.
TIPOS_INTERACTUABLES = frozenset({
    "ButtonControl", "MenuItemControl", "TabItemControl", "ListItemControl",
    "CheckBoxControl", "RadioButtonControl", "HyperlinkControl", "EditControl",
    "ComboBoxControl", "SplitButtonControl", "TreeItemControl", "MenuControl",
    # `DocumentControl` es donde SE ESCRIBE en casi toda aplicación moderna. Sin él, el
    # agente veía los 29 botones y pestañas del Bloc de notas de Windows 11 y no su área de
    # texto, que se llama «Editor de texto» y es un DocumentControl: podía cerrarlo, pero no
    # escribir en él. Medido abriéndolo, no supuesto.
    "DocumentControl",
    # Las filas de una lista de detalle: el Explorador de archivos y las tablas de Office.
    "DataItemControl",
})


@dataclass(frozen=True)
class Elemento:
    """Un control de la interfaz, con su nombre real y su posición exacta."""

    nombre: str
    tipo: str
    x: int
    y: int
    ventana: str = ""

    def __str__(self) -> str:
        legible = self.tipo.replace("Control", "")
        return f"{legible} «{self.nombre}» en ({self.x}, {self.y})"


def disponible() -> bool:
    """Return True si se puede consultar el árbol en esta máquina."""
    try:
        import uiautomation  # noqa: F401

        return True
    except Exception:
        return False


def _normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in plano if not unicodedata.combining(c)).strip()


def _recorrer(control, elementos: List[Elemento], ventana: str, limite_tiempo: float,
              profundidad: int = 0) -> None:
    """Recorre el árbol acumulando controles con nombre. Se detiene por tiempo o cantidad."""
    if profundidad > MAX_PROFUNDIDAD or len(elementos) >= MAX_ELEMENTOS:
        return
    if time.monotonic() > limite_tiempo:
        return

    try:
        hijos = control.GetChildren()
    except Exception:
        return                      # un control puede desaparecer mientras se recorre

    for hijo in hijos:
        if len(elementos) >= MAX_ELEMENTOS or time.monotonic() > limite_tiempo:
            return
        try:
            nombre = (hijo.Name or "").strip()
            tipo = hijo.ControlTypeName
            if nombre:
                rect = hijo.BoundingRectangle
                # Un control invisible o sin área no se puede pulsar: ocupa sitio en la
                # lista y confunde al modelo, que podría intentar hacerle clic.
                if rect and rect.width() > 0 and rect.height() > 0:
                    elementos.append(Elemento(
                        nombre=nombre, tipo=tipo,
                        x=rect.xcenter(), y=rect.ycenter(), ventana=ventana,
                    ))
        except Exception:
            continue

        _recorrer(hijo, elementos, ventana, limite_tiempo, profundidad + 1)


#: `TreeScope_Descendants` de UI Automation: una constante del sistema, no un número
#: elegido acá.
_TREE_DESCENDANTS = 4

#: Tope por tipo de control al preguntar de una vez. Una hoja de cálculo tiene miles de
#: celdas y una página web cientos de enlaces; pasarlos todos no ayuda a decidir.
_MAX_POR_TIPO = 60


def cliente_uia():
    """Return el cliente `IUIAutomation`, o None si esta versión de la librería no lo expone.

    Es API privada de `uiautomation` (`_AutomationClient`). Si una versión futura la mueve,
    esto devuelve None y todo sigue funcionando por el recorrido a mano — más ciego, pero
    sin romperse.
    """
    try:
        from uiautomation.uiautomation import _AutomationClient

        return _AutomationClient.instance().IUIAutomation
    except Exception as e:
        logger.warning(f"UI Automation no expone el cliente nativo: {e}")
        return None


def _preguntar_de_una_vez(ventana, titulo: str) -> List[Elemento]:
    """Return los controles de la ventana pidiéndoselos a Windows en una sola consulta.

    **Por qué existe.** El recorrido a mano (`_recorrer`) baja hijo por hijo y se detiene en
    `MAX_PROFUNDIDAD`. Eso alcanza para un diálogo, y no alcanza para nada más: medido sobre
    una ventana de Chrome con una página cargada, el recorrido devolvía **44 elementos de
    3.467** —el 1,3 % de la ventana— porque el contenido cuelga más abajo de doce niveles.
    No se cortaba por tiempo: se quedaba sin profundidad, que es peor, porque no había
    ningún aviso de que faltaba algo.

    `FindAll` no tiene ese límite: busca en todo el subárbol, dentro de Windows, y de paso
    trae los nombres y las posiciones en la misma llamada en vez de un viaje por propiedad.
    """
    cliente = cliente_uia()
    if cliente is None:
        return []

    import uiautomation as auto

    # Todo el armado va dentro del `try`, no solo la consulta: cualquier cosa que no sea
    # como se espera —una versión de la librería que renombre algo, una ventana que no
    # responda— tiene que caer al recorrido a mano, no reventar la lectura de la pantalla.
    try:
        tipos = {}
        condiciones = []
        for nombre_tipo in list(TIPOS_INTERACTUABLES) + ["TextControl"]:
            id_tipo = getattr(auto.ControlType, nombre_tipo, None)
            if id_tipo is None:
                continue
            tipos[id_tipo] = nombre_tipo
            condiciones.append(cliente.CreatePropertyCondition(
                auto.PropertyId.ControlTypeProperty, id_tipo,
            ))
        if not condiciones:
            return []

        condicion = condiciones[0]
        for otra in condiciones[1:]:
            condicion = cliente.CreateOrCondition(condicion, otra)
        cache = cliente.CreateCacheRequest()
        cache.AddProperty(auto.PropertyId.NameProperty)
        cache.AddProperty(auto.PropertyId.BoundingRectangleProperty)
        cache.AddProperty(auto.PropertyId.ControlTypeProperty)
        hallados = ventana.Element.FindAllBuildCache(_TREE_DESCENDANTS, condicion, cache)
    except Exception as e:
        logger.warning(f"no se pudo leer la ventana de una vez, se recorrerá a mano: {e}")
        return []

    elementos: List[Elemento] = []
    por_tipo: dict = {}
    vistos = set()
    for i in range(hallados.Length):
        if len(elementos) >= MAX_ELEMENTOS:
            break
        try:
            elemento = hallados.GetElement(i)
            nombre = (elemento.CachedName or "").strip()
            rect = elemento.CachedBoundingRectangle
            tipo = tipos.get(elemento.CachedControlType, "")
        except Exception:
            continue
        if not nombre or not tipo or rect is None:
            continue
        if por_tipo.get(tipo, 0) >= _MAX_POR_TIPO:
            continue
        ancho, alto = rect.right - rect.left, rect.bottom - rect.top
        # Un control invisible o sin área no se puede pulsar: ocupa sitio en la lista y
        # confunde al modelo, que podría intentar hacerle clic.
        if ancho <= 0 or alto <= 0:
            continue
        x, y = rect.left + ancho // 2, rect.top + alto // 2
        if (nombre, x, y) in vistos:
            continue
        vistos.add((nombre, x, y))
        por_tipo[tipo] = por_tipo.get(tipo, 0) + 1
        elementos.append(Elemento(nombre=nombre, tipo=tipo, x=x, y=y, ventana=titulo))

    # En orden de lectura: al modelo le sirve el orden visual, no el del árbol.
    elementos.sort(key=lambda e: (e.y, e.x))
    return elementos


def control_por_nombre(raiz, nombre: str, tipos: Optional[frozenset] = None):
    """Return el control que se llama así dentro de `raiz`, o None.

    Hace falta el control y no el `Elemento` porque con el control se puede *operar* —
    pulsarlo, enfocarlo— y con unas coordenadas solo se puede acertar o fallar.

    Es un solo sitio para las dos ventanas que importan: una aplicación cualquiera y el
    documento de una página web. Mientras cada una buscaba por su cuenta, se quedaban con
    nodos distintos que se llaman igual —el título de una sección y el enlace hacia ella—,
    y se terminaba desplazando hasta uno para pulsar el otro.
    """
    cliente = cliente_uia()
    if cliente is None or not nombre:
        return None

    import uiautomation as auto

    aceptados = tipos if tipos is not None else TIPOS_INTERACTUABLES
    try:
        ids = {getattr(auto.ControlType, t) for t in aceptados
               if hasattr(auto.ControlType, t)}
        # `IgnoreCase` evita fallar por una mayúscula; si esta versión de la API no lo
        # admite, se busca exacto, que sirve igual para los nombres que el modelo ya leyó.
        try:
            condicion = cliente.CreatePropertyConditionEx(
                auto.PropertyId.NameProperty, nombre, 1,
            )
        except Exception:
            condicion = cliente.CreatePropertyCondition(auto.PropertyId.NameProperty, nombre)
        hallados = raiz.Element.FindAll(_TREE_DESCENDANTS, condicion)
    except Exception as e:
        logger.debug(f"no se pudo buscar «{nombre}» en la ventana: {e}")
        return None

    for i in range(hallados.Length):
        try:
            control = auto.Control.CreateControlFromElement(hallados.GetElement(i))
            if ids and control.Element.CurrentControlType not in ids:
                continue
            rect = control.BoundingRectangle
            if not rect or rect.width() <= 0 or rect.height() <= 0:
                continue
            return control
        except Exception as e:
            logger.debug(f"un candidato de «{nombre}» no se pudo leer: {e}")
            continue
    return None


def patron(control, nombre: str):
    """Return un patrón de UI Automation del control, o None si no lo tiene.

    Los patrones son lo que permite *operar* un control sin el ratón. Cuando existe,
    siempre es mejor que un clic por coordenadas: no depende de qué ventana esté delante,
    no falla porque algo tape el punto, y no hay ventana de tiempo entre mirar y pulsar.
    """
    if control is None:
        return None
    try:
        import uiautomation as auto

        return control.GetPattern(getattr(auto.PatternId, nombre))
    except Exception as e:
        logger.debug(f"el control no expone {nombre}: {e}")
        return None


def leer_ventana_activa() -> Tuple[List[Elemento], str]:
    """Return los elementos de la ventana en primer plano y su título."""
    if not disponible():
        return [], ""

    import uiautomation as auto

    try:
        ventana = auto.GetForegroundControl()
        titulo = (ventana.Name or "").strip()
    except Exception as e:
        logger.warning(f"No se pudo leer la ventana activa: {e}")
        return [], ""

    inicio = time.monotonic()
    elementos = _preguntar_de_una_vez(ventana, titulo)
    if elementos:
        logger.info(f"[Árbol] '{titulo[:40]}': {len(elementos)} elementos en "
                    f"{time.monotonic() - inicio:.2f}s")
        return elementos, titulo

    # Respaldo: recorrer a mano. Se usa si la librería no expone el cliente nativo o si la
    # ventana no publica nada por esa vía.
    _recorrer(ventana, elementos, titulo, inicio + TIMEOUT_SEGUNDOS)

    transcurrido = time.monotonic() - inicio
    if transcurrido >= TIMEOUT_SEGUNDOS:
        logger.info(
            f"[Árbol] recorrido cortado por tiempo en '{titulo[:40]}' "
            f"({len(elementos)} elementos en {transcurrido:.1f}s)"
        )
    else:
        logger.info(f"[Árbol] '{titulo[:40]}': {len(elementos)} elementos en {transcurrido:.2f}s")

    return elementos, titulo


def buscar(objetivo: str) -> Tuple[Optional[Elemento], List[Elemento]]:
    """Return el elemento que mejor coincide con `objetivo`, y los demás candidatos.

    La búsqueda va de lo más estricto a lo más flexible —exacto, empieza por, contiene—
    porque en una interfaz suele haber varios controles con nombres parecidos, y el más
    parecido literalmente casi siempre es el que se buscaba.
    """
    elementos, _ = leer_ventana_activa()
    if not elementos:
        return None, []

    buscado = _normalizar(objetivo)
    if not buscado:
        return None, elementos

    interactuables = [e for e in elementos if e.tipo in TIPOS_INTERACTUABLES]
    # Se busca primero entre lo pulsable; si no hay nada, entre todo. Un texto suelto puede
    # ser la referencia que el usuario dio ("el mensaje de error") aunque no sea un botón.
    for conjunto in (interactuables, elementos):
        exactos = [e for e in conjunto if _normalizar(e.nombre) == buscado]
        if exactos:
            return exactos[0], exactos

        empiezan = [e for e in conjunto if _normalizar(e.nombre).startswith(buscado)]
        if empiezan:
            return empiezan[0], empiezan

        contienen = [e for e in conjunto if buscado in _normalizar(e.nombre)]
        if contienen:
            return contienen[0], contienen

    return None, interactuables or elementos


def describir_ventana_activa(maximo: int = 25) -> str:
    """Return un resumen legible de lo que hay en la ventana, para dárselo al modelo."""
    elementos, titulo = leer_ventana_activa()
    if not titulo:
        return "No pude identificar la ventana activa."
    if not elementos:
        from os_integration.electron_a11y import diagnostico

        return diagnostico(titulo, elementos)

    from os_integration.electron_a11y import diagnostico, parece_electron_sin_arbol

    # Una ventana Electron devuelve los botones de su marco y nada más. Eso no es "casi
    # nada": es un árbol apagado que se puede encender, y decirlo es más útil que sugerir
    # la visión como si no hubiera alternativa.
    if parece_electron_sin_arbol(elementos, titulo):
        return diagnostico(titulo, elementos)

    interactuables = [e for e in elementos if e.tipo in TIPOS_INTERACTUABLES]
    mostrar = interactuables[:maximo] or elementos[:maximo]

    lineas = [f"Ventana activa: «{titulo}» ({len(elementos)} elementos)."]
    lineas.append("Controles con los que se puede interactuar:")
    lineas.extend(f"  - {e}" for e in mostrar)
    if len(interactuables) > maximo:
        lineas.append(f"  ...y {len(interactuables) - maximo} más.")
    return "\n".join(lineas)


def _contenido_de(control, largo_esperado: int) -> Optional[str]:
    """Return lo que el control dice que contiene, o None si no lo publica."""
    valor = patron(control, "ValuePattern")
    if valor is not None:
        try:
            contenido = getattr(valor, "Value", None)
            if contenido is not None:
                return contenido
        except Exception as e:
            logger.debug(f"el campo no devolvió su contenido: {e}")
    texto_patron = patron(control, "TextPattern")
    if texto_patron is not None:
        try:
            return texto_patron.DocumentRange.GetText(largo_esperado + 200)
        except Exception as e:
            logger.debug(f"el campo no devolvió su texto: {e}")
    return None


#: Cuánto se espera a que la aplicación termine de procesar lo tecleado antes de comprobar.
#: Las teclas van a la cola del sistema y la aplicación las consume a su ritmo: leer el campo
#: justo después de mandarlas daba «Cotización No. 8841 / V» —a medio escribir— y un aviso
#: falso de que no había quedado bien.
_SEGUNDOS_PARA_ASENTARSE = 2.5


def comprobar_escrito(control, texto: str) -> Optional[str]:
    """Return un aviso si el campo NO quedó con lo que se quiso escribir, o None.

    Escribir es simular un teclado, y eso puede salir mal de formas que no se notan: un
    carácter que se pierde porque la ventana todavía se estaba acomodando, un campo que
    reformatea lo que recibe. Si el control publica su contenido, comprobarlo cuesta una
    consulta y convierte un "creo que lo escribí" en un "lo escribí" o en un aviso.

    Si el control no publica nada, no se inventa un veredicto: se devuelve None.
    """
    if control is None or not texto:
        return None

    esperado = " ".join(texto.split())
    limite = time.monotonic() + _SEGUNDOS_PARA_ASENTARSE
    contenido = _contenido_de(control, len(texto))
    if contenido is None:
        return None

    # Se espera a que deje de cambiar, o a que ya esté lo que se quiso: lo primero que
    # ocurra. Un campo que sigue creciendo es una aplicación que sigue tecleando.
    anterior = None
    while time.monotonic() < limite:
        if esperado in " ".join(contenido.split()):
            return None
        if contenido == anterior:
            break
        anterior = contenido
        time.sleep(0.25)
        contenido = _contenido_de(control, len(texto)) or contenido

    # Se comparan con los blancos aplanados: el Bloc de notas guarda los saltos como CR,
    # otras aplicaciones como CR+LF, y lo que se tecleó llevaba LF. Comparando crudo, un
    # texto de tres líneas escrito perfectamente daba "no quedó como querías".
    if esperado in " ".join(contenido.split()):
        return None
    logger.warning(f"lo escrito no coincide: se quiso «{texto[:40]}» y quedó "
                   f"«{contenido[:40]}»")
    return (f" Ojo: el campo quedó con «{contenido.strip()[:60]}», que no es exactamente lo "
            f"que quise escribir. Revisalo antes de seguir.")


def operar(objetivo: str, texto: Optional[str] = None) -> str:
    """Pulsa un control de la ventana activa POR SU NOMBRE, o escribe en él. Return qué pasó.

    Es el equivalente de escritorio de lo que `navegador.accionar` hace en una página, y por
    el mismo motivo: pulsar por el patrón del propio control no depende de qué ventana esté
    delante, no falla porque algo tape el punto, y no hay ventana de tiempo entre mirar y
    pulsar. Las coordenadas quedan de respaldo para lo que no exponga ningún patrón.

    Antes esto costaba dos o tres llamadas —`pc_find`, `pc_click`, `pc_type`— y cada una
    podía quedar desfasada de la anterior.
    """
    from automation.pc_controller import click_position, type_text

    nombre = str(objetivo or "").strip()
    if not nombre:
        return "Necesito el nombre de lo que querés que pulse."
    if not disponible():
        return ("No puedo leer los controles de esta pantalla, así que no pulso a ciegas. "
                "Mirá con 'pc_look' y usá las coordenadas con 'pc_click'.")

    import uiautomation as auto

    elemento, candidatos = buscar(nombre)
    if elemento is None:
        nombres = ", ".join(f"«{c.nombre}»" for c in candidatos[:8])
        return (f"No encontré «{nombre}» en la ventana. Lo que sí hay: {nombres}"
                if nombres else f"No encontré «{nombre}» en la ventana.")

    try:
        ventana = auto.GetForegroundControl()
    except Exception as e:
        logger.warning(f"no se pudo tomar la ventana activa para operar: {e}")
        ventana = None

    control = control_por_nombre(ventana, elemento.nombre) if ventana is not None else None

    if texto is not None:
        # Enfocar por el árbol y teclear. Se teclea de verdad —en vez de escribir el valor
        # con `ValuePattern`— porque muchas aplicaciones escuchan las pulsaciones para
        # validar o autocompletar, y un valor puesto de golpe no dispara nada de eso.
        enfocado = False
        try:
            if control is not None:
                control.SetFocus()
                enfocado = True
        except Exception as e:
            logger.debug(f"no se pudo enfocar «{elemento.nombre}» por el árbol: {e}")
        if not enfocado:
            click_position(elemento.x, elemento.y)
            time.sleep(0.3)
        type_text(texto)
        logger.info(f"[Pantalla] escribí en «{elemento.nombre}» ({elemento.tipo})")
        aviso = comprobar_escrito(control, texto) or ""
        return f"Escribí «{texto}» en «{elemento.nombre}».{aviso}"

    invocar = patron(control, "InvokePattern")
    if invocar is not None:
        try:
            invocar.Invoke()
            logger.info(f"[Pantalla] invoqué «{elemento.nombre}» ({elemento.tipo})")
            return f"Pulsé «{elemento.nombre}»."
        except Exception as e:
            logger.debug(f"Invoke() falló en «{elemento.nombre}», se pulsa a mano: {e}")

    # Algunas cosas no se invocan, se seleccionan: una pestaña, un elemento de lista.
    seleccionar = patron(control, "SelectionItemPattern")
    if seleccionar is not None:
        try:
            seleccionar.Select()
            logger.info(f"[Pantalla] seleccioné «{elemento.nombre}» ({elemento.tipo})")
            return f"Seleccioné «{elemento.nombre}»."
        except Exception as e:
            logger.debug(f"Select() falló en «{elemento.nombre}», se pulsa a mano: {e}")

    click_position(elemento.x, elemento.y)
    logger.info(f"[Pantalla] clic en «{elemento.nombre}» ({elemento.tipo}) por coordenadas")
    return f"Pulsé «{elemento.nombre}»."
