"""
personality.py
Módulo encargado de dar la personalidad al asistente.
Transforma el texto crudo en una respuesta formal y educada.
"""

import random

# Lista de saludos y despedidas
GREETINGS = [
    "A su servicio, Señor.",
    "Buen día, Señor. ¿En qué puedo asistirle hoy?",
    "Sistemas en línea. Listo para sus órdenes, Señor.",
    "Siempre un placer verle, Señor.",
    "Panel de control activo. ¿Qué necesita, Señor?"
]

ADRESSES = ["Señor", "Caballero", "Señor Tony"] # Tony como guiño opcional

ACKNOWLEDGEMENTS = [
    "Entendido, Señor.",
    "Procesando su solicitud de inmediato.",
    "A la orden, Señor. Ejecutando ahora.",
    "Muy bien, Señor. Permítame un segundo.",
    "Sistemas trabajando en ello.",
    "Iniciando secuencia, Señor."
]

ERROR_MESSAGES = [
    "Lo lamento, Señor. He encontrado un inconveniente en los protocolos.",
    "Parece que hay una falla en la ejecución, Señor. Permítame revisar.",
    "Señor, mis disculpas, pero no he podido completar esa tarea.",
    "Error de sistema detectado. No ha sido posible procesar la orden."
]

def format_response(text: str, is_error: bool = False) -> str:
    """
    Toma un texto de salida del dispatcher/handler y lo envuelve
    en una estructura formal de Jarvis.
    """
    if not text:
        return random.choice(ACKNOWLEDGEMENTS)
    
    # Si el texto ya parece un saludo o algo conversacional corto, lo dejamos pasar
    if len(text.split()) < 3 and any(word in text.lower() for word in ["hola", "buen", "saludos"]):
        return random.choice(GREETINGS)

    # Si es un error
    if is_error:
        prefix = random.choice(ERROR_MESSAGES)
        return f"{prefix}\nDetalle: {text}"

    # Para respuestas normales
    address = random.choice(ADRESSES)
    
    # Estructura formal: Prefijo + Contenido + "Señor"
    formal_prefixes = [
        "Por supuesto,",
        "Como usted ordene,",
        "Hecho,",
        "Aquí tiene los resultados,",
        "Según mis registros,",
        "He completado la tarea,"
    ]
    
    prefix = random.choice(formal_prefixes)
    
    # Si la respuesta es multilínea o muy larga, la presentamos más estructurada
    if "\n" in text or len(text) > 100:
        return f"{prefix} {address}:\n\n{text}\n\n¿Desea algo más?"
    
    # Respuesta corta
    return f"{prefix} {address}. {text}"

def get_random_greeting():
    return random.choice(GREETINGS)
