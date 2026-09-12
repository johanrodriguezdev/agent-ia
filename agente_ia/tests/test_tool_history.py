"""
tests/test_tool_history.py
REQ-027 — formato neutral del historial de herramientas (`core/tool_history.py`).

Las expectativas de texto están escritas A MANO, copiadas del comportamiento anterior a
REQ-027 (`reasoning_loop._build_prompt()`/`_append_history_lines()`), y no comparadas
contra el código nuevo: comparar el módulo contra sí mismo no probaría la byte-identidad
que exige CA-07/CA-08.
"""
import json

import pytest

from core import tool_history as th


# ─────────────────────────────────────────────
#  Ayudas
# ─────────────────────────────────────────────

def _historial_de_una_vuelta(params=None, salida="resultado A"):
    """Un par assistant/user como el que arma el bucle tras ejecutar una herramienta."""
    params = params if params is not None else {"query": "python"}
    llamada = th.bloque_llamada("tc_1_0", "web_search", params)
    resultado = th.bloque_resultado("tc_1_0", "web_search", salida)
    return [th.mensaje_de_llamadas(None, [llamada]), th.mensaje_de_resultados([resultado])]


# ─────────────────────────────────────────────
#  CA-02 — el formato neutral no filtra vocabulario de ningún proveedor
# ─────────────────────────────────────────────

def test_bloques_no_llevan_ninguna_clave_nativa_de_proveedor():
    """CA-02: el bucle no puede hablar el dialecto de un proveedor concreto — si lo
    hiciera, un cambio de proveedor a mitad de turno (REQ-022) mandaría bloques que el
    proveedor nuevo no entiende."""
    mensajes = _historial_de_una_vuelta()
    mensajes[0] = th.mensaje_de_llamadas(
        "voy a buscar eso", [th.bloque_llamada("tc_1_0", "web_search", {"query": "x"})]
    )
    serializado = json.dumps(mensajes, ensure_ascii=False)

    for clave_nativa in ("tool_use", "tool_result", "tool_calls", "tool_call_id",
                         "input_schema", "function_call"):
        assert clave_nativa not in serializado, f"se filtró '{clave_nativa}' al formato neutral"


# ─────────────────────────────────────────────
#  CA-08 — sin historial, la lista pasa intacta
# ─────────────────────────────────────────────

def test_aplanar_sin_historial_devuelve_los_mismos_mensajes():
    """CA-08: identidad de objeto, no solo igualdad. Es lo que garantiza que un caller de
    hoy produzca exactamente la misma llamada al proveedor que antes de REQ-027."""
    messages = [{"role": "user", "content": "hola"}]
    assert th.aplanar(messages) is messages


def test_aplanar_sin_historial_no_toca_una_conversacion_multi_turno():
    messages = [
        {"role": "user", "content": "primera"},
        {"role": "assistant", "content": "respuesta"},
        {"role": "user", "content": "segunda"},
    ]
    assert th.aplanar(messages) is messages


# ─────────────────────────────────────────────
#  CA-07 — el aplanado reproduce el texto de antes de REQ-027
# ─────────────────────────────────────────────

_INSTRUCCION = (
    "Continúa resolviendo la tarea con esta información. Si ya puedes responder, "
    "hazlo directamente sin usar más herramientas."
)


def test_aplanar_reproduce_el_texto_sin_turnos_previos():
    """CA-07: caso 'sin prior_turns, con historial' de `_build_prompt()`."""
    params = {"query": "python", "channel": "desktop", "user_id": "default",
              "texto_original": "buscá python"}
    encabezado = ("Tarea original del usuario: buscá python\n"
                  "\n"
                  "Acciones ya ejecutadas en este intento:")
    messages = [{"role": "user", "content": encabezado}] + _historial_de_una_vuelta(params)

    plano = th.aplanar(messages)

    assert len(plano) == 1
    assert plano[0]["content"] == (
        f"{encabezado}\n"
        f"1. web_search({params}) -> resultado A\n"
        f"\n"
        f"{_INSTRUCCION}"
    )


