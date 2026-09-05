"""
tests/test_task_routing.py
Pruebas del enrutado por tarea y del adaptador de OpenRouter (`ai/llm_provider.py`).

Lo que protege esta suite: **que el trabajo interno y repetitivo del agente pueda irse a un
modelo local o gratuito sin que la conversación pierda calidad**. Compactar historial,
destilar memoria o resumir una página son tareas mecánicas que no necesitan el modelo caro;
el razonamiento y la voz del asistente sí.

Y la propiedad que hace seguro todo lo anterior: **sin `task_providers` en config.json, no
cambia absolutamente nada**. El enrutado es opt-in.

Ningún test llama a un proveedor real ni a la red.
"""

import json

import pytest

import ai.llm_provider as prov
from ai import provider_health as salud


def _config_falsa(monkeypatch, tmp_path, contenido):
    """Hace que `llm_provider` lea un config.json temporal en vez del real.

    La ruta sale de `config_manager.CONFIG_FILE` — la misma constante que usa la pantalla
    de configuración para escribir —, así que apuntarla al temporal mueve las dos puntas.
    """
    import config_manager

    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(ruta))


def _proveedores(principal="deepseek", respaldo="", modelo="deepseek-chat", vision=""):
    return lambda: (principal, vision, respaldo, modelo)


# ── Lectura del mapeo ───────────────────────────────────────────────

def test_sin_mapeo_no_se_enruta_nada(monkeypatch, tmp_path):
    """La propiedad más importante: sin configurar nada, todo sigue igual que antes."""
    _config_falsa(monkeypatch, tmp_path, {"ai_provider": "deepseek"})

    assert prov.get_proveedor_de_tarea("ligera") == ("", "")


def test_la_tarea_general_ni_siquiera_mira_el_mapeo(monkeypatch, tmp_path):
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {"general": "ollama"}})

    assert prov.get_proveedor_de_tarea("general") == ("", "")
    assert prov.get_proveedor_de_tarea("") == ("", "")


def test_un_proveedor_suelto_usa_el_modelo_por_defecto_de_ese_proveedor(monkeypatch, tmp_path):
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {"ligera": "ollama"}})

    assert prov.get_proveedor_de_tarea("ligera") == ("ollama", "")


def test_se_puede_fijar_el_modelo_exacto(monkeypatch, tmp_path):
    """Imprescindible en OpenRouter: lo que hace gratis a una llamada es el `:free`."""
    _config_falsa(monkeypatch, tmp_path, {
        "task_providers": {
            "ligera": {"proveedor": "openrouter", "modelo": "qwen/qwen3-32b:free"},
        },
    })

    assert prov.get_proveedor_de_tarea("ligera") == ("openrouter", "qwen/qwen3-32b:free")


def test_las_claves_en_ingles_tambien_valen(monkeypatch, tmp_path):
    """El proyecto mezcla los dos idiomas; que no se caiga por escribir "provider"."""
    _config_falsa(monkeypatch, tmp_path, {
        "task_providers": {"ligera": {"provider": "ollama", "model": "qwen3:14b"}},
    })

    assert prov.get_proveedor_de_tarea("ligera") == ("ollama", "qwen3:14b")


def test_una_tarea_que_no_esta_en_el_mapeo_usa_el_proveedor_de_siempre(monkeypatch, tmp_path):
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {"ligera": "ollama"}})

    assert prov.get_proveedor_de_tarea("razonamiento") == ("", "")


def test_un_mapeo_con_forma_absurda_se_ignora_sin_lanzar(monkeypatch, tmp_path):
    """Enrutar mal una tarea interna no puede tumbar la conversación."""
    _config_falsa(monkeypatch, tmp_path, {"task_providers": ["esto", "no", "va"]})
    assert prov.get_proveedor_de_tarea("ligera") == ("", "")

    _config_falsa(monkeypatch, tmp_path, {"task_providers": {"ligera": 42}})
    assert prov.get_proveedor_de_tarea("ligera") == ("", "")


def test_un_config_ilegible_no_rompe_el_enrutado(monkeypatch, tmp_path):
    """Ni un config.json roto ni uno inexistente pueden tumbar una consulta al modelo."""
    import config_manager

    roto = tmp_path / "config.json"
    roto.write_text("{esto no es json", encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(roto))
    assert prov.get_proveedor_de_tarea("ligera") == ("", "")

    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "no-existe.json"))
    assert prov.get_proveedor_de_tarea("ligera") == ("", "")
    assert not (tmp_path / "no-existe.json").exists(), (
        "consultar el modelo de una tarea no debe crear ni reescribir config.json"
    )


