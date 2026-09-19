"""
tests/test_remote_tools_policy.py
Punto 1 del plan: allow-list de herramientas remotas (MCP) y canal de entrada no confiable.

Lo que protege esta suite: **que nada de afuera pueda decidir qué puede hacer O.R.I.O.N.**
Un servidor MCP declara sus propias herramientas, en runtime, y las describe él mismo. Un
correo lo escribe cualquier persona del mundo. Ninguno de los dos puede terminar
ejecutando algo en una máquina donde el agente apaga el PC y borra archivos.

Las dos mitades son fail-CLOSED, al revés que `ai/provider_health.py`: ante la duda, no.

Ningún test toca la red ni un servidor MCP real.
"""

import json

import pytest

from agents.tool_registry import ToolSpec, register_tool
import agents.tool_registry as registry
from core import remote_tools_policy as politica
from core.confirmation import get_confirmation_adapter
from core.security_manager import (
    CHANNEL_ACTION_EXCEPTIONS,
    ChannelType,
    RiskLevel,
    security_manager,
)


@pytest.fixture
def allowlist(monkeypatch, tmp_path):
    """Devuelve una función para escribir la allow-list en un archivo temporal."""
    ruta = tmp_path / "mcp_allowlist.json"
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(ruta))

    def escribir(contenido):
        ruta.write_text(
            contenido if isinstance(contenido, str) else json.dumps(contenido),
            encoding="utf-8",
        )
        return ruta

    return escribir


@pytest.fixture(autouse=True)
def _limpiar_registro():
    """El registro de tools es global: no dejar que un test contamine a los demás."""
    original = dict(registry._REGISTRY)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(original)


# ── Allow-list: fail-closed ─────────────────────────────────────────

def test_sin_archivo_no_se_permite_nada(monkeypatch, tmp_path):
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(tmp_path / "no-existe.json"))

    assert politica.load_allowlist() == {}
    assert not politica.is_tool_allowed("notion", "search")


def test_un_archivo_corrupto_no_permite_nada(allowlist):
    """Lo contrario de provider_health: en seguridad, ante la duda, NO."""
    allowlist("{esto no es json")

    assert politica.load_allowlist() == {}
    assert not politica.is_tool_allowed("notion", "search")


def test_un_json_valido_pero_absurdo_no_permite_nada(allowlist):
    allowlist(["una", "lista"])

    assert politica.load_allowlist() == {}


def test_lo_nombrado_se_permite(allowlist):
    allowlist({"notion": ["search", "create_page"]})

    assert politica.is_tool_allowed("notion", "search")
    assert politica.is_tool_allowed("notion", "create_page")


def test_lo_no_nombrado_no_se_permite(allowlist):
    """El caso que motiva todo: el servidor agrega un tool nuevo y nadie lo aprobó."""
    allowlist({"notion": ["search"]})

    assert not politica.is_tool_allowed("notion", "delete_everything")


def test_un_servidor_que_no_esta_no_aporta_nada(allowlist):
    allowlist({"notion": ["search"]})

    assert not politica.is_tool_allowed("servidor_desconocido", "search")


def test_los_patrones_glob_funcionan(allowlist):
    allowlist({"calendar": ["read_*"]})

    assert politica.is_tool_allowed("calendar", "read_events")
    assert politica.is_tool_allowed("calendar", "read_free_busy")
    assert not politica.is_tool_allowed("calendar", "write_event")


def test_el_nombre_no_distingue_mayusculas(allowlist):
    allowlist({"Notion": ["Search"]})

    assert politica.is_tool_allowed("notion", "search")


def test_una_entrada_invalida_no_arrastra_a_las_demas(allowlist):
    allowlist({"roto": "no soy una lista", "notion": ["search"]})

    assert politica.is_tool_allowed("notion", "search")
    assert not politica.is_tool_allowed("roto", "cualquier_cosa")


# ── Namespace: que un tool remoto no pise uno local ─────────────────

def test_el_nombre_calificado_lleva_servidor_y_tool():
    assert politica.nombre_calificado("notion", "search") == "mcp__notion__search"


def test_el_nombre_calificado_se_puede_deshacer():
    nombre = politica.nombre_calificado("notion", "search")

    assert politica.parse_nombre_calificado(nombre) == ("notion", "search")


def test_un_nombre_sin_prefijo_no_es_remoto():
    """`task_create` es un tool local: no puede interpretarse como remoto."""
    assert politica.parse_nombre_calificado("task_create") is None


def test_un_nombre_remoto_malformado_no_se_arregla():
    assert politica.parse_nombre_calificado("mcp__solo_servidor") is None
    assert politica.parse_nombre_calificado("mcp____sin_servidor") is None
    assert politica.parse_nombre_calificado("mcp__servidor__") is None


# ── register_tool con tools remotos ─────────────────────────────────

def _spec(nombre, riesgo=RiskLevel.GREEN, origin="mcp_remote"):
    return ToolSpec(
        name=nombre,
        description="tool de prueba",
        parameters_schema={"type": "object", "properties": {}},
        risk_level=riesgo,
        invoke=lambda params: "ok",
        origin=origin,
    )


def test_un_tool_local_se_registra_como_siempre(allowlist):
    """Retrocompatibilidad: los ~10 register_tool() existentes no cambian."""
    allowlist({})

    assert register_tool(_spec("tool_local_de_prueba", origin="local")) is True
    assert registry.get_tool("tool_local_de_prueba") is not None


