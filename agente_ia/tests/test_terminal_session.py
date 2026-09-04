"""
tests/test_terminal_session.py
Terminales embebidas (`core/terminal_session.py`) + su clasificación de riesgo.

Ningún test de acá abre un shell real: `TerminalSession.start()` se ejerce con el import de
la biblioteca de PTY mockeado, y el manager con sesiones falsas. Lo que se prueba es lo que
puede romperse en silencio y costar caro: qué queda registrado en la auditoría, qué se le
devuelve al agente, y que la terminal no sea alcanzable desde un canal remoto.
"""

import sys
import types

import pytest

from core.security_manager import ChannelType, RiskLevel, security_manager
from core.terminal_session import (
    _LineaVisual,
    TerminalManager,
    TerminalSession,
    TerminalUnavailable,
    _clean_capture,
    extraer_comando,
    shell_por_defecto,
    strip_ansi,
)

ESC = chr(27)
CR = chr(13)
LF = chr(10)
DEL = chr(127)
ETX = chr(3)
BEL = chr(7)

PROMPT = "PS C:\\proyecto> "


@pytest.fixture
def sesion_con_auditoria(monkeypatch):
    """Sesión sin proceso, con `_record_command` capturado en una lista."""
    registrados = []
    monkeypatch.setattr(
        TerminalSession, "_record_command", staticmethod(lambda line: registrados.append(line))
    )
    return TerminalSession(), registrados


# --------------------------------------------------------------------------- limpieza ANSI

def test_strip_ansi_saca_colores_y_movimientos_de_cursor():
    crudo = ESC + "[32mverde" + ESC + "[0m" + ESC + "[2J" + "fin"
    assert strip_ansi(crudo) == "verdefin"


def test_strip_ansi_saca_el_titulo_de_ventana_osc():
    crudo = ESC + "]0;C:\\Users\\yo" + BEL + "salida"
    assert strip_ansi(crudo) == "salida"


# --------------------------------------------------------------------------- línea visible

def test_linea_visual_arma_lo_que_se_ve():
    pantalla = _LineaVisual()
    pantalla.feed(PROMPT + "dir")
    assert pantalla.texto() == PROMPT.rstrip() + " dir"


def test_linea_visual_ignora_los_colores():
    pantalla = _LineaVisual()
    pantalla.feed(ESC + "[32m" + "verde" + ESC + "[0m")
    assert pantalla.texto() == "verde"


def test_linea_visual_reescribe_desde_el_principio_con_retorno_de_carro():
    """Es lo que hace el shell al traer un comando del historial: vuelve a la columna 0,
    borra el resto de la línea y escribe otra cosa."""
    pantalla = _LineaVisual()
    pantalla.feed(PROMPT + "algo largo")
    pantalla.feed(CR + ESC + "[K" + PROMPT + "dir")
    assert pantalla.texto() == PROMPT.rstrip() + " dir"


def test_linea_visual_respeta_la_columna_absoluta():
    pantalla = _LineaVisual()
    pantalla.feed("abcdef")
    pantalla.feed(ESC + "[3G" + "XY")     # cursor a la columna 3 (índice 2)
    assert pantalla.texto() == "abXYef"


def test_linea_visual_entrega_la_linea_al_terminar():
    entregadas = []
    pantalla = _LineaVisual(on_linea=entregadas.append)
    pantalla.feed("primera" + CR + LF + "segunda" + CR + LF)
    assert entregadas == ["primera", "segunda"]


def test_linea_visual_aplica_el_borrado_de_linea():
    pantalla = _LineaVisual()
    pantalla.feed("comando largo")
    pantalla.feed(ESC + "[8G" + ESC + "[K")   # cursor a la columna 8 y borra hacia adelante
    assert pantalla.texto() == "comando"


# --------------------------------------------------------------------------- prompt

@pytest.mark.parametrize("linea,esperado", [
    ("PS C:\\proyecto> git status", "git status"),
    ("C:\\Users\\yo>dir", "dir"),
    ("yo@maquina:~/proyecto$ ls -la", "ls -la"),
    ("root@maquina:/# whoami", "whoami"),
    ("PS C:\\proyecto> ", ""),          # solo el prompt: no hay comando
    ("una linea de salida cualquiera", ""),
])
def test_extraer_comando_separa_el_prompt(linea, esperado):
    assert extraer_comando(linea) == esperado


