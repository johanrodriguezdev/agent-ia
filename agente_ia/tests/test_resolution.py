"""
tests/test_resolution.py

REQ-006 — `core/resolution.py:resolve()`, punto único de resolución (CA-01, CA-02,
CA-03, CA-04, CA-06, CA-07).

Convenciones (.claude/rules/testing.md): sin red, sin mic/altavoces, `input()` siempre
mockeado cuando aplica.

Actualizado al invertir el orden de resolución (`RESOLVERS == [pending_dialog, claude]`).
Lo que verifican las pruebas de CA-03/CA-04/CA-06 —misma traza y mismo gate en los cuatro
canales— no cambió; lo que cambió es QUIÉN elige la herramienta: ya no un clasificador
delante del modelo, sino el modelo. Por eso el `matched_by` uniforme ahora es "claude" y no
"intent:<X>", y por eso el bucle se sustituye por `tests/modelo_falso.py` — sin él, estas
pruebas llamarían a un proveedor real, que es justo lo que las convenciones prohíben.
"""

import re
from pathlib import Path

import pytest

from agents.action_registry import ACTION_REGISTRY
from agents.tool_registry import list_tool_names
from core.resolution import resolve
from core.security_manager import ChannelType, security_manager
from intent.intentions import Intent
from tests import modelo_falso

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _modelo(monkeypatch):
    """El modelo lee primero: sin un doble, cada `resolve()` acá llamaría al proveedor."""
    modelo_falso.instalar(monkeypatch)


@pytest.fixture(autouse=True, scope="module")
def _tools_registradas():
    """El catálogo de herramientas que en producción arma `main.py` al arrancar."""
    modelo_falso.registrar_tools()


def test_resolve_es_el_unico_punto_de_entrada():
    """CA-01: `main.py` y `channels/gateway.py` no resuelven intent ni tocan
    `tasks/task_manager.py` por su cuenta — ambos llaman a `core.resolution.resolve()`."""
    main_src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    gateway_src = (REPO_ROOT / "channels" / "gateway.py").read_text(encoding="utf-8")

    assert "from core.resolution import resolve" in main_src
    assert "resolve(command, channel)" in main_src or re.search(r"resolve\(\s*command\s*,\s*channel", main_src)

    assert "from core.resolution import resolve" in gateway_src
    assert "resolve(" in gateway_src
    # `channels/gateway.py` ya no importa `tasks.task_manager` directo (H3): solo llega
    # a él a través de `agents/tool_registry.py::execute_tool()`.
    assert "tasks.task_manager" not in gateway_src
    assert "import task_manager" not in gateway_src


def test_gateway_sin_prematching():
    """CA-02: los métodos `_try_create_task`/`_try_list_tasks`/`_try_complete_task` de
    `channels/gateway.py` (pre-matching sin gate, H3) fueron eliminados — su función
    pasó al resolver `task_tool` dentro de `resolve()`."""
    from channels.gateway import GlassGateway

    for method_name in ("_try_create_task", "_try_list_tasks", "_try_complete_task"):
        assert not hasattr(GlassGateway, method_name), f"GlassGateway todavía tiene {method_name}"


def test_traza_identica_por_canal():
    """CA-03, categoría 'verde': mismo texto de entrada, mismo `matched_by`, para
    DESKTOP/TELEGRAM/VOICE — con una acción GREEN (CALCULATE) solo puede diferir
    `denied`, y acá tampoco difiere."""
    text = "suma 3 mas 4"

    results = {
        channel: resolve(text, channel)
        for channel in (ChannelType.DESKTOP, ChannelType.TELEGRAM, ChannelType.VOICE)
    }

    matched_by_values = {r.matched_by for r in results.values()}
    assert matched_by_values == {"claude"}, matched_by_values
    assert all(not r.denied for r in results.values())


