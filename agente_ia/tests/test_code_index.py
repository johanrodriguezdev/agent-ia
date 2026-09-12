"""
tests/test_code_index.py
REQ-034 — `core/code_index.py`: el índice semántico de código.

Ningún test carga el modelo de embeddings real: se inyecta un embebedor de bolsa de
palabras, que es determinista y da similitud de verdad (no vectores al azar), así que los
tests de búsqueda comprueban ranking real y no "no explotó".

La base de datos se redirige a `tmp_path` en todos los casos: nunca se toca el
`code_index.db` del proyecto.
"""

import os

import pytest

import core.code_index as ci

#: Vocabulario del embebedor de prueba. Alcanza para que "factura" se parezca a un módulo de
#: facturación y no a uno de autenticación, que es lo único que hace falta comprobar acá.
VOCABULARIO = [
    "factura", "cliente", "pago", "usuario", "login", "token", "correo", "reporte",
    "billing", "invoice", "auth", "mail", "config", "base", "datos",
]


def embebedor(textos):
    """Bolsa de palabras: determinista, sin red y sin modelo."""
    return [
        [float(texto.lower().count(palabra)) for palabra in VOCABULARIO] + [1.0]
        for texto in textos
    ]


@pytest.fixture(autouse=True)
def base_aislada(monkeypatch, tmp_path):
    monkeypatch.setattr(ci, "DB_PATH", str(tmp_path / "code_index.db"))
    ci._invalidar_cache()
    yield
    ci._invalidar_cache()


@pytest.fixture
def repo(tmp_path):
    carpeta = tmp_path / "repo"
    (carpeta / "src").mkdir(parents=True)
    (carpeta / "src" / "billing.py").write_text(
        '"""Modulo de facturacion."""\n\n\n'
        'def crear_invoice(cliente, monto):\n'
        '    """Crea una factura para un cliente."""\n'
        '    return {"cliente": cliente}\n\n\n'
        'class GestorDeFacturas:\n'
        '    def emitir(self, invoice):\n'
        '        return invoice\n',
        encoding="utf-8",
    )
    (carpeta / "src" / "auth.py").write_text(
        'def validar_token(token):\n'
        '    """Valida el token de login del usuario."""\n'
        '    return bool(token)\n',
        encoding="utf-8",
    )
    return str(carpeta)


# ─────────────────────────── troceado ───────────────────────────

def test_python_se_trocea_por_funciones_y_clases():
    """Un fragmento que es una función entera se puede buscar por lo que HACE. Uno que
    empieza a mitad de un `for` no significa nada, y su embedding tampoco."""
    codigo = ('import os\n\n\n'
              'def sumar(a, b):\n    return a + b\n\n\n'
              'class Motor:\n    def arrancar(self):\n        return True\n')

    simbolos = {f.simbolo for f in ci.trocear("x.py", codigo)}

    assert "sumar" in simbolos
    assert "Motor" in simbolos
    assert "arrancar" in simbolos, "los métodos también, no solo la clase entera"


def test_lo_que_esta_fuera_de_toda_funcion_tambien_se_indexa():
    """Los imports y las constantes de módulo son justo donde vive la configuración que
    alguien busca."""
    codigo = 'RUTA_BASE = "/datos"\nTIEMPO_LIMITE = 30\n\n\ndef f():\n    return 1\n'

    textos = " ".join(f.texto for f in ci.trocear("x.py", codigo))

    assert "RUTA_BASE" in textos


def test_un_python_que_no_parsea_cae_a_ventanas_y_se_indexa_igual():
    """Pasa justo cuando lo estás arreglando: si el índice se rindiera con un archivo roto,
    fallaría en el momento en que más falta hace."""
    fragmentos = ci.trocear("roto.py", "def esto no es valido(((\nx = 1\n")

    assert fragmentos, "un archivo roto igual tiene que indexarse"


def test_un_archivo_que_no_es_python_se_trocea_por_ventanas_con_solape():
    lineas = "".join(f"linea {i}\n" for i in range(1, 101))

    fragmentos = ci.trocear("notas.md", lineas)

    assert len(fragmentos) > 1
    assert fragmentos[1].linea_inicio < fragmentos[0].linea_fin, "las ventanas tienen que solaparse"


def test_un_fragmento_gigante_se_recorta_al_tope_del_modelo():
    """`all-MiniLM` trunca a 256 word-pieces: un fragmento más largo se indexa por su
    principio y el resto es invisible. Mejor cortarlo nosotros y saberlo."""
    codigo = "def enorme():\n" + "".join(f'    x{i} = "{i}"\n' for i in range(500))

    for fragmento in ci.trocear("x.py", codigo):
        assert len(fragmento.texto) <= ci._MAX_CARACTERES_FRAGMENTO


# ─────────────────────────── indexado incremental ───────────────────────────

def test_el_primer_indexado_registra_archivos_y_fragmentos(repo):
    resultado = ci.indexar(repo, embebedor=embebedor)

    assert resultado.archivos_nuevos == 2
    assert resultado.fragmentos > 0
    assert ci.estado(repo)["archivos"] == 2


