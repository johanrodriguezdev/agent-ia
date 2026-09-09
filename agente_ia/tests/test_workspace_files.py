"""
tests/test_workspace_files.py
REQ-029/CA-01, CA-03, CA-04, CA-10, CA-11, CA-12 — el confinamiento y las operaciones.

`resolver()` es la única función que convierte una ruta pedida por el modelo en una ruta
real. Si tiene un agujero, las 8 herramientas son acceso libre al disco, así que se prueba
contra los cuatro escapes de verdad: ruta absoluta fuera de toda raíz, `..` que se sale,
prefijo de string engañoso, y un ENLACE REAL del sistema de archivos cuyo destino cae
afuera.

Convenciones (.claude/rules/testing.md): todo ocurre dentro de `tmp_path` —incluido el
enlace, que apunta a otra carpeta del mismo `tmp_path`, nunca a una ruta real del disco—
y `CODE_WORKSPACES_FILE` se redirige a un temporal para que ninguna llamada que no reciba
raíces explícitas pueda leer el archivo real del proyecto.
"""

import os
import subprocess
import sys

import pytest

import core.workspace_config as workspace_config
import core.workspace_files as wf
from core.workspace_files import RutaFueraDeRaiz


@pytest.fixture(autouse=True)
def sin_configuracion_real(monkeypatch, tmp_path):
    """Ningún test puede leer el `code_workspaces.json` real del proyecto."""
    monkeypatch.setattr(
        workspace_config, "CODE_WORKSPACES_FILE", str(tmp_path / "code_workspaces.json")
    )


@pytest.fixture
def repo(tmp_path):
    """Una raíz habilitada con algo adentro, y una carpeta hermana que está AFUERA."""
    raiz = tmp_path / "repo"
    (raiz / "src").mkdir(parents=True)
    (raiz / "src" / "main.py").write_text("print('hola')\n", encoding="utf-8")
    afuera = tmp_path / "privado"
    afuera.mkdir()
    (afuera / "secreto.txt").write_text("clave-del-banco", encoding="utf-8")
    return os.path.realpath(str(raiz))


@pytest.fixture
def raices(repo):
    return [repo]


