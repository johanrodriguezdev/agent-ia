"""
tests/test_imagenes_historial.py
REQ-070 — el modelo vuelve a ver las imágenes de los turnos anteriores.

Qué protege esta suite:

- **Que vuelvan a viajar.** Hasta ahora una captura solo se mandaba en su turno; en el
  mensaje siguiente el modelo ya no la veía y «¿y qué dice el botón de abajo?» obligaba a
  pegarla otra vez.
- **Que cada una vaya a SU mensaje**, no todas amontonadas en el último: el modelo tiene
  que poder distinguir «la primera» de «esta otra».
- **Que no se dispare el coste.** Cada imagen se reenvía en cada vuelta del bucle de
  razonamiento, así que hay un tope y una ventana, y se quedan las más recientes.
- **Que un archivo borrado no rompa la conversación.**
"""

import os

import pytest

from ai import llm_provider
from core import imagenes


@pytest.fixture
def png(tmp_path):
    """Una imagen de verdad: el módulo comprueba la firma del archivo, no la extensión."""
    def _crear(nombre):
        from PIL import Image

        ruta = tmp_path / nombre
        Image.new("RGB", (8, 8), (10, 20, 30)).save(str(ruta))
        return str(ruta)
    return _crear


def _usuario(texto, rutas=()):
    return {"role": "user", "content": imagenes.marcar_adjuntos(texto, list(rutas))}


# ------------------------------------------------------------------ qué se recupera

def test_sin_historial_no_hay_nada_que_recuperar():
    assert imagenes.imagenes_del_historial([]) == {}
    assert imagenes.imagenes_del_historial([{"role": "user", "content": "hola"}]) == {}


def test_una_imagen_de_un_turno_anterior_se_recupera(png):
    foto = png("captura.png")
    historial = [
        _usuario("mirá esto", [foto]),
        {"role": "assistant", "content": "Veo una captura."},
        _usuario("¿y qué dice el botón de abajo?"),
    ]

    assert imagenes.imagenes_del_historial(historial) == {0: [foto]}


def test_el_ultimo_mensaje_no_entra_porque_sus_imagenes_ya_viajan(png):
    foto = png("captura.png")
    historial = [{"role": "user", "content": "hola"}, _usuario("mirá", [foto])]

    assert imagenes.imagenes_del_historial(historial) == {}


def test_las_respuestas_del_agente_no_aportan_imagenes(png):
    foto = png("captura.png")
    historial = [
        {"role": "assistant", "content": imagenes.marcar_adjuntos("tomá", [foto])},
        {"role": "user", "content": "gracias"},
        {"role": "user", "content": "¿y ahora?"},
    ]

    assert imagenes.imagenes_del_historial(historial) == {}


def test_una_imagen_borrada_del_disco_se_salta_sin_romper_nada(tmp_path):
    fantasma = str(tmp_path / "ya-no-esta.png")
    historial = [_usuario("mirá", [fantasma]), {"role": "user", "content": "¿y?"}]

    assert imagenes.imagenes_del_historial(historial) == {}


def test_un_archivo_que_no_es_imagen_no_se_reenvia(tmp_path):
    pdf = tmp_path / "informe.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    historial = [_usuario("resumí esto", [str(pdf)]), {"role": "user", "content": "¿y?"}]

    assert imagenes.imagenes_del_historial(historial) == {}


def test_un_turno_de_herramientas_no_rompe_la_busqueda(png):
    """El historial mezcla mensajes planos con otros que llevan bloques de herramientas."""
    foto = png("captura.png")
    historial = [
        _usuario("mirá", [foto]),
        {"role": "assistant", "content": [{"tipo": "llamada", "id": "1", "nombre": "x",
                                           "argumentos": {}}]},
        {"role": "user", "content": "¿y?"},
    ]

    assert imagenes.imagenes_del_historial(historial) == {0: [foto]}


# ------------------------------------------------------------------ los topes

def test_solo_vuelven_las_mas_recientes_hasta_el_tope(png):
    fotos = [png(f"c{i}.png") for i in range(6)]
    historial = [_usuario(f"foto {i}", [f]) for i, f in enumerate(fotos)]
    historial.append({"role": "user", "content": "¿y ahora?"})

    recuperadas = imagenes.imagenes_del_historial(historial, tope=2)

    assert sum(len(v) for v in recuperadas.values()) == 2
    assert recuperadas == {4: [fotos[4]], 5: [fotos[5]]}      # las dos últimas


