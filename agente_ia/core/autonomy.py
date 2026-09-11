"""
core/autonomy.py
REQ-033 — El modo autonomía: que el agente pueda trabajar sin preguntar, cuando el dueño
decide que así sea.

Existe por un caso concreto de Johan: *"si quiero que trabaje toda la noche me va a hacer
preguntas y no voy a estar disponible"*. Un agente que pregunta cuando no hay nadie no es
seguro, es inútil — el permiso se pide igual y nadie lo contesta, así que la acción se
cancela y la noche se pierde.

La idea que hace esto defendible **no es bajar los niveles de riesgo**. Bajarlos sería
permanente y alcanzaría a todos los canales. Acá se invierte: se cambia un permiso débil
repetido (veinte confirmaciones a las 3 de la mañana que nadie va a leer) por **una
autorización humana fuerte, hecha una vez, delante de la máquina**.

Tres cosas quedan fuera del interruptor, y no son negociables por configuración:

1. **Los canales remotos.** El modo solo vale en `DESKTOP`. Si Telegram heredara la
   autonomía, un mensaje —o un texto inyectado en una página que el agente esté leyendo
   mientras investiga— actuaría con permiso total y sin nadie mirando.
2. **Los otros nueve rojos.** Formatear discos, borrar bases, exponer credenciales, mandar
   correo como el usuario, instalar software, privilegios elevados. El pedido era sobre
   programar; eso no tiene nada que ver con programar.
3. **Encenderlo no es una herramienta del agente.** No hay `ToolSpec` que llame acá. Si el
   agente pudiera encender su propia autonomía, bastaría una instrucción inyectada en una
   página para que se suelte solo. Se enciende desde la pantalla de Configuración, que es un
   acto del humano.

Vigencia: hasta que el humano lo apague (decisión explícita de Johan, 2026-09-09, sobre la
alternativa de que expirara solo). Como el modo sobrevive a los reinicios, la mitigación es
que sea **imposible no verlo**: la ventana lo muestra mientras dure y el arranque lo loguea.
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ARCHIVO_AUTONOMIA = os.path.join(os.path.dirname(__file__), "..", "autonomy_mode.json")

#: Sin autonomía: cada acción amarilla pregunta. Es el estado de fábrica y el fallback ante
#: cualquier duda.
NIVEL_NORMAL = "normal"
#: Trabaja sin preguntar sobre las carpetas habilitadas: escribir, editar y ejecutar.
NIVEL_PROYECTOS = "proyectos"
#: Lo anterior y además puede modificar su propio código. Exige PIN maestro y rama de git.
NIVEL_TOTAL = "total"

NIVELES_VALIDOS = (NIVEL_NORMAL, NIVEL_PROYECTOS, NIVEL_TOTAL)

#: Las únicas acciones amarillas que el modo puede aprobar solo. Es lista blanca a
#: propósito: "trabajar sin preguntar" es sobre CÓDIGO. Apagar el equipo, mandar un mensaje
#: por Telegram o borrar una tarea siguen preguntando aunque la autonomía esté encendida —
#: no son parte del trabajo que se autorizó.
ACCIONES_DE_TRABAJO = frozenset({
    "file_write", "file_edit", "project_run",
    # REQ-036 — levantar un servidor es la misma clase de accion que correr las pruebas: un
    # comando dentro de una carpeta habilitada. Sin esto, "levanta el server y corre las
    # pruebas de integracion" se frenaria en el primer paso justo la noche que no hay nadie.
    # Borrar y mover archivos NO estan: se deshacen con git solo si el archivo estaba
    # versionado, y eso no lo sabe nadie a las 3 de la manana.
    "project_start",
})

#: Lo único rojo que el nivel total desbloquea. Los otros nueve de REQ-005 siguen bloqueados
#: pase lo que pase.
ROJAS_DESBLOQUEADAS_EN_TOTAL = frozenset({"modify_source_code"})


def _leer() -> Dict[str, Any]:
    """Return el contenido del archivo, o el estado normal ante cualquier problema.

    Fail-closed en el sentido que importa acá: un archivo roto NO puede interpretarse como
    "autonomía encendida". Mismo criterio que `core/security_config.py` (REQ-019).
    """
    if not os.path.exists(ARCHIVO_AUTONOMIA):
        return {"nivel": NIVEL_NORMAL}
    try:
        with open(ARCHIVO_AUTONOMIA, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        logger.warning(
            f"autonomy_mode.json ilegible ({type(e).__name__}): se asume modo normal. {e}"
        )
        return {"nivel": NIVEL_NORMAL}

    if not isinstance(crudo, dict):
        logger.warning("autonomy_mode.json no es un objeto — se asume modo normal")
        return {"nivel": NIVEL_NORMAL}
    nivel = crudo.get("nivel")
    if nivel not in NIVELES_VALIDOS:
        logger.warning(f"nivel de autonomía desconocido ({nivel!r}) — se asume modo normal")
        return {"nivel": NIVEL_NORMAL}
    return crudo


def modo_actual() -> str:
    """Return el nivel vigente: `normal`, `proyectos` o `total`."""
    return _leer().get("nivel", NIVEL_NORMAL)


def estado() -> Dict[str, Any]:
    """Return el estado completo, para mostrarlo en la ventana y loguearlo al arrancar."""
    datos = _leer()
    return {
        "nivel": datos.get("nivel", NIVEL_NORMAL),
        "desde": datos.get("desde", ""),
        "rama": datos.get("rama", ""),
        "activo": datos.get("nivel", NIVEL_NORMAL) != NIVEL_NORMAL,
    }


def guardar_modo(nivel: str, rama: str = "") -> None:
    """Persiste el nivel. Levanta `ValueError` si el nivel no existe.

    No valida el PIN ni crea la rama: eso lo hace quien enciende el modo (la pantalla de
    Configuración), porque son decisiones de la interfaz y no de la persistencia.
    """
    if nivel not in NIVELES_VALIDOS:
        raise ValueError(f"nivel de autonomía inválido: {nivel!r}")

    datos = {"nivel": nivel}
    if nivel != NIVEL_NORMAL:
        datos["desde"] = datetime.now().isoformat(timespec="seconds")
        if rama:
            datos["rama"] = rama

    _escritura_atomica(datos)
    if nivel == NIVEL_NORMAL:
        logger.warning("Modo autonomía APAGADO: vuelve a pedir confirmación en cada acción")
    else:
        logger.critical(
            f"Modo autonomía ENCENDIDO en nivel '{nivel}'"
            + (f" sobre la rama '{rama}'" if rama else "")
            + ". Las acciones de trabajo dejan de pedir confirmación en el escritorio."
        )


def _escritura_atomica(datos: Dict[str, Any]) -> None:
    """Escribe el archivo de una, para que un corte no deje un estado a medias."""
    carpeta = os.path.dirname(os.path.abspath(ARCHIVO_AUTONOMIA)) or "."
    descriptor, temporal = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
        os.replace(temporal, ARCHIVO_AUTONOMIA)
    except Exception:
        try:
            os.remove(temporal)
        except OSError:
            pass
        raise


def _es_escritorio(canal: Any) -> bool:
    """Return True solo si el canal es el escritorio, sin importar cómo venga expresado."""
    from core.security_manager import ChannelType, security_manager

    try:
        return security_manager.resolve_channel(canal) is ChannelType.DESKTOP
    except Exception as e:  # un canal irreconocible cae del lado restrictivo
        logger.warning(f"no se pudo resolver el canal para la autonomía: {e}")
        return False


def aprueba_sin_preguntar(accion: str, canal: Any) -> bool:
    """Return True si el modo autoriza esta acción amarilla sin molestar al humano.

    Solo acciones de la lista blanca, solo en el escritorio, y solo con el modo encendido.
    """
    if modo_actual() == NIVEL_NORMAL:
        return False
    if accion not in ACCIONES_DE_TRABAJO:
        return False
    return _es_escritorio(canal)


def aprueba_rojo(accion: str, canal: Any) -> bool:
    """Return True si el nivel total autoriza esta acción roja.

    Solo `modify_source_code`, solo en nivel total, solo en el escritorio. Los otros nueve
    rojos de REQ-005 no pasan por acá ni con la autonomía encendida.
    """
    if modo_actual() != NIVEL_TOTAL:
        return False
    if accion not in ROJAS_DESBLOQUEADAS_EN_TOTAL:
        return False
    return _es_escritorio(canal)


def puede_tocar_su_propio_codigo() -> bool:
    """Return True si el confinamiento de rutas debe dejar entrar a la carpeta de O.R.I.O.N.

    Lo consulta `core/workspace_files.py::resolver()`, que en cualquier otro caso rechaza
    esa carpeta en código (REQ-029/CA-03).
    """
    return modo_actual() == NIVEL_TOTAL


# ─────────────────────────────────────────────
#  La red de seguridad del nivel total: git
# ─────────────────────────────────────────────
#
#  Johan pidió que el agente pueda tocar su propio código "si es para mejorarlo". Ningún
#  gate puede evaluar esa intención — no hay condición que un `if` sepa comprobar. Lo que sí
#  se puede garantizar es que **todo sea reversible**: el trabajo va a una rama propia, cada
#  cosa queda en el historial, y a la mañana se ve el diff completo y se vuelve atrás con un
#  comando. La protección no es confiar en la intención, es poder deshacer.

_CARPETA_ORION = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(*argumentos: str) -> "tuple[int, str]":
    """Corre git en la carpeta de O.R.I.O.N. Return `(codigo, salida)`. Sin shell."""
    import subprocess

    try:
        proceso = subprocess.run(
            ["git"] + list(argumentos), cwd=_CARPETA_ORION,
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.error(f"no se pudo correr git {argumentos}: {e}")
        return 1, str(e)
    salida = (proceso.stdout or b"") + (proceso.stderr or b"")
    return proceso.returncode, salida.decode("utf-8", errors="replace").strip()


def preparar_rama() -> "tuple[str, str]":
    """Crea y cambia a una rama de autonomía. Return `(rama_nueva, rama_anterior)`.

    Levanta `RuntimeError` con el motivo si no se puede: **sin rama no se enciende el nivel
    total**. Que el agente trabaje sobre su propio código directamente en la rama del
    usuario es exactamente el escenario que no queremos a las 3 de la mañana.
    """
    codigo, _ = _git("rev-parse", "--is-inside-work-tree")
    if codigo != 0:
        raise RuntimeError(
            "Mi propia carpeta no es un repositorio git, así que no puedo garantizar que mis "
            "cambios sean reversibles. Sin eso no enciendo el nivel total."
        )

    codigo, anterior = _git("rev-parse", "--abbrev-ref", "HEAD")
    if codigo != 0:
        raise RuntimeError(f"No pude averiguar en qué rama estás: {anterior}")

    nueva = f"autonomia/{datetime.now().strftime('%Y%m%d-%H%M')}"
    codigo, salida = _git("switch", "-c", nueva)
    if codigo != 0:
        # `switch` es de git 2.23+; en versiones viejas se usa `checkout -b`.
        codigo, salida = _git("checkout", "-b", nueva)
    if codigo != 0:
        raise RuntimeError(f"No pude crear la rama de trabajo: {salida}")

    logger.critical(
        f"Modo autonomía total: se creó la rama '{nueva}' (venías de '{anterior}'). "
        f"Todo lo que el agente toque de su propio código queda ahí."
    )
    return nueva, anterior


def registrar_cambio(accion: str, ruta: str) -> bool:
    """Deja en el historial el cambio que el agente acaba de hacer en su propio código.

    Return True si quedó un commit.

    **Por qué existe.** El modo total promete que todo es reversible: "el trabajo va a una
    rama propia, cada cosa queda en el historial, y a la mañana se ve el diff completo".
    La rama se creaba, pero nadie confirmaba nada, así que a la mañana el trabajo de ocho
    horas era un único bulto sin commitear: se podía tirar entero, pero no revisar paso a
    paso ni quedarse con la mitad buena. La promesa estaba escrita y no implementada.

    **Se confirma SOLO el archivo tocado** (`git commit -- <ruta>`), nunca `git add -A`.
    Si el usuario dejó trabajo suyo sin confirmar antes de irse a dormir, barrerlo dentro
    de un commit del agente sería mezclarle sus cambios con los de la noche.

    **Y solo en la rama de autonomía.** Si al volver cambió de rama, esto no escribe nada:
    confirmar sobre una rama que no es la del trabajo es justo lo que el modo existe para
    evitar.
    """
    datos = estado()
    rama = (datos.get("rama") or "").strip()
    if datos.get("nivel") != NIVEL_TOTAL or not rama:
        return False

    from core.workspace_files import es_codigo_de_orion

    if not es_codigo_de_orion(ruta):
        return False                       # el repo del usuario es suyo: no se toca su historial

    codigo, actual = _git("rev-parse", "--abbrev-ref", "HEAD")
    if codigo != 0 or actual.strip() != rama:
        logger.warning(
            f"No registro «{accion}» en el historial: la rama activa es '{actual.strip()}' "
            f"y el trabajo de autonomía va en '{rama}'."
        )
        return False

    relativa = os.path.relpath(os.path.abspath(ruta), _CARPETA_ORION)
    codigo, salida = _git("add", "-A", "--", relativa)
    if codigo != 0:
        logger.error(f"no se pudo preparar «{relativa}» para el historial: {salida}")
        return False

    codigo, pendiente = _git("status", "--porcelain", "--", relativa)
    if codigo != 0 or not pendiente.strip():
        return False                       # el archivo quedó igual: no hay nada que contar

    mensaje = f"autonomia({accion}): {relativa}"
    codigo, salida = _git("commit", "-m", mensaje, "--", relativa)
    if codigo != 0:
        logger.error(f"no se pudo registrar «{relativa}» en el historial: {salida}")
        return False

    logger.info(f"[Autonomía] registrado en '{rama}': {mensaje}")
    return True
