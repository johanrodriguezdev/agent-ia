"""
tests/test_flows.py
Punto 4 del plan: flujos durables (`core/flows.py`, `skills/flow_skill.py`).

Lo que protege esta suite: **que un flujo de varios pasos sobreviva a la realidad**. Que un
reinicio a mitad no lo haga empezar de cero, que cancelarlo mientras corre funcione de
verdad, que dos ejecuciones simultáneas no se pisen, y —lo que hace útil todo lo anterior—
que un paso que necesita permiso detenga el flujo en vez de colgarlo esperando un "sí" que
nadie va a escribir a las 4 de la mañana.

Y la garantía de fondo: un flujo no puede hacer nada que el usuario no pudiera pedir paso a
paso. Cada uno pasa por el mismo gate.
"""

import pytest

from core import flows
from core.flows import (
    CANCELADO, CORRIENDO, ESPERANDO, EXITOSO, FALLIDO, PENDIENTE,
    ConflictoDeRevision, FlowStore, Paso, ejecutar, reanudar_pendientes,
)
from core.security_manager import ChannelType, RiskLevel, security_manager


@pytest.fixture
def store(tmp_path):
    return FlowStore(db_path=str(tmp_path / "flows.db"))


@pytest.fixture
def ejecutadas(monkeypatch):
    """Reemplaza el ejecutor real de acciones y registra qué se pidió."""
    llamadas = []

    def _fake(name, params=None, channel=None, user_id="default"):
        llamadas.append(name)
        return f"hecho: {name}"

    import agents.action_registry as registro
    monkeypatch.setattr(registro, "execute_action", _fake)
    return llamadas


def _pasos(*acciones):
    return [Paso(accion=a) for a in acciones]


# ── Seguridad: el flujo no amplía permisos ──────────────────────────

def test_ejecutar_un_flujo_es_verde_porque_el_gate_esta_en_cada_paso():
    """Mismo criterio que la acción `dispatcher`: la autoridad es el gate por paso."""
    assert security_manager.classify_action("RUN_FLOW") == RiskLevel.GREEN


def test_crear_un_flujo_es_amarillo():
    """Deja escrito algo que va a correr después, quizá sin nadie mirando."""
    assert security_manager.classify_action("CREATE_FLOW") == RiskLevel.YELLOW


# ── Almacén ─────────────────────────────────────────────────────────

def test_se_crea_un_flujo(store):
    flujo = store.crear("modo trabajo", _pasos("open_chrome", "open_notepad"))

    assert flujo is not None
    assert flujo.estado == PENDIENTE
    assert [p.accion for p in flujo.pasos] == ["open_chrome", "open_notepad"]
    assert flujo.revision == 0


def test_un_flujo_sin_nombre_o_sin_pasos_no_se_guarda(store):
    assert store.crear("", _pasos("open_chrome")) is None
    assert store.crear("vacio", []) is None
    assert store.crear("basura", [Paso(accion="   ")]) is None


def test_un_flujo_larguisimo_se_recorta(store):
    """Un flujo es una rutina, no un programa."""
    flujo = store.crear("enorme", _pasos(*["open_chrome"] * (flows.MAX_PASOS + 10)))

    assert len(flujo.pasos) == flows.MAX_PASOS


def test_se_busca_por_nombre_exacto_y_parcial(store):
    store.crear("modo trabajo", _pasos("open_chrome"))

    assert store.buscar_por_nombre("modo trabajo") is not None
    assert store.buscar_por_nombre("MODO TRABAJO") is not None
    assert store.buscar_por_nombre("trabajo") is not None
    assert store.buscar_por_nombre("inexistente") is None


def test_los_flujos_de_otro_usuario_no_se_ven(store):
    store.crear("mio", _pasos("open_chrome"), user_id="johan")

    assert store.listar("otro") == []
    assert len(store.listar("johan")) == 1


