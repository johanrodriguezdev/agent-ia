"""
core/flows.py
Flujos durables: trabajo de varios pasos que sobrevive a un reinicio, se puede cancelar a
mitad y se detiene solo cuando necesita permiso.

`learning/routines_engine.py` ya ejecutaba listas de acciones, pero en memoria y de un
tirón: si el PC se apagaba en el paso 3, la próxima vez se empezaba de cero, y no había
forma de cancelar ni de saber qué había pasado. Eso alcanza para "modo trabajo" (abrir dos
apps); no alcanza para "todos los viernes revisá el correo, sacá los pendientes, creá una
tarea por cada uno y mandame el resumen".

Lo que agrega este módulo, tomado del Task Flow de OpenClaw
(`openclaw-main/docs/automation/taskflow.md`):

- **Registro durable** en SQLite: objetivo, estado, pasos con su resultado, y un JSON de
  estado libre entre pasos.
- **Contador de revisión.** Toda escritura declara qué revisión creía estar modificando; si
  no coincide, se rechaza en vez de pisar lo que otro guardó. Sin esto, el hilo del
  planificador y una ejecución manual del mismo flujo se corrompen entre sí en silencio.
- **Cancelación real.** Pedida la cancelación, no se arranca ningún paso más. Se comprueba
  ENTRE pasos releyendo el estado: cancelar un flujo mientras corre tiene que funcionar.
- **Estado `esperando`.** Es la pieza que hace útil lo durable: si un paso necesita
  confirmación y nadie puede darla —porque el flujo lo disparó el reloj a las 4 de la
  mañana— el flujo no falla ni se cuelga pidiendo una respuesta que no va a llegar. Se
  detiene, anota qué le falta, y se retoma después desde donde estaba.

**Seguridad.** Este módulo no relaja nada: cada paso pasa por
`agents/action_registry.execute_action()`, que es uno de los puntos de gate del sistema. Un
flujo no puede hacer nada que el usuario no pudiera hacer pidiendo esos pasos de a uno. Lo
que cambia según quién lo dispara es el CANAL, y con él lo que se permite sin preguntar.
"""

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.notificaciones import notificar
from core.security_manager import ChannelType, security_manager

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "flows.db")

PENDIENTE = "pendiente"
CORRIENDO = "corriendo"
ESPERANDO = "esperando"
EXITOSO = "exitoso"
FALLIDO = "fallido"
CANCELADO = "cancelado"

#: Estados de los que ya no se sale solo.
TERMINALES = frozenset({EXITOSO, FALLIDO, CANCELADO})

#: Tope de pasos por flujo. Un flujo es una rutina, no un programa: si hace falta más que
#: esto, lo que se quiere es otra cosa.
MAX_PASOS = 25


class ConflictoDeRevision(Exception):
    """Se intentó guardar sobre una versión del flujo que ya no es la vigente."""


OMITIDO = "omitido"

#: Operadores admitidos en una condición. Es un conjunto CERRADO y se evalúa con
#: comparaciones de texto, nunca con `eval()`: un flujo es un dato que puede venir de una
#: frase del usuario o de un archivo, y ejecutar código desde ahí sería una puerta abierta.
OPERADORES = ("contiene", "no_contiene", "vacio", "no_vacio")


@dataclass
class Condicion:
    """Cuándo corresponde ejecutar un paso.

    `sobre` dice contra qué se compara: `"anterior"` (el resultado del paso previo) o
    `"paso:N"` (el resultado del paso N, empezando en 1). Referirse a un paso que todavía
    no corrió da texto vacío, que es lo que corresponde: no se puede decidir sobre algo que
    no pasó.
    """
    operador: str
    valor: str = ""
    sobre: str = "anterior"

    def a_dict(self) -> Dict[str, Any]:
        return {"operador": self.operador, "valor": self.valor, "sobre": self.sobre}

    @staticmethod
    def de_dict(datos: Dict[str, Any]) -> Optional["Condicion"]:
        if not isinstance(datos, dict):
            return None
        operador = str(datos.get("operador", "")).strip().lower()
        if operador not in OPERADORES:
            logger.warning(f"Condición con operador desconocido, se ignora: {operador!r}")
            return None
        return Condicion(
            operador=operador,
            valor=str(datos.get("valor", "")),
            sobre=str(datos.get("sobre", "anterior")),
        )

    def describir(self) -> str:
        if self.operador in ("vacio", "no_vacio"):
            return f"si {self.sobre} está {self.operador.replace('_', ' ')}"
        return f"si {self.sobre} {self.operador.replace('_', ' ')} «{self.valor}»"


