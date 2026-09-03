"""
tests/test_flows_avanzado.py
Lo que se agregó a los flujos para cerrarlos: programación en caliente, condiciones,
vocabulario ampliado y la pantalla.

Lo que protege esta suite:

- Que un flujo programado empiece a dispararse **sin reiniciar la app**, y que cancelarlo
  lo saque del planificador de verdad.
- Que las condiciones se evalúen con un conjunto CERRADO de operadores: un flujo es un
  dato que puede venir de una frase dictada, y ejecutar código desde ahí sería una puerta
  abierta.
- Que la pantalla no sea una vía para saltarse nada: editar un flujo a medio correr se
  rechaza en Python, no solo escondiendo el botón.
"""

import pytest

from core import flows
from core.flows import (
    EXITOSO, PENDIENTE, Condicion, FlowStore, Paso, ejecutar, evaluar_condicion,
)
from core.security_manager import ChannelType


@pytest.fixture
def store(tmp_path):
    return FlowStore(db_path=str(tmp_path / "flows.db"))


@pytest.fixture
def ejecutadas(monkeypatch):
    llamadas = []

    def _fake(name, params=None, channel=None, user_id="default"):
        llamadas.append(name)
        return f"hecho: {name}"

    import agents.action_registry as registro
    monkeypatch.setattr(registro, "execute_action", _fake)
    return llamadas


@pytest.fixture
def motor_limpio():
    """El motor proactivo es un singleton de proceso: no dejar triggers colgados."""
    from core.proactive_engine import proactive_engine

    originales = proactive_engine.triggers_activos()
    yield proactive_engine
    proactive_engine._triggers = list(originales)


def _pasos(*acciones):
    return [Paso(accion=a) for a in acciones]


# ── Programación en caliente ────────────────────────────────────────

def test_un_flujo_programado_se_registra_sin_reiniciar(store, motor_limpio):
    from core.flows import nombre_de_agente, programar

    flujo = store.crear("reporte", _pasos("system_info"), horario="daily:16:00")

    assert programar(flujo) is True
    nombres = [t.agent.name for t in motor_limpio.triggers_activos()]
    assert nombre_de_agente(flujo.id) in nombres


def test_reprogramar_no_deja_el_trigger_viejo(store, motor_limpio):
    """Si no, un flujo con horario cambiado se dispararía dos veces."""
    from core.flows import nombre_de_agente, programar

    flujo = store.crear("reporte", _pasos("system_info"), horario="daily:16:00")
    programar(flujo)
    flujo.horario = "hourly"
    programar(flujo)

    coincidencias = [
        t for t in motor_limpio.triggers_activos()
        if t.agent.name == nombre_de_agente(flujo.id)
    ]
    assert len(coincidencias) == 1
    assert coincidencias[0].schedule == "hourly"


def test_un_flujo_sin_horario_no_se_programa(store, motor_limpio):
    from core.flows import programar

    assert programar(store.crear("suelto", _pasos("system_info"))) is False


def test_cancelar_da_de_baja_el_disparo_automatico(store, motor_limpio, monkeypatch):
    """Un flujo cancelado que sigue despertándose cada hora es lo que se quiso evitar."""
    from core.flows import nombre_de_agente, programar
    from skills.flow_skill import FlowSkill

    monkeypatch.setattr(flows, "flow_store", store)
    flujo = store.crear("reporte", _pasos("system_info"), horario="hourly")
    programar(flujo)

    FlowSkill().execute("CANCEL_FLOW", {"name": "reporte"})

    nombres = [t.agent.name for t in motor_limpio.triggers_activos()]
    assert nombre_de_agente(flujo.id) not in nombres


def test_el_motor_deja_iterar_una_copia(motor_limpio):
    """Modificar la lista mientras otro hilo la recorre era corrupción silenciosa."""
    class _Agente:
        name = "agente-de-prueba"

    for _ in range(20):
        motor_limpio.register_trigger(_Agente(), "hourly", "x")
    copia = motor_limpio.triggers_activos()

    motor_limpio.unregister_trigger("agente-de-prueba")

    assert len(copia) >= 20                       # la copia no se ve afectada
    assert all(t.agent.name != "agente-de-prueba"
               for t in motor_limpio.triggers_activos())


def test_programar_todos_solo_toma_los_que_tienen_horario(store, motor_limpio):
    from core.flows import programar_todos

    store.crear("con horario", _pasos("system_info"), horario="hourly")
    store.crear("sin horario", _pasos("system_info"))

    programados = programar_todos(store=store)

    assert len(programados) == 1
    assert "con horario" in programados[0]


