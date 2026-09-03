"""
tests/test_email_adjuntos.py
Adjuntos de correo y verificación del remitente (`core/email_attachments.py`,
`core/email_auth.py`).

Lo que protege esta suite: **que un correo no pueda dejar un archivo en tu disco por su
cuenta**, y que cuando vos autorices uno, el nombre que eligió un desconocido no pueda
escribir fuera del directorio de descargas.

Y la otra mitad: que `allowed_senders` no dé una sensación de seguridad falsa. El campo
`From` lo escribe quien manda; la cabecera que dice si eso se verificó también se puede
falsificar, así que solo vale la que puso un servidor que el usuario declaró suyo.
"""

import email
import email.policy
import os

import pytest

from core import email_attachments, email_auth
from core.email_attachments import Adjunto, es_peligroso, nombre_seguro, tamano_legible
from core.security_manager import ChannelType, RiskLevel, security_manager


def _mensaje_con_adjunto(nombre="informe.pdf", tipo="application/pdf", datos=b"%PDF-1.4 x"):
    mensaje = email.message.EmailMessage()
    mensaje["From"] = "jefe@empresa.com"
    mensaje["Subject"] = "con adjunto"
    mensaje.set_content("mirá el archivo")
    principal, _, secundario = tipo.partition("/")
    mensaje.add_attachment(
        datos, maintype=principal, subtype=secundario, filename=nombre,
    )
    return email.message_from_bytes(mensaje.as_bytes(), policy=email.policy.default)


# ── El gate: descargar es amarillo, y no desde el celular ───────────

def test_guardar_un_adjunto_es_una_accion_amarilla():
    assert security_manager.classify_action("SAVE_EMAIL_ATTACHMENT") == RiskLevel.YELLOW


def test_el_canal_del_correo_no_puede_descargar_nada():
    """El punto entero: un correo no puede iniciar su propia descarga."""
    assert not security_manager.require_confirmation(
        "SAVE_EMAIL_ATTACHMENT", ChannelType.EMAIL,
    )


def test_tampoco_se_puede_descargar_desde_telegram():
    """Se confirma frente al PC: no hay excepción de canal para esta acción."""
    assert not security_manager.is_action_allowed(
        "SAVE_EMAIL_ATTACHMENT", ChannelType.TELEGRAM,
    )


def test_el_nombre_del_archivo_llega_al_texto_de_confirmacion():
    """Sin esto, el 'sí' sería a ciegas. `filename` está en _DETAILS_ALLOWED_KEYS."""
    from core.security_manager import format_details

    detalle = format_details("dispatch:SAVE_EMAIL_ATTACHMENT", {"filename": "informe.pdf"})

    assert "informe.pdf" in detalle


# ── Describir sin descargar ─────────────────────────────────────────

def test_se_describe_el_adjunto_sin_bajarlo():
    adjuntos = email_attachments.describir(_mensaje_con_adjunto())

    assert len(adjuntos) == 1
    assert adjuntos[0].nombre == "informe.pdf"
    assert adjuntos[0].tipo == "application/pdf"
    assert adjuntos[0].tamano > 0


def test_un_correo_sin_adjuntos_no_inventa_ninguno():
    mensaje = email.message.EmailMessage()
    mensaje["From"] = "a@b.com"
    mensaje.set_content("solo texto")

    assert email_attachments.describir(mensaje) == []


def test_la_descripcion_dice_nombre_tipo_y_tamano():
    linea = Adjunto("informe.pdf", "application/pdf", 245_000).describir()

    assert "informe.pdf" in linea
    assert "application/pdf" in linea
    assert "239 KB" in linea


def test_un_ejecutable_se_marca_en_la_descripcion():
    """Que el 'sí' sea una decisión informada y no un reflejo."""
    linea = Adjunto("factura.pdf.exe", "application/octet-stream", 100).describir()

    assert "EJECUTABLE" in linea


def test_el_texto_de_confirmacion_alcanza_para_decidir():
    texto = email_attachments.texto_de_confirmacion(
        Adjunto("virus.exe", "application/octet-stream", 5000), "desconocido@internet.com",
    )

    assert "virus.exe" in texto
    assert "desconocido@internet.com" in texto
    assert "EJECUTABLE" in texto
    assert email_attachments.DIRECTORIO_DESCARGAS in texto