def test_extraer_comando_no_se_come_una_redireccion():
    """El `>` del prompt viene antes; el de la redirección es parte del comando."""
    assert extraer_comando("PS C:\\p> echo hola > salida.txt") == "echo hola > salida.txt"


# --------------------------------------------------------------------------- auditoría

def test_auditoria_registra_la_linea_completa_al_llegar_el_enter(sesion_con_auditoria):
    sesion, registrados = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines("git status")
    assert registrados == []          # sin Enter todavía no hay comando
    sesion._pantalla.feed("git status")
    sesion._audit_lines(CR)
    assert registrados == ["git status"]


def test_auditoria_ignora_las_respuestas_de_escape_de_xterm(sesion_con_auditoria):
    """xterm.js contesta solo las consultas de la consola (atributos, foco) y esas
    respuestas entran por el mismo camino que las teclas. Antes se pegaban al principio
    del comando y la auditoría guardaba `[?1;2c[Igit status`."""
    sesion, registrados = sesion_con_auditoria
    sesion._audit_lines(ESC + "[?1;2c" + ESC + "[Igit status --short" + CR)
    assert registrados == ["git status --short"]


def test_auditoria_registra_un_comando_traido_del_historial(sesion_con_auditoria):
    """↑ no teclea nada: el comando lo repone el shell redibujando la línea. Se registra
    igual, porque se ejecutó igual — antes solo quedaba constancia de que "algo" corrió."""
    sesion, registrados = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines(ESC + "[A")                                   # flecha arriba
    sesion._pantalla.feed(CR + ESC + "[K" + PROMPT + "git push")      # el shell redibuja
    sesion._audit_lines(CR)
    assert registrados == ["git push"]


def test_auditoria_registra_el_comando_completado_con_tab(sesion_con_auditoria):
    """Se tecleó `git sta` y el shell completó `git status`: lo que se ejecuta es lo
    segundo, y es lo que tiene que quedar escrito."""
    sesion, registrados = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines("git sta")
    sesion._pantalla.feed("git sta")
    sesion._audit_lines(chr(9))                                       # Tab
    sesion._pantalla.feed(CR + ESC + "[K" + PROMPT + "git status")
    sesion._audit_lines(CR)
    assert registrados == ["git status"]


def test_auditoria_usa_lo_tecleado_cuando_el_eco_todavia_no_llego(sesion_con_auditoria):
    """La herramienta del agente escribe la línea entera de una vez: cuando llega el Enter
    el shell todavía no hizo eco de nada, y lo único que se sabe es lo que se escribió."""
    sesion, registrados = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines("echo hola" + CR)
    assert registrados == ["echo hola"]


def test_auditoria_prefiere_lo_tecleado_si_el_eco_va_atrasado(sesion_con_auditoria):
    """Caso borde real: el eco puede ir un carácter detrás del teclado. Registrar `di` en
    vez de `dir` sería peor que no tener eco."""
    sesion, registrados = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines("dir")
    sesion._pantalla.feed("di")          # falta el último carácter
    sesion._audit_lines(CR)
    assert registrados == ["dir"]


def test_auditoria_aplica_el_backspace(sesion_con_auditoria):
    sesion, registrados = sesion_con_auditoria
    sesion._audit_lines("echo ho")
    sesion._audit_lines(DEL)
    sesion._audit_lines("la" + CR)
    assert registrados == ["echo hla"]


def test_auditoria_no_registra_un_comando_cancelado_con_ctrl_c(sesion_con_auditoria):
    """Ctrl+C descarta la línea sin ejecutarla: registrarla diría que pasó algo que no pasó."""
    sesion, registrados = sesion_con_auditoria
    sesion._audit_lines("rm -rf algo")
    sesion._audit_lines(ETX)
    sesion._audit_lines("dir" + CR)
    assert registrados == ["dir"]