def test_traza_identica_por_canal_categoria_amarilla(monkeypatch):
    """CA-03, categoría 'amarilla': texto SPEC-006 pide los TRES canales (DESKTOP,
    TELEGRAM, VOICE) — no confundir con CA-04, que por su propio texto solo exige
    DESKTOP vs. VOICE (ver `test_yellow_mismo_action_name_desktop_vs_voice`).

    Misma herramienta (`intent:CLOSE_APP`) sin importar el canal; solo el veredicto del
    gate puede diferir. Con `input()` mockeado a "no": DESKTOP sí pregunta (tiene
    adaptador registrado en conftest.py), TELEGRAM y VOICE ni siquiera preguntan (YELLOW
    no está en su `CHANNEL_ALLOWED_LEVELS`) — pero los tres terminan `denied=True` y con
    el mismo `matched_by`."""
    input_calls = []

    def fake_input(prompt=""):
        input_calls.append(prompt)
        return "no"

    monkeypatch.setattr("builtins.input", fake_input)

    text = "cierra chrome"
    results = {}
    for channel in (ChannelType.DESKTOP, ChannelType.TELEGRAM, ChannelType.VOICE):
        input_calls.clear()
        results[channel] = (resolve(text, channel), len(input_calls))

    matched_by_values = {r.matched_by for r, _ in results.values()}
    assert matched_by_values == {"claude"}, matched_by_values
    assert all(r.denied for r, _ in results.values()), results

    assert results[ChannelType.DESKTOP][1] == 1, "DESKTOP debe pedir confirmación"
    assert results[ChannelType.TELEGRAM][1] == 0, "TELEGRAM no debe pedir confirmación"
    assert results[ChannelType.VOICE][1] == 0, "VOICE no debe pedir confirmación"


def test_traza_identica_por_canal_categoria_desconocida():
    """CA-03, categoría 'desconocida': un texto que ningún resolver reconoce (mockeando
    `ai_system.predict` para forzar `Intent.UNKNOWN` de forma determinista, igual que
    `test_classifier.py::test_classify_command_unknown_falls_back`) cae al mismo último
    recurso (`claude`) en los tres canales, sin denegar nada — `claude` no tiene tool-
    calling ni superficie de riesgo (confirmado en la auditoría de `orion-security`,
    `security-audit-006.md`)."""
    from intent import classifier as classifier_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(classifier_module.ai_system, "predict", lambda text: "UNKNOWN")

        text = "texto totalmente sin clasificar xyz123"
        results = {
            channel: resolve(text, channel, claude_fn=lambda t: f"echo:{t}")
            for channel in (ChannelType.DESKTOP, ChannelType.TELEGRAM, ChannelType.VOICE)
        }

    matched_by_values = {r.matched_by for r in results.values()}
    assert matched_by_values == {"claude"}, matched_by_values
    assert all(not r.denied for r in results.values())
    assert all(r.text == f"echo:{text}" for r in results.values())


def test_traza_identica_por_canal_categoria_multi_paso(monkeypatch):
    """CA-03, categoría 'multi-paso': una petición que dispara un plan de más de un paso
    (rutina "modo trabajo" — `open_chrome` + `open_notepad`, ambos GREEN) selecciona
    exactamente la misma secuencia de acciones y parámetros sin importar el canal, porque
    ni `TaskPlanner.generate_plan()` ni el motor de rutinas reciben o usan `channel` para
    decidir QUÉ ejecutar (solo se usa después, por paso, para el gate).

    Se mockean las funciones reales de `agents/action_registry.py` (abren aplicaciones de
    verdad) para no lanzar procesos durante el test — `.claude/rules/testing.md` prohíbe
    `subprocess` sin mocking."""
    from agents.action_registry import ACTION_REGISTRY

    calls = []

    def fake_open_chrome():
        calls.append(("open_chrome", {}))
        return "Chrome abierto (mock)."

    def fake_open_notepad():
        calls.append(("open_notepad", {}))
        return "Notepad abierto (mock)."

    monkeypatch.setitem(ACTION_REGISTRY["open_chrome"], "fn", fake_open_chrome)
    monkeypatch.setitem(ACTION_REGISTRY["open_notepad"], "fn", fake_open_notepad)
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    text = "haz un modo trabajo"
    traces = {}
    for channel in (ChannelType.DESKTOP, ChannelType.TELEGRAM, ChannelType.VOICE):
        calls.clear()
        result = resolve(text, channel)
        traces[channel] = (result.matched_by, tuple(calls), result.denied)

    matched_by_values = {t[0] for t in traces.values()}
    assert len(matched_by_values) == 1, f"matched_by difiere entre canales: {traces}"

    expected_sequence = (("open_chrome", {}), ("open_notepad", {}))
    for channel, (_matched_by, call_sequence, _denied) in traces.items():
        assert call_sequence == expected_sequence, f"{channel}: {traces}"

    assert all(not t[2] for t in traces.values()), "ambos pasos son GREEN, nada debe denegarse"