def test_un_flujo_sobrevive_a_reabrir_la_base(tmp_path):
    """Durable de verdad: otro proceso lo encuentra igual."""
    ruta = str(tmp_path / "flows.db")
    creado = FlowStore(db_path=ruta).crear("persistente", _pasos("open_chrome"))

    otro = FlowStore(db_path=ruta).obtener(creado.id)

    assert otro is not None and otro.nombre == "persistente"


# ── Contador de revisión ────────────────────────────────────────────

def test_guardar_sube_la_revision(store):
    flujo = store.crear("x", _pasos("open_chrome"))

    guardado = store.guardar(flujo)

    assert guardado.revision == 1


def test_una_escritura_vieja_se_rechaza(store):
    """Sin esto, el hilo del planificador y una ejecución manual se corrompen en silencio."""
    flujo = store.crear("x", _pasos("open_chrome"))
    copia_vieja = store.obtener(flujo.id)

    store.guardar(flujo)                      # alguien más ya guardó

    with pytest.raises(ConflictoDeRevision):
        store.guardar(copia_vieja)


def test_el_conflicto_no_pisa_lo_que_habia(store):
    flujo = store.crear("x", _pasos("open_chrome"))
    copia_vieja = store.obtener(flujo.id)

    flujo.motivo = "el bueno"
    store.guardar(flujo)
    copia_vieja.motivo = "el viejo"
    with pytest.raises(ConflictoDeRevision):
        store.guardar(copia_vieja)

    assert store.obtener(flujo.id).motivo == "el bueno"


# ── Ejecución ───────────────────────────────────────────────────────

def test_se_ejecutan_todos_los_pasos(store, ejecutadas):
    flujo = store.crear("x", _pasos("system_info", "system_info"))

    resultado = ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert resultado.estado == EXITOSO
    assert ejecutadas == ["system_info", "system_info"]
    assert all(p.estado == EXITOSO for p in resultado.pasos)


def test_el_avance_se_persiste_paso_a_paso(store, ejecutadas):
    """Si el proceso muere en el paso 3, la próxima vez arranca en el 3."""
    flujo = store.crear("x", _pasos("system_info", "system_info", "system_info"))

    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert store.obtener(flujo.id).paso_actual == 3


def test_un_flujo_cortado_retoma_donde_quedo(store, ejecutadas):
    flujo = store.crear("x", _pasos("system_info", "system_info", "system_info"))
    # Simula un corte: dos pasos hechos, el proceso murió antes del tercero.
    flujo.paso_actual = 2
    flujo.pasos[0].estado = flujo.pasos[1].estado = EXITOSO
    store.guardar(flujo)

    resultado = ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert resultado.estado == EXITOSO
    assert ejecutadas == ["system_info"]   # solo el que faltaba


def test_un_paso_que_revienta_detiene_el_flujo_sin_perder_lo_hecho(store, monkeypatch):
    def _fake(name, params=None, channel=None, user_id="default"):
        if name == "get_disk_info":
            raise RuntimeError("el disco no responde")
        return "ok"

    import agents.action_registry as registro
    monkeypatch.setattr(registro, "execute_action", _fake)
    flujo = store.crear("x", _pasos("system_info", "get_disk_info", "system_info"))

    resultado = ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert resultado.estado == FALLIDO
    assert resultado.pasos[0].estado == EXITOSO      # lo hecho no se pierde
    assert resultado.pasos[1].estado == FALLIDO
    assert "el disco no responde" in resultado.motivo


def test_un_flujo_ya_terminado_no_se_reejecuta(store, ejecutadas):
    flujo = store.crear("x", _pasos("system_info"))
    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)
    ejecutadas.clear()

    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert ejecutadas == []


def test_ejecutar_un_flujo_inexistente_no_revienta(store):
    assert ejecutar(99999, canal=ChannelType.DESKTOP, store=store) is None


# ── Cancelación ─────────────────────────────────────────────────────

def test_se_puede_cancelar_un_flujo(store):
    flujo = store.crear("x", _pasos("system_info"))

    assert store.cancelar(flujo.id) is True
    assert store.obtener(flujo.id).estado == CANCELADO