def test_auditoria_ignora_un_enter_suelto(sesion_con_auditoria):
    sesion, registrados = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines(CR)
    sesion._audit_lines(CR)
    assert registrados == []


# --------------------------------------------------------------------------- historial

def test_salida_reciente_devuelve_lo_que_se_vio_sin_ansi():
    """Es lo que le permite al agente contestar sobre un comando que corrió el usuario."""
    sesion = TerminalSession()
    sesion._pantalla.feed(PROMPT + "dir" + CR + LF)
    sesion._pantalla.feed(ESC + "[33mmodulo.py" + ESC + "[0m" + CR + LF)
    sesion._pantalla.feed("otro.py" + CR + LF)
    assert sesion.salida_reciente() == "PS C:\\proyecto> dir\nmodulo.py\notro.py"


def test_el_historial_no_guarda_los_redibujados_a_medias():
    """PSReadLine redibuja el renglon entero en cada tecla, reposicionando el cursor. Cada
    redibujado NO es una linea de salida: si se guardaran, el historial que lee el agente
    seria una lista de versiones a medio escribir del mismo comando (bug real, visto en la
    verificacion sobre la app corriendo)."""
    sesion = TerminalSession()
    sesion._pantalla.feed(PROMPT + "di")
    sesion._pantalla.feed(ESC + "[H" + PROMPT + "dir")     # redibujo con reposicion
    sesion._pantalla.feed(ESC + "[H" + PROMPT + "dir /s")  # y otro
    sesion._pantalla.feed(CR + LF)
    assert sesion.salida_reciente() == PROMPT.rstrip() + " dir /s"


def test_el_historial_incluye_el_comando_ejecutado(sesion_con_auditoria):
    """El renglon de edicion nunca "termina" como una linea normal (el shell lo redibuja al
    apretar Enter), asi que sin anotarlo a mano el historial tendria las salidas sin los
    comandos que las produjeron."""
    sesion, _ = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines("dir")
    sesion._pantalla.feed("dir")
    sesion._audit_lines(CR)
    sesion._pantalla.feed(CR + LF)                     # el shell acepta y baja de renglon
    sesion._pantalla.feed("archivo.txt" + CR + LF)

    assert sesion.salida_reciente() == PROMPT.rstrip() + " dir" + chr(10) + "archivo.txt"


def test_el_historial_anota_el_comando_del_agente_aunque_no_haya_eco(sesion_con_auditoria):
    sesion, _ = sesion_con_auditoria
    sesion._pantalla.feed(PROMPT)
    sesion._audit_lines("git status" + CR)      # linea entera de una vez, sin eco todavia
    assert sesion.salida_reciente() == PROMPT.rstrip() + " git status"


def test_salida_reciente_recorta_a_las_ultimas_lineas():
    sesion = TerminalSession()
    for i in range(40):
        sesion._pantalla.feed(f"linea {i}" + CR + LF)
    assert sesion.salida_reciente(3) == "linea 37\nlinea 38\nlinea 39"


def test_salida_reciente_vacia_al_principio():
    assert TerminalSession().salida_reciente() == ""


# --------------------------------------------------------------------------- captura

def test_clean_capture_saca_el_eco_del_comando_y_el_prompt():
    crudo = (
        "git status --short" + CR + LF
        + " M archivo.py" + LF
        + "?? nuevo.py" + LF
        + "PS C:\\Users\\yo\\proyecto> "
    )
    assert _clean_capture(crudo, "git status --short") == " M archivo.py\n?? nuevo.py"


def test_clean_capture_devuelve_vacio_si_el_comando_no_imprimio_nada():
    crudo = "cd .." + CR + LF + "PS C:\\Users\\yo> "
    assert _clean_capture(crudo, "cd ..") == ""


def test_clean_capture_recorta_una_salida_enorme():
    crudo = "comando" + CR + LF + ("x" * 20000)
    salida = _clean_capture(crudo, "comando")
    assert len(salida) < 9000
    assert salida.endswith("(salida recortada)")


# --------------------------------------------------------------------------- multiplataforma

