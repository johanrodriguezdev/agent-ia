import logging
import re
import threading

from intent.intentions import Intent
from nlp.parser import clean_text, normalize_numbers, extract_numbers

logger = logging.getLogger(__name__)

#: El clasificador se construye la PRIMERA VEZ que hace falta, no al importar el modulo.
#:
#: `intent/ai_classifier.py` arrastra scikit-learn, y eso son 8.6 de los 13 segundos que
#: tardaba el arranque medidos con `python -X importtime`. `main.py` importa este modulo
#: para registrar `classify_command` en el orquestador, asi que la ventana no aparecia
#: hasta que sklearn terminara de cargar.
#:
#: Lo mas absurdo es que `core/warmup.py` ya existia precisamente para esto —carga el
#: clasificador en un hilo mientras el usuario abre la ventana y lee el saludo— y no servia
#: de nada: para cuando ese hilo arrancaba, el import de `main.py` ya lo habia pagado todo
#: por adelantado y en el hilo principal.
#:
#: Y desde que el modelo lee primero (`core/resolution.py::RESOLVERS`), el clasificador ya
#: ni siquiera esta en el camino de cada mensaje: solo lo usan la herramienta `dispatcher`
#: y el respaldo sin conexion. Cargarlo antes de mostrar la ventana era pagar por
#: adelantado algo que muchas sesiones no llegan a usar.
_ai_system = None

#: Protege la construccion. `core/warmup.py` lo carga desde un hilo de fondo mientras el
#: usuario abre la ventana; si justo entonces el usuario dicta algo, dos hilos entrarian a
#: la vez y cada uno leeria el pickle por su cuenta. No corrompe nada, pero es trabajo
#: duplicado en el peor momento — el arranque.
_carga_lock = threading.Lock()


def _sistema():
    """Return el clasificador, construyendolo la primera vez."""
    global _ai_system
    if _ai_system is None:
        with _carga_lock:
            if _ai_system is None:      # otro hilo pudo construirlo mientras se esperaba
                from intent.ai_classifier import IntentClassifierSystem

                _ai_system = IntentClassifierSystem()
    return _ai_system


def __getattr__(name):
    """Deja que `intent.classifier.ai_system` siga existiendo desde fuera.

    Es lo que usan las pruebas para sustituir `predict()`. Al hacerlo, `monkeypatch` fija
    el atributo de verdad en el modulo, que a partir de ahi tapa a este `__getattr__` — y
    `_sistema()` devuelve la MISMA instancia que se parcheo, porque es la que se construyo
    aca dentro.
    """
    if name == "ai_system":
        return _sistema()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

#: Operadores tal como sobreviven a `clean_text()`, que borra TODA la puntuacion:
#: "5 * 3" llega como "5 3" y "0 - 12 dias" como "0 12 dias". Por eso solo se buscan las
#: palabras — los `\\*`, `\\+` y `/` que tenian los patrones viejos no podian coincidir
#: nunca. Las alternativas van de la mas larga a la mas corta: "dividido entre" tiene que
#: probarse antes que "entre", y "multiplicado por" antes que "por".
_OPERADORES_CALCULO = (
    ("divide",   r"dividido entre|dividida entre|dividido por|divididos entre|entre"),
    ("multiply", r"multiplicado por|multiplicada por|por|x"),
    ("add",      r"sumado a|mas"),
    ("subtract", r"restado de|menos"),
)


def _extraer_calculo(clean: str) -> dict:
    """Return `{operation, a, b}` si el texto tiene una operacion de verdad, o `{}`.

    Se busca la forma `numero OPERADOR numero`, que es como se dice una cuenta en voz
    alta, en vez de exigir que el verbo venga primero. Los patrones viejos pedian
    `(divid).*?numero.*?entre.*?numero`, asi que "cuanto es 100 dividido entre 4" —con el
    numero ANTES del verbo— no coincidia y caia en el fallback, que respondia 400.
    """
    for operacion, operadores in _OPERADORES_CALCULO:
        m = re.search(rf"([\d.,]+)\s+(?:{operadores})\s+([\d.,]+)", clean)
        if m:
            try:
                return {
                    "operation": operacion,
                    "a": float(m.group(1).replace(",", ".")),
                    "b": float(m.group(2).replace(",", ".")),
                }
            except ValueError:
                continue    # "1.2.3" y companiia: no es un numero, se prueba el siguiente
    return {}


