"""
tests/test_mapa_conexiones.py
REQ-052 — el Mapa de conexiones (`ui/webview/mapa_conexiones.py` + el slot del bridge).

Lo que protege esta suite:
- El JSON del mapa NUNCA lleva una credencial: ni claves de proveedor, ni tokens de bots,
  ni el valor de una variable MCP — solo si están puestas y de dónde salen.
- Cada nodo se clasifica como corresponde: un proveedor elegido sin clave es un problema,
  Telegram con token y proceso es activo, un servidor MCP al que le falta la variable dice
  cuál, un flujo con horario está configurado.
- Un bloque que falla no tira el mapa: los demás salen igual.
- El bridge emite `connection_map_loaded` con el mapa armado.

Sin red, sin DB real, sin procesos: config en `tmp_path`, `psutil` fuera del camino.
"""

import json
from unittest.mock import MagicMock

import pytest

import config_manager
import core.mcp_manager as mcp_manager
import core.remote_tools_policy as politica
from core import email_capabilities, email_reader, flows
from ui.webview import mapa_conexiones

CLAVE_DE_PRUEBA = "sk-esta-clave-no-puede-aparecer-en-el-mapa"
TOKEN_DE_PRUEBA = "123456:token-secreto-del-bot"
VALOR_VARIABLE = "ntn_valor-secreto-de-notion"


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(mcp_manager, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(email_reader, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(tmp_path / "mcp_allowlist.json"))
    monkeypatch.setattr(email_capabilities, "CAPABILITIES_FILE", str(tmp_path / "email_capabilities.json"))
    monkeypatch.setattr(flows, "flow_store", flows.FlowStore(str(tmp_path / "flows.db")))
    for variable in ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
                     "OPENAI_API_KEY", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN",
                     "DISCORD_BOT_TOKEN", "NOTION_TOKEN"):
        monkeypatch.delenv(variable, raising=False)
    # Ningún test mira los procesos de la máquina.
    monkeypatch.setattr("channels.telegram_launcher._ya_hay_uno_corriendo", lambda: False)
    mcp_manager._CLIENTES.clear()
    yield config_path
    mcp_manager._CLIENTES.clear()


def _escribir(config_path, **campos):
    config = dict(config_manager.DEFAULT_CONFIG)
    config.update(campos)
    config_path.write_text(json.dumps(config), encoding="utf-8")


def _nodo(mapa, grupo, id_):
    return next(n for n in mapa[grupo] if n["id"] == id_)


# ── sin secretos ────────────────────────────────────────────────────

def test_el_mapa_no_lleva_ninguna_credencial(entorno):
    _escribir(
        entorno,
        ai_provider="deepseek", ai_model="deepseek-chat",
        deepseek_api_key=CLAVE_DE_PRUEBA, telegram_token=TOKEN_DE_PRUEBA,
        mcp_servers={"notion": {"command": "npx", "args": ["-y", "srv"],
                                "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"}}},
        mcp_variables={"NOTION_TOKEN": VALOR_VARIABLE},
    )

    texto = json.dumps(mapa_conexiones.construir())

    assert CLAVE_DE_PRUEBA not in texto
    assert TOKEN_DE_PRUEBA not in texto
    assert VALOR_VARIABLE not in texto
    # …pero sí dice que están puestas.
    assert _nodo(mapa_conexiones.construir(), "modelos", "deepseek")["estado"] == "activo"
    assert _nodo(mapa_conexiones.construir(), "canales", "telegram")["estado"] == "configurado"


# ── modelos ─────────────────────────────────────────────────────────

def test_el_proveedor_elegido_sin_clave_es_un_problema(entorno):
    _escribir(entorno, ai_provider="openai", ai_model="gpt-4o", gemini_api_key=CLAVE_DE_PRUEBA)

    mapa = mapa_conexiones.construir()

    assert _nodo(mapa, "modelos", "openai")["estado"] == "error"
    assert _nodo(mapa, "modelos", "gemini")["estado"] == "configurado"
    assert _nodo(mapa, "modelos", "deepseek")["estado"] == "inactivo"
    assert mapa["agente"]["proveedor"] == "openai"
    assert mapa["agente"]["modelo"] == "gpt-4o"


