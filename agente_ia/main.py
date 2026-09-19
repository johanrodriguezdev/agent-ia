# REQ-015 — DEBE ir antes que cualquier otro import (ver desarrollo-log-015.md, hallazgo
# de la verificación manual de esta reanudación). Varios módulos de `skills`/
# `os_integration` (p. ej. `screen_analysis_skill.py`, `screenshot_tools.py`) importan
# `pyautogui`, que en Windows llama `ctypes.windll.user32.SetProcessDPIAware()`
# ("System DPI Aware", un único factor de escala global) como efecto secundario de su
# propio import — y ese import ocurre de forma transitiva vía `skill_manager` antes de
# que exista `QApplication`. Windows solo permite fijar el contexto de DPI awareness del
# proceso UNA vez: si `pyautogui` gana la carrera, Qt/QtWebEngine ya no puede subir a
# `DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2` (falla con "Acceso denegado", visible en
# los logs) y queda un desajuste real entre el `devicePixelRatio` que asume QtWebEngine
# (1.5 en una pantalla al 150%, confirmado con Chrome DevTools Protocol contra la ventana
# real) y el tamaño físico real de la ventana (`GetWindowRect`, más chico) — el contenido
# del WebView se pinta para un lienzo ~1.5x más ancho del que la ventana realmente tiene,
# y todo lo que cae más allá del borde físico queda recortado (sidebar/saludo cortados en
# la verificación manual). Fijarlo acá, antes que nada, gana la carrera.
import sys

if sys.platform == "win32":
    import ctypes as _ctypes
    import logging as _early_logging

    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4 (no expuesto por ctypes.wintypes)
        _ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception as e:
        _early_logging.getLogger(__name__).warning(
            f"No se pudo fijar DPI awareness Per-Monitor-V2 antes de otros imports: {e}"
        )

import logging

from core.logger_setup import setup_logging
logger = setup_logging()

from core.orchestrator import orchestrator
from core.proactive_engine import proactive_engine
from tasks.task_scheduler import task_scheduler   # REQ-016/CA-10
from core.security_manager import ChannelType
from core.confirmation import register_confirmation_adapter
from core.resolution import resolve
from router.dispatcher import dispatch
from skills.skill_manager import skill_manager
from intent.classifier import classify_command
from agents.skill_tools import (register_dispatcher_tool, register_family_tools,
                                register_skill_tools)
from agents.user_defined_tools import register_user_defined_tools
from core.address import vocative, vocative_start

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
# Familias: volumen, info del sistema y flujos se presentan como UNA herramienta cada una.
register_family_tools(skill_manager)
# Rutinas, comandos aprendidos y Autopilot. Antes solo eran alcanzables como resolvers
# delante del modelo; ahora que el modelo lee primero, son herramientas que elige el.
register_user_defined_tools()

# Servidores MCP declarados en config.json (`mcp_servers`). Va DESPUÉS de los tools
# locales a propósito: así, si un servidor remoto intentara registrar un nombre que ya
# existe, el local ya está puesto. En la práctica no puede pasar —`register_tool()` exige
# el prefijo `mcp__` para todo lo remoto— pero el orden lo hace cierto por construcción y
# no solo por la validación.
#
# Envuelto y no fatal: un servidor caído, lento o mal configurado no puede impedir que
# O.R.I.O.N. arranque.
try:
    from core.mcp_manager import conectar_todos as _conectar_mcp

    _resumen_mcp = _conectar_mcp()
    for _servidor, _detalle in _resumen_mcp.items():
        print(f"  [+] MCP '{_servidor}' — {_detalle}")
except Exception as e:
    logger.error(f"No se pudieron conectar los servidores MCP: {e}")

def _avisar_proactivo(msg: str) -> None:
    """Destino de lo que produce el motor proactivo.

    Antes solo se registraba en el log: el motor pensaba, gastaba una llamada al modelo y
    la respuesta moría en un archivo que nadie mira. Ahora sale por el canal de avisos
    (`core/notificaciones.py`), que la muestra en la bandeja del sistema y —si la ventana
    está abierta— también dentro de la aplicación.
    """
    if not msg:
        return
    logger.info(f"[Proactivo] {msg}")
    # Import local: esta función se define antes de la sección de imports de
    # `config_manager` de más abajo, y en el cuerpo se resolvería igual por ser tardío —
    # pero dejarlo explícito evita que un reordenamiento futuro lo rompa en silencio.
    from config_manager import get_agent_name
    from core.notificaciones import notificar

    texto = " ".join(str(msg).split())
    notificar(get_agent_name(), texto[:300], "info")


proactive_engine.set_notify_callback(_avisar_proactivo)

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