@dataclass
class Paso:
    """Un paso del flujo y lo que pasó con él."""
    accion: str
    params: Dict[str, Any] = field(default_factory=dict)
    estado: str = PENDIENTE
    resultado: str = ""
    condicion: Optional[Condicion] = None

    def a_dict(self) -> Dict[str, Any]:
        datos = {"accion": self.accion, "params": self.params,
                 "estado": self.estado, "resultado": self.resultado}
        if self.condicion:
            datos["condicion"] = self.condicion.a_dict()
        return datos

    @staticmethod
    def de_dict(datos: Dict[str, Any]) -> "Paso":
        return Paso(
            accion=str(datos.get("accion", "")),
            params=datos.get("params") if isinstance(datos.get("params"), dict) else {},
            estado=str(datos.get("estado", PENDIENTE)),
            resultado=str(datos.get("resultado", "")),
            condicion=Condicion.de_dict(datos.get("condicion")),
        )


def evaluar_condicion(condicion: Optional[Condicion], pasos: List[Paso],
                      indice: int) -> bool:
    """Return True si el paso `indice` debe ejecutarse. Sin condición, siempre True."""
    if condicion is None:
        return True

    referencia = ""
    if condicion.sobre.startswith("paso:"):
        try:
            numero = int(condicion.sobre.split(":", 1)[1])
        except ValueError:
            logger.warning(f"Referencia de paso inválida: {condicion.sobre!r}")
            return False
        if 1 <= numero <= len(pasos):
            referencia = pasos[numero - 1].resultado
    elif indice > 0:
        referencia = pasos[indice - 1].resultado

    texto = (referencia or "").lower()
    valor = (condicion.valor or "").lower()

    if condicion.operador == "contiene":
        return bool(valor) and valor in texto
    if condicion.operador == "no_contiene":
        return not (bool(valor) and valor in texto)
    if condicion.operador == "vacio":
        return not texto.strip()
    return bool(texto.strip())   # no_vacio


@dataclass
class Flujo:
    id: int
    user_id: str
    nombre: str
    objetivo: str
    estado: str
    pasos: List[Paso]
    paso_actual: int
    datos: Dict[str, Any]
    revision: int
    motivo: str
    horario: str
    creado_en: float
    actualizado_en: float

    @property
    def terminado(self) -> bool:
        return self.estado in TERMINALES

    def resumen(self) -> str:
        """Una línea por paso, con lo que le pasó a cada uno."""
        marcas = {PENDIENTE: "·", EXITOSO: "ok", FALLIDO: "x", ESPERANDO: "…",
                  OMITIDO: "–"}
        lineas = [f"Flujo «{self.nombre}» — {self.estado}"]
        for i, paso in enumerate(self.pasos, 1):
            marca = marcas.get(paso.estado, paso.estado)
            condicion = f" ({paso.condicion.describir()})" if paso.condicion else ""
            detalle = f" — {paso.resultado}" if paso.resultado else ""
            lineas.append(f"  {i}. [{marca}] {paso.accion}{condicion}{detalle}")
        if self.motivo:
            lineas.append(f"  Motivo: {self.motivo}")
        return "\n".join(lineas)


