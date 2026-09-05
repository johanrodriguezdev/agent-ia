"""
tests/test_skill_tools.py

Cobertura de `agents/skill_tools.py` (REQ-007, CA-14 a CA-17, CONFIRMADO 4/5) — migración
de `AgentTool` (`main.py` + `skill_manager.get_agent_tools()`) a `ToolSpec`.

Convenciones (.claude/rules/testing.md): usa el `skill_manager` real (ya cargado por el
import del módulo) — no ejecuta ninguna skill real, solo registra su catálogo.
"""
from unittest.mock import MagicMock, patch

from agents.skill_tools import (
    register_dispatcher_tool,
    register_skill_tools,
    _make_skill_invoke,
)
from agents.tool_registry import get_tool, list_tool_names
from core.security_manager import RiskLevel, security_manager
from skills.skill_manager import skill_manager


def test_confirmado5_dispatcher_registrado_green():
    register_dispatcher_tool()
    spec = get_tool("dispatcher")
    assert spec is not None
    assert spec.risk_level == RiskLevel.GREEN


def test_ca14_confirmado4_intent_real_se_registra_con_nombre_crudo():
    """CA-14/CONFIRMADO 4: `register_skill_tools()` corrido sobre el `SkillManager` real
    registra cada intent con su nombre crudo (p.ej. "GET_TIME"), nunca
    `skill_get_time`."""
    register_skill_tools(skill_manager)

    all_intents = [
        intent
        for skill in skill_manager.get_all_skills()
        for intent in skill.get_intents()
    ]
    assert all_intents, "no hay skills cargadas — no se puede verificar el test"

    sample_intent = all_intents[0]
    assert get_tool(sample_intent) is not None
    assert get_tool(f"skill_{sample_intent.lower()}") is None


def test_ca15_risk_level_viene_de_security_manager_no_inventado():
    """CA-15: el `risk_level` de cada `ToolSpec` migrado coincide exactamente con
    `security_manager.classify_action(intent)` — nunca un valor inventado."""
    register_skill_tools(skill_manager)

    for skill in skill_manager.get_all_skills():
        for intent in skill.get_intents():
            spec = get_tool(intent)
            assert spec is not None
            assert spec.risk_level == security_manager.classify_action(intent)


def test_ca15_intent_sin_clasificar_falla_cerrado():
    """CA-15: si un intent no tiene `risk_level` registrado en `security_manager`,
    `register_skill_tools()` levanta `RuntimeError` en vez de inventar un nivel."""
    fake_skill = MagicMock()
    fake_skill.name = "FakeSkill"
    fake_skill.description = "skill de prueba sin clasificación"
    fake_skill.get_intents.return_value = ["INTENT_JAMAS_CLASIFICADO_CA15"]

    fake_manager = MagicMock()
    fake_manager.get_all_skills.return_value = [fake_skill]

    try:
        register_skill_tools(fake_manager)
        assert False, "debía levantar RuntimeError"
    except RuntimeError as e:
        assert "INTENT_JAMAS_CLASIFICADO_CA15" in str(e)


def test_ca16_invoke_llama_extract_params_luego_execute_sin_auto_gate():
    """CA-16: el `invoke` generado llama `skill.extract_params(intent, text)` y LUEGO
    `skill.execute(intent, exec_params)`, en ese orden, sin ningún
    `require_confirmation()` propio — el gate ya ocurrió en `execute_tool()`."""
    skill = MagicMock()
    skill.extract_params.return_value = {"app": "chrome"}
    skill.execute.return_value = "listo"

    invoke = _make_skill_invoke(skill, "OPEN_APP")

    with patch("agents.skill_tools.security_manager") as mock_sm:
        result = invoke({"text": "abre chrome", "channel": "desktop", "user_id": "u1"})
        mock_sm.require_confirmation.assert_not_called()

    assert result == "listo"
    skill.extract_params.assert_called_once_with("OPEN_APP", "abre chrome")

    exec_call_args = skill.execute.call_args
    assert exec_call_args.args[0] == "OPEN_APP"
    exec_params = exec_call_args.args[1]
    assert exec_params["app"] == "chrome"
    assert exec_params["channel"] == "desktop"
    assert exec_params["user_id"] == "u1"

    # extract_params se llamó ANTES que execute (orden CA-16).
    assert skill.mock_calls.index(
        next(c for c in skill.mock_calls if c[0] == "extract_params")
    ) < skill.mock_calls.index(
        next(c for c in skill.mock_calls if c[0] == "execute")
    )