def test_un_tool_remoto_sin_namespace_se_rechaza(allowlist):
    """Sin esto, un servidor que publique 'task_create' pisa el tool local."""
    allowlist({"notion": ["task_create"]})

    assert register_tool(_spec("task_create")) is False


def test_un_tool_remoto_fuera_de_la_allowlist_se_rechaza(allowlist):
    allowlist({"notion": ["search"]})

    assert register_tool(_spec("mcp__notion__delete_everything")) is False
    assert registry.get_tool("mcp__notion__delete_everything") is None


def test_un_tool_remoto_permitido_se_registra(allowlist):
    allowlist({"notion": ["search"]})

    assert register_tool(_spec("mcp__notion__search")) is True
    assert registry.get_tool("mcp__notion__search") is not None


def test_un_tool_remoto_nunca_queda_en_verde(allowlist):
    """El servidor lo declara inofensivo; un tercero no decide eso en esta máquina."""
    allowlist({"notion": ["search"]})

    register_tool(_spec("mcp__notion__search", riesgo=RiskLevel.GREEN))

    assert security_manager.classify_action("mcp__notion__search") == RiskLevel.YELLOW


def test_un_tool_remoto_declarado_rojo_sigue_rojo(allowlist):
    """Se sube el nivel cuando hace falta, nunca se baja: max(nuestro, ajeno)."""
    allowlist({"infra": ["drop_db"]})

    register_tool(_spec("mcp__infra__drop_db", riesgo=RiskLevel.RED))

    assert security_manager.classify_action("mcp__infra__drop_db") == RiskLevel.RED


def test_sin_allowlist_ningun_tool_remoto_entra(monkeypatch, tmp_path):
    """El estado por defecto del sistema: no hay archivo, no entra nada."""
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(tmp_path / "no-existe.json"))

    assert register_tool(_spec("mcp__notion__search")) is False


# ── Canal EMAIL: entrada no confiable ───────────────────────────────

def test_el_canal_email_se_resuelve_desde_string():
    assert security_manager.resolve_channel("email") == ChannelType.EMAIL


def test_el_canal_email_no_permite_ni_siquiera_verde():
    """`open_app` es verde, y bastaría para que un correo abra una URL elegida por quien
    lo escribió. El canal lee y resume; no ejecuta."""
    security_manager.register_action("accion_verde_de_prueba", RiskLevel.GREEN)

    assert not security_manager.require_confirmation(
        "accion_verde_de_prueba", ChannelType.EMAIL
    )


def test_los_canales_de_siempre_siguen_permitiendo_verde():
    """El chequeo de canal agregado al camino VERDE no puede romper lo que ya andaba."""
    security_manager.register_action("otra_accion_verde_de_prueba", RiskLevel.GREEN)

    for canal in (
        ChannelType.DESKTOP, ChannelType.TELEGRAM, ChannelType.DISCORD,
        ChannelType.VOICE, ChannelType.API, ChannelType.UNKNOWN,
    ):
        assert security_manager.require_confirmation("otra_accion_verde_de_prueba", canal), canal


def test_el_canal_email_no_tiene_a_quien_preguntar_salvo_lo_preautorizado():
    """Hasta REQ-049 no había adaptador y todo YELLOW moría por fail-closed. Ahora hay uno
    (`core/email_commands.confirmar_por_correo`) que aprueba ÚNICAMENTE herramientas remotas
    con excepción de canal para EMAIL, o sea las de solo lectura que el usuario habilitó
    para correo. Para cualquier otra acción amarilla la respuesta sigue siendo no, haya o
    no adaptador registrado."""
    from core.confirmation import register_confirmation_adapter
    from core.email_commands import confirmar_por_correo

    security_manager.register_action("accion_amarilla_de_prueba", RiskLevel.YELLOW)

    # Sin adaptador (proceso recién arrancado sin main.py): fail-closed.
    if get_confirmation_adapter(ChannelType.EMAIL) is None:
        assert not security_manager.require_confirmation(
            "accion_amarilla_de_prueba", ChannelType.EMAIL
        )

    # Con el adaptador real: sigue siendo no, aunque tuviera excepción de canal, porque
    # no es una herramienta remota.
    register_confirmation_adapter(ChannelType.EMAIL, confirmar_por_correo)
    CHANNEL_ACTION_EXCEPTIONS.add((ChannelType.EMAIL, "accion_amarilla_de_prueba"))
    try:
        assert not security_manager.require_confirmation(
            "accion_amarilla_de_prueba", ChannelType.EMAIL
        )
    finally:
        CHANNEL_ACTION_EXCEPTIONS.discard((ChannelType.EMAIL, "accion_amarilla_de_prueba"))


def test_la_denegacion_de_email_se_explica_en_castellano():
    security_manager.register_action("accion_verde_explicable", RiskLevel.GREEN)

    motivo = security_manager.explain_denial("accion_verde_explicable", ChannelType.EMAIL)

    assert "solo lee y resume" in motivo


def test_la_lista_vacia_no_rompe_la_excepcion_quirurgica():
    """Si algún día una acción concreta tiene que habilitarse en correo, el mecanismo
    existente sigue sirviendo — `is_action_allowed` evalúa las excepciones primero."""
    security_manager.register_action("accion_verde_exceptuada", RiskLevel.GREEN)
    CHANNEL_ACTION_EXCEPTIONS.add((ChannelType.EMAIL, "accion_verde_exceptuada"))
    try:
        assert security_manager.require_confirmation(
            "accion_verde_exceptuada", ChannelType.EMAIL
        )
    finally:
        CHANNEL_ACTION_EXCEPTIONS.discard((ChannelType.EMAIL, "accion_verde_exceptuada"))
