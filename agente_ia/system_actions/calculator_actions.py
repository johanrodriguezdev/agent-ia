"""
calculator_actions.py
Operaciones matemáticas reales sin simulación de teclado ni mouse.
También abre la calculadora nativa de Windows si se requiere.
"""

import subprocess
import math
import operator


# ─────────────────────────────────────────────────────────────────
#  APERTURA DE CALCULADORA NATIVA
# ─────────────────────────────────────────────────────────────────

def open_calculator() -> str:
    """Abre la Calculadora de Windows usando subprocess (sin pyautogui)."""
    try:
        subprocess.Popen("calc.exe")
        return "Calculadora de Windows abierta."
    except Exception as e:
        return f"No pude abrir la calculadora: {e}"


# ─────────────────────────────────────────────────────────────────
#  OPERACIONES MATEMÁTICAS EXACTAS (Python puro)
# ─────────────────────────────────────────────────────────────────

def multiply(a: float, b: float) -> str:
    """Multiplica dos números y devuelve el resultado formateado."""
    result = a * b
    # Mostrar sin decimales si el resultado es entero
    if result == int(result):
        return f"{int(a)} × {int(b)} = {int(result)}"
    return f"{a} × {b} = {result}"

def add(a: float, b: float) -> str:
    result = a + b
    return f"{a} + {b} = {result if result != int(result) else int(result)}"

def subtract(a: float, b: float) -> str:
    result = a - b
    return f"{a} - {b} = {result if result != int(result) else int(result)}"

def divide(a: float, b: float) -> str:
    if b == 0:
        return "Error: no es posible dividir entre cero."
    result = a / b
    return f"{a} ÷ {b} = {result if result != int(result) else int(result)}"

def power(base: float, exp: float) -> str:
    result = base ** exp
    return f"{base} ^ {exp} = {result if result != int(result) else int(result)}"

def square_root(n: float) -> str:
    if n < 0:
        return "Error: no se puede calcular la raíz cuadrada de un número negativo."
    result = math.sqrt(n)
    return f"√{n} = {result if result != int(result) else int(result)}"

def modulo(a: float, b: float) -> str:
    if b == 0:
        return "Error: módulo con divisor cero."
    result = a % b
    return f"{int(a)} mod {int(b)} = {int(result)}"

def percentage(value: float, percent: float) -> str:
    result = (value * percent) / 100
    return f"El {percent}% de {value} es {result:.2f}"

def evaluate_expression(expression: str) -> str:
    """
    Evalúa una expresión matemática en string de forma segura.
    Solo permite números, operadores básicos y funciones math.
    """
    # Whitelist: solo permite caracteres seguros
    allowed = set("0123456789+-*/().%^ ")
    if not all(c in allowed for c in expression):
        return "Expresión no permitida por seguridad."
    # Reemplazamos ^ por ** para consistencia
    expr_clean = expression.replace("^", "**")
    try:
        result = eval(expr_clean, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except Exception as e:
        return f"No pude evaluar '{expression}': {e}"
