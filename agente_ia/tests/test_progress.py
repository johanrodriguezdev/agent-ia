"""
tests/test_progress.py
Pruebas de `core/progress.py` — la línea de estado que cuenta qué hace el agente.

Este módulo se llama desde dentro de la resolución de cada mensaje, así que el invariante
que protege esta suite no es que informe bien, sino que **no pueda estorbar**: si el
reportero falla, si nadie escucha, si el mensaje viene vacío, la ejecución continúa igual.
Contar lo que se hace nunca puede romper lo que se hace.
"""

import pytest

from core import progress


@pytest.fixture(autouse=True)
def _sin_reportero():
    progress.clear_reporter()
    yield
    progress.clear_reporter()


# ── Camino normal ───────────────────────────────────────────────────

def test_el_reportero_recibe_lo_que_se_reporta():
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report("Buscando en internet")

    assert recibidos == ["Buscando en internet"]


def test_registrar_otro_reportero_reemplaza_al_anterior():
    primero, segundo = [], []
    progress.register_reporter(primero.append)
    progress.register_reporter(segundo.append)

    progress.report("algo")

    assert primero == []
    assert segundo == ["algo"]


def test_retirar_el_reportero_deja_de_entregar():
    recibidos = []
    progress.register_reporter(recibidos.append)
    progress.clear_reporter()

    progress.report("algo")

    assert recibidos == []


# ── No puede estorbar ───────────────────────────────────────────────

def test_sin_reportero_no_falla():
    """Consola, Telegram y tests corren sin nadie escuchando."""
    progress.report("nadie me oye")      # no debe lanzar


def test_un_reportero_que_falla_no_rompe_la_ejecucion():
    """Un fallo contando lo que se hace jamás puede tumbar lo que se está haciendo."""
    def _explota(_mensaje):
        raise RuntimeError("la interfaz se cayó")

    progress.register_reporter(_explota)

    progress.report("esto no debe propagarse")   # no debe lanzar


def test_un_mensaje_vacio_no_llega_al_reportero():
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report("")
    progress.report(None)

    assert recibidos == []


# ── Traducción a lenguaje humano ────────────────────────────────────

def test_las_herramientas_se_anuncian_con_nombre_entendible():
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report_tool("web_search", "ultima version de python")

    assert recibidos == ["Buscando en internet: ultima version de python"]
    assert "web_search" not in recibidos[0]


def test_una_herramienta_desconocida_igual_se_anuncia():
    """Mejor un nombre técnico que el silencio."""
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report_tool("herramienta_nueva")

    assert recibidos == ["Usando herramienta_nueva"]


def test_el_detalle_largo_se_recorta():
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report_tool("web_search", "x" * 200)

    assert len(recibidos[0]) < 120
    assert recibidos[0].endswith("…")


def test_el_detalle_se_aplana_a_una_linea():
    """Es una línea de estado: un salto de línea la rompería."""
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report_tool("web_search", "una consulta\ncon salto\t y tabulador")

    assert "\n" not in recibidos[0]
    assert "\t" not in recibidos[0]


def test_sin_detalle_solo_se_anuncia_la_accion():
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report_tool("task_list")

    assert recibidos == ["Revisando tus tareas"]


# ── Integración con la ejecución de herramientas ────────────────────

def test_ejecutar_una_herramienta_reporta_su_progreso(monkeypatch):
    from agents.tool_registry import ToolSpec, execute_tool, register_tool
    from core.security_manager import ChannelType, RiskLevel

    register_tool(ToolSpec(
        name="web_search", description="x", parameters_schema={},
        risk_level=RiskLevel.GREEN, invoke=lambda p: "resultado",
    ))

    recibidos = []
    progress.register_reporter(recibidos.append)

    execute_tool("web_search", {"query": "gatos"}, ChannelType.DESKTOP, "owner")

    assert any("Buscando en internet: gatos" in m for m in recibidos)


def test_una_herramienta_denegada_no_anuncia_que_la_esta_haciendo(monkeypatch):
    """Si el gate la va a denegar, decir que se está haciendo sería mentir."""
    from agents.tool_registry import ToolSpec, execute_tool, register_tool
    from core.security_manager import ActionDenied, ChannelType, RiskLevel

    from core.security_manager import security_manager

    register_tool(ToolSpec(
        name="tool_denegada", description="x", parameters_schema={},
        risk_level=RiskLevel.GREEN, invoke=lambda p: "no deberia ejecutarse",
    ))
    monkeypatch.setattr(
        security_manager, "require_confirmation", lambda *a, **k: False,
    )

    recibidos = []
    progress.register_reporter(recibidos.append)

    with pytest.raises(ActionDenied):
        execute_tool("tool_denegada", {}, ChannelType.DESKTOP, "owner")

    assert recibidos == []


def test_una_herramienta_remota_se_anuncia_con_su_servidor():
    """REQ-053 — `mcp__notion__search` no le dice nada a nadie; «Consultando notion» sí."""
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report_tool("mcp__notion__search")
    progress.report_tool("mcp__docs__read_page", "Cierre Q3")

    assert recibidos == ["Consultando notion: search", "Consultando docs: read_page: Cierre Q3"]


def test_las_herramientas_de_archivos_y_terminal_tienen_texto_propio():
    recibidos = []
    progress.register_reporter(recibidos.append)

    progress.report_tool("file_read", "C:/proyecto/main.py")
    progress.report_tool("terminal_run_command", "git status")
    progress.report_tool("connection_map")

    assert recibidos == [
        "Leyendo el archivo: C:/proyecto/main.py",
        "Ejecutando en la terminal: git status",
        "Mirando qué hay conectado",
    ]