def test_reindexar_sin_cambios_no_recalcula_nada(repo):
    """La diferencia entre un índice usable y uno que nadie actualiza nunca."""
    ci.indexar(repo, embebedor=embebedor)
    llamadas = []

    def contando(textos):
        llamadas.append(len(textos))
        return embebedor(textos)

    segundo = ci.indexar(repo, embebedor=contando)

    assert segundo.archivos_sin_cambios == 2
    assert segundo.archivos_nuevos == 0
    assert llamadas == [], "no tenía que calcular ni un embedding"


def test_un_archivo_modificado_se_reindexa(repo):
    ci.indexar(repo, embebedor=embebedor)
    with open(os.path.join(repo, "src", "auth.py"), "a", encoding="utf-8") as f:
        f.write("\n\ndef cerrar_sesion(usuario):\n    return True\n")

    resultado = ci.indexar(repo, embebedor=embebedor)

    assert resultado.archivos_actualizados == 1
    assert resultado.archivos_sin_cambios == 1


def test_un_archivo_borrado_desaparece_del_indice_con_sus_fragmentos(repo):
    ci.indexar(repo, embebedor=embebedor)
    antes = ci.estado(repo)["fragmentos"]

    os.remove(os.path.join(repo, "src", "auth.py"))
    resultado = ci.indexar(repo, embebedor=embebedor)

    assert resultado.archivos_borrados == 1
    assert ci.estado(repo)["archivos"] == 1
    assert ci.estado(repo)["fragmentos"] < antes


def test_los_archivos_de_credenciales_no_se_indexan(repo):
    """Meter un `.env` en un índice semántico es dejar la clave a una búsqueda de
    distancia."""
    with open(os.path.join(repo, ".env"), "w", encoding="utf-8") as f:
        f.write("CLAVE_SECRETA=no-deberia-estar\n")
    with open(os.path.join(repo, "id_rsa"), "w", encoding="utf-8") as f:
        f.write("clave privada\n")

    ci.indexar(repo, embebedor=embebedor)

    conn = ci._conexion()
    rutas = [fila[0] for fila in conn.execute("SELECT ruta FROM archivos")]
    conn.close()
    assert not [r for r in rutas if ".env" in r or "id_rsa" in r]


def test_las_extensiones_que_no_son_codigo_se_saltean(repo):
    with open(os.path.join(repo, "imagen.png"), "wb") as f:
        f.write(b"\x89PNG\r\n")
    with open(os.path.join(repo, "paquete.lock"), "w", encoding="utf-8") as f:
        f.write("dependencias\n")

    ci.indexar(repo, embebedor=embebedor)

    assert ci.estado(repo)["archivos"] == 2


def test_el_indexado_se_puede_cortar_y_continuar(repo):
    """Un repositorio grande lleva minutos: hacerlo de una sola vez bloquearía el turno."""
    resultado = ci.indexar(repo, embebedor=embebedor, tope_segundos=0)

    assert resultado.pendientes > 0
    assert resultado.completo is False

    resto = ci.indexar(repo, embebedor=embebedor)
    assert resto.completo is True


# ─────────────────────────── búsqueda ───────────────────────────

def test_encuentra_por_significado_y_no_por_la_palabra_exacta(repo):
    """El caso que motiva el REQ: preguntar por "factura" y caer en el módulo correcto."""
    ci.indexar(repo, embebedor=embebedor)

    resultados = ci.buscar("factura del cliente", repo, embebedor=embebedor)

    assert resultados
    assert "billing.py" in resultados[0].ruta


def test_el_resultado_dice_archivo_lineas_y_simbolo(repo):
    """Sin la ubicación exacta, el resultado obliga a leer el archivo entero de nuevo."""
    ci.indexar(repo, embebedor=embebedor)

    mejor = ci.buscar("token de login", repo, embebedor=embebedor)[0]

    assert mejor.linea_inicio > 0
    assert mejor.linea_fin >= mejor.linea_inicio
    assert mejor.ruta.endswith(".py")


def test_respeta_el_tope_de_resultados(repo):
    ci.indexar(repo, embebedor=embebedor)

    assert len(ci.buscar("cliente", repo, top_k=2, embebedor=embebedor)) <= 2


def test_una_consulta_vacia_no_devuelve_nada(repo):
    ci.indexar(repo, embebedor=embebedor)

    assert ci.buscar("   ", repo, embebedor=embebedor) == []


def test_buscar_en_una_carpeta_sin_indexar_no_revienta(tmp_path):
    otra = tmp_path / "sin-indexar"
    otra.mkdir()

    assert ci.buscar("lo que sea", str(otra), embebedor=embebedor) == []


def test_la_busqueda_ve_los_cambios_despues_de_reindexar(repo):
    """Si la caché no se invalidara, el índice diría lo de ayer y nadie entendería por qué."""
    ci.indexar(repo, embebedor=embebedor)
    ci.buscar("factura", repo, embebedor=embebedor)   # deja la caché armada

    with open(os.path.join(repo, "src", "reportes.py"), "w", encoding="utf-8") as f:
        f.write('def generar_reporte(usuario):\n    """Genera el reporte del usuario."""\n    return []\n')
    ci.indexar(repo, embebedor=embebedor)

    resultados = ci.buscar("reporte del usuario", repo, embebedor=embebedor)

    assert any("reportes.py" in r.ruta for r in resultados)