class _EmailWatcher:
    """Revisa el correo en segundo plano y devuelve el resumen para que se avise.

    NO pasa por el orquestador, a diferencia de `_ProactiveAssistant`, y es deliberado: el
    contenido de un correo no tiene por qué acercarse al camino que resuelve comandos del
    usuario. Acá entra un disparo de reloj y sale texto ya resumido por
    `core/email_reader.py`, que corrió como entrada no confiable.
    """

    def __init__(self):
        self.name = "EmailWatcher"
        self.tools = []

    def can_handle(self, task: str) -> float:
        return 0.0   # solo se invoca por horario, nunca por selección de agente

    def execute(self, task: str, context: dict = None) -> str:
        from core import email_reader

        try:
            resumen = email_reader.revisar()
        except Exception as e:
            logger.error(f"[Correo] fallo en la revisión proactiva: {e}")
            return ""
        return f"Correo nuevo:\n{resumen}" if resumen else ""


_proactive_assistant = _ProactiveAssistant()

# Solo se registra si el correo está configurado: sin cuenta, revisar cada hora sería
# trabajo inútil y una línea de log confusa cada 60 minutos.
try:
    from core import email_reader as _email_reader

    if _email_reader.esta_configurado():
        # Configurable en config.json: "email": {"check_schedule": "daily:08:00"}. Los
        # formatos son los de `core/proactive_engine.py::_should_fire()`.
        _horario = str(_email_reader.cargar_config().get("check_schedule", "hourly")).strip()
        proactive_engine.register_trigger(_EmailWatcher(), _horario, "revisar correo")
        _cuentas = ", ".join(_email_reader.cargar_cuentas())
        print(f"  [+] Vigilancia de correo — {_horario} ({_cuentas})")
except Exception as e:
    logger.error(f"No se pudo registrar la vigilancia de correo: {e}")

try:
    from core.flows import programar_todos, reanudar_pendientes

    for _descripcion in programar_todos():
        print(f"  [+] Flujo programado — {_descripcion}")

    _pendientes = reanudar_pendientes()
    if _pendientes:
        print(f"  [!] {len(_pendientes)} flujo(s) quedaron a medias:")
        for _aviso in _pendientes:
            print(f"      {_aviso}")
except Exception as e:
    logger.error(f"No se pudieron preparar los flujos: {e}")

proactive_engine.register_trigger(_proactive_assistant, "startup", f"¿Necesita algo{vocative()}?")
proactive_engine.register_trigger(_proactive_assistant, "hourly", f"¿Todo en orden{vocative()}?")
proactive_engine.register_trigger(_proactive_assistant, "daily:08:00", f"Buenos días{vocative()}. ¿Qué necesita para hoy?")

from ui.cli import CLI
from voice.wake_word import listen_for_wake_word
from ui.personality import get_random_greeting
from config_manager import get_agent_name, normalize_for_match

