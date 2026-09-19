"""
tests/test_workspace_tools_seguridad.py
REQ-029/CA-05 a CA-09, CA-13, CA-14, CA-15 — la parte de seguridad de las 8 herramientas.

Lo que se fija acá:

- Los niveles con que se registran (CA-05), y que los dos lugares que las registran
  —`core/security_manager.py` y `agents/tool_registry.py`— digan lo mismo.
- Que NINGUNA sea alcanzable fuera del escritorio, ni siquiera las verdes, recorriendo los
  7 canales (CA-06).
- Que `DESKTOP_ONLY_ACTIONS` solo pueda RESTAR permisos, nunca sumarlos (CA-07): es la
  operación inversa de `CHANNEL_ACTION_EXCEPTIONS`, que es aditiva.
- Que la confirmación amarilla muestre la ruta (CA-08) y que el camino de ejecución sea
  `execute_tool()` con su gate, no uno propio (CA-09).
- Que git corra sin shell y con lista blanca de subcomandos (CA-13).

Convenciones (.claude/rules/testing.md): `CODE_WORKSPACES_FILE` se redirige a `tmp_path`,
así que ningún test lee el archivo real ni opera sobre carpetas del proyecto; git nunca se
ejecuta contra el repositorio de O.R.I.O.N. — los tests de `workspace_git` sustituyen
`subprocess.run` por un doble que solo registra con qué lo llamaron.
"""

import os

import pytest

import agents.tool_registry as tool_registry
import core.workspace_config as workspace_config
import core.workspace_git as wg
from core.security_manager import (CHANNEL_ACTION_EXCEPTIONS, CHANNEL_ALLOWED_LEVELS,
                                   DESKTOP_ONLY_ACTIONS, ActionDenied, ChannelType,
                                   RiskLevel, format_details, security_manager)

#: Las 8 de v1 y el nivel con que tienen que quedar registradas (SPEC-029, tabla de tools).
NIVELES_ESPERADOS = {
    "file_list": RiskLevel.GREEN,
    "file_read": RiskLevel.GREEN,
    "file_search": RiskLevel.GREEN,
    "file_write": RiskLevel.YELLOW,
    "file_edit": RiskLevel.YELLOW,
    "git_status": RiskLevel.GREEN,
    "git_diff": RiskLevel.GREEN,
    "git_log": RiskLevel.GREEN,
}

#: REQ-030 — las dos que deciden SOBRE QUE CARPETAS trabajan las 8 de arriba. Mismo
#: tratamiento de canal: habilitar una carpeta por un mensaje remoto sería regalar el
#: confinamiento entero.
NIVELES_REQ030 = {
    "workspace_add_folder": RiskLevel.YELLOW,
    "workspace_remove_folder": RiskLevel.YELLOW,
}

#: REQ-032 — ejecutar en la carpeta del proyecto y ver su estructura.
NIVELES_REQ032 = {
    "project_run": RiskLevel.YELLOW,
    "project_tree": RiskLevel.GREEN,
}

#: REQ-034 — el indice semantico de codigo. Las dos son lecturas.
NIVELES_REQ034 = {
    "code_index": RiskLevel.GREEN,
    "code_search": RiskLevel.GREEN,
}

#: REQ-035 — borrar y mover. Amarillas, y fuera de la lista blanca del modo autonomia.
NIVELES_REQ035 = {
    "file_delete": RiskLevel.YELLOW,
    "file_move": RiskLevel.YELLOW,
}

#: REQ-036 — procesos en segundo plano. Solo arrancar uno es amarillo.
NIVELES_REQ036 = {
    "project_start": RiskLevel.YELLOW,
    "project_output": RiskLevel.GREEN,
    "project_stop": RiskLevel.GREEN,
}

#: REQ-040 — mirar cómo está hecha una plantilla es leer un archivo del usuario: verde, y
#: por lo mismo que `file_read`, solo delante del computador.
NIVELES_REQ040 = {
    "document_inspect": RiskLevel.GREEN,
}

