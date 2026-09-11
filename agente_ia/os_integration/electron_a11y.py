"""
os_integration/electron_a11y.py
Hacer que las aplicaciones Electron publiquen su árbol de accesibilidad.

`ui_tree.py` le pregunta al sistema dónde está cada control, y cuando la aplicación
colabora es exacto e instantáneo. Pero hay una familia entera que no colabora: todo lo
construido sobre Electron —VS Code, Slack, Discord, Teams— esconde su interfaz tras una
«Chrome Legacy Window» y no publica nada. Ahí el agente se quedaba ciego y había que caer
a la visión, que estima coordenadas a ojo sobre una captura.

No es una limitación de Windows: es que Chromium enciende la accesibilidad **por niveles**,
y de forma perezosa. Medido sobre VS Code en esta máquina:

    sin nada                            7 elementos    (solo los botones de la ventana)
    con WM_GETOBJECT                    8 elementos    (aparece el nodo raíz, pero vacío)
    con editor.accessibilitySupport     8 elementos    (el nodo sigue vacío)
    con --force-renderer-accessibility  221 elementos en 0.30 s

Es decir: mandar `WM_GETOBJECT` —lo que hace un lector de pantalla— enciende el nivel
básico y crea el `DocumentControl`, pero **no** construye el árbol del contenido web. Ese
es otro nivel, y solo lo enciende el flag de arranque. Las dos primeras vías no se
descartaron por intuición: se probaron y se midieron.

Lo que hace este módulo es la tercera vía, y la hace permanente. VS Code lee sus flags de
Chromium de `~/.vscode/argv.json`, así que basta con dejar el flag escrito ahí una vez: a
partir del siguiente arranque la aplicación queda tan legible como Excel, sin tener que
lanzarla de ninguna forma especial nunca más.

Dos avisos que el módulo respeta:

- `argv.json` es JSONC: lleva comentarios y un `crash-reporter-id` que no se debe tocar.
  Por eso se edita **insertando una línea**, no reescribiendo el archivo con `json.dump`.
- El flag no se aplica en caliente. Hay que reiniciar la aplicación, y quién decide cuándo
  hacerlo es el usuario, no el agente.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: El flag de Chromium que construye el árbol del contenido web. Sin él, el nodo raíz
#: existe pero está vacío.
FLAG = "force-renderer-accessibility"

#: Por debajo de tantos elementos se considera que una ventana no expone su contenido.
#: VS Code sin el flag daba 7-8 —los botones de la ventana y poco más—; con él, 221. El
#: margen es amplio a propósito: un diálogo pequeño y legítimo puede tener 15 controles.
UMBRAL_ARBOL_VACIO = 25

#: Marcador de que detrás hay un Chromium incrustado que no está publicando su árbol.
MARCADOR_ELECTRON = "chrome legacy window"

#: Aplicaciones que leen sus flags de un `argv.json` propio, con la ruta relativa al home.
#: Todas son derivados de VS Code y comparten el mecanismo.
APPS: Dict[str, Dict[str, str]] = {
    "vscode": {
        "nombre": "Visual Studio Code",
        "argv": os.path.join(".vscode", "argv.json"),
        "pista_titulo": "visual studio code",
    },
    "vscode-insiders": {
        "nombre": "Visual Studio Code - Insiders",
        "argv": os.path.join(".vscode-insiders", "argv.json"),
        "pista_titulo": "visual studio code - insiders",
    },
    "cursor": {
        "nombre": "Cursor",
        "argv": os.path.join(".cursor", "argv.json"),
        "pista_titulo": "cursor",
    },
    "windsurf": {
        "nombre": "Windsurf",
        "argv": os.path.join(".windsurf", "argv.json"),
        "pista_titulo": "windsurf",
    },
}


def ruta_argv(app: str) -> Optional[str]:
    """Return la ruta del `argv.json` de esa aplicación, o `None` si no se conoce."""
    datos = APPS.get(app)
    if not datos:
        return None
    return os.path.join(os.path.expanduser("~"), datos["argv"])


def detectar_app(titulo: str) -> Optional[str]:
    """Return la clave de la aplicación a partir del título de su ventana.

    Se mira de la pista más larga a la más corta: el título de Insiders contiene también el
    de VS Code a secas, y quedarse con el primero que encaje daría la respuesta equivocada.
    """
    t = (titulo or "").lower()
    for app, datos in sorted(APPS.items(), key=lambda kv: -len(kv[1]["pista_titulo"])):
        if datos["pista_titulo"] in t:
            return app
    return None


def parece_electron_sin_arbol(elementos: List, titulo: str = "") -> bool:
    """Return True si la ventana es un Chromium incrustado que no publica su contenido.

    Se exigen las dos cosas —el marcador y que haya muy poco— porque el marcador sigue
    presente cuando el árbol SÍ está poblado: con el flag activo VS Code seguía teniendo su
    «Chrome Legacy Window», solo que además tenía otros 220 controles.

    **Y "que haya muy poco" ya casi no pasa** (2026-09-11). Las mediciones de este módulo se
    hicieron recorriendo el árbol hijo por hijo, y ese recorrido no llegaba al contenido: se
    quedaba sin profundidad. Preguntándole a Windows de una vez (`ui_tree`), el VS Code de
    esta máquina publica 2.399 elementos **sin ningún ajuste en su configuración** —
    comprobado, su `settings.json` no tiene `editor.accessibilitySupport`—. Así que esta
    función devuelve False para VS Code, que es lo correcto: su árbol nunca estuvo apagado.

    Se deja igual porque puede haber una aplicación Electron que de verdad no publique nada,
    y entonces el diagnóstico sigue siendo el bueno.
    """
    if len(elementos) >= UMBRAL_ARBOL_VACIO:
        return False
    nombres = " ".join(getattr(e, "nombre", "") for e in elementos).lower()
    if MARCADOR_ELECTRON in nombres:
        return True
    # Una aplicación conocida que no devuelve prácticamente nada es el mismo caso, aunque
    # su ventana no llegue a exponer el marcador.
    return detectar_app(titulo) is not None


def _sin_comentarios(texto: str) -> str:
    """Return el JSONC sin comentarios ni comas colgantes, listo para `json.loads`."""
    salida = []
    i, n = 0, len(texto)
    en_cadena = False
    while i < n:
        c = texto[i]
        if en_cadena:
            salida.append(c)
            if c == "\\" and i + 1 < n:      # escape: el siguiente carácter va tal cual
                salida.append(texto[i + 1])
                i += 2
                continue
            if c == '"':
                en_cadena = False
            i += 1
            continue
        if c == '"':
            en_cadena = True
            salida.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and texto[i + 1] == "/":
            while i < n and texto[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and texto[i + 1] == "*":
            fin = texto.find("*/", i + 2)
            i = n if fin == -1 else fin + 2
            continue
        salida.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(salida))


def _pos_llave_raiz(texto: str) -> int:
    """Return el índice de la `{` que abre el objeto, ignorando comentarios y cadenas.

    El archivo de VS Code empieza con seis líneas de comentario, así que buscar la primera
    `{` a secas caería dentro de la explicación, no en el objeto.
    """
    i, n = 0, len(texto)
    en_cadena = False
    while i < n:
        c = texto[i]
        if en_cadena:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                en_cadena = False
            i += 1
            continue
        if c == '"':
            en_cadena = True
        elif c == "/" and i + 1 < n and texto[i + 1] == "/":
            while i < n and texto[i] != "\n":
                i += 1
            continue
        elif c == "/" and i + 1 < n and texto[i + 1] == "*":
            fin = texto.find("*/", i + 2)
            i = n if fin == -1 else fin + 2
            continue
        elif c == "{":
            return i
        i += 1
    return -1


def leer_flags(app: str) -> Dict:
    """Return los flags escritos en el `argv.json` de esa aplicación."""
    ruta = ruta_argv(app)
    if not ruta or not os.path.isfile(ruta):
        return {}
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.loads(_sin_comentarios(f.read()))
        return datos if isinstance(datos, dict) else {}
    except Exception as e:
        logger.warning(f"No pude leer {ruta}: {e}")
        return {}


def esta_activo(app: str) -> bool:
    """Return True si esa aplicación ya tiene el flag de accesibilidad escrito."""
    return leer_flags(app).get(FLAG) is True


def activar(app: str) -> Tuple[bool, str]:
    """Escribe el flag en el `argv.json` de la aplicación. Return (si cambió, mensaje).

    Se conserva una copia del archivo original: es configuración del usuario, y aunque la
    edición sea de una línea, dejarla sin vuelta atrás no es aceptable.
    """
    datos = APPS.get(app)
    if not datos:
        return False, f"No sé cómo activar la accesibilidad en «{app}»."

    ruta = ruta_argv(app)
    if not ruta or not os.path.isfile(ruta):
        return False, (
            f"No encontré la configuración de {datos['nombre']} ({ruta}). "
            f"Ábrelo una vez para que la cree."
        )

    if esta_activo(app):
        return False, (
            f"{datos['nombre']} ya tiene la accesibilidad activada. Si aun así no veo sus "
            f"controles, es que no se ha reiniciado desde que se activó."
        )

    try:
        with open(ruta, encoding="utf-8") as f:
            original = f.read()
    except Exception as e:
        logger.warning(f"No pude leer {ruta}: {e}")
        return False, f"No pude leer la configuración de {datos['nombre']}: {e}"

    pos = _pos_llave_raiz(original)
    if pos == -1:
        return False, (
            f"La configuración de {datos['nombre']} no tiene el formato que esperaba; "
            f"no la toco."
        )

    nuevo = (
        original[: pos + 1]
        + "\n\n\t// Publica el árbol de accesibilidad para que O.R.I.O.N. lea la interfaz.\n"
        + f'\t"{FLAG}": true,\n'
        + original[pos + 1:]
    )

    # Si la inserción hubiera roto el archivo, es mejor no escribir nada: con un argv.json
    # inválido VS Code arranca por defecto y el usuario no sabe por qué.
    try:
        json.loads(_sin_comentarios(nuevo))
    except Exception as e:
        logger.error(f"La edición de {ruta} habría dejado un JSON inválido: {e}")
        return False, (
            f"No modifiqué nada: el cambio habría dejado la configuración de "
            f"{datos['nombre']} en un estado inválido."
        )

    try:
        with open(ruta + ".orion-backup", "w", encoding="utf-8") as f:
            f.write(original)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(nuevo)
    except Exception as e:
        logger.error(f"No pude escribir {ruta}: {e}")
        return False, f"No pude escribir la configuración de {datos['nombre']}: {e}"

    logger.info(f"[Árbol] accesibilidad activada en {datos['nombre']} ({ruta})")
    return True, (
        f"Listo: activé el árbol de accesibilidad en {datos['nombre']}. Hay que reiniciarlo "
        f"para que tome efecto — hasta entonces sigo sin ver sus controles. "
        f"(Copia del archivo anterior en {os.path.basename(ruta)}.orion-backup.)"
    )


def diagnostico(titulo: str, elementos: List) -> str:
    """Return por qué no se ve nada en esa ventana, y qué se puede hacer al respecto."""
    app = detectar_app(titulo)
    if app is None:
        return (
            f"Ventana activa: «{titulo}». No expone su contenido al árbol de accesibilidad "
            f"(las aplicaciones basadas en Electron suelen no hacerlo). Usa 'pc_look' para "
            f"verla."
        )

    nombre = APPS[app]["nombre"]
    if esta_activo(app):
        return (
            f"Ventana activa: «{titulo}». {nombre} ya tiene la accesibilidad activada pero "
            f"sigue sin publicar sus controles, así que no se ha reiniciado desde entonces. "
            f"Reinícialo y volveré a verlo. Mientras tanto, usa 'pc_look'."
        )

    return (
        f"Ventana activa: «{titulo}». {nombre} no publica sus controles porque tiene la "
        f"accesibilidad desactivada. Puedo activarla con 'pc_enable_tree' —es un cambio de "
        f"una línea en su configuración, y habría que reiniciar {nombre} una vez—. Después "
        f"vería su interfaz con precisión exacta, en vez de adivinarla sobre una captura. "
        f"Mientras tanto, usa 'pc_look'."
    )
