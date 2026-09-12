"""
tests/test_documentos.py
Pruebas de `core/documentos.py` — REQ-040, producir documentos de verdad.

Lo que protege esta suite, además de que los archivos salgan bien formados:

- **Un documento con relleno no se produce.** "lorem ipsum", "[insertar aquí]" o "por
  definir" se rechazan: un archivo con huecos parece trabajo hecho y no lo es.
- **Nunca se pisa un archivo del usuario.** Si `informe.docx` existe, sale `informe (2).docx`.
- **Los archivos van solo a donde corresponde.** Ni a `AppData`, ni fuera de la carpeta
  personal salvo un espacio de trabajo habilitado.
- **Las plantillas se respetan.** Membrete, pies y estilos se conservan; los marcadores se
  rellenan conservando el formato, también dentro de tablas.

Office no se toca en las pruebas: la conversión a PDF y los temas van simulados.
"""

import os
from pathlib import Path

import pytest

from core import documentos


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    """Una carpeta de salida permitida, fuera de la carpeta personal del que corre la suite."""
    monkeypatch.setattr(documentos, "_bases_permitidas", lambda: [tmp_path])
    # `tmp_path` vive bajo AppData, que en producción se rechaza con razón.
    monkeypatch.setattr(documentos, "CARPETAS_VEDADAS", frozenset())
    monkeypatch.setattr(documentos, "_con_office", lambda *a, **k: False)
    monkeypatch.setattr(documentos, "_aplicar_tema", lambda *a, **k: False)
    return str(tmp_path)


_INFORME = {
    "titulo": "Informe de campo",
    "autor": "Johan",
    "bloques": [
        {"tipo": "titulo", "nivel": 1, "texto": "Visita al lote 14"},
        {"tipo": "parrafo", "texto": ("Se encontró un avance del 60 % en la fertilización "
                                      "programada, con 1.200 palmas atendidas y 800 pendientes "
                                      "para la semana siguiente según el cronograma.")},
        {"tipo": "lista", "items": ["Aplicar segunda dosis", ["el 20 de septiembre"]]},
        {"tipo": "tabla", "encabezados": ["Lote", "Palmas"], "filas": [["14", "1.200"], ["15", "800"]]},
        {"tipo": "cita", "texto": "Lo que no se mide no se mejora."},
    ],
}


# ---------------------------------------------------------------- relleno y contenido

def test_un_documento_con_lorem_ipsum_no_se_produce(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="relleno"):
        documentos.crear_documento("x.docx", {"bloques": [
            {"tipo": "parrafo", "texto": "Lorem ipsum dolor sit amet " * 10}]}, carpeta=carpeta)


def test_un_hueco_por_completar_tampoco(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="relleno"):
        documentos.crear_hoja("x.xlsx", {"hojas": [{"encabezados": ["A"],
                                                    "filas": [["[insertar dato]"]]}]}, carpeta=carpeta)


def test_un_titulo_sin_nada_debajo_no_es_un_documento(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="contenido suficiente"):
        documentos.crear_documento("x.docx", {"titulo": "Informe", "bloques": []}, carpeta=carpeta)


def test_una_presentacion_de_puros_titulos_no_es_una_presentacion(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="contenido suficiente"):
        documentos.crear_presentacion("x.pptx", {"diapositivas": [{"titulo": "Uno"}, {"titulo": "Dos"}]},
                                      carpeta=carpeta)


def test_el_contenido_puede_venir_como_json_en_texto(carpeta):
    """Los modelos mandan a veces el JSON como cadena: se acepta en vez de gastar una vuelta."""
    import json

    r = documentos.crear_documento("nota.md", json.dumps(_INFORME), carpeta=carpeta)
    assert Path(r.ruta).read_text(encoding="utf-8").startswith("# Informe de campo")


def test_el_contenido_puede_venir_en_markdown(carpeta):
    md = ("# Acta\n\n## Asistentes\n\n- Johan\n- María\n\n## Acuerdos\n\n"
          "1. Revisar el drenaje del bloque C antes del viernes de esta semana.\n"
          "2. Enviar la cotización de fertilizante al proveedor con copia a compras.\n\n"
          "| Tema | Responsable |\n|---|---|\n| Drenaje | Johan |\n")
    r = documentos.crear_documento("acta.docx", md, carpeta=carpeta)

    from docx import Document

    doc = Document(r.ruta)
    estilos = [p.style.name for p in doc.paragraphs if p.text.strip()]
    assert "Heading 2" in estilos or "Heading 1" in estilos
    assert any("List" in e for e in estilos)
    assert len(doc.tables) == 1


