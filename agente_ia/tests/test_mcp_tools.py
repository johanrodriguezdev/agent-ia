"""
tests/test_mcp_tools.py
REQ-043 — las seis herramientas `mcp_*` del agente (`agents/tool_registry.py`).

Lo que protege esta suite:
- Niveles: listar y probar son verdes; agregar, permitir, encender/apagar y quitar son
  amarillas (CA-08..CA-13). Las seis son solo de escritorio (CA-14).
- La confirmación muestra lo que hay que ver: el comando completo o la URL al agregar, y
  las herramientas y canales al permitir (CA-10, CA-11).
- Las herramientas remotas registradas tienen frase legible (CA-15).
- El flujo agregar → permitir con un servidor falso, sin proceso ni red (CA-16).
"""

import json

import pytest

import agents.tool_registry as registry
import config_manager
from core import mcp_config, mcp_manager
from core import remote_tools_policy as politica
from core.acciones_legibles import _DESCRIPCIONES, describir, pregunta
from core.security_manager import (
    CHANNEL_ACTION_EXCEPTIONS,
    DESKTOP_ONLY_ACTIONS,
    ChannelType,
    RiskLevel,
    format_details,
    security_manager,
)

HERRAMIENTAS = (
    "mcp_list_servers", "mcp_probe_server", "mcp_add_server",
    "mcp_allow_tools", "mcp_set_server_enabled", "mcp_remove_server",
)
VERDES = ("mcp_list_servers", "mcp_probe_server")


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(mcp_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(tmp_path / "mcp_allowlist.json"))
    mcp_manager._CLIENTES.clear()
    yield
    mcp_manager._CLIENTES.clear()


def _invoke(nombre):
    spec = registry.get_tool(nombre)
    assert spec is not None, nombre
    return spec.invoke


# ── registro y niveles ──────────────────────────────────────────────

def test_las_seis_estan_registradas_con_su_nivel():
    for nombre in HERRAMIENTAS:
        spec = registry.get_tool(nombre)
        assert spec is not None, nombre
        esperado = RiskLevel.GREEN if nombre in VERDES else RiskLevel.YELLOW
        assert spec.risk_level is esperado, nombre
        assert security_manager._actions[nombre] is esperado, nombre


def test_las_seis_son_solo_de_escritorio():
    for nombre in HERRAMIENTAS:
        assert nombre in DESKTOP_ONLY_ACTIONS, nombre
        assert not any(accion == nombre for _, accion in CHANNEL_ACTION_EXCEPTIONS), nombre


@pytest.mark.parametrize("canal", [ChannelType.TELEGRAM, ChannelType.DISCORD, ChannelType.VOICE])
def test_ningun_canal_remoto_las_alcanza_ni_se_las_ofrece(canal):
    for nombre in HERRAMIENTAS:
        assert not security_manager.is_action_allowed(nombre, canal), (nombre, canal)
    ofrecidas = {t["name"] for t in registry.catalogo_para_modelo(canal)}
    assert not ofrecidas & set(HERRAMIENTAS)


def test_en_escritorio_si_se_ofrecen():
    ofrecidas = {t["name"] for t in registry.catalogo_para_modelo(ChannelType.DESKTOP)}
    assert set(HERRAMIENTAS) <= ofrecidas


# ── confirmación legible ────────────────────────────────────────────

def test_las_amarillas_tienen_frase_escrita_a_mano():
    for nombre in set(HERRAMIENTAS) - set(VERDES):
        assert nombre in _DESCRIPCIONES, nombre


def test_la_confirmacion_de_agregar_muestra_el_comando_completo():
    detalle = format_details(
        "tool:mcp_add_server", {"name": "notion", "command": "npx -y @notionhq/notion-mcp-server"},
    )
    texto = pregunta("mcp_add_server", detalle)

    assert "conecte un servidor MCP nuevo" in texto
    assert "notion" in texto
    assert "npx -y @notionhq/notion-mcp-server" in texto


def test_la_confirmacion_de_agregar_remoto_muestra_la_url():
    texto = pregunta(
        "mcp_add_server", format_details("tool:mcp_add_server", {"name": "docs", "url": "https://x.y/mcp"}),
    )

    assert "https://x.y/mcp" in texto


def test_la_confirmacion_de_permitir_muestra_herramientas_y_canales():
    detalle = format_details(
        "tool:mcp_allow_tools",
        {"name": "notion", "herramientas": ["search", "create_page"], "canales": ["desktop", "telegram"]},
    )
    texto = pregunta("mcp_allow_tools", detalle)

    assert "search / create_page" in texto
    assert "desktop / telegram" in texto
    assert "[" not in texto            # nada de `repr` de listas


def test_una_herramienta_remota_registrada_se_describe_con_su_servidor():
    assert describir("mcp__notion__search") == "use la herramienta 'search' del servidor MCP 'notion'"
    assert describir("mcp__solo") == "ejecute mcp solo"     # malformada: cae en la derivada


# ── flujo con un servidor falso ─────────────────────────────────────

class ClienteFalso:
    def __init__(self):
        self.cerrado = False

    def list_tools(self):
        return [{"name": "search"}, {"name": "create_page"}]

    def call_tool(self, nombre, argumentos=None):
        return f"{nombre} ok"

    def close(self):
        self.cerrado = True


def _recargar_falso(monkeypatch):
    """`recargar_servidor` que conecta un `ClienteFalso` y registra lo permitido, sin red."""
    def recargar(nombre):
        mcp_manager.desregistrar_servidor(nombre)
        cliente = ClienteFalso()
        mcp_manager.registrar_tools(cliente, nombre)
        return "ok"

    monkeypatch.setattr(mcp_manager, "recargar_servidor", recargar)


