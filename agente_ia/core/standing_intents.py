"""
core/standing_intents.py
Recordatorios que se disparan por lo que dices, no por el reloj.

Hasta aquí solo existía la mitad del problema resuelta: "recuérdame el viernes a las 9" se
agenda y salta a esa hora. Pero mucho de lo que uno quiere recordar no tiene fecha, tiene
*ocasión*: "la próxima vez que hable del contador, recuérdame preguntarle por la factura".
Eso no es una tarea pendiente ni una nota — es memoria prospectiva, y hasta ahora no había
dónde ponerla.

Las tres formas de querer acordarse de algo, y dónde vive cada una:

    por reloj      "el viernes a las 9"          -> tasks/ (recordatorios, ya existía)
    por ocasión    "cuando mencione el contador" -> este módulo
    aspiración     "mejorar el checklist"        -> MEMORY.md, a mano

Decisiones que sostienen el diseño:

- **Solo recuerda, no ejecuta.** Una intención dispara un aviso, nunca una acción. Es lo que
  la hace segura: si pudiera ejecutar, cualquiera que consiguiera que dijeras cierta palabra
  estaría accionando el sistema por ti. OpenClaw hace lo mismo en su versión.
- **Persiste, a diferencia del diálogo pendiente.** Un diálogo dura tres minutos; esto puede
  esperar semanas. Va a SQLite, no a memoria del proceso.
- **Se agota.** Presupuesto de disparos, caducidad y enfriamiento. Un recordatorio que salta
  en cada frase deja de ser útil y pasa a ser ruido, y el usuario acaba ignorándolo — que es
  la peor forma de fallar para algo cuyo único trabajo es que le hagan caso.
- **Aislada por usuario.** La clave incluye `user_id`, como todo lo demás desde la
  unificación de identidad.
"""

import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "standing_intents.db")

#: Cuántas veces puede dispararse una intención antes de retirarse sola. Tres es suficiente
#: para que no se pierda si el momento no era bueno, y poco para que no se vuelva ruido.
DISPAROS_POR_DEFECTO = 3

#: Segundos mínimos entre dos avisos de la MISMA intención. Sin esto, hablar tres frases
#: seguidas del contador dispararía el mismo recordatorio tres veces.
ENFRIAMIENTO_SEGUNDOS = 1800.0        # media hora

#: Vida máxima por defecto. Una intención de hace tres meses ya no es un recordatorio, es
#: una sorpresa.
CADUCIDAD_DIAS = 30

#: Palabras demasiado comunes para servir de disparador: saltarían en cualquier frase.
_PALABRAS_VACIAS = frozenset({
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a", "en",
    "y", "o", "que", "qué", "por", "para", "con", "sin", "sobre", "mi", "mis", "tu", "tus",
    "su", "sus", "me", "te", "se", "lo", "le", "les", "es", "son", "ser", "estar", "hay",
    "como", "cómo", "cuando", "cuándo", "muy", "más", "mas", "ya", "no", "si", "sí",
    # Verbos y muletillas de la propia condicion: "cuando vuelva a hablar del contador"
    # trata del CONTADOR. Sin esto, "vuelva" y "hablar" quedaban como disparadores y la
    # intencion saltaba en cualquier frase que llevara esas palabras.
    "vuelva", "vuelvo", "vuelve", "vuelvas", "volver",
    "hablar", "hable", "hablo", "hablas", "hablemos", "hablando",
    "mencione", "menciono", "mencionar", "mencionas", "menciones",
    "diga", "digo", "decir", "dices", "digas",
    "vez", "veces", "proxima", "próxima", "cada", "tema", "sobre",
})

#: Longitud mínima de un disparador. "ok" o "eh" saltarían constantemente.
MIN_CHARS_TRIGGER = 4


def _normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in plano if not unicodedata.combining(c))