def classify_command(text: str) -> tuple[Intent, dict]:
    """
    Motor de IA para interpretar comandos.
    1. Normaliza texto (acentos, números en letras)
    2. Usa el modelo ML predictivo (TF-IDF + SVM) para hallar la intención
    3. Extrae entidades y parámetros con Regex
    """
    clean   = clean_text(text)
    clean_n = normalize_numbers(clean)   # aplica conversión de letras a números
    
    # 1. Clasificación ML con texto normalizado
    intent = _sistema().predict(clean_n)
    params = {}
    
    # 2. Intentar extracción con Plugins Dinámicos (Skills)
    try:
        from skills.skill_manager import skill_manager
        if skill_manager.handles_intent(intent):
            params = skill_manager.extract_params(intent, text.lower().strip())
            return intent, params
    except Exception as e:
        print(f"[Aviso] Fallo en la extracción modular de skill: {e}")

    # 3. Extracción de Entidades y Parámetros (Legacy)
    if intent == Intent.OPEN_APP:
        # Extrae después de "abre", "inicia", "ejecuta", etc.
        match = re.search(r'\b(abre|inicia|ejecuta|arranca)\s+(?:el\s+|la\s+|aplicacion(?: de)?\s+)?(.*)', clean)
        if match and match.group(2):
            params["app_name"] = match.group(2).strip()
        else:
            params["app_name"] = clean

    elif intent == Intent.CLOSE_APP:
        # Extrae después de "cierra", "mata", "termina", "detén", etc.
        match = re.search(r'\b(cierra|cerrar|mata|termina|deten|detén|finaliza|para|apaga|quita|salte de)\s+(?:el\s+(?:programa\s+|proceso\s+)?|la\s+(?:aplicacion\s+)?|del?\s+)?(.*)', clean)
        if match and match.group(2):
            params["app_name"] = match.group(2).strip()
        else:
            params["app_name"] = clean

    elif intent == Intent.SEARCH_WEB:
        # Extrae el query tras un prefijo de búsqueda
        match = re.search(r'\b(busca|buscar|googleame)\s+(?:en\s+google\s+|en\s+internet\s+|sobre\s+|que es\s+)?(.*)', clean)
        if match and match.group(2):
             params["query"] = match.group(2).strip()
        else:
             params["query"] = clean
             
    elif intent == Intent.WIKIPEDIA_SUMMARY:
        # Extrae de qué se quiere el resumen (Ej: quien fue albert einstein -> albert einstein)
        match = re.search(r'\b(que es|quien fue|quien es|resumen de|sobre|dime sobre|wikipedia|explicame sobre|dime quien es)\s+((?:el\s+|la\s+|los\s+|las\s+)?.*)', clean)
        if match and match.group(2):
            params["query"] = match.group(2).strip()
        else:
            params["query"] = clean
            
    elif intent == Intent.RECALL_MEMORY:
        # Poda conectores hasta aislar la materia que queremos recordar de BD
        match = re.search(r'\b(acuerdas de|dije sobre|respondiste acerca de|recuerdas sobre|memoria|hablamos de|que era|dijimos de|dijiste de)\s+(.*)', clean)
        if match and match.group(2):
            params["query"] = match.group(2).strip()
        else:
            params["query"] = clean
            
    elif intent == Intent.TEACH_COMMAND:
        # Este no se asocia de forma léxica en el clasificador porque dispara una conversación de múltiples 
        # giros (Multi-turn dialogue) implementada en main.py. Solo le pasamos señal pura.
        pass
        
    elif intent == Intent.PC_CLICK:
        # Extrae números de las coordenadas. Ej: "haz clic en 250 500" -> x=250, y=500
        matches = re.findall(r'\d+', clean)
        if len(matches) >= 2:
            params["x"] = int(matches[0])
            params["y"] = int(matches[1])
            
    elif intent == Intent.PC_TYPE:
        # Extraer texto final para escribirlo
        res = re.search(r'\b(?:escribe|tipea|teclado|texto)\s+(.*)', clean)
        if res and res.group(1):
            params["text"] = res.group(1).strip()
            
    elif intent == Intent.PC_SCROLL:
        # Localiza arriba o abajo
        if "arriba" in clean or "up" in clean or "sube" in clean:
            params["direction"] = "arriba"
        elif "abajo" in clean or "down" in clean or "baja" in clean:
            params["direction"] = "abajo"
        else:
            params["direction"] = "abajo" # por defecto fallback
             
    elif intent == Intent.OPEN_FOLDER:
        match = re.search(r'\b(abre|muestra|ve a)\s+(?:la\s+carpeta(?: de)?\s+|el\s+directorio(?: de)?\s+|mis\s+|mi\s+)?(.*)', clean)
        if match and match.group(2):
            params["path"] = match.group(2).strip()
        else:
            params["path"] = "."
            
    elif intent == Intent.LIST_FILES:
        match = re.search(r'\b(en\s+|de\s+)(?:la\s+carpeta\s+|mi\s+|mis\s+)?(.*)', clean)
        if match and match.group(2):
            params["path"] = match.group(2).strip()
        else:
            params["path"] = "."
            
    elif intent == Intent.CREATE_FILE:
        match = re.search(r'\b(?:llamado\s+|archivo(?: de texto)?\s+)(.*)', clean)
        if match and match.group(1):
            params["filename"] = match.group(1).strip()
        else:
            params["filename"] = "documento_nuevo.txt"

    elif intent == Intent.CALCULATE:
        calculo = _extraer_calculo(clean)
        if not calculo:
            # Ninguna operacion reconocible: no hay cuenta que hacer. UNKNOWN hace que
            # `core/resolution.py::_try_intent()` deje pasar la frase al LLM, el unico que
            # puede decidir si eso era una cuenta o una consulta.
            #
            # Antes habia aca un fallback que tomaba dos numeros CUALESQUIERA del texto y
            # asumia una multiplicacion. Un JSON de colores para ciclos de cosecha
            # ("ini": 0, "fin": 12, ...) se contestaba con "0 x 12 = 0": inventaba la
            # operacion, inventaba los operandos, y el mensaje nunca llegaba al modelo.
            # Adivinar era peor que no entender.
            return Intent.UNKNOWN, {}
        params.update(calculo)

    elif intent == Intent.SEARCH_FILES:
        # "busca archivos llamados reporte en documentos"
        m = re.search(r'(?:archivos?|busca).*?(?:llamad[oa]s?|con nombre|que se llame[n]?)\s+([\w.]+)(?:.*?en\s+(.+))?', clean)
        if m:
            params["name"] = m.group(1).strip()
            params["path"] = m.group(2).strip() if m.group(2) else "~"
        else:
            nums_out = re.findall(r'\b([\w.]+\.\w{2,4})\b', clean)
            params["name"] = nums_out[0] if nums_out else clean
            params["path"] = "~"

    elif intent == Intent.FOLDER_SIZE:
        m = re.search(r'(?:cuanto pesa|tamaño de|tamaño del?|peso de)\s+(?:la\s+carpeta\s+)?(.+)', clean)
        params["path"] = m.group(1).strip() if m else "~"

    elif intent == Intent.FIND_LARGEST:
        m = re.search(r'(?:carpeta|carpetas).*?(?:grande|pesa).*?(?:en\s+)?(.+)?', clean)
        params["path"] = m.group(1).strip() if (m and m.group(1)) else "~"

    elif intent in (Intent.SYSTEM_INFO, Intent.CPU_INFO, Intent.RAM_INFO):
        pass  # No requieren parámetros adicionales

    return intent, params