#: REQ-043 — servidores MCP desde el chat. Declarar uno arranca un programa en la
#: máquina y habilitar herramientas abre capacidades: amarillas. Listar y probar son
#: lecturas, pero cuentan qué hay conectado y con qué: las seis solo delante del computador.
NIVELES_REQ043 = {
    "mcp_list_servers": RiskLevel.GREEN,
    "mcp_probe_server": RiskLevel.GREEN,
    "mcp_add_server": RiskLevel.YELLOW,
    "mcp_allow_tools": RiskLevel.YELLOW,
    "mcp_set_server_enabled": RiskLevel.YELLOW,
    "mcp_remove_server": RiskLevel.YELLOW,
}

#: Todas juntas. Las pruebas de canal recorren todas; las que fijan el alcance de REQ-029
#: (el modo "codigo") siguen usando solo las 8 de v1.
TODAS = {**NIVELES_ESPERADOS, **NIVELES_REQ030, **NIVELES_REQ032, **NIVELES_REQ034,
         **NIVELES_REQ035, **NIVELES_REQ036, **NIVELES_REQ040, **NIVELES_REQ043}

TODOS_LOS_CANALES = [
    ChannelType.DESKTOP, ChannelType.TELEGRAM, ChannelType.DISCORD, ChannelType.VOICE,
    ChannelType.API, ChannelType.EMAIL, ChannelType.UNKNOWN,
]


@pytest.fixture(autouse=True)
def sin_configuracion_real(monkeypatch, tmp_path):
    """Ningún test puede leer el `code_workspaces.json` real del proyecto."""
    monkeypatch.setattr(
        workspace_config, "CODE_WORKSPACES_FILE", str(tmp_path / "code_workspaces.json")
    )


@pytest.fixture
def repo_habilitado(monkeypatch, tmp_path):
    """Una raíz habilitada de verdad, dentro de `tmp_path`, vista por `cargar_raices()`."""
    raiz = tmp_path / "repo"
    raiz.mkdir()
    (raiz / "hola.txt").write_text("contenido de prueba\n", encoding="utf-8")
    real = os.path.realpath(str(raiz))
    monkeypatch.setattr(workspace_config, "cargar_raices", lambda: [real])
    return real


# ─────────────────────────── CA-05: niveles ───────────────────────────

@pytest.mark.parametrize("nombre,nivel", sorted(TODAS.items()))
def test_ca05_nivel_registrado_en_security_manager(nombre, nivel):
    assert security_manager.classify_action_base(nombre) == nivel


@pytest.mark.parametrize("nombre,nivel", sorted(TODAS.items()))
def test_ca05_la_toolspec_declara_el_mismo_nivel(nombre, nivel):
    """Las 8 se registran en dos lugares (`security_manager` y la `ToolSpec`). Un
    desacuerdo entre ambos degradaría el nivel en silencio: acá se fija que coincidan."""
    spec = tool_registry.get_tool(nombre)
    assert spec is not None, f"'{nombre}' no está registrada como tool"
    assert spec.risk_level == nivel


def test_ca09_las_8_estan_en_el_registro_y_no_tienen_camino_propio():
    """CA-09 — se ejecutan por `execute_tool()`, que es el gate. Estar en `_REGISTRY` es
    la condición para eso: un tool que no está ahí no se puede invocar."""
    registradas = set(tool_registry.list_tool_names())
    assert set(TODAS) <= registradas


# ─────────────────────────── CA-06: los 7 canales ───────────────────────────

def test_ca06_desktop_only_actions_son_exactamente_las_declaradas():
    """El conjunto exacto, no "al menos": una herramienta de archivos que se cuele fuera de
    esta tabla queda alcanzable desde Telegram sin que nadie lo note."""
    assert DESKTOP_ONLY_ACTIONS == set(TODAS)


@pytest.mark.parametrize("nombre", sorted(TODAS))
@pytest.mark.parametrize("canal", TODOS_LOS_CANALES)
def test_ca06_ninguna_es_alcanzable_fuera_del_escritorio(nombre, canal):
    """Las 8 × los 7 canales. Sin esto, `file_read` es verde y un mensaje de Telegram se
    lleva cualquier archivo de las carpetas habilitadas."""
    permitida = security_manager.is_action_allowed(nombre, canal)
    assert permitida is (canal is ChannelType.DESKTOP)


