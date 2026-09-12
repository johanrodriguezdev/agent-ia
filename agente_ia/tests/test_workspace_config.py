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


# ─────────────────────────── REQ-030: habilitar por instrucción ───────────────────────────
# El agente no puede darse permisos solos: `workspace_add_folder` es 🟡 y solo de escritorio
# (eso se fija en test_workspace_tools_seguridad.py). Acá se fija la otra mitad — QUÉ carpetas
# no se habilitan aunque el humano confirme el modal distraído.

def _instalacion() -> str:
    """La carpeta de O.R.I.O.N., derivada del módulo y no escrita a mano."""
    return os.path.dirname(os.path.dirname(os.path.abspath(workspace_config.__file__)))


def test_agregar_una_carpeta_la_habilita_y_la_persiste(tmp_path):
    proyecto = tmp_path / "mi-repo"
    proyecto.mkdir()

    real = workspace_config.agregar_raiz(str(proyecto))

    assert workspace_config.cargar_raices() == [real]


def test_agregar_la_misma_carpeta_dos_veces_no_duplica(tmp_path):
    """Pedir de nuevo lo que ya está no puede fallar ni dejar la lista con dos entradas: el
    usuario diría "trabajá sobre este repo" otra vez sin acordarse."""
    proyecto = tmp_path / "mi-repo"
    proyecto.mkdir()

    primero = workspace_config.agregar_raiz(str(proyecto))
    segundo = workspace_config.agregar_raiz(str(proyecto))

    assert primero == segundo
    assert workspace_config.cargar_raices() == [primero]


def test_no_se_habilita_la_raiz_de_un_disco(tmp_path):
    raiz = os.path.abspath(os.sep)
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.agregar_raiz(raiz)
    assert workspace_config.cargar_raices() == []


def test_no_se_habilita_una_carpeta_del_sistema():
    windir = os.environ.get("WINDIR")
    if not windir or not os.path.isdir(windir):
        pytest.skip("sin carpeta de Windows en este sistema")
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.agregar_raiz(windir)


def test_no_se_habilita_la_carpeta_personal_entera():
    """Adentro están `.ssh`, `.aws` y los perfiles del navegador: habilitarla es casi tan
    amplio como habilitar el disco."""
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.agregar_raiz(os.path.expanduser("~"))


def test_una_carpeta_dentro_de_la_personal_si_se_habilita(tmp_path):
    """La contracara: lo que se bloquea es la carpeta personal EN SÍ, no todo lo que hay
    dentro. `Documentos/repos` tiene que poder habilitarse."""
    proyecto = tmp_path / "documentos" / "repos" / "proyecto"
    proyecto.mkdir(parents=True)

    assert workspace_config.agregar_raiz(str(proyecto))


def test_no_se_habilita_el_codigo_del_propio_agente():
    """`modify_source_code` es 🔴 y lo sigue siendo: no se puede llegar a él por la puerta
    de atrás de habilitar su carpeta como espacio de trabajo."""
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.agregar_raiz(_instalacion())


def test_no_se_habilita_una_subcarpeta_del_codigo_del_agente():
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.agregar_raiz(os.path.join(_instalacion(), "core"))


def test_no_se_habilita_una_carpeta_que_no_existe(tmp_path):
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.agregar_raiz(str(tmp_path / "no-existe"))


def test_una_carpeta_rechazada_no_queda_escrita(tmp_path, archivo_aislado):
    """Lo importante no es solo que levante: es que no deje rastro. Una raíz rechazada que
    igual se persistiera quedaría habilitada en el próximo arranque."""
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.agregar_raiz(os.path.abspath(os.sep))

    assert not archivo_aislado.exists()
    assert workspace_config.cargar_raices() == []


def test_quitar_una_carpeta_la_deshabilita(tmp_path):
    proyecto = tmp_path / "mi-repo"
    proyecto.mkdir()
    real = workspace_config.agregar_raiz(str(proyecto))

    quitada = workspace_config.quitar_raiz(str(proyecto))

    assert quitada == real, "tiene que devolver la ruta como estaba guardada, no en minúsculas"
    assert workspace_config.cargar_raices() == []


def test_quitar_una_que_no_estaba_avisa_en_vez_de_decir_listo(tmp_path):
    """Decirle "listo" a alguien que se equivocó de carpeta le haría creer que cerró un
    acceso que sigue abierto."""
    with pytest.raises(workspace_config.RaizRechazada):
        workspace_config.quitar_raiz(str(tmp_path / "nunca-estuvo"))


def test_quitar_una_no_toca_las_demas(tmp_path):
    uno = tmp_path / "repo-uno"
    dos = tmp_path / "repo-dos"
    uno.mkdir()
    dos.mkdir()
    workspace_config.agregar_raiz(str(uno))
    real_dos = workspace_config.agregar_raiz(str(dos))

    workspace_config.quitar_raiz(str(uno))

    assert workspace_config.cargar_raices() == [real_dos]
