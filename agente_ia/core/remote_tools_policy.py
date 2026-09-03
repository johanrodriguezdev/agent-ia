"""
core/remote_tools_policy.py
Allow-list de las herramientas que O.R.I.O.N. acepta de un servidor remoto (MCP).

El problema que resuelve: un servidor MCP declara sus propias herramientas, en runtime, y
las describe él mismo — nombre, descripción y riesgo. Registrar lo que venga sería dejar
que un tercero decida qué puede hacer un agente que apaga el PC y borra archivos. Un
servidor que hoy expone `search` puede exponer `delete_everything` mañana, sin avisar.

La respuesta es la misma que usa OpenClaw (`toolFilter.include`, ver
`openclaw-main/docs/tools/mcp.md`): no se importa el catálogo de un servidor, se importan
las herramientas que el usuario nombró. Lo que no está nombrado no entra.

**Fail-CLOSED, al revés que `ai/provider_health.py`.** Archivo ausente, corrupto, con
forma inválida o vacío ⇒ NO se permite ninguna herramienta remota. Que el agente se quede
sin una herramienta es un mal día; que ejecute una que nadie aprobó es un incidente. En
seguridad, ante la duda, no.

Formato de `mcp_allowlist.json` (sibling de config.json, igual que security_overrides.json)::

    {
      "notion":   ["search", "create_page"],
      "calendar": {
        "tools":   ["list_events", "read_*"],
        "canales": ["desktop", "telegram"]
      }
    }

Las claves son nombres de servidor. La forma corta es una lista de patrones estilo glob
(`*`, `?`) contra el nombre de la herramienta TAL COMO la publica el servidor, sin el
prefijo de namespace.

La forma larga agrega `canales`: desde qué canales puede usarse ese servidor. Hace falta
porque toda herramienta remota se registra en AMARILLO como mínimo, y canales como
Telegram solo admiten verde — sin declarar el canal, un tool MCP quedaría inalcanzable
desde el celular. Se implementa con `CHANNEL_ACTION_EXCEPTIONS` de
`core/security_manager.py`, el mecanismo que ya existía para exactamente esto: habilitar
una acción amarilla concreta en un canal puntual sin abrir las demás. Por defecto,
`["desktop"]` — el único canal que ya admite amarillo por política general.
"""

import fnmatch
import json
import logging
import os
from typing import Dict, List

logger = logging.getLogger(__name__)

MCP_ALLOWLIST_FILE = os.path.join(os.path.dirname(__file__), "..", "mcp_allowlist.json")

#: Prefijo obligatorio de toda herramienta remota registrada. Ver `nombre_calificado()`.
PREFIJO_REMOTO = "mcp__"
_SEPARADOR = "__"

#: Canales desde los que se puede usar un servidor si su entrada no dice otra cosa. Se
#: elige DESKTOP porque es el único canal cuya política general ya admite amarillo: el
#: default no habilita nada que no estuviera habilitado.
CANALES_POR_DEFECTO = ("desktop",)