def test_cancelar_uno_ya_terminado_no_hace_nada(store, ejecutadas):
    flujo = store.crear("x", _pasos("system_info"))
    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert store.cancelar(flujo.id) is False


def test_cancelar_a_mitad_detiene_los_pasos_siguientes(store, monkeypatch):
    """Que «cancelá ese flujo» funcione de verdad y no solo cuando está quieto."""
    flujo = store.crear("x", _pasos("system_info", "system_info", "system_info"))
    hechos = []

    def _fake(name, params=None, channel=None, user_id="default"):
        hechos.append(name)
        if len(hechos) == 1:
            store.cancelar(flujo.id)      # alguien cancela mientras corre el paso 1
        return "ok"

    import agents.action_registry as registro
    monkeypatch.setattr(registro, "execute_action", _fake)

    resultado = ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert len(hechos) == 1               # no arrancó ningún paso más
    assert resultado.estado == CANCELADO


def test_un_flujo_cancelado_no_se_puede_ejecutar(store, ejecutadas):
    flujo = store.crear("x", _pasos("system_info"))
    store.cancelar(flujo.id)

    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert ejecutadas == []


# ── Espera por permiso: lo que hace útil la durabilidad ─────────────

def test_un_paso_sin_permiso_pone_el_flujo_en_espera(store, ejecutadas):
    """A las 4 de la mañana no hay a quién preguntarle: se detiene, no se cuelga."""
    flujo = store.crear("x", _pasos("system_info", "shutdown", "system_info"))

    # UNKNOWN no admite amarillo y no tiene adaptador de confirmación: es el canal con el
    # que llega un flujo disparado por el reloj.
    resultado = ejecutar(flujo.id, canal=ChannelType.UNKNOWN, store=store)

    assert resultado.estado == ESPERANDO
    assert ejecutadas == ["system_info"]        # el verde sí corrió
    assert "shutdown" in resultado.motivo
    assert resultado.paso_actual == 1           # queda parado justo ahí


def test_lo_que_espera_se_retoma_desde_un_canal_que_si_puede(store, monkeypatch):
    """La segunda mitad de la historia: el dueño lo retoma y ahí sí se le pregunta."""
    hechos = []

    def _fake(name, params=None, channel=None, user_id="default"):
        hechos.append(name)
        return "ok"

    import agents.action_registry as registro
    monkeypatch.setattr(registro, "execute_action", _fake)
    monkeypatch.setattr("builtins.input", lambda _: "sí")

    flujo = store.crear("x", _pasos("system_info", "shutdown"))
    ejecutar(flujo.id, canal=ChannelType.UNKNOWN, store=store)
    assert hechos == ["system_info"]

    resultado = ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert resultado.estado == EXITOSO
    assert hechos == ["system_info", "shutdown"]


def test_un_paso_sin_clasificar_tambien_detiene_el_flujo(store, ejecutadas):
    """Fail-closed: lo que no está clasificado no se ejecuta, ni dentro de un flujo."""
    flujo = store.crear("x", _pasos("accion_que_nadie_clasifico_jamas"))

    resultado = ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert resultado.estado == ESPERANDO
    assert ejecutadas == []


# ── Reanudación tras un reinicio ────────────────────────────────────

def test_un_flujo_que_quedo_corriendo_se_marca_como_pendiente_de_retomar(store):
    """Nadie deja 'corriendo' escrito a propósito: el proceso murió ejecutándolo."""
    flujo = store.crear("x", _pasos("system_info"))
    flujo.estado = CORRIENDO
    store.guardar(flujo)

    avisos = reanudar_pendientes(store=store)

    assert len(avisos) == 1
    assert store.obtener(flujo.id).estado == ESPERANDO
    assert "reinicio" in store.obtener(flujo.id).motivo


