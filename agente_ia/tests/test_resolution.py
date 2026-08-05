"""
tests/test_resolution.py

REQ-006 — `core/resolution.py:resolve()`, punto único de resolución (CA-01, CA-02,
CA-03, CA-04, CA-06, CA-07).

Convenciones (.claude/rules/testing.md): sin red, sin mic/altavoces, `input()` siempre
mockeado cuando aplica.
"""

import re
from pathlib import Path

import pytest

from agents.action_registry import ACTION_REGISTRY
from agents.tool_registry import list_tool_names
from core.resolution import resolve
from core.security_manager import ChannelType, security_manager
from intent.intentions import Intent

REPO_ROOT = Path(__file__).resolve().parent.parent


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
    assert matched_by_values == {"intent:CALCULATE"}, matched_by_values
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
    assert matched_by_values == {"intent:CLOSE_APP"}, matched_by_values
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

    mock_run.assert_called_once_with(
        "texto sin clasificar xyz789", ChannelType.DESKTOP, "u1"
    )
    assert result.matched_by == "claude"
    assert result.text == "respuesta del loop"


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
