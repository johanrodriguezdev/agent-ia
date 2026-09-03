"""
tests/test_mcp_client.py
Punto 2 del plan: el cliente MCP (`core/mcp_client.py`).

Lo que protege esta suite: **que O.R.I.O.N. hable MCP de verdad**, no una aproximación que
funcione con un servidor y se rompa con el siguiente. Cubre el handshake, la paginación
del catálogo, la ejecución, y las dos formas en que un servidor reporta un fallo (error
JSON-RPC y `isError` dentro del resultado, que son cosas distintas).

El transporte stdio se prueba end-to-end contra un servidor MCP falso lanzado como
subproceso real: es la única forma de ejercitar los pipes, los hilos lectores y la cola.
Sin red y sin servidores de terceros.
"""

import json
import sys
import textwrap
import time

import pytest

from core import mcp_client
from core.mcp_client import (
    HttpTransport,
    MCPClient,
    MCPError,
    StdioTransport,
    _contenido_a_texto,
    crear_transporte,
    expandir_secreto,
)


class TransporteFalso:
    """Responde lo que se le diga, y guarda lo que se le mandó."""

    def __init__(self, respuestas=None):
        self.respuestas = list(respuestas or [])
        self.enviados = []
        self.notificaciones = []
        self.cerrado = False

    def send_request(self, mensaje, timeout):
        self.enviados.append(mensaje)
        if not self.respuestas:
            raise MCPError("el falso se quedó sin respuestas")
        resultado = self.respuestas.pop(0)
        if isinstance(resultado, Exception):
            raise resultado
        return {"jsonrpc": "2.0", "id": mensaje.get("id"), **resultado}

    def send_notification(self, mensaje):
        self.notificaciones.append(mensaje)

    def close(self):
        self.cerrado = True


def _cliente(respuestas):
    return MCPClient("prueba", TransporteFalso(respuestas))


_INIT_OK = {"result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "servidor-falso", "version": "1.0"},
    "capabilities": {},
}}


# ── Secretos fuera del archivo de configuración ─────────────────────

def test_una_referencia_a_variable_de_entorno_se_resuelve(monkeypatch):
    monkeypatch.setenv("MI_TOKEN", "secreto-real")

    assert expandir_secreto("${MI_TOKEN}") == "secreto-real"


def test_una_variable_no_definida_no_manda_el_literal(monkeypatch):
    """Mandar "${MI_TOKEN}" como si fuera el token da un error incomprensible del servidor."""
    monkeypatch.delenv("MI_TOKEN", raising=False)

    assert expandir_secreto("${MI_TOKEN}") == ""


def test_un_valor_normal_pasa_tal_cual():
    assert expandir_secreto("Bearer abc123") == "Bearer abc123"
    assert expandir_secreto(42) == 42


# ── Elección de transporte ──────────────────────────────────────────

def test_una_url_da_transporte_http():
    transporte = crear_transporte("x", {"url": "https://ejemplo.com/mcp"})

    assert isinstance(transporte, HttpTransport)


def test_definir_command_y_url_a_la_vez_es_un_error():
    """Adivinar cuál quiso el usuario sería peor que fallar con un mensaje claro."""
    with pytest.raises(MCPError, match="elegí uno"):
        crear_transporte("x", {"command": "node", "url": "https://ejemplo.com"})


def test_no_definir_ninguno_es_un_error():
    with pytest.raises(MCPError, match="ni 'command'"):
        crear_transporte("x", {})


# ── Handshake ──────────────────────────────────────────────────────

def test_el_handshake_manda_lo_que_pide_el_protocolo():
    cliente = _cliente([_INIT_OK])

    info = cliente.initialize()

    enviado = cliente._transporte.enviados[0]
    assert enviado["method"] == "initialize"
    assert enviado["jsonrpc"] == "2.0"
    assert enviado["params"]["protocolVersion"] == mcp_client.PROTOCOL_VERSION
    assert enviado["params"]["clientInfo"]["name"] == "orion"
    assert info["name"] == "servidor-falso"