# ---------------------------------------------------------------------- destino

def test_no_se_pisa_un_archivo_existente(carpeta):
    r1 = documentos.crear_documento("informe.md", _INFORME, carpeta=carpeta)
    r2 = documentos.crear_documento("informe.md", _INFORME, carpeta=carpeta)

    assert Path(r1.ruta).name == "informe.md"
    assert Path(r2.ruta).name == "informe (2).md"
    assert Path(r1.ruta).exists() and Path(r2.ruta).exists()


def test_no_se_escribe_fuera_de_las_carpetas_permitidas(tmp_path, monkeypatch):
    monkeypatch.setattr(documentos, "_bases_permitidas", lambda: [tmp_path / "permitida"])
    monkeypatch.setattr(documentos, "CARPETAS_VEDADAS", frozenset())
    with pytest.raises(documentos.DocumentoRechazado, match="carpeta personal"):
        documentos.crear_documento("x.md", _INFORME, carpeta=str(tmp_path / "otra"))


def test_no_se_escribe_en_carpetas_de_configuracion(tmp_path, monkeypatch):
    monkeypatch.setattr(documentos, "_bases_permitidas", lambda: [tmp_path])
    with pytest.raises(documentos.DocumentoRechazado, match="configuración"):
        documentos.crear_documento("x.md", _INFORME, carpeta=str(tmp_path / ".ssh"))


def test_el_nombre_se_limpia_de_caracteres_prohibidos(carpeta):
    r = documentos.crear_documento('in:for<me>.md', _INFORME, carpeta=carpeta)
    assert Path(r.ruta).name == "in_for_me_.md"


# -------------------------------------------------------------------------- Word

def test_el_word_sale_con_titulo_encabezados_lista_tabla_y_cita(carpeta):
    from docx import Document

    r = documentos.crear_documento("informe.docx", _INFORME, carpeta=carpeta)
    doc = Document(r.ruta)

    textos = [p.text for p in doc.paragraphs if p.text.strip()]
    estilos = {p.style.name for p in doc.paragraphs if p.text.strip()}
    assert textos[0] == "Informe de campo"
    assert "Heading 1" in estilos
    assert "List Bullet" in estilos
    assert any("Quote" in e for e in estilos)
    assert doc.tables[0].rows[0].cells[0].text == "Lote"
    assert doc.tables[0].rows[1].cells[1].text == "1.200"


def test_una_imagen_que_no_existe_no_tumba_el_documento(carpeta):
    spec = {**_INFORME, "bloques": _INFORME["bloques"] + [{"tipo": "imagen", "ruta": "C:/no/hay.png"}]}
    r = documentos.crear_documento("con_imagen.docx", spec, carpeta=carpeta)

    assert Path(r.ruta).exists()
    assert any("No encontré la imagen" in a for a in r.avisos)


def test_pdf_sin_office_se_maqueta_igual(carpeta):
    """Sin Word, un .pdf se produce con PyMuPDF: peor que Word, mejor que nada."""
    r = documentos.crear_documento("informe.pdf", _INFORME, carpeta=carpeta)

    import pymupdf

    pdf = pymupdf.open(r.ruta)
    assert pdf.page_count >= 1
    assert "Visita al lote 14" in pdf[0].get_text()
    assert "sin Office" in r.detalle


def test_pdf_con_office_se_convierte_desde_word(carpeta, monkeypatch):
    def _convertir(aplicacion, origen, destino):
        assert aplicacion == "Word" and origen.endswith(".docx")
        Path(destino).write_bytes(b"%PDF-1.4 simulado")
        return True

    monkeypatch.setattr(documentos, "_con_office", _convertir)
    r = documentos.crear_documento("informe.pdf", _INFORME, carpeta=carpeta)

    assert Path(r.ruta).read_bytes().startswith(b"%PDF")
    assert "convertido con Word" in r.detalle


def test_html_md_y_txt_salen_del_mismo_contenido(carpeta):
    for ext in ("html", "md", "txt"):
        r = documentos.crear_documento(f"informe.{ext}", _INFORME, carpeta=carpeta)
        texto = Path(r.ruta).read_text(encoding="utf-8")
        assert "Visita al lote 14" in texto
        assert "1.200" in texto


# --------------------------------------------------------------- Word con plantilla

