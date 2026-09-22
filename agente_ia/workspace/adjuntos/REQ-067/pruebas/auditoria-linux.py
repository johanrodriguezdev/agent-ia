"""Clasifica las herramientas del agente según su dependencia de Windows."""
import inspect
import re
import sys

sys.path.insert(0, r"C:\Users\WHOAMI\Documents\Apps\agent-ia\agente_ia")

from agents import tool_registry as TR

# Módulos que hoy solo saben hablar con Windows (verificado leyendo el código).
MODULOS_WINDOWS = {
    "ui_tree": "árbol de accesibilidad UI Automation",
    "navegador": "control del navegador por UI Automation",
    "ocr": "OCR de Windows.Media.Ocr",
    "system_ctrl": "taskkill / tasklist / shutdown de Windows",
    "system_actions": "explorer.exe / cmd.exe",
    "window_tracker": "ventanas por PowerShell",
    "pc_controller": "apagar/reiniciar Windows",
    "terminal_session": "PowerShell sobre ConPTY",
    "workspace_run": "comandos vía PowerShell",
    "action_registry": "rutas C:\\Program Files",
    "documentos": "PDF y temas con Office COM (tiene respaldo sin Office)",
}

tools = TR.get_all_tools() if hasattr(TR, "get_all_tools") else None
if tools is None:
    nombres = re.findall(r'name="([a-z0-9_]+)"', open(TR.__file__, encoding="utf-8").read())
    tools = [TR.get_tool(n) for n in dict.fromkeys(nombres)]
    tools = [t for t in tools if t is not None]

print(f"Herramientas registradas: {len(tools)}\n")
clasificadas = {}
for t in tools:
    try:
        fuente = inspect.getsource(t.invoke)
    except (OSError, TypeError):
        fuente = ""
    tocados = sorted({m for m in MODULOS_WINDOWS if re.search(rf"\b{m}\b", fuente)})
    clasificadas.setdefault(tuple(tocados), []).append(t.name)

afectadas = []
for modulos, nombres in sorted(clasificadas.items(), key=lambda kv: (len(kv[0]), kv[0])):
    etiqueta = ", ".join(modulos) if modulos else "— sin dependencia de Windows —"
    print(f"[{etiqueta}]  ({len(nombres)})")
    print("   " + ", ".join(sorted(nombres)))
    if modulos:
        afectadas += nombres
    print()

print(f"RESUMEN: {len(afectadas)} de {len(tools)} herramientas tocan un módulo de Windows.")
print("Afectadas:", ", ".join(sorted(afectadas)))