def _crear_enlace(destino: str, enlace: str) -> bool:
    """Crea un enlace REAL del sistema de archivos, o devuelve False si no se puede.

    En Windows `os.symlink` exige un privilegio que una sesión normal no tiene, pero una
    unión de directorio (`mklink /J`) sí se puede crear sin permisos especiales y es
    exactamente el mismo vector: un punto de reanálisis dentro de la raíz cuyo destino
    real está afuera, que `os.path.realpath` resuelve igual que a un symlink. Se usa
    `subprocess` solo para FABRICAR el escenario dentro de `tmp_path`; el código bajo
    prueba no ejecuta nada.
    """
    try:
        os.symlink(destino, enlace, target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        pass
    if sys.platform != "win32":
        return False
    try:
        proceso = subprocess.run(
            ["cmd", "/c", "mklink", "/J", enlace, destino],
            capture_output=True, text=True, shell=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proceso.returncode == 0 and os.path.exists(enlace)


# ─────────────────────────── CA-01/CA-04: confinamiento ───────────────────────────

def test_ruta_dentro_de_la_raiz_se_resuelve(repo, raices):
    esperado = os.path.realpath(os.path.join(repo, "src", "main.py"))
    assert wf.resolver(os.path.join(repo, "src", "main.py"), raices) == esperado


def test_ruta_relativa_se_resuelve_contra_la_raiz_no_contra_el_cwd(repo, raices):
    """El directorio de trabajo del proceso es el de O.R.I.O.N. y no tiene nada que ver
    con el repo del usuario: una ruta relativa jamás debe interpretarse contra él."""
    esperado = os.path.realpath(os.path.join(repo, "src", "main.py"))
    assert wf.resolver("src/main.py", raices) == esperado


def test_ruta_absoluta_fuera_de_toda_raiz_se_rechaza(tmp_path, raices):
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(str(tmp_path / "privado" / "secreto.txt"), raices)


def test_dos_puntos_que_se_escapa_se_rechaza(repo, raices):
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(os.path.join(repo, "..", "privado", "secreto.txt"), raices)


def test_dos_puntos_que_no_se_escapa_se_acepta(repo, raices):
    """`..` no es una palabra prohibida: lo que se rechaza es salir, no el token."""
    esperado = os.path.realpath(os.path.join(repo, "src", "main.py"))
    assert wf.resolver(os.path.join(repo, "src", "..", "src", "main.py"), raices) == esperado


def test_prefijo_de_string_enganoso_se_rechaza(tmp_path):
    """CA-04 — el escape que `startswith` deja pasar: `/home/proyecto-malo` NO está dentro
    de `/home/proyecto`, aunque su ruta empiece igual. `commonpath` compara por segmentos."""
    bueno = tmp_path / "proyecto"
    malo = tmp_path / "proyecto-malo"
    bueno.mkdir()
    malo.mkdir()
    (malo / "robado.txt").write_text("x", encoding="utf-8")
    raices = [os.path.realpath(str(bueno))]

    assert str(malo).startswith(str(bueno))  # el escape que se está cerrando
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(str(malo / "robado.txt"), raices)


def test_symlink_real_que_apunta_afuera_se_rechaza(tmp_path, repo, raices):
    """CA-01 — el escape que solo se cierra resolviendo con `realpath` ANTES de comparar.
    El enlace VIVE dentro de la raíz habilitada; su destino real, no."""
    afuera = str(tmp_path / "privado")
    enlace = os.path.join(repo, "escape")
    if not _crear_enlace(afuera, enlace):
        pytest.skip("este sistema no permite crear enlaces de directorio sin privilegios")

    assert os.path.exists(os.path.join(enlace, "secreto.txt"))  # el enlace funciona
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(os.path.join(enlace, "secreto.txt"), raices)


def test_symlink_real_que_apunta_adentro_se_acepta(tmp_path, repo, raices):
    """La contracara: un enlace cuyo destino cae dentro de la raíz no se rechaza. El
    control es sobre dónde termina la ruta, no sobre si hay un enlace en el medio."""
    enlace = os.path.join(repo, "atajo")
    if not _crear_enlace(os.path.join(repo, "src"), enlace):
        pytest.skip("este sistema no permite crear enlaces de directorio sin privilegios")

    esperado = os.path.realpath(os.path.join(repo, "src", "main.py"))
    assert wf.resolver(os.path.join(enlace, "main.py"), raices) == esperado


def test_sin_raices_no_se_resuelve_nada(repo):
    """CA-02 aplicado al resolver: sin carpetas habilitadas no hay ruta válida, ni
    siquiera una que existiría. Fail-closed, nunca 'sin restricciones'."""
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(os.path.join(repo, "src", "main.py"), [])


def test_ruta_vacia_se_rechaza(raices):
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver("", raices)
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver("   ", raices)


def test_la_raiz_misma_es_valida(repo, raices):
    assert wf.resolver(repo, raices) == repo


def test_comparacion_case_insensitive_en_windows(repo, raices):
    """En Windows la misma carpeta escrita en otra caja ES la misma carpeta, y
    `commonpath` no lo sabe por su cuenta: por eso los dos lados pasan por `normcase`."""
    if os.path.normcase("A") != os.path.normcase("a"):
        pytest.skip("sistema de archivos case-sensitive")
    pedida = os.path.join(repo.upper(), "src", "main.py")
    assert wf.resolver(pedida, raices) == os.path.realpath(pedida)


def test_otra_unidad_no_esta_dentro(raices):
    """Rutas en unidades distintas hacen que `commonpath` levante `ValueError`; la duda se
    resuelve del lado restrictivo."""
    if sys.platform != "win32":
        pytest.skip("solo aplica a Windows, que tiene unidades")
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver("Z:\\lo-que-sea\\archivo.txt", raices)


# ─────────────────────────── CA-03: el código de O.R.I.O.N. ───────────────────────────

def test_instalacion_de_orion_se_rechaza_aunque_este_habilitada(monkeypatch, tmp_path):
    """CA-03 — el bloqueo vive en CÓDIGO, no en la configuración: agregar la carpeta de
    instalación como raíz habilitada no alcanza para tocarla. Mismo criterio con que
    `_merge_with_override()` (REQ-019) bloquea bajar un RED editando el JSON a mano."""
    falsa_instalacion = tmp_path / "orion"
    (falsa_instalacion / "core").mkdir(parents=True)
    (falsa_instalacion / "main.py").write_text("# soy O.R.I.O.N.\n", encoding="utf-8")
    monkeypatch.setattr(wf, "_INSTALACION", str(falsa_instalacion))

    raices = [os.path.realpath(str(falsa_instalacion))]  # habilitada a propósito
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(str(falsa_instalacion / "main.py"), raices)
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(str(falsa_instalacion / "core" / "security_manager.py"), raices)


def test_instalacion_real_se_rechaza_aunque_este_habilitada():
    """El mismo control, contra la ruta de instalación REAL. No abre, no lee y no escribe
    ningún archivo: `resolver()` rechaza antes de tocar el disco, que es justo su
    contrato."""
    instalacion = os.path.realpath(wf._INSTALACION)
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(os.path.join(instalacion, "main.py"), [instalacion])
    with pytest.raises(RutaFueraDeRaiz):
        wf.resolver(os.path.join(instalacion, "core", "security_manager.py"), [instalacion])


def test_el_rechazo_de_la_instalacion_se_loguea_como_critical(monkeypatch, tmp_path, caplog):
    falsa = tmp_path / "orion"
    falsa.mkdir()
    monkeypatch.setattr(wf, "_INSTALACION", str(falsa))
    with caplog.at_level("CRITICAL"):
        with pytest.raises(RutaFueraDeRaiz):
            wf.resolver(str(falsa / "main.py"), [os.path.realpath(str(falsa))])
    assert any(r.levelname == "CRITICAL" for r in caplog.records)


def test_una_carpeta_hermana_de_la_instalacion_no_se_bloquea(monkeypatch, tmp_path):
    """El bloqueo es por segmentos también acá: `orion-docs` no es `orion`."""
    falsa = tmp_path / "orion"
    hermana = tmp_path / "orion-docs"
    falsa.mkdir()
    hermana.mkdir()
    (hermana / "notas.md").write_text("nada secreto", encoding="utf-8")
    monkeypatch.setattr(wf, "_INSTALACION", str(falsa))

    raices = [os.path.realpath(str(hermana))]
    assert wf.resolver(str(hermana / "notas.md"), raices)


# ─────────────────────────── CA-10: leer ───────────────────────────

def test_leer_devuelve_el_contenido_numerado(repo, raices):
    salida = wf.leer("src/main.py", raices=raices)
    assert "print('hola')" in salida
    assert "1\t" in salida


def test_leer_acepta_rango_de_lineas(repo, raices):
    ruta = os.path.join(repo, "largo.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(f"linea {i}" for i in range(1, 51)))

    salida = wf.leer("largo.txt", desde=10, hasta=12, raices=raices)
    assert "linea 10" in salida and "linea 12" in salida
    assert "linea 9" not in salida and "linea 13" not in salida


def test_leer_trunca_avisando_y_diciendo_en_que_linea(monkeypatch, repo, raices):
    """CA-10 — nunca revienta el turno ni se corta en silencio: dice que truncó, en qué
    línea, y cómo pedir el pedazo siguiente."""
    monkeypatch.setattr(wf, "_MAX_LINEAS", 5)
    ruta = os.path.join(repo, "enorme.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("\n".join(f"linea {i}" for i in range(1, 101)))

    salida = wf.leer("enorme.txt", raices=raices)
    assert "TRUNCADO" in salida
    assert "línea 5 de 100" in salida
    assert "desde=6" in salida
    assert "linea 6" not in salida


def test_leer_archivo_demasiado_grande_no_lo_abre(monkeypatch, repo, raices):
    monkeypatch.setattr(wf, "_MAX_BYTES_ARCHIVO", 10)
    ruta = os.path.join(repo, "pesado.txt")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("x" * 500)

    salida = wf.leer("pesado.txt", raices=raices)
    assert "demasiado grande" in salida
    assert "file_search" in salida


def test_leer_archivo_inexistente_explica_sin_stacktrace(repo, raices):
    salida = wf.leer("no-existe.txt", raices=raices)
    assert "No existe" in salida
    assert "Traceback" not in salida


def test_leer_una_carpeta_sugiere_file_list(repo, raices):
    assert "file_list" in wf.leer("src", raices=raices)


def test_leer_binario_no_lo_vuelca(repo, raices):
    ruta = os.path.join(repo, "imagen.bin")
    with open(ruta, "wb") as f:
        f.write(b"\x89PNG\x00\x00\x00binario")
    assert "binario" in wf.leer("imagen.bin", raices=raices)


def test_leer_fuera_de_la_raiz_levanta_y_no_lee(tmp_path, raices):
    with pytest.raises(RutaFueraDeRaiz):
        wf.leer(str(tmp_path / "privado" / "secreto.txt"), raices=raices)


def test_leer_archivo_vacio_no_falla(repo, raices):
    open(os.path.join(repo, "vacio.txt"), "w", encoding="utf-8").close()
    assert "0 líneas" in wf.leer("vacio.txt", raices=raices)


# ─────────────────────────── CA-12: escribir ───────────────────────────

def test_escribir_crea_el_archivo(repo, raices):
    salida = wf.escribir("nuevo.txt", "contenido nuevo", raices=raices)
    assert "Creé" in salida
    with open(os.path.join(repo, "nuevo.txt"), encoding="utf-8") as f:
        assert f.read() == "contenido nuevo"


def test_escribir_crea_los_directorios_intermedios_dentro_de_la_raiz(repo, raices):
    wf.escribir("a/b/c/hondo.txt", "hola", raices=raices)
    assert os.path.isfile(os.path.join(repo, "a", "b", "c", "hondo.txt"))


def test_escribir_fuera_de_la_raiz_no_crea_nada(tmp_path, raices):
    objetivo = tmp_path / "privado" / "plantado" / "malo.txt"
    with pytest.raises(RutaFueraDeRaiz):
        wf.escribir(str(objetivo), "no deberia existir", raices=raices)
    assert not objetivo.exists()
    assert not objetivo.parent.exists()  # CA-12: tampoco crea las carpetas


def test_escribir_reescribe_un_archivo_existente(repo, raices):
    salida = wf.escribir("src/main.py", "print('otra cosa')\n", raices=raices)
    assert "Reescribí" in salida
    with open(os.path.join(repo, "src", "main.py"), encoding="utf-8") as f:
        assert f.read() == "print('otra cosa')\n"


def test_escribir_sobre_una_carpeta_no_la_destruye(repo, raices):
    salida = wf.escribir("src", "texto", raices=raices)
    assert "carpeta" in salida
    assert os.path.isdir(os.path.join(repo, "src"))


# ─────────────────────────── CA-11: editar ───────────────────────────

def test_editar_reemplaza_la_coincidencia_unica(repo, raices):
    salida = wf.editar("src/main.py", "hola", "chau", raices=raices)
    assert "Edité" in salida
    with open(os.path.join(repo, "src", "main.py"), encoding="utf-8") as f:
        assert f.read() == "print('chau')\n"


def test_editar_sin_coincidencias_no_escribe_y_lo_dice(repo, raices):
    antes = open(os.path.join(repo, "src", "main.py"), encoding="utf-8").read()
    salida = wf.editar("src/main.py", "texto que no está", "x", raices=raices)
    assert "No encontré" in salida
    assert open(os.path.join(repo, "src", "main.py"), encoding="utf-8").read() == antes


def test_editar_con_varias_coincidencias_no_escribe_y_dice_cuantas(repo, raices):
    ruta = os.path.join(repo, "repetido.py")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("x = 1\ny = 1\nz = 1\n")

    salida = wf.editar("repetido.py", "= 1", "= 2", raices=raices)
    assert "3 veces" in salida
    assert open(ruta, encoding="utf-8").read() == "x = 1\ny = 1\nz = 1\n"


def test_los_dos_fallos_de_editar_se_distinguen(repo, raices):
    """CA-11 — con 0 y con más de 1 no escribe, pero explica CUÁL de los dos casos fue."""
    ruta = os.path.join(repo, "repetido.py")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("a\na\n")
    cero = wf.editar("repetido.py", "zzz", "x", raices=raices)
    varias = wf.editar("repetido.py", "a", "b", raices=raices)
    assert cero != varias
    assert "No encontré" in cero and "2 veces" in varias


def test_editar_archivo_inexistente_sugiere_file_write(repo, raices):
    assert "file_write" in wf.editar("no-existe.py", "a", "b", raices=raices)


def test_editar_fuera_de_la_raiz_levanta(tmp_path, raices):
    with pytest.raises(RutaFueraDeRaiz):
        wf.editar(str(tmp_path / "privado" / "secreto.txt"), "clave", "x", raices=raices)


def test_editar_sin_fragmento_no_hace_nada(repo, raices):
    assert "fragmento" in wf.editar("src/main.py", "", "x", raices=raices)


# ─────────────────────────── listar y buscar ───────────────────────────

def test_listar_sin_ruta_muestra_las_raices_habilitadas(repo, raices):
    salida = wf.listar("", raices=raices)
    assert repo in salida


def test_listar_sin_raices_lo_explica(repo):
    salida = wf.listar("", raices=[])
    assert "code_workspaces.json" in salida


def test_listar_muestra_carpetas_y_archivos(repo, raices):
    salida = wf.listar(".", raices=raices)
    assert "src/" in salida


def test_listar_fuera_de_la_raiz_levanta(tmp_path, raices):
    with pytest.raises(RutaFueraDeRaiz):
        wf.listar(str(tmp_path / "privado"), raices=raices)


def test_buscar_devuelve_archivo_y_linea(repo, raices):
    salida = wf.buscar("hola", raices=raices)
    assert "main.py" in salida
    assert ":1:" in salida


def test_buscar_sin_coincidencias_lo_dice(repo, raices):
    assert "No encontré" in wf.buscar("cadena-que-no-existe-en-ningun-lado", raices=raices)


def test_buscar_no_sale_de_la_raiz(tmp_path, repo, raices):
    """El secreto está en `tmp_path`, no dentro de la raíz: la búsqueda no puede verlo."""
    salida = wf.buscar("clave-del-banco", raices=raices)
    assert "No encontré" in salida


def test_buscar_ignora_las_carpetas_de_ruido(repo, raices):
    ruidosa = os.path.join(repo, "node_modules", "paquete")
    os.makedirs(ruidosa)
    with open(os.path.join(ruidosa, "index.js"), "w", encoding="utf-8") as f:
        f.write("marcador-unico\n")
    assert "No encontré" in wf.buscar("marcador-unico", raices=raices)


def test_buscar_no_es_una_expresion_regular(repo, raices):
    """El patrón se busca literal: una expresión que llega del modelo podría colgar el
    proceso con backtracking exponencial."""
    with open(os.path.join(repo, "regex.txt"), "w", encoding="utf-8") as f:
        f.write("esto tiene un .* literal\n")
    assert "regex.txt" in wf.buscar(".*", raices=raices)


def test_buscar_respeta_el_tope_de_resultados(repo, raices):
    with open(os.path.join(repo, "muchos.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join("repetido" for _ in range(50)))
    salida = wf.buscar("repetido", raices=raices, max_resultados=5)
    assert salida.count("muchos.txt") == 5
    assert "recortada" in salida


# ───────────── CA-01 aplicado al RECORRIDO (hallazgo de la auditoría de REQ-029) ─────────────
# `resolver()` protege la ruta que pide el modelo. `buscar()` recorre carpetas y visita
# rutas que nadie pidió, así que necesita su propia barrera: sin ella devolvía el contenido
# de archivos de afuera de la raíz. En Windows el vector no es exótico — `os.walk()` no
# desciende por symlinks, pero una junction NO es un symlink para Python, y el recorrido
# entraba igual. Encontrado con una junction real, no en teoría.

def test_buscar_no_se_lleva_contenido_de_afuera_por_un_enlace(tmp_path, repo, raices):
    afuera = tmp_path / "privado_de_buscar"
    afuera.mkdir()
    (afuera / "secreto.txt").write_text("MARCA_DE_AFUERA\n", encoding="utf-8")
    with open(os.path.join(repo, "adentro.txt"), "w", encoding="utf-8") as f:
        f.write("MARCA_DE_ADENTRO\n")

    enlace = os.path.join(repo, "atajo")
    if not _crear_enlace(str(afuera), enlace):
        pytest.skip("este sistema no permite crear enlaces de directorio sin privilegios")
    assert os.path.exists(os.path.join(enlace, "secreto.txt"))  # el enlace funciona

    salida = wf.buscar("MARCA_DE", raices=raices)

    assert "MARCA_DE_ADENTRO" in salida, "lo de adentro tiene que seguir apareciendo"
    assert "MARCA_DE_AFUERA" not in salida, "fuga: el recorrido salió de la raíz"


def test_buscar_sigue_entrando_por_un_enlace_que_apunta_adentro(tmp_path, repo, raices):
    """La contracara, para que el arreglo no se convierta en "no seguir ningún enlace":
    lo que se corta es salir de la raíz, no que haya un enlace en el camino."""
    destino = os.path.join(repo, "src")
    with open(os.path.join(destino, "buscable.txt"), "w", encoding="utf-8") as f:
        f.write("MARCA_INTERNA\n")

    enlace = os.path.join(repo, "atajo_interno")
    if not _crear_enlace(destino, enlace):
        pytest.skip("este sistema no permite crear enlaces de directorio sin privilegios")

    assert "MARCA_INTERNA" in wf.buscar("MARCA_INTERNA", raices=raices)


# ───────── REQ-030: la búsqueda no abre archivos de credenciales (hallazgo C) ─────────
# Leer un archivo significa mandarlo al proveedor del modelo. Que una clave privada aparezca
# sola porque alguien buscó una palabra que estaba adentro no es la decisión de nadie.

def test_la_busqueda_no_lee_archivos_de_credenciales(repo, raices):
    aguja = "CADENA_BUSCADA_REQ030"
    with open(os.path.join(repo, "codigo.py"), "w", encoding="utf-8") as f:
        f.write(f"variable = '{aguja}'\n")
    for secreto in (".env", "id_rsa", "clave.pem"):
        with open(os.path.join(repo, secreto), "w", encoding="utf-8") as f:
            f.write(f"{aguja}=valor-que-no-debe-salir\n")

    salida = wf.buscar(aguja, raices=raices)

    assert "codigo.py" in salida, "lo normal se sigue encontrando"
    assert "valor-que-no-debe-salir" not in salida
    for secreto in (".env", "id_rsa", "clave.pem"):
        assert f"{secreto}:" not in salida


def test_la_busqueda_avisa_cuantos_secretos_salteo(repo, raices):
    """Saltearlos en silencio dejaría al modelo concluyendo que el dato no existe."""
    aguja = "OTRA_CADENA_REQ030"
    with open(os.path.join(repo, ".env"), "w", encoding="utf-8") as f:
        f.write(f"{aguja}=x\n")

    salida = wf.buscar(aguja, raices=raices)

    assert "credenciales" in salida


def test_file_read_si_lee_un_secreto_si_se_lo_piden_por_su_nombre(repo, raices):
    """Pedir `.env` por su nombre SÍ es una decisión de alguien. Lo que se corta es que
    aparezca solo en una búsqueda amplia."""
    with open(os.path.join(repo, ".env"), "w", encoding="utf-8") as f:
        f.write("CLAVE=valor\n")

    assert "CLAVE=valor" in wf.leer(".env", raices=raices)