def main(boot_mode=None, gui_active=False):
    ui = CLI(gui_active=gui_active)
    
    # Iniciar engine proactivo
    proactive_engine.start()
    task_scheduler.start()   # REQ-016/CA-10 — antes solo arrancaba desde channels/telegram_bot.py

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
            task_scheduler.stop()   # simetría con proactive_engine — TaskScheduler.stop() ya existe
            try:
                from core.mcp_manager import cerrar_todos as _cerrar_mcp

                _cerrar_mcp()   # los servidores stdio son subprocesos: hay que terminarlos
            except Exception as e:
                logger.warning(f"No se pudieron cerrar los servidores MCP: {e}")
            ui.display_output(f"Apagando todos los sistemas{vocative()}. ¡Que tenga un excelente día!", read_aloud=True)
            break
            
        while True:
            # === BLOQUE DE CAPTURA ===
            command = ""
            if choice == '1':
                command = ui.get_text_command()
            elif choice == '2':
                ui.display_output(f"Micrófono activado. Estoy escuchando{vocative()}.", read_aloud=True)
                command = ui.get_voice_command()
            elif choice == '3':
                wake_result = listen_for_wake_word()
                
                if wake_result is True:
                    ui.display_output(f"Dígame{vocative()}.", read_aloud=True)
                    command = ui.get_voice_command()
                elif isinstance(wake_result, str) and wake_result:
                    command = wake_result
                else:
                    break
                    
                # Se normaliza igual que las wake words: con un nombre como "O.R.I.O.N"
                # la comparación cruda ("o.r.i.o.n descansa") jamás coincidiría con lo
                # que devuelve el reconocedor de voz ("orion descansa").
                agent_name = normalize_for_match(get_agent_name())
                spoken = normalize_for_match(command)
                if spoken in ["descansa", f"{agent_name} descansa", "apagate", "salir"]:
                    ui.display_output(f"Entendido{vocative()}. Pasando a modo de bajo consumo. Avíseme si me necesita.", read_aloud=True)
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
                ui.display_output(f"Por supuesto{vocative()}. ¿Cuál será la frase de activación?", read_aloud=True)
                phrase = ui.get_voice_command() if choice in ['2', '3'] else ui.get_text_command()
                if not phrase: continue

                ui.display_output("Entendido. ¿Qué acciones debo ejecutar en secuencia? Júntelas con la palabra 'y'.", read_aloud=True)
                actions_text = ui.get_voice_command() if choice in ['2', '3'] else ui.get_text_command()
                if not actions_text: continue

                from learning.command_learning import save_custom_command
                actions_list = [a.strip() for a in actions_text.replace(" y ", ",").replace(" luego ", ",").split(",")]
                save_custom_command(phrase, actions_list)
                ui.display_output(f"Protocolo '{phrase}' cargado y listo para usar{vocative()}.", read_aloud=True)
                if choice == '3': continue
                else: break

            try:
                from ui.webview.gui_state import update_gui_state
                update_gui_state("PROCESSING")
            except Exception:
                logger.debug("GUI no disponible en este modo")

            resolution = resolve(command, channel)
            result = resolution.text

            # ✅ BUG CORREGIDO: display_output solo una vez aquí
            ui.display_output(result, read_aloud=True)
            ui.display_output(f"¿Desea que realice alguna otra acción{vocative()}?", read_aloud=True)
            
            from ai.memory_manager import memory
            memory.store(f"{command} | {result}", category="interaction")
            
            # Guardar embedding semántico (sin bloquear el flujo si falla)
            try:
                from ai.memory_manager import memory
                memory.store(f"Pregunta: {command} | Respuesta: {result}", category="semantic")
            except Exception as e:
                # El turno ya quedo guardado como interaccion; lo que se pierde aca es el
                # vector semantico, o sea la posibilidad de recordar esto mas adelante. En
                # silencio, la memoria deja de crecer y nadie lo nota.
                logger.warning(f"no se pudo guardar el embedding del turno: {e}")
            
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

    # USER.md y MEMORY.md son del usuario y no viajan en el repositorio: en un equipo
    # recién clonado no existen, y sin ellos el agente no sabe a quién le habla. Se crean
    # desde sus plantillas una sola vez; los que ya existen no se tocan.
    from core.identity import asegurar_archivos_personales

    asegurar_archivos_personales()

    # Lo caro se carga ahora, en segundo plano, mientras el usuario abre la ventana y
    # escribe su primer mensaje. Antes se cargaba en esa primera pregunta: más de un minuto
    # entre el clasificador, torch y el modelo de embeddings, con el usuario mirando tres
    # puntos suspensivos sin saber si el agente pensaba o se había colgado.
    from core.warmup import start_warmup

    start_warmup()

    # Consolidación automática de la memoria. Desactivada por defecto: gasta llamadas al
    # modelo por su cuenta, y eso se activa a propósito, no por descuido.
    from core.dreaming import start_dreaming

    start_dreaming()

    # El canal de Telegram, en su propia terminal. Hasta ahora habia que lanzarlo a mano en
    # otra consola, asi que en la practica el agente casi nunca estaba disponible desde el
    # telefono: la app se abria y el canal se quedaba apagado. No arranca si no hay token,
    # si ya hay uno corriendo, o si se apago en config.json.
    from channels.telegram_launcher import detener as detener_telegram

    # Muere con la aplicacion, mismo criterio que la terminal embebida: nunca queda un canal
    # vivo, hablando con quien sea, sin nada que lo muestre. `atexit` cubre tambien el modo
    # headless y la salida por Ctrl+C.
    import atexit

    atexit.register(detener_telegram)

    # Sin ventana no hay pestaña donde mostrarlo, asi que ahi si va en una consola aparte.
    # Con ventana lo abre `MainWindow` en la terminal embebida, que es donde se ve.
    if headless:
        from channels.telegram_launcher import arrancar_si_procede

        arrancar_si_procede()

    if not headless:
        try:
            from PyQt6.QtWidgets import QApplication
            from ui.webview.app_icon import fijar_identidad_en_windows
            from ui.webview.main_window import MainWindow

            # ANTES de crear la QApplication: la barra de tareas de Windows agrupa por
            # AppUserModelID, y si el proceso no declara uno propio hereda el de
            # `python.exe`. Por eso seguía saliendo el logo de Python en la barra aunque la
            # ventana ya tuviera su icono — `setWindowIcon()` no alcanza, son dos cosas
            # distintas: una pinta la ventana, la otra le dice a Windows qué aplicación es.
            fijar_identidad_en_windows()

            app = QApplication(sys.argv)
            window = MainWindow()
            # Cerrar la ventana tambien cierra el canal: `atexit` no siempre corre cuando Qt
            # termina el proceso, y un bot huerfano seguiria atendiendo mensajes.
            app.aboutToQuit.connect(detener_telegram)
            if not tray_mode:
                window.show()
            # REQ-015: tamaño/posición ya resueltos por `fit_size_to_screen()` dentro del
            # constructor de `MainWindow` (CA-04) — nunca `showMaximized()` (ver
            # arquitectura-015.md §5.1, evita los márgenes extra que DWM añade en
            # maximizado+frameless en Windows).
            # tray_mode=True: MainWindow ya corrió _setup_tray_icon() dentro de __init__()
            # (incondicional) — la bandeja queda funcional sin haber llamado show() (CA-03,
            # CA-04 de SPEC-011).
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
