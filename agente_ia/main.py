import logging

from core.logger_setup import setup_logging
logger = setup_logging()

from core.orchestrator import orchestrator
from core.proactive_engine import proactive_engine
from core.security_manager import ChannelType
from core.confirmation import register_confirmation_adapter
from core.resolution import resolve
from router.dispatcher import dispatch
from skills.skill_manager import skill_manager
from intent.classifier import classify_command
from agents.skill_tools import register_dispatcher_tool, register_skill_tools

orchestrator.register_legacy_dispatcher(dispatch)
orchestrator.register_classifier(classify_command)


def _desktop_confirm(action_name: str, message: str) -> bool:
    """Único adaptador de confirmación real de REQ-006 (CA-10). Reproduce exactamente la
    UX que `security_manager.require_confirmation()` tenía hardcodeada antes de este REQ
    (mismo prompt, misma comparación de respuesta) — ahora vive acá porque `main.py` es el
    único punto de entrada con una consola bloqueante disponible."""
    response = input(message)
    return response.strip().lower() in ("sí", "si", "yes", "s")


register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)

# REQ-007/CA-14: migrado de AgentTool (orchestrator.register_tool) a ToolSpec
# (agents/tool_registry.py) — el catálogo de tools ahora es consumido por
# core/reasoning_loop.py, no por AgentOrchestrator.
register_dispatcher_tool()
register_skill_tools(skill_manager)

proactive_engine.set_notify_callback(lambda msg: logger.info(f"[Proactivo] {msg}"))

# ── Registrar triggers proactivos ──────────────────────────────
class _ProactiveAssistant:
    def __init__(self):
        self.name = "ProactiveAssistant"
        self.tools = []

    def can_handle(self, task: str) -> float:
        # REQ-006/CA-12: antes ambas ramas retornaban 0.0 (bug), así que este agente nunca
        # se podía seleccionar por score aunque el trigger proactivo lo invocara. Ver
        # `core/proactive_engine.py::_check_triggers()`, que hoy llama a `trigger.agent.execute()`
        # directo sin pasar por `can_handle()` — este fix deja la clasificación correcta
        # lista para cuando algo sí la consulte (p.ej. un futuro selector de agentes).
        return 0.6 if ("briefing" in task.lower() or "recordatorio" in task.lower()) else 0.0

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

def main(boot_mode=None, gui_active=False):
    ui = CLI(gui_active=gui_active)
    
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

            # REQ-006/CA-01, CA-03: canal real de esta captura (nunca inferido de texto
            # libre) — voz si vino de reconocimiento de voz (choice '2'/'3'), desktop si
            # vino de texto. El resto de la resolución vive en core/resolution.py:resolve(),
            # el punto único de resolución que reemplaza la cascada de 6 capas que existía
            # acá antes de este REQ (rutinas → autopilot → aprendidos → capacidades →
            # intent/dispatch → Claude).
            channel = ChannelType.VOICE if choice in ('2', '3') else ChannelType.DESKTOP

            # TEACH_COMMAND requiere un intercambio interactivo de varios turnos (pedir la
            # frase de activación y luego las acciones) que no puede resolverse en una sola
            # llamada síncrona a resolve() — se preclasifica solo para detectar este caso
            # especial, igual que channels/gateway.py preclasifica para detectar
            # TAKE_SCREENSHOT.
            from intent.intentions import Intent
            _pre_intent, _pre_params = classify_command(command)
            if _pre_intent == Intent.TEACH_COMMAND:
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

            try:
                from ui.gui import update_gui_state
                update_gui_state("PROCESSING")
            except Exception:
                logger.debug("GUI no disponible en este modo")

            resolution = resolve(command, channel)
            result = resolution.text

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
    tray_mode = "--tray" in sys.argv          # REQ-011 — arranque minimizado a bandeja

    if not headless:
        try:
            from ui.gui import QApplication, JarvisMainWindow
            app = QApplication(sys.argv)
            window = JarvisMainWindow()
            if not tray_mode:
                window.showMaximized()
            # tray_mode=True: JarvisMainWindow ya corrió _setup_tray_icon() dentro de
            # _init_ui() (incondicional, ver ui/gui.py) — la bandeja queda funcional sin
            # haber llamado show()/showMaximized() (CA-03, CA-04 de SPEC-011).
        except Exception as e:
            print(f"[GUI] No disponible, modo headless: {e}")
            headless = True

    def jarvis_runner():
        try:
            # REQ-009/CA-06, CA-07: propaga si la sesión corre con GUI activa (closure
            # sobre `headless`, ya calculado arriba) para que `ui/cli.py` oculte la
            # opción "3" cuando hay GUI, sin introducir ningún estado compartido nuevo.
            main(gui_active=(not headless))
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
