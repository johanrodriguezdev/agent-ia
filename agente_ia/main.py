import logging

from core.logger_setup import setup_logging
logger = setup_logging()

from core.orchestrator import orchestrator
from core.proactive_engine import proactive_engine
from core.base_agent import AgentTool
from router.dispatcher import dispatch, dispatch_as_tool
from skills.skill_manager import skill_manager
from intent.classifier import classify_command

orchestrator.register_legacy_dispatcher(dispatch)
orchestrator.register_classifier(classify_command)

orchestrator.register_tool(AgentTool(
    name="dispatcher",
    description="Ejecuta comandos directos del sistema: abrir apps, controlar volumen, hora, etc.",
    function=dispatch_as_tool
))

for tool in skill_manager.get_agent_tools():
    orchestrator.register_tool(tool)

proactive_engine.set_notify_callback(lambda msg: logger.info(f"[Proactivo] {msg}"))

# ── Registrar triggers proactivos ──────────────────────────────
class _ProactiveAssistant:
    def __init__(self):
        self.name = "ProactiveAssistant"
        self.tools = []

    def can_handle(self, task: str) -> float:
        return 0.0 if "briefing" in task.lower() or "recordatorio" in task.lower() else 0.0

    def execute(self, task: str, context: dict = None) -> str:
        from core.orchestrator import orchestrator
        return orchestrator.process_task(
            text=task,
            channel="desktop",
            user_id=(context or {}).get("user_id", "default")
        )

_proactive_assistant = _ProactiveAssistant()
proactive_engine.register_trigger(_proactive_assistant, "startup", "¿Necesita algo, Señor?")
proactive_engine.register_trigger(_proactive_assistant, "hourly", "¿Todo en orden, Señor?")
proactive_engine.register_trigger(_proactive_assistant, "daily:08:00", "Buenos días, Señor. ¿Qué necesita para hoy?")

from ui.cli import CLI
from voice.wake_word import listen_for_wake_word
from ui.personality import get_random_greeting
from config_manager import get_agent_name

