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


_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def momento_actual() -> str:
    """Return la fecha, la hora y la zona horaria del equipo, para el prompt del modelo.

    Sin esto el modelo no sabe qué hora es y lo resuelve como puede: a las once de la noche
    saludaba con "buenos días" mientras la pantalla —que sí mira el reloj— decía "buenas
    noches". `claude_brain` ya se lo decía a Telegram; el escritorio y la voz, que son los
    canales más usados, eran justo los que no.

    La zona sale de `astimezone()`, o sea del sistema operativo. Es la única señal honesta
    de dónde está el usuario que ya tenemos: no hace falta pedir permisos de ubicación ni
    consultar a nadie por internet para saber que son las 22:30 en su huso.
    """
    from datetime import datetime

    ahora = datetime.now().astimezone()
    zona = ahora.strftime("%Z") or ahora.strftime("%z")
    # El dia se traduce a mano y no con `%A`: `strftime` usa la locale del proceso, que en
    # Windows suele ser la del sistema en ingles, y el agente hablaria de "Friday" en
    # mitad de una frase en espanol. Cambiar la locale global del proceso por un nombre de
    # dia seria mucho peor: afecta a como se parsean numeros y fechas en todo el programa.
    return (f"{_DIAS[ahora.weekday()]} {ahora.strftime('%d/%m/%Y %H:%M')} "
            f"(zona horaria del equipo: {zona})")