def test_tamano_legible():
    assert tamano_legible(500) == "500 B"
    assert tamano_legible(2048) == "2 KB"
    assert tamano_legible(5 * 1024 * 1024) == "5.0 MB"


# ── Extensiones peligrosas ──────────────────────────────────────────

@pytest.mark.parametrize("nombre", [
    "malo.exe", "script.ps1", "macro.vbs", "instalador.msi", "app.bat", "lib.dll",
    "FACTURA.EXE",
])
def test_los_ejecutables_se_detectan(nombre):
    assert es_peligroso(nombre)


@pytest.mark.parametrize("nombre", ["informe.pdf", "foto.jpg", "datos.csv", "carta.docx"])
def test_los_archivos_normales_no_se_marcan(nombre):
    assert not es_peligroso(nombre)


def test_la_doble_extension_se_juzga_por_la_ultima():
    """"factura.pdf.exe" es un ejecutable, por más que empiece pareciendo un PDF."""
    assert es_peligroso("factura.pdf.exe")


# ── Travesía de rutas ───────────────────────────────────────────────

@pytest.mark.parametrize("hostil", [
    "../../../windows/system32/evil.dll",
    "..\\..\\Windows\\System32\\evil.dll",
    "/etc/passwd",
    "C:\\Windows\\algo.exe",
])
def test_un_nombre_hostil_no_puede_salir_del_directorio(hostil):
    """El nombre lo eligió un desconocido: no puede decidir dónde se escribe."""
    seguro = nombre_seguro(hostil)

    assert ".." not in seguro
    assert "/" not in seguro and "\\" not in seguro
    assert not os.path.isabs(seguro)


def test_un_nombre_vacio_o_absurdo_recibe_uno_por_defecto():
    assert nombre_seguro("") == "adjunto_sin_nombre"
    assert nombre_seguro("..") == "adjunto_sin_nombre"
    assert nombre_seguro("   ") == "adjunto_sin_nombre"


def test_un_nombre_larguisimo_se_recorta_conservando_la_extension():
    seguro = nombre_seguro("a" * 500 + ".pdf")

    assert len(seguro) <= 120
    assert seguro.endswith(".pdf")


def test_un_nombre_normal_no_se_estropea():
    assert nombre_seguro("Informe final (v2).pdf") == "Informe final (v2).pdf"


# ── Guardado ────────────────────────────────────────────────────────

@pytest.fixture
def descargas(monkeypatch, tmp_path):
    destino = tmp_path / "descargas"
    monkeypatch.setattr(email_attachments, "DIRECTORIO_DESCARGAS", str(destino))
    return destino


def test_se_guarda_el_adjunto_pedido(descargas):
    ruta = email_attachments.guardar(_mensaje_con_adjunto(), "informe.pdf")

    assert os.path.exists(ruta)
    assert open(ruta, "rb").read().startswith(b"%PDF")


def test_no_se_pisa_un_archivo_que_ya_estaba(descargas):
    """Un correo no puede reemplazarte un archivo que ya tenías."""
    primera = email_attachments.guardar(_mensaje_con_adjunto(), "informe.pdf")
    segunda = email_attachments.guardar(_mensaje_con_adjunto(), "informe.pdf")

    assert primera != segunda
    assert os.path.exists(primera) and os.path.exists(segunda)
    assert "(2)" in os.path.basename(segunda)


def test_un_nombre_hostil_termina_dentro_del_directorio(descargas):
    ruta = email_attachments.guardar(
        _mensaje_con_adjunto(nombre="../../../evil.dll"), "../../../evil.dll",
    )

    assert os.path.dirname(os.path.abspath(ruta)) == os.path.abspath(str(descargas))


def test_pedir_un_adjunto_que_no_existe_falla_claro(descargas):
    with pytest.raises(ValueError, match="no tiene ningún adjunto"):
        email_attachments.guardar(_mensaje_con_adjunto(), "otro.pdf")


def test_un_adjunto_gigante_se_rechaza(descargas):
    with pytest.raises(ValueError, match="tope"):
        email_attachments.guardar(
            _mensaje_con_adjunto(datos=b"x" * 5000), "informe.pdf", max_bytes=100,
        )