# ── Efecto sobre el router ──────────────────────────────────────────

def test_una_tarea_ligera_va_al_proveedor_configurado(monkeypatch):
    llamados = []
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(prov, "destinos_de_tarea", lambda t: [("ollama", "")])
    monkeypatch.setattr(
        prov, "_cached_call", lambda p, *a, **k: (llamados.append(p), "resumen")[1],
    )

    prov.generate_response([], "sp", tarea="ligera")

    assert llamados == ["ollama"]


def test_al_enrutar_por_tarea_tambien_cambia_el_modelo(monkeypatch):
    recibido = {}
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(prov, "destinos_de_tarea", lambda t: [("ollama", "")])

    def _fake(proveedor, messages, system_prompt, image_path, model):
        recibido["modelo"] = model
        return "ok"

    monkeypatch.setattr(prov, "_cached_call", _fake)

    prov.generate_response([], "sp", tarea="ligera")

    assert recibido["modelo"] == prov._MODELO_POR_PROVEEDOR["ollama"]


def test_el_modelo_explicito_de_la_config_gana(monkeypatch):
    recibido = {}
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(
        prov, "destinos_de_tarea", lambda t: [("openrouter", "qwen/qwen3-32b:free")],
    )

    def _fake(proveedor, messages, system_prompt, image_path, model):
        recibido["modelo"] = model
        return "ok"

    monkeypatch.setattr(prov, "_cached_call", _fake)

    prov.generate_response([], "sp", tarea="ligera")

    assert recibido["modelo"] == "qwen/qwen3-32b:free"


def test_un_caller_que_no_pasa_tarea_sigue_funcionando_igual(monkeypatch):
    """Retrocompatibilidad: hay ~15 callers que no pasan `tarea` y no deben cambiar."""
    llamados = []
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(
        prov, "_cached_call", lambda p, *a, **k: (llamados.append(p), "hola")[1],
    )

    assert prov.generate_response([], "sp") == "hola"
    assert llamados == ["deepseek"]


def test_con_una_imagen_la_vision_le_gana_al_enrutado_por_tarea(monkeypatch, tmp_path):
    """Un modelo de texto local no sirve para una captura, por barato que sea."""
    imagen = tmp_path / "captura.jpg"
    imagen.write_bytes(b"jpeg falso")

    recibido = {}
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek", vision="gemini"))
    monkeypatch.setattr(prov, "destinos_de_tarea", lambda t: [("ollama", "")])

    def _fake(proveedor, messages, system_prompt, image_path, model):
        recibido["proveedor"] = proveedor
        recibido["modelo"] = model
        return "veo una ventana"

    monkeypatch.setattr(prov, "_cached_call", _fake)

    prov.generate_response([], "sp", image_path=str(imagen), tarea="ligera")

    assert recibido["proveedor"] == "gemini"
    # Y el modelo tiene que ser el de Gemini, no el que dejó el enrutado por tarea.
    assert recibido["modelo"] == prov._MODELO_POR_PROVEEDOR["gemini"]


def test_el_enrutado_por_tarea_respeta_el_cooldown(monkeypatch):
    """Si al modelo gratuito se le acabó la cuota, la tarea ligera cae al de siempre."""
    llamados = []
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek", respaldo="deepseek"))
    monkeypatch.setattr(prov, "destinos_de_tarea", lambda t: [("openrouter", "")])
    monkeypatch.setattr(
        prov, "_cached_call", lambda p, *a, **k: (llamados.append(p), "ok")[1],
    )
    salud.registrar_fallo("openrouter", "429 insufficient_quota")

    prov.generate_response([], "sp", tarea="ligera")

    assert llamados == ["deepseek"]


# ── OpenRouter ──────────────────────────────────────────────────────

def test_openrouter_esta_registrado_en_el_router():
    assert "openrouter" in prov._MODELO_POR_PROVEEDOR


def test_el_modelo_por_defecto_de_openrouter_es_gratuito():
    """Si alguien le quita el `:free` sin querer, esto empieza a costar plata de verdad."""
    assert prov._MODELO_POR_PROVEEDOR["openrouter"].endswith(":free")


def test_openrouter_recibe_las_herramientas(monkeypatch):
    assert "openrouter" in prov._PROVEEDORES_CON_TOOLS


def test_uncached_call_despacha_a_openrouter(monkeypatch):
    recibido = {}

    def _fake(messages, system_prompt, image_path, model_name, tools=None):
        recibido["llamado"] = True
        return "ok"

    monkeypatch.setattr(prov, "_ask_openrouter", _fake)

    assert prov._uncached_call("openrouter", [], "sp", None, "m") == "ok"
    assert recibido["llamado"]


