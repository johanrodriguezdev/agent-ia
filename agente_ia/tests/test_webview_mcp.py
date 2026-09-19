"""
tests/test_webview_mcp.py
REQ-043 — los slots de servidores MCP del `Bridge` (`ui/webview/bridge.py`), CA-18..CA-21.

Lo que protege esta suite:
- El payload que va a la página dice qué servidores hay y qué variables usan, pero
  **nunca** el valor de una variable.
- Lo que llega del JS no decide sobre qué se actúa: un nombre de servidor que no está en
  la configuración se rechaza en todos los slots.
- Quitar un servidor y cambiar sus herramientas permitidas pasan por el MISMO gate
  amarillo que las herramientas del agente (`mcp_remove_server`, `mcp_allow_tools`), con
  la lista a la vista; si el humano dice no, no se escribe nada.
- Guardar una variable solo funciona para una que algún servidor referencie.

`run_async()` se reemplaza por una versión síncrona (mismo patrón que
`tests/test_webview_bridge.py`); `config.json` y `mcp_allowlist.json` viven en `tmp_path`.
"""

import json
from unittest.mock import MagicMock

import pytest

import config_manager
import ui.webview.bridge as bridge_module
from core import mcp_config, mcp_manager
from core import remote_tools_policy as politica
from core.security_manager import security_manager
from ui.webview.bridge import Bridge


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(mcp_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(tmp_path / "mcp_allowlist.json"))
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    # Nada conecta de verdad: recargar solo devuelve un texto.
    monkeypatch.setattr(mcp_manager, "recargar_servidor", lambda n: "ok")
    monkeypatch.setattr(mcp_manager, "desregistrar_servidor", lambda n: 0)
    mcp_manager._CLIENTES.clear()
    yield config_path
    mcp_manager._CLIENTES.clear()


@pytest.fixture
def fake_run_async(monkeypatch):
    def _fake(fn, on_done=None, on_error=None, *args, **kwargs):
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            if on_error:
                on_error(str(e))
            return None
        if on_done:
            on_done(result)
        return result

    monkeypatch.setattr(bridge_module, "run_async", _fake)


@pytest.fixture
def bridge(qtbot, entorno, fake_run_async):
    return Bridge(MagicMock())


@pytest.fixture
def confirmacion(monkeypatch):
    """Registra qué acción pidió confirmación y responde lo que diga `respuesta[0]`."""
    pedidas = []
    respuesta = [True]

    def _falsa(action_name, channel, details="", user_id=None, **kwargs):
        pedidas.append({"accion": action_name, "detalle": details})
        return respuesta[0]

    monkeypatch.setattr(security_manager, "require_confirmation", _falsa)
    return {"pedidas": pedidas, "respuesta": respuesta}


def _con_notion():
    mcp_config.agregar_servidor("notion", command="npx -y x", env={"NOTION_TOKEN": "${NOTION_TOKEN}"})


# ── payload ─────────────────────────────────────────────────────────

def test_el_payload_lista_servidores_y_variables_sin_valores(entorno):
    _con_notion()
    mcp_config.definir_variable("NOTION_TOKEN", "ntn_super_secreto")

    crudo = json.dumps(bridge_module._build_mcp_payload())
    payload = json.loads(crudo)

    assert "ntn_super_secreto" not in crudo
    assert payload["servidores"][0]["nombre"] == "notion"
    assert payload["variables"] == [{"nombre": "NOTION_TOKEN", "origen": "archivo", "servidores": ["notion"]}]
    assert payload["canales"] == ["desktop", "telegram", "discord", "voice"]


def test_request_emite_el_payload(bridge, qtbot):
    _con_notion()

    with qtbot.waitSignal(bridge.mcp_servers_loaded, timeout=1000) as blocker:
        bridge.request_mcp_servers()

    assert json.loads(blocker.args[0])["servidores"][0]["nombre"] == "notion"


# ── nombres que llegan del JS ───────────────────────────────────────

@pytest.mark.parametrize("slot", ["set_mcp_server_enabled", "remove_mcp_server", "probe_mcp_server", "login_mcp_server"])
def test_un_servidor_desconocido_se_rechaza_con_aviso(bridge, qtbot, slot, confirmacion):
    _con_notion()
    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as blocker:
        if slot == "set_mcp_server_enabled":
            bridge.set_mcp_server_enabled("fantasma", False)
        else:
            getattr(bridge, slot)("fantasma")

    assert blocker.args[0] == "error"
    assert confirmacion["pedidas"] == []
    assert mcp_config.listar_servidores()[0]["enabled"] is True


def test_save_allowed_tools_con_servidor_desconocido_no_escribe(bridge, entorno, confirmacion):
    _con_notion()

    bridge.save_mcp_allowed_tools("fantasma", "search", "desktop")

    assert confirmacion["pedidas"] == []
    assert politica.load_allowlist() == {}


