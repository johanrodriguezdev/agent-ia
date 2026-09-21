"""
tests/test_imagenes.py
REQ-054 — `core/imagenes.py`: tipo real, miniaturas, copia reducida, marcador del adjunto.
"""

import base64
import os

import pytest

from core import imagenes

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _png(ruta, ancho=40, alto=30, modo="RGB", color=(200, 30, 30)):
    Image.new(modo, (ancho, alto), color).save(ruta, format="PNG")
    return str(ruta)


def _jpg(ruta, ancho=40, alto=30):
    Image.new("RGB", (ancho, alto), (30, 200, 30)).save(ruta, format="JPEG")
    return str(ruta)


# --------------------------------------------------------------------------- es_imagen

@pytest.mark.parametrize("ruta,esperado", [
    (r"C:\fotos\captura.PNG", True),
    ("/home/j/foto.jpeg", True),
    ("animacion.gif", True),
    ("imagen.webp", True),
    ("informe.pdf", False),
    ("codigo.py", False),
    ("", False),
    (None, False),
])
def test_es_imagen_por_extension(ruta, esperado):
    assert imagenes.es_imagen(ruta) is esperado


# --------------------------------------------------------------------------- media_type

def test_media_type_mira_los_bytes_y_no_la_extension(tmp_path):
    """Una captura pegada se guarda como PNG; antes se declaraba siempre `image/jpeg` y la
    API de Anthropic rechazaba la imagen por no coincidir con lo declarado."""
    disfrazado = tmp_path / "captura.jpg"        # extensión mentirosa, contenido PNG
    _png(disfrazado)
    assert imagenes.media_type(str(disfrazado)) == "image/png"

    assert imagenes.media_type(_jpg(tmp_path / "foto.png")) == "image/jpeg"


def test_media_type_reconoce_gif_y_webp(tmp_path):
    gif = tmp_path / "a.gif"
    Image.new("P", (4, 4)).save(gif, format="GIF")
    assert imagenes.media_type(str(gif)) == "image/gif"

    webp = tmp_path / "a.webp"
    try:
        Image.new("RGB", (4, 4)).save(webp, format="WEBP")
    except Exception:
        pytest.skip("Pillow sin soporte WEBP")
    assert imagenes.media_type(str(webp)) == "image/webp"


def test_media_type_sin_firma_cae_a_la_extension_y_luego_a_jpeg(tmp_path):
    raro = tmp_path / "raro.png"
    raro.write_bytes(b"esto no es una imagen")
    assert imagenes.media_type(str(raro)) == "image/png"

    sin_ext = tmp_path / "sin_extension"
    sin_ext.write_bytes(b"nada")
    assert imagenes.media_type(str(sin_ext)) == "image/jpeg"

    assert imagenes.media_type(str(tmp_path / "no_existe.png")) == "image/png"


# --------------------------------------------------------------------------- miniatura

def test_miniatura_es_un_data_url_reducido_al_lado_pedido(tmp_path):
    ruta = _png(tmp_path / "grande.png", 1200, 600)
    url = imagenes.miniatura_data_url(ruta, lado=120)

    assert url.startswith("data:image/jpeg;base64,")
    datos = base64.b64decode(url.split(",", 1)[1])
    import io
    reducida = Image.open(io.BytesIO(datos))
    assert max(reducida.size) == 120


def test_miniatura_conserva_la_transparencia_como_png(tmp_path):
    ruta = _png(tmp_path / "alfa.png", 50, 50, modo="RGBA", color=(0, 0, 0, 0))
    assert imagenes.miniatura_data_url(ruta).startswith("data:image/png;base64,")


def test_miniatura_de_algo_que_no_es_imagen_o_no_existe_es_vacia(tmp_path):
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"no es png")
    assert imagenes.miniatura_data_url(str(roto)) == ""
    assert imagenes.miniatura_data_url(str(tmp_path / "nada.png")) == ""
    assert imagenes.miniatura_data_url("") == ""
    assert imagenes.miniatura_data_url(None) == ""


# --------------------------------------------------------------------------- preparar_para_el_modelo

def test_una_imagen_chica_va_tal_cual(tmp_path):
    ruta = _png(tmp_path / "chica.png", 300, 200)
    assert imagenes.preparar_para_el_modelo(ruta) == ruta


def test_una_imagen_enorme_se_reduce_a_una_copia_en_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(imagenes.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    imagenes._reducidas.clear()
    ruta = _png(tmp_path / "4k.png", 3840, 2160)

    reducida = imagenes.preparar_para_el_modelo(ruta)

    assert reducida != ruta
    assert os.path.dirname(reducida) == str(tmp_path / "tmp" / "orion_imagenes")
    assert max(Image.open(reducida).size) == imagenes.LADO_MAXIMO_PARA_EL_MODELO
    # La segunda vez (misma imagen, mismo mtime) no se vuelve a reducir.
    assert imagenes.preparar_para_el_modelo(ruta) == reducida


def test_preparar_nunca_lanza_con_una_ruta_rota_o_inexistente(tmp_path):
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"x" * 10)
    assert imagenes.preparar_para_el_modelo(str(roto)) == str(roto)
    assert imagenes.preparar_para_el_modelo(str(tmp_path / "nada.png")) == str(tmp_path / "nada.png")
    assert imagenes.preparar_para_el_modelo(None) is None


# --------------------------------------------------------------------------- imagen pegada