def test_tras_el_handshake_se_avisa_que_esta_inicializado():
    """`notifications/initialized` no es opcional: varios servidores no atienden sin ella."""
    cliente = _cliente([_INIT_OK])

    cliente.initialize()

    assert cliente._transporte.notificaciones[0]["method"] == "notifications/initialized"


def test_si_falla_el_aviso_de_initialized_igual_se_sigue():
    """Hay servidores HTTP que responden 404/405 a una notificación en vez del 202 del
    protocolo. Tumbar por eso un handshake que ya salió bien sería peor."""
    transporte = TransporteFalso([_INIT_OK])
    transporte.send_notification = lambda mensaje: (_ for _ in ()).throw(MCPError("405"))
    cliente = MCPClient("prueba", transporte)

    cliente.initialize()

    assert cliente._inicializado


def test_si_el_servidor_habla_otra_version_se_sigue_igual():
    """El handshake de MCP permite que el servidor responda con la suya."""
    cliente = _cliente([{"result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "s"}}}])

    cliente.initialize()

    assert cliente._inicializado


def test_no_se_puede_listar_sin_handshake():
    cliente = _cliente([])

    with pytest.raises(MCPError, match="initialize"):
        cliente.list_tools()


def test_no_se_puede_ejecutar_sin_handshake():
    cliente = _cliente([])

    with pytest.raises(MCPError, match="initialize"):
        cliente.call_tool("search")


# ── Catálogo ────────────────────────────────────────────────────────

def test_se_lista_el_catalogo():
    cliente = _cliente([_INIT_OK, {"result": {"tools": [{"name": "a"}, {"name": "b"}]}}])
    cliente.initialize()

    catalogo = cliente.list_tools()

    assert [t["name"] for t in catalogo] == ["a", "b"]


def test_el_catalogo_paginado_se_resuelve_entero():
    cliente = _cliente([
        _INIT_OK,
        {"result": {"tools": [{"name": "a"}], "nextCursor": "p2"}},
        {"result": {"tools": [{"name": "b"}]}},
    ])
    cliente.initialize()

    catalogo = cliente.list_tools()

    assert [t["name"] for t in catalogo] == ["a", "b"]
    assert cliente._transporte.enviados[-1]["params"] == {"cursor": "p2"}


def test_un_servidor_que_pagina_para_siempre_no_cuelga_el_arranque():
    infinitas = [_INIT_OK] + [
        {"result": {"tools": [{"name": f"t{i}"}], "nextCursor": "otra"}} for i in range(50)
    ]
    cliente = _cliente(infinitas)
    cliente.initialize()

    catalogo = cliente.list_tools()

    assert len(catalogo) == mcp_client._MAX_PAGINAS


# ── Ejecución ───────────────────────────────────────────────────────

def test_ejecutar_devuelve_el_texto_del_resultado():
    cliente = _cliente([_INIT_OK, {"result": {"content": [{"type": "text", "text": "hola"}]}}])
    cliente.initialize()

    assert cliente.call_tool("echo", {"texto": "hola"}) == "hola"
    assert cliente._transporte.enviados[-1]["params"] == {
        "name": "echo", "arguments": {"texto": "hola"},
    }


def test_un_error_jsonrpc_se_convierte_en_excepcion():
    cliente = _cliente([_INIT_OK, {"error": {"code": -32601, "message": "método desconocido"}}])
    cliente.initialize()

    with pytest.raises(MCPError, match="método desconocido"):
        cliente.call_tool("no_existe")


def test_un_iserror_del_resultado_se_devuelve_como_texto():
    """Es distinto de un error JSON-RPC: el turno del loop de razonamiento no se pierde,
    el modelo lee el fallo y decide qué hacer."""
    cliente = _cliente([
        _INIT_OK,
        {"result": {"isError": True, "content": [{"type": "text", "text": "falta el token"}]}},
    ])
    cliente.initialize()

    resultado = cliente.call_tool("search")

    assert "Error de la herramienta" in resultado
    assert "falta el token" in resultado


# ── Aplanado del contenido ──────────────────────────────────────────

def test_varios_bloques_de_texto_se_unen():
    assert _contenido_a_texto([
        {"type": "text", "text": "uno"}, {"type": "text", "text": "dos"},
    ]) == "uno\ndos"


def test_un_recurso_con_texto_se_aprovecha():
    assert _contenido_a_texto([
        {"type": "resource", "resource": {"uri": "file://x", "text": "contenido"}},
    ]) == "contenido"


def test_lo_no_textual_se_describe_en_vez_de_desaparecer():
    """Descartarlo en silencio dejaría al usuario creyendo que la herramienta no devolvió nada."""
    salida = _contenido_a_texto([{"type": "image", "data": "..."}])

    assert "image" in salida and "no representable" in salida


def test_un_contenido_con_forma_rara_no_revienta():
    assert _contenido_a_texto(None) == ""
    assert _contenido_a_texto("ya es texto") == "ya es texto"
    assert _contenido_a_texto([None, 42]) == ""


# ── Transporte stdio, contra un servidor real ───────────────────────

_SERVIDOR_FALSO = textwrap.dedent('''
    import json, sys
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        msg = json.loads(linea)
        if "id" not in msg:
            continue
        metodo = msg.get("method")
        if metodo == "initialize":
            r = {"protocolVersion": "2024-11-05",
                 "serverInfo": {"name": "servidor-de-prueba", "version": "9.9"}}
        elif metodo == "tools/list":
            r = {"tools": [{"name": "echo", "description": "devuelve lo que le mandes",
                            "inputSchema": {"type": "object",
                                            "properties": {"texto": {"type": "string"}}}}]}
        elif metodo == "tools/call":
            texto = msg["params"]["arguments"].get("texto", "")
            r = {"content": [{"type": "text", "text": "eco: " + texto}]}
        else:
            r = {}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": r}) + "\\n")
        sys.stdout.flush()
''')


@pytest.fixture
def servidor_stdio(tmp_path):
    ruta = tmp_path / "servidor_mcp_falso.py"
    ruta.write_text(_SERVIDOR_FALSO, encoding="utf-8")
    return {"command": sys.executable, "args": [str(ruta)]}


def test_stdio_conversacion_completa_contra_un_proceso_real(servidor_stdio):
    """El camino de verdad: subproceso, pipes, hilo lector y cola."""
    transporte = crear_transporte("real", servidor_stdio)
    assert isinstance(transporte, StdioTransport)
    cliente = MCPClient("real", transporte, connect_timeout=15, request_timeout=15)
    try:
        info = cliente.initialize()
        assert info["name"] == "servidor-de-prueba"

        catalogo = cliente.list_tools()
        assert [t["name"] for t in catalogo] == ["echo"]
        assert catalogo[0]["inputSchema"]["type"] == "object"

        assert cliente.call_tool("echo", {"texto": "hola"}) == "eco: hola"
    finally:
        cliente.close()


def test_stdio_detecta_al_instante_que_el_servidor_murio(tmp_path):
    """Sin esto se esperaba el timeout completo —30s por defecto— para descubrir algo que
    el sistema operativo ya sabía."""
    suicida = tmp_path / "suicida.py"
    suicida.write_text("import sys\nsys.stdin.readline()\nsys.exit(3)\n", encoding="utf-8")
    cliente = MCPClient(
        "suicida",
        crear_transporte("suicida", {"command": sys.executable, "args": [str(suicida)]}),
        connect_timeout=30.0,
    )
    try:
        comienzo = time.monotonic()
        with pytest.raises(MCPError, match="terminó"):
            cliente.initialize()
        assert time.monotonic() - comienzo < 10, "esperó el timeout entero"
    finally:
        cliente.close()


def test_stdio_avisa_claro_si_el_comando_no_existe():
    with pytest.raises(MCPError, match="no se pudo lanzar"):
        StdioTransport("fantasma", "este_comando_no_existe_en_ninguna_parte_12345")


def test_stdio_pone_timeout_si_el_servidor_no_contesta(tmp_path):
    """Un servidor que se queda callado no puede colgar el arranque para siempre."""
    mudo = tmp_path / "mudo.py"
    mudo.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    cliente = MCPClient(
        "mudo", crear_transporte("mudo", {"command": sys.executable, "args": [str(mudo)]}),
        connect_timeout=1.0,
    )
    try:
        with pytest.raises(MCPError, match="no respondió"):
            cliente.initialize()
    finally:
        cliente.close()


# ── Transporte HTTP ─────────────────────────────────────────────────

class _RespuestaFalsa:
    def __init__(self, cuerpo, tipo="application/json", status=200, session=None):
        self._cuerpo = cuerpo
        self.status_code = status
        self.text = cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo)
        self.headers = {"Content-Type": tipo}
        if session:
            self.headers["Mcp-Session-Id"] = session

    def json(self):
        return json.loads(self.text)


def test_http_reenvia_el_id_de_sesion(monkeypatch):
    """Sin esto, un servidor con estado trata cada petición como conexión nueva y
    `tools/call` falla después de un initialize que parecía correcto."""
    llamadas = []

    def _post(url, json=None, headers=None, timeout=None):
        llamadas.append(headers)
        if "id" not in json:                      # notifications/initialized
            return _RespuestaFalsa("", tipo="text/plain", status=202)
        cuerpo = {"jsonrpc": "2.0", "id": json["id"], "result": {"serverInfo": {"name": "s"}}}
        return _RespuestaFalsa(cuerpo, session="sesion-123" if len(llamadas) == 1 else None)

    import requests
    monkeypatch.setattr(requests, "post", _post)

    cliente = MCPClient("http", HttpTransport("http", "https://ejemplo.com/mcp"))
    cliente.initialize()
    cliente.list_tools()

    assert "Mcp-Session-Id" not in llamadas[0]
    assert llamadas[-1]["Mcp-Session-Id"] == "sesion-123"


def test_http_entiende_una_respuesta_sse(monkeypatch):
    cuerpo = '{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"sse"}}}'
    sse = f"event: message\ndata: {cuerpo}\n\n"

    import requests
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _RespuestaFalsa(sse, tipo="text/event-stream"),
    )

    cliente = MCPClient("http", HttpTransport("http", "https://ejemplo.com/mcp"))

    assert cliente.initialize()["name"] == "sse"


def test_http_reporta_un_error_del_servidor(monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _RespuestaFalsa("servidor roto", tipo="text/plain", status=500),
    )

    cliente = MCPClient("http", HttpTransport("http", "https://ejemplo.com/mcp"))

    with pytest.raises(MCPError, match="500"):
        cliente.initialize()


# ── OAuth en el transporte HTTP ─────────────────────────────────────

def test_un_401_sin_oauth_configurado_dice_como_activarlo(monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _RespuestaFalsa("", tipo="text/plain", status=401),
    )

    cliente = MCPClient("hosted", HttpTransport("hosted", "https://ejemplo.com/mcp"))

    with pytest.raises(MCPError, match='"oauth": true'):
        cliente.initialize()


def test_un_401_con_oauth_configurado_manda_a_loguearse(monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, "post", lambda *a, **k: _RespuestaFalsa("", tipo="text/plain", status=401),
    )

    transporte = HttpTransport("hosted", "https://ejemplo.com/mcp", oauth=True)
    cliente = MCPClient("hosted", transporte)

    with pytest.raises(MCPError, match="login hosted"):
        cliente.initialize()


def test_del_401_se_guarda_donde_esta_la_metadata(monkeypatch):
    """`login_servidor()` la usa para no tener que adivinar el servidor de autorización."""
    import requests

    respuesta = _RespuestaFalsa("", tipo="text/plain", status=401)
    respuesta.headers["WWW-Authenticate"] = 'Bearer resource_metadata="https://a.com/meta"'
    monkeypatch.setattr(requests, "post", lambda *a, **k: respuesta)

    transporte = HttpTransport("hosted", "https://ejemplo.com/mcp", oauth=True)
    with pytest.raises(MCPError):
        MCPClient("hosted", transporte).initialize()

    assert transporte.url_metadata_oauth == "https://a.com/meta"


def test_el_token_guardado_viaja_en_la_cabecera(monkeypatch, tmp_path):
    from core import mcp_oauth

    monkeypatch.setattr(mcp_oauth, "TOKENS_FILE", str(tmp_path / "t.json"))
    mcp_oauth.guardar_tokens({"hosted": {"access_token": "token-vivo"}})

    capturadas = {}

    def _post(url, json=None, headers=None, timeout=None):
        capturadas.update(headers)
        return _RespuestaFalsa({"jsonrpc": "2.0", "id": json.get("id"), "result": {}})

    import requests
    monkeypatch.setattr(requests, "post", _post)

    MCPClient("hosted", HttpTransport("hosted", "https://x/mcp", oauth=True)).initialize()

    assert capturadas["Authorization"] == "Bearer token-vivo"


def test_sin_oauth_no_se_manda_ninguna_autorizacion(monkeypatch):
    capturadas = {}

    def _post(url, json=None, headers=None, timeout=None):
        capturadas.update(headers)
        return _RespuestaFalsa({"jsonrpc": "2.0", "id": json.get("id"), "result": {}})

    import requests
    monkeypatch.setattr(requests, "post", _post)

    MCPClient("simple", HttpTransport("simple", "https://x/mcp")).initialize()

    assert "Authorization" not in capturadas


# ── Recursos y prompts ──────────────────────────────────────────────

_INIT_COMPLETO = {"result": {
    "protocolVersion": "2024-11-05",
    "serverInfo": {"name": "s"},
    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
}}


def test_se_sabe_que_declara_el_servidor():
    cliente = _cliente([_INIT_COMPLETO])
    cliente.initialize()

    assert cliente.soporta("resources")
    assert not cliente.soporta("sampling")


def test_a_un_servidor_sin_recursos_no_se_le_preguntan():
    """Preguntarle por algo que no ofrece es pedir un error que ensucia el log."""
    cliente = _cliente([_INIT_OK])
    cliente.initialize()

    assert cliente.list_resources() == []
    assert cliente.list_prompts() == []


def test_se_listan_los_recursos():
    cliente = _cliente([_INIT_COMPLETO, {"result": {"resources": [{"uri": "file://a"}]}}])
    cliente.initialize()

    assert cliente.list_resources()[0]["uri"] == "file://a"


def test_un_recurso_se_lee_como_texto():
    cliente = _cliente([
        _INIT_COMPLETO,
        {"result": {"contents": [{"uri": "file://a", "text": "el contenido"}]}},
    ])
    cliente.initialize()

    assert cliente.read_resource("file://a") == "el contenido"


def test_un_recurso_binario_se_describe_en_vez_de_volcar_base64():
    cliente = _cliente([
        _INIT_COMPLETO,
        {"result": {"contents": [{"uri": "file://img.png", "blob": "iVBORw0KGgo="}]}},
    ])
    cliente.initialize()

    salida = cliente.read_resource("file://img.png")

    assert "binario" in salida and "iVBOR" not in salida


def test_un_prompt_se_resuelve_a_texto():
    cliente = _cliente([_INIT_COMPLETO, {"result": {"messages": [
        {"role": "user", "content": {"type": "text", "text": "resumí esto"}},
    ]}}])
    cliente.initialize()

    assert cliente.get_prompt("resumen") == "user: resumí esto"


def test_los_recursos_tambien_paginan():
    cliente = _cliente([
        _INIT_COMPLETO,
        {"result": {"resources": [{"uri": "a"}], "nextCursor": "p2"}},
        {"result": {"resources": [{"uri": "b"}]}},
    ])
    cliente.initialize()

    assert [r["uri"] for r in cliente.list_resources()] == ["a", "b"]
