"""
tests/test_webview_conexiones.py
Sección "Conexiones" de Configuración — `config_manager` + `ui/webview/bridge.py`.

Desde que `config.json` dejó de estar versionado, un equipo recién clonado arranca sin
ninguna credencial. Esta pantalla es la forma de ponerlas sin editar un archivo a mano.

Lo que se fija acá:

- **El valor de una clave NUNCA sale de Python.** El payload dice si está puesta y de
  dónde sale; devolverla la dejaría en el DOM, en una captura o en un volcado del webview,
  y para decidir si hay que cambiarla no hace falta verla.
- **Lo que llega del JS no decide qué clave se escribe.** `save_connection` y
  `clear_connection` son `@pyqtSlot` alcanzables desde cualquier script de la página
  (mismo criterio que `save_task_models` y `delete_conversation`, REQ-015/§10.2), así que
  se validan contra la lista cerrada `_CONEXIONES`.
- **El entorno manda sobre el archivo**, y hay que decirlo: si no, alguien pega una clave,
  ve "guardada", y sigue sin funcionar sin ninguna pista de por qué.
- **Sin ninguna clave de proveedor, la app avisa al arrancar** en vez de dejar al usuario
  delante de un chat que solo devuelve errores.

`CONFIG_FILE` se redirige a `tmp_path` y las variables de entorno se limpian en cada
prueba: la máquina que corre la suite tiene claves de verdad puestas
(`.claude/rules/testing.md`).
"""

import json
from unittest.mock import MagicMock

import pytest

import config_manager
import ui.webview.bridge as bridge_module
from ui.webview.bridge import Bridge

TODAS_LAS_VARIABLES = tuple(config_manager._ENV_KEY_MAP.values())


