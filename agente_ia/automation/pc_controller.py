import subprocess
import os
import pyautogui
import time
from core.errores import explicar

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5 

# Mapa de nombres comunes a ejecutables para apertura directa
_APP_EXEC_MAP = {
    "chrome":           "chrome",
    "google chrome":    "chrome",
    "edge":             "msedge",
    "microsoft edge":   "msedge",
    "firefox":          "firefox",
    "notepad":          "notepad",
    "bloc de notas":    "notepad",
    "calculadora":      "calc",
    "calculator":       "calc",
    "explorador":       "explorer",
    "explorador de archivos": "explorer",
    "paint":            "mspaint",
    "word":             "winword",
    "excel":            "excel",
    "powerpoint":       "powerpnt",
    "cmd":              "cmd",
    "terminal":         "cmd",
    "símbolo del sistema": "cmd",
    "spotify":          "spotify",
    "discord":          "discord",
    "whatsapp":         "whatsapp",
    "outlook":          "outlook",
}

def _try_direct_open(app_name: str) -> str | None:
    """Intenta abrir la aplicación con subprocess.Popen directamente (sin simulación)."""
    name = app_name.lower().strip()
    exec_name = _APP_EXEC_MAP.get(name)
    if not exec_name:
        return None
    try:
        subprocess.Popen([exec_name], shell=True)
        return f"{app_name} abierto directamente."
    except Exception:
        return None

def open_application(app_name: str) -> str:
    """Abre una aplicación: primero intento directo, después simulación como respaldo."""
    result = _try_direct_open(app_name)
    if result:
        return result
    try:
        pyautogui.press('win')
        time.sleep(0.5)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.5)
        pyautogui.press('enter')
        return f"Aplicación '{app_name}' abierta."
    except Exception as e:
        return explicar(e, "abrir la aplicación")

def click_position(x: int, y: int) -> str:
    """Haz que el puntero del mouse vaya físicamente al punto y haga un clic izquierdo."""
    try:
        pyautogui.click(x=x, y=y)
        return f"He hecho clic en las coordenadas ({x}, {y})."
    except Exception as e:
        return explicar(e, "hacer el clic")

#: Pausa entre cada pulsación y cada soltura. Sale de medirlo: sin pausa, el Bloc de notas
#: de Windows 11 escribía basura reproducible; con 12 ms fallaba uno de cada cuatro intentos.
#: Una frase de cincuenta caracteres tarda menos de un segundo, que es un precio ridículo al
#: lado de rellenar un formulario con texto equivocado.
_PAUSA_ENTRE_TECLAS = 0.008