def test_aplanar_reproduce_el_texto_con_turnos_previos():
    """CA-07: caso 'con prior_turns, con historial' de `_build_prompt()`."""
    encabezado = ("Turnos anteriores de esta conversación:\n"
                  "- Usuario: hola\n"
                  "- Asistente: buenas\n"
                  "\n"
                  "Tarea original del usuario: buscá python\n"
                  "\n"
                  "Acciones ya ejecutadas en este intento:")
    messages = [{"role": "user", "content": encabezado}] + _historial_de_una_vuelta()

    plano = th.aplanar(messages)

    assert len(plano) == 1
    assert plano[0]["content"].startswith("Turnos anteriores de esta conversación:")
    assert plano[0]["content"].endswith(_INSTRUCCION)
    assert "1. web_search({'query': 'python'}) -> resultado A" in plano[0]["content"]


def test_aplanar_numera_varias_herramientas_en_orden():
    """CA-07: la numeración de `_append_history_lines()` arranca en 1 y sigue el orden."""
    llamadas = [th.bloque_llamada(f"tc_1_{i}", nombre, {})
                for i, nombre in enumerate(("web_search", "web_read", "task_list"))]
    resultados = [th.bloque_resultado(f"tc_1_{i}", nombre, f"r{i}")
                  for i, nombre in enumerate(("web_search", "web_read", "task_list"))]
    messages = [
        {"role": "user", "content": "encabezado"},
        th.mensaje_de_llamadas(None, llamadas),
        th.mensaje_de_resultados(resultados),
    ]

    contenido = th.aplanar(messages)[0]["content"]

    assert "1. web_search({}) -> r0" in contenido
    assert "2. web_read({}) -> r1" in contenido
    assert "3. task_list({}) -> r2" in contenido


def test_aplanar_deja_todo_content_como_str():
    """CA-07: `gemini` y `ollama` reciben strings o revientan."""
    messages = [{"role": "user", "content": "encabezado"}] + _historial_de_una_vuelta()
    for mensaje in th.aplanar(messages):
        assert isinstance(mensaje["content"], str)


def test_aplanar_no_deja_dos_mensajes_user_seguidos():
    """CA-07: Gemini rechaza dos `user` consecutivos. El historial se FUNDE en el último
    mensaje de texto, no se agrega detrás como un mensaje nuevo."""
    messages = [{"role": "user", "content": "encabezado"}] + _historial_de_una_vuelta()

    roles = [m["role"] for m in th.aplanar(messages)]

    assert roles == ["user"]
    for anterior, siguiente in zip(roles, roles[1:]):
        assert not (anterior == "user" and siguiente == "user")


def test_aplanar_descarta_el_razonamiento_intermedio_del_assistant():
    """CA-07: el texto que el modelo escribió entre herramientas no viajaba antes de
    REQ-027; incluirlo rompería la byte-identidad."""
    llamada = th.bloque_llamada("tc_1_0", "web_search", {})
    messages = [
        {"role": "user", "content": "encabezado"},
        th.mensaje_de_llamadas("déjame pensar en voz alta", [llamada]),
        th.mensaje_de_resultados([th.bloque_resultado("tc_1_0", "web_search", "ok")]),
    ]

    contenido = th.aplanar(messages)[0]["content"]

    assert "déjame pensar en voz alta" not in contenido


# ─────────────────────────────────────────────
#  D-6 — nunca un resultado vacío
# ─────────────────────────────────────────────

@pytest.mark.parametrize("salida", ["", None, 0, []])
def test_bloque_resultado_normaliza_salida_vacia(salida):
    """D-6: Anthropic rechaza un bloque de contenido vacío, y `execute_tool()` puede
    devolver "" o None sin que eso sea un error."""
    bloque = th.bloque_resultado("tc_1_0", "task_list", salida)
    assert bloque["salida"] == th.SIN_SALIDA


def test_bloque_resultado_conserva_una_salida_real():
    assert th.bloque_resultado("tc_1_0", "task_list", "3 tareas")["salida"] == "3 tareas"


