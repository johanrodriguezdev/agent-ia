"""
core/workspace_procesos.py
REQ-036 — Procesos que no terminan: levantar un servidor, usarlo y bajarlo.

`project_run` (REQ-032) espera a que el comando termine y devuelve su salida. Eso cubre
correr las pruebas o un build, pero deja afuera la otra mitad del trabajo real: levantar el
servidor de desarrollo, pegarle, mirar el log, y bajarlo. Con `project_run` eso terminaba
siempre igual — el timeout mata el servidor a los 120 segundos y el turno se pierde.

Acá el proceso queda vivo, con un hilo leyendo su salida a un buffer circular, y el agente
puede consultarla y detenerlo cuando quiera.

Tres cosas que hacen que esto no deje basura:

- **Los procesos mueren con la app.** `MainWindow` llama a `cerrar_todos()` en `aboutToQuit`,
  igual que hace con las terminales embebidas. Un servidor huérfano ocupando el puerto 3000
  después de cerrar el asistente es exactamente lo que nadie quiere depurar.
- **La salida no crece sin freno.** Un servidor que loguea cada petición llenaría la memoria
  en una tarde: se guardan las últimas líneas y nada más.
- **Hay un tope de procesos.** Sin él, un bucle del modelo puede levantar cincuenta.
"""

import logging
import os
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Cuántas líneas de salida se recuerdan por proceso. Un servidor que loguea cada petición
#: llenaría la memoria en una tarde; con las últimas mil alcanza para entender qué pasó.
MAX_LINEAS = 1000

#: Cuántos procesos pueden estar vivos a la vez. El tope existe para que un bucle del modelo
#: no levante cincuenta servidores mientras nadie mira.
MAX_PROCESOS = 5

#: Cuánto se espera a que un proceso se cierre por las buenas antes de matarlo.
SEGUNDOS_PARA_CERRAR = 5


@dataclass
class ProcesoVivo:
    """Un proceso lanzado por el agente que sigue corriendo."""

    identificador: str
    comando: str
    carpeta: str
    proceso: subprocess.Popen
    iniciado: str
    lineas: Deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LINEAS))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def vivo(self) -> bool:
        return self.proceso.poll() is None

    @property
    def codigo(self) -> Optional[int]:
        return self.proceso.poll()

    def agregar(self, linea: str) -> None:
        with self._lock:
            self.lineas.append(linea)

    def salida(self, ultimas: int = 100) -> str:
        with self._lock:
            recientes = list(self.lineas)[-max(1, ultimas):]
        return "".join(recientes)


_PROCESOS: Dict[str, ProcesoVivo] = {}
_LOCK = threading.Lock()
_CONTADOR = 0


def _leer_salida(vivo: ProcesoVivo) -> None:
    """Hilo lector: vuelca la salida del proceso al buffer, línea por línea.

    Sin este hilo, la tubería del sistema se llena y el proceso se BLOQUEA esperando que
    alguien lea — un servidor que loguea se congelaría solo, y el síntoma (se cuelga después
    de un rato) es de los peores de diagnosticar.
    """
    try:
        for cruda in iter(vivo.proceso.stdout.readline, b""):
            vivo.agregar(cruda.decode("utf-8", errors="replace"))
    except (OSError, ValueError) as e:
        logger.debug(f"lector del proceso {vivo.identificador} terminado: {e}")
    finally:
        try:
            vivo.proceso.stdout.close()
        except OSError:
            pass