def test_ruta_para_imagen_pegada_vive_en_users_data_y_es_unica(tmp_path, monkeypatch):
    monkeypatch.setattr(imagenes, "carpeta_de_imagenes_pegadas",
                        lambda user_id="owner": str(tmp_path))
    primera = imagenes.ruta_para_imagen_pegada("owner")
    assert primera.endswith(".png") and os.path.basename(primera).startswith("pegada_")
    open(primera, "wb").close()
    segunda = imagenes.ruta_para_imagen_pegada("owner")
    assert segunda != primera


def test_carpeta_de_imagenes_pegadas_es_la_del_usuario(monkeypatch, tmp_path):
    monkeypatch.setattr(imagenes.os, "makedirs", lambda *a, **k: None)
    carpeta = imagenes.carpeta_de_imagenes_pegadas("owner")
    assert carpeta.replace("\\", "/").endswith("users_data/owner/imagenes")


# --------------------------------------------------------------------------- marcador

def test_marcar_y_separar_adjunto_van_y_vuelven():
    con_imagen = imagenes.marcar_adjunto("¿qué dice esto?", r"C:\fotos\captura.png")
    assert con_imagen == "¿qué dice esto?\n\n[Imagen adjunta: C:\\fotos\\captura.png]"
    assert imagenes.separar_adjunto(con_imagen) == ("¿qué dice esto?", r"C:\fotos\captura.png")

    con_archivo = imagenes.marcar_adjunto("resumí esto", r"C:\docs\informe.pdf")
    assert con_archivo == "resumí esto\n\n[Archivo adjunto: C:\\docs\\informe.pdf]"
    assert imagenes.separar_adjunto(con_archivo) == ("resumí esto", r"C:\docs\informe.pdf")


def test_separar_adjunto_deja_en_paz_un_texto_sin_marcador_o_con_uno_en_medio():
    assert imagenes.separar_adjunto("hola") == ("hola", None)
    assert imagenes.separar_adjunto("") == ("", None)
    assert imagenes.separar_adjunto(None) == ("", None)
    # Un marcador citado en medio del mensaje no es el adjunto del mensaje.
    texto = "ayer mandé [Archivo adjunto: C:\\a.pdf] y no funcionó"
    assert imagenes.separar_adjunto(texto) == (texto, None)


def test_separar_adjunto_con_solo_el_marcador_deja_texto_vacio():
    assert imagenes.separar_adjunto("[Imagen adjunta: C:\\x.png]") == ("", "C:\\x.png")


# --------------------------------------------------------------------------- resolver_para_mirar (REQ-062)

@pytest.fixture
def raices_de_prueba(tmp_path, monkeypatch):
    """La «carpeta personal» es `tmp_path/home`; los espacios de trabajo, `tmp_path/repo`."""
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    monkeypatch.setattr(imagenes, "_raices_para_mirar", lambda: [str(home), str(repo)])
    import core.documentos as documentos
    monkeypatch.setattr(documentos, "_escritorio", lambda: home / "Desktop")
    # `tmp_path` vive bajo AppData: se deja solo `.ssh` como carpeta vedada para la prueba.
    monkeypatch.setattr(documentos, "CARPETAS_VEDADAS", frozenset({".ssh"}))
    (home / "Desktop").mkdir()
    return home, repo


def test_resuelve_una_imagen_real_dentro_de_la_carpeta_personal(raices_de_prueba):
    home, _ = raices_de_prueba
    ruta = _png(home / "Desktop" / "captura.png")
    assert imagenes.resolver_para_mirar(ruta) == os.path.realpath(ruta)
    # Relativa: al Escritorio.
    assert imagenes.resolver_para_mirar("captura.png") == os.path.realpath(ruta)
    # Con comillas alrededor, como las pega el modelo a veces.
    assert imagenes.resolver_para_mirar(f'"{ruta}"') == os.path.realpath(ruta)


def test_rechaza_lo_que_no_es_imagen_o_no_existe(raices_de_prueba):
    home, _ = raices_de_prueba
    with pytest.raises(imagenes.ImagenRechazada, match="No encuentro"):
        imagenes.resolver_para_mirar(str(home / "nada.png"))
    texto = home / "notas.txt"
    texto.write_text("hola", encoding="utf-8")
    with pytest.raises(imagenes.ImagenRechazada, match="no es una imagen"):
        imagenes.resolver_para_mirar(str(texto))
    disfrazado = home / "virus.png"
    disfrazado.write_bytes(b"MZ no soy png")
    with pytest.raises(imagenes.ImagenRechazada, match="no lo es"):
        imagenes.resolver_para_mirar(str(disfrazado))
    with pytest.raises(imagenes.ImagenRechazada, match="Necesito la ruta"):
        imagenes.resolver_para_mirar("")


def test_rechaza_fuera_de_las_raices_y_en_carpetas_de_configuracion(raices_de_prueba, tmp_path):
    home, repo = raices_de_prueba
    afuera = _png(tmp_path / "afuera.png")
    with pytest.raises(imagenes.ImagenRechazada, match="Solo miro"):
        imagenes.resolver_para_mirar(afuera)
    (home / ".ssh").mkdir()
    secreta = _png(home / ".ssh" / "clave.png")
    with pytest.raises(imagenes.ImagenRechazada, match="configuración"):
        imagenes.resolver_para_mirar(secreta)
    # Un espacio de trabajo habilitado sí.
    en_repo = _png(repo / "docs" / "diagrama.png") if (repo / "docs").mkdir() is None else None
    assert imagenes.resolver_para_mirar(en_repo) == os.path.realpath(en_repo)