def test_yellow_mismo_action_name_desktop_vs_voice(monkeypatch):
    """CA-04: `CLOSE_APP` (YELLOW) llega al mismo `require_confirmation("close_app", ...)`
    sin importar el canal. Por VOICE (sin adaptador registrado) se deniega sin siquiera
    pedir confirmación; por DESKTOP sí se pide confirmación (adaptador de conftest.py
    consulta `input()`)."""
    input_calls = []

    def fake_input(prompt=""):
        input_calls.append(prompt)
        return "no"

    monkeypatch.setattr("builtins.input", fake_input)

    voice_result = resolve("cierra chrome", ChannelType.VOICE)
    assert voice_result.denied is True
    assert input_calls == [], "por VOICE no debe pedirse confirmación (sin adaptador)"

    desktop_result = resolve("cierra chrome", ChannelType.DESKTOP)
    assert desktop_result.denied is True  # "no" -> no confirmado -> denegado igual
    assert len(input_calls) == 1, "por DESKTOP sí debe pedirse confirmación"


def test_solo_verde_ejecuta_por_voz():
    """CA-06: una acción YELLOW vía `ChannelType.VOICE` siempre queda `denied=True` —
    garantizado por `CHANNEL_ALLOWED_LEVELS[ChannelType.VOICE] == [GREEN]` (sin tocar)."""
    result = resolve("cierra chrome", ChannelType.VOICE)
    assert result.denied is True


def test_cobertura_total_de_tools_y_acciones():
    """CA-07: cada `ToolSpec` registrado en `agents/tool_registry.py`, cada acción de
    `agents/action_registry.py::ACTION_REGISTRY` y cada `Intent` tienen clasificación de
    riesgo — el fail-closed de REQ-005 sigue intacto, ningún tool/acción/intent queda sin
    clasificar."""
    for tool_name in list_tool_names():
        assert security_manager.classify_action(tool_name) is not None, (
            f"tool '{tool_name}' sin clasificación de riesgo"
        )

    for action_name in ACTION_REGISTRY:
        assert security_manager.classify_action(action_name) is not None, (
            f"acción '{action_name}' de action_registry sin clasificación de riesgo"
        )

    for intent in Intent:
        assert security_manager.classify_action(intent.value) is not None, (
            f"intent '{intent.value}' sin clasificación de riesgo"
        )


def test_try_claude_sin_claude_fn_cae_en_reasoning_loop(monkeypatch):
    """REQ-007 — Pregunta 1, Opción A (aprobada): sin `claude_fn` inyectado (el caso de
    `main.py`, único caller de producción confirmado por baseline-007.md), `_try_claude()`
    cae en `core.reasoning_loop.run()` en vez de `ai.claude_brain.ask_claude()` — y su
    resultado se propaga sin modificar en `ResolutionResult.text`."""
    from unittest.mock import patch

    from intent import classifier as classifier_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(classifier_module.ai_system, "predict", lambda text: "UNKNOWN")

        with patch("core.reasoning_loop.run", return_value="respuesta del loop") as mock_run:
            result = resolve("texto sin clasificar xyz789", ChannelType.DESKTOP, user_id="u1")

    # `estado` es el dict que el bucle rellena si corta por una acción denegada: desde la
    # inversión, la denegación llega por acá y no por el resolver que la ejecutaba, y
    # `resolve()` necesita saberlo para no colgarle recordatorios a un aviso de seguridad.
    mock_run.assert_called_once_with(
        "texto sin clasificar xyz789", ChannelType.DESKTOP, "u1", estado={},
    )
    assert result.matched_by == "claude"
    assert result.text == "respuesta del loop"