def test_shell_por_defecto_windows(monkeypatch):
    monkeypatch.setattr("core.terminal_session.ES_WINDOWS", True)
    assert shell_por_defecto()[0] == "powershell.exe"


def test_shell_por_defecto_posix_respeta_la_variable_shell(monkeypatch):
    monkeypatch.setattr("core.terminal_session.ES_WINDOWS", False)
    monkeypatch.setenv("SHELL", "/usr/bin/zsh")
    assert shell_por_defecto() == ["/usr/bin/zsh"]


def test_shell_por_defecto_posix_sin_variable_cae_a_sh(monkeypatch):
    monkeypatch.setattr("core.terminal_session.ES_WINDOWS", False)
    monkeypatch.delenv("SHELL", raising=False)
    assert shell_por_defecto() == ["/bin/sh"]


def test_start_sin_la_dependencia_de_pty_lanza_terminal_unavailable(monkeypatch):
    """Sin la biblioteca, la app no puede reventar: tiene que decir qué falta."""
    monkeypatch.setitem(sys.modules, "winpty", None)      # fuerza el ImportError del `from`
    monkeypatch.setitem(sys.modules, "ptyprocess", None)
    with pytest.raises(TerminalUnavailable) as exc:
        TerminalSession().start()
    assert "pywinpty" in str(exc.value) or "ptyprocess" in str(exc.value)


def test_start_propaga_un_fallo_de_spawn_como_terminal_unavailable(monkeypatch):
    falso = types.ModuleType("winpty")

    class PtyProcess:
        @staticmethod
        def spawn(*args, **kwargs):
            raise OSError("no se pudo crear la consola")

    falso.PtyProcess = PtyProcess
    falso.PtyProcessUnicode = PtyProcess
    monkeypatch.setitem(sys.modules, "winpty", falso)
    monkeypatch.setitem(sys.modules, "ptyprocess", falso)
    with pytest.raises(TerminalUnavailable):
        TerminalSession().start()


def test_write_y_resize_no_revientan_sin_proceso():
    """El panel puede mandar teclas o un resize entre que la shell muere y el frontend se
    entera: eso es una carrera normal, no un error."""
    sesion = TerminalSession()
    sesion.write("algo")
    sesion.resize(100, 40)
    assert sesion.is_alive() is False


# --------------------------------------------------------------------------- manager

class _SesionFalsa:
    """Doble de `TerminalSession` para el manager: no abre nada."""

    _n = 0

    def __init__(self, cwd=None, **kwargs):
        _SesionFalsa._n += 1
        self.id = f"t{_SesionFalsa._n}"
        self.titulo = f"Terminal {_SesionFalsa._n}"
        self.cwd = cwd or "C:\\proyecto"
        self.viva = True
        self.cerrada = False
        self.on_output = None
        self.on_exit = None

    def start(self):
        return None

    def is_alive(self):
        return self.viva

    def close(self):
        self.cerrada = True
        self.viva = False


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setattr("core.terminal_session.TerminalSession", _SesionFalsa)
    return TerminalManager()


def test_manager_ensure_reusa_la_sesion_activa(manager):
    """Dos entradas (el panel y el agente) tienen que dar contra la MISMA shell: si el
    agente abriera una propia, el usuario no vería lo que se ejecuta en su máquina."""
    primera = manager.ensure()
    assert manager.ensure() is primera
    assert len(manager.ids()) == 1


def test_manager_crear_abre_una_pestana_nueva_cada_vez(manager):
    primera = manager.crear()
    segunda = manager.crear()
    assert primera is not segunda
    assert manager.ids() == [primera.id, segunda.id]
    assert manager.active() is segunda      # la nueva queda al frente


def test_manager_cambia_de_pestana_activa(manager):
    primera = manager.crear()
    manager.crear()
    assert manager.set_active(primera.id) is True
    assert manager.active() is primera
    assert manager.set_active("no-existe") is False


def test_manager_al_cerrar_una_activa_la_anterior(manager):
    primera = manager.crear()
    segunda = manager.crear()
    manager.close(segunda.id)
    assert segunda.cerrada is True
    assert manager.active() is primera