@pytest.mark.parametrize("nombre", sorted(TODAS))
@pytest.mark.parametrize(
    "canal",
    [c for c in TODOS_LOS_CANALES if c is not ChannelType.DESKTOP],
)
def test_ca06_require_confirmation_las_deniega_fuera_del_escritorio(nombre, canal):
    """El gate real, no solo la consulta: `require_confirmation()` es lo que llama
    `execute_tool()`, y tiene que decir que no sin preguntarle a nadie."""
    assert security_manager.require_confirmation(nombre, canal) is False


@pytest.mark.parametrize("nombre", sorted(TODAS))
def test_ca06_el_motivo_de_la_denegacion_se_explica(nombre):
    motivo = security_manager.explain_denial(nombre, ChannelType.TELEGRAM)
    assert "delante del computador" in motivo


@pytest.mark.parametrize("nombre", sorted(TODAS))
def test_ca06_no_se_le_ofrecen_al_modelo_fuera_del_escritorio(nombre):
    """No es el control de seguridad —ese es `is_action_allowed()`—, pero ofrecerle a
    Telegram una herramienta que se le va a denegar solo le hace gastar una vuelta."""
    ofrecidas = {t["name"] for t in tool_registry.catalogo_para_modelo(ChannelType.TELEGRAM)}
    assert nombre not in ofrecidas


def test_ca06_si_se_le_ofrecen_en_el_escritorio():
    ofrecidas = {t["name"] for t in tool_registry.catalogo_para_modelo(ChannelType.DESKTOP)}
    assert set(TODAS) <= ofrecidas


# ─────────────────────────── CA-07: solo resta, nunca suma ───────────────────────────

def test_ca07_una_excepcion_de_canal_no_reabre_una_herramienta_de_archivos():
    """`CHANNEL_ACTION_EXCEPTIONS` (REQ-018) es aditiva y se evalúa DESPUÉS: ni siquiera
    una entrada explícita puede devolverle `file_read` a Telegram."""
    entrada = (ChannelType.TELEGRAM, "file_read")
    CHANNEL_ACTION_EXCEPTIONS.add(entrada)
    try:
        assert security_manager.is_action_allowed("file_read", ChannelType.TELEGRAM) is False
    finally:
        CHANNEL_ACTION_EXCEPTIONS.discard(entrada)


def test_ca07_agregar_una_accion_a_la_tabla_nunca_la_habilita():
    """La invariante en una frase: para toda acción y todo canal, estar en
    `DESKTOP_ONLY_ACTIONS` solo puede quitar permisos. Se compara el antes y el después
    de agregar una acción cualquiera a la tabla, en los 7 canales."""
    accion = "__accion_de_prueba_desktop_only__"
    security_manager.register_action(accion, RiskLevel.GREEN)
    try:
        antes = {c: security_manager.is_action_allowed(accion, c) for c in TODOS_LOS_CANALES}
        DESKTOP_ONLY_ACTIONS.add(accion)
        try:
            despues = {
                c: security_manager.is_action_allowed(accion, c) for c in TODOS_LOS_CANALES
            }
        finally:
            DESKTOP_ONLY_ACTIONS.discard(accion)
        for canal in TODOS_LOS_CANALES:
            assert not (despues[canal] and not antes[canal]), (
                f"DESKTOP_ONLY_ACTIONS habilitó '{accion}' en {canal.value}: la tabla solo "
                f"puede restar permisos"
            )
    finally:
        security_manager._base_levels.pop(accion, None)
        security_manager._actions.pop(accion, None)


def test_ca07_no_habilita_una_amarilla_en_un_canal_que_solo_admite_verde():
    """El caso concreto: `file_write` es amarilla y Telegram solo admite verde. Estar en
    la tabla no la sube; el escritorio la sigue teniendo porque `CHANNEL_ALLOWED_LEVELS`
    ya se la daba."""
    assert RiskLevel.YELLOW not in CHANNEL_ALLOWED_LEVELS[ChannelType.TELEGRAM]
    assert security_manager.is_action_allowed("file_write", ChannelType.TELEGRAM) is False
    assert security_manager.is_action_allowed("file_write", ChannelType.DESKTOP) is True