# ─────────────────────────────────────────────
#  REQ-026 — hilo del modo estratégico del composer hasta `reasoning_loop.run()`
# ─────────────────────────────────────────────

def test_resolve_con_modo_lo_threadea_hasta_reasoning_loop(monkeypatch):
    """`resolve(..., modo="codigo")` debe llegar como kwarg `modo` a
    `reasoning_loop.run()` — es el único hilo real que activa la priorización de tools/
    tarea del modo (`arquitectura-026.md`, "Flujo de datos: Envío de un mensaje")."""
    from unittest.mock import patch

    from intent import classifier as classifier_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(classifier_module.ai_system, "predict", lambda text: "UNKNOWN")

        with patch("core.reasoning_loop.run", return_value="respuesta del loop") as mock_run:
            result = resolve(
                "ejecuta un script xyz789", ChannelType.DESKTOP, user_id="u1", modo="codigo",
            )

    mock_run.assert_called_once_with(
        "ejecuta un script xyz789", ChannelType.DESKTOP, "u1", estado={}, modo="codigo",
    )
    assert result.text == "respuesta del loop"


def test_resolve_con_imagen_la_threadea_hasta_reasoning_loop(monkeypatch):
    """REQ-054: `resolve(..., image_path=...)` llega como kwarg a `reasoning_loop.run()`;
    sin imagen el kwarg no se manda (dobles con la firma vieja)."""
    from unittest.mock import patch

    from intent import classifier as classifier_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(classifier_module.ai_system, "predict", lambda text: "UNKNOWN")

        with patch("core.reasoning_loop.run", return_value="veo un error 404") as mock_run:
            result = resolve(
                "¿qué dice esta captura xyz789?", ChannelType.DESKTOP, user_id="u1",
                image_path=r"C:\\capturas\\error.png",
            )

    mock_run.assert_called_once_with(
        "¿qué dice esta captura xyz789?", ChannelType.DESKTOP, "u1", estado={},
        image_path=r"C:\\capturas\\error.png",
    )
    assert result.text == "veo un error 404"


def test_resolve_sin_modo_no_manda_el_kwarg_modo(monkeypatch):
    """Regresión explícita del hallazgo de `desarrollo-log-026.md`: sin `modo` (o
    `modo=None`), `_try_claude()` NO agrega el kwarg — preserva la firma exacta de antes
    de REQ-026 para los caminos que no lo conocen (dobles de test con la firma vieja,
    Telegram/Discord vía `claude_fn`)."""
    from unittest.mock import patch

    from intent import classifier as classifier_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(classifier_module.ai_system, "predict", lambda text: "UNKNOWN")

        with patch("core.reasoning_loop.run", return_value="ok") as mock_run:
            resolve("texto sin clasificar abc123", ChannelType.DESKTOP, user_id="u1")

    mock_run.assert_called_once_with(
        "texto sin clasificar abc123", ChannelType.DESKTOP, "u1", estado={},
    )


def test_try_claude_con_claude_fn_ignora_modo():
    """Telegram/Discord (`claude_fn` inyectado, vía `channels/gateway.py`) no tienen
    ningún concepto de modo — un `modo` que igual llegara no debe tocar ese camino."""
    from core.resolution import _try_claude

    result = _try_claude(
        "hola", ChannelType.TELEGRAM, "u1", claude_fn=lambda t: f"echo:{t}", modo="codigo",
    )

    assert result.text == "echo:hola"


# ─────────────────────────────────────────────
#  REQ-017 — "completar todas las tareas pendientes" en lote (CA-01 a CA-06 de SPEC-017)
# ─────────────────────────────────────────────

