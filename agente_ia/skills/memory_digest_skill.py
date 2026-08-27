"""
skills/memory_digest_skill.py
Destila el historial acumulado en un `MEMORY.md` legible y revisable.

Al consolidar las memorias dispersas quedó claro que el almacén no guarda *hechos*, guarda
*conversaciones*: 351 registros del tipo "Johan preguntó X, el agente respondió Y". Eso
sirve para buscar por parecido, pero no para que el modelo sepa de un vistazo quién es
Johan, en qué anda y qué decidió. Esta skill hace ese paso: lee el historial, le pide al
modelo que extraiga lo que merece recordarse, y lo escribe en `MEMORY.md`.

Es la versión manual y con supervisión de lo que OpenClaw automatiza con su consolidación en
segundo plano. Se ejecuta cuando el usuario lo pide, no sola, para que él vea qué se guardó
antes de que empiece a influir en las respuestas.

Reglas de escritura, pensadas para que no se pueda perder trabajo:

- **Lo escrito a mano no se toca.** Solo se reemplaza el bloque entre los marcadores
  generados; el resto del archivo queda byte a byte como estaba.
- **Copia de seguridad antes de escribir**, siempre, en `MEMORY.md.bak`.
- **Si el modelo falla, no se escribe nada.** Un `MEMORY.md` a medias es peor que uno viejo.
"""

import logging
import os
import shutil
from typing import Any, Dict, List, Tuple

from skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_FILE = os.path.join(_PROJECT_ROOT, "MEMORY.md")
BACKUP_FILE = MEMORY_FILE + ".bak"

MARCA_INICIO = "<!-- MEMORIA-GENERADA:INICIO -->"
MARCA_FIN = "<!-- MEMORIA-GENERADA:FIN -->"

#: Cuántos registros del historial se leen como mucho. Con más de esto la destilación se
#: vuelve cara sin aportar: lo viejo ya suele estar recogido en una pasada anterior.
MAX_REGISTROS = 400

#: Registros por llamada al modelo. Lotes pequeños evitan desbordar el contexto y hacen que
#: un fallo puntual no tire toda la destilación.
TAMANO_LOTE = 60

#: Caracteres máximos por registro que se le muestran al modelo.
MAX_CHARS_REGISTRO = 300

#: Contenido mínimo, ya sin la viñeta, para que una línea cuente como hecho. Los modelos
#: intercalan viñetas vacías ("-", "- -", "---") entre los elementos reales; sin este filtro
#: acaban en MEMORY.md como hechos. Se mide el texto y no la línea entera, para no descartar
#: un hecho corto pero legítimo.
MIN_CHARS_HECHO = 3

#: Frases que delatan una petición puntual disfrazada de hecho durable. El prompt ya las
#: prohíbe, pero un modelo desobedece y aquí no hay segunda oportunidad: lo que pase este
#: filtro acaba escrito en MEMORY.md e influyendo en todas las respuestas futuras.
#: Se escriben SIN acentos porque la comparación se hace sobre el texto ya normalizado: el
#: modelo tilda de forma inconsistente y "pidio"/"pidió" deben filtrarse igual.
FRASES_NO_DURABLES = (
    "el usuario pidio",
    "el usuario pregunto",
    "el usuario solicito",
    "el usuario quiso",
    "el usuario intento",
    "pidio que",
    "solicito que",
)


def _es_hecho_durable(linea: str) -> bool:
    """Return False si la línea describe algo que pasó una vez, no algo que es cierto."""
    import unicodedata

    plano = unicodedata.normalize("NFKD", linea.lower())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return not any(frase in plano for frase in FRASES_NO_DURABLES)


_PROMPT_LOTE = (
    "A continuación tienes fragmentos del historial de conversación entre un usuario y su "
    "asistente personal. Extrae ÚNICAMENTE hechos DURABLES sobre el usuario.\n\n"
    "LA PRUEBA QUE DEBE PASAR CADA HECHO: ¿seguirá siendo cierto dentro de seis meses? Si "
    "la respuesta es no, NO lo incluyas.\n\n"
    "PROHIBIDO ABSOLUTAMENTE — no escribas ninguna línea que empiece o contenga:\n"
    "- 'El usuario pidió...'\n"
    "- 'El usuario preguntó...'\n"
    "- 'El usuario quiere que...' (referido a una petición concreta de un momento)\n"
    "- 'El usuario solicitó...'\n"
    "Una petición que ocurrió una vez NO es un hecho durable, por muy real que sea. Que "
    "alguien pidiera abrir la calculadora, reproducir una canción concreta o tomar una "
    "captura es historial, no memoria.\n\n"
    "SÍ son hechos durables:\n"
    "- Datos personales estables: nombre, ciudad, cómo quiere que lo traten, su equipo.\n"
    "- Gustos y aficiones recurrentes: qué música escucha, qué le interesa.\n"
    "- Contexto de vida y trabajo: dónde trabaja, qué proyectos lleva, qué mascotas tiene.\n"
    "- Herramientas y entorno que usa a diario.\n"
    "- Preferencias de trato sostenidas: cómo quiere las respuestas.\n"
    "- Correcciones que le hizo al asistente y que deben respetarse siempre.\n\n"
    "EJEMPLOS.\n"
    "MAL: '- El usuario pidió reproducir Bed of Roses de Bon Jovi.'\n"
    "BIEN: '- Escucha rock clásico, sobre todo Bon Jovi.'\n"
    "MAL: '- El usuario pidió verificar el uso de CPU.'\n"
    "BIEN: (nada, no aporta)\n"
    "MAL: '- El usuario preguntó qué es un bot.'\n"
    "BIEN: (nada, no aporta)\n\n"
    "Reglas de forma:\n"
    "- NO resumas las conversaciones. Generaliza a hechos.\n"
    "- NO inventes nada que no esté en el texto.\n"
    "- Un hecho por línea, empezando con '- '.\n"
    "- Prefiere pocas líneas buenas a muchas mediocres.\n"
    "- Si no hay ningún hecho durable, responde exactamente: SIN HECHOS\n\n"
    "Historial:\n{lote}"
)

