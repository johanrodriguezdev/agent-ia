"""
tests/test_mcp_manager.py
Punto 2 del plan: descubrimiento y registro de herramientas MCP (`core/mcp_manager.py`).

Lo que protege esta suite: **que conectar un servidor no sea una forma de saltarse la
política del punto 1**. El manager propone herramientas; quien decide es
`register_tool()`. Un servidor que publique 40 herramientas tiene que terminar con las 2
que el usuario nombró, ni una más.

Ningún test conecta a un servidor real.
"""

import json

import pytest

import agents.tool_registry as registry
from core import mcp_manager, remote_tools_policy as politica
from core.mcp_client import MCPError
from core.security_manager import (
    CHANNEL_ACTION_EXCEPTIONS,
    ChannelType,
    RiskLevel,
    security_manager,
)


class ClienteFalso:
    """Un MCPClient ya conectado, sin proceso ni red detrás."""

    def __init__(self, nombre="notion", catalogo=None, resultado="listo"):
        self.nombre = nombre
        self._catalogo = catalogo if catalogo is not None else []
        self._resultado = resultado
        self.llamadas = []

    def list_tools(self):
        if isinstance(self._catalogo, Exception):
            raise self._catalogo
        return self._catalogo

    def call_tool(self, nombre_tool, argumentos=None):
        self.llamadas.append((nombre_tool, argumentos))
        if isinstance(self._resultado, Exception):
            raise self._resultado
        return self._resultado

    def close(self):
        pass


def _tool(nombre, **extra):
    base = {
        "name": nombre,
        "description": f"herramienta {nombre}",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }
    base.update(extra)
    return base


@pytest.fixture
def allowlist(monkeypatch, tmp_path):
    ruta = tmp_path / "mcp_allowlist.json"
    monkeypatch.setattr(politica, "MCP_ALLOWLIST_FILE", str(ruta))

    def escribir(contenido):
        ruta.write_text(json.dumps(contenido), encoding="utf-8")

    escribir({})
    return escribir


@pytest.fixture
def config_falsa(monkeypatch, tmp_path):
    ruta = tmp_path / "config.json"
    monkeypatch.setattr(mcp_manager, "CONFIG_FILE", str(ruta))

    def escribir(contenido):
        ruta.write_text(
            contenido if isinstance(contenido, str) else json.dumps(contenido),
            encoding="utf-8",
        )

    return escribir


@pytest.fixture(autouse=True)
def _limpiar_estado_global():
    """`_REGISTRY` y `CHANNEL_ACTION_EXCEPTIONS` son globales de proceso."""
    tools = dict(registry._REGISTRY)
    excepciones = set(CHANNEL_ACTION_EXCEPTIONS)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(tools)
    CHANNEL_ACTION_EXCEPTIONS.clear()
    CHANNEL_ACTION_EXCEPTIONS.update(excepciones)
    mcp_manager._CLIENTES.clear()
    # El enfriamiento de reconexión también es global: sin limpiarlo, un test que intentó
    # reconectar bloquea al siguiente durante 30 segundos.
    mcp_manager._ULTIMO_INTENTO.clear()


# ── Lectura de la configuración ─────────────────────────────────────

def test_sin_mcp_servers_no_hay_nada_que_conectar(config_falsa):
    config_falsa({"ai_provider": "deepseek"})

    assert mcp_manager.cargar_definiciones() == {}


def test_un_config_ilegible_no_rompe_el_arranque(config_falsa):
    config_falsa("{roto")

    assert mcp_manager.cargar_definiciones() == {}


def test_una_definicion_que_no_es_objeto_se_descarta(config_falsa):
    config_falsa({"mcp_servers": {"bueno": {"url": "https://x"}, "malo": "no soy objeto"}})

    definiciones = mcp_manager.cargar_definiciones()

    assert "bueno" in definiciones and "malo" not in definiciones