def test_manager_abre_una_nueva_si_la_anterior_murio(manager):
    primera = manager.ensure()
    primera.viva = False
    assert manager.active() is None
    assert manager.ensure() is not primera


def test_manager_close_all_no_deja_ninguna_viva(manager):
    manager.crear()
    manager.crear()
    manager.close_all()
    assert manager.ids() == []
    assert manager.active() is None


def test_manager_avisa_cada_cambio_de_estado(manager):
    estados = []
    manager.set_sink(None, lambda sid, estado, detalle: estados.append((estado, sid)))
    sesion = manager.crear()
    manager.close(sesion.id)
    assert estados == [("abierta", sesion.id), ("cerrada", sesion.id)]


def test_manager_listado_describe_las_pestanas(manager):
    primera = manager.crear()
    segunda = manager.crear()
    filas = manager.listado()
    assert [f["id"] for f in filas] == [primera.id, segunda.id]
    assert [f["activa"] for f in filas] == [False, True]
    assert filas[0]["titulo"] and filas[0]["cwd"]


# --------------------------------------------------------------------------- seguridad

def test_abrir_la_terminal_es_amarillo():
    assert security_manager.classify_action("terminal_open") == RiskLevel.YELLOW


@pytest.mark.parametrize("accion", ["terminal_run_command", "terminal_read_output"])
def test_las_herramientas_del_agente_son_amarillas(accion):
    import agents.tool_registry  # noqa: F401  (registra los tools al importarse)

    assert security_manager.classify_action(accion) == RiskLevel.YELLOW


@pytest.mark.parametrize(
    "canal", [ChannelType.TELEGRAM, ChannelType.DISCORD, ChannelType.VOICE, ChannelType.EMAIL]
)
@pytest.mark.parametrize(
    "accion", ["terminal_open", "terminal_run_command", "terminal_read_output"]
)
def test_la_terminal_no_es_alcanzable_desde_ningun_canal_remoto(accion, canal):
    """Una shell libre disparable por un mensaje de Telegram —o peor, por un correo que
    manda cualquiera— es exactamente lo que el modelo de canales existe para impedir. Se
    apoya en CHANNEL_ALLOWED_LEVELS (solo verde fuera del escritorio) y en que no haya
    ninguna excepción en CHANNEL_ACTION_EXCEPTIONS para estas acciones."""
    import agents.tool_registry  # noqa: F401

    assert security_manager.is_action_allowed(accion, canal) is False


@pytest.mark.parametrize(
    "accion", ["terminal_open", "terminal_run_command", "terminal_read_output"]
)
def test_la_terminal_si_es_alcanzable_desde_el_escritorio(accion):
    import agents.tool_registry  # noqa: F401

    assert security_manager.is_action_allowed(accion, ChannelType.DESKTOP) is True


def test_el_comando_va_al_texto_de_confirmacion():
    """El "sí" del modal se da sobre el comando exacto: si `command` no estuviera entre las
    claves permitidas de `format_details()`, se autorizaría a ciegas."""
    from core.security_manager import format_details

    detalle = format_details("tool:terminal_run_command", {"command": "git push --force"})
    assert "git push --force" in detalle


def test_la_herramienta_del_agente_sin_comando_no_abre_nada():
    from agents.tool_registry import get_tool

    respuesta = get_tool("terminal_run_command").invoke({})
    assert "comando" in respuesta.lower()


def test_leer_la_salida_sin_terminal_abierta_avisa(monkeypatch):
    from agents.tool_registry import get_tool

    monkeypatch.setattr("core.terminal_session.terminal_manager.active", lambda: None)
    assert "no hay" in get_tool("terminal_read_output").invoke({}).lower()


def test_leer_la_salida_devuelve_el_historial(monkeypatch):
    from agents.tool_registry import get_tool

    sesion = TerminalSession()
    sesion._pantalla.feed("dir" + CR + LF + "archivo.txt" + CR + LF)
    monkeypatch.setattr("core.terminal_session.terminal_manager.active", lambda: sesion)

    respuesta = get_tool("terminal_read_output").invoke({"lines": 5})
    assert "archivo.txt" in respuesta