@pytest.fixture
def plantilla_docx(tmp_path):
    from docx import Document
    from docx.shared import RGBColor

    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "AGRO ORIENTAL S.A.S."
    doc.styles["Heading 1"].font.color.rgb = RGBColor(0x1F, 0x6E, 0x43)
    doc.add_paragraph("Cotización {{numero}} para {{cliente}}", style="Heading 1")
    t = doc.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "{{concepto}}"
    t.rows[0].cells[1].text = "{{valor}}"
    ruta = tmp_path / "plantilla.docx"
    doc.save(str(ruta))
    return str(ruta)


def test_rellenar_una_plantilla_conserva_membrete_y_rellena_las_tablas(carpeta, plantilla_docx):
    from docx import Document

    r = documentos.crear_documento(
        "cotizacion.docx", {"bloques": []}, plantilla=plantilla_docx,
        reemplazos={"{{numero}}": "2026-18", "{{cliente}}": "Palmar Ltda",
                    "{{concepto}}": "Urea", "{{valor}}": "$ 1.200.000"},
        carpeta=carpeta)
    doc = Document(r.ruta)

    assert doc.sections[0].header.paragraphs[0].text == "AGRO ORIENTAL S.A.S."
    assert doc.paragraphs[0].text == "Cotización 2026-18 para Palmar Ltda"
    assert doc.paragraphs[0].style.name == "Heading 1"          # el formato se conserva
    assert [c.text for c in doc.tables[0].rows[0].cells] == ["Urea", "$ 1.200.000"]
    assert "4 marcadores" in r.detalle