def extraer_triggers(texto: str, maximo: int = 4) -> Tuple[str, ...]:
    """Return las palabras de `texto` que sirven como disparador.

    Se descartan las palabras vacías y las muy cortas: un disparador debe ser específico.
    "cuando hable del contador" deja "contador", no "cuando" ni "del".
    """
    palabras = re.findall(r"[a-záéíóúñü]+", _normalizar(texto))
    utiles = [
        p for p in palabras
        if len(p) >= MIN_CHARS_TRIGGER and p not in _PALABRAS_VACIAS
    ]
    # Se conserva el orden de aparición y se quitan duplicados.
    vistas, resultado = set(), []
    for p in utiles:
        if p not in vistas:
            vistas.add(p)
            resultado.append(p)
    return tuple(resultado[:maximo])


@dataclass(frozen=True)
class StandingIntent:
    """Una intención condicionada a que aparezca algo en la conversación."""

    id: int
    user_id: str
    descripcion: str          # qué recordarle: "preguntar por la factura"
    triggers: Tuple[str, ...]  # qué tiene que aparecer: ("contador",)
    creado_en: float
    caduca_en: float
    disparos_restantes: int
    ultimo_disparo: float

    def esta_viva(self, ahora: float) -> bool:
        return self.disparos_restantes > 0 and ahora < self.caduca_en

    def en_enfriamiento(self, ahora: float) -> bool:
        """Return True si es demasiado pronto para volver a avisar de esto.

        `ultimo_disparo <= 0` significa "nunca se ha disparado", no "se disparó en el
        instante cero". Sin esta comprobación, una intención recién creada parecía estar en
        enfriamiento: la resta daba menos que el umbral y el primer aviso no llegaba nunca.
        Con el reloj real del sistema la diferencia es enorme y el fallo quedaba oculto.
        """
        if self.ultimo_disparo <= 0:
            return False
        return (ahora - self.ultimo_disparo) < ENFRIAMIENTO_SEGUNDOS

    def coincide(self, texto_normalizado: str) -> bool:
        """Return True si el texto contiene alguno de los disparadores.

        Se comparan palabras completas, no subcadenas: "contador" no debe dispararse con
        "contadores" a medias ni aparecer dentro de otra palabra por casualidad.
        """
        palabras = set(re.findall(r"[a-záéíóúñü]+", texto_normalizado))
        return any(t in palabras for t in self.triggers)