def test_sin_api_key_openrouter_avisa_en_vez_de_reventar(monkeypatch, tmp_path):
    """Y ese texto es justo el que `provider_health` clasifica como 'credenciales'."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _config_falsa(monkeypatch, tmp_path, {"ai_provider": "deepseek"})

    resultado = prov._ask_openrouter([{"role": "user", "content": "hola"}], "sp", None, "")

    assert resultado.startswith("Error:")
    assert salud.clasificar_error(resultado) == salud.CATEGORIA_CREDENCIALES


def test_la_variable_de_entorno_sirve_si_el_config_no_tiene_la_clave(monkeypatch, tmp_path):
    """`cfg.get(clave, env)` habría pisado la variable de entorno con un valor vacío."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-de-prueba")
    _config_falsa(monkeypatch, tmp_path, {"openrouter_api_key": ""})

    capturado = {}

    class _ClienteFalso:
        def __init__(self, api_key, base_url):
            capturado["api_key"] = api_key
            capturado["base_url"] = base_url
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            capturado["modelo"] = kwargs["model"]
            raise RuntimeError("corte deliberado: ya se comprobó lo que importaba")

    monkeypatch.setattr("openai.OpenAI", _ClienteFalso)

    with pytest.raises(RuntimeError):
        prov._ask_openrouter([{"role": "user", "content": "hola"}], "sp", None, "")

    assert capturado["api_key"] == "sk-or-de-prueba"
    assert capturado["base_url"] == "https://openrouter.ai/api/v1"
    assert capturado["modelo"] == prov._MODELO_POR_PROVEEDOR["openrouter"]


# ── La lista de tool-calling, una sola vez ──────────────────────────

def test_la_cadena_de_respaldo_usa_la_misma_lista_de_tool_calling(monkeypatch):
    """Estaba escrita a mano en dos sitios: agregar un proveedor a uno y no al otro dejaba
    al respaldo sin herramientas justo cuando más falta hacen."""
    recibido = {}

    def _fake(proveedor, messages, system_prompt, image_path, model, tools=None):
        recibido["tools"] = tools
        return "ok"

    monkeypatch.setattr(prov, "_uncached_call", _fake)
    herramientas = [{"name": "web_search"}]

    prov._intentar_respaldos(
        "deepseek", Exception("x"), [], "sp", None, "m", herramientas, "openrouter",
    )

    assert recibido["tools"] == herramientas


# ── Varios modelos para la misma tarea ────────────────────────────────────────────────
#
# El caso que motiva todo esto: los catalogos gratuitos (OpenRouter) se quedan sin cuota
# todo el tiempo, y tener un solo modelo por tarea significa quedarse sin la tarea.

def test_una_tarea_puede_tener_varios_modelos(monkeypatch, tmp_path):
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {
        "codigo": {"proveedor": "openrouter",
                   "modelos": ["cohere/north-mini-code:free", "poolside/laguna-s-2.1:free"]},
    }})
    assert prov.destinos_de_tarea("codigo") == [
        ("openrouter", "cohere/north-mini-code:free"),
        ("openrouter", "poolside/laguna-s-2.1:free"),
    ]


def test_una_tarea_puede_mezclar_proveedores(monkeypatch, tmp_path):
    """Primero el gratuito; si se quedo sin cuota, el de pago. Es la forma de gastar solo
    cuando de verdad hace falta."""
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {
        "razonamiento": [
            {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
            {"proveedor": "deepseek", "modelo": "deepseek-chat"},
        ],
    }})
    assert prov.destinos_de_tarea("razonamiento") == [
        ("openrouter", "z-ai/glm-5.2:free"),
        ("deepseek", "deepseek-chat"),
    ]


def test_las_formas_de_siempre_siguen_dando_un_destino(monkeypatch, tmp_path):
    """Nadie tiene que reescribir su config: las dos formas viejas siguen valiendo."""
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {
        "ligera": "ollama",
        "resumen": {"proveedor": "openrouter", "modelo": "google/gemma-4-31b-it:free"},
    }})
    assert prov.destinos_de_tarea("ligera") == [("ollama", "")]
    assert prov.destinos_de_tarea("resumen") == [("openrouter", "google/gemma-4-31b-it:free")]


def test_un_destino_repetido_no_se_prueba_dos_veces(monkeypatch, tmp_path):
    """Repetirlo solo gasta su timeout dos veces cuando esta caido."""
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {
        "codigo": {"proveedor": "openrouter", "modelos": ["a:free", "a:free", "b:free"]},
    }})
    assert prov.destinos_de_tarea("codigo") == [("openrouter", "a:free"), ("openrouter", "b:free")]