def test_bloque_resultado_convierte_a_str_lo_que_no_lo_es():
    assert th.bloque_resultado("tc_1_0", "x", 42)["salida"] == "42"


# ─────────────────────────────────────────────
#  D-7 — los argumentos que vuelven al modelo van sin lo que inyectó el caller
# ─────────────────────────────────────────────

def test_argumentos_para_el_modelo_quita_las_claves_inyectadas():
    """D-7: `texto_original` es el mensaje entero del usuario; con presupuesto 40 se
    repetiría más de cien veces en el prompt."""
    bloque = th.bloque_llamada("tc_1_0", "web_search", {
        "query": "python", "channel": "desktop", "user_id": "default",
        "texto_original": "buscá algo sobre python por favor",
    })

    assert th.argumentos_para_el_modelo(bloque) == {"query": "python"}


def test_el_bloque_conserva_los_argumentos_completos():
    """El dict completo se guarda igual: el aplanado de CA-07 lo necesita para imprimir el
    mismo `repr` que antes de REQ-027."""
    params = {"query": "python", "channel": "desktop", "user_id": "default"}
    bloque = th.bloque_llamada("tc_1_0", "web_search", params)
    assert bloque["argumentos"] == params


# ─────────────────────────────────────────────
#  Correlación e inspección
# ─────────────────────────────────────────────

def test_pares_de_correlaciona_por_id_y_no_por_orden():
    """Los resultados pueden volver en otro orden sin que se crucen los pares."""
    llamadas = [th.bloque_llamada("tc_1_0", "a", {}), th.bloque_llamada("tc_1_1", "b", {})]
    resultados = [th.bloque_resultado("tc_1_1", "b", "R-B"),
                  th.bloque_resultado("tc_1_0", "a", "R-A")]
    messages = [th.mensaje_de_llamadas(None, llamadas), th.mensaje_de_resultados(resultados)]

    pares = th.pares_de(messages)

    assert [(p["tool"], p["result"]) for p in pares] == [("a", "R-A"), ("b", "R-B")]


def test_pares_de_no_rompe_si_falta_un_resultado():
    """No debería pasar (`_ejecutar_vuelta()` garantiza el par, D-6), pero un historial
    armado a mano no puede tumbar el aplanado."""
    messages = [th.mensaje_de_llamadas(None, [th.bloque_llamada("tc_1_0", "a", {})])]
    assert th.pares_de(messages) == [{"tool": "a", "params": {}, "result": ""}]


def test_tiene_historial_de_herramientas():
    assert th.tiene_historial_de_herramientas(_historial_de_una_vuelta()) is True
    assert th.tiene_historial_de_herramientas([{"role": "user", "content": "hola"}]) is False
    assert th.tiene_historial_de_herramientas([]) is False
    assert th.tiene_historial_de_herramientas(None) is False


def test_es_estructurado_no_confunde_una_lista_de_bloques_de_imagen():
    """El formato de imagen de OpenAI también usa `content` como lista, pero sin `tipo`."""
    mensaje = {"role": "user", "content": [{"type": "text", "text": "hola"}]}
    assert th.es_estructurado(mensaje) is False


def test_con_texto_agregado_no_muta_el_mensaje_original():
    mensaje = th.mensaje_de_resultados([th.bloque_resultado("tc_1_0", "a", "ok")])
    copia = th.con_texto_agregado(mensaje, "ahora respondé")

    assert len(mensaje["content"]) == 1
    assert len(copia["content"]) == 2
    assert copia["content"][-1] == {"tipo": th.TIPO_TEXTO, "texto": "ahora respondé"}
    assert copia["role"] == "user"


def test_mensaje_de_llamadas_omite_el_bloque_de_texto_si_no_hubo():
    mensaje = th.mensaje_de_llamadas(None, [th.bloque_llamada("tc_1_0", "a", {})])
    assert len(mensaje["content"]) == 1
    assert mensaje["content"][0]["tipo"] == th.TIPO_LLAMADA
    assert mensaje["role"] == "assistant"