def main(boot_mode=None):
    ui = CLI()
    
    # Iniciar engine proactivo
    proactive_engine.start()
    
    # Saludo inicial al conectar los sistemas
    ui.display_output(get_random_greeting(), read_aloud=True)
    
    while True:
        if boot_mode:
            choice = boot_mode
            boot_mode = None
        else:
            choice = ui.get_input_method()
        
        if choice == 'q':
            proactive_engine.stop()
            ui.display_output("Apagando todos los sistemas, Señor. ¡Que tenga un excelente día!", read_aloud=True)
            break
            
        while True:
            # === BLOQUE DE CAPTURA ===
            command = ""
            if choice == '1':
                command = ui.get_text_command()
            elif choice == '2':
                ui.display_output("Micrófono activado. Estoy escuchando, Señor.", read_aloud=True)
                command = ui.get_voice_command()
            elif choice == '3':
                wake_result = listen_for_wake_word()
                
                if wake_result is True:
                    ui.display_output("Dígame, Señor.", read_aloud=True)
                    command = ui.get_voice_command()
                elif isinstance(wake_result, str) and wake_result:
                    command = wake_result
                else:
                    break
                    
                agent_name = get_agent_name().lower()
                if command.strip().lower() in ["descansa", f"{agent_name} descansa", "apágate", "salir"]:
                    ui.display_output("Entendido, Señor. Pasando a modo de bajo consumo. Avíseme si me necesita.", read_aloud=True)
                    break

            if not command:
                break
                
            # === BLOQUE DE EJECUCIÓN ===
            ui.display_output(f"Comando detectado: '{command}'", read_aloud=False)
            
            # -1. RUTINAS DIRECTAS (antes que todo, ejecuta sin simulación)
            try:
                from learning.routines_engine import try_routine
                routine_result = try_routine(command)
                if routine_result:
                    ui.display_output(routine_result, read_aloud=True)
                    ui.display_output("Rutina ejecutada. ¿Algo más, Señor?", read_aloud=True)
                    from ai.memory_manager import memory
                    memory.store(f"{command} | {routine_result}", category="interaction")
                    if choice == '3': continue
                    else: break
            except Exception as _r_err:
                ui.display_output(f"Error en rutinas: {_r_err}", read_aloud=True)

            # 0. AUTOPILOT
            _autopilot_triggers = ["autopilot", "ejecuta tarea", "crea un", "redacta", "haz un"]
            _cmd_lower = command.strip().lower()
            if any(t in _cmd_lower for t in _autopilot_triggers):
                try:
                    from agents.task_planner import TaskPlanner
                    from agents.task_executor import TaskExecutor
                    planner  = TaskPlanner()
                    executor = TaskExecutor()
                    plan = planner.generate_plan(command)
                    if plan:
                        ui.display_output(f"He generado una secuencia de {len(plan)} pasos, Señor.", read_aloud=True)
                        ui.display_output("Iniciando ejecución de protocolos...", read_aloud=True)
                        
                        def on_step(idx, result):
                            ui.display_output(f"Protocolo {idx+1} completado: {result}", read_aloud=True)
                        
                        summary = executor.execute(plan, on_step_done=on_step)
                        ui.display_output(f"Secuencia finalizada, Señor. {summary}", read_aloud=True)
                        ui.display_output("¿Desea que realice algo más por usted?", read_aloud=True)
                        
                        from ai.memory_manager import memory
                        memory.store(f"{command} | {summary}", category="interaction")
                        if choice == '3': continue
                        else: break
                    else:
                        ui.display_output("No he podido formular un plan complejo. Intentaré ejecutarlo como tarea simple, Señor.", read_aloud=True)
                except Exception as _ap_err:
                    ui.display_output(f"Señor, el Autopilot ha tenido una falla: {_ap_err}", read_aloud=True)
            
            # Comandos aprendidos
            from learning.command_learning import run_custom_command
            
            def execute_simulated_action(action_text):
                ui.display_output(f"Iniciando sub-proceso: '{action_text}'", read_aloud=True)
                act_intent, act_params = classify_command(action_text)
                act_result = dispatch(act_intent, act_params)
                ui.display_output(act_result, read_aloud=True)
                
            if run_custom_command(command, execute_simulated_action):
                ui.display_output("Rutina completada perfectamente. ¿Algo más, Señor?", read_aloud=True)
                if choice == '3': continue
                else: break

            # Capacidades directas del sistema operativo (JSON)
            try:
                from os_integration.capabilities_router import try_capability
                cap_result = try_capability(command)
                if cap_result is not None:
                    ui.display_output(cap_result, read_aloud=True)
                    ui.display_output("Realizado. ¿Requiere algo más, Señor?", read_aloud=True)
                    from ai.memory_manager import memory
                    memory.store(f"{command} | {cap_result}", category="interaction")
                    if choice == '3': continue
                    else: break
            except Exception:
                pass
                
            try:
                from ui.gui import update_gui_state
                update_gui_state("PROCESSING")
            except Exception:
                logger.debug("GUI no disponible en este modo")
                
            intent, params = classify_command(command)
            
            from intent.intentions import Intent
            if intent == Intent.TEACH_COMMAND:
                ui.display_output("Por supuesto, Señor. ¿Cuál será la frase de activación?", read_aloud=True)
                phrase = ui.get_voice_command() if choice in ['2', '3'] else ui.get_text_command()
                if not phrase: continue
                
                ui.display_output("Entendido. ¿Qué acciones debo ejecutar en secuencia? Júntelas con la palabra 'y'.", read_aloud=True)
                actions_text = ui.get_voice_command() if choice in ['2', '3'] else ui.get_text_command()
                if not actions_text: continue
                    
                from learning.command_learning import save_custom_command
                actions_list = [a.strip() for a in actions_text.replace(" y ", ",").replace(" luego ", ",").split(",")]
                save_custom_command(phrase, actions_list)
                ui.display_output(f"Protocolo '{phrase}' cargado y listo para usar, Señor.", read_aloud=True)
                if choice == '3': continue
                else: break
            
            result = dispatch(intent, params)

            # ✅ BUG CORREGIDO: display_output solo una vez aquí
            ui.display_output(result, read_aloud=True)
            ui.display_output("¿Desea que realice alguna otra acción, Señor?", read_aloud=True)
            
            from ai.memory_manager import memory
            memory.store(f"{command} | {result}", category="interaction")
            
            # Guardar embedding semántico (sin bloquear el flujo si falla)
            try:
                from ai.memory_manager import memory
                memory.store(f"Pregunta: {command} | Respuesta: {result}", category="semantic")
            except Exception:
                pass
            
            # ✅ BUG CORREGIDO: eliminado el segundo display_output(result) que existía aquí
            # y que hacía que Glass hablara CADA respuesta DOS veces.

            if choice != '3':
                break

if __name__ == "__main__":
    import sys
    import os
    import threading

    headless = "--headless" in sys.argv

    if not headless:
        try:
            from ui.gui import QApplication, JarvisGUI
            app = QApplication(sys.argv)
            window = JarvisGUI()
            window.show()
        except Exception as e:
            print(f"[GUI] No disponible, modo headless: {e}")
            headless = True

    def jarvis_runner():
        try:
            main()
        except KeyboardInterrupt:
            print("\nDetenido por el usuario (Ctrl + C).")
        except Exception as e:
            import traceback
            import sys
            print(f"\n[❌] Error fatal en el ciclo del asistente:")
            traceback.print_exc()
            sys.stdout.flush()
        finally:
            import sys
            sys.stdout.flush()
            os._exit(0)

    jarvis_mind = threading.Thread(target=jarvis_runner, daemon=True)
    jarvis_mind.start()

    if not headless:
        sys.exit(app.exec())
    else:
        jarvis_mind.join()
