from ui.cli import CLI
from intent.classifier import classify_command
from router.dispatcher import dispatch
from voice.wake_word import listen_for_wake_word
from ui.personality import get_random_greeting
from config_manager import get_agent_name

def main(boot_mode=None):
    ui = CLI()
    
    # Saludo inicial al conectar los sistemas
    ui.display_output(get_random_greeting(), read_aloud=True)
    
    while True:
        # Si boot_mode está definido (ej: desde instalador), omitimos el menú inicial
        if boot_mode:
            choice = boot_mode
            boot_mode = None # Solo la primera vez
        else:
            choice = ui.get_input_method()
        
        if choice == 'q':
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
                # Modo escucha pasiva continua
                wake_result = listen_for_wake_word()
                
                if wake_result is True:
                    # Notificar proactivamente el estado activo
                    ui.display_output("Dígame, Señor.", read_aloud=True)
                    command = ui.get_voice_command()
                elif isinstance(wake_result, str) and wake_result:
                    command = wake_result
                else:
                    break # Salir al menú principal si falla
                    
                # Condición de salida del loop continuo
                agent_name = get_agent_name().lower()
                if command.strip().lower() in ["descansa", f"{agent_name} descansa", "apágate", "salir"]:
                    ui.display_output("Entendido, Señor. Pasando a modo de bajo consumo. Avíseme si me necesita.", read_aloud=True)
                    break 

            if not command:
                break # Regresa al Menú Principal si no hay Input
                
            # === BLOQUE DE EJECUCIÓN ===
            ui.display_output(f"Comando detectado: '{command}'", read_aloud=False)
            
            # -1. AUTOPILOT
            _autopilot_triggers = ["autopilot", "ejecuta tarea", "crea un", "redacta", "haz un"]
            _cmd_lower = command.strip().lower()
            if any(t in _cmd_lower for t in _autopilot_triggers):
                try:
                    from agents.task_planner  import TaskPlanner
                    from agents.task_executor import TaskExecutor
                    planner  = TaskPlanner()
                    executor = TaskExecutor()
                    plan = planner.generate_plan(command)
                    if plan:
                        ui.display_output(f"He generado una secuencia de {len(plan)} pasos, Señor.", read_aloud=True)
                        ui.display_output("Iniciando ejecución de protocolos...", read_aloud=True)
                        
                        def on_step(idx, result):
                            # Interacción constante: anunciar progreso
                            ui.display_output(f"Protocolo {idx+1} completado: {result}", read_aloud=True)
                        
                        summary = executor.execute(plan, on_step_done=on_step)
                        ui.display_output(f"Secuencia finalizada, Señor. {summary}", read_aloud=True)
                        ui.display_output("¿Desea que realice algo más por usted?", read_aloud=True)
                        
                        from ai.memory_manager import save_memory
                        save_memory(command, summary)
                        if choice == '3': continue
                        else: break
                    else:
                        ui.display_output("No he podido formular un plan complejo. Intentaré ejecutarlo como tarea simple, Señor.", read_aloud=True)
                except Exception as _ap_err:
                    ui.display_output(f"Señor, el Autopilot ha tenido una falla: {_ap_err}", read_aloud=True)
            
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

            # 0.5. Capacidades directas
            try:
                from os_integration.capabilities_router import try_capability
                cap_result = try_capability(command)
                if cap_result is not None:
                    ui.display_output(cap_result, read_aloud=True)
                    ui.display_output("Realizado. ¿Requiere algo más, Señor?", read_aloud=True)
                    from ai.memory_manager import save_memory
                    save_memory(command, cap_result)
                    if choice == '3': continue
                    else: break
            except Exception: pass
                
            try:
                from ui.gui import update_gui_state
                update_gui_state("PROCESSING")
            except: pass
                
            intent, params = classify_command(command)
            
            # (El bloque de TEACH_COMMAND se mantiene igual pero es ejecutado si coincide)
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
            ui.display_output(result, read_aloud=True)
            ui.display_output("¿Desea que realice alguna otra acción, Señor?", read_aloud=True)
            
            from ai.memory_manager import save_memory
            save_memory(command, result)
            
            # Guardar también como embedding semántico (para recuperación inteligente)
            try:
                from ai.semantic_memory import store_memory as sem_store
                sem_store(f"Pregunta: {command} | Respuesta: {result}")
            except Exception:
                pass  # Si sentence-transformers no cargó, no bloqueamos el flujo
            
            ui.display_output(result, read_aloud=True)
            
            # Condición de retorno al inicio: si era opción 1 o 2, sal del sub-bucle. 
            # Si es opción 3, se repetirá arriba.
            if choice != '3':
                break

if __name__ == "__main__":
    import sys
    import os
    import threading
    from ui.gui import QApplication, JarvisGUI

    app = QApplication(sys.argv)
    window = JarvisGUI()
    window.show()

    def jarvis_runner():
        try:
            main()
        except KeyboardInterrupt:
            print("\nDetenido por el usuario (Ctrl + C).")
        except Exception as e:
            print(f"\nError fatal en el ciclo del asistente: {e}")
        finally:
            # Dado que matamos el sistema desde un daemon thread secundario de consola, 
            # forzamos os._exit(0) para saltarnos el blindaje de PyQt6 en Windows.
            os._exit(0)

    jarvis_mind = threading.Thread(target=jarvis_runner, daemon=True)
    jarvis_mind.start()
    
    # Este hilo queda atrapado ejecutando la pantalla.
    sys.exit(app.exec())