def test_de_deriva_conteo_intents_vs_tools_migrados():
    """Test de deriva (sugerido en arquitectura-007.md, no ligado a un CA puntual):
    `len(skill_manager.get_agent_tools())` (oráculo legado de `AgentTool`, todavía
    construido por `skill_manager.py` sin tocar) debe coincidir con la cantidad de
    intents de skill migrados a `ToolSpec` — detecta drift si una skill nueva no
    termina migrada.

    Se compara por CONJUNTO de nombres de intent (no por tamaño total de
    `list_tool_names()`) porque el registro de tools es un singleton de módulo
    compartido entre archivos de test — otros tests registran sus propios tools de
    prueba (`task_create`/`task_list`/`task_complete` del propio `tool_registry.py`,
    tools de `test_reasoning_loop.py`, etc.) y un conteo total absoluto sería frágil al
    orden de ejecución de la suite."""
    register_dispatcher_tool()
    register_skill_tools(skill_manager)

    expected_intents = {
        intent for skill in skill_manager.get_all_skills() for intent in skill.get_intents()
    }
    registered_names = set(list_tool_names())

    assert expected_intents <= registered_names, expected_intents - registered_names
    assert len(skill_manager.get_agent_tools()) == len(expected_intents)


# ─────────────────────────────────────────────
#  El modelo reformula; el clasificador no lo perdona
# ─────────────────────────────────────────────

def test_el_despachador_reintenta_con_las_palabras_del_usuario(monkeypatch):
    """El usuario dijo "Abre la calculadora" y al despachador le llegó "abrir la
    calculadora de windows": el modelo pasa la orden a infinitivo, y el clasificador está
    entrenado con imperativos ("abre la calculadora" puntúa +0.66 con margen 1.10; "abrir
    la calculadora", -0.27). La orden no se reconocía, el modelo probaba una herramienta
    más pesada, y abrir la calculadora acababa pidiendo confirmación
    (logs/orion.log, 2026-09-04 22:15).
    """
    import router.dispatcher as dispatcher_module

    recibido = []
    monkeypatch.setattr(
        dispatcher_module, "dispatch",
        lambda intent, params: recibido.append((str(intent), dict(params))) or "ok",
    )

    dispatcher_module.dispatch_as_tool({
        "task": "abrir la calculadora de windows",
        "texto_original": "Abre la calculadora",
        "channel": "desktop",
    })

    intent, params = recibido[-1]
    assert intent == "OPEN_APP", recibido
    assert params.get("app_name") == "calculadora", params


def test_lo_que_el_modelo_pide_manda_si_se_reconoce(monkeypatch):
    """El reintento es una red, no un secuestro: si lo que pidió el modelo se entiende, se
    ejecuta eso y no lo que el usuario dijo hace tres turnos."""
    import router.dispatcher as dispatcher_module

    recibido = []
    monkeypatch.setattr(
        dispatcher_module, "dispatch",
        lambda intent, params: recibido.append((str(intent), dict(params))) or "ok",
    )

    dispatcher_module.dispatch_as_tool({
        "task": "sube el volumen",
        "texto_original": "Abre la calculadora",
        "channel": "desktop",
    })

    assert recibido[-1][0] == "SYS_VOL_UP", recibido


def test_el_texto_original_lo_pone_el_bucle_no_el_modelo():
    """Mismo invariante que `channel` y `user_id`: es un dato de la invocación, y el modelo
    no puede proponerlo. Si pudiera, podría hacer pasar por "lo que dijo el usuario" algo
    que el usuario nunca dijo."""
    import inspect

    from core import reasoning_loop

    fuente = inspect.getsource(reasoning_loop.run)
    assert 'params["texto_original"] = task' in fuente