def test_un_servidor_deshabilitado_no_se_conecta():
    assert mcp_manager.conectar_servidor("x", {"enabled": False, "url": "https://x"}) is None


# ── Registro: la política manda ─────────────────────────────────────

def test_solo_se_registra_lo_que_el_usuario_nombro(allowlist):
    """El caso que motiva todo el punto 1: el servidor publica de más."""
    allowlist({"notion": ["search"]})
    cliente = ClienteFalso(catalogo=[
        _tool("search"), _tool("delete_workspace"), _tool("export_all"),
    ])

    registradas, rechazadas = mcp_manager.registrar_tools(cliente, "notion")

    assert (registradas, rechazadas) == (1, 2)
    assert registry.get_tool("mcp__notion__search") is not None
    assert registry.get_tool("mcp__notion__delete_workspace") is None


def test_sin_allowlist_no_entra_ninguna(allowlist):
    allowlist({})
    cliente = ClienteFalso(catalogo=[_tool("search")])

    registradas, _ = mcp_manager.registrar_tools(cliente, "notion")

    assert registradas == 0


def test_lo_registrado_queda_en_amarillo(allowlist):
    """MCP no tiene campo de riesgo: nadie declara nada, y aun así nunca es verde."""
    allowlist({"notion": ["search"]})

    mcp_manager.registrar_tools(ClienteFalso(catalogo=[_tool("search")]), "notion")

    assert security_manager.classify_action("mcp__notion__search") == RiskLevel.YELLOW


def test_una_anotacion_de_solo_lectura_no_baja_el_nivel(allowlist):
    """Las `annotations` las escribe el servidor: solo pueden endurecer, nunca ablandar."""
    allowlist({"notion": ["search"]})
    tool = _tool("search", annotations={"readOnlyHint": True})

    mcp_manager.registrar_tools(ClienteFalso(catalogo=[tool]), "notion")

    assert security_manager.classify_action("mcp__notion__search") == RiskLevel.YELLOW


def test_una_herramienta_sin_nombre_se_descarta(allowlist):
    allowlist({"notion": ["*"]})
    cliente = ClienteFalso(catalogo=[{"description": "sin nombre"}, _tool("search")])

    registradas, rechazadas = mcp_manager.registrar_tools(cliente, "notion")

    assert (registradas, rechazadas) == (1, 1)


def test_un_schema_invalido_se_normaliza(allowlist):
    """Registrar un ToolSpec con forma rota falla más tarde, lejos de la causa."""
    allowlist({"notion": ["search"]})
    cliente = ClienteFalso(catalogo=[_tool("search", inputSchema="no soy un schema")])

    mcp_manager.registrar_tools(cliente, "notion")

    spec = registry.get_tool("mcp__notion__search")
    assert spec.parameters_schema == {"type": "object", "properties": {}}


def test_si_no_se_puede_listar_no_se_registra_nada(allowlist):
    allowlist({"notion": ["search"]})
    cliente = ClienteFalso(catalogo=MCPError("servidor caído"))

    assert mcp_manager.registrar_tools(cliente, "notion") == (0, 0)


# ── Canales ─────────────────────────────────────────────────────────

def test_por_defecto_solo_se_habilita_el_escritorio(allowlist):
    allowlist({"notion": ["search"]})

    mcp_manager.registrar_tools(ClienteFalso(catalogo=[_tool("search")]), "notion")

    assert (ChannelType.TELEGRAM, "mcp__notion__search") not in CHANNEL_ACTION_EXCEPTIONS
    assert not security_manager.is_action_allowed("mcp__notion__search", ChannelType.TELEGRAM)


def test_un_canal_declarado_habilita_esa_herramienta(allowlist):
    """Sin esto, todo tool MCP sería inalcanzable desde el celular."""
    allowlist({"notion": {"tools": ["search"], "canales": ["desktop", "telegram"]}})

    mcp_manager.registrar_tools(ClienteFalso(catalogo=[_tool("search")]), "notion")

    assert security_manager.is_action_allowed("mcp__notion__search", ChannelType.TELEGRAM)


