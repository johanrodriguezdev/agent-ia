"""
tests/test_http_seguro.py
REQ-031 — `core/http_seguro.py`: a dónde puede conectarse el agente.

El bug que cierra estaba vivo: `web_read` es 🟢 verde —o sea alcanzable desde Telegram— y
`leer_pagina()` validaba solo el esquema, así que un mensaje podía hacer que el agente
leyera `http://127.0.0.1:3000` o `http://192.168.1.1` y devolviera el contenido al chat.
Reproducido antes de escribir el módulo (`workspace/adjuntos/REQ-031/origen/`).

Sin red (.claude/rules/testing.md): `127.0.0.1` y `localhost` resuelven sin salir del
equipo, y para cualquier nombre público se sustituye `getaddrinfo`.
"""

import socket

import pytest

import core.http_seguro as hs
from core.http_seguro import DestinoBloqueado, pedir, validar_url


def _resolver_a(monkeypatch, ip: str) -> None:
    """Hace que cualquier nombre resuelva a `ip`, sin tocar la red."""
    def _falso(host, puerto, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, puerto))]

    monkeypatch.setattr(hs.socket, "getaddrinfo", _falso)


class _RespuestaFalsa:
    """Doble de la respuesta de `requests`, con `iter_content` como el real."""

    def __init__(self, status=200, headers=None, contenido=b"contenido", encoding="utf-8"):
        self.status_code = status
        self.headers = headers or {"Content-Type": "text/plain"}
        self.encoding = encoding
        self.is_redirect = status in (301, 302, 303, 307, 308)
        self._contenido = contenido

    def iter_content(self, tamano):
        for i in range(0, len(self._contenido), tamano):
            yield self._contenido[i:i + tamano]

    def close(self):
        return None


# ─────────────────────────── esquemas ───────────────────────────

@pytest.mark.parametrize("url", [
    "file:///C:/Users/alguien/.ssh/id_rsa",
    "ftp://servidor/archivo",
    "data:text/html,<h1>hola</h1>",
    "javascript:alert(1)",
])
def test_solo_se_permiten_http_y_https(url):
    """`urlopen()` entiende `file://`: un esquema no validado es un lector de archivos."""
    with pytest.raises(DestinoBloqueado):
        validar_url(url)


def test_una_url_vacia_se_rechaza():
    with pytest.raises(DestinoBloqueado):
        validar_url("   ")


# ─────────────────────────── destinos internos ───────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:3000/panel",
    "http://localhost:8080/",
    "http://[::1]:9000/",
])
def test_la_propia_maquina_se_rechaza(url):
    """El caso reproducido: un servicio local leído desde una herramienta verde."""
    with pytest.raises(DestinoBloqueado):
        validar_url(url)


@pytest.mark.parametrize("ip", ["10.0.0.5", "192.168.1.1", "172.16.0.9"])
def test_la_red_local_se_rechaza(monkeypatch, ip):
    """El router de casa y cualquier servicio de la LAN. Se mira la IP RESUELTA: un dominio
    normal que apunte adentro es el mismo ataque escrito de otra forma."""
    _resolver_a(monkeypatch, ip)
    with pytest.raises(DestinoBloqueado):
        validar_url("http://parece-de-internet.example/")


def test_el_endpoint_de_metadatos_de_la_nube_se_rechaza():
    """169.254.169.254 es donde viven las credenciales de una instancia: el destino clásico
    de un SSRF. Tiene que rechazarse POR POLÍTICA, sin intentar conectarse."""
    with pytest.raises(DestinoBloqueado):
        validar_url("http://169.254.169.254/latest/meta-data/")


def test_un_destino_publico_se_acepta(monkeypatch):
    """La contracara: el guard no puede dejar al agente sin internet."""
    _resolver_a(monkeypatch, "93.184.216.34")
    assert validar_url("https://ejemplo.example/pagina") == "https://ejemplo.example/pagina"