def test_ca07_email_sigue_sin_ejecutar_nada():
    """EMAIL tiene lista vacía desde REQ-006 y sigue teniéndola: la tabla nueva no le
    devuelve nada."""
    assert CHANNEL_ALLOWED_LEVELS[ChannelType.EMAIL] == []
    for nombre in TODAS:
        assert security_manager.is_action_allowed(nombre, ChannelType.EMAIL) is False


def test_ca07_las_demas_acciones_no_cambiaron_de_comportamiento():
    """Red de regresión: la tabla nueva no puede alterar lo que ya estaba permitido. Se
    verifica sobre acciones que no son de este REQ, en los 7 canales."""
    for nombre in ("open_app", "chat", "system_info", "shutdown", "terminal_run_command"):
        for canal in TODOS_LOS_CANALES:
            nivel = security_manager.classify_action(nombre)
            esperado = (
                (canal, nombre) in CHANNEL_ACTION_EXCEPTIONS
                or nivel in CHANNEL_ALLOWED_LEVELS.get(canal, [RiskLevel.GREEN])
            )
            assert security_manager.is_action_allowed(nombre, canal) is esperado


# ─────────────────────────── CA-08: la ruta a la vista ───────────────────────────

def test_ca08_la_confirmacion_muestra_la_ruta_exacta():
    """Autorizar una escritura sin ver dónde sería autorizar a ciegas — el mismo motivo
    por el que `terminal_run_command` muestra el comando."""
    detalle = format_details("tool:file_write", {"path": "C:/repo/src/main.py", "content": "x"})
    assert "C:/repo/src/main.py" in detalle


def test_ca08_el_contenido_a_escribir_no_va_al_prompt_ni_a_la_auditoria():
    """`content` NO está en la allowlist a propósito: puede ser largo y puede traer
    secretos, y `details` se imprime al humano y se persiste en audit.db."""
    detalle = format_details("tool:file_write", {"path": "/repo/x.py", "content": "TOKEN=abc123"})
    assert "abc123" not in detalle


def test_ca08_el_fragmento_de_file_edit_tampoco_se_vuelca():
    detalle = format_details(
        "tool:file_edit",
        {"path": "/repo/x.py", "buscar": "clave = 'secreta'", "reemplazar": "clave = None"},
    )
    assert "secreta" not in detalle
    assert "/repo/x.py" in detalle


def test_ca08_la_pregunta_se_lee_en_castellano_con_la_ruta():
    from core.acciones_legibles import pregunta

    texto = pregunta("file_write", format_details("tool:file_write", {"path": "/repo/x.py"}))
    assert "file_write" not in texto
    assert "/repo/x.py" in texto


# ─────────────────────────── CA-09: el camino real ───────────────────────────

def test_ca09_execute_tool_ejecuta_en_escritorio(repo_habilitado):
    salida = tool_registry.execute_tool(
        "file_read", {"path": "hola.txt"}, ChannelType.DESKTOP
    )
    assert "contenido de prueba" in salida


def test_ca09_execute_tool_deniega_desde_telegram(repo_habilitado):
    with pytest.raises(ActionDenied):
        tool_registry.execute_tool("file_read", {"path": "hola.txt"}, ChannelType.TELEGRAM)


def test_ca09_execute_tool_no_lee_el_archivo_cuando_deniega(repo_habilitado):
    """La denegación ocurre ANTES de invocar: el contenido no puede haberse leído."""
    with pytest.raises(ActionDenied) as exc:
        tool_registry.execute_tool("file_read", {"path": "hola.txt"}, ChannelType.VOICE)
    assert "contenido de prueba" not in str(exc.value)


