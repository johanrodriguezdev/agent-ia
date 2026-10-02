"""
core/estilo_respuesta.py
REQ-071 — que la regla de economía de la especificación de O.R.I.O.N. se cumpla, y se pueda
comprobar que se cumple.

**Qué había.** La especificación de comportamiento dice, en su regla fundamental, que hay
que responder «con la menor cantidad de palabras necesarias», y da el ejemplo: a «abre
Chrome» se contesta «Abriendo Chrome», no un párrafo. El prompt ya pedía «de forma concisa
y directa»… y no alcanzaba. Medido sobre las 170 respuestas guardadas en la memoria del
agente antes de este REQ:

    mediana 374 caracteres · media 778 · p90 1.804 · máxima 6.570
    una línea (≤80): 24 %   ·   largas (>400): 49 %

La mitad de las respuestas pasaba de 400 caracteres. Pedir brevedad en prosa no la produce.

**Qué hace este módulo.** Dos cosas, y la segunda es la que importa:

1. `CONTRATO` — las reglas de economía en términos operativos, con el contraste de lo que
   está mal y lo que está bien. Un modelo copia un ejemplo mucho mejor que una adjetivación.
2. `registrar()` / `estadisticas()` — mide cuánto mide cada respuesta de verdad. Sin esto,
   dentro de un mes nadie sabría si el contrato sirvió o si solo quedó bonito en el prompt.
   El registro es local, anónimo y acotado: longitud, canal y si hubo herramientas. **No se
   guarda el texto**: para leer conversaciones ya está la memoria, y este archivo no tiene
   por qué contener nada que el usuario haya escrito.
"""

import json
import logging
import os
import statistics
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Dónde queda el registro de medidas. Al lado del resto del estado local.
_ARCHIVO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "logs", "longitud_respuestas.jsonl")

#: Cuántas medidas se conservan. Son dos números por línea: con 5.000 el archivo no pasa de
#: medio mega y alcanza para ver una tendencia.
MAX_MEDIDAS = 5000

#: A partir de acá una respuesta se considera larga. Sale de la propia especificación: una
#: confirmación («Abriendo Chrome»), un dato («Son las 6:42») y hasta un resultado con
#: contexto («Listo. Organicé 326 archivos en 4 carpetas») caben de sobra en 400.
LARGA = 400

#: Y acá, una respuesta de una línea: lo que la especificación pide para una confirmación.
UNA_LINEA = 80

_candado = threading.Lock()


#: El contrato que viaja en el prompt. Está en español porque el agente responde en español
#: y porque las reglas se cumplen mejor en el idioma en el que se va a escribir.
CONTRATO = """ECONOMÍA DE LA RESPUESTA (regla fundamental, por encima del resto del estilo):
Responde con la menor cantidad de palabras que transmita lo necesario. La longitud se gana,
no se asume.

- Una acción que se ejecuta se confirma en una línea: «Abriendo Chrome», «Listo»,
  «Hecho», «Detenido». No se explica lo que se va a hacer antes de hacerlo.
- Un dato se da y se calla: «Son las 6:42 de la tarde.»
- Un resultado lleva su cifra, no su relato: «Listo. Organicé 326 archivos en 4 carpetas.»
- Si algo falla, se dice qué pasó y por qué, sin volcar el error técnico: «No pude
  abrir el archivo: parece un problema de permisos.» El detalle, solo si lo piden.
- Una explicación larga se da cuando el usuario pide entender algo, compara opciones o
  pregunta «por qué». Ahí sí: lo que haga falta, bien escrito.

MAL (a «abre Chrome»):
«Por supuesto. Procederé a abrir Google Chrome en tu dispositivo. Una vez que la aplicación
haya sido localizada, la iniciaré y te confirmaré cuando esté lista para usar.»

BIEN:
«Abriendo Chrome.»

No abras con cortesías de relleno («Por supuesto», «Claro que sí», «Con gusto»), no cierres
con la coletilla vacía («¿Hay algo más en lo que pueda ayudarte?»), y no repitas la
pregunta del usuario antes de contestarla.

Eso no es lo mismo que ofrecer algo. Si del contexto sale una acción concreta y útil,
ofrecela en una línea y con el dato delante: «Te quedan 4,8 GB. Puedo ver qué los está
ocupando.» Lo que sobra es la coletilla genérica, no la iniciativa.

LO QUE DICES QUE HICISTE, LO HICISTE:
Nunca des por hecha una acción que no ejecutaste, ni inventes un acceso, un permiso, un
resultado o un recuerdo. Si una herramienta falló, se denegó o no existe, dilo. «No pude»
es una respuesta; «Listo» cuando no está listo es una mentira que el usuario descubre más
tarde y peor.

Distingue lo que sabes de lo que supones, con las palabras:
- comprobado: «Encontré el archivo.» / «Son 326.»
- inferido: «Creo que este es el que buscas.» / «Diría que viene de ahí.»
- desconocido: «No lo sé.» / «No tengo forma de verlo desde acá.»
Una suposición presentada como hecho es el peor error que puedes cometer.

HUMOR:
Sutil, breve y de vez en cuando. Cállatelo del todo cuando haya un error importante, el
usuario esté frustrado, se haya perdido información o esté por ejecutarse algo peligroso.
Ahí se responde y se resuelve, no se hace gracia."""