# ── Condiciones ─────────────────────────────────────────────────────

def test_un_paso_cuya_condicion_no_se_cumple_se_omite(store, monkeypatch):
    hechos = []

    def _fake(name, params=None, channel=None, user_id="default"):
        hechos.append(name)
        return "todo en orden"

    import agents.action_registry as registro
    monkeypatch.setattr(registro, "execute_action", _fake)

    flujo = store.crear("condicional", [
        Paso(accion="system_info"),
        Paso(accion="get_disk_info", condicion=Condicion("contiene", "error")),
    ])

    resultado = ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert hechos == ["system_info"]
    assert resultado.pasos[1].estado == "omitido"
    assert resultado.estado == EXITOSO      # omitir no es fallar


def test_un_paso_cuya_condicion_se_cumple_si_corre(store, monkeypatch):
    hechos = []

    def _fake(name, params=None, channel=None, user_id="default"):
        hechos.append(name)
        return "hubo un error grave"

    import agents.action_registry as registro
    monkeypatch.setattr(registro, "execute_action", _fake)

    flujo = store.crear("condicional", [
        Paso(accion="system_info"),
        Paso(accion="take_screenshot", condicion=Condicion("contiene", "error")),
    ])

    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert hechos == ["system_info", "take_screenshot"]


def test_un_operador_inventado_se_descarta():
    """Conjunto cerrado: un flujo es un dato, nunca código."""
    assert Condicion.de_dict({"operador": "os.system"}) is None
    assert Condicion.de_dict({"operador": "contiene", "valor": "x"}) is not None
    assert Condicion.de_dict("no soy un dict") is None


def test_sin_condicion_el_paso_siempre_corre():
    assert evaluar_condicion(None, [], 0) is True


def test_una_condicion_puede_mirar_un_paso_concreto():
    pasos = [Paso(accion="a", resultado="hola mundo"), Paso(accion="b")]

    assert evaluar_condicion(Condicion("contiene", "mundo", "paso:1"), pasos, 1)
    assert not evaluar_condicion(Condicion("contiene", "chau", "paso:1"), pasos, 1)


def test_una_referencia_a_un_paso_inexistente_no_revienta():
    pasos = [Paso(accion="a", resultado="hola")]

    assert not evaluar_condicion(Condicion("contiene", "hola", "paso:99"), pasos, 0)
    assert not evaluar_condicion(Condicion("contiene", "x", "paso:abc"), pasos, 0)


def test_los_operadores_de_vacio():
    con_texto = [Paso(accion="a", resultado="algo"), Paso(accion="b")]
    sin_texto = [Paso(accion="a", resultado=""), Paso(accion="b")]

    assert evaluar_condicion(Condicion("no_vacio"), con_texto, 1)
    assert not evaluar_condicion(Condicion("no_vacio"), sin_texto, 1)
    assert evaluar_condicion(Condicion("vacio"), sin_texto, 1)


def test_no_contiene_es_cierto_cuando_el_texto_no_esta():
    pasos = [Paso(accion="a", resultado="todo bien"), Paso(accion="b")]

    assert evaluar_condicion(Condicion("no_contiene", "error"), pasos, 1)


def test_reiniciar_limpia_los_resultados_viejos(store, ejecutadas):
    """Sin limpiarlos, «si el anterior contiene X» decidiría con datos de la corrida previa."""
    from core.flows import reiniciar

    flujo = store.crear("x", _pasos("system_info"))
    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    reiniciado = reiniciar(store.obtener(flujo.id), store=store)

    assert reiniciado.estado == PENDIENTE
    assert reiniciado.paso_actual == 0
    assert all(p.resultado == "" for p in reiniciado.pasos)


# ── Condiciones dictadas ────────────────────────────────────────────

def test_se_entiende_una_condicion_hablada():
    from skills.flow_skill import FlowSkill

    pasos, no_entendidos = FlowSkill.interpretar_pasos(
        "abri chrome, despues si contiene error, toma una captura",
    )

    assert [p.accion for p in pasos] == ["open_chrome", "take_screenshot"]
    assert pasos[1].condicion.operador == "contiene"
    assert pasos[1].condicion.valor == "error"
    assert no_entendidos == []


def test_se_entiende_la_negacion():
    from skills.flow_skill import FlowSkill

    pasos, _ = FlowSkill.interpretar_pasos("si no contiene ok entonces toma una captura")

    assert pasos[0].condicion.operador == "no_contiene"