class FlowStore:
    """Almacén persistente de flujos. Una fila por flujo, aislada por usuario."""

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
                    CREATE TABLE IF NOT EXISTS flujos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        nombre TEXT NOT NULL,
                        objetivo TEXT NOT NULL DEFAULT '',
                        estado TEXT NOT NULL,
                        pasos TEXT NOT NULL,
                        paso_actual INTEGER NOT NULL DEFAULT 0,
                        datos TEXT NOT NULL DEFAULT '{}',
                        revision INTEGER NOT NULL DEFAULT 0,
                        motivo TEXT NOT NULL DEFAULT '',
                        horario TEXT NOT NULL DEFAULT '',
                        creado_en REAL NOT NULL,
                        actualizado_en REAL NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_flujos_user ON flujos(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_flujos_estado ON flujos(estado)")
        except sqlite3.Error as e:
            logger.error(f"No se pudo preparar la base de flujos: {e}")

    # ── Lectura ─────────────────────────────────────────────────────

    def _fila_a_flujo(self, fila: sqlite3.Row) -> Flujo:
        try:
            pasos_crudos = json.loads(fila["pasos"])
        except (json.JSONDecodeError, TypeError):
            logger.error(f"Flujo {fila['id']} tiene pasos ilegibles — se trata como vacío")
            pasos_crudos = []
        try:
            datos = json.loads(fila["datos"])
        except (json.JSONDecodeError, TypeError):
            datos = {}

        return Flujo(
            id=fila["id"],
            user_id=fila["user_id"],
            nombre=fila["nombre"],
            objetivo=fila["objetivo"],
            estado=fila["estado"],
            pasos=[Paso.de_dict(p) for p in pasos_crudos if isinstance(p, dict)],
            paso_actual=fila["paso_actual"],
            datos=datos if isinstance(datos, dict) else {},
            revision=fila["revision"],
            motivo=fila["motivo"],
            horario=fila["horario"],
            creado_en=fila["creado_en"],
            actualizado_en=fila["actualizado_en"],
        )

    def obtener(self, flujo_id: int) -> Optional[Flujo]:
        try:
            with self._lock, closing(self._conectar()) as conn:
                fila = conn.execute(
                    "SELECT * FROM flujos WHERE id = ?", (flujo_id,),
                ).fetchone()
        except sqlite3.Error as e:
            logger.error(f"No se pudo leer el flujo {flujo_id}: {e}")
            return None
        return self._fila_a_flujo(fila) if fila else None

    def buscar_por_nombre(self, nombre: str, user_id: str = "default") -> Optional[Flujo]:
        """Busca por nombre exacto y, si no hay, por coincidencia parcial."""
        objetivo = (nombre or "").strip().lower()
        if not objetivo:
            return None
        candidatos = self.listar(user_id)
        for flujo in candidatos:
            if flujo.nombre.lower() == objetivo:
                return flujo
        for flujo in candidatos:
            if objetivo in flujo.nombre.lower():
                return flujo
        return None

    def listar(self, user_id: str = "default", estado: Optional[str] = None) -> List[Flujo]:
        consulta = "SELECT * FROM flujos WHERE user_id = ?"
        args: List[Any] = [user_id]
        if estado:
            consulta += " AND estado = ?"
            args.append(estado)
        consulta += " ORDER BY actualizado_en DESC"
        try:
            with self._lock, closing(self._conectar()) as conn:
                filas = conn.execute(consulta, args).fetchall()
        except sqlite3.Error as e:
            logger.error(f"No se pudieron listar los flujos: {e}")
            return []
        return [self._fila_a_flujo(f) for f in filas]

    def reanudables(self, user_id: str = "default") -> List[Flujo]:
        """Flujos que quedaron a medias: esperando permiso, o cortados por un reinicio.

        `corriendo` en disco significa que el proceso murió mientras ejecutaba: nadie deja
        ese estado escrito a propósito.
        """
        return [
            f for f in self.listar(user_id)
            if f.estado in (ESPERANDO, CORRIENDO, PENDIENTE)
        ]

    # ── Escritura ───────────────────────────────────────────────────

    def crear(self, nombre: str, pasos: List[Paso], objetivo: str = "",
              user_id: str = "default", horario: str = "") -> Optional[Flujo]:
        """Registra un flujo nuevo. None si le falta lo indispensable."""
        nombre = (nombre or "").strip()
        if not nombre:
            logger.warning("Flujo sin nombre: se descarta")
            return None
        pasos = [p for p in pasos if p.accion.strip()]
        if not pasos:
            logger.warning(f"Flujo '{nombre}' sin pasos utilizables: se descarta")
            return None
        if len(pasos) > MAX_PASOS:
            logger.warning(f"Flujo '{nombre}' tiene más de {MAX_PASOS} pasos: se recorta")
            pasos = pasos[:MAX_PASOS]

        ahora = time.time()
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                cursor = conn.execute(
                    """INSERT INTO flujos
                       (user_id, nombre, objetivo, estado, pasos, paso_actual, datos,
                        revision, motivo, horario, creado_en, actualizado_en)
                       VALUES (?, ?, ?, ?, ?, 0, '{}', 0, '', ?, ?, ?)""",
                    (user_id, nombre, objetivo, PENDIENTE,
                     json.dumps([p.a_dict() for p in pasos], ensure_ascii=False),
                     horario, ahora, ahora),
                )
                flujo_id = cursor.lastrowid
        except sqlite3.Error as e:
            logger.error(f"No se pudo crear el flujo '{nombre}': {e}")
            return None

        logger.info(f"Flujo '{nombre}' creado con {len(pasos)} paso(s) (id {flujo_id})")
        return self.obtener(flujo_id)

    def guardar(self, flujo: Flujo) -> Flujo:
        """Persiste `flujo` si nadie lo tocó desde que se leyó. Return el flujo con su
        revisión nueva.

        Lanza `ConflictoDeRevision` si la revisión en disco ya no es la que traía el objeto.
        Es deliberado que lance en vez de reintentar solo: quien escribe tiene que releer y
        decidir, porque el estado que iba a guardar puede haber dejado de tener sentido.
        """
        ahora = time.time()
        nueva_revision = flujo.revision + 1
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                cursor = conn.execute(
                    """UPDATE flujos
                       SET estado = ?, pasos = ?, paso_actual = ?, datos = ?,
                           revision = ?, motivo = ?, horario = ?, actualizado_en = ?
                       WHERE id = ? AND revision = ?""",
                    (flujo.estado,
                     json.dumps([p.a_dict() for p in flujo.pasos], ensure_ascii=False),
                     flujo.paso_actual,
                     json.dumps(flujo.datos, ensure_ascii=False),
                     nueva_revision, flujo.motivo, flujo.horario, ahora,
                     flujo.id, flujo.revision),
                )
                if cursor.rowcount == 0:
                    raise ConflictoDeRevision(
                        f"el flujo {flujo.id} cambió mientras se ejecutaba "
                        f"(se esperaba la revisión {flujo.revision})"
                    )
        except sqlite3.Error as e:
            logger.error(f"No se pudo guardar el flujo {flujo.id}: {e}")
            raise ConflictoDeRevision(str(e)) from e

        flujo.revision = nueva_revision
        flujo.actualizado_en = ahora
        return flujo

    def cancelar(self, flujo_id: int, user_id: str = "default") -> bool:
        """Marca el flujo como cancelado. Return True si había algo que cancelar.

        No usa `guardar()` a propósito: cancelar tiene que funcionar aunque el flujo esté
        corriendo y su revisión esté cambiando debajo. El motor comprueba la cancelación
        entre pasos releyendo el estado, así que no hay riesgo de pisar un paso a medias.
        """
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                cursor = conn.execute(
                    """UPDATE flujos SET estado = ?, motivo = ?, revision = revision + 1,
                                        actualizado_en = ?
                       WHERE id = ? AND user_id = ? AND estado NOT IN (?, ?, ?)""",
                    (CANCELADO, "cancelado por el usuario", time.time(),
                     flujo_id, user_id, EXITOSO, FALLIDO, CANCELADO),
                )
                cancelado = cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"No se pudo cancelar el flujo {flujo_id}: {e}")
            return False
        if cancelado:
            logger.info(f"Flujo {flujo_id} cancelado")
        return cancelado

    def borrar(self, flujo_id: int, user_id: str = "default") -> bool:
        try:
            with self._lock, closing(self._conectar()) as conn, conn:
                cursor = conn.execute(
                    "DELETE FROM flujos WHERE id = ? AND user_id = ?", (flujo_id, user_id),
                )
                return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"No se pudo borrar el flujo {flujo_id}: {e}")
            return False