def bloque_para_el_prompt() -> str:
    """Return el contrato listo para concatenar al prompt de sistema."""
    return CONTRATO


def registrar(respuesta: Optional[str], canal: str = "", con_herramientas: bool = False) -> None:
    """Anota cuánto midió una respuesta. Nunca levanta: medir no puede romper una conversación.

    Se guarda la longitud, el canal y si el turno usó herramientas —un turno que investigó
    y resume cinco fuentes puede ser legítimamente más largo que una confirmación, y sin
    ese dato la media mezclaría peras con manzanas—. El texto no se guarda.
    """
    if not respuesta:
        return
    try:
        medida = {
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "largo": len(respuesta),
            "canal": str(canal or "")[:20],
            "herramientas": bool(con_herramientas),
        }
        with _candado:
            carpeta = os.path.dirname(_ARCHIVO)
            # `makedirs` en cada respuesta es una llamada al sistema por turno para algo
            # que solo puede hacer falta la primera vez.
            if not os.path.isdir(carpeta):
                os.makedirs(carpeta, exist_ok=True)
            with open(_ARCHIVO, "a", encoding="utf-8") as f:
                f.write(json.dumps(medida, ensure_ascii=False) + "\n")
            _recortar_si_crecio()
    except Exception as e:
        logger.debug(f"no se pudo registrar la longitud de la respuesta: {e}")


#: Lo que ocupa una medida en el archivo. Medido, no estimado: una línea real ronda los 75
#: bytes. Sirve para saber si hace falta recortar sin abrir el archivo — `getsize` es una
#: llamada al sistema; leer 5.000 líneas, no.
_BYTES_POR_MEDIDA = 75


def _recortar_si_crecio() -> None:
    """Deja el archivo en las últimas `MAX_MEDIDAS` líneas, si creció de más.

    Se mira primero el **tamaño** del archivo, no su contenido: esto corre después de cada
    respuesta del agente, y leer medio mega de medidas en cada una para contar líneas sería
    pagar un precio por una limpieza que hace falta una vez cada mil turnos.
    """
    try:
        if os.path.getsize(_ARCHIVO) <= MAX_MEDIDAS * _BYTES_POR_MEDIDA * 1.2:
            return
        with open(_ARCHIVO, encoding="utf-8") as f:
            lineas = f.readlines()
        if len(lineas) <= MAX_MEDIDAS:
            return
        with open(_ARCHIVO, "w", encoding="utf-8") as f:
            f.writelines(lineas[-MAX_MEDIDAS:])
    except OSError as e:
        logger.debug(f"no se pudo recortar el registro de longitudes: {e}")


def medidas() -> List[Dict[str, Any]]:
    """Return las medidas registradas. Una línea ilegible se salta, no rompe la lectura."""
    if not os.path.isfile(_ARCHIVO):
        return []
    salida = []
    try:
        with open(_ARCHIVO, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    salida.append(json.loads(linea))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.debug(f"no se pudo leer el registro de longitudes: {e}")
    return salida


def estadisticas(solo_sin_herramientas: bool = False) -> Dict[str, Any]:
    """Return cómo están quedando las respuestas: mediana, media, p90 y el reparto.

    `solo_sin_herramientas` deja fuera los turnos que investigaron o ejecutaron algo, que
    es donde una respuesta larga puede estar justificada. Para juzgar la economía del día a
    día —confirmaciones, datos, charla— ese es el número que vale.
    """
    datos = [m for m in medidas()
             if not (solo_sin_herramientas and m.get("herramientas"))]
    largos = sorted(int(m.get("largo", 0)) for m in datos)
    if not largos:
        return {"respuestas": 0}

    n = len(largos)
    return {
        "respuestas": n,
        "mediana": round(statistics.median(largos)),
        "media": round(statistics.mean(largos)),
        "p90": largos[min(int(n * 0.9), n - 1)],
        "maxima": largos[-1],
        "una_linea": sum(1 for x in largos if x <= UNA_LINEA),
        "largas": sum(1 for x in largos if x > LARGA),
        "porcentaje_largas": round(100 * sum(1 for x in largos if x > LARGA) / n),
    }


def resumen() -> str:
    """Return las estadísticas en una frase que se le pueda decir al usuario."""
    e = estadisticas()
    if not e.get("respuestas"):
        return "Todavía no tengo medidas de mis respuestas."
    return (f"{e['respuestas']} respuestas medidas: mediana {e['mediana']} caracteres, "
            f"media {e['media']}, y un {e['porcentaje_largas']} % por encima de {LARGA}. "
            f"{e['una_linea']} fueron de una línea.")
