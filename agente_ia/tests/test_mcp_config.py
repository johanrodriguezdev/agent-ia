"""
tests/test_mcp_config.py
REQ-043 — `core/mcp_config.py`: declarar, permitir, apagar y quitar servidores MCP sin
editar JSON, y que ningún secreto pase por el chat.

Lo que protege esta suite:
- Un secreto literal en `env`/`headers` se rechaza (CA-02): lo que el modelo escribe viaja
  al proveedor del modelo.
- La allow-list se escribe conservando lo de otros servidores, sin `email` y siempre con
  `desktop` (CA-03).
- `definir_variable()` solo acepta nombres que algún servidor use (CA-06): el slot que la
  llama es alcanzable desde cualquier script de la página.
- `listar_servidores()` nunca incluye el valor de una variable (CA-05).

`config.json` y `mcp_allowlist.json` viven en `tmp_path`; nada conecta a un servidor real.
"""

import json

import pytest

import config_manager
from core import mcp_config, mcp_manager
from core import remote_tools_policy as politica
from core.mcp_client import expandir_secreto
from core.mcp_config import MCPConfigRechazada


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    allow_path = tmp_path / "mcp_allowlist.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(mcp_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(allow_path))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    mcp_manager._CLIENTES.clear()
    yield {"config": config_path, "allow": allow_path}
    mcp_manager._CLIENTES.clear()


def _config(entorno):
    return json.loads(entorno["config"].read_text(encoding="utf-8"))


def _allow(entorno):
    return json.loads(entorno["allow"].read_text(encoding="utf-8"))


# ── nombres ─────────────────────────────────────────────────────────

def test_el_nombre_se_normaliza_a_minusculas():
    assert mcp_config.normalizar_nombre("  Notion ") == "notion"


@pytest.mark.parametrize("malo", ["", "   ", "1abc", "con espacio", "__proto__", "a" * 41, "ñandú"])
def test_un_nombre_invalido_se_rechaza(malo):
    with pytest.raises(MCPConfigRechazada):
        mcp_config.normalizar_nombre(malo)


# ── agregar ─────────────────────────────────────────────────────────

def test_agregar_un_servidor_local_parte_el_comando_completo(entorno):
    definicion = mcp_config.agregar_servidor(
        "notion", command="npx -y @notionhq/notion-mcp-server", env={"NOTION_TOKEN": "${NOTION_TOKEN}"},
    )

    assert definicion == {
        "enabled": True,
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server"],
        "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"},
    }
    assert _config(entorno)["mcp_servers"]["notion"] == definicion


def test_un_comando_con_ruta_entre_comillas_conserva_los_espacios():
    partes = mcp_config.partir_comando('"C:/Program Files/node/node.exe" server.js --port 3')

    assert partes == ["C:/Program Files/node/node.exe", "server.js", "--port", "3"]


def test_agregar_un_servidor_remoto_guarda_la_url(entorno):
    definicion = mcp_config.agregar_servidor(
        "docs", url="https://mcp.ejemplo.com/mcp", headers={"Authorization": "${DOCS_TOKEN}"},
    )

    assert definicion["url"] == "https://mcp.ejemplo.com/mcp"
    assert definicion["headers"] == {"Authorization": "${DOCS_TOKEN}"}
    assert "command" not in definicion


def test_un_secreto_literal_en_env_se_rechaza_y_se_dice_donde_va(entorno):
    with pytest.raises(MCPConfigRechazada) as exc:
        mcp_config.agregar_servidor("notion", command="npx x", env={"NOTION_TOKEN": "ntn_secreto123"})

    assert "Configuración" in str(exc.value)
    assert "ntn_secreto123" not in _config(entorno).get("mcp_servers", {}).__repr__()
    assert "mcp_servers" not in _config(entorno) or "notion" not in _config(entorno)["mcp_servers"]


def test_un_secreto_literal_en_headers_se_rechaza(entorno):
    with pytest.raises(MCPConfigRechazada):
        mcp_config.agregar_servidor("docs", url="https://x.y/mcp", headers={"Authorization": "Bearer abc"})


def test_command_y_url_a_la_vez_se_rechaza(entorno):
    with pytest.raises(MCPConfigRechazada):
        mcp_config.agregar_servidor("x", command="npx x", url="https://x.y/mcp")


def test_sin_command_ni_url_se_rechaza(entorno):
    with pytest.raises(MCPConfigRechazada):
        mcp_config.agregar_servidor("x")


def test_una_url_sin_esquema_http_se_rechaza(entorno):
    with pytest.raises(MCPConfigRechazada):
        mcp_config.agregar_servidor("x", url="ftp://x.y/mcp")


def test_un_nombre_repetido_se_rechaza(entorno):
    mcp_config.agregar_servidor("notion", command="npx x")

    with pytest.raises(MCPConfigRechazada):
        mcp_config.agregar_servidor("Notion", command="npx y")


# ── permitir ────────────────────────────────────────────────────────

