"""
executor/system_action_handlers.py
Handlers que conectan las intenciones de system_actions con las
funciones reales de los módulos system_actions/*.
"""

from system_actions import calculator_actions as calc
from system_actions import filesystem_actions as fs
from system_actions import system_info as sysinfo


# ─────────────────────────────────────────────────────────────────
#  CÁLCULOS MATEMÁTICOS
# ─────────────────────────────────────────────────────────────────

MATH_OPS = {
    "multiply":  calc.multiply,
    "add":       calc.add,
    "subtract":  calc.subtract,
    "divide":    calc.divide,
    "power":     calc.power,
    "modulo":    calc.modulo,
}

def handle_calculate(params: dict) -> str:
    operation = params.get("operation", "multiply")
    a = params.get("a")
    b = params.get("b")

    # Si el clasificador envió una expresión completa en lugar de operandos:
    expr = params.get("expression")
    if expr:
        return calc.evaluate_expression(expr)

    if a is None or b is None:
        return "Necesito dos números para realizar el cálculo. Ejemplo: 'multiplica 40 por 60'."

    fn = MATH_OPS.get(operation, calc.multiply)
    return fn(float(a), float(b))


# ─────────────────────────────────────────────────────────────────
#  SISTEMA DE ARCHIVOS
# ─────────────────────────────────────────────────────────────────

def handle_search_files(params: dict) -> str:
    name = params.get("name", "")
    path = params.get("path", "~")
    if not name:
        return "¿Qué nombre de archivo deseas buscar?"
    return fs.search_files(name, path)


def handle_folder_size(params: dict) -> str:
    path = params.get("path", "~")
    return fs.get_folder_size(path)


def handle_find_largest(params: dict) -> str:
    path  = params.get("path", "~")
    top_n = int(params.get("top_n", 5))
    return fs.find_largest_folders(path, top_n)


# ─────────────────────────────────────────────────────────────────
#  INFORMACIÓN DEL SISTEMA
# ─────────────────────────────────────────────────────────────────

def handle_system_info(params: dict) -> str:
    return sysinfo.get_system_overview()


def handle_cpu_info(params: dict) -> str:
    return sysinfo.get_cpu_info()


def handle_ram_info(params: dict) -> str:
    return sysinfo.get_ram_info()