def test_agregar_conecta_lista_y_no_habilita_nada(entorno, monkeypatch):
    _recargar_falso(monkeypatch)

    resultado = _invoke("mcp_add_server")({
        "name": "notion", "command": "npx -y @notionhq/notion-mcp-server",
        "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"},
    })

    assert "'notion' conectado" in resultado
    assert "search" in resultado and "create_page" in resultado
    assert "Ninguna está habilitada todavía" in resultado
    assert registry.get_tool("mcp__notion__search") is None
    assert "NOTION_TOKEN" in resultado


def test_permitir_registra_solo_lo_nombrado(entorno, monkeypatch):
    _recargar_falso(monkeypatch)
    _invoke("mcp_add_server")({"name": "notion", "command": "npx x"})

    resultado = _invoke("mcp_allow_tools")({"name": "notion", "herramientas": ["search"]})

    assert "Habilitadas 1: search" in resultado
    assert registry.get_tool("mcp__notion__search") is not None
    assert registry.get_tool("mcp__notion__create_page") is None
    mcp_manager.desregistrar_servidor("notion")


def test_permitir_con_comodin_avisa(entorno, monkeypatch):
    _recargar_falso(monkeypatch)
    _invoke("mcp_add_server")({"name": "notion", "command": "npx x"})

    resultado = _invoke("mcp_allow_tools")({"name": "notion", "herramientas": ["*"]})

    assert "CUALQUIER herramienta" in resultado
    mcp_manager.desregistrar_servidor("notion")


def test_agregar_no_acepta_args_que_el_modal_no_muestra(entorno, monkeypatch):
    """El comando va COMPLETO en `command`, que es lo que ve el humano al confirmar. Un
    `args` aparte se ejecutaría sin haberse mostrado."""
    _recargar_falso(monkeypatch)
    spec = registry.get_tool("mcp_add_server")
    assert "args" not in spec.parameters_schema["properties"]

    _invoke("mcp_add_server")({"name": "x", "command": "npx", "args": ["-y", "malo"]})

    assert mcp_config.listar_servidores()[0]["destino"] == "npx"
    mcp_manager.desregistrar_servidor("x")


def test_un_secreto_literal_vuelve_como_rechazo_en_palabras(entorno):
    resultado = _invoke("mcp_add_server")({
        "name": "notion", "command": "npx x", "env": {"NOTION_TOKEN": "ntn_secreto"},
    })

    assert "nunca el secreto escrito" in resultado
    assert mcp_config.listar_servidores() == []


def test_listar_sin_servidores_lo_dice(entorno):
    assert "No hay ningún servidor MCP" in _invoke("mcp_list_servers")({})


def test_listar_con_servidores_describe_cada_uno(entorno, monkeypatch):
    _recargar_falso(monkeypatch)
    _invoke("mcp_add_server")({"name": "notion", "command": "npx x"})
    _invoke("mcp_allow_tools")({"name": "notion", "herramientas": ["search"]})

    texto = _invoke("mcp_list_servers")({})

    assert "notion (stdio: npx x)" in texto
    assert "1 herramienta(s) habilitada(s)" in texto
    assert "permitidas: search" in texto
    mcp_manager.desregistrar_servidor("notion")


def test_deshabilitar_desregistra_y_habilitar_vuelve_a_conectar(entorno, monkeypatch):
    _recargar_falso(monkeypatch)
    _invoke("mcp_add_server")({"name": "notion", "command": "npx x"})
    _invoke("mcp_allow_tools")({"name": "notion", "herramientas": ["search"]})

    apagado = _invoke("mcp_set_server_enabled")({"name": "notion", "enabled": False})
    assert "deshabilitado" in apagado
    assert registry.get_tool("mcp__notion__search") is None

    encendido = _invoke("mcp_set_server_enabled")({"name": "notion", "enabled": True})
    assert "'notion' conectado" in encendido
    assert registry.get_tool("mcp__notion__search") is not None
    mcp_manager.desregistrar_servidor("notion")


def test_set_enabled_sin_booleano_pide_el_dato(entorno):
    assert "true" in _invoke("mcp_set_server_enabled")({"name": "notion", "enabled": "si"})


def test_quitar_desconecta_y_borra_todo(entorno, monkeypatch):
    _recargar_falso(monkeypatch)
    _invoke("mcp_add_server")({"name": "notion", "command": "npx x"})
    _invoke("mcp_allow_tools")({"name": "notion", "herramientas": ["search"]})

    resultado = _invoke("mcp_remove_server")({"name": "notion"})

    assert "quitado" in resultado
    assert registry.get_tool("mcp__notion__search") is None
    assert mcp_config.listar_servidores() == []
    assert "No había" in _invoke("mcp_remove_server")({"name": "notion"})


def test_probar_un_servidor_no_declarado_lo_dice(entorno):
    assert "No hay ningún servidor" in _invoke("mcp_probe_server")({"name": "fantasma"})
    assert "Necesito el nombre" in _invoke("mcp_probe_server")({})


def test_la_plantilla_de_config_muestra_la_forma_de_un_servidor():
    import os

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(mcp_config.__file__)))
    with open(os.path.join(raiz, "config.example.json"), encoding="utf-8") as f:
        plantilla = json.load(f)

    assert "mcp_servers" in plantilla and "mcp_variables" in plantilla
    for definicion in plantilla["mcp_servers"].values():
        assert definicion.get("enabled") is False       # de ejemplo: no arranca nada solo
        for valor in (definicion.get("env") or {}).values():
            assert valor.startswith("${")                # nunca un secreto literal
