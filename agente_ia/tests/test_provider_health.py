"""
tests/test_provider_health.py
Pruebas del cooldown por proveedor (`ai/provider_health.py`) y de su efecto en el router
de `ai/llm_provider.py`.

Lo que protege esta suite: **que quedarse sin cuota deje de costar un timeout por mensaje**.
La cadena de respaldo ya salvaba la respuesta; lo que no evitaba era volver a empezar por
el proveedor muerto en cada cosa que el usuario dijera.

Y su contracara, igual de importante: que el cooldown NUNCA deje al agente sin a quién
preguntar. Apartar es reordenar, no descartar.

Ningún test llama a un proveedor real. El archivo de estado vive en un temporal por el
fixture `_aislar_cooldowns_de_proveedor` de conftest.py.
"""

import json
import time

import ai.llm_provider as prov
from ai import provider_health as salud


# ── Clasificación del error ─────────────────────────────────────────

def test_saldo_agotado_es_cuota():
    assert salud.clasificar_error("Insufficient Balance") == salud.CATEGORIA_CUOTA
    assert salud.clasificar_error("You exceeded your current quota") == salud.CATEGORIA_CUOTA
    assert salud.clasificar_error(Exception("402 Payment Required")) == salud.CATEGORIA_CUOTA


def test_un_429_por_velocidad_es_limite_de_tasa():
    assert salud.clasificar_error("429 Too Many Requests") == salud.CATEGORIA_LIMITE_TASA
    assert salud.clasificar_error("rate_limit_error") == salud.CATEGORIA_LIMITE_TASA
    assert salud.clasificar_error("overloaded_error") == salud.CATEGORIA_LIMITE_TASA


def test_un_429_por_cuota_agotada_cuenta_como_cuota_no_como_velocidad():
    """El caso que más importa distinguir: OpenAI devuelve 429 en los dos escenarios.

    Tratarlo como límite de velocidad haría reintentar en 60s algo que no vuelve en horas.
    """
    error = "Error code: 429 - {'type': 'insufficient_quota'}"
    assert salud.clasificar_error(error) == salud.CATEGORIA_CUOTA


def test_falta_de_api_key_es_un_problema_de_credenciales():
    """Es literalmente lo que devuelven `_ask_anthropic`/`_ask_gemini` sin clave."""
    error = "Error: ANTHROPIC_API_KEY no está configurada."
    assert salud.clasificar_error(error) == salud.CATEGORIA_CREDENCIALES
    assert salud.clasificar_error("401 Unauthorized") == salud.CATEGORIA_CREDENCIALES


def test_una_caida_de_red_no_entra_en_ninguna_categoria():
    """Es transitoria: apartar al proveedor por esto sería contraproducente."""
    assert salud.clasificar_error(ConnectionError("timed out")) == salud.CATEGORIA_OTRO
    assert salud.clasificar_error("Error: no está instalado") == salud.CATEGORIA_OTRO


def test_un_numero_parecido_a_un_codigo_http_no_confunde():
    """"4293 tokens" no puede apartar a un proveedor que está funcionando."""
    assert salud.clasificar_error("consumidos 4293 tokens de 8000") == salud.CATEGORIA_OTRO


# ── Aplicar y levantar el cooldown ──────────────────────────────────

def test_un_fallo_transitorio_no_aparta_a_nadie():
    assert salud.registrar_fallo("deepseek", ConnectionError("timed out")) == 0.0
    assert not salud.en_cooldown("deepseek")


def test_quedarse_sin_cuota_aparta_al_proveedor_un_buen_rato():
    aplicado = salud.registrar_fallo("deepseek", "Insufficient Balance")

    assert aplicado == salud.SEGUNDOS_POR_CATEGORIA[salud.CATEGORIA_CUOTA]
    assert salud.en_cooldown("deepseek")


def test_pasarse_de_velocidad_aparta_mucho_menos_tiempo():
    """Un límite por minuto se repone solo: media hora sería desperdiciar al proveedor."""
    aplicado = salud.registrar_fallo("gemini", "429 Too Many Requests")

    assert aplicado == salud.SEGUNDOS_POR_CATEGORIA[salud.CATEGORIA_LIMITE_TASA]
    assert aplicado < salud.SEGUNDOS_POR_CATEGORIA[salud.CATEGORIA_CUOTA]