def test_permitir_escribe_la_forma_larga_y_conserva_otros_servidores(entorno):
    entorno["allow"].write_text(json.dumps({"otro": ["algo"]}), encoding="utf-8")
    mcp_config.agregar_servidor("notion", command="npx x")

    escrito = mcp_config.permitir_herramientas("notion", ["Search", "create_page", "search"])

    assert escrito == {"tools": ["search", "create_page"], "canales": ["desktop"]}
    assert _allow(entorno) == {"otro": ["algo"], "notion": escrito}
    assert politica.is_tool_allowed("notion", "search")
    assert not politica.is_tool_allowed("notion", "delete_page")


def test_permitir_acepta_una_cadena_separada_por_comas(entorno):
    mcp_config.agregar_servidor("notion", command="npx x")

    escrito = mcp_config.permitir_herramientas("notion", "search, read_*")

    assert escrito["tools"] == ["search", "read_*"]


def test_permitir_sin_patrones_se_rechaza(entorno):
    mcp_config.agregar_servidor("notion", command="npx x")

    with pytest.raises(MCPConfigRechazada):
        mcp_config.permitir_herramientas("notion", [])


def test_permitir_para_un_servidor_no_declarado_se_rechaza(entorno):
    with pytest.raises(MCPConfigRechazada):
        mcp_config.permitir_herramientas("fantasma", ["search"])


def test_el_canal_de_correo_nunca_es_habilitable(entorno):
    mcp_config.agregar_servidor("notion", command="npx x")

    with pytest.raises(MCPConfigRechazada):
        mcp_config.permitir_herramientas("notion", ["search"], ["desktop", "email"])


def test_desktop_se_agrega_siempre_a_los_canales(entorno):
    """Es donde se confirma: sin él una herramienta amarilla quedaría solo en canales que
    no pueden mostrar el modal."""
    mcp_config.agregar_servidor("notion", command="npx x")

    escrito = mcp_config.permitir_herramientas("notion", ["search"], ["telegram"])

    assert escrito["canales"] == ["desktop", "telegram"]


# ── apagar y quitar ─────────────────────────────────────────────────

def test_habilitar_y_deshabilitar_escriben_enabled(entorno):
    mcp_config.agregar_servidor("notion", command="npx x")

    mcp_config.habilitar_servidor("notion", False)
    assert _config(entorno)["mcp_servers"]["notion"]["enabled"] is False

    mcp_config.habilitar_servidor("notion", True)
    assert _config(entorno)["mcp_servers"]["notion"]["enabled"] is True


def test_quitar_borra_la_definicion_y_su_allowlist(entorno):
    mcp_config.agregar_servidor("notion", command="npx x")
    mcp_config.permitir_herramientas("notion", ["search"])

    assert mcp_config.quitar_servidor("notion") is True

    assert "notion" not in _config(entorno)["mcp_servers"]
    assert "notion" not in _allow(entorno)
    assert mcp_config.quitar_servidor("notion") is False


# ── variables ───────────────────────────────────────────────────────

def test_las_variables_referenciadas_salen_de_env_y_headers(entorno):
    mcp_config.agregar_servidor("notion", command="npx x", env={"NOTION_TOKEN": "${NOTION_TOKEN}"})
    mcp_config.agregar_servidor("docs", url="https://x.y/mcp", headers={"Authorization": "${DOCS_TOKEN}"})

    assert mcp_config.variables_referenciadas() == {"NOTION_TOKEN": ["notion"], "DOCS_TOKEN": ["docs"]}


def test_solo_se_guarda_una_variable_que_algun_servidor_use(entorno):
    mcp_config.agregar_servidor("notion", command="npx x", env={"NOTION_TOKEN": "${NOTION_TOKEN}"})

    assert mcp_config.definir_variable("OTRA_COSA", "valor") is False
    assert mcp_config.definir_variable("NOTION_TOKEN", "   ") is False
    assert mcp_config.definir_variable("NOTION_TOKEN", "ntn_123") is True

    assert _config(entorno)["mcp_variables"] == {"NOTION_TOKEN": "ntn_123"}
    assert mcp_config.origen_de_variable("NOTION_TOKEN") == "archivo"


def test_el_cliente_resuelve_la_variable_del_archivo_y_el_entorno_manda(entorno, monkeypatch):
    mcp_config.agregar_servidor("notion", command="npx x", env={"NOTION_TOKEN": "${NOTION_TOKEN}"})
    mcp_config.definir_variable("NOTION_TOKEN", "del_archivo")

    assert expandir_secreto("${NOTION_TOKEN}") == "del_archivo"

    monkeypatch.setenv("NOTION_TOKEN", "del_entorno")
    assert expandir_secreto("${NOTION_TOKEN}") == "del_entorno"
    assert mcp_config.origen_de_variable("NOTION_TOKEN") == "entorno"


def test_una_variable_sin_definir_se_envia_vacia_y_no_rompe(entorno):
    assert expandir_secreto("${NO_EXISTE_EN_NINGUN_LADO}") == ""


