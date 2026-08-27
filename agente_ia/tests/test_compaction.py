"""
tests/test_compaction.py
Pruebas de `core/compaction.py` — resumir lo viejo en vez de cortarlo.

El invariante que protege esta suite: **compactar nunca puede dejar la conversación peor de
como estaba**. Si el resumen falla, sale vacío o el corte caería mal, se devuelve el
historial intacto. Un historial largo funciona; uno mutilado, no.

Ningún test llama al modelo real: el resumidor se inyecta.
"""

import pytest

from core import compaction


def _historial(n, empezando_por="user"):
    """Return `n` mensajes alternando usuario y asistente."""
    roles = ["user", "assistant"] if empezando_por == "user" else ["assistant", "user"]
    return [
        {"role": roles[i % 2], "content": f"mensaje {i}"}
        for i in range(n)
    ]


def _resumidor(texto):
    return "Resumen de lo hablado."


# ── Cuándo actúa y cuándo no ────────────────────────────────────────

def test_una_conversacion_corta_no_se_toca():
    historial = _historial(10)

    assert compaction.compactar(historial, resumir_fn=_resumidor) is historial


def test_una_conversacion_larga_se_compacta():
    historial = _historial(60)

    resultado = compaction.compactar(historial, resumir_fn=_resumidor)

    assert len(resultado) < len(historial)
    assert compaction.MARCA_RESUMEN in resultado[0]["content"]


def test_un_historial_vacio_no_rompe():
    assert compaction.compactar([], resumir_fn=_resumidor) == []


# ── Lo reciente se conserva literal ─────────────────────────────────

def test_los_mensajes_recientes_quedan_palabra_por_palabra():
    historial = _historial(60)

    resultado = compaction.compactar(historial, resumir_fn=_resumidor)

    ultimos_originales = [m["content"] for m in historial[-10:]]
    ultimos_resultado = [m["content"] for m in resultado[-10:]]
    assert ultimos_resultado == ultimos_originales


def test_no_se_parte_un_intercambio_por_la_mitad():
    """La parte conservada tiene que empezar por una pregunta, no por una respuesta suelta."""
    historial = _historial(60)

    resultado = compaction.compactar(historial, resumir_fn=_resumidor)

    # [0] es el resumen; [1] es el primero conservado.
    assert resultado[1]["role"] == "user"


# ── Ante la duda, no tocar ──────────────────────────────────────────

def test_si_el_resumidor_falla_se_devuelve_el_historial_intacto():
    def _explota(_texto):
        raise RuntimeError("el modelo no responde")

    historial = _historial(60)

    assert compaction.compactar(historial, resumir_fn=_explota) is historial


def test_si_el_resumen_sale_vacio_no_se_compacta():
    historial = _historial(60)

    assert compaction.compactar(historial, resumir_fn=lambda t: "   ") is historial


def test_si_el_resumidor_devuelve_none_no_se_compacta():
    historial = _historial(60)

    assert compaction.compactar(historial, resumir_fn=lambda t: None) is historial


# ── No crecer sin freno ─────────────────────────────────────────────

def test_un_resumen_previo_se_absorbe_en_el_nuevo():
    """Si cada compactación dejara un resumen más, volveríamos al problema original."""
    recibido = {}

    def _capturar(texto):
        recibido["texto"] = texto
        return "Resumen nuevo."

    historial = (
        [{"role": "user", "content": f"{compaction.MARCA_RESUMEN}\nLo de antes."}]
        + _historial(60)
    )

    resultado = compaction.compactar(historial, resumir_fn=_capturar)

    assert "Lo de antes." in recibido["texto"]          # el previo entró al nuevo resumen
    marcas = [m for m in resultado if compaction.MARCA_RESUMEN in m["content"]]
    assert len(marcas) == 1                              # y solo queda uno


def test_compactar_dos_veces_no_acumula_resumenes():
    historial = _historial(60)

    primera = compaction.compactar(historial, resumir_fn=_resumidor)
    segunda = compaction.compactar(primera + _historial(60), resumir_fn=_resumidor)

    marcas = [m for m in segunda if compaction.MARCA_RESUMEN in m["content"]]
    assert len(marcas) == 1


# ── Tamaño ──────────────────────────────────────────────────────────

def test_un_resumen_desmedido_se_recorta():
    """Un resumen de mil palabras no ahorra nada, que es el objetivo."""
    historial = _historial(60)

    resultado = compaction.compactar(historial, resumir_fn=lambda t: "x" * 9000)

    assert len(resultado[0]["content"]) < compaction.MAX_CHARS_RESUMEN + 200


def test_los_umbrales_estan_fijados():
    """Moverlos cambia cuánto contexto ve el modelo y cuánto cuesta cada turno."""
    assert compaction.UMBRAL_MENSAJES == 40
    assert compaction.MENSAJES_RECIENTES == 16


# ── Integración con el historial real ───────────────────────────────

def test_el_historial_guardado_se_modifica_de_verdad(monkeypatch):
    """El bug original: `history = history[-N:]` reasignaba la variable local y la lista
    guardada seguía creciendo, ademas de perder los mensajes posteriores."""
    import ai.claude_brain as cb

    guardado = _historial(60)
    almacen = {"owner": guardado}
    monkeypatch.setattr(cb, "_conversation_histories", almacen)
    monkeypatch.setattr(
        "core.compaction._resumir_con_modelo", lambda t: "Resumen."
    )
    monkeypatch.setattr(cb, "_resolver_con_tools", lambda *a, **k: "respuesta")

    # `ask_claude` consulta la memoria semántica, y eso carga el modelo de embeddings: 50
    # segundos de espera en un test que no tiene nada que ver con la búsqueda. Se anula.
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "search_semantic", lambda *a, **k: [])
    monkeypatch.setattr(memory, "get_user_profile_text", lambda *a, **k: "")

    cb.ask_claude("un mensaje mas", user_id="owner")

    # La MISMA lista sigue en el almacén y ya está compactada.
    assert almacen["owner"] is guardado
    assert len(guardado) < 62
    assert compaction.MARCA_RESUMEN in guardado[0]["content"]
    # Y la respuesta del asistente sí quedó guardada.
    assert guardado[-1]["content"] == "respuesta"
