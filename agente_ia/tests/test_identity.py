"""
tests/test_identity.py
Pruebas de `core/identity.py` — carga de SOUL.md / IDENTITY.md / USER.md para el prompt.

Ningún test toca los archivos reales del proyecto: todos redirigen `_PROJECT_ROOT` a un
`tmp_path`, como exige `.claude/rules/testing.md`.
"""

import os

import pytest

from core import identity


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    """Aísla cada test en su propia raíz y limpia la caché entre tests."""
    monkeypatch.setattr(identity, "_PROJECT_ROOT", str(tmp_path))
    identity.clear_cache()
    yield tmp_path
    identity.clear_cache()


def _write(root, name, text):
    path = os.path.join(str(root), name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ── Camino feliz ────────────────────────────────────────────────────

def test_los_tres_documentos_entran_en_el_bloque(_isolated_root):
    _write(_isolated_root, "SOUL.md", "Humor seco y sutil.")
    _write(_isolated_root, "IDENTITY.md", "Asistente de escritorio.")
    _write(_isolated_root, "USER.md", "Johan, de Villavicencio.")

    block = identity.build_identity_block("O.R.I.O.N")

    assert "Humor seco y sutil." in block
    assert "Asistente de escritorio." in block
    assert "Johan, de Villavicencio." in block


def test_el_orden_es_voz_rol_usuario(_isolated_root):
    """El modelo necesita el tono antes que el contenido: SOUL va primero."""
    _write(_isolated_root, "SOUL.md", "ALMA")
    _write(_isolated_root, "IDENTITY.md", "ROL")
    _write(_isolated_root, "USER.md", "USUARIO")

    block = identity.build_identity_block("O.R.I.O.N")

    assert block.index("ALMA") < block.index("ROL") < block.index("USUARIO")


def test_el_nombre_configurado_se_declara_autoridad(_isolated_root):
    """Un documento con el nombre viejo no debe poder renombrar al agente."""
    _write(_isolated_root, "SOUL.md", "Eres Noddoo, un asistente leal.")

    block = identity.build_identity_block("O.R.I.O.N")

    assert "Tu nombre es O.R.I.O.N" in block
    assert "está desactualizado" in block


def test_el_bloque_pide_encarnar_no_citar(_isolated_root):
    """Sin esta instruccion el modelo tiende a responder 'segun mi SOUL.md...'."""
    _write(_isolated_root, "SOUL.md", "Formal pero no frio.")

    block = identity.build_identity_block("O.R.I.O.N")

    assert "Encárnalos" in block
    assert "no los cites" in block


# ── Degradación: nunca romper el turno ──────────────────────────────

def test_sin_ningun_documento_devuelve_cadena_vacia(_isolated_root):
    """El caller concatena sin condicionales: el prompt queda igual que antes del módulo."""
    assert identity.build_identity_block("O.R.I.O.N") == ""


def test_un_documento_ausente_se_omite_y_el_resto_entra(_isolated_root):
    _write(_isolated_root, "SOUL.md", "ALMA")
    # IDENTITY.md y USER.md no existen

    block = identity.build_identity_block("O.R.I.O.N")

    assert "ALMA" in block
    assert "TU ROL" not in block
    assert "QUIÉN ES TU USUARIO" not in block


def test_un_documento_vacio_se_omite(_isolated_root):
    _write(_isolated_root, "SOUL.md", "   \n\n  ")
    _write(_isolated_root, "IDENTITY.md", "ROL")

    block = identity.build_identity_block("O.R.I.O.N")

    assert "TU VOZ" not in block
    assert "ROL" in block


def test_un_documento_no_utf8_se_omite_y_queda_registrado(_isolated_root, caplog):
    path = os.path.join(str(_isolated_root), "SOUL.md")
    with open(path, "wb") as f:
        f.write(b"\xff\xfe\x00 bytes invalidos")
    _write(_isolated_root, "USER.md", "USUARIO")

    with caplog.at_level("WARNING"):
        block = identity.build_identity_block("O.R.I.O.N")

    assert "USUARIO" in block          # el resto sigue entrando
    assert "TU VOZ" not in block
    assert any("SOUL.md" in r.message for r in caplog.records)


def test_un_error_de_lectura_no_lanza(_isolated_root, monkeypatch):
    """Un OSError al abrir (permisos, archivo bloqueado) degrada, no rompe el turno."""
    _write(_isolated_root, "SOUL.md", "ALMA")

    def _boom(*args, **kwargs):
        raise OSError("permiso denegado")

    monkeypatch.setattr("builtins.open", _boom)

    assert identity.build_identity_block("O.R.I.O.N") == ""


# ── Presupuesto ─────────────────────────────────────────────────────

def test_un_documento_enorme_se_trunca(_isolated_root):
    _write(_isolated_root, "SOUL.md", "linea de relleno\n" * 5000)

    block = identity.build_identity_block("O.R.I.O.N")

    assert identity._TRUNCATION_NOTE.strip() in block
    assert len(block) < identity.MAX_CHARS_PER_FILE + 2000


def test_el_presupuesto_total_corta_los_documentos_siguientes(_isolated_root):
    """Tres documentos en su techo (18000) exceden el total (14000): el tercero no entra.

    El corte es por documento completo, nunca a mitad de uno: media identidad confunde
    más al modelo que ninguna.
    """
    grande = "x" * (identity.MAX_CHARS_PER_FILE - 10)
    _write(_isolated_root, "SOUL.md", grande)
    _write(_isolated_root, "IDENTITY.md", grande)
    _write(_isolated_root, "USER.md", "USUARIO_QUE_NO_DEBERIA_ENTRAR\n" + grande)

    block = identity.build_identity_block("O.R.I.O.N")

    assert "USUARIO_QUE_NO_DEBERIA_ENTRAR" not in block
    assert "TU VOZ Y TU CARÁCTER" in block          # los dos primeros sí entran
    assert "TU ROL Y TUS LÍMITES" in block
    assert len(block) <= identity.MAX_CHARS_TOTAL + 1000  # + cabecera y nota de nombre


def test_los_limites_de_presupuesto_estan_fijados():
    """Fijación literal: moverlos cambia el coste de cada llamada al LLM."""
    assert identity.MAX_CHARS_PER_FILE == 6000
    assert identity.MAX_CHARS_TOTAL == 14000


# ── Caché ───────────────────────────────────────────────────────────

def test_editar_un_documento_tiene_efecto_sin_reiniciar(_isolated_root):
    """Mismo criterio que renombrar al agente: efecto en el turno siguiente."""
    path = _write(_isolated_root, "SOUL.md", "PRIMERA VERSION")
    assert "PRIMERA VERSION" in identity.build_identity_block("O.R.I.O.N")

    # `st_size` distinto garantiza la detección aunque el mtime no cambie de valor.
    with open(path, "w", encoding="utf-8") as f:
        f.write("SEGUNDA VERSION MAS LARGA")

    block = identity.build_identity_block("O.R.I.O.N")
    assert "SEGUNDA VERSION MAS LARGA" in block
    assert "PRIMERA VERSION" not in block


def test_el_disco_no_se_toca_si_el_documento_no_cambio(_isolated_root, monkeypatch):
    _write(_isolated_root, "SOUL.md", "ALMA")
    identity.build_identity_block("O.R.I.O.N")   # primera lectura, llena la caché

    def _no_deberia_abrirse(*args, **kwargs):
        raise AssertionError("se releyó el disco con la caché caliente")

    monkeypatch.setattr("builtins.open", _no_deberia_abrirse)

    assert "ALMA" in identity.build_identity_block("O.R.I.O.N")


# ── Archivos personales: se crean desde la plantilla, nunca se pisan ─

def test_los_personales_se_crean_desde_su_plantilla_al_primer_arranque(_isolated_root):
    _write(_isolated_root, "USER.example.md", "# Perfil\n\n- Nombre: (tu nombre)")
    _write(_isolated_root, "MEMORY.example.md", "# Memoria\n")

    creados = identity.asegurar_archivos_personales()

    assert sorted(creados) == ["MEMORY.md", "USER.md"]
    assert (_isolated_root / "USER.md").read_text(encoding="utf-8").startswith("# Perfil")
    assert (_isolated_root / "MEMORY.md").exists()


def test_un_personal_que_ya_existe_no_se_toca(_isolated_root):
    _write(_isolated_root, "USER.example.md", "PLANTILLA")
    _write(_isolated_root, "USER.md", "MI PERFIL DE VERDAD")
    _write(_isolated_root, "MEMORY.example.md", "PLANTILLA")

    creados = identity.asegurar_archivos_personales()

    assert creados == ["MEMORY.md"]
    assert (_isolated_root / "USER.md").read_text(encoding="utf-8") == "MI PERFIL DE VERDAD"


def test_sin_plantilla_no_se_crea_nada_ni_se_lanza(_isolated_root):
    assert identity.asegurar_archivos_personales() == []
    assert not (_isolated_root / "USER.md").exists()


def test_un_error_al_copiar_no_interrumpe_el_arranque(_isolated_root, monkeypatch):
    _write(_isolated_root, "USER.example.md", "PLANTILLA")

    def _boom(*args, **kwargs):
        raise OSError("disco lleno")

    monkeypatch.setattr(identity.shutil, "copyfile", _boom)

    assert identity.asegurar_archivos_personales() == []


def test_las_plantillas_de_los_personales_viajan_en_el_repositorio():
    """Si falta una plantilla, un equipo recién clonado arranca sin perfil de usuario."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(identity.__file__)))
    for nombre in identity.PERSONAL_FILES:
        base, ext = os.path.splitext(nombre)
        assert os.path.exists(os.path.join(raiz, f"{base}.example{ext}")), nombre
