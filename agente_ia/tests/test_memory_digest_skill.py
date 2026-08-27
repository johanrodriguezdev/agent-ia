"""
tests/test_memory_digest_skill.py
Pruebas de `skills/memory_digest_skill.py` — destilación del historial a MEMORY.md.

El invariante que protege esta suite: **nunca se pierde lo que el usuario escribió a mano.**
La skill reescribe un archivo del proyecto con texto generado por un modelo, así que lo que
importa no es que escriba bien, sino que no destruya nada al hacerlo.

Ningún test llama al modelo real (`.claude/rules/testing.md`).
"""

import os

import pytest

from skills.memory_digest_skill import MemoryDigestSkill


@pytest.fixture
def skill(tmp_path, monkeypatch):
    """Skill apuntando a un MEMORY.md desechable."""
    import skills.memory_digest_skill as mod

    destino = str(tmp_path / "MEMORY.md")
    monkeypatch.setattr(mod, "MEMORY_FILE", destino)
    monkeypatch.setattr(mod, "BACKUP_FILE", destino + ".bak")
    s = MemoryDigestSkill()
    s._destino = destino
    return s


def _leer(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _mock_llm(monkeypatch, respuestas):
    """Sustituye `generate_response` por una secuencia fija de respuestas."""
    import ai.llm_provider as prov

    pendientes = list(respuestas)

    def _fake(messages, system_prompt, **kwargs):
        return pendientes.pop(0) if pendientes else "SIN HECHOS"

    monkeypatch.setattr(prov, "generate_response", _fake)


# ── Camino feliz ────────────────────────────────────────────────────

def test_destila_el_historial_y_escribe_el_bloque(skill, monkeypatch):
    monkeypatch.setattr(skill, "_leer_historial", lambda: ["Johan usa VS Code"])
    _mock_llm(monkeypatch, ["- Johan usa VS Code", "## Sobre el usuario\n- Usa VS Code"])

    resultado = skill.execute("UPDATE_MEMORY_FILE", {})

    contenido = _leer(skill._destino)
    assert "Usa VS Code" in contenido
    assert "MEMORIA-GENERADA:INICIO" in contenido
    assert "MEMORIA-GENERADA:FIN" in contenido
    assert "Memoria actualizada" in resultado


def test_informa_cuantos_registros_y_hechos(skill, monkeypatch):
    monkeypatch.setattr(skill, "_leer_historial", lambda: ["a", "b", "c"])
    _mock_llm(monkeypatch, ["- hecho uno\n- hecho dos", "## Sobre el usuario\n- hecho uno"])

    resultado = skill.execute("UPDATE_MEMORY_FILE", {})

    assert "3 registros" in resultado
    assert "2 hechos" in resultado


# ── Lo escrito a mano: el invariante crítico ────────────────────────

def test_conserva_intacto_lo_escrito_a_mano(skill, monkeypatch):
    manual = "# Mi memoria\n\n## Notas mías\n- No borrar esto jamás\n"
    with open(skill._destino, "w", encoding="utf-8") as f:
        f.write(manual)

    monkeypatch.setattr(skill, "_leer_historial", lambda: ["algo"])
    _mock_llm(monkeypatch, ["- un hecho", "## Sobre el usuario\n- un hecho"])

    skill.execute("UPDATE_MEMORY_FILE", {})

    contenido = _leer(skill._destino)
    assert "# Mi memoria" in contenido
    assert "- No borrar esto jamás" in contenido
    assert "un hecho" in contenido


def test_una_segunda_pasada_reemplaza_solo_el_bloque_generado(skill, monkeypatch):
    monkeypatch.setattr(skill, "_leer_historial", lambda: ["algo"])

    _mock_llm(monkeypatch, ["- viejo", "## Sobre el usuario\n- dato VIEJO"])
    skill.execute("UPDATE_MEMORY_FILE", {})

    # El usuario añade una nota suya después de la primera pasada.
    with open(skill._destino, "a", encoding="utf-8") as f:
        f.write("\n## Añadido por Johan\n- sobrevive\n")

    _mock_llm(monkeypatch, ["- nuevo", "## Sobre el usuario\n- dato NUEVO"])
    skill.execute("UPDATE_MEMORY_FILE", {})

    contenido = _leer(skill._destino)
    assert "dato NUEVO" in contenido
    assert "dato VIEJO" not in contenido        # el bloque se reemplazó
    assert "- sobrevive" in contenido           # la nota manual sigue
    assert contenido.count("MEMORIA-GENERADA:INICIO") == 1


def test_deja_copia_de_seguridad_antes_de_escribir(skill, monkeypatch):
    with open(skill._destino, "w", encoding="utf-8") as f:
        f.write("contenido original")

    monkeypatch.setattr(skill, "_leer_historial", lambda: ["algo"])
    _mock_llm(monkeypatch, ["- Johan prefiere respuestas cortas",
                            "## Sobre el usuario\n- Prefiere respuestas cortas"])

    skill.execute("UPDATE_MEMORY_FILE", {})

    assert os.path.exists(skill._destino + ".bak")
    assert _leer(skill._destino + ".bak") == "contenido original"


# ── Degradación: ante la duda, no escribir ──────────────────────────

def test_sin_historial_no_escribe_nada(skill, monkeypatch):
    monkeypatch.setattr(skill, "_leer_historial", lambda: [])

    resultado = skill.execute("UPDATE_MEMORY_FILE", {})

    assert "No encontré historial" in resultado
    assert not os.path.exists(skill._destino)


def test_si_no_hay_hechos_no_toca_el_archivo(skill, monkeypatch):
    with open(skill._destino, "w", encoding="utf-8") as f:
        f.write("intacto")

    monkeypatch.setattr(skill, "_leer_historial", lambda: ["charla trivial"])
    _mock_llm(monkeypatch, ["SIN HECHOS"])

    resultado = skill.execute("UPDATE_MEMORY_FILE", {})

    assert "no encontré hechos nuevos" in resultado
    assert _leer(skill._destino) == "intacto"


def test_si_falla_la_consolidacion_no_escribe(skill, monkeypatch):
    import ai.llm_provider as prov

    with open(skill._destino, "w", encoding="utf-8") as f:
        f.write("intacto")

    monkeypatch.setattr(skill, "_leer_historial", lambda: ["algo"])

    llamadas = {"n": 0}

    def _fake(messages, system_prompt, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return "- un hecho"
        raise RuntimeError("el modelo no responde")

    monkeypatch.setattr(prov, "generate_response", _fake)

    resultado = skill.execute("UPDATE_MEMORY_FILE", {})

    assert "no pude consolidarlos" in resultado.lower()
    assert _leer(skill._destino) == "intacto"


def test_un_lote_fallido_no_tumba_la_destilacion(skill, monkeypatch):
    """Un fallo puntual del modelo se salta; lo demás se aprovecha y se avisa."""
    import ai.llm_provider as prov
    import skills.memory_digest_skill as mod

    monkeypatch.setattr(mod, "TAMANO_LOTE", 1)
    monkeypatch.setattr(skill, "_leer_historial", lambda: ["uno", "dos"])

    llamadas = {"n": 0}

    def _fake(messages, system_prompt, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("lote caido")
        if llamadas["n"] == 2:
            return "- hecho del segundo lote"
        return "## Sobre el usuario\n- hecho del segundo lote"

    monkeypatch.setattr(prov, "generate_response", _fake)

    resultado = skill.execute("UPDATE_MEMORY_FILE", {})

    assert "hecho del segundo lote" in _leer(skill._destino)
    assert "1 lote(s) fallaron" in resultado


def test_si_todos_los_lotes_fallan_no_escribe(skill, monkeypatch):
    import ai.llm_provider as prov

    monkeypatch.setattr(skill, "_leer_historial", lambda: ["uno"])
    monkeypatch.setattr(
        prov, "generate_response",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("caido")),
    )

    resultado = skill.execute("UPDATE_MEMORY_FILE", {})

    assert "No pude destilar" in resultado
    assert not os.path.exists(skill._destino)


# ── Contrato de skill ───────────────────────────────────────────────

def test_declara_su_intent_y_datos_de_entrenamiento(skill):
    assert skill.get_intents() == ["UPDATE_MEMORY_FILE"]

    entrenamiento = skill.get_training_data()
    assert len(entrenamiento) >= 5
    assert all(intent == "UPDATE_MEMORY_FILE" for _, intent in entrenamiento)


def test_la_accion_esta_clasificada_como_amarilla():
    """Reescribe un archivo del proyecto: sin clasificar quedaría bloqueada (fail-closed)."""
    from core.security_manager import RiskLevel, security_manager

    assert security_manager._actions.get("UPDATE_MEMORY_FILE") == RiskLevel.YELLOW


# ── Filtro de hechos no durables ────────────────────────────────────
#
# La primera destilación real llenó "Preferencias de trabajo" con peticiones sueltas
# ("El usuario pidió reproducir Bed of Roses"). El prompt las prohíbe, pero el prompt es una
# sugerencia y esto no: lo que pase el filtro acaba en MEMORY.md influyendo en cada respuesta.

@pytest.mark.parametrize("linea", [
    "- El usuario pidió reproducir Bed of Roses de Bon Jovi",
    "- El usuario pidio usar la calculadora",
    "- El usuario preguntó qué es un bot",
    "- El usuario pregunto por el uso de CPU",
    "- El usuario solicitó una captura de pantalla",
    "- El usuario quiso cerrar pgAdmin",
])
def test_descarta_las_peticiones_puntuales(linea):
    from skills.memory_digest_skill import _es_hecho_durable

    assert _es_hecho_durable(linea) is False


@pytest.mark.parametrize("linea", [
    "- Escucha rock clásico, sobre todo Bon Jovi",
    "- Su equipo se llama Hansel y usa Windows 11",
    "- Trabaja con Unipalma",
    "- Tiene perros que necesita sacar",
    "- Prefiere que lo traten de 'Señor Johan'",
    "- Vive en Villavicencio, Colombia",
])
def test_conserva_los_hechos_durables(linea):
    from skills.memory_digest_skill import _es_hecho_durable

    assert _es_hecho_durable(linea) is True


def test_el_filtro_actua_aunque_el_modelo_desobedezca(skill, monkeypatch):
    """Extremo a extremo: si el modelo cuela peticiones, no llegan a MEMORY.md."""
    monkeypatch.setattr(skill, "_leer_historial", lambda: ["algo"])
    _mock_llm(monkeypatch, [
        "- El usuario pidió abrir la calculadora\n- Vive en Villavicencio",
        "## Sobre el usuario\n- Vive en Villavicencio",
    ])

    skill.execute("UPDATE_MEMORY_FILE", {})

    contenido = _leer(skill._destino)
    assert "Villavicencio" in contenido
    assert "pidió abrir la calculadora" not in contenido