@pytest.fixture
def entorno_limpio(tmp_path, monkeypatch):
    """`config.json` en `tmp_path` y sin ninguna variable de entorno de credenciales."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(config_path))
    for variable in TODAS_LAS_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    return config_path


@pytest.fixture
def bridge(qtbot, entorno_limpio):
    return Bridge(MagicMock())


def _escribir(path, datos):
    path.write_text(json.dumps(datos), encoding="utf-8")


# ---------------------------------------------------------------------------
# El catálogo
# ---------------------------------------------------------------------------

def test_toda_conexion_del_catalogo_es_una_clave_que_config_manager_sabe_leer():
    """Una fila que no esté en `_ENV_KEY_MAP` sería un campo que no guarda nada."""
    conocidas = set(config_manager._ENV_KEY_MAP)
    for fila in bridge_module._CONEXIONES:
        assert fila["id"] in conocidas, fila["id"]


def test_cada_conexion_trae_lo_que_la_pantalla_necesita_para_explicarla():
    for fila in bridge_module._CONEXIONES:
        assert fila["label"].strip()
        assert fila["descripcion"].strip()
        assert fila["variable"] == config_manager._ENV_KEY_MAP[fila["id"]]


def test_los_proveedores_son_un_subconjunto_del_catalogo():
    ids = {fila["id"] for fila in bridge_module._CONEXIONES}
    assert set(bridge_module._CLAVES_DE_PROVEEDOR) <= ids


# ---------------------------------------------------------------------------
# El payload no lleva valores
# ---------------------------------------------------------------------------

def test_el_payload_dice_que_hay_pero_nunca_el_valor(entorno_limpio, monkeypatch):
    secreto = "sk-noDebeSalirDeAqui1234567890"
    _escribir(entorno_limpio, {"deepseek_api_key": secreto})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "8600000000:TOKEN_DEL_ENTORNO")

    crudo = json.dumps(bridge_module._build_connections_payload())

    assert secreto not in crudo
    assert "TOKEN_DEL_ENTORNO" not in crudo
    por_id = {f["id"]: f for f in json.loads(crudo)["conexiones"]}
    assert por_id["deepseek_api_key"]["origen"] == "archivo"
    assert por_id["telegram_token"]["origen"] == "entorno"
    assert por_id["openai_api_key"]["origen"] == ""


def test_request_connections_emite_el_mismo_payload(bridge, qtbot):
    with qtbot.waitSignal(bridge.connections_loaded, timeout=1000) as capturada:
        bridge.request_connections()

    payload = json.loads(capturada.args[0])
    assert len(payload["conexiones"]) == len(bridge_module._CONEXIONES)
    assert all("origen" in fila for fila in payload["conexiones"])


# ---------------------------------------------------------------------------
# El entorno manda sobre el archivo
# ---------------------------------------------------------------------------

def test_la_variable_de_entorno_gana_al_archivo(entorno_limpio, monkeypatch):
    _escribir(entorno_limpio, {"openai_api_key": "la-del-archivo"})
    monkeypatch.setenv("OPENAI_API_KEY", "la-del-entorno")

    assert config_manager.origen_de_credencial("openai_api_key") == "entorno"
    assert config_manager.get_api_key("openai") == "la-del-entorno"


def test_guardar_con_el_entorno_puesto_avisa_de_que_no_va_a_valer(bridge, qtbot, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "la-del-entorno")

    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as aviso:
        bridge.save_connection("openai_api_key", "la-nueva")

    nivel, mensaje = aviso.args
    assert nivel == "info"
    assert "entorno" in mensaje.lower()
    # Se guardó igual: el día que quiten la variable, la clave ya está puesta.
    assert config_manager.load_config()["openai_api_key"] == "la-nueva"


def test_guardar_sin_entorno_confirma_sin_letra_pequena(bridge, qtbot):
    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as aviso:
        bridge.save_connection("openai_api_key", "la-nueva")

    assert aviso.args[0] == "ok"
    assert "la-nueva" not in aviso.args[1]   # tampoco en un aviso de pantalla


# ---------------------------------------------------------------------------
# Lo que llega del JS no decide qué clave se toca
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("clave", ["", "agent_name", "ui_theme", "../../secreto", "__class__"])
def test_save_connection_ignora_cualquier_clave_fuera_del_catalogo(bridge, clave, qtbot,
                                                                   entorno_limpio):
    _escribir(entorno_limpio, {"agent_name": "noddoo", "ui_theme": "dark"})

    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as aviso:
        bridge.save_connection(clave, "valor-cualquiera")

    assert aviso.args[0] == "error"
    config = config_manager.load_config()
    assert config.get(clave) != "valor-cualquiera"
    assert config["agent_name"] == "noddoo"       # y no se llevó por delante lo que había
    assert config["ui_theme"] == "dark"


@pytest.mark.parametrize("clave", ["", "agent_name", "ui_theme", "../../secreto"])
def test_clear_connection_ignora_cualquier_clave_fuera_del_catalogo(bridge, clave,
                                                                    entorno_limpio):
    _escribir(entorno_limpio, {"agent_name": "noddoo", "ui_theme": "dark"})

    bridge.clear_connection(clave)

    config = config_manager.load_config()
    assert config["agent_name"] == "noddoo"
    assert config["ui_theme"] == "dark"


def test_una_clave_vacia_no_borra_la_que_ya_estaba(bridge, qtbot):
    bridge.save_connection("openai_api_key", "la-buena")

    with qtbot.waitSignal(bridge.notice_shown, timeout=1000) as aviso:
        bridge.save_connection("openai_api_key", "   ")

    assert aviso.args[0] == "error"
    assert config_manager.load_config()["openai_api_key"] == "la-buena"


def test_quitar_una_clave_la_saca_del_archivo(bridge, qtbot):
    bridge.save_connection("openai_api_key", "la-buena")

    with qtbot.waitSignal(bridge.connections_loaded, timeout=1000):
        bridge.clear_connection("openai_api_key")

    assert "openai_api_key" not in config_manager.load_config()


def test_quitar_no_toca_la_variable_de_entorno(bridge, monkeypatch):
    """La pantalla solo ofrece "Quitar" sobre lo del archivo, pero el slot es alcanzable
    igual: quitar del archivo no puede dejar creyendo que se quitó la del entorno."""
    monkeypatch.setenv("OPENAI_API_KEY", "la-del-entorno")

    bridge.clear_connection("openai_api_key")

    assert config_manager.origen_de_credencial("openai_api_key") == "entorno"


# ---------------------------------------------------------------------------
# Primer arranque: sin ninguna clave de proveedor
# ---------------------------------------------------------------------------

def test_sin_ninguna_clave_falta_configurar_proveedor(entorno_limpio):
    assert bridge_module.falta_configurar_proveedor() is True


def test_con_una_sola_clave_de_proveedor_ya_no_falta(entorno_limpio):
    _escribir(entorno_limpio, {"openrouter_api_key": "sk-or-loquesea"})

    assert bridge_module.falta_configurar_proveedor() is False


def test_un_token_de_telegram_no_cuenta_como_proveedor(entorno_limpio):
    """Telegram es una puerta de entrada, no quien contesta: con solo eso sigue sin poder."""
    _escribir(entorno_limpio, {"telegram_token": "8600000000:loquesea"})

    assert bridge_module.falta_configurar_proveedor() is True


def test_el_arranque_avisa_cuando_no_hay_con_que_responder(bridge, qtbot, monkeypatch):
    monkeypatch.setattr(bridge, "_load_conversations", lambda **kw: None)

    with qtbot.waitSignal(bridge.setup_required, timeout=1000) as pedido:
        bridge.request_initial_state()

    assert pedido.args[0] == "conexiones"


def test_el_arranque_no_molesta_cuando_ya_hay_una_clave(bridge, qtbot, monkeypatch,
                                                        entorno_limpio):
    _escribir(entorno_limpio, {"deepseek_api_key": "sk-la-que-sea"})
    monkeypatch.setattr(bridge, "_load_conversations", lambda **kw: None)

    with qtbot.assertNotEmitted(bridge.setup_required):
        bridge.request_initial_state()
