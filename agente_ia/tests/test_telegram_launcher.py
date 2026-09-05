"""
tests/test_telegram_launcher.py
El canal de Telegram arrancando junto con la app de escritorio.

Hasta ahora había que lanzarlo a mano en otra consola, así que en la práctica el agente casi
nunca estaba disponible desde el teléfono: la app se abría y el canal se quedaba apagado.

Ningún test lanza un proceso de verdad ni habla con Telegram (`.claude/rules/testing.md`):
`subprocess.Popen` siempre está sustituido.
"""

import contextlib

from unittest.mock import patch

import pytest

import channels.telegram_launcher as launcher


class _ProcesoFalso:
    """Un `Popen` que no lanza nada. `poll()` a None = sigue vivo."""

    def __init__(self, pid: int = 4242) -> None:
        self.pid = pid
        self._muerto = False
        self.terminado = False
        self.matado = False

    def poll(self):
        return 0 if self._muerto else None

    def terminate(self):
        self.terminado = True

    def wait(self, timeout=None):
        self._muerto = True
        return 0

    def kill(self):
        self.matado = True
        self._muerto = True


@pytest.fixture(autouse=True)
def _sin_proceso_previo():
    """El módulo guarda el proceso en una global: se limpia entre pruebas."""
    launcher._proceso = None
    yield
    launcher._proceso = None


@pytest.fixture
def todo_listo():
    """Token puesto, autostart encendido y nadie más corriendo."""
    with patch("config_manager.get_telegram_token", return_value="123:ABC"), \
         patch("config_manager.get_telegram_autostart", return_value=True), \
         patch.object(launcher, "_ya_hay_uno_corriendo", return_value=False):
        yield


# ── Cuándo NO arranca ───────────────────────────────────────────────

def test_sin_token_no_arranca(todo_listo):
    """Sin credencial no hay canal que levantar, y no es un error: es no estar configurado."""
    with patch("config_manager.get_telegram_token", return_value=""), \
         patch.object(launcher.subprocess, "Popen") as popen:
        assert launcher.arrancar_si_procede() is None
        popen.assert_not_called()


def test_apagado_en_la_configuracion_no_arranca(todo_listo):
    with patch("config_manager.get_telegram_autostart", return_value=False), \
         patch.object(launcher.subprocess, "Popen") as popen:
        assert launcher.arrancar_si_procede() is None
        popen.assert_not_called()


def test_no_arranca_un_segundo_bot(todo_listo):
    """Telegram solo admite un cliente haciendo `getUpdates` por token: el segundo recibe un
    `Conflict` y se queda inútil. Si el usuario ya lo tenía abierto en su consola, lo suyo
    es no abrir otro."""
    with patch.object(launcher, "_ya_hay_uno_corriendo", return_value=True), \
         patch.object(launcher.subprocess, "Popen") as popen:
        assert launcher.arrancar_si_procede() is None
        popen.assert_not_called()


def test_dos_llamadas_no_lanzan_dos_procesos(todo_listo):
    with patch.object(launcher.subprocess, "Popen", return_value=_ProcesoFalso()) as popen:
        primero = launcher.arrancar_si_procede()
        segundo = launcher.arrancar_si_procede()

    assert primero is segundo
    assert popen.call_count == 1


def test_un_fallo_al_lanzar_no_tumba_la_app(todo_listo):
    """Que el canal remoto no pueda arrancar no puede impedir que se abra el escritorio."""
    with patch.object(launcher.subprocess, "Popen", side_effect=OSError("boom")):
        assert launcher.arrancar_si_procede() is None


# ── Cómo arranca ────────────────────────────────────────────────────

def test_arranca_como_proceso_aparte_y_no_dentro_de_la_app(todo_listo):
    """Proceso separado, no un hilo: `run_polling()` monta su propio bucle de asyncio e
    instala manejadores de señales. Y no dentro de la terminal embebida, que es amarilla y
    exige confirmación humana — arrancar algo ahí solo saltaría ese gate."""
    with patch.object(launcher.subprocess, "Popen", return_value=_ProcesoFalso()) as popen:
        launcher.arrancar_si_procede()

    args, kwargs = popen.call_args
    comando = args[0]
    assert comando[0].endswith(("python.exe", "python", "pythonw.exe")), comando
    assert comando[1:] == ["-m", "channels.telegram_bot"], comando
    assert kwargs.get("cwd"), "sin cwd, los imports absolutos del proyecto no resuelven"


def test_el_hijo_queda_marcado_como_lanzado_por_la_app(todo_listo):
    with patch.object(launcher.subprocess, "Popen", return_value=_ProcesoFalso()) as popen:
        launcher.arrancar_si_procede()

    entorno = popen.call_args.kwargs["env"]
    assert entorno[launcher._MARCA_ENTORNO] == "1"


# ── Muere con la aplicación ─────────────────────────────────────────