def test_se_entiende_si_no_hay_nada():
    from skills.flow_skill import FlowSkill

    pasos, _ = FlowSkill.interpretar_pasos("si no hay nada entonces abri la calculadora")

    assert pasos[0].condicion.operador == "vacio"
    assert pasos[0].accion == "open_calculator"


def test_la_coma_de_una_condicion_no_parte_el_paso():
    """«si contiene error, tomá una captura» es UN paso, no dos."""
    from skills.flow_skill import FlowSkill

    pasos, _ = FlowSkill.interpretar_pasos("si contiene error, toma una captura")

    assert len(pasos) == 1


# ── Vocabulario ampliado ────────────────────────────────────────────

def test_se_acepta_el_nombre_exacto_de_una_accion():
    from skills.flow_skill import FlowSkill

    assert FlowSkill.resolver_accion("open_spotify") == "open_spotify"


def test_se_resuelve_por_la_descripcion_cuando_es_inequivoca():
    """Lo que amplía el vocabulario sin adivinar."""
    from skills.flow_skill import FlowSkill

    assert FlowSkill.resolver_accion("presiona una tecla") == "press_key"


def test_una_frase_que_no_encaja_no_se_resuelve():
    from skills.flow_skill import FlowSkill

    assert FlowSkill.resolver_accion("zzz nada que ver zzz") is None
    assert FlowSkill.resolver_accion("") is None


# ── La pantalla ─────────────────────────────────────────────────────

def test_el_payload_trae_lo_que_la_pantalla_necesita(store, monkeypatch):
    from ui.webview.bridge import _build_flows_payload

    monkeypatch.setattr(flows, "flow_store", store)
    store.crear("reporte", [
        Paso(accion="system_info"),
        Paso(accion="take_screenshot", condicion=Condicion("contiene", "error")),
    ], horario="daily:16:00")

    payload = _build_flows_payload()

    assert payload[0]["nombre"] == "reporte"
    assert payload[0]["horario"] == "daily:16:00"
    assert payload[0]["editable"] is True
    assert payload[0]["terminado"] is False
    assert "contiene" in payload[0]["pasos"][1]["condicion"]


def test_no_se_puede_editar_un_flujo_a_medio_correr(store, monkeypatch):
    """Sacar un paso desalinearía `paso_actual` con la lista. Se rechaza en Python, no
    solo escondiendo el botón."""
    from ui.webview.bridge import Bridge

    monkeypatch.setattr(flows, "flow_store", store)
    flujo = store.crear("x", _pasos("system_info", "system_info"))
    flujo.paso_actual = 1
    flujo.estado = "esperando"
    store.guardar(flujo)

    with pytest.raises(ValueError, match="a medio ejecutar"):
        Bridge._remove_flow_step_flow(None, flujo.id, 0)


def test_quitar_un_paso_reinicia_el_flujo(store, monkeypatch):
    from ui.webview.bridge import Bridge

    monkeypatch.setattr(flows, "flow_store", store)
    flujo = store.crear("x", _pasos("system_info", "take_screenshot"))

    Bridge._remove_flow_step_flow(None, flujo.id, 0)

    quedo = store.obtener(flujo.id)
    assert [p.accion for p in quedo.pasos] == ["take_screenshot"]
    assert quedo.paso_actual == 0
    assert quedo.estado == PENDIENTE


def test_no_se_puede_dejar_un_flujo_sin_pasos(store, monkeypatch):
    from ui.webview.bridge import Bridge

    monkeypatch.setattr(flows, "flow_store", store)
    flujo = store.crear("x", _pasos("system_info"))

    with pytest.raises(ValueError, match="borralo entero"):
        Bridge._remove_flow_step_flow(None, flujo.id, 0)


def test_un_indice_fuera_de_rango_se_rechaza(store, monkeypatch):
    from ui.webview.bridge import Bridge

    monkeypatch.setattr(flows, "flow_store", store)
    flujo = store.crear("x", _pasos("system_info", "take_screenshot"))

    with pytest.raises(ValueError, match="ese paso no existe"):
        Bridge._remove_flow_step_flow(None, flujo.id, 99)


def test_ejecutar_de_nuevo_reinicia_uno_terminado(store, monkeypatch, ejecutadas):
    """`ejecutar()` no toca un flujo terminado: sin reiniciar, el botón no haría nada."""
    from ui.webview.bridge import Bridge

    monkeypatch.setattr(flows, "flow_store", store)
    flujo = store.crear("x", _pasos("system_info"))
    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)
    ejecutadas.clear()

    Bridge._run_flow_flow(None, flujo.id)

    assert ejecutadas == ["system_info"]
