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

VS Code, como cualquier aplicación Electron, esconde su interfaz tras una "Chrome Legacy
Window" y no publica el árbol salvo que se active la accesibilidad. Ahí este módulo devuelve
poco y hay que caer a la visión.

De ahí las dos protecciones que lleva: un tope de tiempo, porque hay aplicaciones que tardan
segundos en responder, y un tope de elementos, porque una hoja de cálculo grande tiene miles
de celdas y ninguna es lo que se está buscando.
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

    elementos: List[Elemento] = []
    inicio = time.monotonic()
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
        return (
            f"Ventana activa: «{titulo}». No expone su contenido al árbol de accesibilidad "
            f"(las aplicaciones tipo Electron suelen no hacerlo). Usa 'pc_look' para verla."
        )

    interactuables = [e for e in elementos if e.tipo in TIPOS_INTERACTUABLES]
    mostrar = interactuables[:maximo] or elementos[:maximo]

    lineas = [f"Ventana activa: «{titulo}» ({len(elementos)} elementos)."]
    lineas.append("Controles con los que se puede interactuar:")
    lineas.extend(f"  - {e}" for e in mostrar)
    if len(interactuables) > maximo:
        lineas.append(f"  ...y {len(interactuables) - maximo} más.")
    return "\n".join(lineas)