def load_allowlist() -> Dict[str, List[str]]:
    """Return {servidor: [patrones]}. Ante cualquier problema, {} — que no permite nada.

    Nunca lanza y nunca interpreta un archivo inválido como "permitir todo".
    """
    if not os.path.exists(MCP_ALLOWLIST_FILE):
        logger.debug("No hay mcp_allowlist.json: ninguna herramienta remota está permitida")
        return {}
    try:
        with open(MCP_ALLOWLIST_FILE, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        # `except Exception` amplio y logueado, mismo criterio que core/security_config.py:
        # el caso real es un archivo truncado a mitad de escritura (UnicodeDecodeError),
        # no solo JSON inválido. A nivel ERROR y no WARNING: acá el fallback deja al
        # usuario sin herramientas y tiene que poder verlo en el log.
        logger.error(
            f"mcp_allowlist.json ilegible ({type(e).__name__}) — no se permite NINGUNA "
            f"herramienta remota hasta que se corrija: {e}"
        )
        return {}

    if not isinstance(crudo, dict):
        logger.error("mcp_allowlist.json no es un objeto JSON — no se permite nada")
        return {}

    valido: Dict[str, Dict[str, List[str]]] = {}
    for servidor, entrada in crudo.items():
        if not isinstance(servidor, str) or not servidor.strip():
            logger.warning(f"Nombre de servidor inválido en mcp_allowlist.json: {servidor!r}")
            continue

        # Forma corta (lista de patrones) y forma larga ({tools, canales}) conviven: la
        # corta es la que se va a escribir el 90% de las veces y no tiene por qué cargar
        # con la ceremonia de la otra.
        if isinstance(entrada, list):
            patrones, canales = entrada, list(CANALES_POR_DEFECTO)
        elif isinstance(entrada, dict):
            patrones = entrada.get("tools")
            canales_crudos = entrada.get("canales", entrada.get("channels"))
            if not isinstance(patrones, list):
                logger.warning(f"'{servidor}' en mcp_allowlist.json no tiene lista 'tools'")
                continue
            if canales_crudos is None:
                canales = list(CANALES_POR_DEFECTO)
            elif isinstance(canales_crudos, list):
                canales = [c.strip().lower() for c in canales_crudos
                           if isinstance(c, str) and c.strip()]
            else:
                logger.warning(f"'{servidor}': 'canales' no es una lista — se usa el default")
                canales = list(CANALES_POR_DEFECTO)
        else:
            logger.warning(
                f"'{servidor}' en mcp_allowlist.json no es ni una lista de patrones ni un "
                f"objeto con 'tools' — se ignora"
            )
            continue

        limpios = [p.strip().lower() for p in patrones if isinstance(p, str) and p.strip()]
        if not limpios:
            logger.warning(f"'{servidor}' en mcp_allowlist.json no tiene patrones utilizables")
            continue
        if "*" in limpios:
            # No se prohíbe —es una decisión explícita del usuario— pero no puede pasar
            # desapercibida: equivale a aceptar lo que el servidor decida exponer mañana.
            logger.warning(
                f"'{servidor}' está permitido con '*': se aceptará CUALQUIER herramienta que "
                f"publique, incluidas las que agregue en el futuro. Preferí nombrarlas."
            )
        valido[servidor.strip().lower()] = {"tools": limpios, "canales": canales}
    return valido


def is_tool_allowed(servidor: str, tool: str) -> bool:
    """Return True solo si `tool` de `servidor` está explícitamente permitida."""
    if not servidor or not tool:
        return False
    entrada = load_allowlist().get(str(servidor).strip().lower())
    if not entrada:
        return False
    objetivo = str(tool).strip().lower()
    return any(fnmatch.fnmatchcase(objetivo, patron) for patron in entrada["tools"])


def canales_permitidos(servidor: str) -> List[str]:
    """Return los canales desde los que puede usarse `servidor` (vacío si no está listado).

    Nunca inventa: un servidor ausente de la allow-list no habilita ningún canal.
    """
    entrada = load_allowlist().get(str(servidor).strip().lower())
    return list(entrada["canales"]) if entrada else []


def nombre_calificado(servidor: str, tool: str) -> str:
    """Return el nombre con el que se registra una herramienta remota: `mcp__servidor__tool`.

    El namespace no es cosmético. En `agents/tool_registry.py` el nombre del tool ES la
    `action_name` que clasifica `security_manager`: un servidor remoto que publicara un
    tool llamado `task_create` se registraría encima del `task_create` local y heredaría su
    clasificación de riesgo. El prefijo hace que los dos espacios no puedan tocarse.
    """
    return f"{PREFIJO_REMOTO}{str(servidor).strip().lower()}{_SEPARADOR}{str(tool).strip()}"


def parse_nombre_calificado(nombre: str):
    """Return `(servidor, tool)` si `nombre` tiene la forma remota, o `None` si no.

    Se exige exactamente `mcp__<servidor>__<tool>` con servidor y tool no vacíos. Un nombre
    remoto malformado no se "arregla": no se registra.
    """
    if not isinstance(nombre, str) or not nombre.startswith(PREFIJO_REMOTO):
        return None
    resto = nombre[len(PREFIJO_REMOTO):]
    servidor, separador, tool = resto.partition(_SEPARADOR)
    if not separador or not servidor.strip() or not tool.strip():
        return None
    return servidor.strip().lower(), tool.strip()
