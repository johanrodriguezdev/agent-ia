"""
tests/test_user_identity.py
Pruebas de `core/user_identity.py` — identidad canónica del dueño entre canales.

El invariante crítico: **una identidad no autorizada nunca puede resolver a
`OWNER_USER_ID`.** Si eso fallara, un desconocido leería y escribiría en la memoria
personal del dueño.
"""

import json

import pytest

from core import authorized_users as au
from core import user_identity as ui


@pytest.fixture(autouse=True)
def _isolated_file(tmp_path, monkeypatch):
    path = str(tmp_path / "authorized_users.json")
    monkeypatch.setattr(au, "AUTHORIZED_USERS_FILE", path)
    au.clear_cache()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"telegram": ["1578909994"], "discord": ["555"]}, f)
    yield path
    au.clear_cache()


# ── Convergencia: el punto de todo el módulo ────────────────────────

def test_los_tres_canales_del_dueno_convergen_en_un_usuario():
    """Lo que le cuentas por voz y lo que le escribes por Telegram van al mismo sitio."""
    assert ui.canonical_user_id("desktop", "default") == ui.OWNER_USER_ID
    assert ui.canonical_user_id("voice", "cualquiera") == ui.OWNER_USER_ID
    assert ui.canonical_user_id("telegram", "1578909994") == ui.OWNER_USER_ID
    assert ui.canonical_user_id("discord", "555") == ui.OWNER_USER_ID


def test_is_owner_coincide_con_la_resolucion():
    assert ui.is_owner("telegram", "1578909994") is True
    assert ui.is_owner("telegram", "999999") is False


# ── Aislamiento: lo que no puede fallar ─────────────────────────────

def test_un_desconocido_nunca_resuelve_al_dueno():
    resuelto = ui.canonical_user_id("telegram", "999999")

    assert resuelto != ui.OWNER_USER_ID
    assert resuelto == "999999"


def test_un_desconocido_de_discord_tampoco():
    assert ui.canonical_user_id("discord", "111") != ui.OWNER_USER_ID


def test_identidad_vacia_no_cae_en_el_dueno():
    """Sin identidad, una clave inerte antes que heredar la memoria del dueño."""
    for vacio in ("", "   ", None):
        assert ui.canonical_user_id("telegram", vacio) == "desconocido"


def test_un_canal_desconocido_no_resuelve_al_dueno():
    assert ui.canonical_user_id("canal_inventado", "1578909994") != ui.OWNER_USER_ID


def test_sin_archivo_de_autorizados_nadie_remoto_es_el_dueno(_isolated_file):
    import os

    os.unlink(_isolated_file)
    au.clear_cache()

    assert ui.canonical_user_id("telegram", "1578909994") != ui.OWNER_USER_ID
    # Los locales siguen siendo el dueño: no dejar a Johan fuera de su propia app.
    assert ui.canonical_user_id("desktop", "default") == ui.OWNER_USER_ID


def test_revocar_una_identidad_la_saca_del_dueno(_isolated_file):
    assert ui.canonical_user_id("telegram", "1578909994") == ui.OWNER_USER_ID

    with open(_isolated_file, "w", encoding="utf-8") as f:
        json.dump({"telegram": []}, f)

    assert ui.canonical_user_id("telegram", "1578909994") != ui.OWNER_USER_ID


# ── Identificadores históricos para la migración ────────────────────

def test_owner_legacy_ids_reune_los_identificadores_antiguos():
    legacy = ui.owner_legacy_ids({"telegram": ["1578909994"], "discord": ["555"]})

    assert "1578909994" in legacy
    assert "555" in legacy
    assert ui.LEGACY_DESKTOP_USER_ID in legacy


def test_owner_legacy_ids_ignora_los_canales_locales():
    legacy = ui.owner_legacy_ids({"telegram": ["111"], "desktop": ["no-deberia-entrar"]})

    assert "no-deberia-entrar" not in legacy
    assert "111" in legacy


def test_owner_legacy_ids_tolera_entradas_vacias():
    legacy = ui.owner_legacy_ids({"telegram": ["111", "", "   "]})

    assert legacy == {"111", ui.LEGACY_DESKTOP_USER_ID}


def test_owner_legacy_ids_sin_argumento_devuelve_al_menos_el_escritorio():
    assert ui.owner_legacy_ids({}) == {ui.LEGACY_DESKTOP_USER_ID}
    assert ui.owner_legacy_ids(None) == {ui.LEGACY_DESKTOP_USER_ID}
