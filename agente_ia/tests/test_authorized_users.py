"""
tests/test_authorized_users.py
Pruebas de `core/authorized_users.py` — control de acceso por identidad en canales remotos.

El invariante que cuida esta suite: **ningún camino puede acabar autorizando a un remitente
remoto que no esté en la lista.** Archivo ausente, corrupto, vacío, con el canal faltante o
con basura dentro: todos deben denegar. Un fallo aquí deja el bot abierto al mundo, y las
acciones verdes (incluida "tomar captura de pantalla") se ejecutan sin confirmación.
"""

import json
import os

import pytest

from core import authorized_users as au


@pytest.fixture(autouse=True)
def _isolated_file(tmp_path, monkeypatch):
    path = str(tmp_path / "authorized_users.json")
    monkeypatch.setattr(au, "AUTHORIZED_USERS_FILE", path)
    au.clear_cache()
    yield path
    au.clear_cache()


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, str):
            f.write(data)
        else:
            json.dump(data, f)


# ── Camino feliz ────────────────────────────────────────────────────

def test_una_identidad_listada_queda_autorizada(_isolated_file):
    _write(_isolated_file, {"telegram": ["1578909994"]})

    assert au.is_authorized("telegram", "1578909994") is True


def test_una_identidad_no_listada_se_deniega(_isolated_file):
    _write(_isolated_file, {"telegram": ["1578909994"]})

    assert au.is_authorized("telegram", "999999") is False


def test_las_identidades_no_se_cruzan_entre_canales(_isolated_file):
    """Estar autorizado en Telegram no autoriza en Discord."""
    _write(_isolated_file, {"telegram": ["111"], "discord": ["222"]})

    assert au.is_authorized("telegram", "111") is True
    assert au.is_authorized("discord", "111") is False
    assert au.is_authorized("telegram", "222") is False
    assert au.is_authorized("discord", "222") is True


def test_los_ids_numericos_del_json_tambien_valen(_isolated_file):
    """Un id sin comillas en el JSON no debe dejar fuera a su dueño."""
    _write(_isolated_file, {"telegram": [1578909994]})

    assert au.is_authorized("telegram", "1578909994") is True


def test_acepta_channeltype_ademas_de_str(_isolated_file):
    from core.security_manager import ChannelType

    _write(_isolated_file, {"telegram": ["111"]})

    assert au.is_authorized(ChannelType.TELEGRAM, "111") is True


# ── Canales locales ─────────────────────────────────────────────────

def test_los_canales_locales_no_se_filtran(_isolated_file):
    """Quien tiene acceso físico al equipo ya tiene acceso al agente.

    Además evita que un archivo mal escrito deje al usuario fuera de su propia aplicación.
    """
    _write(_isolated_file, {"telegram": []})

    assert au.is_authorized("desktop", "default") is True
    assert au.is_authorized("voice", "cualquiera") is True
    assert au.is_authorized("cli", "") is True


def test_los_canales_locales_pasan_incluso_sin_archivo(_isolated_file):
    assert not os.path.exists(_isolated_file)

    assert au.is_authorized("desktop", "default") is True


# ── Fail-closed: lo que de verdad importa ───────────────────────────

def test_sin_archivo_nadie_remoto_pasa(_isolated_file):
    assert not os.path.exists(_isolated_file)

    assert au.is_authorized("telegram", "1578909994") is False
    assert au.is_authorized("discord", "1578909994") is False


def test_un_json_corrupto_no_abre_el_bot(_isolated_file, caplog):
    _write(_isolated_file, "{ esto no es json valido")

    with caplog.at_level("ERROR"):
        assert au.is_authorized("telegram", "1578909994") is False

    assert any("ilegible" in r.message for r in caplog.records)


def test_un_json_que_no_es_objeto_no_abre_el_bot(_isolated_file):
    _write(_isolated_file, ["1578909994"])

    assert au.is_authorized("telegram", "1578909994") is False


def test_lista_vacia_deniega(_isolated_file):
    _write(_isolated_file, {"telegram": []})

    assert au.is_authorized("telegram", "1578909994") is False


def test_canal_ausente_en_el_archivo_deniega(_isolated_file):
    _write(_isolated_file, {"discord": ["222"]})

    assert au.is_authorized("telegram", "1578909994") is False


def test_un_canal_desconocido_deniega(_isolated_file):
    """Fail-closed igual que una acción sin clasificar en REQ-005."""
    _write(_isolated_file, {"telegram": ["111"]})

    assert au.is_authorized("canal_inventado", "111") is False


def test_identidad_vacia_o_nula_deniega(_isolated_file):
    """Un update sin remitente identificable no puede colarse."""
    _write(_isolated_file, {"telegram": ["111"]})

    assert au.is_authorized("telegram", "") is False
    assert au.is_authorized("telegram", "   ") is False
    assert au.is_authorized("telegram", None) is False


def test_un_valor_no_lista_se_ignora_sin_arrastrar_al_resto(_isolated_file):
    """Un error de tecleo en un canal no debe dejar al otro sin autorizados."""
    _write(_isolated_file, {"telegram": ["111"], "discord": "no-es-una-lista"})

    assert au.is_authorized("telegram", "111") is True
    assert au.is_authorized("discord", "no-es-una-lista") is False


def test_las_claves_de_comentario_se_ignoran_en_silencio(_isolated_file, caplog):
    _write(_isolated_file, {"_comentario": "texto de ayuda", "telegram": ["111"]})

    with caplog.at_level("WARNING"):
        assert au.is_authorized("telegram", "111") is True

    assert not any("_comentario" in r.message for r in caplog.records)


# ── Recarga ─────────────────────────────────────────────────────────

def test_autorizar_a_alguien_no_exige_reiniciar(_isolated_file):
    _write(_isolated_file, {"telegram": ["111"]})
    assert au.is_authorized("telegram", "222") is False

    _write(_isolated_file, {"telegram": ["111", "222"]})

    assert au.is_authorized("telegram", "222") is True


def test_revocar_a_alguien_tiene_efecto_inmediato(_isolated_file):
    _write(_isolated_file, {"telegram": ["111", "222"]})
    assert au.is_authorized("telegram", "222") is True

    _write(_isolated_file, {"telegram": ["111"]})

    assert au.is_authorized("telegram", "222") is False


def test_borrar_el_archivo_cierra_el_bot(_isolated_file):
    """El fail-closed también aplica a la caché ya caliente."""
    _write(_isolated_file, {"telegram": ["111"]})
    assert au.is_authorized("telegram", "111") is True

    os.unlink(_isolated_file)

    assert au.is_authorized("telegram", "111") is False


def test_list_authorized_devuelve_lo_configurado(_isolated_file):
    _write(_isolated_file, {"telegram": ["222", "111"]})

    assert au.list_authorized("telegram") == ["111", "222"]
    assert au.list_authorized("discord") == []