flow_store = FlowStore()


# ── Motor ───────────────────────────────────────────────────────────

def ejecutar(flujo_id: int, canal=None, user_id: str = "default",
             store: Optional[FlowStore] = None) -> Optional[Flujo]:
    """Avanza el flujo desde donde haya quedado. Return el flujo con su estado final.

    Se persiste DESPUÉS de cada paso, no al final: si el proceso muere en el paso 3, la
    próxima ejecución arranca en el 3 y no en el 1.

    `canal` decide qué se puede hacer sin preguntar. Un flujo disparado por el reloj llega
    acá con un canal sin adaptador de confirmación, así que un paso amarillo no cuelga el
    hilo esperando un "sí" que nadie va a escribir: el flujo pasa a `esperando` y sigue
    cuando el dueño lo retome desde un canal donde sí se le pueda preguntar.
    """
    store = store or flow_store
    flujo = store.obtener(flujo_id)
    if flujo is None:
        logger.warning(f"Se pidió ejecutar un flujo inexistente: {flujo_id}")
        return None
    if flujo.terminado:
        return flujo

    canal_resuelto = security_manager.resolve_channel(canal)
    flujo.estado = CORRIENDO
    flujo.motivo = ""
    try:
        flujo = store.guardar(flujo)
    except ConflictoDeRevision as e:
        logger.warning(f"No se arrancó el flujo {flujo_id}: {e}")
        return store.obtener(flujo_id)

    while flujo.paso_actual < len(flujo.pasos):
        # Se relee el estado antes de cada paso: si mientras tanto alguien canceló, no se
        # arranca ninguno más. Es lo que hace que "cancelá ese flujo" funcione de verdad.
        vigente = store.obtener(flujo_id)
        if vigente is None or vigente.estado == CANCELADO:
            logger.info(f"Flujo {flujo_id} cancelado a mitad de ejecución")
            return vigente

        paso = flujo.pasos[flujo.paso_actual]

        # La condición se evalúa ANTES del gate de seguridad: si el paso no corresponde,
        # no tiene sentido pedir permiso para algo que no se va a hacer. Un paso omitido
        # no detiene el flujo ni lo marca como fallido — simplemente no era su turno.
        if not evaluar_condicion(paso.condicion, flujo.pasos, flujo.paso_actual):
            paso.estado = OMITIDO
            paso.resultado = f"no se cumplió la condición ({paso.condicion.describir()})"
            flujo.paso_actual += 1
            try:
                flujo = store.guardar(flujo)
            except ConflictoDeRevision as e:
                logger.warning(f"Flujo {flujo_id}: {e}")
                return store.obtener(flujo_id)
            continue

        if not security_manager.is_action_allowed(paso.accion, canal_resuelto):
            paso.estado = ESPERANDO
            flujo.estado = ESPERANDO
            flujo.motivo = (
                f"el paso {flujo.paso_actual + 1} («{paso.accion}») necesita permiso que "
                f"no se puede pedir por {canal_resuelto.value}"
            )
            logger.info(f"Flujo {flujo_id} en espera: {flujo.motivo}")
            notificar(f"El flujo «{flujo.nombre}» espera permiso", flujo.motivo, "info")
            return _guardar_tolerante(store, flujo)

        try:
            from agents.action_registry import execute_action

            resultado = execute_action(
                paso.accion, paso.params, channel=canal_resuelto, user_id=user_id,
            )
            paso.resultado = str(resultado)[:500]
            paso.estado = EXITOSO
        except Exception as e:
            # Un paso que revienta detiene el flujo pero no pierde lo ya hecho: queda
            # escrito qué pasos salieron bien y en cuál se cortó.
            logger.error(f"Flujo {flujo_id}, paso '{paso.accion}' falló: {e}")
            paso.estado = FALLIDO
            paso.resultado = str(e)[:500]
            flujo.estado = FALLIDO
            flujo.motivo = f"el paso {flujo.paso_actual + 1} («{paso.accion}») falló: {e}"
            # Un flujo programado puede fallar a las tres de la mañana. Sin este aviso, el
            # usuario se entera solo si un día abre la pantalla de Flujos y mira.
            notificar(f"El flujo «{flujo.nombre}» falló", flujo.motivo, "error")
            return _guardar_tolerante(store, flujo)

        flujo.paso_actual += 1
        try:
            flujo = store.guardar(flujo)
        except ConflictoDeRevision as e:
            logger.warning(f"Flujo {flujo_id}: {e}. Se recarga y se deja como esté.")
            return store.obtener(flujo_id)

    flujo.estado = EXITOSO
    flujo.motivo = ""
    logger.info(f"Flujo '{flujo.nombre}' completado ({len(flujo.pasos)} pasos)")
    # Solo se avisa de lo que el usuario no estaba mirando: un flujo lanzado a mano desde
    # la pantalla ya muestra su resultado ahí, y avisar dos veces es ruido.
    if canal_resuelto != ChannelType.DESKTOP:
        notificar(f"Flujo «{flujo.nombre}» completado",
                  f"{len(flujo.pasos)} pasos, sin errores", "ok")
    return _guardar_tolerante(store, flujo)