def test_buscar_tolera_un_nombre_a_medias():
    adjuntos = [Adjunto("Informe Final 2026.pdf", "application/pdf", 10)]

    assert email_attachments.buscar(adjuntos, "informe") is adjuntos[0]
    assert email_attachments.buscar(adjuntos, "planilla") is None


# ── Autenticación del remitente ─────────────────────────────────────

def _con_auth(*cabeceras):
    mensaje = email.message.EmailMessage()
    mensaje["From"] = "jefe@empresa.com"
    for cabecera in cabeceras:
        mensaje["Authentication-Results"] = cabecera
    mensaje.set_content("hola")
    return email.message_from_bytes(mensaje.as_bytes(), policy=email.policy.default)


_CONFIABLE = {"min": "verified", "trusted_authserv_ids": ["mx.google.com"]}


def test_sin_politica_todo_pasa_pero_se_anota():
    detalle, aceptado = email_auth.evaluar(_con_auth(), {})

    assert aceptado
    assert detalle == "desconocido"


def test_una_cabecera_de_un_servidor_de_confianza_vale():
    mensaje = _con_auth("mx.google.com; dkim=pass header.i=@empresa.com; spf=pass")

    detalle, aceptado = email_auth.evaluar(mensaje, _CONFIABLE)

    assert aceptado
    assert "dkim=pass" in detalle


def test_una_cabecera_falsificada_por_el_remitente_no_vale():
    """La defensa clave: cualquiera puede escribir esta cabecera en su propio correo."""
    mensaje = _con_auth("servidor-del-atacante.com; dkim=pass; spf=pass; dmarc=pass")

    detalle, aceptado = email_auth.evaluar(mensaje, _CONFIABLE)

    assert not aceptado
    assert detalle == "desconocido"


def test_el_atacante_no_gana_prependiendo_su_cabecera():
    """Manda la suya primero; solo debe contar la del servidor propio."""
    mensaje = _con_auth(
        "servidor-del-atacante.com; dkim=pass; spf=pass",
        "mx.google.com; dkim=fail; spf=fail",
    )

    detalle, aceptado = email_auth.evaluar(mensaje, _CONFIABLE)

    assert not aceptado
    assert "fail" in detalle


def test_sin_lista_de_servidores_propios_no_se_puede_verificar():
    """Preferimos 'desconocido' a un 'pass' que no significa nada."""
    mensaje = _con_auth("cualquiera.com; dkim=pass")

    detalle, aceptado = email_auth.evaluar(mensaje, {"min": "verified"})

    assert not aceptado
    assert detalle == "desconocido"


def test_dkim_fallado_no_pasa_el_nivel_verified():
    mensaje = _con_auth("mx.google.com; dkim=fail; spf=fail")

    _, aceptado = email_auth.evaluar(mensaje, _CONFIABLE)

    assert not aceptado


def test_con_spf_alcanza_para_verified():
    mensaje = _con_auth("mx.google.com; dkim=none; spf=pass")

    _, aceptado = email_auth.evaluar(mensaje, _CONFIABLE)

    assert aceptado


def test_el_nivel_strict_exige_dmarc():
    estricto = {"min": "strict", "trusted_authserv_ids": ["mx.google.com"]}

    _, con_dkim = email_auth.evaluar(_con_auth("mx.google.com; dkim=pass"), estricto)
    _, con_dmarc = email_auth.evaluar(
        _con_auth("mx.google.com; dkim=pass; dmarc=pass"), estricto,
    )

    assert not con_dkim
    assert con_dmarc


def test_un_nivel_invalido_cae_al_permisivo():
    mensaje = _con_auth("cualquiera.com; dkim=pass")

    _, aceptado = email_auth.evaluar(mensaje, {"min": "loquesea"})

    assert aceptado


def test_un_servidor_con_nombre_tramposo_no_se_lee_como_resultado():
    """Un authserv-id llamado "spf=pass.malo.com" no puede colarse como un resultado."""
    mensaje = _con_auth("spf=pass.malo.com; dkim=fail")

    detalle, aceptado = email_auth.evaluar(
        mensaje, {"min": "verified", "trusted_authserv_ids": ["spf=pass.malo.com"]},
    )

    assert not aceptado
    assert "spf=pass" not in detalle