def test_una_opcion_sin_proveedor_se_ignora_sin_arrastrar_a_las_demas(monkeypatch, tmp_path):
    _config_falsa(monkeypatch, tmp_path, {"task_providers": {
        "codigo": [{"modelo": "sin-proveedor:free"}, {"proveedor": "openrouter", "modelo": "b:free"}],
    }})
    assert prov.destinos_de_tarea("codigo") == [("openrouter", "b:free")]


def test_si_el_primer_modelo_se_queda_sin_cuota_se_usa_el_siguiente(monkeypatch):
    """El corazon de la rotacion: dentro de la MISMA llamada, sin irse al proveedor de pago
    ni abandonar la tarea."""
    llamados = []

    def _fake(proveedor, messages, system_prompt, image_path, model, tools=None):
        llamados.append(model)
        if model == "a:free":
            raise RuntimeError("429 rate limit exceeded")
        return "respondio el segundo"

    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(prov, "destinos_de_tarea",
                        lambda t: [("openrouter", "a:free"), ("openrouter", "b:free")])
    monkeypatch.setattr(prov, "_cached_call", _fake)

    resultado = prov.generate_response([], "sp", tarea="codigo")

    assert resultado == "respondio el segundo"
    assert llamados == ["a:free", "b:free"]


def test_un_429_de_un_gratuito_no_aparta_a_los_demas_del_catalogo(monkeypatch):
    """Lo que hacia inutil tener varios: el cooldown era por proveedor, asi que un 429 de
    un modelo dejaba fuera a los otros veinte de OpenRouter que seguian funcionando."""
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(prov, "destinos_de_tarea",
                        lambda t: [("openrouter", "a:free"), ("openrouter", "b:free")])
    monkeypatch.setattr(
        prov, "_cached_call",
        lambda p, m, s, i, model, **k: (_ for _ in ()).throw(RuntimeError("429 rate limit"))
        if model == "a:free" else "ok",
    )

    prov.generate_response([], "sp", tarea="codigo")

    assert salud.en_cooldown("openrouter", "a:free")
    assert not salud.en_cooldown("openrouter", "b:free")
    assert not salud.en_cooldown("openrouter"), "el proveedor entero no puede quedar apartado"


def test_el_modelo_apartado_se_prueba_ultimo(monkeypatch):
    """Empezar por uno que acaba de contestar 429 cuesta su timeout en cada mensaje."""
    salud.registrar_fallo("openrouter", "429 rate limit", "a:free")
    llamados = []

    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(prov, "destinos_de_tarea",
                        lambda t: [("openrouter", "a:free"), ("openrouter", "b:free")])
    monkeypatch.setattr(
        prov, "_cached_call",
        lambda p, m, s, i, model, **k: (llamados.append(model), "ok")[1],
    )

    prov.generate_response([], "sp", tarea="codigo")

    assert llamados == ["b:free"], "el apartado no se prueba primero"


def test_una_cuota_agotada_en_deepseek_si_aparta_al_proveedor(monkeypatch):
    """Al reves que OpenRouter: en DeepSeek la cuota es de la CUENTA. Apartar solo un
    modelo haria que el siguiente mensaje choque contra la misma pared."""
    monkeypatch.setattr(prov, "get_provider_config", _proveedores("deepseek"))
    monkeypatch.setattr(prov, "destinos_de_tarea", lambda t: [])
    monkeypatch.setattr(
        prov, "_cached_call",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Insufficient Balance")),
    )

    prov.generate_response([], "sp")

    assert salud.en_cooldown("deepseek")


def test_si_todos_los_modelos_de_la_tarea_fallan_se_cae_al_respaldo(monkeypatch):
    """La rotacion no reemplaza a la cadena de respaldo: la precede."""
    llamados = []

    def _fake(proveedor, messages, system_prompt, image_path, model, tools=None):
        llamados.append((proveedor, model))
        if proveedor == "openrouter":
            raise RuntimeError("429 rate limit")
        return "respondio el respaldo"

    monkeypatch.setattr(prov, "get_provider_config",
                        lambda: ("deepseek", "", "ollama", "deepseek-chat"))
    monkeypatch.setattr(prov, "destinos_de_tarea",
                        lambda t: [("openrouter", "a:free"), ("openrouter", "b:free")])
    monkeypatch.setattr(prov, "_cached_call", _fake)
    monkeypatch.setattr(prov, "_uncached_call", _fake)

    resultado = prov.generate_response([], "sp", tarea="codigo")

    assert resultado == "respondio el respaldo"
    assert [p for p, _ in llamados] == ["openrouter", "openrouter", "ollama"]
