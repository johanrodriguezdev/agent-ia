import re
from intent.intentions import Intent
from intent.ai_classifier import IntentClassifierSystem
from nlp.parser import clean_text, normalize_numbers, extract_numbers

# Instancia global del sistema de IA predictivo
ai_system = IntentClassifierSystem()

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
    intent = ai_system.predict(clean_n)
    params = {}
    
    # 2. Extracción de Entidades y Parámetros
    if intent == Intent.OPEN_APP:
        # Extrae después de "abre", "inicia", "ejecuta", etc.
        match = re.search(r'\b(abre|inicia|ejecuta|arranca)\s+(?:el\s+|la\s+|aplicacion(?: de)?\s+)?(.*)', clean)
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
        # Extraer operandos y operación: "multiplica 40 por 60", "suma 5 más 3"
        m = re.search(r'(multiplic|mul).*?([\d,.]+).*?(?:por|x|\*).*?([\d,.]+)', clean)
        if m:
            params["operation"] = "multiply"
            params["a"] = float(m.group(2).replace(',', '.'))
            params["b"] = float(m.group(3).replace(',', '.'))
        else:
            m = re.search(r'(sum|add).*?([\d,.]+).*?(?:mas|más|\+).*?([\d,.]+)', clean)
            if m:
                params["operation"] = "add"
                params["a"] = float(m.group(2).replace(',', '.'))
                params["b"] = float(m.group(3).replace(',', '.'))
            else:
                m = re.search(r'(rest|subtract).*?([\d,.]+).*?(?:menos|-).*?([\d,.]+)', clean)
                if m:
                    params["operation"] = "subtract"
                    params["a"] = float(m.group(2).replace(',', '.'))
                    params["b"] = float(m.group(3).replace(',', '.'))
                else:
                    m = re.search(r'(divid).*?([\d,.]+).*?(?:entre|/).*?([\d,.]+)', clean)
                    if m:
                        params["operation"] = "divide"
                        params["a"] = float(m.group(2).replace(',', '.'))
                        params["b"] = float(m.group(3).replace(',', '.'))
                    else:
                        # Fallback: buscar dos números y asumir multiplicación
                        nums = re.findall(r'[\d,.]+', clean)
                        if len(nums) >= 2:
                            params["operation"] = "multiply"
                            params["a"] = float(nums[0].replace(',', '.'))
                            params["b"] = float(nums[1].replace(',', '.'))

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
