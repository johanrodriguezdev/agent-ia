"""
tests/test_workspace_config.py
REQ-029/CA-02 — `core/workspace_config.py` es fail-closed.

Un archivo ausente, corrupto, con un JSON que no es una lista, o con una entrada que no
es una carpeta existente, se interpreta SIEMPRE como "sin carpetas habilitadas" — nunca
como "sin restricciones". Es el mismo criterio de REQ-019/CA-06, y acá importa más: el
peor caso de este módulo es la lista vacía, y la lista vacía significa que el agente no
puede tocar ningún archivo de la máquina.

Convenciones (.claude/rules/testing.md): `CODE_WORKSPACES_FILE` se redirige a `tmp_path`
en cada test, así que ninguno lee ni escribe el archivo real del proyecto.
"""

import json
import os

import pytest

import core.workspace_config as workspace_config


@pytest.fixture(autouse=True)
def archivo_aislado(monkeypatch, tmp_path):
    """Redirige CODE_WORKSPACES_FILE a un temporal — nunca toca el archivo real."""
    path = tmp_path / "code_workspaces.json"
    monkeypatch.setattr(workspace_config, "CODE_WORKSPACES_FILE", str(path))
    return path


def _escribir(archivo, contenido) -> None:
    archivo.write_text(json.dumps(contenido), encoding="utf-8")


# ─────────────────────────── fail-closed ───────────────────────────

def test_archivo_inexistente_no_habilita_nada(archivo_aislado):
    """El estado de fábrica: la feature nace inerte, a propósito."""
    assert not archivo_aislado.exists()
    assert workspace_config.cargar_raices() == []


def test_json_corrupto_no_habilita_nada(archivo_aislado):
    archivo_aislado.write_text("{esto no es json", encoding="utf-8")
    assert workspace_config.cargar_raices() == []


def test_bytes_no_utf8_no_crashean_ni_habilitan_nada(archivo_aislado):
    """`UnicodeDecodeError` no es `OSError` ni `JSONDecodeError` — mismo hallazgo que
    REQ-019: archivo truncado a mitad de escritura, el caso de corrupción más realista."""
    archivo_aislado.write_bytes(b"\xff\xfe\x00\x01no-es-utf8")
    assert workspace_config.cargar_raices() == []


@pytest.mark.parametrize("contenido", [42, "una ruta suelta", {"otra_clave": ["x"]}, None])
def test_json_que_no_es_lista_no_habilita_nada(archivo_aislado, contenido):
    _escribir(archivo_aislado, contenido)
    assert workspace_config.cargar_raices() == []


def test_entrada_que_no_es_string_se_descarta_y_el_resto_sobrevive(archivo_aislado, tmp_path):
    valida = tmp_path / "repo"
    valida.mkdir()
    _escribir(archivo_aislado, [123, None, {"ruta": "x"}, str(valida)])
    assert workspace_config.cargar_raices() == [os.path.realpath(str(valida))]


def test_entrada_vacia_se_descarta(archivo_aislado, tmp_path):
    valida = tmp_path / "repo"
    valida.mkdir()
    _escribir(archivo_aislado, ["", "   ", str(valida)])
    assert workspace_config.cargar_raices() == [os.path.realpath(str(valida))]


def test_carpeta_inexistente_se_descarta(archivo_aislado, tmp_path):
    _escribir(archivo_aislado, [str(tmp_path / "no-existe")])
    assert workspace_config.cargar_raices() == []


def test_archivo_en_vez_de_carpeta_se_descarta(archivo_aislado, tmp_path):
    archivo = tmp_path / "algo.txt"
    archivo.write_text("no soy una carpeta", encoding="utf-8")
    _escribir(archivo_aislado, [str(archivo)])
    assert workspace_config.cargar_raices() == []


def test_una_raiz_rota_no_deja_sin_herramientas_a_las_otras(archivo_aislado, tmp_path):
    """Descartar y seguir: una raíz en un disco desconectado no invalida el archivo entero.
    Descartar NUNCA agrega permisos, solo los quita."""
    buena = tmp_path / "repo_bueno"
    buena.mkdir()
    _escribir(archivo_aislado, [str(tmp_path / "disco_desconectado"), str(buena)])
    assert workspace_config.cargar_raices() == [os.path.realpath(str(buena))]


# ─────────────────────────── carga válida ───────────────────────────

def test_raices_validas_vuelven_como_realpath(archivo_aislado, tmp_path):
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    _escribir(archivo_aislado, [str(repo / "sub" / ".." )])
    assert workspace_config.cargar_raices() == [os.path.realpath(str(repo))]


def test_raices_duplicadas_se_deduplican(archivo_aislado, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _escribir(archivo_aislado, [str(repo), str(repo), str(repo) + os.sep])
    assert workspace_config.cargar_raices() == [os.path.realpath(str(repo))]


def test_duplicado_por_mayusculas_se_deduplica_en_windows(archivo_aislado, tmp_path):
    """En Windows el sistema de archivos es case-insensitive: la misma carpeta escrita con
    otra caja es la misma carpeta, y contarla dos veces solo ensucia los mensajes."""
    repo = tmp_path / "Repo"
    repo.mkdir()
    _escribir(archivo_aislado, [str(repo), str(repo).upper()])
    raices = workspace_config.cargar_raices()
    if os.path.normcase("A") == os.path.normcase("a"):
        assert len(raices) == 1
    else:
        assert len(raices) in (1, 2)


def test_forma_objeto_con_clave_raices(archivo_aislado, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _escribir(archivo_aislado, {"raices": [str(repo)]})
    assert workspace_config.cargar_raices() == [os.path.realpath(str(repo))]


# ─────────────────────────── guardado ───────────────────────────

def test_guardar_y_volver_a_cargar(archivo_aislado, tmp_path):
    uno = tmp_path / "uno"
    dos = tmp_path / "dos"
    uno.mkdir()
    dos.mkdir()
    workspace_config.guardar_raices([str(uno), str(dos)])
    assert workspace_config.cargar_raices() == [
        os.path.realpath(str(uno)), os.path.realpath(str(dos)),
    ]


def test_guardar_no_persiste_entradas_invalidas(archivo_aislado, tmp_path):
    """Si se escribiera una entrada inválida, la carga siguiente la descartaría y el
    usuario creería tener habilitada una carpeta que no lo está."""
    valida = tmp_path / "repo"
    valida.mkdir()
    workspace_config.guardar_raices([str(tmp_path / "fantasma"), str(valida), 7])
    assert json.loads(archivo_aislado.read_text(encoding="utf-8")) == [
        os.path.realpath(str(valida))
    ]


def test_guardar_lista_vacia_deja_al_agente_sin_nada(archivo_aislado):
    workspace_config.guardar_raices([])
    assert workspace_config.cargar_raices() == []
