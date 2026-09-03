"""
tests/test_mcp_oauth.py
OAuth 2.1 para servidores MCP (`core/mcp_oauth.py`).

Lo que protege esta suite: **que las credenciales se manejen bien**. PKCE bien calculado,
`state` verificado (sin eso cualquier pestaña abierta en el navegador podría hacernos
canjear un código ajeno), tokens que se refrescan solos, y un archivo de credenciales que
ante la duda se trata como vacío en vez de como válido.

Ningún test sale a internet: el descubrimiento y los canjes van contra `requests` mockeado,
y el loopback se prueba contra sí mismo en localhost.
"""

import base64
import hashlib
import json
import threading
import time

import pytest
import requests

from core import mcp_oauth


@pytest.fixture(autouse=True)
def _tokens_en_temporal(monkeypatch, tmp_path):
    """Nunca escribir el mcp_tokens.json real: son credenciales de verdad."""
    monkeypatch.setattr(mcp_oauth, "TOKENS_FILE", str(tmp_path / "mcp_tokens.json"))


class _Respuesta:
    def __init__(self, cuerpo=None, status=200, headers=None, texto=None):
        self._cuerpo = cuerpo
        self.status_code = status
        self.headers = headers or {}
        self.text = texto if texto is not None else json.dumps(cuerpo or {})

    def json(self):
        if self._cuerpo is None:
            raise ValueError("no es JSON")
        return self._cuerpo


# ── PKCE ────────────────────────────────────────────────────────────

def test_el_challenge_es_el_sha256_del_verifier():
    verifier, challenge = mcp_oauth.generar_pkce()

    esperado = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    assert challenge == esperado


def test_el_challenge_no_lleva_relleno():
    """El '=' de base64 no es válido en base64url para PKCE."""
    _, challenge = mcp_oauth.generar_pkce()

    assert "=" not in challenge


def test_cada_autorizacion_usa_un_verifier_distinto():
    assert mcp_oauth.generar_pkce()[0] != mcp_oauth.generar_pkce()[0]


def test_el_verifier_respeta_el_largo_del_estandar():
    verifier, _ = mcp_oauth.generar_pkce()

    assert 43 <= len(verifier) <= 128


# ── Almacén de credenciales ─────────────────────────────────────────

def test_las_credenciales_sobreviven_al_reinicio():
    mcp_oauth.guardar_tokens({"notion": {"access_token": "abc"}})

    assert mcp_oauth.cargar_tokens()["notion"]["access_token"] == "abc"


def test_un_archivo_de_credenciales_corrupto_no_rompe_nada():
    with open(mcp_oauth.TOKENS_FILE, "w", encoding="utf-8") as f:
        f.write("{roto")

    assert mcp_oauth.cargar_tokens() == {}


def test_se_pueden_olvidar_las_credenciales_de_un_servidor():
    mcp_oauth.guardar_tokens({"notion": {"access_token": "abc"}, "otro": {"access_token": "x"}})

    assert mcp_oauth.olvidar("notion") is True
    assert "notion" not in mcp_oauth.cargar_tokens()
    assert "otro" in mcp_oauth.cargar_tokens()


def test_olvidar_algo_que_no_estaba_no_es_un_error():
    assert mcp_oauth.olvidar("fantasma") is False


# ── Vencimiento ─────────────────────────────────────────────────────

def test_el_vencimiento_relativo_se_guarda_como_instante_absoluto():
    """Guardar `expires_in` sería inútil: al releerlo no se sabe cuánto tiempo pasó."""
    guardado = mcp_oauth._con_vencimiento({"access_token": "a", "expires_in": 3600})

    assert guardado["expires_at"] > time.time() + 3500


def test_un_token_sin_vencimiento_declarado_no_se_da_por_vencido():
    assert not mcp_oauth.esta_vencido({"access_token": "a"})


def test_un_token_pasado_esta_vencido():
    assert mcp_oauth.esta_vencido({"expires_at": time.time() - 10})


def test_un_token_a_punto_de_vencer_ya_cuenta_como_vencido():
    """Sin margen, un token que vence a mitad de la llamada la hace fallar."""
    assert mcp_oauth.esta_vencido({"expires_at": time.time() + 5})


# ── Descubrimiento ──────────────────────────────────────────────────

def test_se_extrae_la_metadata_del_401():
    respuesta = _Respuesta(status=401, headers={
        "WWW-Authenticate": 'Bearer resource_metadata="https://x.com/.well-known/oauth"',
    })

    assert mcp_oauth.url_de_metadata_desde_401(respuesta) == "https://x.com/.well-known/oauth"


def test_un_401_sin_metadata_no_inventa_nada():
    assert mcp_oauth.url_de_metadata_desde_401(_Respuesta(status=401, headers={})) is None


def test_se_usa_el_servidor_de_autorizacion_que_declara_la_metadata(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Respuesta(
        {"authorization_servers": ["https://auth.ejemplo.com"]},
    ))

    base = mcp_oauth.descubrir_servidor_de_autorizacion("https://mcp.ejemplo.com/mcp")

    assert base == "https://auth.ejemplo.com"


def test_sin_metadata_se_asume_el_mismo_origen(monkeypatch):
    """Hay bastantes servidores que funcionan y no publican la metadata del estándar."""
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Respuesta(status=404))

    base = mcp_oauth.descubrir_servidor_de_autorizacion("https://mcp.ejemplo.com/algo/mcp")

    assert base == "https://mcp.ejemplo.com"