_PROMPT_CONSOLIDACION = (
    "Tienes una lista de hechos extraídos sobre un usuario y su asistente. Consolídalos en "
    "un documento de memoria en español, agrupados bajo estos encabezados de nivel 2 y solo "
    "los que tengan contenido:\n\n"
    "## Sobre el usuario\n## Preferencias de trabajo\n## Proyectos y contexto técnico\n"
    "## Decisiones tomadas\n## Correcciones que me hizo\n\n"
    "Reglas estrictas:\n"
    "- Fusiona los duplicados y las contradicciones (gana lo más reciente).\n"
    "- Un hecho por línea, empezando con '- '.\n"
    "- Sin preámbulo ni cierre: empieza directamente por el primer encabezado.\n"
    "- NO inventes nada que no esté en la lista.\n\n"
    "Hechos:\n{hechos}"
)


class MemoryDigestSkill(BaseSkill):
    """Convierte el historial acumulado en un documento de memoria revisable."""

    @property
    def name(self) -> str:
        return "MemoryDigestSkill"

    @property
    def description(self) -> str:
        return (
            "Lee el historial de conversaciones y destila lo que merece recordarse en "
            "MEMORY.md, sin tocar lo que el usuario escribió a mano."
        )

    def get_intents(self) -> List[str]:
        return ["UPDATE_MEMORY_FILE"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("actualiza tu memoria", "UPDATE_MEMORY_FILE"),
            ("actualiza tu archivo de memoria", "UPDATE_MEMORY_FILE"),
            ("destila tu memoria", "UPDATE_MEMORY_FILE"),
            ("consolida lo que sabes de mi", "UPDATE_MEMORY_FILE"),
            ("actualiza el memory md", "UPDATE_MEMORY_FILE"),
            ("repasa lo que has aprendido", "UPDATE_MEMORY_FILE"),
            ("guarda lo que aprendiste de mi", "UPDATE_MEMORY_FILE"),
            ("pon al dia tu memoria", "UPDATE_MEMORY_FILE"),
            ("reconstruye tu memoria", "UPDATE_MEMORY_FILE"),
            ("que recuerdas de mi actualizalo", "UPDATE_MEMORY_FILE"),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        return {}

    # ── Lectura ─────────────────────────────────────────────────────

    def _leer_historial(self) -> List[str]:
        """Return los textos del historial del dueño, del más reciente al más antiguo."""
        import sqlite3

        from ai.memory_manager import DB_PATH
        from core.user_identity import OWNER_USER_ID

        try:
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            filas = conn.execute(
                "SELECT text FROM memories WHERE user_id = ? AND archived = 0 "
                "ORDER BY timestamp DESC LIMIT ?",
                (OWNER_USER_ID, MAX_REGISTROS),
            ).fetchall()
            conn.close()
        except sqlite3.Error as e:
            logger.error(f"No se pudo leer el historial para destilar: {e}")
            return []

        return [t[:MAX_CHARS_REGISTRO] for (t,) in filas if t and t.strip()]

    # ── Destilación ─────────────────────────────────────────────────

    def _extraer_hechos(self, registros: List[str]) -> Tuple[List[List[str]], int]:
        """Return los hechos AGRUPADOS POR LOTE y cuántos lotes fallaron.

        Se devuelven por lote y no en una lista plana porque la puntuación necesita saber en
        cuántos tramos distintos de la conversación apareció cada hecho: repetirse a lo
        largo del tiempo es la señal más fiable de que algo se sostiene, y aplanar la lista
        la destruye.
        """
        from ai.llm_provider import generate_response

        por_lote: List[List[str]] = []
        fallidos = 0
        descartados = 0

        for inicio in range(0, len(registros), TAMANO_LOTE):
            lote = registros[inicio:inicio + TAMANO_LOTE]
            texto = "\n".join(f"- {r}" for r in lote)
            try:
                respuesta = generate_response(
                    [{"role": "user", "content": _PROMPT_LOTE.format(lote=texto)}],
                    "Eres un extractor de hechos. Respondes solo con la lista pedida.",
                )
            except Exception as e:
                logger.warning(f"Lote {inicio // TAMANO_LOTE + 1} falló al destilar: {e}")
                fallidos += 1
                continue

            if not isinstance(respuesta, str) or "SIN HECHOS" in respuesta.upper():
                continue

            del_lote: List[str] = []
            for linea in respuesta.splitlines():
                limpia = linea.strip()
                if not limpia.startswith("-"):
                    continue
                if len(limpia.lstrip("-").strip()) < MIN_CHARS_HECHO:
                    continue
                if not _es_hecho_durable(limpia):
                    descartados += 1
                    continue
                del_lote.append(limpia)

            if del_lote:
                por_lote.append(del_lote)

        if descartados:
            logger.info(f"{descartados} línea(s) descartadas por no ser hechos durables")
        return por_lote, fallidos

    def _consolidar(self, hechos: str) -> str:
        """`hechos` llega ya formateado por `memory_scoring`, con la marca de cuáles se
        repitieron: esa señal es justo lo que el consolidador necesita para ordenar."""
        from ai.llm_provider import generate_response

        respuesta = generate_response(
            [{"role": "user", "content": _PROMPT_CONSOLIDACION.format(
                hechos="\n".join(hechos))}],
            "Eres un consolidador de memoria. Respondes solo con el documento pedido.",
        )
        return respuesta if isinstance(respuesta, str) else ""

    # ── Escritura ───────────────────────────────────────────────────

    def _escribir(self, cuerpo: str) -> None:
        """Reemplaza solo el bloque generado, dejando intacto lo escrito a mano."""
        original = ""
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                original = f.read()
            shutil.copy2(MEMORY_FILE, BACKUP_FILE)

        from datetime import datetime

        bloque = (
            f"{MARCA_INICIO}\n"
            f"<!-- Generado automáticamente el {datetime.now().strftime('%d/%m/%Y %H:%M')}. "
            f"Todo lo que esté FUERA de estos dos marcadores se conserva tal cual. -->\n\n"
            f"{cuerpo.strip()}\n\n"
            f"{MARCA_FIN}"
        )

        if MARCA_INICIO in original and MARCA_FIN in original:
            antes = original.split(MARCA_INICIO)[0]
            despues = original.split(MARCA_FIN, 1)[1]
            nuevo = f"{antes}{bloque}{despues}"
        else:
            separador = "\n\n" if original.strip() else ""
            nuevo = f"{original.rstrip()}{separador}{bloque}\n"

        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(nuevo)

    # ── Ejecución ───────────────────────────────────────────────────

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        from core.address import vocative

        registros = self._leer_historial()
        if not registros:
            return f"No encontré historial que destilar{vocative()}."

        por_lote, fallidos = self._extraer_hechos(registros)
        if not por_lote:
            if fallidos:
                return (
                    f"No pude destilar la memoria{vocative()}: fallaron {fallidos} de los "
                    f"lotes al consultar el modelo. No se modificó nada."
                )
            return (
                f"Revisé {len(registros)} registros y no encontré hechos nuevos que "
                f"merecieran guardarse{vocative()}. MEMORY.md queda como estaba."
            )

        # Un candidato no se promueve por existir, sino por ganárselo: se agrupan los que
        # dicen lo mismo, se cuenta en cuántos tramos distintos apareció cada uno, y se
        # ordena por eso. Antes entraban todos por igual, así que un comentario suelto
        # pesaba lo mismo que algo repetido en veinte conversaciones — y lo que entra de
        # más no es neutro: desplaza a lo que importa, en cada respuesta.
        from core.memory_scoring import formatear_para_consolidar, promover

        promovidos, resumen = promover(por_lote)
        if not promovidos:
            return (
                f"Revisé {len(registros)} registros y no encontré hechos nuevos que "
                f"merecieran guardarse{vocative()}. MEMORY.md queda como estaba."
            )

        try:
            cuerpo = self._consolidar(formatear_para_consolidar(promovidos))
        except Exception as e:
            logger.error(f"Falló la consolidación de la memoria: {e}")
            return f"Extraje los hechos pero no pude consolidarlos{vocative()}. No se escribió nada."

        if not cuerpo.strip():
            return f"El modelo no devolvió nada consolidable{vocative()}. No se escribió nada."

        try:
            self._escribir(cuerpo)
        except OSError as e:
            logger.error(f"No se pudo escribir MEMORY.md: {e}")
            return f"No pude escribir el archivo de memoria{vocative()}: {e}"

        aviso = f" ({fallidos} lote(s) fallaron y se omitieron)" if fallidos else ""
        reforzados = (
            f", {resumen['reforzados']} de ellos confirmados en varios tramos"
            if resumen["reforzados"] else ""
        )
        return (
            f"Memoria actualizada{vocative()}. Revisé {len(registros)} registros, de los "
            f"que salieron {resumen['propuestos']} hechos; agrupé los repetidos en "
            f"{resumen['agrupados']} distintos y promoví {resumen['promovidos']}"
            f"{reforzados}{aviso}. "
            f"Guardé una copia previa en MEMORY.md.bak por si quiere comparar."
        )
