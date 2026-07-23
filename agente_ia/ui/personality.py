import random

GREETINGS = [
    "Buenos dias, Senor. Todos los sistemas estan operativos.",
    "A su servicio, Senor. En que puedo asistirle?",
    "Bienvenido, Senor. Sistemas en linea y listos.",
    "Senor, siempre es un placer. Que necesita?",
    "Sistemas verificados. Estoy a su disposicion, Senor."
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
        return random.choice(GREETINGS)

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
    return random.choice(GREETINGS)