def test_la_clave_del_entorno_se_distingue(entorno, monkeypatch):
    _escribir(entorno, ai_provider="deepseek")
    monkeypatch.setenv("GEMINI_API_KEY", CLAVE_DE_PRUEBA)

    nodo = _nodo(mapa_conexiones.construir(), "modelos", "gemini")

    assert nodo["estado"] == "configurado"
    assert "entorno" in nodo["detalle"]


# ── canales ─────────────────────────────────────────────────────────

def test_escritorio_siempre_esta_activo(entorno):
    _escribir(entorno)
    assert _nodo(mapa_conexiones.construir(), "canales", "desktop")["estado"] == "activo"


@pytest.mark.parametrize("wake,estado", [
    ("INACTIVE", "inactivo"), ("LISTENING_WAKE", "activo"), ("AWAKE", "activo"),
    ("RECONNECTING", "error"),
])
def test_la_voz_sigue_al_manos_libres(entorno, wake, estado):
    _escribir(entorno)
    assert _nodo(mapa_conexiones.construir(wake_state=wake), "canales", "voice")["estado"] == estado


def test_telegram_sin_token_con_token_y_corriendo(entorno, monkeypatch):
    _escribir(entorno)
    assert _nodo(mapa_conexiones.construir(), "canales", "telegram")["estado"] == "inactivo"

    _escribir(entorno, telegram_token=TOKEN_DE_PRUEBA)
    assert _nodo(mapa_conexiones.construir(), "canales", "telegram")["estado"] == "configurado"

    # La pestaña de la terminal que abre la app al arrancar es la señal de que corre.
    pestañas = [{"id": "t1", "titulo": "Telegram", "cwd": "", "activa": False}]
    nodo = _nodo(mapa_conexiones.construir(sesiones_terminal=pestañas), "canales", "telegram")
    assert nodo["estado"] == "activo"
    assert "terminal" in nodo["detalle"]

    # O un proceso aparte, lanzado a mano.
    monkeypatch.setattr("channels.telegram_launcher._ya_hay_uno_corriendo", lambda: True)
    assert _nodo(mapa_conexiones.construir(), "canales", "telegram")["estado"] == "activo"


def test_telegram_apagado_en_la_configuracion_lo_dice(entorno):
    _escribir(entorno, telegram_token=TOKEN_DE_PRUEBA, telegram_autostart=False)
    nodo = _nodo(mapa_conexiones.construir(), "canales", "telegram")
    assert nodo["estado"] == "configurado"
    assert "no arranca solo" in nodo["detalle"]


def test_discord_solo_sabe_si_hay_token(entorno):
    _escribir(entorno)
    assert _nodo(mapa_conexiones.construir(), "canales", "discord")["estado"] == "inactivo"
    _escribir(entorno, discord_token=TOKEN_DE_PRUEBA)
    assert _nodo(mapa_conexiones.construir(), "canales", "discord")["estado"] == "configurado"


def test_correo_cuenta_las_cuentas_y_las_capacidades(entorno, monkeypatch):
    _escribir(entorno)
    assert _nodo(mapa_conexiones.construir(), "canales", "email")["estado"] == "inactivo"

    _escribir(entorno, email={"enabled": True, "host": "imap.ejemplo.com", "user": "yo@ejemplo.com",
                              "password": "clave-del-correo"})
    monkeypatch.setattr(email_capabilities, "cargar", lambda: {"send": False, "mark_read": False, "commands": True})
    monkeypatch.setattr("core.email_commands.esta_activa", lambda: True)

    mapa = mapa_conexiones.construir()
    nodo = _nodo(mapa, "canales", "email")

    assert nodo["estado"] == "activo"
    assert "1 cuenta" in nodo["detalle"] and "órdenes" in nodo["detalle"]
    assert nodo["capacidades"] == ["commands"]
    assert "clave-del-correo" not in json.dumps(mapa)