@pytest.fixture
def responder_confirmacion(monkeypatch):
    """Fija qué responde la confirmación de escritorio, y lo deshace al terminar.

    Se toca el registro de `core/confirmation.py` en vez de `builtins.input` porque el
    adaptador de DESKTOP es estado global del proceso: cualquier test que construya una
    `MainWindow` deja registrado el adaptador del webview, y a partir de ahí el `input()`
    del adaptador de `conftest.py` ya no es lo que se consulta. Con `monkeypatch.setitem`
    la sustitución vale para este test y se revierte sola.
    """
    import core.confirmation as confirmation

    def _responder(respuesta: bool) -> None:
        monkeypatch.setitem(
            confirmation._ADAPTERS, ChannelType.DESKTOP, lambda accion, mensaje: respuesta
        )

    return _responder


def test_ca09_file_write_confirmado_escribe(responder_confirmacion, repo_habilitado):
    responder_confirmacion(True)
    tool_registry.execute_tool(
        "file_write", {"path": "creado.txt", "content": "hecho"}, ChannelType.DESKTOP
    )
    with open(os.path.join(repo_habilitado, "creado.txt"), encoding="utf-8") as f:
        assert f.read() == "hecho"


def test_ca09_file_write_cancelado_no_escribe(responder_confirmacion, repo_habilitado):
    responder_confirmacion(False)
    with pytest.raises(ActionDenied):
        tool_registry.execute_tool(
            "file_write", {"path": "no-creado.txt", "content": "x"}, ChannelType.DESKTOP
        )
    assert not os.path.exists(os.path.join(repo_habilitado, "no-creado.txt"))


# ─────────────────────────── CA-14: errores legibles ───────────────────────────

def test_ca14_una_ruta_fuera_de_raiz_vuelve_como_texto_no_como_excepcion(tmp_path, repo_habilitado):
    """El modelo tiene que poder leer qué pasó y qué puede hacer, sin stacktrace."""
    salida = tool_registry.execute_tool(
        "file_read", {"path": str(tmp_path / "afuera.txt")}, ChannelType.DESKTOP
    )
    assert "fuera de las carpetas habilitadas" in salida
    assert "Traceback" not in salida


def test_ca14_sin_carpetas_habilitadas_las_herramientas_no_operan(monkeypatch):
    """CA-02 desde el lado de la herramienta: la feature nace inerte y lo explica."""
    monkeypatch.setattr(workspace_config, "cargar_raices", lambda: [])
    salida = tool_registry.execute_tool(
        "file_read", {"path": "cualquier.txt"}, ChannelType.DESKTOP
    )
    assert "code_workspaces.json" in salida


def test_ca14_file_list_sin_ruta_dice_que_no_hay_carpetas(monkeypatch):
    monkeypatch.setattr(workspace_config, "cargar_raices", lambda: [])
    salida = tool_registry.execute_tool("file_list", {}, ChannelType.DESKTOP)
    assert "code_workspaces.json" in salida


def test_ca03_el_codigo_de_orion_no_se_toca_ni_habilitandolo(monkeypatch):
    """CA-03 por el camino real de la herramienta: aunque la carpeta de instalación esté
    habilitada como raíz, `resolver()` la rechaza y la herramienta lo explica."""
    import core.workspace_files as wf

    instalacion = os.path.realpath(wf._INSTALACION)
    monkeypatch.setattr(workspace_config, "cargar_raices", lambda: [instalacion])
    salida = tool_registry.execute_tool(
        "file_read", {"path": os.path.join(instalacion, "main.py")}, ChannelType.DESKTOP
    )
    assert "mi propio código" in salida


# ─────────────────────────── CA-13: git sin shell ───────────────────────────

class _ProcesoFalso:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def git_espiado(monkeypatch):
    """Sustituye `subprocess.run` en `core/workspace_git.py` y registra cómo se llamó.

    Nunca se ejecuta git de verdad: ni contra el repo del proyecto ni contra ningún otro.
    """
    llamadas = []

    def _falso(comando, **kwargs):
        llamadas.append((comando, kwargs))
        return _ProcesoFalso(stdout="## main\n M archivo.py\n")

    monkeypatch.setattr(wg.subprocess, "run", _falso)
    return llamadas


def test_ca13_la_lista_blanca_es_status_diff_y_log():
    assert wg.SUBCOMANDOS_PERMITIDOS == frozenset({"status", "diff", "log"})