def test_habilitar_un_canal_no_abre_las_demas_acciones(allowlist):
    """La excepción es por (canal, acción), nunca por canal entero."""
    allowlist({"notion": {"tools": ["search", "create"], "canales": ["telegram"]}})

    mcp_manager.registrar_tools(
        ClienteFalso(catalogo=[_tool("search")]), "notion",
    )

    assert security_manager.is_action_allowed("mcp__notion__search", ChannelType.TELEGRAM)
    # `delete_file` es una acción amarilla local que nadie habilitó en Telegram.
    assert not security_manager.is_action_allowed("delete_file", ChannelType.TELEGRAM)


def test_una_herramienta_destructiva_nunca_se_habilita_en_remoto(allowlist):
    """Se confirma sentado frente al PC, nunca por un atajo desde el celular."""
    allowlist({"notion": {"tools": ["borrar"], "canales": ["telegram"]}})
    tool = _tool("borrar", annotations={"destructiveHint": True})

    mcp_manager.registrar_tools(ClienteFalso(catalogo=[tool]), "notion")

    assert registry.get_tool("mcp__notion__borrar") is not None
    assert not security_manager.is_action_allowed("mcp__notion__borrar", ChannelType.TELEGRAM)
    assert security_manager.is_action_allowed("mcp__notion__borrar", ChannelType.DESKTOP)


def test_un_canal_inventado_se_ignora(allowlist):
    allowlist({"notion": {"tools": ["search"], "canales": ["telepatia"]}})

    mcp_manager.registrar_tools(ClienteFalso(catalogo=[_tool("search")]), "notion")

    assert not any(
        nombre == "mcp__notion__search" and canal == ChannelType.UNKNOWN
        for canal, nombre in CHANNEL_ACTION_EXCEPTIONS
    )


# ── Ejecución a través del registro ─────────────────────────────────

def test_ejecutar_el_tool_registrado_llega_al_servidor(allowlist, monkeypatch):
    allowlist({"notion": ["search"]})
    cliente = ClienteFalso(catalogo=[_tool("search")], resultado="tres resultados")
    mcp_manager.registrar_tools(cliente, "notion")
    monkeypatch.setattr("builtins.input", lambda _: "sí")

    salida = registry.execute_tool(
        "mcp__notion__search", {"q": "informe"}, ChannelType.DESKTOP, "default",
    )

    assert salida == "tres resultados"
    assert cliente.llamadas == [("search", {"q": "informe"})]


def test_un_fallo_del_servidor_no_tumba_el_turno(allowlist, monkeypatch):
    """`execute_tool()` no atrapa: una excepción acá perdería el turno entero del loop de
    razonamiento en vez de dejar que el modelo lea el fallo y siga."""
    allowlist({"notion": ["search"]})
    cliente = ClienteFalso(catalogo=[_tool("search")], resultado=MCPError("timeout"))
    mcp_manager.registrar_tools(cliente, "notion")
    monkeypatch.setattr("builtins.input", lambda _: "sí")

    salida = registry.execute_tool(
        "mcp__notion__search", {"q": "x"}, ChannelType.DESKTOP, "default",
    )

    assert salida.startswith("Error:")
    assert "timeout" in salida


def test_sin_confirmar_no_se_llama_al_servidor(allowlist, monkeypatch):
    """El gate del punto 1, de punta a punta: amarillo sin confirmación no ejecuta."""
    from agents.tool_registry import ActionDenied

    allowlist({"notion": ["search"]})
    cliente = ClienteFalso(catalogo=[_tool("search")])
    mcp_manager.registrar_tools(cliente, "notion")
    monkeypatch.setattr("builtins.input", lambda _: "no")

    with pytest.raises(ActionDenied):
        registry.execute_tool("mcp__notion__search", {}, ChannelType.DESKTOP, "default")

    assert cliente.llamadas == []