def test_el_cooldown_se_vence_solo():
    salud.registrar_fallo("deepseek", "quota exceeded")
    salud._cooldowns["deepseek"]["hasta"] = time.time() - 1

    assert not salud.en_cooldown("deepseek")
    assert salud.segundos_restantes("deepseek") == 0.0


def test_una_respuesta_buena_levanta_el_cooldown_antes_de_tiempo():
    salud.registrar_fallo("deepseek", "quota exceeded")
    salud.registrar_exito("deepseek")

    assert not salud.en_cooldown("deepseek")


def test_el_nombre_del_proveedor_no_distingue_mayusculas():
    salud.registrar_fallo("DeepSeek", "quota exceeded")
    assert salud.en_cooldown("deepseek")


def test_un_reloj_que_salto_hacia_atras_no_deja_a_nadie_apartado_para_siempre():
    """Cambio de hora o VM suspendida: el "hasta" guardado podría quedar vivo días."""
    salud.registrar_fallo("deepseek", "quota exceeded")
    salud._cooldowns["deepseek"]["hasta"] = time.time() + 10 * 24 * 3600

    assert salud.segundos_restantes("deepseek") == float(salud._COOLDOWN_MAXIMO)


# ── El orden de intento ─────────────────────────────────────────────

def test_los_disponibles_van_primero_conservando_su_orden():
    salud.registrar_fallo("deepseek", "quota exceeded")

    assert salud.ordenar_por_disponibilidad(["deepseek", "ollama", "openai"]) == [
        "ollama", "openai", "deepseek",
    ]


def test_si_todos_estan_apartados_se_prueban_igual():
    """El cooldown es una optimización, no una restricción: nunca deja al agente mudo."""
    salud.registrar_fallo("deepseek", "quota exceeded")
    salud.registrar_fallo("ollama", "quota exceeded")

    assert salud.ordenar_por_disponibilidad(["deepseek", "ollama"]) == ["deepseek", "ollama"]


def test_ordenar_no_pierde_ningun_candidato():
    salud.registrar_fallo("ollama", "quota exceeded")
    candidatos = ["deepseek", "ollama", "openai"]

    assert sorted(salud.ordenar_por_disponibilidad(candidatos)) == sorted(candidatos)


# ── Persistencia ────────────────────────────────────────────────────

def test_el_cooldown_sobrevive_a_un_reinicio():
    """Reiniciar la app no debe volver a quemar la cuota que se acaba de agotar."""
    salud.registrar_fallo("deepseek", "Insufficient Balance")

    salud._cooldowns.clear()
    salud._cargado = False  # simula el arranque de un proceso nuevo

    assert salud.en_cooldown("deepseek")


def test_un_archivo_corrupto_se_trata_como_sin_cooldowns():
    """Fail-open: el peor caso es no ahorrar tiempo, nunca quedarse sin proveedor."""
    with open(salud.COOLDOWN_FILE, "w", encoding="utf-8") as f:
        f.write("{esto no es json")

    salud._cooldowns.clear()
    salud._cargado = False

    assert salud.estado() == {}
    assert not salud.en_cooldown("deepseek")


def test_un_json_valido_pero_absurdo_tampoco_rompe():
    with open(salud.COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump(["una", "lista"], f)

    salud._cooldowns.clear()
    salud._cargado = False

    assert salud.estado() == {}


def test_una_entrada_invalida_se_descarta_sin_arrastrar_a_las_demas():
    with open(salud.COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "roto": {"hasta": "mañana"},
            "tambien_roto": {"hasta": True},
            "deepseek": {"hasta": time.time() + 600, "categoria": "cuota"},
        }, f)

    salud._cooldowns.clear()
    salud._cargado = False

    assert salud.en_cooldown("deepseek")
    assert not salud.en_cooldown("roto")
    assert not salud.en_cooldown("tambien_roto")