def test_un_nombre_que_no_resuelve_se_rechaza_con_un_motivo(monkeypatch):
    def _falla(*a, **k):
        raise socket.gaierror("no existe")

    monkeypatch.setattr(hs.socket, "getaddrinfo", _falla)
    with pytest.raises(DestinoBloqueado):
        validar_url("https://esto-no-existe.example/")


# ─────────────────────────── redirecciones ───────────────────────────

def test_una_redireccion_hacia_adentro_se_corta(monkeypatch):
    """El error clásico: validar la primera dirección y seguir las redirecciones a ciegas.
    Una URL pública puede redirigir a `127.0.0.1`."""
    _resolver_a(monkeypatch, "93.184.216.34")

    def _request(metodo, url, **kwargs):
        return _RespuestaFalsa(status=302, headers={"Location": "http://127.0.0.1:9/"})

    monkeypatch.setattr("requests.request", _request)
    # El salto se valida con el `getaddrinfo` real: `127.0.0.1` es loopback de verdad.
    monkeypatch.setattr(hs.socket, "getaddrinfo", socket.getaddrinfo)

    with pytest.raises(DestinoBloqueado):
        pedir("https://ejemplo.example/redirige")


def test_una_redireccion_hacia_afuera_se_sigue(monkeypatch):
    _resolver_a(monkeypatch, "93.184.216.34")
    saltos = {"n": 0}

    def _request(metodo, url, **kwargs):
        saltos["n"] += 1
        if saltos["n"] == 1:
            return _RespuestaFalsa(status=302, headers={"Location": "https://otro.example/final"})
        return _RespuestaFalsa(contenido=b"destino final")

    monkeypatch.setattr("requests.request", _request)

    respuesta = pedir("https://ejemplo.example/redirige")

    assert respuesta.texto == "destino final"
    assert respuesta.url_final == "https://otro.example/final"


def test_un_bucle_de_redirecciones_no_es_infinito(monkeypatch):
    _resolver_a(monkeypatch, "93.184.216.34")

    def _request(metodo, url, **kwargs):
        return _RespuestaFalsa(status=302, headers={"Location": "https://ejemplo.example/otra"})

    monkeypatch.setattr("requests.request", _request)

    with pytest.raises(DestinoBloqueado):
        pedir("https://ejemplo.example/vueltas")


# ─────────────────────────── tamaño y métodos ───────────────────────────