# ── gates ───────────────────────────────────────────────────────────

def test_quitar_pasa_por_el_gate_amarillo_con_el_nombre(bridge, entorno, confirmacion):
    _con_notion()

    bridge.remove_mcp_server("notion")

    assert confirmacion["pedidas"][0]["accion"] == "mcp_remove_server"
    assert "name=notion" in confirmacion["pedidas"][0]["detalle"]
    assert mcp_config.listar_servidores() == []


def test_si_el_humano_dice_no_el_servidor_se_queda(bridge, entorno, confirmacion):
    _con_notion()
    confirmacion["respuesta"][0] = False

    bridge.remove_mcp_server("notion")

    assert len(confirmacion["pedidas"]) == 1
    assert mcp_config.listar_servidores()[0]["nombre"] == "notion"


def test_permitir_pasa_por_el_gate_con_las_herramientas_a_la_vista(bridge, entorno, confirmacion):
    _con_notion()

    bridge.save_mcp_allowed_tools("notion", "search, create_page", "desktop,telegram")

    pedido = confirmacion["pedidas"][0]
    assert pedido["accion"] == "mcp_allow_tools"
    assert "herramientas=search / create_page" in pedido["detalle"]
    assert "canales=desktop / telegram" in pedido["detalle"]
    assert politica.load_allowlist()["notion"] == {
        "tools": ["search", "create_page"], "canales": ["desktop", "telegram"],
    }


def test_permitir_denegado_no_escribe_la_allowlist(bridge, entorno, confirmacion):
    _con_notion()
    confirmacion["respuesta"][0] = False

    bridge.save_mcp_allowed_tools("notion", "search", "")

    assert politica.load_allowlist() == {}


def test_permitir_con_canal_de_correo_se_rechaza_en_palabras(bridge, qtbot, entorno, confirmacion):
    _con_notion()

    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as blocker:
        bridge.save_mcp_allowed_tools("notion", "search", "email")

    assert blocker.args[0] == "error"
    assert "email" in blocker.args[1]
    assert politica.load_allowlist() == {}


# ── habilitar / deshabilitar ────────────────────────────────────────

def test_apagar_y_encender_no_confirman_pero_escriben(bridge, entorno, confirmacion):
    _con_notion()

    bridge.set_mcp_server_enabled("notion", False)
    assert mcp_config.listar_servidores()[0]["enabled"] is False

    bridge.set_mcp_server_enabled("notion", True)
    assert mcp_config.listar_servidores()[0]["enabled"] is True
    assert confirmacion["pedidas"] == []


# ── variables ───────────────────────────────────────────────────────

def test_guardar_una_variable_referenciada(bridge, qtbot, entorno):
    _con_notion()

    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as blocker:
        bridge.save_mcp_variable("NOTION_TOKEN", "ntn_123")

    assert blocker.args[0] == "ok"
    assert mcp_config.origen_de_variable("NOTION_TOKEN") == "archivo"
    assert "ntn_123" not in blocker.args[1]


def test_una_variable_que_nadie_usa_no_se_guarda(bridge, qtbot, entorno):
    _con_notion()

    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as blocker:
        bridge.save_mcp_variable("OTRA", "valor")

    assert blocker.args[0] == "error"
    assert "mcp_variables" not in json.loads(entorno.read_text(encoding="utf-8"))


def test_si_el_entorno_manda_se_avisa(bridge, qtbot, entorno, monkeypatch):
    _con_notion()
    monkeypatch.setenv("NOTION_TOKEN", "del_entorno")

    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as blocker:
        bridge.save_mcp_variable("NOTION_TOKEN", "del_archivo")

    assert blocker.args[0] == "info"
    assert "entorno" in blocker.args[1]


def test_borrar_variable(bridge, qtbot, entorno):
    _con_notion()
    mcp_config.definir_variable("NOTION_TOKEN", "x")

    with qtbot.waitSignal(bridge.mcp_servers_loaded, timeout=1000):
        bridge.clear_mcp_variable("NOTION_TOKEN")

    assert mcp_config.origen_de_variable("NOTION_TOKEN") == ""


# ── sondeo ──────────────────────────────────────────────────────────

def test_probar_emite_el_resultado_en_la_fila(bridge, qtbot, entorno, monkeypatch):
    _con_notion()
    monkeypatch.setattr(mcp_manager, "probar_servidor", lambda n: f"Servidor '{n}':\n  conexión: FALLÓ — sin proceso")

    with qtbot.waitSignal(bridge.mcp_probe_result, timeout=1000) as blocker:
        bridge.probe_mcp_server("notion")

    assert blocker.args[0] == "notion"
    assert "FALLÓ" in blocker.args[1]