def test_contenido_nuevo_sobre_la_plantilla_hereda_estilos_y_quita_el_cuerpo_viejo(
        carpeta, plantilla_docx):
    from docx import Document

    r = documentos.crear_documento("informe.docx", _INFORME, plantilla=plantilla_docx, carpeta=carpeta)
    doc = Document(r.ruta)

    assert doc.sections[0].header.paragraphs[0].text == "AGRO ORIENTAL S.A.S."
    assert not any("{{" in p.text for p in doc.paragraphs)   # el cuerpo viejo se fue
    h1 = [p for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert h1 and str(h1[0].style.font.color.rgb) == "1F6E43"  # y el estilo de la plantilla queda


def test_marcadores_que_no_estan_en_la_plantilla_se_avisan(carpeta, plantilla_docx):
    r = documentos.crear_documento("x.docx", {"bloques": []}, plantilla=plantilla_docx,
                                   reemplazos={"{{inexistente}}": "nada"}, carpeta=carpeta)
    assert any("ninguno de los marcadores" in a for a in r.avisos)


def test_una_plantilla_que_no_existe_lo_dice(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="No encuentro la plantilla"):
        documentos.crear_documento("x.docx", _INFORME, plantilla="C:/no/hay.docx", carpeta=carpeta)


def test_inspeccionar_una_plantilla_cuenta_sus_marcadores_y_su_membrete(plantilla_docx):
    salida = documentos.inspeccionar(plantilla_docx)

    assert "AGRO ORIENTAL" in salida
    assert "{{cliente}}" in salida and "{{valor}}" in salida
    assert "Heading 1" in salida


# -------------------------------------------------------------------------- Excel

_VENTAS = {"hojas": [{
    "nombre": "Ventas", "encabezados": ["Mes", "Ventas", "Costos", "Margen"],
    "filas": [["Enero", 1200000, "800.000", "=B2-C2"], ["Febrero", "1.350.000", 870000, "=B3-C3"]],
    "totales": True, "formatos": {"B": "#,##0"},
    "grafico": {"tipo": "barras", "titulo": "Ventas", "columnas": ["Ventas"], "categorias": "Mes"},
}]}


def test_el_excel_sale_con_numeros_formulas_totales_y_grafico(carpeta):
    from openpyxl import load_workbook

    r = documentos.crear_hoja("ventas.xlsx", _VENTAS, carpeta=carpeta)
    ws = load_workbook(r.ruta)["Ventas"]

    assert ws["C2"].value == 800000                 # "800.000" a la colombiana es un número
    assert ws["B3"].value == 1350000
    assert ws["D2"].value == "=B2-C2"               # las fórmulas se quedan como fórmulas
    assert ws["A4"].value == "Total"
    assert ws["B4"].value == "=SUM(B2:B3)"
    assert ws["B2"].number_format == "#,##0"
    assert ws.freeze_panes == "A2"
    assert len(ws._charts) == 1


def test_los_numeros_se_leen_a_la_colombiana():
    v = documentos._valor_de_celda
    assert v("870.000") == 870000
    assert v("1.250.000,50") == 1250000.5
    assert v("3,4") == 3.4
    assert v("12.5") == 12.5                        # uno o dos decimales tras el punto
    assert v("2026") == 2026
    assert v("=SUM(A1:A3)") == "=SUM(A1:A3)"
    assert v("Enero") == "Enero"


def test_una_lista_de_registros_se_vuelve_hoja(carpeta):
    from openpyxl import load_workbook

    registros = [{"cliente": "Agro SAS", "cupo": 45000000}, {"cliente": "Palmar", "cupo": 32000000}]
    r = documentos.crear_hoja("clientes.xlsx", registros, carpeta=carpeta)
    ws = load_workbook(r.ruta).active

    assert [c.value for c in ws[1]] == ["cliente", "cupo"]
    assert ws["B3"].value == 32000000


def test_csv_sale_con_punto_y_coma_para_excel_en_espanol(carpeta):
    r = documentos.crear_hoja("ventas.csv", _VENTAS, carpeta=carpeta)
    lineas = Path(r.ruta).read_text(encoding="utf-8-sig").splitlines()
    assert lineas[0] == "Mes;Ventas;Costos;Margen"
    assert lineas[1].startswith("Enero;1200000")


def test_excel_sobre_plantilla_escribe_debajo_del_encabezado_que_ya_tiene(carpeta, tmp_path):
    from openpyxl import Workbook, load_workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Inventario"
    ws.append(["Producto", "Existencias"])
    plantilla = tmp_path / "plantilla.xlsx"
    wb.save(str(plantilla))

    r = documentos.crear_hoja("inventario.xlsx", {"hojas": [{
        "nombre": "Inventario", "encabezados": ["Producto", "Existencias"],
        "filas": [["Urea", 120], ["KCl", 80]]}]}, plantilla=str(plantilla), carpeta=carpeta)
    ws = load_workbook(r.ruta)["Inventario"]

    assert [c.value for c in ws[1]] == ["Producto", "Existencias"]   # el de la plantilla
    assert ws["A2"].value == "Urea" and ws["B3"].value == 80
    assert ws.max_row == 3                                             # sin encabezado repetido


def test_una_hoja_vacia_se_rechaza(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="vacía"):
        documentos.crear_hoja("x.xlsx", {"hojas": [{"nombre": "A", "filas": []}]}, carpeta=carpeta)


# --------------------------------------------------------------------- PowerPoint

_PRESENTACION = {"titulo": "Resultados 2025", "subtitulo": "Junta", "diapositivas": [
    {"titulo": "Producción", "puntos": ["1.850.000 t", ["Oriental +15 %"]], "notas": "Riego."},
    {"titulo": "Indicadores", "tabla": {"encabezados": ["Ind", "2025"], "filas": [["Agua", "3,1"]]}},
    {"titulo": "Cierre", "texto": "Auditoría en marzo."},
]}


def test_la_presentacion_sale_con_portada_vinetas_tabla_y_notas(carpeta):
    from pptx import Presentation

    r = documentos.crear_presentacion("resultados.pptx", _PRESENTACION, carpeta=carpeta)
    prs = Presentation(r.ruta)

    titulos = [s.shapes.title.text for s in prs.slides]
    assert titulos == ["Resultados 2025", "Producción", "Indicadores", "Cierre"]
    cuerpo = [ph for ph in prs.slides[1].placeholders if ph.placeholder_format.idx == 1][0]
    niveles = [(p.text, p.level) for p in cuerpo.text_frame.paragraphs]
    assert niveles == [("1.850.000 t", 0), ("Oriental +15 %", 1)]
    assert prs.slides[1].notes_slide.notes_text_frame.text == "Riego."
    assert any(sh.has_table for sh in prs.slides[2].shapes)
    assert prs.slide_width > prs.slide_height * 1.5          # panorámica, no 4:3


def test_sin_powerpoint_el_tema_no_se_aplica_y_se_avisa(carpeta):
    r = documentos.crear_presentacion("x.pptx", _PRESENTACION, carpeta=carpeta)
    assert any("tema" in a.lower() for a in r.avisos)


def test_con_powerpoint_se_aplica_el_tema_pedido(carpeta, monkeypatch):
    aplicados = []
    monkeypatch.setattr(documentos, "_ruta_de_tema", lambda n: "C:/temas/Facet.thmx")
    monkeypatch.setattr(documentos, "_aplicar_tema", lambda ruta, tema: aplicados.append(tema) or True)

    r = documentos.crear_presentacion("x.pptx", _PRESENTACION, carpeta=carpeta, tema="Facet")

    assert aplicados == ["Facet"]
    assert "tema Facet" in r.detalle


def test_un_tema_que_no_existe_lo_dice_y_lista_los_que_hay(carpeta, monkeypatch):
    monkeypatch.setattr(documentos, "_ruta_de_tema", lambda n: None)
    monkeypatch.setattr(documentos, "temas_disponibles", lambda: ["Facet", "Ion"])

    r = documentos.crear_presentacion("x.pptx", _PRESENTACION, carpeta=carpeta, tema="Inventado")

    assert any("Inventado" in a and "Facet" in a for a in r.avisos)


def test_pptx_sobre_plantilla_rellena_y_conserva_el_tema(carpeta, tmp_path):
    from pptx import Presentation

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Propuesta para {{cliente}}"
    plantilla = tmp_path / "plantilla.pptx"
    prs.save(str(plantilla))

    r = documentos.crear_presentacion("propuesta.pptx", {"diapositivas": []},
                                      plantilla=str(plantilla),
                                      reemplazos={"{{cliente}}": "Palmar"}, carpeta=carpeta)

    assert Presentation(r.ruta).slides[0].shapes.title.text == "Propuesta para Palmar"
    assert "con el tema de plantilla.pptx" in r.detalle


def test_pdf_de_presentacion_sin_powerpoint_lo_dice(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="PowerPoint"):
        documentos.crear_presentacion("x.pdf", _PRESENTACION, carpeta=carpeta)


# ------------------------------------------------------------------- otros archivos

def test_un_json_sale_con_sangria(carpeta):
    r = documentos.crear_archivo("datos.json", {"a": 1, "b": [1, 2]}, carpeta=carpeta)
    assert Path(r.ruta).read_text(encoding="utf-8") == '{\n  "a": 1,\n  "b": [\n    1,\n    2\n  ]\n}'


def test_cualquier_extension_de_texto(carpeta):
    r = documentos.crear_archivo("consulta.sql", "SELECT * FROM ventas WHERE anio = 2026;", carpeta=carpeta)
    assert Path(r.ruta).read_text(encoding="utf-8").startswith("SELECT")


def test_un_archivo_sin_extension_se_rechaza(carpeta):
    with pytest.raises(documentos.DocumentoRechazado, match="extensión"):
        documentos.crear_archivo("sinextension", "hola", carpeta=carpeta)


def test_convertir_a_pdf_un_archivo_que_no_es_de_office_lo_dice(carpeta, tmp_path):
    origen = tmp_path / "nota.txt"
    origen.write_text("hola", encoding="utf-8")
    with pytest.raises(documentos.DocumentoRechazado, match="solo Word, Excel y PowerPoint"):
        documentos.convertir_a_pdf(str(origen))


# --------------------------------------------------------------- las herramientas

def test_las_herramientas_estan_registradas_con_su_nivel():
    from agents.tool_registry import get_tool
    from core.security_manager import ChannelType, RiskLevel, security_manager

    for amarilla in ("document_create", "spreadsheet_create", "presentation_create",
                     "file_create", "document_to_pdf"):
        assert get_tool(amarilla) is not None, amarilla
        assert security_manager.classify_action(amarilla) == RiskLevel.YELLOW, amarilla
    assert security_manager.classify_action("document_inspect") == RiskLevel.GREEN
    # Leer una plantilla es leer un archivo del usuario: solo delante del computador.
    assert not security_manager.is_action_allowed("document_inspect", ChannelType.TELEGRAM)


def test_la_confirmacion_dice_que_archivo_se_va_a_crear_y_donde():
    from core.security_manager import format_details

    detalle = format_details("document_create", {"nombre": "renuncia.docx", "carpeta": "Escritorio",
                                                 "plantilla": "membrete.docx"})
    assert "renuncia.docx" in detalle and "Escritorio" in detalle and "membrete.docx" in detalle


def test_la_herramienta_devuelve_el_rechazo_en_palabras_del_modelo(monkeypatch, carpeta):
    from agents.tool_registry import get_tool

    salida = get_tool("document_create").invoke(
        {"nombre": "x.docx", "contenido": {"bloques": [{"tipo": "parrafo", "texto": "lorem ipsum " * 20}]},
         "carpeta": carpeta})

    assert "relleno" in salida