# ── Probe ───────────────────────────────────────────────────────────

def test_el_probe_avisa_si_el_servidor_no_esta_declarado(config_falsa):
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})

    informe = mcp_manager.probar_servidor("calendario")

    assert "No hay ningún servidor 'calendario'" in informe
    assert "notion" in informe


def test_el_probe_reporta_lo_permitido_y_lo_bloqueado(config_falsa, allowlist, monkeypatch):
    """Guardar la definición no prueba nada; el probe sí."""
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})
    allowlist({"notion": ["search"]})

    cliente = ClienteFalso(catalogo=[_tool("search"), _tool("delete_workspace")])
    monkeypatch.setattr(mcp_manager, "crear_transporte", lambda n, d: object())
    monkeypatch.setattr(mcp_manager, "MCPClient", lambda *a, **k: _ClienteConHandshake(cliente))

    informe = mcp_manager.probar_servidor("notion")

    assert "search: PERMITIDA" in informe
    assert "delete_workspace: bloqueada" in informe


class _ClienteConHandshake(ClienteFalso):
    """ClienteFalso con `initialize()`, para el camino del probe."""

    def __init__(self, base):
        super().__init__(base.nombre, base._catalogo, base._resultado)
        self.capabilities = {"tools": {}}

    def initialize(self):
        return {"name": "servidor-falso", "version": "1.0"}

    def soporta(self, capacidad):
        return capacidad in self.capabilities


# ── Recarga en caliente ─────────────────────────────────────────────

def test_desregistrar_saca_herramientas_y_permisos(allowlist):
    """Dejar la excepción de canal viva sería una trampa el día que un nombre se reutilice."""
    allowlist({"notion": {"tools": ["search"], "canales": ["telegram"]}})
    mcp_manager.registrar_tools(ClienteFalso(catalogo=[_tool("search")]), "notion")
    assert (ChannelType.TELEGRAM, "mcp__notion__search") in CHANNEL_ACTION_EXCEPTIONS

    quitadas = mcp_manager.desregistrar_servidor("notion")

    assert quitadas == 1
    assert registry.get_tool("mcp__notion__search") is None
    assert (ChannelType.TELEGRAM, "mcp__notion__search") not in CHANNEL_ACTION_EXCEPTIONS
    assert "notion" not in mcp_manager._CLIENTES


def test_desregistrar_un_servidor_que_no_estaba_no_falla():
    assert mcp_manager.desregistrar_servidor("fantasma") == 0


def test_recargar_aplica_una_allowlist_nueva(allowlist, config_falsa, monkeypatch):
    """El objetivo de la recarga: cortar o abrir acceso sin reiniciar O.R.I.O.N."""
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})
    allowlist({"notion": ["search", "crear"]})
    cliente = ClienteFalso(catalogo=[_tool("search"), _tool("crear")])
    monkeypatch.setattr(mcp_manager, "_conectar_cliente", lambda n, d: cliente)

    mcp_manager.conectar_servidor("notion", {"url": "https://x"})
    assert len(mcp_manager._tools_de("notion")) == 2

    allowlist({"notion": ["search"]})           # el usuario le quita 'crear'
    mcp_manager.recargar_servidor("notion")

    assert mcp_manager._tools_de("notion") == ["mcp__notion__search"]


def test_recargar_un_servidor_borrado_lo_deja_desconectado(allowlist, config_falsa, monkeypatch):
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})
    allowlist({"notion": ["search"]})
    monkeypatch.setattr(
        mcp_manager, "_conectar_cliente", lambda n, d: ClienteFalso(catalogo=[_tool("search")]),
    )
    mcp_manager.conectar_servidor("notion", {"url": "https://x"})

    config_falsa({"mcp_servers": {}})           # se lo saca de la config
    informe = mcp_manager.recargar_servidor("notion")

    assert "quedó desconectado" in informe
    assert mcp_manager._tools_de("notion") == []