def test_ca13_commit_y_push_no_estan():
    """`.claude/rules/git.md`: los commits los hace el humano."""
    assert "commit" not in wg.SUBCOMANDOS_PERMITIDOS
    assert "push" not in wg.SUBCOMANDOS_PERMITIDOS


def test_ca13_un_subcomando_fuera_de_la_lista_se_bloquea(git_espiado, tmp_path):
    ok, mensaje = wg._correr("push", [], str(tmp_path))
    assert ok is False
    assert "no está permitido" in mensaje
    assert git_espiado == []  # ni se intentó ejecutar


def test_ca13_nunca_se_usa_shell(git_espiado, repo_habilitado):
    wg.estado(raices=[repo_habilitado])
    wg.diff(raices=[repo_habilitado])
    wg.log(raices=[repo_habilitado])
    assert git_espiado
    for comando, kwargs in git_espiado:
        assert kwargs.get("shell") is False
        assert isinstance(comando, list)


def test_ca13_el_comando_se_arma_con_un_subcomando_de_la_lista(git_espiado, repo_habilitado):
    wg.estado(raices=[repo_habilitado])
    comando, kwargs = git_espiado[0]
    assert comando[0] == "git"
    assert any(parte in wg.SUBCOMANDOS_PERMITIDOS for parte in comando[:3])
    assert kwargs.get("cwd") == repo_habilitado


def test_ca13_la_cantidad_de_log_es_un_entero_acotado(git_espiado, repo_habilitado):
    wg.log(cantidad="; rm -rf /", raices=[repo_habilitado])
    comando, _ = git_espiado[0]
    assert "-n10" in comando
    assert not any(";" in str(parte) for parte in comando)


def test_ca13_una_cantidad_absurda_se_recorta(git_espiado, repo_habilitado):
    wg.log(cantidad=10_000, raices=[repo_habilitado])
    comando, _ = git_espiado[0]
    assert "-n50" in comando


def test_ca13_el_archivo_del_diff_pasa_por_el_confinamiento(git_espiado, repo_habilitado, tmp_path):
    from core.workspace_files import RutaFueraDeRaiz

    with pytest.raises(RutaFueraDeRaiz):
        wg.diff(archivo=str(tmp_path / "privado" / "secreto.txt"), raices=[repo_habilitado])
    assert git_espiado == []


def test_ca13_el_archivo_del_diff_va_detras_de_un_separador(git_espiado, repo_habilitado):
    with open(os.path.join(repo_habilitado, "hola.txt"), "a", encoding="utf-8") as f:
        f.write("cambio\n")
    wg.diff(archivo="hola.txt", raices=[repo_habilitado])
    comando, _ = git_espiado[0]
    assert "--" in comando
    assert comando.index("--") < comando.index("hola.txt")


def test_ca13_sin_carpetas_habilitadas_git_no_corre(git_espiado, monkeypatch):
    monkeypatch.setattr(workspace_config, "cargar_raices", lambda: [])
    salida = wg.estado()
    assert "code_workspaces.json" in salida
    assert git_espiado == []


def test_una_carpeta_que_no_es_repo_se_explica(monkeypatch, repo_habilitado):
    def _falso(comando, **kwargs):
        return _ProcesoFalso(returncode=128, stderr="fatal: not a git repository")

    monkeypatch.setattr(wg.subprocess, "run", _falso)
    assert "no es un repositorio git" in wg.estado(raices=[repo_habilitado])


# ─────────────────────────── CA-15: el modo "codigo" ───────────────────────────

def test_ca15_el_modo_codigo_ofrece_primero_las_herramientas_de_repo():
    from core.composer_modes import get_mode

    modo = get_mode("codigo")
    assert modo is not None
    assert set(NIVELES_ESPERADOS) <= set(modo.tool_names)
    # Las de repositorio van antes que EXECUTE_CODE: en este modo lo habitual es trabajar
    # sobre un repo que ya existe, no generar un script suelto.
    assert modo.tool_names.index("file_read") < modo.tool_names.index("EXECUTE_CODE")


def test_ca15_el_presupuesto_de_req_027_no_se_toca():
    from core.composer_modes import get_mode

    assert get_mode("codigo").presupuesto == 40