class StandingIntentStore:
    """Almacén persistente. Una fila por intención, aislada por usuario."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS standing_intents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        descripcion TEXT NOT NULL,
                        triggers TEXT NOT NULL,
                        creado_en REAL NOT NULL,
                        caduca_en REAL NOT NULL,
                        disparos_restantes INTEGER NOT NULL,
                        ultimo_disparo REAL NOT NULL DEFAULT 0
                    )
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_si_user ON standing_intents(user_id)"
                )
        except sqlite3.Error as e:
            logger.error(f"No se pudo preparar la base de intenciones: {e}")

    def _fila_a_intent(self, fila: sqlite3.Row) -> StandingIntent:
        return StandingIntent(
            id=fila["id"],
            user_id=fila["user_id"],
            descripcion=fila["descripcion"],
            triggers=tuple(t for t in fila["triggers"].split(",") if t),
            creado_en=fila["creado_en"],
            caduca_en=fila["caduca_en"],
            disparos_restantes=fila["disparos_restantes"],
            ultimo_disparo=fila["ultimo_disparo"],
        )

    # ── Alta ────────────────────────────────────────────────────────

    def crear(
        self, user_id: str, descripcion: str, triggers: Tuple[str, ...],
        disparos: int = DISPAROS_POR_DEFECTO, dias: int = CADUCIDAD_DIAS,
        ahora: Optional[float] = None,
    ) -> Optional[StandingIntent]:
        """Registra una intención. Return `None` si le falta lo indispensable."""
        if not user_id or not str(user_id).strip():
            logger.warning("Intención sin dueño: se descarta")
            return None
        if not descripcion.strip():
            return None
        if not triggers:
            logger.info(f"Intención sin disparadores utilizables: '{descripcion[:40]}'")
            return None

        t = ahora if ahora is not None else time.time()
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                cursor = conn.execute(
                    """INSERT INTO standing_intents
                       (user_id, descripcion, triggers, creado_en, caduca_en,
                        disparos_restantes, ultimo_disparo)
                       VALUES (?, ?, ?, ?, ?, ?, 0)""",
                    (str(user_id), descripcion.strip(), ",".join(triggers),
                     t, t + dias * 86400, max(1, disparos)),
                )
                nueva_id = cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"No se pudo guardar la intención: {e}")
            return None

        logger.info(
            f"[Intención #{nueva_id}] creada para {user_id}: '{descripcion[:40]}' "
            f"disparadores={triggers}"
        )
        return StandingIntent(
            id=nueva_id, user_id=str(user_id), descripcion=descripcion.strip(),
            triggers=triggers, creado_en=t, caduca_en=t + dias * 86400,
            disparos_restantes=max(1, disparos), ultimo_disparo=0.0,
        )

    # ── Consulta ────────────────────────────────────────────────────

    def listar(
        self, user_id: str, incluir_muertas: bool = False,
        ahora: Optional[float] = None,
    ) -> List[StandingIntent]:
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                filas = conn.execute(
                    "SELECT * FROM standing_intents WHERE user_id = ? ORDER BY id",
                    (str(user_id),),
                ).fetchall()
        except sqlite3.Error as e:
            logger.error(f"No se pudieron leer las intenciones: {e}")
            return []

        t = ahora if ahora is not None else time.time()
        intents = [self._fila_a_intent(f) for f in filas]
        if incluir_muertas:
            return intents
        return [i for i in intents if i.esta_viva(t)]

    def comprobar(
        self, texto: str, user_id: str, ahora: Optional[float] = None,
    ) -> List[StandingIntent]:
        """Return las intenciones que dispara `texto`, y las marca como disparadas.

        Nunca lanza: un fallo aquí no puede impedir que el usuario reciba su respuesta.
        """
        if not texto or not user_id:
            return []

        t = ahora if ahora is not None else time.time()
        normalizado = _normalizar(texto)

        try:
            candidatas = [
                i for i in self.listar(user_id, ahora=t)
                if i.coincide(normalizado) and not i.en_enfriamiento(t)
            ]
            for intent in candidatas:
                self._marcar_disparada(intent.id, t)
            return candidatas
        except Exception as e:
            logger.warning(f"Fallo comprobando intenciones permanentes: {e}")
            return []

    # ── Cambios de estado ───────────────────────────────────────────

    def _marcar_disparada(self, intent_id: int, ahora: float) -> None:
        with self._lock, closing(self._conectar()) as conn, conn:
            conn.execute(
                """UPDATE standing_intents
                   SET disparos_restantes = disparos_restantes - 1, ultimo_disparo = ?
                   WHERE id = ?""",
                (ahora, intent_id),
            )

    def cancelar(self, intent_id: int, user_id: str) -> bool:
        """Retira una intención. El `user_id` va en el WHERE: nadie cancela las de otro."""
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                cursor = conn.execute(
                    "DELETE FROM standing_intents WHERE id = ? AND user_id = ?",
                    (intent_id, str(user_id)),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"No se pudo cancelar la intención #{intent_id}: {e}")
            return False

    def purgar(self) -> int:
        """Borra las agotadas y caducadas. Return cuántas. Para mantenimiento."""
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                cursor = conn.execute(
                    "DELETE FROM standing_intents "
                    "WHERE disparos_restantes <= 0 OR caduca_en < ?",
                    (time.time(),),
                )
                return cursor.rowcount
        except sqlite3.Error as e:
            logger.error(f"No se pudieron purgar las intenciones: {e}")
            return 0


standing_intents = StandingIntentStore()


def formatear_aviso(intents: List[StandingIntent]) -> str:
    """Return el texto que se cuelga a la respuesta cuando algo dispara una intención."""
    if not intents:
        return ""
    if len(intents) == 1:
        return f"Por cierto, me pidió que le recordara: {intents[0].descripcion}"
    lineas = ["Por cierto, me pidió que le recordara:"]
    lineas.extend(f"• {i.descripcion}" for i in intents)
    return "\n".join(lineas)