# ── Reconexión ──────────────────────────────────────────────────────

def test_si_el_servidor_se_cae_se_reconecta_y_la_llamada_sale(
        allowlist, config_falsa, monkeypatch):
    """Un servidor stdio muerto dejaría TODAS las llamadas siguientes rotas hasta reiniciar."""
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})
    allowlist({"notion": ["search"]})

    caido = ClienteFalso(catalogo=[_tool("search")], resultado=MCPError("el proceso murió"))
    sano = ClienteFalso(catalogo=[_tool("search")], resultado="funcionó")
    monkeypatch.setattr(mcp_manager, "_conectar_cliente", lambda n, d: caido)
    mcp_manager.conectar_servidor("notion", {"url": "https://x"})

    # A partir de acá, reconectar devuelve un cliente sano.
    monkeypatch.setattr(mcp_manager, "_conectar_cliente", lambda n, d: sano)
    monkeypatch.setattr("builtins.input", lambda _: "sí")

    salida = registry.execute_tool(
        "mcp__notion__search", {"q": "x"}, ChannelType.DESKTOP, "default",
    )

    assert salida == "funcionó"


def test_si_tampoco_se_puede_reconectar_se_avisa_sin_reventar(
        allowlist, config_falsa, monkeypatch):
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})
    allowlist({"notion": ["search"]})

    caido = ClienteFalso(catalogo=[_tool("search")], resultado=MCPError("murió"))
    monkeypatch.setattr(mcp_manager, "_conectar_cliente", lambda n, d: caido)
    mcp_manager.conectar_servidor("notion", {"url": "https://x"})

    def _no_levanta(n, d):
        raise MCPError("sigue sin levantar")

    monkeypatch.setattr(mcp_manager, "_conectar_cliente", _no_levanta)
    monkeypatch.setattr("builtins.input", lambda _: "sí")

    salida = registry.execute_tool(
        "mcp__notion__search", {"q": "x"}, ChannelType.DESKTOP, "default",
    )

    assert salida.startswith("Error:")


def test_no_se_reintenta_la_reconexion_en_bucle(config_falsa, monkeypatch):
    """Un servidor que no levanta no puede provocar un intento por cada herramienta."""
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})
    intentos = []

    def _contar(n, d):
        intentos.append(n)
        raise MCPError("no levanta")

    monkeypatch.setattr(mcp_manager, "_conectar_cliente", _contar)

    assert mcp_manager._reconectar("notion") is None
    assert mcp_manager._reconectar("notion") is None

    assert len(intentos) == 1


def test_pasado_el_enfriamiento_se_vuelve_a_intentar(config_falsa, monkeypatch):
    config_falsa({"mcp_servers": {"notion": {"url": "https://x"}}})
    intentos = []

    def _contar(n, d):
        intentos.append(n)
        raise MCPError("no levanta")

    monkeypatch.setattr(mcp_manager, "_conectar_cliente", _contar)
    mcp_manager._reconectar("notion")
    mcp_manager._ULTIMO_INTENTO["notion"] -= mcp_manager.SEGUNDOS_ENTRE_RECONEXIONES + 1

    mcp_manager._reconectar("notion")

    assert len(intentos) == 2


# ── OAuth desde el manager ──────────────────────────────────────────

def test_no_se_pide_login_a_un_servidor_stdio(config_falsa):
    config_falsa({"mcp_servers": {"local": {"command": "node"}}})

    assert "no usa OAuth" in mcp_manager.login_servidor("local")


def test_no_se_pide_login_a_un_servidor_que_no_existe(config_falsa):
    config_falsa({"mcp_servers": {}})

    assert "No hay ningún servidor" in mcp_manager.login_servidor("fantasma")
