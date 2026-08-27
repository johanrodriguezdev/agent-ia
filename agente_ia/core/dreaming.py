"""
core/dreaming.py
Destila la memoria sola, cada cierto tiempo, sin que haya que pedírselo.

`MemoryDigestSkill` ya sabe convertir el historial en hechos y escribirlos en `MEMORY.md`,
pero hay que acordarse de decírselo. Este módulo lo hace por su cuenta mientras el agente
está encendido — la versión automática de lo mismo, con dos condiciones que la hacen
soportable:

- **Solo si hay material nuevo.** Destilar cuesta varias llamadas al modelo. Repetirlo cada
  día sobre las mismas conversaciones gasta dinero para reescribir lo que ya estaba, así
  que solo se ejecuta si se han acumulado suficientes memorias desde la última vez.
- **Se puede apagar.** Es lo primero que uno quiere cuando algo consume API por su cuenta.
  Desactivado por configuración, este módulo no hace absolutamente nada.

Deja un registro de cada pasada en `workspace/dreams.md`: cuándo corrió, cuántos registros
miró y qué salió. Un proceso que reescribe tu memoria mientras no miras tiene que poder
explicarse después — es la diferencia entre una función y una caja negra.
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIARIO_PATH = os.path.join(_PROJECT_ROOT, "workspace", "dreams.md")

#: Cada cuánto se comprueba si toca destilar. No es cada cuánto se destila: si no hay
#: material nuevo, la comprobación no cuesta nada y se vuelve a dormir.
INTERVALO_SEGUNDOS = 6 * 3600           # 6 horas

#: Cuántas memorias nuevas hacen falta para que compense destilar. Por debajo, el resumen
#: saldría casi igual al anterior y habríamos pagado varias llamadas para nada.
MIN_MEMORIAS_NUEVAS = 25

#: Espera antes de la primera comprobación. Arrancar la aplicación ya carga bastante; no
#: conviene sumarle una destilación en el primer minuto.
RETRASO_INICIAL_SEGUNDOS = 600          # 10 minutos

_hilo: Optional[threading.Thread] = None
_parar = threading.Event()
_ultimo_total = 0


def esta_activo() -> bool:
    """Return True si la consolidación automática está habilitada en la configuración."""
    try:
        from config_manager import load_config

        return bool(load_config().get("dreaming_enabled", False))
    except Exception as e:
        # Sin poder leer la configuración, no se asume que sí: esto gasta dinero.
        logger.warning(f"No se pudo leer la configuración de consolidación: {e}")
        return False


def _contar_memorias(user_id: str) -> int:
    import sqlite3

    from ai.memory_manager import DB_PATH

    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        total = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE user_id = ? AND archived = 0", (user_id,)
        ).fetchone()[0]
        conn.close()
        return int(total)
    except Exception as e:
        logger.warning(f"No se pudo contar la memoria: {e}")
        return 0


def _anotar_en_diario(texto: str) -> None:
    """Deja constancia de la pasada. Nunca interrumpe: es un registro, no el trabajo."""
    try:
        os.makedirs(os.path.dirname(DIARIO_PATH), exist_ok=True)
        nuevo = not os.path.exists(DIARIO_PATH)
        with open(DIARIO_PATH, "a", encoding="utf-8") as f:
            if nuevo:
                f.write(
                    "# Diario de consolidación\n\n"
                    "> Registro de cada vez que el agente destiló su memoria por su cuenta.\n"
                    "> Sirve para saber qué se guardó y cuándo, sin tener que reconstruirlo.\n\n"
                )
            f.write(f"## {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n{texto}\n\n")
    except OSError as e:
        logger.warning(f"No se pudo escribir el diario de consolidación: {e}")


def ejecutar_una_pasada(user_id: str = None, forzar: bool = False) -> str:
    """Destila si toca. Return una línea con lo que pasó, para el diario y los tests."""
    from core.user_identity import OWNER_USER_ID

    global _ultimo_total
    uid = user_id or OWNER_USER_ID

    total = _contar_memorias(uid)
    nuevas = total - _ultimo_total

    if not forzar and _ultimo_total and nuevas < MIN_MEMORIAS_NUEVAS:
        mensaje = f"Sin cambios suficientes ({nuevas} memorias nuevas); no se destiló."
        logger.info(f"[Consolidación] {mensaje}")
        return mensaje

    try:
        from skills.memory_digest_skill import MemoryDigestSkill

        resultado = MemoryDigestSkill().execute("UPDATE_MEMORY_FILE", {})
    except Exception as e:
        logger.error(f"[Consolidación] falló la destilación: {e}")
        return f"Falló la destilación: {e}"

    _ultimo_total = total
    mensaje = f"{total} memorias revisadas. {resultado}"
    _anotar_en_diario(mensaje)
    logger.info(f"[Consolidación] {mensaje[:120]}")
    return mensaje


def _bucle() -> None:
    if _parar.wait(timeout=RETRASO_INICIAL_SEGUNDOS):
        return
    while not _parar.is_set():
        if esta_activo():
            try:
                ejecutar_una_pasada()
            except Exception as e:
                # El hilo no puede morir por un fallo puntual: mañana lo vuelve a intentar.
                logger.warning(f"[Consolidación] pasada fallida: {e}")
        if _parar.wait(timeout=INTERVALO_SEGUNDOS):
            return


def start_dreaming() -> bool:
    """Arranca la consolidación automática. Return si quedó en marcha.

    Se comprueba la configuración ANTES de crear el hilo: si está desactivada, este módulo
    no deja ni un hilo dormido de fondo.
    """
    global _hilo

    if not esta_activo():
        logger.info("[Consolidación] desactivada por configuración")
        return False
    if _hilo is not None and _hilo.is_alive():
        return True

    _parar.clear()
    _hilo = threading.Thread(target=_bucle, name="dreaming", daemon=True)
    _hilo.start()
    logger.info(
        f"[Consolidación] activada: comprueba cada {INTERVALO_SEGUNDOS // 3600}h, "
        f"destila con {MIN_MEMORIAS_NUEVAS}+ memorias nuevas"
    )
    return True


def stop_dreaming() -> None:
    """Pide la parada. El hilo sale en cuanto despierta."""
    _parar.set()
