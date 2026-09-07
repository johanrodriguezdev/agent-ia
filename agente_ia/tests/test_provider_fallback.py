"""
tests/test_provider_fallback.py
Pruebas de la caída entre proveedores de `ai/llm_provider.py`.

Lo que protege esta suite: **que un fallo de un proveedor no deje al agente mudo**. Si
DeepSeek se cae, se queda sin crédito o no responde, la conversación debe continuar con
otro en vez de devolver un error al usuario.

Ningún test llama a un proveedor real.
"""

import pytest

import ai.llm_provider as prov


# ── La cadena ───────────────────────────────────────────────────────

def test_sin_respaldo_configurado_la_cadena_esta_vacia():
    assert prov._cadena_de_respaldo("deepseek", "") == []
    assert prov._cadena_de_respaldo("deepseek", None) == []


def test_un_respaldo_suelto_sigue_funcionando():
    """Comportamiento anterior: la configuración de quien ya lo tenía no se rompe."""
    assert prov._cadena_de_respaldo("deepseek", "ollama") == ["ollama"]


def test_se_pueden_encadenar_varios():
    assert prov._cadena_de_respaldo("deepseek", "ollama openai") == ["ollama", "openai"]
    assert prov._cadena_de_respaldo("deepseek", "ollama, openai") == ["ollama", "openai"]
    assert prov._cadena_de_respaldo("deepseek", ["ollama", "openai"]) == ["ollama", "openai"]


def test_el_proveedor_que_ya_fallo_no_entra_en_la_cadena():
    """Reintentar el que acaba de fallar solo gasta tiempo."""
    assert prov._cadena_de_respaldo("ollama", "ollama openai") == ["openai"]


def test_no_se_repiten_respaldos():
    assert prov._cadena_de_respaldo("deepseek", "ollama ollama openai") == ["ollama", "openai"]


# ── El recorrido ────────────────────────────────────────────────────

def test_si_el_primer_respaldo_responde_se_usa(monkeypatch):
    llamados = []

    def _fake(proveedor, *a, **k):
        llamados.append(proveedor)
        return "respuesta del respaldo"

    monkeypatch.setattr(prov, "_uncached_call", _fake)

    resultado = prov._intentar_respaldos(
        "deepseek", Exception("caido"), [], "sp", None, "m", None, "ollama",
    )

    assert resultado == "respuesta del respaldo"
    assert llamados == ["ollama"]


def test_si_el_primero_falla_se_prueba_el_siguiente(monkeypatch):
    """Antes se rendía tras un único intento."""
    llamados = []

    def _fake(proveedor, *a, **k):
        llamados.append(proveedor)
        if proveedor == "ollama":
            raise RuntimeError("tampoco está")
        return "respuesta de openai"

    monkeypatch.setattr(prov, "_uncached_call", _fake)

    resultado = prov._intentar_respaldos(
        "deepseek", Exception("caido"), [], "sp", None, "m", None, "ollama openai",
    )

    assert resultado == "respuesta de openai"
    assert llamados == ["ollama", "openai"]


def test_si_todos_fallan_se_avisa_sin_tecnicismos(monkeypatch):
    monkeypatch.setattr(
        prov, "_uncached_call",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("caido")),
    )

    resultado = prov._intentar_respaldos(
        "deepseek", Exception("caido"), [], "sp", None, "m", None, "ollama openai",
    )

    assert "No consigo comunicarme" in resultado
    assert "RuntimeError" not in resultado       # el detalle va al log, no al usuario


def test_sin_ningun_destino_se_devuelve_sin_proveedor(monkeypatch):
    """REQ-022/CA-11: antes se devolvía el texto crudo de la excepción original
    (`f"Error ({activo}): {error_original}"`) — eso es justo el tecnicismo que este REQ
    saca de la vista del usuario. Con la cadena resuelta genuinamente vacía (ni respaldo
    explícito ni default posible), la respuesta es siempre `SIN_PROVEEDOR`.

    `_resolver_cadena_de_respaldo` se monkeypatchea para forzar una cadena vacía: con
    `fallback_config=""` el código real cae al default de CA-06 (OpenRouter->Ollama), que
    salvo en una instalación sin Ollama y sin clave de OpenRouter, no está vacío — probar
    eso de verdad dependería de la máquina que corre el test.
    """
    monkeypatch.setattr(prov, "_resolver_cadena_de_respaldo", lambda activo, cfg: [])

    resultado = prov._intentar_respaldos(
        "deepseek", Exception("sin credito"), [], "sp", None, "m", None, "",
    )

    assert resultado == prov.SIN_PROVEEDOR
    assert "sin credito" not in resultado


def test_una_respuesta_de_error_del_respaldo_cuenta_como_fallo(monkeypatch):
    """Algunos proveedores devuelven "Error: ..." como texto en vez de lanzar."""
    llamados = []

    def _fake(proveedor, *a, **k):
        llamados.append(proveedor)
        if proveedor == "ollama":
            return "Error: no está instalado"
        return "respuesta buena"

    monkeypatch.setattr(prov, "_uncached_call", _fake)

    resultado = prov._intentar_respaldos(
        "deepseek", Exception("x"), [], "sp", None, "m", None, "ollama openai",
    )

    assert resultado == "respuesta buena"
    assert llamados == ["ollama", "openai"]


# ── Detalles que marcan la diferencia ───────────────────────────────

def test_el_respaldo_conserva_las_herramientas(monkeypatch):
    """Antes se perdían: el agente caía a un modo sin poder buscar ni consultar nada."""
    recibido = {}

    def _fake(proveedor, messages, system_prompt, image_path, model, tools=None):
        recibido["tools"] = tools
        return "ok"

    monkeypatch.setattr(prov, "_uncached_call", _fake)
    herramientas = [{"name": "web_search"}]

    prov._intentar_respaldos(
        "deepseek", Exception("x"), [], "sp", None, "m", herramientas, "openai",
    )

    assert recibido["tools"] == herramientas


def test_un_respaldo_sin_tool_calling_no_recibe_herramientas(monkeypatch):
    recibido = {}

    def _fake(proveedor, messages, system_prompt, image_path, model, tools=None):
        recibido["tools"] = tools
        return "ok"

    monkeypatch.setattr(prov, "_uncached_call", _fake)

    prov._intentar_respaldos(
        "deepseek", Exception("x"), [], "sp", None, "m", [{"name": "x"}], "ollama",
    )

    assert recibido["tools"] is None


def test_cada_respaldo_usa_su_propio_modelo(monkeypatch):
    """Pedirle "deepseek-chat" a Ollama garantiza que el respaldo falle también."""
    recibido = {}

    def _fake(proveedor, messages, system_prompt, image_path, model, tools=None):
        recibido["modelo"] = model
        return "ok"

    monkeypatch.setattr(prov, "_uncached_call", _fake)

    prov._intentar_respaldos(
        "deepseek", Exception("x"), [], "sp", None, "deepseek-chat", None, "ollama",
    )

    assert recibido["modelo"] == prov._MODELO_POR_PROVEEDOR["ollama"]


def test_el_usuario_no_ve_avisos_de_infraestructura(monkeypatch):
    """Antes la respuesta llegaba con "[Fallback activado...]" pegado delante."""
    monkeypatch.setattr(prov, "_uncached_call", lambda *a, **k: "La respuesta de siempre.")

    resultado = prov._intentar_respaldos(
        "deepseek", Exception("x"), [], "sp", None, "m", None, "ollama",
    )

    assert resultado == "La respuesta de siempre."
    assert "allback" not in resultado