def test_el_canal_muere_con_la_aplicacion(todo_listo):
    """Mismo criterio que la terminal embebida: nunca queda un canal vivo, hablando con
    quien sea, sin nada que lo muestre."""
    proceso = _ProcesoFalso()
    with patch.object(launcher.subprocess, "Popen", return_value=proceso):
        launcher.arrancar_si_procede()

    launcher.detener()

    assert proceso.terminado
    assert launcher._proceso is None


def test_si_no_se_va_por_las_buenas_se_fuerza(todo_listo):
    """Un bot que sigue atendiendo mensajes con la app cerrada es peor que uno matado."""
    proceso = _ProcesoFalso()
    proceso.wait = lambda timeout=None: (_ for _ in ()).throw(
        launcher.subprocess.TimeoutExpired(cmd="telegram", timeout=5)
    )
    with patch.object(launcher.subprocess, "Popen", return_value=proceso):
        launcher.arrancar_si_procede()

    launcher.detener()

    assert proceso.matado


def test_detener_sin_haber_arrancado_no_rompe():
    launcher.detener()      # no debe lanzar


# ── El enganche real en main.py ─────────────────────────────────────

def test_con_ventana_va_a_la_terminal_de_la_app_y_sin_ventana_a_una_consola():
    """Dónde se ve el canal: en la pestaña de la app cuando hay ventana, y en una consola
    aparte solo en modo headless, donde no hay pestaña que mostrar."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    main_src = (raiz / "main.py").read_text(encoding="utf-8")
    ventana_src = (raiz / "ui" / "webview" / "main_window.py").read_text(encoding="utf-8")

    assert "abrir_canal_telegram()" in ventana_src, "la ventana ya no abre el canal"
    assert "if headless:" in main_src and "arrancar_si_procede()" in main_src, (
        "sin ventana tiene que quedar el camino de la consola aparte"
    )
    assert "atexit.register(detener_telegram)" in main_src
    assert "aboutToQuit.connect(detener_telegram)" in main_src, (
        "sin esto, cerrar la ventana deja el bot vivo: Qt no siempre pasa por atexit"
    )


# ─────────────────────────────────────────────
#  La pestaña del canal NO es una shell
#
#  Es lo que sostiene todo el diseño. `terminal_open` es 🟡 amarilla y pide confirmación
#  humana porque abrir una shell concede la capacidad de ejecutar cualquier cosa. Esta
#  pestaña se abre sola al arrancar, sin esa confirmación, y solo puede hacerlo mientras no
#  sea una shell: comando fijo y teclado descartado. Si algún día acepta lo que se teclee,
#  se habrá regalado la shell por la puerta de atrás.
# ─────────────────────────────────────────────

def test_una_pestana_de_solo_lectura_descarta_el_teclado():
    from core.terminal_session import TerminalSession

    sesion = TerminalSession(argv=["echo", "hola"], solo_lectura=True)
    escrito = []
    sesion._proc = type("P", (), {"write": lambda self, d: escrito.append(d)})()

    sesion.write("whoami")

    assert escrito == [], "una pestaña de solo lectura no puede ejecutar lo que se teclee"


def test_una_pestana_normal_si_acepta_el_teclado():
    """La otra mitad: la terminal de siempre —la que sí pasó por la confirmación— no cambia."""
    from core.terminal_session import TerminalSession

    sesion = TerminalSession()
    escrito = []
    sesion._proc = type("P", (), {"write": lambda self, d: escrito.append(d)})()

    sesion.write("whoami")

    assert escrito == ["whoami"]


def test_la_pestana_del_canal_corre_el_bot_y_no_un_shell():
    """Lo que se lanza es el comando del bot, no `powershell`/`bash`."""
    from core.terminal_session import TerminalSession, shell_por_defecto

    sesion = TerminalSession(argv=launcher.comando(), solo_lectura=True)

    assert sesion.argv == launcher.comando()
    assert sesion.argv != shell_por_defecto()
    assert sesion.argv[1:] == ["-m", "channels.telegram_bot"]


def test_el_bridge_no_expone_la_apertura_del_canal_a_la_pagina():
    """`abrir_canal_telegram` NO puede ser un `@pyqtSlot`: los slots son invocables desde
    cualquier script de la página, y uno que abre pestañas de terminal sería otra superficie
    que habría que gatear. Lo llama `MainWindow` al arrancar, y nadie más."""
    import re
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent
              / "ui" / "webview" / "bridge.py").read_text(encoding="utf-8")
    bloque = fuente[:fuente.index("def abrir_canal_telegram")]

    assert not re.search(r"@pyqtSlot\([^)]*\)\s*$", bloque.rstrip()), (
        "abrir_canal_telegram quedó decorado como slot: la página podría llamarlo"
    )

@contextlib.contextmanager
def _sesion_inyectada(sesion):
    """Mete una sesión en el gestor global y DEVUELVE EL ESTADO COMO ESTABA.

    El gestor es un singleton de proceso, compartido con los tests del webview que abren
    terminales de verdad. La primera versión de esto restauraba `_activa = None` a pelo, sin
    mirar qué había antes: en la suite completa eso le dejaba el gestor descolocado a los
    tests que corrían después, y uno se quedó media hora esperando un estado de terminal que
    ya nadie iba a emitir.
    """
    from core.terminal_session import terminal_manager

    sesion.is_alive = lambda: True      # `get()` descarta las muertas
    with terminal_manager._lock:
        previas = dict(terminal_manager._sessions)
        orden_previo = list(terminal_manager._orden)
        activa_previa = terminal_manager._activa

        terminal_manager._sessions[sesion.id] = sesion
        terminal_manager._orden.append(sesion.id)
        terminal_manager._activa = sesion.id
    try:
        yield terminal_manager
    finally:
        with terminal_manager._lock:
            terminal_manager._sessions = previas
            terminal_manager._orden = orden_previo
            terminal_manager._activa = activa_previa


def test_la_pestana_del_canal_no_hace_de_llave_para_abrir_una_shell():
    """El punto más fino de todo esto, y el que estuve a punto de erosionar.

    `terminal_open` no vuelve a pedir confirmación cuando ya hay una terminal corriendo —
    volver a mostrar algo que ya está abierto no ejecuta nada. Pero la pestaña del canal la
    abre la aplicación sola, sin que nadie la autorice: si contara como "ya hay una terminal
    abierta", su mera existencia saltaría el gate y el usuario acabaría con un shell que
    nunca autorizó, abierto por una pestaña que puso el sistema.
    """
    from core.terminal_session import TerminalSession

    canal = TerminalSession(argv=launcher.comando(), solo_lectura=True, session_id="tcanal")
    with _sesion_inyectada(canal) as gestor:
        assert gestor.hay_interactiva() is False, (
            "una pestaña de solo lectura no puede contar como terminal autorizada"
        )


def test_una_shell_de_verdad_si_cuenta_como_terminal_abierta():
    """La otra mitad: con una shell que el usuario sí autorizó, volver a pulsar el botón no
    tiene por qué preguntar otra vez."""
    from core.terminal_session import TerminalSession

    with _sesion_inyectada(TerminalSession(session_id="tshell")) as gestor:
        assert gestor.hay_interactiva() is True


def test_la_suite_no_levanta_el_canal():
    """Cada test que construía la ventana lanzaba un bot DE VERDAD, con el token real y
    peleándose por él con el que el usuario tuviera abierto."""
    import config_manager

    assert config_manager.get_telegram_autostart() is False, (
        "el fixture autouse de conftest.py dejó de apagar el canal"
    )

# ─────────────────────────────────────────────
#  Dos cosas que salieron al probarlo de verdad
# ─────────────────────────────────────────────

def test_el_token_no_se_imprime_en_la_salida_del_bot():
    """`httpx` registra cada petición con la URL completa, y en la API de Telegram el token
    va DENTRO de la URL:

        HTTP Request: POST https://api.telegram.org/bot<ID>:<TOKEN>/getUpdates "200 OK"

    Varias líneas por minuto, cada una con la credencial entera. Antes solo ensuciaba una
    consola; desde que el canal corre en una pestaña de la terminal, esa salida la guarda
    `TerminalSession` en su scrollback — y `terminal_read_output` puede mandársela al
    proveedor del modelo.
    """
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent
              / "channels" / "telegram_bot.py").read_text(encoding="utf-8")

    assert 'logging.getLogger("httpx").setLevel(logging.WARNING)' in fuente, (
        "sin esto, el token del bot se imprime en la terminal en cada petición"
    )


def test_no_confunde_cualquier_mencion_con_un_bot_corriendo():
    """Con la subcadena suelta se marcaba cualquier proceso que nombrara el módulo —un
    editor con el archivo abierto, un grep, un diagnóstico— y el canal se quedaba sin
    arrancar por un falso positivo: silencioso y con pinta de que nada falló."""
    import psutil

    class _Proc:
        def __init__(self, argv):
            self.info = {"pid": 99999, "cmdline": argv}

    def _procesos(*argvs):
        return lambda attrs=None: [_Proc(a) for a in argvs]

    # Lo que NO es el bot, aunque lo mencione.
    no_son = _procesos(
        ["/usr/bin/python", "-c", "import x; print('telegram_bot')"],
        ["/usr/bin/python", "-m", "pytest", "tests/test_telegram_launcher.py"],
        ["/usr/bin/notepad", "channels/telegram_bot.py"],
        ["grep", "-r", "telegram_bot", "."],
    )
    with patch.object(psutil, "process_iter", no_son):
        assert launcher._ya_hay_uno_corriendo() is False

    # Y el de verdad, que sí tiene que reconocerse.
    es = _procesos(["/usr/bin/python", "-m", "channels.telegram_bot"])
    with patch.object(psutil, "process_iter", es):
        assert launcher._ya_hay_uno_corriendo() is True