def test_borrar_variable(entorno):
    mcp_config.agregar_servidor("notion", command="npx x", env={"NOTION_TOKEN": "${NOTION_TOKEN}"})
    mcp_config.definir_variable("NOTION_TOKEN", "ntn_123")

    assert mcp_config.borrar_variable("NOTION_TOKEN") is True
    assert mcp_config.borrar_variable("NOTION_TOKEN") is False
    assert _config(entorno)["mcp_variables"] == {}


# ── listar ──────────────────────────────────────────────────────────

def test_listar_dice_el_estado_y_nunca_el_valor_de_una_variable(entorno):
    mcp_config.agregar_servidor("notion", command="npx x", env={"NOTION_TOKEN": "${NOTION_TOKEN}"})
    mcp_config.permitir_herramientas("notion", ["search"], ["telegram"])
    mcp_config.definir_variable("NOTION_TOKEN", "ntn_secretisimo")

    filas = mcp_config.listar_servidores()

    assert len(filas) == 1
    fila = filas[0]
    assert fila["nombre"] == "notion"
    assert fila["transporte"] == "stdio"
    assert fila["destino"] == "npx x"
    assert fila["enabled"] is True
    assert fila["permitidas"] == ["search"]
    assert fila["canales"] == ["desktop", "telegram"]
    assert fila["conectado"] is False
    assert fila["herramientas"] == []
    assert fila["variables"] == [{"nombre": "NOTION_TOKEN", "origen": "archivo"}]
    assert "ntn_secretisimo" not in json.dumps(filas)


def test_listar_muestra_las_herramientas_registradas_sin_prefijo(entorno, monkeypatch):
    mcp_config.agregar_servidor("notion", command="npx x")
    monkeypatch.setattr(mcp_manager, "estado", lambda: {"notion": ["mcp__notion__search", "mcp__notion__create_page"]})

    fila = mcp_config.listar_servidores()[0]

    assert fila["conectado"] is True
    assert fila["herramientas"] == ["create_page", "search"]


# ── aplicar y resumir ───────────────────────────────────────────────

def test_aplicar_recarga_y_cuenta_lo_publicado_y_lo_habilitado(entorno, monkeypatch):
    class ClienteFalso:
        def list_tools(self):
            return [{"name": "search"}, {"name": "create_page"}, {"name": "delete_page"}]

    mcp_config.agregar_servidor("notion", command="npx x")
    mcp_config.permitir_herramientas("notion", ["search"])

    def recargar_falso(nombre):
        mcp_manager._CLIENTES[nombre] = ClienteFalso()
        return "ok"

    monkeypatch.setattr(mcp_manager, "recargar_servidor", recargar_falso)
    monkeypatch.setattr(mcp_manager, "estado", lambda: {"notion": ["mcp__notion__search"]})

    resumen = mcp_config.aplicar_y_resumir("notion")

    assert "'notion' conectado" in resumen
    assert "Publica 3 herramienta(s)" in resumen
    assert "delete_page" in resumen
    assert "Habilitadas 1: search" in resumen


def test_aplicar_sin_nada_habilitado_le_pide_al_modelo_que_pregunte(entorno, monkeypatch):
    class ClienteFalso:
        def list_tools(self):
            return [{"name": "search"}]

    mcp_config.agregar_servidor("notion", command="npx x", env={"NOTION_TOKEN": "${NOTION_TOKEN}"})
    monkeypatch.setattr(mcp_manager, "recargar_servidor", lambda n: mcp_manager._CLIENTES.__setitem__(n, ClienteFalso()))
    monkeypatch.setattr(mcp_manager, "estado", lambda: {"notion": []})

    resumen = mcp_config.aplicar_y_resumir("notion")

    assert "Ninguna está habilitada todavía" in resumen
    assert "mcp_allow_tools" in resumen
    assert "NOTION_TOKEN" in resumen          # falta definirla, y se dice


def test_aplicar_un_servidor_que_no_responde_lo_dice_sin_lanzar(entorno, monkeypatch):
    mcp_config.agregar_servidor("notion", command="npx x")
    monkeypatch.setattr(mcp_manager, "recargar_servidor", lambda n: "no")
    monkeypatch.setattr(mcp_manager, "estado", lambda: {})

    resumen = mcp_config.aplicar_y_resumir("notion")

    assert "no respondió" in resumen
    assert "mcp_probe_server" in resumen


def test_aplicar_un_servidor_deshabilitado_lo_desregistra(entorno, monkeypatch):
    mcp_config.agregar_servidor("notion", command="npx x")
    mcp_config.habilitar_servidor("notion", False)
    llamadas = []
    monkeypatch.setattr(mcp_manager, "desregistrar_servidor", lambda n: llamadas.append(n) or 0)

    resumen = mcp_config.aplicar_y_resumir("notion")

    assert llamadas == ["notion"]
    assert "deshabilitado" in resumen