def test_los_endpoints_salen_de_la_metadata_del_servidor(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Respuesta({
        "authorization_endpoint": "https://auth.x/oauth/authorize",
        "token_endpoint": "https://auth.x/oauth/token",
    }))

    metadata = mcp_oauth.descubrir_endpoints("https://auth.x")

    assert metadata["authorization_endpoint"] == "https://auth.x/oauth/authorize"


def test_sin_metadata_los_endpoints_se_arman_por_convencion(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Respuesta(status=404))

    metadata = mcp_oauth.descubrir_endpoints("https://auth.x")

    assert metadata["authorization_endpoint"] == "https://auth.x/authorize"
    assert metadata["token_endpoint"] == "https://auth.x/token"


# ── Registro dinámico ───────────────────────────────────────────────

def test_el_registro_dinamico_devuelve_el_client_id(monkeypatch):
    enviado = {}

    def _post(url, timeout=None, json=None):
        enviado.update(json)
        return _Respuesta({"client_id": "cliente-123"}, status=201)

    monkeypatch.setattr(requests, "post", _post)

    assert mcp_oauth.registrar_cliente({"registration_endpoint": "https://auth.x/register"}) \
        == "cliente-123"
    assert enviado["redirect_uris"] == [mcp_oauth.REDIRECT_URI]
    assert "refresh_token" in enviado["grant_types"]


def test_sin_registro_dinamico_se_explica_que_hacer():
    with pytest.raises(mcp_oauth.OAuthError, match="client_id"):
        mcp_oauth.registrar_cliente({})


# ── Refresco ────────────────────────────────────────────────────────

def _guardado(**extra):
    base = {
        "access_token": "viejo",
        "refresh_token": "refresco",
        "token_endpoint": "https://auth.x/token",
        "client_id": "c1",
        "expires_at": time.time() - 10,
    }
    base.update(extra)
    return base


def test_un_token_vencido_se_refresca_solo(monkeypatch):
    mcp_oauth.guardar_tokens({"notion": _guardado()})
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Respuesta(
        {"access_token": "nuevo", "expires_in": 3600},
    ))

    assert mcp_oauth.access_token_valido("notion") == "nuevo"


def test_al_refrescar_se_conserva_el_refresh_token_si_no_mandan_uno(monkeypatch):
    """Borrarlo obligaría a un login manual en la renovación siguiente."""
    mcp_oauth.guardar_tokens({"notion": _guardado()})
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Respuesta({"access_token": "nuevo"}))

    mcp_oauth.access_token_valido("notion")

    assert mcp_oauth.cargar_tokens()["notion"]["refresh_token"] == "refresco"


def test_si_el_refresco_falla_se_avisa_con_none(monkeypatch):
    mcp_oauth.guardar_tokens({"notion": _guardado()})
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Respuesta(status=400, texto="expirado"))

    assert mcp_oauth.access_token_valido("notion") is None


def test_un_token_vigente_no_se_refresca(monkeypatch):
    mcp_oauth.guardar_tokens({"notion": _guardado(expires_at=time.time() + 9999)})

    def _no_llamar(*a, **k):
        raise AssertionError("no debería refrescar un token vigente")

    monkeypatch.setattr(requests, "post", _no_llamar)

    assert mcp_oauth.access_token_valido("notion") == "viejo"


def test_sin_credenciales_guardadas_no_hay_token():
    assert mcp_oauth.access_token_valido("nunca_logueado") is None


def test_sin_refresh_token_no_se_puede_renovar():
    mcp_oauth.guardar_tokens({"notion": _guardado(refresh_token=None)})

    assert mcp_oauth.access_token_valido("notion") is None


# ── Loopback ────────────────────────────────────────────────────────

def _pedir_callback(parametros, resultado):
    """Simula la vuelta del navegador al puerto local."""
    time.sleep(0.4)
    try:
        requests.get(f"http://127.0.0.1:{mcp_oauth.PUERTO_REDIRECCION}/callback",
                     params=parametros, timeout=5)
    except Exception as e:      # el servidor puede cerrar antes de responder del todo
        resultado["error_cliente"] = e


def test_el_loopback_recibe_el_codigo_del_navegador():
    resultado = {}
    threading.Thread(
        target=_pedir_callback, args=({"code": "abc123", "state": "esperado"}, resultado),
        daemon=True,
    ).start()

    assert mcp_oauth.esperar_codigo("esperado", timeout=10) == "abc123"


def test_un_state_que_no_coincide_se_rechaza():
    """Sin esto, cualquier página abierta en el navegador podría llamar a este puerto y
    hacernos canjear un código ajeno."""
    resultado = {}
    threading.Thread(
        target=_pedir_callback, args=({"code": "abc", "state": "otro"}, resultado), daemon=True,
    ).start()

    with pytest.raises(mcp_oauth.OAuthError, match="state"):
        mcp_oauth.esperar_codigo("esperado", timeout=10)


def test_si_el_servidor_de_autorizacion_rechaza_se_reporta():
    resultado = {}
    threading.Thread(
        target=_pedir_callback, args=({"error": "access_denied"}, resultado), daemon=True,
    ).start()

    with pytest.raises(mcp_oauth.OAuthError, match="access_denied"):
        mcp_oauth.esperar_codigo("esperado", timeout=10)