def _guardar_tolerante(store: FlowStore, flujo: Flujo) -> Flujo:
    """Guarda el estado final; si hubo conflicto, devuelve lo que haya en disco.

    En un estado terminal no tiene sentido propagar el conflicto: quien lo pisó (una
    cancelación, típicamente) tenía razones más nuevas que las nuestras.
    """
    try:
        return store.guardar(flujo)
    except ConflictoDeRevision as e:
        logger.info(f"Flujo {flujo.id}: {e}")
        return store.obtener(flujo.id) or flujo


# ── Programación ────────────────────────────────────────────────────

def nombre_de_agente(flujo_id: int) -> str:
    """Identificador con el que un flujo aparece en el motor proactivo.

    Lleva el id y no el nombre porque es la clave para darlo de baja: renombrar un flujo no
    puede dejar un trigger huérfano imposible de encontrar.
    """
    return f"Flujo#{flujo_id}"


class EjecutorProgramado:
    """Adaptador entre un flujo y `core/proactive_engine.py`.

    Llega a `ejecutar()` con `ChannelType.UNKNOWN` a propósito: ese canal no tiene
    adaptador de confirmación, así que un paso amarillo NO cuelga el hilo del planificador
    esperando un "sí" que a las 4 de la mañana nadie va a escribir. El flujo se detiene en
    `esperando` y el dueño lo retoma cuando quiera.
    """

    def __init__(self, flujo_id: int, user_id: str = "default"):
        self.name = nombre_de_agente(flujo_id)
        self.tools: List[Any] = []
        self._flujo_id = flujo_id
        self._user_id = user_id

    def can_handle(self, task: str) -> float:
        return 0.0   # solo por horario, nunca por selección de agente

    def execute(self, task: str, context: Optional[dict] = None) -> str:
        from core.security_manager import ChannelType

        resultado = ejecutar(
            self._flujo_id, canal=ChannelType.UNKNOWN,
            user_id=(context or {}).get("user_id", self._user_id),
        )
        return resultado.resumen() if resultado else ""


