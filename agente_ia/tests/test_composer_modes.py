"""
tests/test_composer_modes.py

REQ-026 — cobertura de `core/composer_modes.py`: el catálogo único de los 4 modos
estratégicos del composer (Código/script, Investigación, Nodos/flujos, Tareas) que
consumen tanto `ui/webview/bridge.py` como `core/reasoning_loop.py`.

Convenciones (.claude/rules/testing.md): módulo puro, sin red, sin DB, sin Qt — no
necesita ningún mock.
"""
from core.composer_modes import ModoComposer, get_mode, listar_modos


def test_listar_modos_devuelve_exactamente_4_en_el_orden_de_la_ui():
    """SPEC-026, criterio de catálogo: la fila principal muestra EXACTAMENTE 4 modos."""
    modos = listar_modos()

    assert len(modos) == 4
    assert [m.id for m in modos] == ["codigo", "investigacion", "flujos", "tareas"]
    assert [m.label for m in modos] == [
        "Código/script", "Investigación", "Nodos/flujos", "Tareas",
    ]


def test_cada_modo_es_un_modocomposer_con_los_5_campos():
    for modo in listar_modos():
        assert isinstance(modo, ModoComposer)
        assert isinstance(modo.id, str) and modo.id
        assert isinstance(modo.label, str) and modo.label
        assert isinstance(modo.tool_names, tuple) and len(modo.tool_names) > 0
        assert modo.tarea is None or isinstance(modo.tarea, str)
        assert isinstance(modo.prompt_hint, str) and modo.prompt_hint


def test_mapeo_modo_a_tools_segun_arquitectura_026():
    """arquitectura-026.md §1 — mapeo modo→tools corregido (no el de la SPEC original,
    que incluía `info_skill` por error)."""
    por_id = {m.id: m for m in listar_modos()}

    assert por_id["codigo"].tool_names == ("EXECUTE_CODE",)
    assert por_id["investigacion"].tool_names == (
        "web_search", "web_read", "wikipedia_search", "BROWSE_WEB",
    )
    assert por_id["flujos"].tool_names == ("flujo", "CREATE_FLOW")
    assert por_id["tareas"].tool_names == (
        "task_create", "task_list", "task_complete", "task_complete_all",
    )


def test_solo_codigo_e_investigacion_fijan_tarea():
    """arquitectura-026.md §3 — decisión de criterio técnico: Nodos/flujos y Tareas
    necesitan tool-calling multi-paso con el modelo de razonamiento principal, así que
    NO fijan `tarea` (quedan en `tarea=None` → `"razonamiento"` en el caller)."""
    por_id = {m.id: m for m in listar_modos()}

    assert por_id["codigo"].tarea == "modo_codigo"
    assert por_id["investigacion"].tarea == "modo_investigacion"
    assert por_id["flujos"].tarea is None
    assert por_id["tareas"].tarea is None


def test_get_mode_resuelve_un_id_valido():
    modo = get_mode("codigo")
    assert modo is not None
    assert modo.id == "codigo"
    assert modo.label == "Código/script"


def test_get_mode_vacio_o_none_es_sin_modo():
    """Camino normal (sin modo activo) — idéntico al de antes de REQ-026."""
    assert get_mode(None) is None
    assert get_mode("") is None


def test_get_mode_id_desconocido_es_fail_safe_no_lanza():
    """Un frontend cacheado con un catálogo viejo (o un id inventado) nunca debe romper
    el turno — se trata exactamente igual que 'sin modo activo'."""
    assert get_mode("modo_que_no_existe") is None
    assert get_mode("   ") is None or isinstance(get_mode("   "), ModoComposer) is False


def test_listar_modos_es_estable_entre_llamadas():
    """`_MODOS` es una tupla módulo-level (frozen dataclasses) — dos llamadas devuelven
    el mismo catálogo, no una copia distinta cada vez que podría desincronizarse."""
    assert listar_modos() == listar_modos()


def test_ca12_cada_modo_declara_su_presupuesto():
    """REQ-027/CA-12: el presupuesto vive en el catálogo, junto a `tool_names` y `tarea`,
    y no en una tabla paralela en otro módulo que haya que mantener sincronizada."""
    esperado = {"codigo": 40, "investigacion": 25, "flujos": 12, "tareas": 10}
    assert {m.id: m.presupuesto for m in listar_modos()} == esperado


def test_ca12_el_presupuesto_es_obligatorio_al_declarar_un_modo():
    """D-9: un modo nuevo que se olvide de declararlo tiene que explotar al construirlo, no
    heredar en silencio el presupuesto más bajo."""
    import pytest

    with pytest.raises(TypeError):
        ModoComposer(
            id="x", label="X", tool_names=(), tarea=None, prompt_hint="",
        )