# ── servidores MCP ──────────────────────────────────────────────────

def test_un_servidor_al_que_le_falta_la_variable_dice_cual(entorno):
    _escribir(entorno, mcp_servers={
        "notion": {"command": "npx", "args": ["-y", "srv"], "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"}},
        "apagado": {"command": "node", "args": ["x.js"], "enabled": False},
    })

    mapa = mapa_conexiones.construir()

    notion = _nodo(mapa, "mcp", "notion")
    assert notion["estado"] == "error"
    assert "NOTION_TOKEN" in notion["detalle"]
    assert notion["transporte"] == "stdio"
    assert _nodo(mapa, "mcp", "apagado")["estado"] == "inactivo"


def test_un_servidor_conectado_cuenta_sus_herramientas(entorno, monkeypatch):
    _escribir(entorno, mcp_servers={"notion": {"command": "npx", "args": ["-y", "srv"]}})
    monkeypatch.setattr(mcp_manager, "estado", lambda: {"notion": ["mcp__notion__search", "mcp__notion__create_page"]})

    nodo = _nodo(mapa_conexiones.construir(), "mcp", "notion")

    assert nodo["estado"] == "activo"
    assert nodo["herramientas"] == ["create_page", "search"]
    assert "2 herramientas" in nodo["detalle"]


# ── flujos ──────────────────────────────────────────────────────────

def test_los_flujos_se_clasifican_por_estado_y_horario(entorno):
    _escribir(entorno)
    store = flows.flow_store
    con_horario = store.crear("modo trabajo", [flows.Paso("abrir chrome"), flows.Paso("abrir notas")],
                              horario="08:00")
    suelto = store.crear("cierre", [flows.Paso("cerrar todo")])

    mapa = mapa_conexiones.construir()

    assert _nodo(mapa, "flujos", str(con_horario.id))["estado"] == "configurado"
    assert "2 pasos" in _nodo(mapa, "flujos", str(con_horario.id))["detalle"]
    assert _nodo(mapa, "flujos", str(suelto.id))["estado"] == "inactivo"


# ── robustez ────────────────────────────────────────────────────────

def test_un_bloque_roto_no_tira_el_mapa(entorno, monkeypatch):
    _escribir(entorno, deepseek_api_key=CLAVE_DE_PRUEBA)

    def _explota():
        raise RuntimeError("sin base de flujos")
    monkeypatch.setattr(mapa_conexiones, "_flujos", _explota)

    mapa = mapa_conexiones.construir()

    assert mapa["flujos"] == []
    assert mapa["modelos"] and mapa["canales"]


def test_un_estado_desconocido_es_un_error_de_programacion():
    with pytest.raises(ValueError):
        mapa_conexiones._nodo("x", "X", "encendido")


# ── bridge ──────────────────────────────────────────────────────────

def test_el_bridge_emite_el_mapa(qtbot, monkeypatch, entorno):
    import ui.webview.bridge as bridge_module
    from ui.webview.bridge import Bridge

    def _fake_run_async(fn, on_done=None, on_error=None, *args, **kwargs):
        on_done(fn(*args, **kwargs))
    monkeypatch.setattr(bridge_module, "run_async", _fake_run_async)
    monkeypatch.setattr(mapa_conexiones, "construir",
                        lambda wake, sesiones: {"agente": {"nombre": "Orion"}, "wake": wake,
                                                "sesiones": sesiones})
    _escribir(entorno)
    bridge = Bridge(MagicMock())

    with qtbot.waitSignal(bridge.connection_map_loaded, timeout=1000) as blocker:
        bridge.request_connection_map()

    mapa = json.loads(blocker.args[0])
    assert mapa["agente"]["nombre"] == "Orion"
    assert mapa["wake"] in ("INACTIVE", "LISTENING_WAKE", "AWAKE", "RECONNECTING")
    assert isinstance(mapa["sesiones"], list)
