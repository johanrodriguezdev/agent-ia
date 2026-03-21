"""
task_planner.py
Analiza una instrucción compleja en lenguaje natural y genera un plan
de ejecución compuesto por pasos del ACTION_REGISTRY.

El planificador usa un sistema de reglas (pattern matching) para traducir
frases a acciones concretas sin necesidad de un LLM externo.
"""

import re
from nlp.parser import clean_text
from agents.action_registry import list_action_names


# ─────────────────────────────────────────────────────────────────
#  PLANTILLAS DE PLANES PREDEFINIDOS
#  Clave: patrón regex que coincide con la instrucción del usuario.
#  Valor: lista de pasos (cada paso es un dict con "action" y "params").
# ─────────────────────────────────────────────────────────────────
PLAN_TEMPLATES = [

    # ── Bloc de notas + Escribir texto + Guardar ──────────────────
    {
        "patterns": [
            r"crea.*documento.*sobre (.*)",
            r"escribe.*texto.*sobre (.*)",
            r"redacta.*documento.*sobre (.*)",
            r"escribe.*resumen.*de (.*)",
            r"crea.*resumen.*de (.*)",
        ],
        "plan_builder": lambda m: [
            {"action": "open_notepad",        "params": {}},
            {"action": "wait_seconds",         "params": {"seconds": 1.5}},
            {"action": "generate_ai_summary",  "params": {"topic": m.group(1).strip()}, "store_as": "summary_text"},
            {"action": "write_text",           "params": {}, "use_stored": "summary_text"},
            {"action": "save_file_desktop",    "params": {"filename": f"Resumen_{m.group(1).strip().replace(' ','_')}.txt"}},
        ]
    },

    # ── Captura de pantalla ───────────────────────────────────────
    {
        "patterns": [
            r"toma.*captura.*de pantalla",
            r"captura.*pantalla",
            r"screenshot",
            r"fotografía.*pantalla",
        ],
        "plan_builder": lambda m: [
            {"action": "take_screenshot", "params": {"delay": 1.5}},
        ]
    },

    # ── Abrir navegador y buscar ───────────────────────────────────
    {
        "patterns": [
            r"busca.*en.*google\s+(.*)",
            r"busca.*internet\s+(.*)",
            r"abre.*google.*busca\s+(.*)",
            r"googleame\s+(.*)",
        ],
        "plan_builder": lambda m: [
            {"action": "search_google", "params": {"query": m.group(1).strip()}},
        ]
    },

    # ── Abrir URL específica ──────────────────────────────────────
    {
        "patterns": [
            r"abre\s+(https?://\S+)",
            r"navega a\s+(https?://\S+)",
            r"ve a\s+(https?://\S+)",
        ],
        "plan_builder": lambda m: [
            {"action": "open_url", "params": {"url": m.group(1).strip()}},
        ]
    },

    # ── Información del disco ─────────────────────────────────────
    {
        "patterns": [
            r"cuanto.*espacio.*disco",
            r"info.*disco",
            r"almacenamiento.*disco",
            r"estado.*disco",
        ],
        "plan_builder": lambda m: [
            {"action": "get_disk_info", "params": {}},
        ]
    },

    # ── Fecha y hora ──────────────────────────────────────────────
    {
        "patterns": [
            r"que.*hora.*es",
            r"dime.*fecha.*hora",
            r"fecha.*actual",
        ],
        "plan_builder": lambda m: [
            {"action": "get_current_datetime", "params": {}},
        ]
    },

    # ── Abrir aplicación genérica ─────────────────────────────────
    {
        "patterns": [
            r"abre.*calculadora",
        ],
        "plan_builder": lambda m: [
            {"action": "open_calculator", "params": {}},
        ]
    },
    {
        "patterns": [
            r"abre.*explorador",
            r"abre.*mis archivos",
        ],
        "plan_builder": lambda m: [
            {"action": "open_explorer", "params": {}},
        ]
    },
    {
        "patterns": [
            r"abre.*bloc.*notas",
            r"abre.*notepad",
        ],
        "plan_builder": lambda m: [
            {"action": "open_notepad", "params": {}},
        ]
    },

    # ── Escribir texto en app activa ───────────────────────────────
    {
        "patterns": [
            r"escribe\s+(.*)\s+en la pantalla",
            r"tipea\s+(.*)",
            r"escribe en el teclado\s+(.*)",
        ],
        "plan_builder": lambda m: [
            {"action": "write_text", "params": {"text": m.group(1).strip()}},
        ]
    },
]


class TaskPlanner:
    """
    Analiza una instrucción en lenguaje natural y genera un plan de acción
    compuesto por una lista ordenada de pasos del ACTION_REGISTRY.
    """

    def generate_plan(self, instruction: str) -> list[dict]:
        """
        Devuelve una lista de steps. Cada step es:
          {
            "action":     str,       (nombre de la acción en action_registry)
            "params":     dict,      (parámetros a pasar a la función)
            "store_as":   str | None (guardar resultado para uso posterior)
            "use_stored": str | None (reemplazar params['text'] con resultado guardado)
          }
        Retorna [] si no se encontró un plan.
        """
        clean = clean_text(instruction)
        plan  = self._match_templates(clean)

        if plan:
            return plan

        # Fallback: si mencionan solo una acción conocida, la ejecutamos directa
        for action_name in list_action_names():
            if action_name.replace("_", " ") in clean:
                return [{"action": action_name, "params": {}}]

        return []

    def _match_templates(self, text: str) -> list[dict]:
        for template in PLAN_TEMPLATES:
            for pattern in template["patterns"]:
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    try:
                        steps = template["plan_builder"](m)
                        # Normalizamos cada step para que tenga las claves opcionales
                        for step in steps:
                            step.setdefault("store_as",   None)
                            step.setdefault("use_stored", None)
                        return steps
                    except Exception as e:
                        print(f"[Planner] Error construyendo plan: {e}")
                        return []
        return []

    def describe_plan(self, plan: list[dict]) -> str:
        """Formatea el plan como texto legible para el usuario."""
        if not plan:
            return "No pude generar un plan para esa instrucción."
        lines = ["📋 Plan de Autopilot:"]
        for i, step in enumerate(plan, 1):
            params_str = ", ".join(f"{k}={v}" for k, v in step["params"].items()) if step["params"] else "—"
            lines.append(f"  {i}. {step['action']}  ({params_str})")
        return "\n".join(lines)