def test_la_ventana_deja_fuera_lo_viejo(png):
    viejo, nuevo = png("vieja.png"), png("nueva.png")
    historial = [_usuario("antigua", [viejo])]
    historial += [{"role": "user", "content": f"relleno {i}"} for i in range(8)]
    historial.append(_usuario("reciente", [nuevo]))
    historial.append({"role": "user", "content": "¿y?"})

    recuperadas = imagenes.imagenes_del_historial(historial, ventana=4)

    assert list(recuperadas.values()) == [[nuevo]]


def test_varias_imagenes_del_mismo_mensaje_se_mantienen_juntas(png):
    a, b = png("a.png"), png("b.png")
    historial = [_usuario("mirá estas dos", [a, b]), {"role": "user", "content": "¿cuál?"}]

    assert imagenes.imagenes_del_historial(historial) == {0: [a, b]}


# ------------------------------------------------------------------ llegan al proveedor

def test_anthropic_pone_la_imagen_vieja_en_su_propio_mensaje(png):
    foto = png("captura.png")
    historial = [
        _usuario("mirá esto", [foto]),
        {"role": "assistant", "content": "Veo una captura."},
        {"role": "user", "content": "¿y el botón de abajo?"},
    ]

    salida = llm_provider._mensajes_para_anthropic(historial, image_path=None)

    tipos = [b["type"] for b in salida[0]["content"]]
    assert tipos == ["image", "text"]                      # la imagen antes del texto
    assert salida[0]["content"][0]["source"]["media_type"] == "image/png"
    # Y no se coló en el mensaje nuevo.
    assert all(b["type"] == "text" for b in salida[2]["content"])


def test_anthropic_convive_con_la_imagen_del_turno_actual(png):
    vieja, nueva = png("vieja.png"), png("nueva.png")
    historial = [
        _usuario("la primera", [vieja]),
        {"role": "assistant", "content": "ok"},
        _usuario("y esta otra", [nueva]),
    ]

    salida = llm_provider._mensajes_para_anthropic(historial, image_path=nueva)

    assert [b["type"] for b in salida[0]["content"]] == ["image", "text"]
    assert [b["type"] for b in salida[2]["content"]] == ["image", "text"]


def test_openai_pone_la_imagen_vieja_en_su_mensaje(png):
    foto = png("captura.png")
    historial = [
        _usuario("mirá esto", [foto]),
        {"role": "assistant", "content": "Veo una captura."},
        {"role": "user", "content": "¿y el botón?"},
    ]

    salida = llm_provider._mensajes_para_openai(
        historial, "sistema", None, imagen_como_bloque=True)

    primero = next(m for m in salida if m["role"] == "user")
    assert [b["type"] for b in primero["content"]] == ["image_url", "text"]
    assert primero["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_deepseek_no_recibe_imagenes_porque_no_las_ve(png):
    """Manda texto plano: adjuntarlas sería gastar tokens en algo que ignora."""
    foto = png("captura.png")
    historial = [
        _usuario("mirá esto", [foto]),
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "¿y?"},
    ]

    salida = llm_provider._mensajes_para_openai(
        historial, "sistema", None, imagen_como_bloque=False, aviso_sin_vision=" (sin visión)")

    assert all(isinstance(m["content"], str) or m["content"] is None for m in salida)


def test_sin_imagenes_en_el_historial_los_mensajes_salen_como_siempre():
    """La forma de siempre no cambia: es lo que protege a los proveedores de una regresión."""
    historial = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "Te escucho."},
        {"role": "user", "content": "¿qué hora es?"},
    ]

    anthropic = llm_provider._mensajes_para_anthropic(historial, image_path=None)
    openai = llm_provider._mensajes_para_openai(historial, "sistema", None,
                                                imagen_como_bloque=True)

    assert all(len(m["content"]) == 1 and m["content"][0]["type"] == "text"
               for m in anthropic)
    # En OpenAI los mensajes del historial siguen siendo texto plano y solo el último se
    # arma con bloques, que es como era antes de REQ-070.
    cuerpo = [m for m in openai if m["role"] != "system"]
    assert [m["content"] for m in cuerpo[:-1]] == ["hola", "Te escucho."]
    assert cuerpo[-1]["content"] == [{"type": "text", "text": "¿qué hora es?"}]