def test_reanudar_no_ejecuta_nada(store, ejecutadas):
    """Retomar solo al arrancar sería ejecutar acciones que nadie pidió en ese momento."""
    flujo = store.crear("x", _pasos("system_info"))
    flujo.estado = CORRIENDO
    store.guardar(flujo)

    reanudar_pendientes(store=store)

    assert ejecutadas == []


def test_los_terminados_no_aparecen_como_pendientes(store, ejecutadas):
    flujo = store.crear("x", _pasos("system_info"))
    ejecutar(flujo.id, canal=ChannelType.DESKTOP, store=store)

    assert reanudar_pendientes(store=store) == []


# ── La skill ────────────────────────────────────────────────────────

@pytest.fixture
def skill_con_store(monkeypatch, store):
    monkeypatch.setattr(flows, "flow_store", store)
    from skills.flow_skill import FlowSkill
    return FlowSkill()


def test_la_frase_se_convierte_en_pasos():
    from skills.flow_skill import FlowSkill

    pasos, no_entendidos = FlowSkill.interpretar_pasos(
        "abri chrome, despues el bloc de notas y despues una captura",
    )

    assert [p.accion for p in pasos] == ["open_chrome", "open_notepad", "take_screenshot"]
    assert no_entendidos == []


def test_una_espera_se_reconoce_con_su_numero():
    from skills.flow_skill import FlowSkill

    pasos, _ = FlowSkill.interpretar_pasos("espera 5 segundos")

    assert pasos[0].accion == "wait_seconds"
    assert pasos[0].params == {"seconds": 5}


def test_lo_que_no_se_entiende_no_se_adivina():
    """Un flujo con un paso adivinado es peor que uno que no se guardó."""
    from skills.flow_skill import FlowSkill

    pasos, no_entendidos = FlowSkill.interpretar_pasos("abri chrome, despues haceme un cafe")

    assert [p.accion for p in pasos] == ["open_chrome"]
    assert no_entendidos == ["haceme un cafe"]


def test_se_crea_un_flujo_hablando(skill_con_store):
    params = skill_con_store.extract_params(
        "CREATE_FLOW", "aprende el flujo modo trabajo: abri chrome, despues el bloc de notas",
    )

    assert params["name"] == "modo trabajo"
    salida = skill_con_store.execute("CREATE_FLOW", params)

    assert "modo trabajo" in salida
    assert "open_chrome" in salida and "open_notepad" in salida


def test_al_crear_se_avisa_lo_que_quedo_afuera(skill_con_store):
    salida = skill_con_store.execute("CREATE_FLOW", {
        "name": "raro", "cuerpo": "abri chrome, despues haceme un cafe",
    })

    assert "no lo entendí" in salida
    assert "haceme un cafe" in salida


def test_sin_ningun_paso_reconocible_no_se_guarda_nada(skill_con_store):
    salida = skill_con_store.execute("CREATE_FLOW", {"name": "x", "cuerpo": "haceme un cafe"})

    assert "No reconocí ningún paso" in salida
    assert skill_con_store.execute("LIST_FLOWS", {}).startswith("No tenés")


def test_se_listan_los_flujos(skill_con_store, store):
    store.crear("modo trabajo", _pasos("open_chrome"))

    salida = skill_con_store.execute("LIST_FLOWS", {})

    assert "modo trabajo" in salida


def test_pedir_un_flujo_que_no_existe_lista_los_que_si(skill_con_store, store):
    store.crear("modo trabajo", _pasos("open_chrome"))

    salida = skill_con_store.execute("RUN_FLOW", {"name": "inexistente"})

    assert "No encontré" in salida
    assert "modo trabajo" in salida


def test_se_cancela_hablando(skill_con_store, store):
    store.crear("modo trabajo", _pasos("open_chrome"))

    salida = skill_con_store.execute("CANCEL_FLOW", {"name": "modo trabajo"})

    assert "Cancelé" in salida
    assert store.buscar_por_nombre("modo trabajo").estado == CANCELADO


def test_el_nombre_se_extrae_de_la_frase():
    from skills.flow_skill import FlowSkill

    params = FlowSkill().extract_params("RUN_FLOW", "ejecuta el flujo modo trabajo")

    assert params["name"] == "modo trabajo"