def iniciar(comando: str, ruta: str = "", raices: Optional[List[str]] = None) -> ProcesoVivo:
    """Lanza `comando` en segundo plano dentro de una carpeta habilitada.

    Levanta `RutaFueraDeRaiz` si la carpeta no sirve, y `RuntimeError` si ya hay demasiados
    procesos vivos.
    """
    from core.workspace_run import _invocacion, carpeta_de_trabajo

    global _CONTADOR

    texto = str(comando or "").strip()
    if not texto:
        raise ValueError("comando vacío")

    carpeta = carpeta_de_trabajo(ruta, raices)

    with _LOCK:
        _limpiar_terminados()
        if len(_PROCESOS) >= MAX_PROCESOS:
            raise RuntimeError(
                f"Ya hay {len(_PROCESOS)} procesos corriendo, que es el máximo. Detené alguno "
                f"antes de levantar otro."
            )
        _CONTADOR += 1
        identificador = f"p{_CONTADOR}"

    proceso = subprocess.Popen(
        _invocacion(texto),
        cwd=carpeta,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # junto, por lo mismo que en project_run: el error importa
        stdin=subprocess.DEVNULL,   # nadie va a contestarle una pregunta interactiva
    )
    vivo = ProcesoVivo(
        identificador=identificador, comando=texto, carpeta=carpeta, proceso=proceso,
        iniciado=datetime.now().strftime("%H:%M:%S"),
    )
    threading.Thread(target=_leer_salida, args=(vivo,), daemon=True).start()

    with _LOCK:
        _PROCESOS[identificador] = vivo
    logger.warning(f"Proceso en segundo plano {identificador} iniciado en «{carpeta}»: {texto}")
    return vivo


def _limpiar_terminados() -> None:
    """Saca de la lista los que ya terminaron solos. Se llama con `_LOCK` tomado."""
    for identificador in [i for i, v in _PROCESOS.items() if not v.vivo]:
        logger.info(f"Proceso {identificador} ya había terminado (código "
                    f"{_PROCESOS[identificador].codigo})")
        _PROCESOS.pop(identificador, None)


def obtener(identificador: str) -> Optional[ProcesoVivo]:
    with _LOCK:
        return _PROCESOS.get(identificador)


def listar() -> List[ProcesoVivo]:
    with _LOCK:
        return list(_PROCESOS.values())


def detener(identificador: str) -> str:
    """Detiene un proceso lanzado por el agente. Return qué pasó, en una frase."""
    with _LOCK:
        vivo = _PROCESOS.get(identificador)
    if vivo is None:
        return f"No tengo ningún proceso «{identificador}» corriendo."

    if not vivo.vivo:
        with _LOCK:
            _PROCESOS.pop(identificador, None)
        return f"El proceso «{identificador}» ya había terminado por su cuenta (código {vivo.codigo})."

    vivo.proceso.terminate()
    try:
        vivo.proceso.wait(timeout=SEGUNDOS_PARA_CERRAR)
        final = "se cerró"
    except subprocess.TimeoutExpired:
        # Por las malas: un servidor que ignora la señal no puede quedar vivo porque sí.
        vivo.proceso.kill()
        try:
            vivo.proceso.wait(timeout=SEGUNDOS_PARA_CERRAR)
        except subprocess.TimeoutExpired:
            logger.error(f"el proceso {identificador} no murió ni con kill()")
        final = "no respondió y lo maté"

    with _LOCK:
        _PROCESOS.pop(identificador, None)
    logger.warning(f"Proceso {identificador} detenido ({final}): {vivo.comando}")
    return f"Detuve «{identificador}» ({vivo.comando}): {final}."


def cerrar_todos() -> int:
    """Detiene todo. Lo llama `MainWindow` al salir. Return cuántos cerró."""
    identificadores = [v.identificador for v in listar()]
    for identificador in identificadores:
        try:
            detener(identificador)
        except Exception as e:
            logger.warning(f"no se pudo detener {identificador} al salir: {e}")
    if identificadores:
        logger.info(f"{len(identificadores)} procesos en segundo plano cerrados al salir")
    return len(identificadores)


def describir(vivo: ProcesoVivo, ultimas: int = 40) -> str:
    """Return el estado del proceso y sus últimas líneas, para el modelo."""
    estado = "corriendo" if vivo.vivo else f"terminado (código {vivo.codigo})"
    salida = vivo.salida(ultimas).strip() or "(todavía no escribió nada)"
    return (f"«{vivo.identificador}» — {vivo.comando}\n"
            f"Carpeta: {vivo.carpeta} | Iniciado: {vivo.iniciado} | Estado: {estado}\n\n"
            f"{salida}")