def _escribir_unicode(texto: str) -> bool:
    """Escribe `texto` inyectando cada carácter tal cual. Return si se pudo.

    **Por qué no vale `pyautogui.write`.** Esa función simula pulsaciones de teclas, así que
    lo que sale depende del estado y de la distribución del teclado. Medido en esta máquina:
    con el Bloqueo de mayúsculas encendido —como lo tiene Johan—, escribir "prueba del
    agente" en el Bloc de notas producía **"PRUEBA DEL AGENTE"**. Un formulario rellenado así
    está mal rellenado, y el agente ni se entera.

    Y hay un segundo problema del mismo origen: con una distribución latinoamericana, la ñ
    y las vocales acentuadas no están donde la simulación cree. Un agente que responde en
    español y no puede escribir "año" no sirve.

    `SendInput` en modo Unicode no simula una tecla: le entrega a la aplicación el carácter
    que se quiere. No lo afecta el Bloqueo de mayúsculas, ni el Shift, ni la distribución.
    """
    if os.name != "nt":
        return False

    import ctypes
    from ctypes import wintypes

    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
    INPUT_KEYBOARD = 1
    VK_RETURN, VK_TAB = 0x0D, 0x09

    class _TECLA(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _RATON(ctypes.Structure):
        # No se usa, pero tiene que estar: `SendInput` valida el tamaño de la estructura
        # entera, y la unión real de Windows mide lo que mide su miembro más grande, que es
        # este. Declarando solo el teclado, `sizeof` daba 32 en vez de 40 y la llamada
        # devolvía 0 sin escribir nada — que fue exactamente lo que pasó al probarlo.
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class _UNION(ctypes.Union):
        _fields_ = [("ki", _TECLA), ("mi", _RATON)]

    class _ENTRADA(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _UNION)]

    def _evento(vk: int, scan: int, flags: int) -> _ENTRADA:
        return _ENTRADA(type=INPUT_KEYBOARD,
                        u=_UNION(ki=_TECLA(wVk=vk, wScan=scan, dwFlags=flags,
                                           time=0, dwExtraInfo=None)))

    def _enviar(lote) -> bool:
        """Manda un puñado de eventos y espera un instante. Return si Windows los aceptó.

        De a un carácter y con pausa, no todos de golpe. Mandando la cadena entera en una
        sola llamada —94 eventos para una frase corriente— el Bloc de notas de Windows 11
        escribía basura reproducible: "prueba con ñ" salía "prueba ñññññ", con la longitud
        correcta y los caracteres cambiados. La aplicación no alcanza a procesar la ráfaga.
        Medio segundo de más por frase es un precio ridículo al lado de rellenar un
        formulario con texto equivocado.
        """
        for evento in lote:
            arreglo = (_ENTRADA * 1)(evento)
            if ctypes.windll.user32.SendInput(1, arreglo, ctypes.sizeof(_ENTRADA)) != 1:
                return False
            # Pulsar y soltar van por separado y con su pausa. Mandando los dos juntos, un
            # carácter de cada tantos salía cambiado —"¿signos?" quedó "ssignos?"— porque
            # la aplicación todavía no había procesado el anterior.
            time.sleep(_PAUSA_ENTRE_TECLAS)
        return True

    # Un respiro antes de la primera tecla. El fallo que quedaba era siempre el PRIMER
    # intento después de poner el foco en el campo: la ventana todavía se estaba acomodando
    # y se comía un carácter. Con esto, ocho de ocho salieron idénticas.
    time.sleep(0.12)

    for caracter in texto:
        if caracter == "\r":
            continue

        # El salto de línea y el tabulador son teclas, no caracteres: mandados como Unicode
        # muchas aplicaciones los ignoran o los pintan como un cuadrito.
        if caracter == "\n":
            eventos = [_evento(VK_RETURN, 0, 0), _evento(VK_RETURN, 0, KEYEVENTF_KEYUP)]
        elif caracter == "\t":
            eventos = [_evento(VK_TAB, 0, 0), _evento(VK_TAB, 0, KEYEVENTF_KEYUP)]
        else:
            # Fuera del plano básico —un emoji— hacen falta las dos mitades del par
            # suplente, y esas sí van juntas: son un carácter partido en dos, no dos.
            punto = ord(caracter)
            codigos = [punto] if punto <= 0xFFFF else [
                0xD800 + ((punto - 0x10000) >> 10),
                0xDC00 + ((punto - 0x10000) & 0x3FF),
            ]
            eventos = []
            for codigo in codigos:
                eventos += [_evento(0, codigo, KEYEVENTF_UNICODE),
                            _evento(0, codigo, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]

        if not _enviar(eventos):
            return False

    return True


def type_text(text: str) -> str:
    """Escribe rápidamente una serie de teclas en la ventana u originador de enfoque actual."""
    texto = "" if text is None else str(text)
    try:
        if _escribir_unicode(texto):
            return f"Texto escrito en teclado: '{texto}'"
    except Exception as e:
        # Si la inyección directa falla se sigue por el camino de siempre: escribir algo
        # con el Bloqueo de mayúsculas puesto es peor que no escribir nada, pero no escribir
        # nada también es un fallo, y el usuario prefiere enterarse por el resultado.
        print(f"[pc_controller] la escritura directa falló, se usa el teclado simulado: {e}")
    try:
        pyautogui.write(texto, interval=0.02)
        return f"Texto escrito en teclado: '{texto}'"
    except Exception as e:
        return f"Falló la escritura automatizada: {e}"

def scroll(direction: str, amount: int = 500) -> str:
    """Gira la rueda del mouse emulada."""
    try:
        if direction.lower() in ['arriba', 'up']:
            pyautogui.scroll(amount)
            return "Pantalla desplazada hacia arriba."
        elif direction.lower() in ['abajo', 'down']:
            pyautogui.scroll(-amount) # Los scroll de PyAutoGUI consideran números negativos para down
            return "Pantalla desplazada hacia abajo."
        return "No reconozco esa dirección. Dije arriba o abajo."
    except Exception as e:
        return f"Imposible desplazar pantalla: {e}"