def test_la_skill_esta_clasificada_y_no_rompe_el_arranque():
    """`agents/skill_tools.py` lanza al arrancar si un intent no tiene riesgo registrado."""
    from skills.flow_skill import FlowSkill

    for intent in FlowSkill().get_intents():
        assert security_manager.classify_action(intent) is not None, intent


# ── Horarios (motor proactivo) ──────────────────────────────────────

def test_un_trigger_diario_dispara_a_su_hora():
    """Regresión: `daily:HH:MM` nunca disparaba. `sched.split(":")[1].split(":")` daba una
    lista de un elemento y el desempaquetado lanzaba ValueError, que el except se tragaba.
    Con eso, el saludo diario de las 8:00 de main.py jamás se ejecutó."""
    from datetime import datetime

    from core.proactive_engine import ProactiveEngine, ProactiveTrigger

    class _AgenteFalso:
        name = "falso"

    motor = ProactiveEngine()
    trigger = ProactiveTrigger(_AgenteFalso(), "daily:08:00", "buenos días")

    justo_a_las_ocho = datetime(2026, 9, 3, 8, 0, 30)
    assert motor._should_fire(trigger, justo_a_las_ocho)


def test_un_trigger_diario_no_dispara_a_otra_hora():
    from datetime import datetime

    from core.proactive_engine import ProactiveEngine, ProactiveTrigger

    class _AgenteFalso:
        name = "falso"

    motor = ProactiveEngine()
    trigger = ProactiveTrigger(_AgenteFalso(), "daily:08:00", "buenos días")

    assert not motor._should_fire(trigger, datetime(2026, 9, 3, 15, 0, 0))


def test_un_horario_con_forma_invalida_no_revienta():
    from datetime import datetime

    from core.proactive_engine import ProactiveEngine, ProactiveTrigger

    class _AgenteFalso:
        name = "falso"

    motor = ProactiveEngine()
    for malo in ("daily:", "daily:99:99", "daily:ocho:cero"):
        trigger = ProactiveTrigger(_AgenteFalso(), malo, "x")
        assert not motor._should_fire(trigger, datetime(2026, 9, 3, 8, 0, 0)), malo


# ── Programar un flujo hablando ─────────────────────────────────────

def test_se_reconoce_un_horario_diario():
    from skills.flow_skill import extraer_horario

    horario, resto = extraer_horario(
        "aprende el flujo reporte, todos los dias a las 16:00: abri chrome",
    )

    assert horario == "daily:16:00"
    assert "todos los dias" not in resto


def test_se_reconoce_cada_hora():
    from skills.flow_skill import extraer_horario

    assert extraer_horario("el flujo x, cada hora: abri chrome")[0] == "hourly"


def test_sin_horario_no_se_inventa_ninguno():
    from skills.flow_skill import extraer_horario

    assert extraer_horario("el flujo x: abri chrome")[0] == ""


def test_una_hora_imposible_no_se_acepta():
    from skills.flow_skill import extraer_horario

    assert extraer_horario("todos los dias a las 99:99: abri chrome")[0] == ""


def test_el_horario_no_se_pega_al_nombre_del_flujo(skill_con_store):
    """Sin sacarlo primero, el nombre quedaría «reporte, todos los días a las 16:00»."""
    params = skill_con_store.extract_params(
        "CREATE_FLOW",
        "aprende el flujo reporte diario, todos los dias a las 16:00: abri chrome",
    )

    assert params["name"] == "reporte diario"
    assert params["horario"] == "daily:16:00"


def test_un_flujo_programado_guarda_su_horario(skill_con_store, store):
    salida = skill_con_store.execute("CREATE_FLOW", {
        "name": "reporte", "cuerpo": "abri chrome", "horario": "daily:16:00",
    })

    assert "daily:16:00" in salida
    assert store.buscar_por_nombre("reporte").horario == "daily:16:00"