def reiniciar(flujo: Flujo, store: Optional[FlowStore] = None) -> Flujo:
    """Deja el flujo listo para correr de nuevo desde el principio.

    Hace falta porque `ejecutar()` no toca un flujo terminado: sin esto, "ejecutar de
    nuevo" no haría nada. Se limpia también el resultado de cada paso — dejar el de la
    corrida anterior haría que una condición «si el anterior contiene X» decidiera con
    datos viejos.
    """
    store = store or flow_store
    flujo.estado = PENDIENTE
    flujo.paso_actual = 0
    flujo.motivo = ""
    for paso in flujo.pasos:
        paso.estado = PENDIENTE
        paso.resultado = ""
    return _guardar_tolerante(store, flujo)


def programar(flujo: Flujo) -> bool:
    """Registra el disparo automático de `flujo`. Return True si quedó programado.

    Se da de baja primero: reprogramar un flujo cuyo horario cambió no puede dejar el
    trigger viejo vivo, o se dispararía dos veces.
    """
    if not flujo.horario:
        return False
    try:
        from core.proactive_engine import proactive_engine

        proactive_engine.unregister_trigger(nombre_de_agente(flujo.id))
        proactive_engine.register_trigger(
            EjecutorProgramado(flujo.id, flujo.user_id), flujo.horario,
            f"flujo {flujo.nombre}", user_id=flujo.user_id,
        )
    except Exception as e:
        logger.error(f"No se pudo programar el flujo '{flujo.nombre}': {e}")
        return False
    logger.info(f"Flujo '{flujo.nombre}' programado ({flujo.horario})")
    return True


def desprogramar(flujo_id: int) -> int:
    """Da de baja el disparo automático de un flujo. Return cuántos triggers se quitaron."""
    try:
        from core.proactive_engine import proactive_engine

        return proactive_engine.unregister_trigger(nombre_de_agente(flujo_id))
    except Exception as e:
        logger.error(f"No se pudo desprogramar el flujo {flujo_id}: {e}")
        return 0


def programar_todos(user_id: str = "default", store: Optional[FlowStore] = None) -> List[str]:
    """Programa todos los flujos con horario que no estén terminados. Return sus nombres."""
    store = store or flow_store
    programados = []
    for flujo in store.listar(user_id):
        if flujo.horario and not flujo.terminado and programar(flujo):
            programados.append(f"{flujo.nombre} ({flujo.horario})")
    return programados


def reanudar_pendientes(user_id: str = "default",
                        store: Optional[FlowStore] = None) -> List[str]:
    """Return un aviso por cada flujo que quedó a medias. NO los ejecuta.

    Retomarlos solo, al arrancar, sería ejecutar acciones que el usuario no pidió en este
    momento. Se le cuenta qué quedó pendiente y él decide.
    """
    store = store or flow_store
    avisos = []
    for flujo in store.reanudables(user_id):
        if flujo.estado == CORRIENDO:
            # Nadie deja este estado escrito a propósito: el proceso murió ejecutándolo.
            flujo.estado = ESPERANDO
            flujo.motivo = "quedó cortado por un reinicio"
            _guardar_tolerante(store, flujo)
        avisos.append(
            f"«{flujo.nombre}»: {flujo.motivo or 'sin empezar'} "
            f"(paso {flujo.paso_actual + 1} de {len(flujo.pasos)})"
        )
    return avisos
