"""
tests/test_dialog_resolution.py

REQ-021 — el diálogo pendiente dentro de `core/resolution.py::resolve()`.

Actualizado al invertir el orden de resolución: el modelo lee primero y `RESOLVERS` quedó
en `[pending_dialog, claude]`. La primera sección era la red de regresión del orden VIEJO
—fijaba el `matched_by` de los 7 resolvers que iban delante del modelo—; ahora fija dos
cosas distintas: que delante del modelo no quede nada más que el diálogo pendiente, y que
ninguno de los 7 retirados se haya perdido, porque todos siguen alcanzables como
herramienta.

El resto de las pruebas no cambió de intención, solo de etiqueta: donde antes un desvío se
resolvía con `matched_by == "intent:CALCULATE"`, ahora se resuelve con `"claude"`. Lo que
verifican —que el diálogo no se coma la frase, que sobreviva al desvío, que el gate reciba
el canal real— es exactamente lo mismo.

Sin red, sin micrófono, sin `sleep` real (.claude/rules/testing.md). Ningún test de este
archivo llega a un proveedor LLM real: el bucle de razonamiento se sustituye por un modelo
falso que decide como decidiría el real (ver `sin_llm`), y `ask_question()` se mockea
siempre que el camino pueda invocarlo.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.dialog_state import DialogStore, dialog_store
from tests import modelo_falso
from core.resolution import resolve
from core.security_manager import ChannelType, security_manager


class FakeClock:
    def __init__(self, start: float = 5000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True, scope="module")
def _tools_registradas():
    """El catálogo de herramientas que en producción arma `main.py` al arrancar.

    Desde la inversión, una orden se ejecuta porque el modelo llama a `dispatcher`. Si ese
    tool no está registrado, la orden muere con "tool no registrado" — y que lo estuviera
    dependía de qué otro test hubiera corrido antes en la sesión.
    """
    modelo_falso.registrar_tools()


class _Espia(list):
    """Las llamadas a `execute_tool`, y aparte las tareas REALMENTE creadas.

    Hacen falta las dos listas desde que el modelo llama `task_create` tambien cuando
    faltan datos: esa llamada existe —y se cuenta— pero no crea nada, responde la pregunta.
    Confundir "se llamo a la herramienta" con "se creo una tarea" haria que estas pruebas
    dieran por creada una tarea que nunca existio.
    """

    def __init__(self):
        super().__init__()
        self.creadas = []


@pytest.fixture
def spy_execute_tool(monkeypatch):
    """Espía sobre `execute_tool` — ningún test de este archivo toca `tasks.db`.

    ENVUELVE al real para `task_create` en vez de reemplazarlo. El chequeo de "pregunta lo
    que falta en vez de inventarlo" (CA-01) se mudó de `core/resolution.py` al invoke de la
    herramienta, porque desde la inversión quien la llama es el modelo y la guarda tiene que
    valer para él también. Sustituir `execute_tool` por un doble apagaba justo eso. Lo que
    sí se stubbea es la ÚNICA línea que tocaría la base: `create_from_natural()`.
    """
    from agents import tool_registry
    from tasks.task_manager import task_manager

    calls = _Espia()
    real = tool_registry.execute_tool

    def fake_execute_tool(name, params, channel, user_id):
        calls.append({"name": name, "params": params, "channel": channel, "user_id": user_id})
        # `task_create` y `dispatcher` pasan al REAL: son los dos caminos donde estas
        # pruebas verifican logica que vive del otro lado del gate —el chequeo de slots y
        # la denegacion de una accion YELLOW/RED—. Antes `dispatch()` no pasaba por
        # `execute_tool`, asi que el espia no lo tapaba; desde la inversion sí.
        if name in ("task_create", "dispatcher"):
            return real(name, params, channel, user_id)
        return f"resultado:{name}"

    def fake_create(text, user_id, channel="telegram"):
        calls.creadas.append({"text": text, "user_id": user_id, "channel": channel})
        return {"id": 1, "title": text, "remind_at": None}

    monkeypatch.setattr("agents.tool_registry.execute_tool", fake_execute_tool)
    monkeypatch.setattr(task_manager, "create_from_natural", fake_create)
    monkeypatch.setattr(task_manager, "format_task_created", lambda info: "resultado:task_create")
    return calls


@pytest.fixture
def preguntas(monkeypatch):
    """Repregunta determinista: los tests de flujo no dependen de la redacción del LLM.

    `ask_question()` se importa dentro de la función en `core/resolution.py`, así que
    parchear el atributo del módulo alcanza a los dos puntos que la llaman.
    """
    llamadas = []

    def fake_ask(action, slot, slots):
        llamadas.append({"action": action, "slot": slot, "slots": dict(slots)})
        return f"¿Pregunta por {slot}?"

    monkeypatch.setattr("core.dialog_questions.ask_question", fake_ask)
    return llamadas


@pytest.fixture(autouse=True)
def sin_llm(monkeypatch):
    """Ningun test llega a un proveedor real, y `resolve()` sigue probandose de punta a punta.

    Desde la inversion, TODO lo que no sea la respuesta a un dialogo pendiente termina en
    `reasoning_loop.run()`. Si aca solo se prohibiera la llamada real, cada test moriria en
    la prohibicion y no se probaria nada. Se sustituye entonces el bucle por un modelo falso
    que decide como decidiria el real: reconoce un recordatorio y llama `task_create`,
    reconoce una orden del sistema y llama `dispatcher`, y si no es ninguna de las dos,
    contesta el mismo. Las herramientas que ejecuta son las de verdad, con su gate.
    """
    modelo_falso.instalar(monkeypatch)


@pytest.fixture
def reloj_de_dialogo(monkeypatch):
    """Sustituye el singleton por un store con reloj inyectado (sin `sleep` real).

    Se sustituye en los DOS sitios que lo referencian. `core/resolution.py` lo importó al
    cargarse, y desde que el chequeo de slots vive en `agents/tool_registry.py`, la
    herramienta `task_create` lo busca por su cuenta: parchear solo uno dejaba al diálogo
    abriéndose en un almacén y leyéndose desde el otro.
    """
    clock = FakeClock()
    store = DialogStore(clock=clock)
    monkeypatch.setattr("core.resolution.dialog_store", store)
    monkeypatch.setattr("core.dialog_state.dialog_store", store)
    return clock


@pytest.fixture
def spy_gate(monkeypatch):
    """Espía sobre `require_confirmation()` SIN cambiar su veredicto."""
    llamadas = []
    original = security_manager.require_confirmation

    def wrapper(action_name, channel, details="", user_id="default"):
        llamadas.append({"action": action_name, "channel": channel, "user_id": user_id})
        return original(action_name, channel, details=details, user_id=user_id)

    monkeypatch.setattr(security_manager, "require_confirmation", wrapper)
    return llamadas


@pytest.fixture
def spy_dispatch(monkeypatch):
    """Espía sobre `dispatch()` que NO ejecuta la acción.

    Distinto de `sin_dispatch`: acá el camino normal SÍ debe pasar por `dispatch()`, solo
    que ejecutarlo de verdad no aporta nada y sí cuesta — el clasificador manda
    "mañana a las 9" a `FIND_LARGEST` con `path="~"`, que recorre el disco entero.
    """
    intents = []

    def fake_dispatch(intent, params):
        intents.append(getattr(intent, "value", str(intent)))
        return "respuesta del camino normal"

    monkeypatch.setattr("router.dispatcher.dispatch", fake_dispatch)
    return intents


@pytest.fixture
def sin_dispatch(monkeypatch):
    """`dispatch()` nunca debe invocarse — el otro punto de ejecución del sistema."""
    llamadas = []

    def fake_dispatch(intent, params):  # pragma: no cover - se asevera que no corre
        llamadas.append((intent, params))
        raise AssertionError(f"dispatch() no debía invocarse: {intent}")

    monkeypatch.setattr("router.dispatcher.dispatch", fake_dispatch)
    return llamadas


def _abrir_dialogo(preguntas, spy_execute_tool, texto="recuérdame algo",
                   channel=ChannelType.DESKTOP, user_id="u1"):
    """Deja un diálogo abierto y devuelve el resultado del turno que lo abrió."""
    result = resolve(texto, channel, user_id=user_id)
    # El diálogo lo abre ahora `task_create` desde dentro del bucle del modelo, así que
    # quien responde es "claude". Lo que importa —que quedó una pregunta en el aire— se
    # verifica con `expects_reply`, que es lo que de verdad consume la voz.
    assert result.matched_by == "claude", result.matched_by
    assert result.expects_reply is True, "el turno dejó una pregunta sin marcar"
    return result


# ─────────────────────────────────────────────
#  Red de regresión del orden INVERTIDO
#
#  Antes esta sección fijaba el `matched_by` de los 7 resolvers que iban delante del
#  modelo. Ese orden ya no existe: el modelo lee primero. Lo que hay que proteger ahora es
#  lo contrario — que nadie vuelva a meterse delante, y que ninguna de las 7 capacidades
#  retiradas se haya perdido por el camino.
# ─────────────────────────────────────────────

def test_delante_del_modelo_solo_queda_el_dialogo_pendiente():
    """La propiedad central de la inversión. Cada resolver que se agregue acá es una
    heurística que puede quedarse con un mensaje sin que el modelo lo vea nunca — que es
    exactamente como un JSON de colores terminó contestado con "0 x 12 = 0"."""
    from core.resolution import RESOLVERS

    assert [nombre for nombre, _ in RESOLVERS] == ["pending_dialog", "claude"]


def test_ninguna_capacidad_retirada_se_perdio():
    """Los 7 resolvers retirados siguen siendo alcanzables: ahora los elige el modelo.

    Sin esto, invertir el orden habría borrado en silencio las rutinas del usuario, sus
    comandos aprendidos y el planificador — nadie los llamaría nunca más.
    """
    from agents.skill_tools import register_dispatcher_tool, register_skill_tools
    from agents.tool_registry import list_tool_names
    from agents.user_defined_tools import register_user_defined_tools
    from skills.skill_manager import skill_manager

    register_dispatcher_tool()
    register_skill_tools(skill_manager)
    register_user_defined_tools()
    tools = set(list_tool_names())

    equivalencias = {
        "routine": ("routine_run", "routine_list"),
        "autopilot": ("autopilot_run",),
        "learned": ("learned_command_run", "learned_command_list"),
        "standing_intent": ("intent_create", "intent_list", "intent_cancel"),
        "task_tool": ("task_create", "task_list", "task_complete"),
        "intent": ("dispatcher",),
    }
    from core.resolution import RESOLVERS_RETIRADOS

    retirados = {nombre for nombre, _ in RESOLVERS_RETIRADOS}
    # `capability` es el único sin tool fijo: solo se registra si hay capacidades
    # declaradas en system_capabilities.json, que es un archivo opcional.
    assert retirados == set(equivalencias) | {"capability"}

    for resolver, esperadas in equivalencias.items():
        faltan = [t for t in esperadas if t not in tools]
        assert not faltan, f"'{resolver}' se retiró y sus tools no existen: {faltan}"


def test_una_orden_del_sistema_sigue_ejecutandose_via_el_modelo(spy_gate):
    """La contracara del coste asumido: la orden ya no se resuelve en local, pero se
    ejecuta igual — el modelo llama `dispatcher` y el gate se evalúa como siempre."""
    result = resolve("sube el volumen", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "claude"
    assert any(c["action"] == "SYS_VOL_UP" for c in spy_gate), [c["action"] for c in spy_gate]


def test_un_pedido_de_analisis_llega_al_modelo_sin_ejecutar_nada(spy_gate):
    """El caso que motivó todo: un JSON de rangos de colores pidiendo mejorar la paleta.
    Antes lo contestaba la calculadora con "0 x 12 = 0"."""
    json_cosecha = (
        '[{"ini": 0, "fin": 12, "color": "#92D050", "label": "0 - 12 dias"},'
        '{"ini": 13, "fin": 16, "color": "#ECEF12", "label": "13 - 16 dias"}] '
        "este json con diferentes colores quiero que me ayudes a mejorar esta "
        "visualizacion para que le asignes otra paleta de colores mejor, esto es para "
        "los ciclos de cosecha."
    )

    result = resolve(json_cosecha, ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "claude"
    assert "0 × 12" not in result.text and "0 x 12" not in result.text
    assert not spy_gate, f"no debía ejecutarse ninguna acción: {[c['action'] for c in spy_gate]}"

# ─────────────────────────────────────────────
#  CA-01, CA-02, CA-03 — no se inventa nada; se pregunta
# ─────────────────────────────────────────────

@pytest.mark.parametrize(
    "texto",
    ["recuérdame", "recuérdame algo", "recuérdame una cosa", "ponme un recordatorio"],
)
def test_ca01_frase_sin_contenido_no_crea_nada_y_repregunta(
    texto, preguntas, spy_execute_tool, sin_llm
):
    """CA-01: `execute_tool` NO se invoca (cero filas en tasks.db) y queda una pregunta
    en el aire."""
    result = resolve(texto, ChannelType.DESKTOP, user_id="u1")

    assert spy_execute_tool.creadas == [], f"{texto} creó una tarea"
    assert result.matched_by == "claude"
    assert result.expects_reply is True
    assert result.expects_reply is True
    assert result.text == "¿Pregunta por que?"
    assert dialog_store.get("u1", ChannelType.DESKTOP) is not None


def test_ca01_falta_solo_el_cuando(preguntas, spy_execute_tool, sin_llm):
    result = resolve("recuérdame llamar al contador", ChannelType.DESKTOP, user_id="u1")

    assert spy_execute_tool.creadas == []
    assert result.text == "¿Pregunta por cuando?"
    assert preguntas[0]["slot"] == "cuando"
    assert preguntas[0]["slots"] == {"que": "llamar al contador"}


def test_ca01_falta_solo_el_que(preguntas, spy_execute_tool, sin_llm):
    result = resolve("recuérdame mañana a las 9", ChannelType.DESKTOP, user_id="u1")

    assert spy_execute_tool.creadas == []
    assert result.text == "¿Pregunta por que?"
    assert preguntas[0]["slots"] == {"cuando": "mañana a las 9"}


def test_ca03_no_regresion_de_un_solo_tiro(preguntas, spy_execute_tool, sin_llm):
    """CA-03: la frase completa sigue creando la tarea al instante, sin repreguntar."""
    result = resolve(
        "recuérdame llamar al contador mañana a las 9", ChannelType.DESKTOP, user_id="u1"
    )

    assert [c["name"] for c in spy_execute_tool] == ["task_create"]
    assert spy_execute_tool[0]["params"]["text"] == (
        "recuérdame llamar al contador mañana a las 9"
    )
    assert result.matched_by == "claude"
    assert result.expects_reply is False
    assert preguntas == [], "una frase completa no puede consultar al LLM para repreguntar"
    assert dialog_store.get("u1", ChannelType.DESKTOP) is None


# ─────────────────────────────────────────────
#  CA-04, CA-05, CA-02 — el caso de referencia completo
# ─────────────────────────────────────────────

def test_ca04_ca05_caso_de_referencia_completo(preguntas, monkeypatch, sin_llm):
    """Los 3 turnos del caso de referencia, por `resolve()`, con el `matched_by` de cada
    uno. `execute_tool` se sustituye por el parseo REAL (`parse_natural_task` +
    `format_task_created`), sin tocar la base de datos: así CA-02 se verifica de punta a
    punta — título "Llamar al contador" y `remind_at` de mañana 09:00, nunca "Algo" ni
    `now()+1h`."""
    import datetime

    from tasks.task_manager import parse_natural_task, task_manager

    creadas = []

    # Se stubbea la ESCRITURA, no la herramienta. Sustituir `execute_tool` apagaba el
    # chequeo de slots, que ahora vive dentro de `task_create`: con el doble puesto, el
    # turno 1 creaba una tarea llamada "Algo" — justo la regresión que CA-02 vigila.
    def fake_create(text, user_id, channel="telegram"):
        info = parse_natural_task(text, user_id)
        creadas.append(info)
        return {**info, "id": 12}

    monkeypatch.setattr(task_manager, "create_from_natural", fake_create)

    t1 = resolve("recuérdame algo", ChannelType.DESKTOP, user_id="u1")
    assert t1.matched_by == "claude"
    assert t1.expects_reply is True
    assert creadas == []

    t2 = resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")
    assert t2.matched_by == "pending_dialog", "lo resolvió otro resolver"
    assert t2.expects_reply is True
    assert t2.text == "¿Pregunta por cuando?"
    assert creadas == []

    t3 = resolve("mañana a las 9", ChannelType.DESKTOP, user_id="u1")
    assert t3.matched_by == "pending_dialog"
    assert t3.expects_reply is False
    assert len(creadas) == 1

    manana_9 = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    assert creadas[0]["title"] == "Llamar al contador"
    assert creadas[0]["remind_at"] == manana_9.isoformat()

    # CA-05: la respuesta de cierre menciona el qué y el cuándo confirmados.
    assert "Llamar al contador" in t3.text
    assert "09:00" in t3.text
    assert t3.text.endswith("¿Algo más?")

    # El diálogo quedó cerrado: la frase siguiente se resuelve como comando nuevo.
    assert dialog_store.get("u1", ChannelType.DESKTOP) is None


def test_ca04_la_frase_suelta_no_la_resuelve_ningun_otro_resolver(
    preguntas, spy_execute_tool, sin_llm
):
    """CA-04: con el "qué" pendiente, la frase suelta no cae en routine, autopilot,
    learned, task_tool, capability, intent ni claude."""
    _abrir_dialogo(preguntas, spy_execute_tool)

    result = resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "pending_dialog"
    assert spy_execute_tool.creadas == []


# ─────────────────────────────────────────────
#  CA-06 — cancelación explícita
# ─────────────────────────────────────────────

@pytest.mark.parametrize("frase", ["olvídalo", "cancela", "déjalo", "nada"])
def test_ca06_cancelacion(frase, preguntas, spy_execute_tool, sin_llm):
    _abrir_dialogo(preguntas, spy_execute_tool)

    result = resolve(frase, ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "pending_dialog:cancel"
    assert result.expects_reply is False
    assert spy_execute_tool.creadas == [], "cancelar no puede crear una tarea"
    assert dialog_store.get("u1", ChannelType.DESKTOP) is None

    # Y la frase siguiente se resuelve por el orden normal de RESOLVERS.
    siguiente = resolve("suma 3 mas 4", ChannelType.DESKTOP, user_id="u1")
    assert siguiente.matched_by == "claude"
    assert "Por cierto" not in siguiente.text


def test_ca06_cancelar_exige_coincidencia_exacta(preguntas, spy_execute_tool, sin_llm):
    """Una frase que solo CONTIENE un verbo de cancelar es contenido del slot, no una
    cancelación: la coincidencia es exacta sobre la frase normalizada."""
    _abrir_dialogo(preguntas, spy_execute_tool)

    result = resolve("cancela la reunión del lunes", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "pending_dialog"
    assert dialog_store.get("u1", ChannelType.DESKTOP).slots["que"] == (
        "cancela la reunión del lunes"
    )


def test_frase_vacia_no_avanza_ni_cierra_el_dialogo(preguntas, spy_execute_tool, sin_llm):
    """Caso borde de la SPEC: el STT devuelve "". No cuenta como turno."""
    _abrir_dialogo(preguntas, spy_execute_tool)

    resolve("   ", ChannelType.DESKTOP, user_id="u1", claude_fn=lambda t: "eco")

    dialog = dialog_store.get("u1", ChannelType.DESKTOP)
    assert dialog is not None
    assert dialog.missing == ("que", "cuando")


# ─────────────────────────────────────────────
#  CA-07 — expiración silenciosa (reloj inyectado)
# ─────────────────────────────────────────────

def test_ca07_dialogo_expirado_no_crea_nada_ni_avisa(
    preguntas, spy_execute_tool, sin_llm, reloj_de_dialogo
):
    resolve("recuérdame algo", ChannelType.DESKTOP, user_id="u1")

    reloj_de_dialogo.advance(181)               # > TTL de ~3 min

    result = resolve("suma 3 mas 4", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "claude", "debía resolverse como mensaje nuevo"
    assert "Por cierto" not in result.text, "un diálogo expirado no puede repreguntar"
    assert spy_execute_tool.creadas == []


# ─────────────────────────────────────────────
#  CA-08, CA-11 — aislamiento y paridad entre canales
# ─────────────────────────────────────────────

def test_ca08_aislamiento_por_usuario_y_canal(preguntas, spy_execute_tool, sin_llm):
    resolve("recuérdame algo", ChannelType.TELEGRAM, user_id="A")

    # Usuario B en el mismo canal: su frase NO la absorbe el diálogo de A.
    b = resolve("suma 3 mas 4", ChannelType.TELEGRAM, user_id="B")
    assert b.matched_by == "claude"
    assert "Por cierto" not in b.text

    # El mismo usuario A en otro canal: tampoco.
    a_desktop = resolve("suma 3 mas 4", ChannelType.DESKTOP, user_id="A")
    assert a_desktop.matched_by == "claude"
    assert "Por cierto" not in a_desktop.text

    # Y el de A en TELEGRAM sigue vivo.
    assert dialog_store.get("A", ChannelType.TELEGRAM) is not None


@pytest.mark.parametrize(
    "channel,user_id",
    [
        (ChannelType.DESKTOP, "default"),
        (ChannelType.TELEGRAM, "123"),
        (ChannelType.DISCORD, "discord_456"),
    ],
)
def test_ca11_mismo_dialogo_en_los_3_canales(
    channel, user_id, preguntas, spy_execute_tool, sin_llm
):
    """CA-11: mismo mecanismo, sin una sola línea de lógica por canal."""
    t1 = resolve("recuérdame algo", channel, user_id=user_id)
    assert t1.matched_by == "claude"
    assert t1.expects_reply is True

    t2 = resolve("llamar al contador", channel, user_id=user_id)
    assert t2.matched_by == "pending_dialog"

    t3 = resolve("mañana a las 9", channel, user_id=user_id)
    assert t3.matched_by == "pending_dialog"
    # Dos llamadas a `task_create`, no una: la del turno 1 —el modelo la intenta y la
    # herramienta responde con la pregunta en vez de crear nada— y la del turno 3, ya con
    # los slots completos. La que crea la tarea es la ÚLTIMA.
    assert [c["name"] for c in spy_execute_tool] == ["task_create", "task_create"]
    creacion = spy_execute_tool[-1]
    assert creacion["params"]["text"] == "recuérdame llamar al contador mañana a las 9"
    assert creacion["channel"] == channel
    assert creacion["user_id"] == user_id


# ─────────────────────────────────────────────
#  CA-30, CA-31, CA-32 — desvío de tema
# ─────────────────────────────────────────────

def test_ca30_ca31_desvio_se_responde_y_el_dialogo_sigue_vivo(
    preguntas, spy_execute_tool, sin_llm
):
    """CA-30: la pregunta nueva se responde por el orden normal de RESOLVERS.
    CA-31: en esa misma respuesta reaparece la pregunta pendiente."""
    _abrir_dialogo(preguntas, spy_execute_tool)

    result = resolve("qué hora es", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by != "pending_dialog", "el desvío no lo resuelve el diálogo"
    assert result.expects_reply is True
    assert "Por cierto, ¿pregunta por que?" in result.text
    assert dialog_store.get("u1", ChannelType.DESKTOP) is not None, "el diálogo murió"
    assert spy_execute_tool.creadas == []


def test_ca31_la_repregunta_no_se_cuelga_dos_veces_ni_al_propio_dialogo(
    preguntas, spy_execute_tool, sin_llm
):
    """El turno que ABRE el diálogo y los que lo hacen avanzar ya son la pregunta: no
    pueden llevarla colgada otra vez."""
    abierto = _abrir_dialogo(preguntas, spy_execute_tool)
    assert "Por cierto" not in abierto.text

    avance = resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")
    assert avance.text.count("Por cierto") == 0


def test_ca32_el_desvio_no_reinicia_el_contador(
    preguntas, spy_execute_tool, sin_llm, reloj_de_dialogo
):
    """CA-32: el TTL corre desde el último AVANCE del diálogo, no desde el último turno.
    Si el desvío lo reiniciara, una charla larga haría aparecer la repregunta veinte
    minutos después — la sorpresa que "descartar en silencio" quiere evitar."""
    resolve("recuérdame algo", ChannelType.DESKTOP, user_id="u1")

    reloj_de_dialogo.advance(100)
    desvio = resolve("qué hora es", ChannelType.DESKTOP, user_id="u1")
    assert "Por cierto" in desvio.text, "el diálogo debía seguir vivo a los 100 s"

    reloj_de_dialogo.advance(81)                # 181 s desde el ÚLTIMO AVANCE real
    final = resolve("qué hora es", ChannelType.DESKTOP, user_id="u1")

    assert "Por cierto" not in final.text, "el desvío compró tiempo: CA-32 roto"


# ─────────────────────────────────────────────
#  Seguridad — CA-17, CA-18 (reescrito), CA-19, H2
# ─────────────────────────────────────────────

def test_ca18_a_fail_safe_con_el_slot_que_pendiente(
    preguntas, spy_execute_tool, sin_llm, sin_dispatch
):
    """CA-18 (a): con el "qué" pendiente, una frase no interrogativa con trigger YELLOW se
    guarda como texto del slot y NO ejecuta esa acción. `dispatch()` ni se invoca."""
    _abrir_dialogo(preguntas, spy_execute_tool)

    result = resolve("cierra chrome", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "pending_dialog"
    assert result.denied is False
    assert sin_dispatch == []
    dialog = dialog_store.get("u1", ChannelType.DESKTOP)
    assert dialog.slots["que"] == "cierra chrome"
    assert dialog.action == "task_create", "CA-19: la acción destino no puede cambiar"


def test_ca18_b_desvio_yellow_pasa_por_el_gate_con_el_canal_real(
    preguntas, spy_execute_tool, sin_llm, spy_gate, monkeypatch
):
    """CA-18 (b): con el "cuándo" pendiente, esa misma frase se desvía y
    `require_confirmation()` se evalúa con el CANAL REAL del caller, exactamente igual que
    si no hubiera ningún diálogo abierto. El diálogo no altera el nivel efectivo."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")

    resolve("recuérdame llamar al contador", ChannelType.DESKTOP, user_id="u1")
    assert dialog_store.get("u1", ChannelType.DESKTOP).missing == ("cuando",)
    spy_gate.clear()

    result = resolve("cierra chrome", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "claude", result.matched_by
    assert result.denied is True, "una acción YELLOW rechazada sigue denegada"
    assert spy_gate, "el gate no se evaluó"
    for llamada in spy_gate:
        assert security_manager.resolve_channel(llamada["channel"]) == ChannelType.DESKTOP
    assert dialog_store.get("u1", ChannelType.DESKTOP) is not None, "el diálogo sigue vivo"


def test_ca18_b_desvio_red_sigue_bloqueado_por_el_fail_closed(
    preguntas, spy_execute_tool, sin_llm, spy_gate, monkeypatch
):
    """Con un diálogo abierto, una acción RED sigue bloqueada por el fail-closed de
    REQ-005. El diálogo no abre ninguna puerta que no estuviera ya abierta."""
    from intent import classifier as classifier_module

    monkeypatch.setattr(
        classifier_module, "classify_command",
        lambda text: ("delete_database", {"raw_text": text}),
    )

    resolve("recuérdame llamar al contador", ChannelType.DESKTOP, user_id="u1")
    spy_gate.clear()

    result = resolve("borra la base de datos", ChannelType.DESKTOP, user_id="u1")

    assert result.denied is True
    assert result.matched_by == "claude", result.matched_by
    assert any(c["action"] == "delete_database" for c in spy_gate)
    for llamada in spy_gate:
        assert security_manager.resolve_channel(llamada["channel"]) == ChannelType.DESKTOP


def test_h2_un_resultado_denegado_no_lleva_la_repregunta_colgada(
    preguntas, spy_execute_tool, sin_llm, monkeypatch
):
    """H2 de la auditoría: mezclar "⛔ Acción no autorizada" con "Por cierto, ¿para
    cuándo?" degrada el aviso de seguridad. El diálogo NO se cancela: la repregunta
    reaparece en el turno siguiente."""
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")

    resolve("recuérdame llamar al contador", ChannelType.DESKTOP, user_id="u1")

    result = resolve("cierra chrome", ChannelType.DESKTOP, user_id="u1")

    assert result.denied is True
    assert "Por cierto" not in result.text, "la repregunta se colgó de una denegación"
    assert result.expects_reply is False
    assert dialog_store.get("u1", ChannelType.DESKTOP) is not None


def test_ca19_el_contenido_de_un_slot_nunca_cambia_la_accion_destino(
    preguntas, spy_execute_tool, sin_llm, sin_dispatch
):
    """CA-19: en v1 la única acción alcanzable por diálogo es `task_create` (GREEN)."""
    _abrir_dialogo(preguntas, spy_execute_tool)

    resolve("apaga el pc", ChannelType.DESKTOP, user_id="u1")
    resolve("mañana a las 9", ChannelType.DESKTOP, user_id="u1")

    # Dos: la del turno que preguntó (que no creó nada) y la del turno que completó.
    assert [c["name"] for c in spy_execute_tool] == ["task_create", "task_create"]
    assert sin_dispatch == []


def test_ca19_una_accion_no_cableada_no_se_ejecuta_y_la_frase_sigue_el_camino_normal(
    preguntas, spy_execute_tool, sin_llm, spy_dispatch
):
    """CA-19 — el guard de `_execute_completed_dialog()` (desviación #6 del dev-log).

    La otra mitad de CA-19: además de que el contenido de un slot no pueda CAMBIAR la
    acción destino, una acción destino que no sea `task_create` no llega a ejecutarse.
    En v1 `task_create` es la única cableada; el día que otro resolver empiece a abrir
    diálogos, uno a medio cablear se descarta en vez de improvisar una ejecución.

    Se abre el diálogo directamente en el store porque hoy ningún resolver puede producir
    este estado — que es justamente el motivo por el que el guard existe.
    """
    from tasks.task_slots import SLOT_WHAT, SLOT_WHEN

    dialog_store.open(
        "u1", ChannelType.DESKTOP, action="shutdown_pc", slots={},
        missing=(SLOT_WHAT, SLOT_WHEN), question="¿Pregunta por que?",
    )

    # El diálogo avanza con normalidad: el guard NO está en el camino de llenar slots.
    avance = resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")
    assert avance.matched_by == "pending_dialog"
    assert avance.expects_reply is True
    assert dialog_store.get("u1", ChannelType.DESKTOP).action == "shutdown_pc", (
        "CA-19: el slot no puede cambiar la acción destino, ni siquiera para arreglarla"
    )

    # Y al completarse es cuando el guard actúa.
    final = resolve(
        "mañana a las 9", ChannelType.DESKTOP, user_id="u1",
        claude_fn=lambda t: f"respuesta normal a: {t}",
    )

    assert spy_execute_tool.creadas == [], (
        "se ejecutó una acción que v1 no cablea: el guard fail-safe no corrió"
    )
    assert "shutdown_pc" not in spy_dispatch, (
        "la acción del diálogo se ejecutó por el otro punto de ejecución del sistema"
    )
    assert final.matched_by != "pending_dialog", (
        f"el diálogo no cableado devolvió un resultado propio: {final.matched_by}"
    )
    assert dialog_store.get("u1", ChannelType.DESKTOP) is None, (
        "el diálogo no cableado quedó vivo y volvería a intentarlo en el turno siguiente"
    )
    assert "Por cierto" not in final.text, "quedó una repregunta colgada de un diálogo muerto"


def test_ca19_el_mismo_dialogo_con_task_create_si_ejecuta(
    preguntas, spy_execute_tool, sin_llm
):
    """Contraste del guard: idéntico al test de arriba salvo la acción destino. Si el
    guard dejara pasar cualquier acción, los dos tests darían el mismo resultado."""
    from tasks.task_slots import SLOT_WHAT, SLOT_WHEN, TASK_CREATE_ACTION

    dialog_store.open(
        "u1", ChannelType.DESKTOP, action=TASK_CREATE_ACTION, slots={},
        missing=(SLOT_WHAT, SLOT_WHEN), question="¿Pregunta por que?",
    )

    resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")
    final = resolve("mañana a las 9", ChannelType.DESKTOP, user_id="u1")

    assert [c["name"] for c in spy_execute_tool] == [TASK_CREATE_ACTION]
    assert final.matched_by == "pending_dialog"
    assert dialog_store.get("u1", ChannelType.DESKTOP) is None


def test_ca17_el_canal_llega_al_gate_desde_el_caller_no_del_dialogo(
    preguntas, spy_execute_tool, sin_llm
):
    """CA-17: `dialog_store` guarda el canal solo como parte de la clave de partición;
    nunca lo transporta hacia el gate. El `channel` que recibe `execute_tool()` es el que
    pasó el caller."""
    resolve("recuérdame algo", ChannelType.TELEGRAM, user_id="tg1")
    resolve("llamar al contador", ChannelType.TELEGRAM, user_id="tg1")
    resolve("mañana a las 9", ChannelType.TELEGRAM, user_id="tg1")

    assert spy_execute_tool[0]["channel"] == ChannelType.TELEGRAM
    assert spy_execute_tool[0]["params"]["channel"] == "telegram"


# ─────────────────────────────────────────────
#  CA-20, CA-21 — motor híbrido: reglas detectan, LLM redacta
# ─────────────────────────────────────────────

def test_ca21_detectar_no_consume_llm_y_el_respaldo_mantiene_el_flujo(
    spy_execute_tool, monkeypatch
):
    """CA-21: con el LLM mockeado para fallar, el diálogo se abre igual y sale la
    repregunta de respaldo. Ninguna frase se manda al LLM para DECIDIR si falta un dato:
    la única llamada posible es la de redacción, y ocurre después de la decisión."""
    from core.dialog_questions import FALLBACK_QUESTIONS

    llamadas = []

    def llm_caido(messages, system_prompt, *a, **k):
        llamadas.append(messages)
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr("ai.llm_provider.generate_response", llm_caido)

    result = resolve("recuérdame algo", ChannelType.DESKTOP, user_id="u1")

    assert result.text == FALLBACK_QUESTIONS["que"]
    assert result.expects_reply is True
    assert spy_execute_tool.creadas == []
    assert len(llamadas) == 1, "solo la redacción puede llamar al LLM"

    # Y el flujo continúa igual pese al fallo del proveedor.
    siguiente = resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")
    assert siguiente.text == FALLBACK_QUESTIONS["cuando"]


def test_ca20_la_repregunta_del_llm_se_usa_cuando_sirve(spy_execute_tool, monkeypatch):
    monkeypatch.setattr(
        "ai.llm_provider.generate_response",
        lambda *a, **k: "¿Qué desea que le recuerde exactamente?",
    )

    result = resolve("recuérdame algo", ChannelType.DESKTOP, user_id="u1")

    assert result.text == "¿Qué desea que le recuerde exactamente?"


# ─────────────────────────────────────────────
#  CA-29 (b) — interrumpir no es cancelar
#
#  La mitad de CA-29 que introduce este REQ: el barge-in corta la LOCUCIÓN, nunca el
#  diálogo pendiente. Si cortar al agente descartara la pregunta en el aire, la frase con
#  la que el usuario lo cortó dejaría de leerse como su respuesta — que es exactamente el
#  problema que el REQ vino a resolver.
#
#  La mitad pre-existente (que `signal_barge_in()` corta la locución y que el bucle de
#  escucha la señala) está en `tests/test_mic_window.py`.
# ─────────────────────────────────────────────

def _mock_microphone():
    mock_source = MagicMock()
    mock_microphone = MagicMock()
    mock_microphone.__enter__.return_value = mock_source
    mock_microphone.__exit__.return_value = False
    return mock_microphone


def test_ca29_el_dialogo_pendiente_sobrevive_al_barge_in(
    preguntas, spy_execute_tool, sin_llm, monkeypatch
):
    """CA-29: señalar el barge-in no toca el estado del diálogo — ni los slots, ni lo que
    falta, ni el reloj del TTL."""
    import ui.tts_engine as tts

    monkeypatch.setattr(tts, "_barge_in", False)   # global de proceso: se restaura al salir

    _abrir_dialogo(preguntas, spy_execute_tool)
    antes = dialog_store.get("u1", ChannelType.DESKTOP)

    tts.signal_barge_in()                          # el usuario corta la locución

    assert tts._barge_in is True, "el barge-in ni siquiera llegó a señalarse"

    despues = dialog_store.get("u1", ChannelType.DESKTOP)
    assert despues is not None, "interrumpir al agente canceló el diálogo"
    assert despues.action == antes.action
    assert despues.slots == antes.slots
    assert despues.missing == antes.missing
    assert despues.question == antes.question
    assert despues.last_progress_at == antes.last_progress_at, (
        "CA-32: el barge-in movió el reloj del TTL"
    )

    # Y el hilo sigue donde estaba: la frase siguiente es la respuesta a la pregunta.
    avance = resolve("llamar al contador", ChannelType.DESKTOP, user_id="u1")
    assert avance.matched_by == "pending_dialog"
    assert avance.text == "¿Pregunta por cuando?"
    assert spy_execute_tool.creadas == []


def test_ca29_la_frase_que_interrumpe_la_locucion_avanza_el_dialogo(
    preguntas, spy_execute_tool, sin_llm, monkeypatch
):
    """CA-29 de punta a punta: agente hablando + diálogo abierto -> el usuario lo corta ->
    el bucle señala el barge-in y devuelve la frase -> esa frase hace avanzar el diálogo.

    Sin micrófono ni altavoces: `sr.Microphone`/`sr.Recognizer` mockeados y `is_speaking()`
    forzado a `True` (.claude/rules/testing.md).
    """
    import threading

    import config_manager
    import ui.tts_engine as tts
    import voice.wake_word as wake_word_module

    monkeypatch.setattr(config_manager, "get_agent_name", lambda: "O.R.I.O.N")
    monkeypatch.setattr(config_manager, "get_agent_pronunciation", lambda: "orion")

    _abrir_dialogo(preguntas, spy_execute_tool)

    stop_event = threading.Event()
    recognizer = MagicMock()
    recognizer.listen.return_value = MagicMock()

    def transcribir(audio, language=None):
        stop_event.set()                            # una sola vuelta del bucle
        return "orión llamar al contador"

    recognizer.recognize_google.side_effect = transcribir

    with patch.object(wake_word_module.sr, "Microphone", return_value=_mock_microphone()), \
         patch.object(wake_word_module.sr, "Recognizer", return_value=recognizer), \
         patch.object(wake_word_module, "speak"), \
         patch.object(tts, "is_speaking", return_value=True), \
         patch.object(tts, "signal_barge_in") as senal:
        frase = wake_word_module.listen_for_wake_word(stop_event=stop_event)

    assert senal.called, "el usuario habló encima del agente y no se cortó la locución"
    assert frase == "llamar al contador"

    assert dialog_store.get("u1", ChannelType.DESKTOP) is not None, (
        "el diálogo murió por la interrupción: la frase quedaría sin destino"
    )

    avance = resolve(frase, ChannelType.DESKTOP, user_id="u1")
    assert avance.matched_by == "pending_dialog", (
        "la frase que interrumpió al agente se resolvió como comando nuevo"
    )
    assert dialog_store.get("u1", ChannelType.DESKTOP).slots["que"] == "llamar al contador"
    assert spy_execute_tool.creadas == []

def test_crear_la_tarea_cierra_la_pregunta_que_quedaba_abierta(preguntas, spy_execute_tool):
    """El caso reportado: "registró la tarea y todo bien, pero al finalizar siempre me
    preguntaba que para cuándo, y ya le había indicado que hoy".

    Pasa cuando el modelo llama a `task_create` dos veces: la primera con la frase
    incompleta —que abre el diálogo y devuelve la pregunta— y la segunda ya completa, que
    crea la tarea. Nada cerraba el diálogo de la primera, así que seguía vivo y
    `_append_pending_question()` lo colgaba de cada respuesta posterior: una pregunta por
    un dato que el usuario acababa de dar.
    """
    from agents.tool_registry import execute_tool
    from core import dialog_state

    _abrir_dialogo(preguntas, spy_execute_tool)
    assert dialog_state.dialog_store.get("u1", ChannelType.DESKTOP) is not None

    execute_tool(
        "task_create",
        {"text": "recuérdame llamar al contador mañana a las 9", "user_id": "u1",
         "channel": "desktop"},
        ChannelType.DESKTOP, "u1",
    )

    assert dialog_state.dialog_store.get("u1", ChannelType.DESKTOP) is None, (
        "la tarea quedó creada y la pregunta seguía en pie"
    )
