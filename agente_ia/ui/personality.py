import random
from datetime import datetime

#: Coletillas del saludo inicial. La parte horaria YA NO vive acá.
#:
#: Antes esto eran cinco frases completas y `get_random_greeting()` elegía una al azar —
#: la primera empezaba con "Buenos dias". A las once de la noche, la pantalla saludaba con
#: "Buenas noches" (lo calcula de la hora local) y el agente contestaba "Buenos días" en la
#: misma ventana. No era una diferencia de opinión: eran dos relojes, y uno no existía.
#:
#: Ahora la mitad horaria la pone `get_time_based_greeting()`, la MISMA función y las
#: mismas franjas que usa `ui/webview/frontend/js/app.js`. Lo que varía es solo la
#: coletilla, que es donde la variedad se nota sin poder equivocarse.
GREETING_TAILS = [
    "Todos los sistemas están operativos.",
    "¿En qué puedo asistirle?",
    "Sistemas en línea y listos.",
    "Siempre es un placer. ¿Qué necesita?",
    "Sistemas verificados. Estoy a su disposición.",
]

ADDRESS = "Senor"

ACKNOWLEDGEMENTS = [
    "Enseguida, Senor.",
    "Como usted ordene, Senor.",
    "Muy bien, Senor. Ejecutando ahora.",
    "Hecho, Senor. Algo mas en que pueda servirle?",
    "Perfectamente, Senor. Iniciando ahora.",
    "Comprendido, Senor. Ya mismo."
]

ERROR_MESSAGES = [
    "Lo lamento, Senor. He encontrado una limitacion en mis protocolos.",
    "Senor, me temo que no puedo completar esa accion.",
    "Mis disculpas, Senor. Se ha producido un error en el proceso.",
    "Senor, he intentado ejecutar su orden pero el sistema no responde."
]

FORMAL_PREFIXES = [
    "Enseguida,",
    "Como usted ordene,",
    "Ejecutado,",
    "Operacion completada,",
    "Segun mis sistemas,",
    "He finalizado la tarea,",
    "Tal como solicito,"
]

REPORT_STARTS = [
    "Todos los sistemas indican que",
    "He confirmado que",
    "Puedo informarle que",
    "Los registros confirman que",
]

JARVIS_CLOSINGS = [
    "Todo en orden, Senor.",
    "Sistemas estables, Senor.",
    "Operacion exitosa, Senor.",
    "A su disposicion, Senor.",
    "Sin novedades, Senor.",
]


def format_response(text: str, is_error: bool = False) -> str:
    if not text:
        return random.choice(ACKNOWLEDGEMENTS)

    words = text.split()
    is_greeting = any(w in text.lower() for w in ["hola", "buen", "saludos", "buenos"])
    if len(words) < 4 and is_greeting:
        return get_random_greeting()

    if is_error:
        prefix = random.choice(ERROR_MESSAGES)
        return f"{prefix}\nDetalle: {text}"

    style = random.randint(0, 4)

    if style == 0:
        prefix = random.choice(FORMAL_PREFIXES)
        return f"{prefix} {ADDRESS}. {text}"

    elif style == 1:
        lower = text[0].lower() + text[1:] if text else text
        return f"{random.choice(REPORT_STARTS)} {lower}, {ADDRESS}."

    elif style == 2:
        main = text.rstrip(".")
        return f"{main}, {ADDRESS}."

    elif style == 3:
        main = text.rstrip(".")
        return f"{main}. {random.choice(JARVIS_CLOSINGS)}"

    else:
        return f"{text}, {ADDRESS}. {random.choice(JARVIS_CLOSINGS)}"


def get_random_greeting():
    """Return el saludo inicial: la franja horaria real, con una coletilla al azar."""
    from core.address import vocative

    return f"{get_time_based_greeting()}{vocative()}. {random.choice(GREETING_TAILS)}"


def get_time_based_greeting(display_name: str = "") -> str:
    """Return a greeting based on the current hour (REQ-008/CA-03/CA-04).

    Rangos exactos de CA-03: "Buenas noches" 19:00–04:59 (envuelve medianoche, se
    evalúa primero por ser el rango explícito más específico), "Buenos días" 05:00–11:59,
    "Buenas tardes" 12:00–18:59. Si `display_name` está vacío, retorna el saludo sin coma
    final (p. ej. "Buenos días" en vez de "Buenos días, "). Independiente de
    `get_random_greeting()` (que se conserva intacta para voz/CLI).
    """
    hour = datetime.now().hour
    if hour >= 19 or hour < 5:
        base = "Buenas noches"
    elif hour < 12:
        base = "Buenos días"
    else:
        base = "Buenas tardes"
    return f"{base}, {display_name}" if display_name else base