def test_una_respuesta_enorme_se_corta_mientras_se_descarga(monkeypatch):
    """Se corta al descargar, no después: una respuesta de gigabytes no puede llenar la
    memoria antes de que a alguien se le ocurra medirla."""
    _resolver_a(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(
        "requests.request",
        lambda metodo, url, **k: _RespuestaFalsa(contenido=b"x" * 50_000),
    )

    respuesta = pedir("https://ejemplo.example/gigante", max_bytes=1000)

    assert respuesta.truncada is True
    assert len(respuesta.texto) < 50_000


@pytest.mark.parametrize("metodo", ["TRACE", "CONNECT", "PROPFIND", "borrar todo"])
def test_un_metodo_fuera_de_la_lista_se_rechaza(monkeypatch, metodo):
    _resolver_a(monkeypatch, "93.184.216.34")
    with pytest.raises(DestinoBloqueado):
        pedir("https://ejemplo.example/", metodo=metodo)


# ─────────────── el camino real: leer_pagina() ya no entra a la red local ───────────────

def test_leer_pagina_ya_no_lee_un_servicio_local():
    """La regresión del bug reportado, sobre la función que usa `web_read`."""
    from os_integration.web_search import leer_pagina

    salida = leer_pagina("http://127.0.0.1:3000/panel-interno")

    assert "propia máquina" in salida or "interna" in salida
    assert "PANEL" not in salida


# ─────────────────────── la herramienta http_request ───────────────────────

def _spec_http():
    import agents.tool_registry as tool_registry

    spec = tool_registry.get_tool("http_request")
    assert spec is not None, "'http_request' no está registrada"
    return spec


def test_http_request_es_amarilla_y_ningun_canal_remoto_la_alcanza():
    """Manda datos afuera: amarillo no es solo "pide confirmación", es además que
    `CHANNEL_ALLOWED_LEVELS` la deja fuera de Telegram, Discord, voz, API y correo."""
    from core.security_manager import ChannelType, RiskLevel, security_manager

    assert _spec_http().risk_level == RiskLevel.YELLOW
    assert security_manager.is_action_allowed("http_request", ChannelType.DESKTOP) is True
    for canal in (ChannelType.TELEGRAM, ChannelType.DISCORD, ChannelType.VOICE,
                  ChannelType.API, ChannelType.EMAIL, ChannelType.UNKNOWN):
        assert security_manager.is_action_allowed("http_request", canal) is False


def test_http_request_tiene_su_frase_en_castellano():
    """Sin esto el modal diría "¿Quiere que ejecute http request?"."""
    from core.acciones_legibles import describir

    assert "servicio de internet" in describir("http_request")


def test_http_request_resuelve_la_credencial_y_no_la_pide_en_el_texto(monkeypatch):
    """La cabecera viaja como ${VAR} y se resuelve contra el entorno: el token no queda en
    el historial del modelo ni en el log de auditoría."""
    monkeypatch.setenv("TOKEN_DE_PRUEBA_REQ031", "secreto-real-de-verdad")
    _resolver_a(monkeypatch, "93.184.216.34")
    capturadas = {}

    def _request(metodo, url, **kwargs):
        capturadas.update(kwargs.get("headers") or {})
        return _RespuestaFalsa(contenido=b"listo")

    monkeypatch.setattr("requests.request", _request)

    salida = _spec_http().invoke({
        "url": "https://api.example/recurso",
        "method": "POST",
        "headers": {"Authorization": "${TOKEN_DE_PRUEBA_REQ031}"},
        "body": "hola",
    })

    assert capturadas.get("Authorization") == "secreto-real-de-verdad"
    assert "listo" in salida


def test_http_request_manda_un_objeto_como_json(monkeypatch):
    _resolver_a(monkeypatch, "93.184.216.34")
    capturado = {}

    def _request(metodo, url, **kwargs):
        capturado["cuerpo"] = kwargs.get("data")
        capturado["headers"] = kwargs.get("headers") or {}
        return _RespuestaFalsa(contenido=b"ok")

    monkeypatch.setattr("requests.request", _request)

    _spec_http().invoke({"url": "https://api.example/x", "method": "POST",
                         "body": {"clave": "valor"}})

    assert capturado["cuerpo"] == '{"clave": "valor"}'
    assert capturado["headers"].get("Content-Type") == "application/json"


def test_http_request_si_puede_pegarle_al_servidor_local(monkeypatch):
    """REQ-036 — cambio deliberado sobre REQ-031: `http_request` SÍ alcanza direcciones
    internas, porque es amarilla, solo de escritorio, y confirma cada llamada mostrando la
    URL. Sin esto, el agente no puede probar el servidor de desarrollo que él mismo acaba de
    levantar con `project_start`, que es la mitad de un flujo de desarrollo."""
    llamadas = []

    def _request(metodo, url, **kwargs):
        llamadas.append(url)
        return _RespuestaFalsa(contenido=b"hola desde el server")

    monkeypatch.setattr("requests.request", _request)

    salida = _spec_http().invoke({"url": "http://127.0.0.1:8080/api/salud"})

    assert llamadas == ["http://127.0.0.1:8080/api/salud"]
    assert "hola desde el server" in salida


def test_web_read_sigue_sin_poder_leer_direcciones_internas():
    """La contracara, y es la que importa: el camino VERDE —alcanzable desde Telegram y por
    una inyección en una página— mantiene el bloqueo absoluto."""
    from os_integration.web_search import leer_pagina

    salida = leer_pagina("http://127.0.0.1:8080/panel-interno")

    assert "propia máquina" in salida or "interna" in salida


def test_un_destino_que_no_responde_vuelve_como_frase_y_no_como_excepcion():
    """Un fallo de conexión no puede cortar el turno del modelo."""
    salida = _spec_http().invoke({"url": "http://127.0.0.1:9/no-hay-nadie"})

    assert "No pude conectarme" in salida