def test_bulk_complete_prioriza_sobre_list_trigger(monkeypatch):
    """CA-01: 'completa todas las tareas pendientes' (contiene el substring de
    _TASK_LIST_TRIGGERS 'tareas pendientes') resuelve vía task_complete_all, NO vía
    task_list — spy sobre execute_tool."""
    calls = []

    def fake_execute_tool(name, params, channel, user_id):
        calls.append(name)
        return f"resultado:{name}"

    monkeypatch.setattr("agents.tool_registry.execute_tool", fake_execute_tool)

    result = resolve("completa todas las tareas pendientes", ChannelType.DESKTOP, user_id="u1")

    assert calls == ["task_complete_all"], calls
    assert result.matched_by == "claude"


def test_bulk_complete_variantes_sin_palabra_tarea(monkeypatch):
    """CA-01: variantes sin la palabra 'tarea' explícita también disparan
    task_complete_all — cubre el gap que señaló orion-baseline."""
    calls = []

    def fake_execute_tool(name, params, channel, user_id):
        calls.append(name)
        return f"resultado:{name}"

    monkeypatch.setattr("agents.tool_registry.execute_tool", fake_execute_tool)

    for text in ("ya completé todas las pendientes", "marca todas como completadas"):
        calls.clear()
        resolve(text, ChannelType.DESKTOP, user_id="u1")
        assert calls == ["task_complete_all"], (text, calls)


def test_mensaje_bulk_lista_ids_y_titulos(monkeypatch):
    """CA-02: el texto de respuesta contiene cada '#id - título' de las tareas
    completadas, no un genérico 'listo'."""
    from tasks.task_manager import task_manager

    monkeypatch.setattr(task_manager, "list_tasks", lambda *a, **k: [{"id": 5, "title": "comprar pan"}])
    monkeypatch.setattr(task_manager, "complete_task", lambda *a, **k: True)

    result = resolve("completa todas mis tareas pendientes", ChannelType.DESKTOP, user_id="u1")

    assert "#5 - comprar pan" in result.text
    assert result.text.strip().lower() != "listo"


def test_un_pendiente_sin_id_sin_cambios(monkeypatch):
    """CA-03: con texto que YA matchea _is_task_complete_phrase() hoy (literal de
    _TASK_COMPLETE_TRIGGERS, sin 'todas' ni 'tareas pendientes') y 1 sola pendiente:
    resuelve vía task_complete (no task_complete_all), mismo mensaje que antes de
    REQ-017."""
    from tasks.task_manager import task_manager

    monkeypatch.setattr(task_manager, "list_tasks", lambda *a, **k: [{"id": 7, "title": "regar plantas"}])
    complete_calls = []
    monkeypatch.setattr(
        task_manager, "complete_task",
        lambda task_id, user_id: complete_calls.append((task_id, user_id)) or True,
    )

    result = resolve("ya completé la tarea", ChannelType.DESKTOP, user_id="u1")

    assert complete_calls == [(7, "u1")]
    assert "regar plantas" in result.text
    assert result.matched_by == "claude"


def test_cero_pendientes_sin_cambios(monkeypatch):
    """CA-04: texto que matchea _TASK_LIST_TRIGGERS (sin 'todas' ni ID) con 0 pendientes:
    mensaje sin cambios — sigue resolviendo vía task_list/get_task_summary, no vía el
    tool nuevo task_complete_all (reutiliza el hallazgo de orion-baseline sobre el
    mensaje real de get_task_summary)."""
    from tasks.task_manager import task_manager

    monkeypatch.setattr(
        task_manager, "get_task_summary",
        lambda user_id: "No tiene ninguna tarea registrada, Señor. Todo está en orden.",
    )
    complete_calls = []
    monkeypatch.setattr(
        task_manager, "complete_task", lambda *a, **k: complete_calls.append(1) or True,
    )

    result = resolve("mis tareas pendientes", ChannelType.DESKTOP, user_id="u1")

    assert complete_calls == []
    assert result.text == "No tiene ninguna tarea registrada, Señor. Todo está en orden."


