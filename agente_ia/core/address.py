"""
core/address.py
Tratamiento configurable con el que el agente se dirige al usuario.

Antes la palabra "Señor" estaba escrita a mano en ~94 lugares (chat, voz, Telegram,
Discord, skills, tareas), así que cambiarla obligaba a editar 20 archivos. Ahora sale de
`config_manager.get_user_title()` y se resuelve en cada llamada, no al importar: cambiar
el tratamiento desde la pantalla de Configuración tiene efecto inmediato, sin reiniciar.

Hay dos helpers porque el vocativo se puntúa distinto según dónde caiga en la frase:

    f"Todo listo{vocative()}."        -> "Todo listo, Señor."   | "Todo listo."
    f"{vocative_start()}ya terminé."  -> "Señor, ya terminé."   | "ya terminé."

Un tratamiento vacío es una elección válida ("que no me trate de ninguna forma") y ambos
helpers devuelven cadena vacía sin dejar comas sueltas.
"""

from config_manager import get_user_title


def vocative() -> str:
    """Return el vocativo para el final o el medio de una frase."""
    title = get_user_title().strip()
    return f", {title}" if title else ""


def vocative_start() -> str:
    """Return el vocativo para el comienzo de una frase."""
    title = get_user_title().strip()
    return f"{title}, " if title else ""