# ── Efecto real sobre el router ─────────────────────────────────────

def _config(principal, respaldo, modelo="deepseek-chat"):
    return lambda: (principal, "", respaldo, modelo)


def test_con_el_principal_apartado_se_empieza_por_el_respaldo(monkeypatch):
    """El objetivo entero: no volver a gastar el timeout del proveedor sin cuota."""
    llamados = []
    monkeypatch.setattr(prov, "get_provider_config", _config("deepseek", "ollama"))
    monkeypatch.setattr(
        prov, "_cached_call", lambda p, *a, **k: (llamados.append(p), "hola")[1],
    )
    salud.registrar_fallo("deepseek", "Insufficient Balance")

    resultado = prov.generate_response([], "sp")

    assert resultado == "hola"
    assert llamados == ["ollama"]


def test_al_saltar_al_respaldo_por_cooldown_tambien_cambia_el_modelo(monkeypatch):
    """Pedirle "deepseek-chat" a Ollama garantiza el error, igual que en la cadena."""
    recibido = {}
    monkeypatch.setattr(prov, "get_provider_config", _config("deepseek", "ollama"))

    def _fake(proveedor, messages, system_prompt, image_path, model):
        recibido["modelo"] = model
        return "ok"

    monkeypatch.setattr(prov, "_cached_call", _fake)
    salud.registrar_fallo("deepseek", "Insufficient Balance")

    prov.generate_response([], "sp")

    assert recibido["modelo"] == prov._MODELO_POR_PROVEEDOR["ollama"]


def test_sin_respaldo_configurado_se_usa_el_principal_aunque_este_apartado(monkeypatch):
    """Fail-open de punta a punta: sin alternativa, se intenta igual."""
    llamados = []
    monkeypatch.setattr(prov, "get_provider_config", _config("deepseek", ""))
    monkeypatch.setattr(
        prov, "_cached_call", lambda p, *a, **k: (llamados.append(p), "hola")[1],
    )
    salud.registrar_fallo("deepseek", "Insufficient Balance")

    assert prov.generate_response([], "sp") == "hola"
    assert llamados == ["deepseek"]


def test_un_fallo_de_cuota_del_principal_lo_aparta_para_el_proximo_mensaje(monkeypatch):
    monkeypatch.setattr(prov, "get_provider_config", _config("deepseek", ""))
    monkeypatch.setattr(
        prov, "_cached_call",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429 insufficient_quota")),
    )

    prov.generate_response([], "sp")

    assert salud.en_cooldown("deepseek")


def test_un_error_devuelto_como_texto_tambien_aparta(monkeypatch):
    """Sin respaldo configurado, este caso antes no dejaba ningún rastro."""
    monkeypatch.setattr(prov, "get_provider_config", _config("gemini", "", "gemini-1.5-flash"))
    monkeypatch.setattr(
        prov, "_cached_call", lambda *a, **k: "Error: GEMINI_API_KEY no está configurada.",
    )

    prov.generate_response([], "sp")

    assert salud.en_cooldown("gemini")


def test_cuando_el_proveedor_revive_se_lo_deja_de_apartar(monkeypatch):
    monkeypatch.setattr(prov, "get_provider_config", _config("deepseek", ""))
    monkeypatch.setattr(prov, "_cached_call", lambda *a, **k: "hola de nuevo")
    salud.registrar_fallo("deepseek", "Insufficient Balance")

    prov.generate_response([], "sp")

    assert not salud.en_cooldown("deepseek")


def test_el_respaldo_que_falla_por_cuota_tambien_queda_apartado(monkeypatch):
    def _fake(proveedor, *a, **k):
        if proveedor == "ollama":
            raise RuntimeError("Insufficient Balance")
        return "respuesta de openai"

    monkeypatch.setattr(prov, "_uncached_call", _fake)

    prov._intentar_respaldos(
        "deepseek", Exception("x"), [], "sp", None, "m", None, "ollama openai",
    )

    assert salud.en_cooldown("ollama")
    assert not salud.en_cooldown("openai")