def test_id_explicito_gana_sobre_todas(monkeypatch):
    """CA-05, CA-06: 'de todas mis tareas, la #3 ya la hice' y 'de todas mis tareas,
    completa la #3' (ejemplos literales de SPEC-017.md) resuelven task_complete con
    task_id=3, NO task_complete_all ni task_list — spy sobre execute_tool."""
    calls = []

    def fake_execute_tool(name, params, channel, user_id):
        calls.append((name, params.get("text")))
        return f"resultado:{name}"

    monkeypatch.setattr("agents.tool_registry.execute_tool", fake_execute_tool)

    for text in ("de todas mis tareas, la #3 ya la hice", "de todas mis tareas, completa la #3"):
        calls.clear()
        resolve(text, ChannelType.DESKTOP, user_id="u1")
        assert len(calls) == 1, (text, calls)
        name, sent_text = calls[0]
        assert name == "task_complete", (text, calls)
        assert sent_text == text


def test_mismo_texto_bulk_en_3_canales(monkeypatch):
    """CA-06: 'completa todas las tareas pendientes' vía resolve() con DESKTOP
    (user_id='default'), TELEGRAM (user_id='123') y DISCORD (user_id='discord_456'),
    cada uno con sus propias pendientes mockeadas — mismo matched_by, cada canal
    completa SOLO las suyas (partición por user_id, documentada como preexistente)."""
    from tasks.task_manager import task_manager

    pending_by_user = {
        "default": [{"id": 1, "title": "tarea desktop"}],
        "123": [{"id": 2, "title": "tarea telegram"}],
        "discord_456": [{"id": 3, "title": "tarea discord"}],
    }
    completed_calls = []

    monkeypatch.setattr(
        task_manager, "list_tasks",
        lambda user_id, status="pending", limit=20: pending_by_user.get(user_id, []),
    )
    monkeypatch.setattr(
        task_manager, "complete_task",
        lambda task_id, user_id: completed_calls.append((task_id, user_id)) or True,
    )

    text = "completa todas las tareas pendientes"
    results = {}
    for channel, user_id in (
        (ChannelType.DESKTOP, "default"),
        (ChannelType.TELEGRAM, "123"),
        (ChannelType.DISCORD, "discord_456"),
    ):
        completed_calls.clear()
        result = resolve(text, channel, user_id=user_id)
        results[channel] = (result, list(completed_calls))

    matched_by_values = {r.matched_by for r, _ in results.values()}
    assert matched_by_values == {"claude"}, matched_by_values

    assert results[ChannelType.DESKTOP][1] == [(1, "default")]
    assert results[ChannelType.TELEGRAM][1] == [(2, "123")]
    assert results[ChannelType.DISCORD][1] == [(3, "discord_456")]


def test_bulk_no_intercepta_create(monkeypatch):
    """Regresión: 'recuérdame completar todas mis tareas mañana' sigue resolviendo
    task_create (create mantiene prioridad, sin cambios)."""
    calls = []

    def fake_execute_tool(name, params, channel, user_id):
        calls.append(name)
        return f"resultado:{name}"

    monkeypatch.setattr("agents.tool_registry.execute_tool", fake_execute_tool)

    resolve("recuérdame completar todas mis tareas mañana", ChannelType.DESKTOP, user_id="u1")

    assert calls == ["task_create"], calls


def test_try_claude_con_claude_fn_no_toca_reasoning_loop(monkeypatch):
    """Con `claude_fn` inyectado (p.ej. `channels/gateway.py`), el comportamiento es
    idéntico al de antes de REQ-007: se llama `claude_fn(text)` directo y
    `core.reasoning_loop.run` NUNCA se invoca."""
    from unittest.mock import patch

    from intent import classifier as classifier_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(classifier_module.ai_system, "predict", lambda text: "UNKNOWN")

        with patch("core.reasoning_loop.run") as mock_run:
            result = resolve(
                "texto sin clasificar xyz789", ChannelType.DESKTOP,
                claude_fn=lambda t: f"echo:{t}",
            )

    mock_run.assert_not_called()
    assert result.matched_by == "claude"
    assert result.text == "echo:texto sin clasificar xyz789"


# ─────────────────────────────────────────────
#  Sin conexión: el camino local como RED, no como filtro
# ─────────────────────────────────────────────

