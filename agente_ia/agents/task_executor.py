"""
task_executor.py
Ejecuta un plan generado por TaskPlanner paso a paso, manejando
el estado compartido entre pasos (ej: texto generado → escribir en app).
"""

import time
from agents.action_registry import get_action, execute_action


class StepResult:
    """Encapsula el resultado de un paso individual del plan."""
    def __init__(self, step_index: int, action: str, success: bool, output: str):
        self.step_index = step_index
        self.action     = action
        self.success    = success
        self.output     = output

    def __repr__(self):
        status = "✅" if self.success else "❌"
        return f"  {status} Paso {self.step_index} [{self.action}]: {self.output}"


class TaskExecutor:
    """
    Ejecuta cada paso de un plan de Autopilot de forma secuencial.
    Mantiene un estado interno que permite pasar resultados de un paso al siguiente.
    """

    def execute(self, plan: list[dict], on_step_done=None, channel=None) -> str:
        """
        Ejecuta todos los pasos del plan.

        Args:
            plan:         Lista de steps del TaskPlanner.
            on_step_done: Callback opcional que recibe (step_index, step_result) en tiempo real.
            channel:      Canal real de la invocación (desktop/telegram/discord/voice/etc.),
                           propagado al gate de seguridad de cada paso.

        Retorna:
            Resumen completo de la ejecución como string.
        """
        if not plan:
            return "El plan está vacío, no hay nada que ejecutar."

        results: list[StepResult] = []
        # Estado compartido entre pasos (para pasar textos generados, etc.)
        shared_context: dict = {}

        print(f"\n[🤖 AUTOPILOT] Iniciando ejecución de {len(plan)} paso(s)...\n")

        for i, step in enumerate(plan, 1):
            action_name = step.get("action", "")
            params      = dict(step.get("params", {}))      # Copia mutable
            store_as    = step.get("store_as")
            use_stored  = step.get("use_stored")

            action_info = get_action(action_name)
            if not action_info:
                result = StepResult(i, action_name, False, f"Acción '{action_name}' no reconocida.")
                results.append(result)
                if on_step_done:
                    on_step_done(i, result)
                continue

            # Si el paso debe usar el resultado de un paso anterior como parámetro text
            if use_stored and use_stored in shared_context:
                params["text"] = shared_context[use_stored]

            try:
                print(f"  ▶ Paso {i}/{len(plan)}: {action_name}  params={params}")
                output = execute_action(action_name, params, channel=channel)

                # Si el paso necesita guardar su resultado
                if store_as:
                    shared_context[store_as] = output

                result = StepResult(i, action_name, True, str(output)[:120])
            except Exception as e:
                result = StepResult(i, action_name, False, f"Error: {e}")

            results.append(result)
            if on_step_done:
                on_step_done(i, result)

            # Pequeña pausa entre pasos para no saturar el SO
            time.sleep(0.3)

        # Construir resumen final
        ok    = sum(1 for r in results if r.success)
        total = len(results)
        lines = [f"\n[🤖 AUTOPILOT] Ejecución completada: {ok}/{total} pasos exitosos."]
        lines += [str(r) for r in results]

        # Si el último paso generó output real (resumen, información), añadirlo
        if results and results[-1].success and results[-1].output:
            lines.append(f"\n📄 Resultado final: {results[-1].output}")

        return "\n".join(lines)

    def execute_single(self, action_name: str, params: dict = {}, channel=None) -> str:
        """Ejecuta una sola acción del registro directamente."""
        action_info = get_action(action_name)
        if not action_info:
            return f"La acción '{action_name}' no existe en el registro."
        try:
            return execute_action(action_name, params, channel=channel)
        except Exception as e:
            return f"Error al ejecutar '{action_name}': {e}"
