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


# ─────────────────────────────────────────────
#  Menos herramientas delante del modelo, mismos permisos detrás
# ─────────────────────────────────────────────

def _catalogo_completo():
    from agents.skill_tools import (register_dispatcher_tool, register_family_tools,
                                    register_skill_tools)
    from agents.user_defined_tools import register_user_defined_tools
    from skills.skill_manager import skill_manager

    register_dispatcher_tool()
    register_skill_tools(skill_manager)
    register_family_tools(skill_manager)
    register_user_defined_tools()


def test_lo_agrupado_sigue_registrado_con_su_propio_nivel():
    """La propiedad que no se puede perder: agrupar es PRESENTACIÓN, no permisos.

    Cada intent conserva su nombre, su nivel y su gate; lo único que cambia es que el
    modelo ve una entrada en vez de tres. Si agrupar borrara el registro, el gate dejaría
    de poder clasificar la acción concreta y `execute_tool()` la denegaría por
    "tool no registrado" — o peor, la familia entera pasaría a compartir un solo veredicto.
    """
    from agents.skill_tools import INTENTS_OCULTOS
    from agents.tool_registry import get_tool

    _catalogo_completo()

    for intent in INTENTS_OCULTOS:
        spec = get_tool(intent)
        assert spec is not None, f"'{intent}' dejó de estar registrado al agruparlo"
        assert spec.risk_level is not None


def test_una_familia_nunca_mezcla_niveles_de_riesgo():
    """Juntar una verde con una amarilla obligaría a darle a todo el grupo el nivel más
    alto: listar tareas pediría confirmación. La granularidad del gate es por acción."""
    from agents.skill_tools import _FAMILIAS
    from core.security_manager import security_manager

    _catalogo_completo()

    for familia, datos in _FAMILIAS.items():
        niveles = {security_manager.classify_action(i) for i in datos["opciones"].values()}
        assert len(niveles) == 1, f"la familia '{familia}' mezcla niveles: {niveles}"


def test_las_acciones_amarillas_no_se_esconden_dentro_de_una_familia():
    """`SYS_POWER_OFF` y `CREATE_FLOW` son amarillas y quedan FUERA de sus familias
    (volumen y flujos, verdes). Apagar el computador no puede entrar por la misma puerta
    que subir el volumen."""
    from agents.skill_tools import INTENTS_OCULTOS

    assert "SYS_POWER_OFF" not in INTENTS_OCULTOS
    assert "CREATE_FLOW" not in INTENTS_OCULTOS


def test_la_familia_ejecuta_la_accion_concreta_por_el_gate():
    from unittest.mock import patch as _patch

    from agents.tool_registry import execute_tool
    from core.security_manager import ChannelType

    _catalogo_completo()
    ejecutado = []

    with _patch("os_integration.system_ctrl.volume_up",
                lambda: ejecutado.append("volume_up") or "Volumen subido."):
        resultado = execute_tool(
            "volumen",
            {"opcion": "subir", "text": "sube el volumen", "channel": "desktop",
             "user_id": "owner"},
            ChannelType.DESKTOP, "owner",
        )

    assert ejecutado == ["volume_up"], resultado


def test_una_opcion_inventada_no_ejecuta_nada():
    from agents.tool_registry import execute_tool
    from core.security_manager import ChannelType

    _catalogo_completo()
    resultado = execute_tool(
        "volumen", {"opcion": "formatear el disco", "channel": "desktop", "user_id": "owner"},
        ChannelType.DESKTOP, "owner",
    )

    assert "no válida" in resultado


def test_un_canal_no_ve_lo_que_no_podria_ejecutar():
    """Ofrecerle a Telegram `terminal_run_command` solo le hace gastar una vuelta en
    descubrir que le van a decir que no. No es control de acceso —ese sigue en
    `execute_tool()`—, es no prometer lo que no se va a cumplir."""
    from core.reasoning_loop import _build_tool_list
    from core.security_manager import ChannelType

    _catalogo_completo()
    escritorio = {t["name"] for t in _build_tool_list(ChannelType.DESKTOP)}
    telegram = {t["name"] for t in _build_tool_list(ChannelType.TELEGRAM)}

    assert telegram < escritorio, "Telegram debería ver menos que el escritorio"
    assert "terminal_run_command" in escritorio
    assert "terminal_run_command" not in telegram

def test_los_dos_motores_ofrecen_el_mismo_catalogo():
    """Hay dos sitios que le muestran herramientas al modelo —`core/reasoning_loop.py`
    (escritorio y voz) y `ai/claude_brain.py` (Telegram y Discord)— y cada uno armaba su
    lista por su cuenta. El resultado era que la reducción del catálogo aplicaba en un
    canal y no en el otro: por Telegram seguían apareciendo las agrupadas y las amarillas
    que ese canal nunca puede ejecutar. Ahora los dos leen `catalogo_para_modelo()`.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    for modulo in ("core/reasoning_loop.py", "ai/claude_brain.py"):
        fuente = (raiz / modulo).read_text(encoding="utf-8")
        assert "catalogo_para_modelo" in fuente, f"{modulo} arma su lista por su cuenta"


def test_el_catalogo_del_modelo_se_reduce_por_canal():
    from agents.tool_registry import catalogo_para_modelo, list_tool_names
    from core.security_manager import ChannelType

    _catalogo_completo()

    registradas = len(list_tool_names())
    escritorio = len(catalogo_para_modelo(ChannelType.DESKTOP))
    telegram = len(catalogo_para_modelo(ChannelType.TELEGRAM))

    # Registradas > ofrecidas: lo agrupado y lo que el canal no puede sigue existiendo.
    assert telegram < escritorio < registradas, (registradas, escritorio, telegram)