_JSON_DE_COSECHA = (
    '[{"ini": 0, "fin": 12, "color": "#92D050", "label": "0 - 12 dias"},'
    '{"ini": 13, "fin": 16, "color": "#ECEF12", "label": "13 - 16 dias"}] '
    "este json con diferentes colores quiero que me ayudes a mejorar esta visualizacion "
    "para que le asignes otra paleta de colores mejor, esto es para los ciclos de cosecha."
)


@pytest.fixture
def sin_proveedor(monkeypatch):
    """Simula que ningún proveedor de modelo responde (caída de red, o sin claves)."""
    modelo_falso.instalar_sin_proveedor(monkeypatch)


def test_sin_modelo_una_orden_se_resuelve_en_local(sin_proveedor, monkeypatch):
    """Quedarse sin internet no puede dejar al agente sin poder subir el volumen: es una
    orden que sabe ejecutar sola, sin consultarle nada a nadie."""
    # Se mockea el volumen real: `.claude/rules/testing.md` prohíbe que un test toque el
    # sistema, y esta acción es GREEN — se ejecutaría de verdad.
    ejecutadas = []

    def _subir():
        ejecutadas.append("volume_up")
        return "Volumen subido."

    monkeypatch.setattr("os_integration.system_ctrl.volume_up", _subir)

    result = resolve("sube el volumen", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "intent:SYS_VOL_UP:sin_modelo", result.matched_by
    assert ejecutadas == ["volume_up"], "la orden tenía que ejecutarse de verdad"
    assert "Sin conexión con el modelo" in result.text
    assert "Volumen subido." in result.text


def test_sin_modelo_lo_que_no_es_una_orden_dice_la_verdad(sin_proveedor):
    """La prueba que separa una RED de un FILTRO.

    El JSON de colores es justamente lo que el camino local contestaba mal ("0 x 12 = 0").
    Sin modelo no hay respuesta posible, y la honesta es decirlo — no dejar que una
    heurística invente una multiplicación con los dos primeros números que encuentre.
    """
    import ai.llm_provider as prov

    result = resolve(_JSON_DE_COSECHA, ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "claude", result.matched_by
    assert result.text == prov.SIN_PROVEEDOR
    assert "0 × 12" not in result.text and "0 x 12" not in result.text


def test_con_modelo_disponible_el_camino_local_ni_se_toca(monkeypatch):
    """El respaldo solo corre cuando el modelo NO contestó. Si corriera igual, volveríamos
    a tener heurísticas decidiendo por delante, que es lo que la inversión eliminó."""
    llamados = []

    def _espiar(nombre, fn):
        def _envuelto(text, channel, user_id):
            llamados.append(nombre)
            return fn(text, channel, user_id)
        return (nombre, _envuelto)

    import core.resolution as res

    monkeypatch.setattr(
        res, "RESOLVERS_RETIRADOS", [_espiar(n, f) for n, f in res.RESOLVERS_RETIRADOS]
    )

    result = resolve("sube el volumen", ChannelType.DESKTOP, user_id="u1")

    assert result.matched_by == "claude"
    assert llamados == [], f"el camino local corrió teniendo modelo: {llamados}"


def test_sin_modelo_el_gate_sigue_mandando(sin_proveedor, monkeypatch):
    """Sin conexión no se abre ninguna puerta: una acción YELLOW rechazada sigue denegada,
    y por voz —donde YELLOW no está permitido— ni siquiera se pregunta."""
    entradas = []
    monkeypatch.setattr("builtins.input", lambda prompt="": entradas.append(prompt) or "no")

    escritorio = resolve("cierra chrome", ChannelType.DESKTOP, user_id="u1")
    assert escritorio.denied is True, escritorio
    assert len(entradas) == 1, "DESKTOP debe pedir confirmación también sin modelo"

    entradas.clear()
    voz = resolve("cierra chrome", ChannelType.VOICE, user_id="u1")
    assert voz.denied is True
    assert entradas == [], "por VOICE no debe preguntarse, YELLOW no está permitido"
