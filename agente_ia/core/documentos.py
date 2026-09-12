"""
core/documentos.py
REQ-040 — Crear documentos de verdad: Word, Excel, PowerPoint, PDF y lo que haga falta.

**Qué había.** El agente escribía texto plano (`file_write`, `write_file_direct`) y leía
documentos de Office (`FileAnalysisSkill`), pero no podía *producir* uno: pedirle "hazme el
informe en Word" terminaba en un `.txt` en el escritorio. Y menos seguir una plantilla: el
membrete de la empresa, la cotización con el logo, la presentación con el tema corporativo.

**Cómo se reparte el trabajo.** El modelo escribe el contenido —todo el contenido: las
secciones, las filas, las diapositivas— como una estructura, y este módulo lo convierte en
un archivo bien formado. Es la misma división que en el resto del proyecto: la inteligencia
en el modelo, la mecánica acá. Lo que este módulo sí decide es que un documento vacío o de
relleno **no se produce**: "lorem ipsum", "[insertar aquí]", "por definir" se rechazan con
un mensaje que le pide al modelo el contenido real. Un archivo con marcadores de relleno
parece trabajo hecho y no lo es; peor que ningún archivo.

**Plantillas.** Se abre el archivo de plantilla y se escribe *dentro* de él, así que
conserva sus estilos, encabezados, pies, márgenes, tema y patrones. Hay dos maneras, que se
pueden combinar:

- `reemplazos`: la plantilla trae marcadores —`{{cliente}}`, `[FECHA]`— y se sustituyen,
  conservando el formato del texto que estaba. Es lo que se hace con una cotización.
- contenido nuevo: se vacía el cuerpo de la plantilla (nunca los encabezados ni los pies) y
  se escribe el contenido con los estilos que la plantilla define. Es lo que se hace con un
  membrete.

**PDF.** Con Office instalado —como en esta máquina— se convierte con el propio Word, Excel
o PowerPoint, que es la única forma de que el PDF se vea exactamente igual que el
documento. Sin Office, un documento de texto se maqueta con PyMuPDF; una hoja o una
presentación no tienen ese respaldo y se dice.

**Dónde quedan.** En el Escritorio, salvo que se pida otra carpeta dentro de la carpeta
personal del usuario o de un espacio de trabajo habilitado. Nunca se pisa un archivo que
ya exista: se numera (`informe (2).docx`), como hacen los adjuntos de correo.
"""

import csv
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Lo que este módulo sabe producir, por extensión.
EXTENSIONES_DOCUMENTO = ("docx", "pdf", "md", "html", "txt")
EXTENSIONES_HOJA = ("xlsx", "csv")
EXTENSIONES_PRESENTACION = ("pptx",)
EXTENSIONES_DATOS = ("json",)

#: Marcadores de relleno. Un documento que los trae no está hecho, está esbozado, y se
#: rechaza. La lista es corta a propósito: mejor dejar pasar un caso raro que rechazar un
#: documento real por una palabra normal.
_RELLENO = (
    "lorem ipsum", "[insertar", "[inserte", "[introducir", "[completar", "[pendiente",
    "[por definir", "por definir]", "texto de ejemplo", "texto de prueba", "contenido aquí",
    "contenido aqui", "tbd", "todo:", "xxxx", "placeholder", "{{", "}}", "<<", ">>",
    "ejemplo de párrafo", "ejemplo de parrafo",
)

#: Menos que esto y el documento es un título con nada debajo.
_MINIMO_CARACTERES_DOCUMENTO = 120

#: Ancho por defecto de una imagen dentro de un documento, en centímetros.
_ANCHO_IMAGEN_CM = 14.0

#: Tope de ancho de columna en Excel. Un texto largo no puede convertir la columna en una
#: cinta de tres pantallas.
_ANCHO_COLUMNA_MAXIMO = 60


#: Carpetas de la carpeta personal donde NO se crean documentos: son de configuración y
#: de llaves, no de trabajo del usuario.
CARPETAS_VEDADAS = frozenset({"appdata", ".ssh", ".gnupg", ".aws", ".azure", ".config"})


class DocumentoRechazado(Exception):
    """El contenido o el destino no sirven, y el motivo se le puede decir al modelo."""


@dataclass
class Resultado:
    """Qué se produjo y dónde, en términos que el modelo pueda contarle al usuario."""

    ruta: str
    formato: str
    detalle: str = ""
    avisos: List[str] = field(default_factory=list)

    def describir(self) -> str:
        texto = f"Listo: {self.ruta}"
        if self.detalle:
            texto += f" ({self.detalle})"
        texto += "."
        for aviso in self.avisos:
            texto += f" {aviso}"
        return texto


# =============================================================================== destino

def _escritorio() -> Path:
    """Return el Escritorio del usuario: el de OneDrive si lo redirige, si no el normal."""
    onedrive = Path.home() / "OneDrive" / "Desktop"
    if onedrive.exists():
        return onedrive
    escritorio = Path.home() / "Desktop"
    if escritorio.exists():
        return escritorio
    return Path.home()


def _bases_permitidas() -> List[Path]:
    """Return dónde se pueden crear archivos: la carpeta personal y los espacios de trabajo."""
    bases = [Path.home()]
    try:
        from core.workspace_config import cargar_raices

        bases += [Path(r) for r in cargar_raices()]
    except Exception as e:
        logger.debug(f"no se pudieron leer los espacios de trabajo: {e}")
    return bases


def carpeta_de_salida(carpeta: Optional[str]) -> Path:
    """Return la carpeta donde se va a escribir, ya comprobada. Levanta `DocumentoRechazado`."""
    if not carpeta or not str(carpeta).strip():
        return _escritorio()

    pedida = Path(os.path.expanduser(str(carpeta).strip()))
    if not pedida.is_absolute():
        pedida = _escritorio() / pedida
    real = Path(os.path.realpath(pedida))

    for base in _bases_permitidas():
        try:
            base_real = Path(os.path.realpath(base))
            if os.path.commonpath([str(real).lower(), str(base_real).lower()]) == \
                    str(base_real).lower():
                break
        except ValueError:
            continue
    else:
        raise DocumentoRechazado(
            f"No creo archivos en «{carpeta}»: solo dentro de tu carpeta personal o de un "
            f"espacio de trabajo habilitado."
        )

    # Dentro de la carpeta personal hay sitios que no son para documentos.
    nombre = real.name.lower()
    partes = {p.lower() for p in real.parts}
    if partes & CARPETAS_VEDADAS or nombre.startswith("."):
        raise DocumentoRechazado(
            f"«{carpeta}» es una carpeta de configuración, no de documentos. Elegí otra."
        )

    try:
        real.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise DocumentoRechazado(f"No pude crear la carpeta «{carpeta}»: {e.strerror or e}")
    return real


def ruta_libre(carpeta: Path, nombre: str) -> Path:
    """Return una ruta que no exista: si `informe.docx` está, `informe (2).docx`.

    Nunca se pisa un archivo del usuario. Un documento que él hizo a mano y que el agente
    reescribe porque se llamaba igual no se recupera.
    """
    limpio = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(nombre or "").strip()) or "documento"
    base, ext = os.path.splitext(limpio)
    candidata = carpeta / limpio
    numero = 2
    while candidata.exists():
        candidata = carpeta / f"{base} ({numero}){ext}"
        numero += 1
    return candidata


def _extension(nombre: str) -> str:
    return os.path.splitext(str(nombre or ""))[1].lower().lstrip(".")


def _plantilla_valida(plantilla: Optional[str], extensiones: Tuple[str, ...]) -> Optional[Path]:
    """Return la ruta de la plantilla comprobada, o None si no se pidió."""
    if not plantilla or not str(plantilla).strip():
        return None
    ruta = Path(os.path.expanduser(str(plantilla).strip()))
    if not ruta.is_absolute():
        for base in [_escritorio(), Path.home() / "Documents", Path.home() / "OneDrive" / "Documentos",
                     Path.home() / "Downloads"]:
            if (base / ruta).exists():
                ruta = base / ruta
                break
    if not ruta.is_file():
        raise DocumentoRechazado(f"No encuentro la plantilla «{plantilla}».")
    if _extension(ruta.name) not in extensiones:
        raise DocumentoRechazado(
            f"«{ruta.name}» no sirve de plantilla para esto: hace falta un archivo "
            f"{', '.join('.' + e for e in extensiones)}."
        )
    return ruta


# ============================================================================== contenido

def _texto_de(valor: Any) -> str:
    """Return todo el texto que haya dentro de una estructura, para revisarlo."""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, dict):
        return " ".join(_texto_de(v) for v in valor.values())
    if isinstance(valor, (list, tuple)):
        return " ".join(_texto_de(v) for v in valor)
    return "" if valor is None else str(valor)


def rechazar_relleno(contenido: Any) -> None:
    """Levanta `DocumentoRechazado` si el contenido trae marcadores de relleno.

    Se revisa lo que el modelo escribió, no la plantilla: los `{{marcadores}}` de una
    plantilla son justamente lo que se va a sustituir.
    """
    texto = _texto_de(contenido).lower()
    hallados = sorted({marca for marca in _RELLENO if marca in texto})
    if hallados:
        raise DocumentoRechazado(
            f"El contenido trae marcadores de relleno ({', '.join(repr(h) for h in hallados)}). "
            f"Un documento con huecos no es un documento: escribí el contenido completo y "
            f"real en cada sección antes de generarlo."
        )


def _como_estructura(contenido: Any) -> Any:
    """Return `contenido` como diccionario o lista, venga como venga.

    Los modelos mandan a veces el JSON como texto dentro del argumento. Se acepta, porque
    rechazarlo sería gastar una vuelta en pedirlo de otra forma.
    """
    if isinstance(contenido, str):
        recortado = contenido.strip()
        if recortado.startswith(("{", "[")):
            try:
                return json.loads(recortado)
            except json.JSONDecodeError as e:
                raise DocumentoRechazado(f"El contenido no es un JSON válido: {e}")
        return recortado
    return contenido


# ================================================================= documentos de texto

def _bloques_de(spec: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return `(cabecera, bloques)` de una especificación de documento.

    Se acepta un texto suelto —se parte en párrafos— y también Markdown sencillo: `#`
    títulos, `-` listas, `1.` numeradas. Es lo que un modelo escribe con más naturalidad.
    """
    if isinstance(spec, str):
        return {}, _bloques_desde_markdown(spec)
    if isinstance(spec, list):
        return {}, [b if isinstance(b, dict) else {"tipo": "parrafo", "texto": str(b)} for b in spec]
    if not isinstance(spec, dict):
        raise DocumentoRechazado("El contenido del documento tiene que ser un objeto con "
                                 "'bloques', una lista de bloques o un texto en Markdown.")
    bloques = spec.get("bloques") or spec.get("secciones") or spec.get("contenido") or []
    if isinstance(bloques, str):
        bloques = _bloques_desde_markdown(bloques)
    cabecera = {k: spec.get(k) for k in ("titulo", "subtitulo", "autor", "fecha") if spec.get(k)}
    return cabecera, [b if isinstance(b, dict) else {"tipo": "parrafo", "texto": str(b)}
                      for b in bloques]


def _bloques_desde_markdown(texto: str) -> List[Dict[str, Any]]:
    """Return bloques a partir de Markdown sencillo. No es un parser completo ni lo pretende."""
    bloques: List[Dict[str, Any]] = []
    lista: Optional[Dict[str, Any]] = None
    parrafo: List[str] = []

    def _cerrar_parrafo():
        nonlocal parrafo
        if parrafo:
            bloques.append({"tipo": "parrafo", "texto": " ".join(parrafo)})
            parrafo = []

    def _cerrar_lista():
        nonlocal lista
        if lista:
            bloques.append(lista)
            lista = None

    for linea in (texto or "").splitlines():
        cruda = linea.rstrip()
        if not cruda.strip():
            _cerrar_parrafo()
            _cerrar_lista()
            continue
        encabezado = re.match(r"^(#{1,4})\s+(.*)$", cruda)
        if encabezado:
            _cerrar_parrafo()
            _cerrar_lista()
            bloques.append({"tipo": "titulo", "nivel": len(encabezado.group(1)),
                            "texto": encabezado.group(2).strip()})
            continue
        item = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.*)$", cruda)
        if item:
            _cerrar_parrafo()
            numerada = bool(re.match(r"^\s*\d+[.)]", cruda))
            if lista is None or lista.get("numerada") != numerada:
                _cerrar_lista()
                lista = {"tipo": "lista", "numerada": numerada, "items": []}
            lista["items"].append(item.group(1).strip())
            continue
        if cruda.startswith("|") and cruda.endswith("|"):
            _cerrar_parrafo()
            _cerrar_lista()
            celdas = [c.strip() for c in cruda.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in celdas):
                continue                       # la línea de separación de la tabla
            if bloques and bloques[-1].get("tipo") == "tabla" and bloques[-1].get("_abierta"):
                bloques[-1]["filas"].append(celdas)
            else:
                bloques.append({"tipo": "tabla", "encabezados": celdas, "filas": [],
                                "_abierta": True})
            continue
        if bloques and bloques[-1].get("tipo") == "tabla" and bloques[-1].get("_abierta"):
            bloques[-1].pop("_abierta", None)
        _cerrar_lista()
        parrafo.append(cruda.strip())

    _cerrar_parrafo()
    _cerrar_lista()
    for b in bloques:
        b.pop("_abierta", None)
    return bloques


def _validar_documento(cabecera: Dict[str, Any], bloques: List[Dict[str, Any]],
                       con_reemplazos: bool) -> None:
    """Un documento tiene que tener contenido de verdad. Levanta si no."""
    if con_reemplazos and not bloques:
        return                                 # rellenar una plantilla es contenido en sí
    prosa = 0
    filas = 0
    for b in bloques:
        tipo = b.get("tipo", "parrafo")
        if tipo in ("parrafo", "cita", "titulo"):
            prosa += len(str(b.get("texto") or ""))
        elif tipo == "lista":
            prosa += sum(len(str(i)) for i in b.get("items") or [])
        elif tipo == "tabla":
            filas += len(b.get("filas") or [])
    if not bloques or (prosa < _MINIMO_CARACTERES_DOCUMENTO and filas < 2):
        raise DocumentoRechazado(
            "El documento no tiene contenido suficiente: hacen falta las secciones con su "
            "texto completo, no solo el título. Escribí el documento entero y volvé a pedirlo."
        )


def _reemplazar_en_parrafo(parrafo, reemplazos: Dict[str, str]) -> int:
    """Sustituye marcadores en un párrafo de Word conservando el formato. Return cuántos.

    Word parte el texto de un párrafo en "runs" según el formato, y un marcador como
    `{{cliente}}` puede quedar repartido en tres. Se sustituye sobre el texto completo y se
    vuelve a escribir en el primer run, que conserva su fuente y su tamaño; los demás se
    vacían. Es lo que hace que la cotización rellenada siga pareciendo la cotización.
    """
    texto = parrafo.text
    if not any(marca in texto for marca in reemplazos):
        return 0
    cuantos = 0
    for marca, valor in reemplazos.items():
        if marca in texto:
            cuantos += texto.count(marca)
            texto = texto.replace(marca, str(valor))
    if parrafo.runs:
        parrafo.runs[0].text = texto
        for run in parrafo.runs[1:]:
            run.text = ""
    else:
        parrafo.add_run(texto)
    return cuantos


def _reemplazar_en_docx(doc, reemplazos: Dict[str, str]) -> int:
    """Return cuántos marcadores se sustituyeron en cuerpo, tablas, encabezados y pies."""
    cuantos = 0
    contenedores = [doc]
    for seccion in doc.sections:
        contenedores += [seccion.header, seccion.footer, seccion.first_page_header,
                         seccion.first_page_footer]
    for contenedor in contenedores:
        try:
            for parrafo in contenedor.paragraphs:
                cuantos += _reemplazar_en_parrafo(parrafo, reemplazos)
            for tabla in contenedor.tables:
                for fila in tabla.rows:
                    for celda in fila.cells:
                        for parrafo in celda.paragraphs:
                            cuantos += _reemplazar_en_parrafo(parrafo, reemplazos)
        except Exception as e:
            logger.debug(f"no se pudo recorrer una parte de la plantilla: {e}")
    return cuantos


def _vaciar_cuerpo(doc) -> None:
    """Quita el contenido del cuerpo de una plantilla, dejando encabezados, pies y estilos."""
    cuerpo = doc.element.body
    for hijo in list(cuerpo):
        if hijo.tag.endswith("}sectPr"):
            continue                           # la configuración de página se queda
        cuerpo.remove(hijo)


def _estilo(doc, *candidatos: str):
    """Return el primer estilo que exista en el documento de entre los candidatos, o None."""
    for nombre in candidatos:
        try:
            return doc.styles[nombre]
        except KeyError:
            continue
    return None


def _docx(cabecera: Dict[str, Any], bloques: List[Dict[str, Any]], ruta: Path,
          plantilla: Optional[Path], reemplazos: Dict[str, str]) -> Resultado:
    from docx import Document
    from docx.shared import Cm, Pt

    doc = Document(str(plantilla)) if plantilla else Document()
    avisos: List[str] = []

    sustituidos = _reemplazar_en_docx(doc, reemplazos) if reemplazos else 0
    if reemplazos and not sustituidos:
        avisos.append("Ojo: ninguno de los marcadores que me diste aparece en la plantilla; "
                      "revisá cómo están escritos en ella con document_inspect.")
    if plantilla and bloques:
        _vaciar_cuerpo(doc)

    if cabecera.get("titulo"):
        p = doc.add_paragraph(str(cabecera["titulo"]), style=_estilo(doc, "Title", "Título"))
        if p.style is None or p.style.name not in ("Title", "Título"):
            p.runs[0].bold = True
            p.runs[0].font.size = Pt(24)
    if cabecera.get("subtitulo"):
        doc.add_paragraph(str(cabecera["subtitulo"]), style=_estilo(doc, "Subtitle", "Subtítulo"))
    pie_portada = " · ".join(str(cabecera[k]) for k in ("autor", "fecha") if cabecera.get(k))
    if pie_portada:
        doc.add_paragraph(pie_portada)

    for bloque in bloques:
        tipo = str(bloque.get("tipo") or "parrafo").lower()
        if tipo == "titulo":
            nivel = max(1, min(int(bloque.get("nivel") or 1), 4))
            texto = str(bloque.get("texto") or "")
            try:
                doc.add_heading(texto, level=nivel)
            except KeyError:
                p = doc.add_paragraph(texto)
                p.runs[0].bold = True
                p.runs[0].font.size = Pt(18 - 2 * nivel)
        elif tipo == "lista":
            numerada = bool(bloque.get("numerada"))
            estilo = _estilo(doc, "List Number" if numerada else "List Bullet",
                             "Lista con números" if numerada else "Lista con viñetas")
            for item in bloque.get("items") or []:
                if isinstance(item, (list, tuple)):
                    for sub in item:
                        p = doc.add_paragraph(str(sub), style=estilo)
                        p.paragraph_format.left_indent = Cm(1.25)
                    continue
                if estilo is not None:
                    doc.add_paragraph(str(item), style=estilo)
                else:
                    doc.add_paragraph(("• " if not numerada else "") + str(item))
        elif tipo == "tabla":
            encabezados = [str(c) for c in (bloque.get("encabezados") or [])]
            filas = [[("" if c is None else str(c)) for c in fila]
                     for fila in (bloque.get("filas") or [])]
            columnas = max([len(encabezados)] + [len(f) for f in filas]) if (encabezados or filas) else 0
            if not columnas:
                continue
            if bloque.get("titulo"):
                doc.add_paragraph(str(bloque["titulo"]),
                                  style=_estilo(doc, "Caption", "Descripción"))
            tabla = doc.add_table(rows=0, cols=columnas)
            estilo_tabla = _estilo(doc, "Table Grid", "Tabla con cuadrícula")
            if estilo_tabla is not None:
                tabla.style = estilo_tabla
            if encabezados:
                celdas = tabla.add_row().cells
                for i, texto in enumerate(encabezados):
                    celdas[i].text = texto
                    for p in celdas[i].paragraphs:
                        for r in p.runs:
                            r.bold = True
            for fila in filas:
                celdas = tabla.add_row().cells
                for i, texto in enumerate(fila[:columnas]):
                    celdas[i].text = texto
            doc.add_paragraph()
        elif tipo == "imagen":
            ruta_imagen = str(bloque.get("ruta") or "")
            if not os.path.isfile(ruta_imagen):
                avisos.append(f"No encontré la imagen «{ruta_imagen}»; el documento se hizo sin ella.")
                continue
            try:
                ancho = float(bloque.get("ancho_cm") or _ANCHO_IMAGEN_CM)
                doc.add_picture(ruta_imagen, width=Cm(ancho))
                if bloque.get("pie"):
                    doc.add_paragraph(str(bloque["pie"]), style=_estilo(doc, "Caption", "Descripción"))
            except Exception as e:
                avisos.append(f"No pude insertar la imagen «{os.path.basename(ruta_imagen)}»: {e}.")
        elif tipo == "salto":
            doc.add_page_break()
        elif tipo == "cita":
            doc.add_paragraph(str(bloque.get("texto") or ""),
                              style=_estilo(doc, "Intense Quote", "Quote", "Cita destacada", "Cita"))
        else:
            p = doc.add_paragraph(str(bloque.get("texto") or ""))
            if bloque.get("negrita"):
                for r in p.runs:
                    r.bold = True

    doc.save(str(ruta))
    detalle = f"{len(bloques)} bloques"
    if sustituidos:
        detalle += f", {sustituidos} marcadores rellenados"
    if plantilla:
        detalle += f", sobre la plantilla {plantilla.name}"
    return Resultado(ruta=str(ruta), formato="docx", detalle=detalle, avisos=avisos)


def _html_de(cabecera: Dict[str, Any], bloques: List[Dict[str, Any]]) -> str:
    """Return el documento como HTML sencillo y limpio. Sirve para .html y para el PDF sin Office."""
    import html as _html

    partes = ["<!doctype html><html><head><meta charset='utf-8'>",
              "<style>body{font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.4;"
              "max-width:17cm;margin:2cm auto;color:#222}h1{font-size:20pt}h2{font-size:15pt}"
              "h3{font-size:12.5pt}table{border-collapse:collapse;margin:8pt 0}"
              "td,th{border:1px solid #999;padding:4pt 6pt;vertical-align:top}th{background:#eee}"
              "blockquote{border-left:3px solid #999;margin:8pt 0;padding-left:8pt;color:#444}"
              ".portada{color:#555}</style></head><body>"]
    e = _html.escape
    if cabecera.get("titulo"):
        partes.append(f"<h1>{e(str(cabecera['titulo']))}</h1>")
    if cabecera.get("subtitulo"):
        partes.append(f"<p class='portada'><b>{e(str(cabecera['subtitulo']))}</b></p>")
    pie = " · ".join(str(cabecera[k]) for k in ("autor", "fecha") if cabecera.get(k))
    if pie:
        partes.append(f"<p class='portada'>{e(pie)}</p>")
    for b in bloques:
        tipo = str(b.get("tipo") or "parrafo").lower()
        if tipo == "titulo":
            n = max(1, min(int(b.get("nivel") or 1), 4)) + 1
            partes.append(f"<h{n}>{e(str(b.get('texto') or ''))}</h{n}>")
        elif tipo == "lista":
            etiqueta = "ol" if b.get("numerada") else "ul"
            items = "".join(f"<li>{e(str(i))}</li>" for i in (b.get("items") or []))
            partes.append(f"<{etiqueta}>{items}</{etiqueta}>")
        elif tipo == "tabla":
            enc = "".join(f"<th>{e(str(c))}</th>" for c in (b.get("encabezados") or []))
            filas = "".join("<tr>" + "".join(f"<td>{e('' if c is None else str(c))}</td>"
                                             for c in f) + "</tr>"
                            for f in (b.get("filas") or []))
            titulo = f"<p><i>{e(str(b['titulo']))}</i></p>" if b.get("titulo") else ""
            partes.append(f"{titulo}<table>{'<tr>' + enc + '</tr>' if enc else ''}{filas}</table>")
        elif tipo == "cita":
            partes.append(f"<blockquote>{e(str(b.get('texto') or ''))}</blockquote>")
        elif tipo == "salto":
            partes.append("<div style='page-break-after:always'></div>")
        elif tipo == "imagen":
            if os.path.isfile(str(b.get("ruta") or "")):
                partes.append(f"<img src='file:///{e(str(b['ruta']))}' style='max-width:100%'>")
        else:
            partes.append(f"<p>{e(str(b.get('texto') or ''))}</p>")
    partes.append("</body></html>")
    return "".join(partes)


def _markdown_de(cabecera: Dict[str, Any], bloques: List[Dict[str, Any]]) -> str:
    lineas: List[str] = []
    if cabecera.get("titulo"):
        lineas += [f"# {cabecera['titulo']}", ""]
    if cabecera.get("subtitulo"):
        lineas += [f"**{cabecera['subtitulo']}**", ""]
    pie = " · ".join(str(cabecera[k]) for k in ("autor", "fecha") if cabecera.get(k))
    if pie:
        lineas += [f"*{pie}*", ""]
    for b in bloques:
        tipo = str(b.get("tipo") or "parrafo").lower()
        if tipo == "titulo":
            nivel = max(1, min(int(b.get("nivel") or 1), 4)) + 1
            lineas += ["#" * nivel + " " + str(b.get("texto") or ""), ""]
        elif tipo == "lista":
            for i, item in enumerate(b.get("items") or [], 1):
                lineas.append((f"{i}. " if b.get("numerada") else "- ") + str(item))
            lineas.append("")
        elif tipo == "tabla":
            enc = [str(c) for c in (b.get("encabezados") or [])]
            filas = b.get("filas") or []
            if b.get("titulo"):
                lineas += [f"*{b['titulo']}*", ""]
            if enc:
                lineas.append("| " + " | ".join(enc) + " |")
                lineas.append("|" + "---|" * len(enc))
            for f in filas:
                lineas.append("| " + " | ".join("" if c is None else str(c) for c in f) + " |")
            lineas.append("")
        elif tipo == "cita":
            lineas += ["> " + str(b.get("texto") or ""), ""]
        elif tipo == "salto":
            lineas += ["---", ""]
        elif tipo == "imagen":
            lineas += [f"![{b.get('pie') or ''}]({b.get('ruta') or ''})", ""]
        else:
            lineas += [str(b.get("texto") or ""), ""]
    return "\n".join(lineas).rstrip() + "\n"


def _texto_plano_de(cabecera: Dict[str, Any], bloques: List[Dict[str, Any]]) -> str:
    md = _markdown_de(cabecera, bloques)
    return re.sub(r"^#+\s*", "", md, flags=re.MULTILINE).replace("**", "").replace("*", "")


def _pdf_sin_office(html: str, ruta: Path) -> None:
    """Maqueta el HTML en un PDF con PyMuPDF. Es el respaldo cuando no hay Word."""
    import pymupdf

    historia = pymupdf.Story(html=html)
    escritor = pymupdf.DocumentWriter(str(ruta))
    rect_pagina = pymupdf.paper_rect("a4")
    area = rect_pagina + (56, 56, -56, -56)         # 2 cm de margen
    hay_mas = True
    while hay_mas:
        dispositivo = escritor.begin_page(rect_pagina)
        hay_mas, _ = historia.place(area)
        historia.draw(dispositivo)
        escritor.end_page()
    escritor.close()


def crear_documento(nombre: str, contenido: Any, plantilla: Optional[str] = None,
                    reemplazos: Optional[Dict[str, str]] = None,
                    carpeta: Optional[str] = None) -> Resultado:
    """Produce un documento de texto: .docx, .pdf, .md, .html o .txt. Levanta `DocumentoRechazado`.

    `contenido` es un objeto con `titulo`, `subtitulo`, `autor`, `fecha` y `bloques` —o un
    texto en Markdown, que se convierte—. Cada bloque tiene `tipo`: `titulo` (con `nivel`),
    `parrafo`, `lista` (`items`, `numerada`), `tabla` (`encabezados`, `filas`, `titulo`),
    `imagen` (`ruta`, `ancho_cm`, `pie`), `cita`, `salto`.
    """
    extension = _extension(nombre)
    if extension not in EXTENSIONES_DOCUMENTO:
        raise DocumentoRechazado(
            f"«{nombre}» no es un documento de texto: hace falta "
            f"{', '.join('.' + e for e in EXTENSIONES_DOCUMENTO)}."
        )
    reemplazos = {str(k): str(v) for k, v in (reemplazos or {}).items()}
    spec = _como_estructura(contenido)
    rechazar_relleno(spec)
    cabecera, bloques = _bloques_de(spec)
    _validar_documento(cabecera, bloques, con_reemplazos=bool(reemplazos))
    destino = carpeta_de_salida(carpeta)
    ruta = ruta_libre(destino, nombre)
    ruta_plantilla = _plantilla_valida(plantilla, ("docx",)) if plantilla else None

    if extension == "docx":
        return _docx(cabecera, bloques, ruta, ruta_plantilla, reemplazos)

    if extension == "pdf":
        # Primero el Word —con la plantilla si la hay— y de ahí el PDF con el propio Word:
        # es la única forma de que el PDF se vea exactamente igual. Sin Word, se maqueta.
        with tempfile.TemporaryDirectory() as temporal:
            intermedio = Path(temporal) / (ruta.stem + ".docx")
            resultado = _docx(cabecera, bloques, intermedio, ruta_plantilla, reemplazos)
            pdf_temporal = Path(temporal) / (ruta.stem + ".pdf")
            if _con_office("Word", str(intermedio), str(pdf_temporal)):
                os.replace(str(pdf_temporal), str(ruta))
                return Resultado(ruta=str(ruta), formato="pdf",
                                 detalle=resultado.detalle + ", convertido con Word",
                                 avisos=resultado.avisos)
        avisos = list(resultado.avisos)
        if ruta_plantilla:
            avisos.append("Sin Word no puedo aplicar la plantilla al PDF: se maquetó con el "
                          "estilo básico.")
        _pdf_sin_office(_html_de(cabecera, bloques), ruta)
        return Resultado(ruta=str(ruta), formato="pdf",
                         detalle=f"{len(bloques)} bloques, maquetado sin Office", avisos=avisos)

    if extension == "html":
        ruta.write_text(_html_de(cabecera, bloques), encoding="utf-8")
    elif extension == "md":
        ruta.write_text(_markdown_de(cabecera, bloques), encoding="utf-8")
    else:
        ruta.write_text(_texto_plano_de(cabecera, bloques), encoding="utf-8")
    return Resultado(ruta=str(ruta), formato=extension, detalle=f"{len(bloques)} bloques")


# ==================================================================== hojas de cálculo

def _hojas_de(spec: Any) -> List[Dict[str, Any]]:
    """Return la lista de hojas de una especificación, venga como venga."""
    if isinstance(spec, dict) and "hojas" in spec:
        hojas = spec["hojas"]
    elif isinstance(spec, dict) and ("filas" in spec or "encabezados" in spec):
        hojas = [spec]
    elif isinstance(spec, list) and spec and isinstance(spec[0], (list, tuple)):
        hojas = [{"encabezados": list(spec[0]), "filas": [list(f) for f in spec[1:]]}]
    elif isinstance(spec, list) and spec and isinstance(spec[0], dict) and "filas" in spec[0]:
        hojas = spec
    elif isinstance(spec, list) and spec and isinstance(spec[0], dict):
        # Una lista de registros: las claves son los encabezados.
        claves = list(spec[0].keys())
        hojas = [{"encabezados": claves, "filas": [[r.get(k) for k in claves] for r in spec]}]
    else:
        raise DocumentoRechazado("El contenido de la hoja tiene que traer 'hojas' o, al menos, "
                                 "'encabezados' y 'filas'.")
    salida = []
    for i, h in enumerate(hojas or [], 1):
        if not isinstance(h, dict):
            raise DocumentoRechazado("Cada hoja tiene que ser un objeto con 'encabezados' y 'filas'.")
        filas = [list(f) if isinstance(f, (list, tuple)) else [f] for f in (h.get("filas") or [])]
        if not filas and not h.get("encabezados"):
            raise DocumentoRechazado(f"La hoja {i} está vacía: no trae filas.")
        salida.append({**h, "nombre": str(h.get("nombre") or f"Hoja{i}")[:31], "filas": filas,
                       "encabezados": [str(c) for c in (h.get("encabezados") or [])]})
    if not salida:
        raise DocumentoRechazado("No hay ninguna hoja que escribir.")
    return salida


def _valor_de_celda(valor: Any) -> Any:
    """Return el valor listo para Excel: números como números, fórmulas como fórmulas."""
    if valor is None or isinstance(valor, (int, float, bool)):
        return valor
    texto = str(valor).strip()
    if texto.startswith("="):
        return texto                            # fórmula, la calcula Excel
    # "1.250.000" y "12,5" son números escritos a la colombiana: se guardan como número para
    # que las fórmulas y los formatos funcionen, no como texto que parece número.
    #
    # La convención es la del español, y se decide a propósito: el punto seguido de
    # exactamente tres dígitos es separador de miles, la coma es el decimal. La primera
    # versión leía "870.000" como 870 con decimales —a la inglesa— y una hoja de costos
    # quedó con ochocientos setenta pesos donde iban ochocientos setenta mil. Un "12.5" a
    # la inglesa (uno o dos decimales tras el punto) se sigue leyendo como 12,5.
    numero = re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?|-?\d+(,\d+)?|-?\d+(\.\d+)?", texto)
    if numero:
        limpio = texto
        if "," in texto:
            limpio = texto.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", texto):
            limpio = texto.replace(".", "")
        try:
            return float(limpio) if ("." in limpio) else int(limpio)
        except ValueError:
            return texto
    return texto


def _columna(indice: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(indice)


def _escribir_hoja(ws, hoja: Dict[str, Any], desde_fila: int = 1) -> Dict[str, Any]:
    """Escribe encabezados, filas, totales y formato en una hoja. Return qué se hizo."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    encabezados = hoja["encabezados"]
    filas = hoja["filas"]
    columnas = max([len(encabezados)] + [len(f) for f in filas]) if (encabezados or filas) else 0
    fila_actual = desde_fila
    borde = Border(*(Side(style="thin", color="BBBBBB"),) * 4)

    if encabezados:
        for i, texto in enumerate(encabezados, 1):
            celda = ws.cell(row=fila_actual, column=i, value=texto)
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="305496")
            celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            celda.border = borde
        fila_actual += 1

    primera_dato = fila_actual
    for fila in filas:
        for i, valor in enumerate(fila[:columnas], 1):
            celda = ws.cell(row=fila_actual, column=i, value=_valor_de_celda(valor))
            celda.border = borde
        fila_actual += 1
    ultima_dato = fila_actual - 1

    # Totales: una fila con SUMA en cada columna que sea numérica, y la etiqueta en la primera.
    if hoja.get("totales") and filas and ultima_dato >= primera_dato:
        numericas = []
        for c in range(1, columnas + 1):
            valores = [ws.cell(row=r, column=c).value for r in range(primera_dato, ultima_dato + 1)]
            if valores and all(isinstance(v, (int, float)) or
                               (isinstance(v, str) and v.startswith("=")) for v in valores if v is not None) \
                    and any(isinstance(v, (int, float)) or (isinstance(v, str) and v.startswith("="))
                            for v in valores):
                numericas.append(c)
        if numericas:
            etiqueta = ws.cell(row=fila_actual, column=1, value="Total")
            etiqueta.font = Font(bold=True)
            for c in numericas:
                if c == 1:
                    continue
                letra = get_column_letter(c)
                celda = ws.cell(row=fila_actual, column=c,
                                value=f"=SUM({letra}{primera_dato}:{letra}{ultima_dato})")
                celda.font = Font(bold=True)
                celda.border = borde
            fila_actual += 1

    # Formatos de número por columna: {"B": "#,##0", "D": "0.0%"}.
    for letra, formato in (hoja.get("formatos") or {}).items():
        try:
            for r in range(primera_dato, fila_actual):
                ws[f"{letra}{r}"].number_format = str(formato)
        except Exception as e:
            logger.debug(f"formato «{formato}» no aplicable a la columna {letra}: {e}")

    # Anchos: a la medida del contenido, con tope.
    for c in range(1, columnas + 1):
        letra = get_column_letter(c)
        largo = max((len(str(ws.cell(row=r, column=c).value or ""))
                     for r in range(desde_fila, fila_actual)), default=8)
        ws.column_dimensions[letra].width = min(max(10, largo + 2), _ANCHO_COLUMNA_MAXIMO)

    if encabezados and desde_fila == 1:
        ws.freeze_panes = "A2"
        if ultima_dato >= primera_dato:
            ws.auto_filter.ref = f"A1:{get_column_letter(columnas)}{ultima_dato}"

    grafico = hoja.get("grafico")
    if grafico and filas and ultima_dato >= primera_dato:
        _agregar_grafico(ws, grafico, encabezados, primera_dato, ultima_dato, fila_actual + 2)

    return {"filas": len(filas), "columnas": columnas, "totales": bool(hoja.get("totales"))}


def _agregar_grafico(ws, grafico: Dict[str, Any], encabezados: List[str],
                     primera: int, ultima: int, fila_ancla: int) -> None:
    """Pone un gráfico de barras, líneas o torta con las columnas pedidas."""
    from openpyxl.chart import BarChart, LineChart, PieChart, Reference
    from openpyxl.utils import column_index_from_string

    tipo = str(grafico.get("tipo") or "barras").lower()
    clase = {"barras": BarChart, "columnas": BarChart, "lineas": LineChart, "línea": LineChart,
             "linea": LineChart, "torta": PieChart, "pastel": PieChart, "pie": PieChart}.get(tipo, BarChart)
    chart = clase()
    chart.title = str(grafico.get("titulo") or "")
    if hasattr(chart, "y_axis") and grafico.get("eje_y"):
        chart.y_axis.title = str(grafico["eje_y"])

    columnas = grafico.get("columnas") or ([encabezados[1]] if len(encabezados) > 1 else [])
    categorias = grafico.get("categorias") or (encabezados[0] if encabezados else "A")

    def _indice(referencia: Any) -> int:
        texto = str(referencia)
        if texto in encabezados:
            return encabezados.index(texto) + 1
        try:
            return column_index_from_string(texto.upper())
        except Exception:
            return 2

    for col in columnas:
        c = _indice(col)
        datos = Reference(ws, min_col=c, min_row=primera - 1 if encabezados else primera,
                          max_row=ultima)
        chart.add_data(datos, titles_from_data=bool(encabezados))
    cats = Reference(ws, min_col=_indice(categorias), min_row=primera, max_row=ultima)
    chart.set_categories(cats)
    chart.width, chart.height = 18, 9
    if chart.legend is not None:
        chart.legend.position = "b"          # abajo: a la derecha se corta al imprimir
    ws.add_chart(chart, f"A{fila_ancla}")


def crear_hoja(nombre: str, contenido: Any, plantilla: Optional[str] = None,
               carpeta: Optional[str] = None) -> Resultado:
    """Produce una hoja de cálculo: .xlsx o .csv. Levanta `DocumentoRechazado`.

    `contenido` trae `hojas`, y cada hoja `nombre`, `encabezados`, `filas`, y opcionalmente
    `totales` (fila de sumas), `formatos` (`{"B": "#,##0"}`), `grafico` (`tipo`, `titulo`,
    `columnas`, `categorias`) y `desde` (celda donde empezar, para una plantilla).
    Las celdas que empiezan por `=` son fórmulas y las calcula Excel.
    """
    extension = _extension(nombre)
    if extension not in EXTENSIONES_HOJA:
        raise DocumentoRechazado(f"«{nombre}» no es una hoja de cálculo: hace falta .xlsx o .csv.")
    spec = _como_estructura(contenido)
    rechazar_relleno(spec)
    hojas = _hojas_de(spec)
    destino = carpeta_de_salida(carpeta)
    ruta = ruta_libre(destino, nombre)

    if extension == "csv":
        hoja = hojas[0]
        with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
            escritor = csv.writer(f, delimiter=";")     # el separador que abre Excel en español
            if hoja["encabezados"]:
                escritor.writerow(hoja["encabezados"])
            escritor.writerows(hoja["filas"])
        return Resultado(ruta=str(ruta), formato="csv",
                         detalle=f"{len(hoja['filas'])} filas" +
                                 (", solo la primera hoja" if len(hojas) > 1 else ""))

    from openpyxl import Workbook, load_workbook

    ruta_plantilla = _plantilla_valida(plantilla, ("xlsx",)) if plantilla else None
    if ruta_plantilla:
        wb = load_workbook(str(ruta_plantilla))
    else:
        wb = Workbook()
        wb.remove(wb.active)

    resumen = []
    avisos: List[str] = []
    for hoja in hojas:
        desde_fila = 1
        if ruta_plantilla and hoja["nombre"] in wb.sheetnames:
            ws = wb[hoja["nombre"]]
            celda = str(hoja.get("desde") or "A1").upper()
            desde_fila = int(re.sub(r"[A-Z]+", "", celda) or 1)
            if desde_fila == 1 and ws.max_row > 1:
                # La plantilla ya tiene su encabezado: se escribe debajo de lo que haya.
                desde_fila = ws.max_row + 1
                hoja = {**hoja, "encabezados": []}
        else:
            ws = wb.create_sheet(hoja["nombre"])
        hecho = _escribir_hoja(ws, hoja, desde_fila)
        resumen.append(f"{hoja['nombre']}: {hecho['filas']} filas × {hecho['columnas']} columnas")

    wb.save(str(ruta))
    detalle = "; ".join(resumen)
    if ruta_plantilla:
        detalle += f"; sobre la plantilla {ruta_plantilla.name}"
    return Resultado(ruta=str(ruta), formato="xlsx", detalle=detalle, avisos=avisos)


# ===================================================================== presentaciones

def _diapositivas_de(spec: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if isinstance(spec, list):
        return {}, [d if isinstance(d, dict) else {"titulo": str(d)} for d in spec]
    if not isinstance(spec, dict):
        raise DocumentoRechazado("El contenido de la presentación tiene que ser un objeto con "
                                 "'diapositivas'.")
    diapositivas = spec.get("diapositivas") or spec.get("slides") or []
    cabecera = {k: spec.get(k) for k in ("titulo", "subtitulo") if spec.get(k)}
    return cabecera, [d if isinstance(d, dict) else {"titulo": str(d)} for d in diapositivas]


def _validar_presentacion(cabecera: Dict[str, Any], diapositivas: List[Dict[str, Any]],
                          con_reemplazos: bool) -> None:
    if con_reemplazos and not diapositivas:
        return
    con_contenido = [d for d in diapositivas
                     if d.get("puntos") or d.get("texto") or d.get("tabla") or d.get("imagen")]
    if len(con_contenido) < 2:
        raise DocumentoRechazado(
            "La presentación no tiene contenido suficiente: hacen falta al menos dos "
            "diapositivas con sus puntos o su texto, no solo títulos. Escribila completa."
        )


def _layout(prs, *nombres: str, con_cuerpo: bool = True):
    """Return el diseño de diapositiva que mejor encaja, por nombre o por sus marcadores."""
    from pptx.enum.shapes import PP_PLACEHOLDER

    for nombre in nombres:
        for layout in prs.slide_layouts:
            if layout.name.lower() == nombre.lower():
                return layout
    # Sin coincidencia por nombre: el primero que tenga título y, si hace falta, cuerpo.
    for layout in prs.slide_layouts:
        tipos = {ph.placeholder_format.type for ph in layout.placeholders}
        tiene_titulo = PP_PLACEHOLDER.TITLE in tipos or PP_PLACEHOLDER.CENTER_TITLE in tipos
        tiene_cuerpo = PP_PLACEHOLDER.BODY in tipos or PP_PLACEHOLDER.OBJECT in tipos
        if tiene_titulo and (tiene_cuerpo or not con_cuerpo):
            return layout
    return prs.slide_layouts[0]


def _reemplazar_en_pptx(prs, reemplazos: Dict[str, str]) -> int:
    cuantos = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for parrafo in shape.text_frame.paragraphs:
                    texto = "".join(r.text for r in parrafo.runs)
                    if any(m in texto for m in reemplazos):
                        for m, v in reemplazos.items():
                            cuantos += texto.count(m)
                            texto = texto.replace(m, str(v))
                        if parrafo.runs:
                            parrafo.runs[0].text = texto
                            for r in parrafo.runs[1:]:
                                r.text = ""
            if shape.has_table:
                for fila in shape.table.rows:
                    for celda in fila.cells:
                        for parrafo in celda.text_frame.paragraphs:
                            texto = "".join(r.text for r in parrafo.runs)
                            if any(m in texto for m in reemplazos):
                                for m, v in reemplazos.items():
                                    cuantos += texto.count(m)
                                    texto = texto.replace(m, str(v))
                                if parrafo.runs:
                                    parrafo.runs[0].text = texto
                                    for r in parrafo.runs[1:]:
                                        r.text = ""
    return cuantos


def _quitar_diapositivas(prs) -> None:
    """Deja la presentación sin diapositivas, conservando el patrón, los diseños y el tema."""
    lista = prs.slides._sldIdLst
    for sld_id in list(lista):
        prs.part.drop_rel(sld_id.rId)
        lista.remove(sld_id)


def _pptx(cabecera: Dict[str, Any], diapositivas: List[Dict[str, Any]], ruta: Path,
          plantilla: Optional[Path], reemplazos: Dict[str, str]) -> Resultado:
    from pptx import Presentation
    from pptx.util import Cm, Pt

    from pptx.util import Inches

    prs = Presentation(str(plantilla)) if plantilla else Presentation()
    if not plantilla:
        prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)   # panorámica 16:9
    avisos: List[str] = []
    sustituidos = _reemplazar_en_pptx(prs, reemplazos) if reemplazos else 0
    if reemplazos and not sustituidos:
        avisos.append("Ojo: ninguno de los marcadores que me diste aparece en la plantilla.")
    if plantilla and diapositivas:
        _quitar_diapositivas(prs)

    if cabecera.get("titulo"):
        slide = prs.slides.add_slide(_layout(prs, "Title Slide", "Diapositiva de título",
                                             con_cuerpo=False))
        if slide.shapes.title is not None:
            slide.shapes.title.text = str(cabecera["titulo"])
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == 1 and cabecera.get("subtitulo"):
                ph.text = str(cabecera["subtitulo"])

    for d in diapositivas:
        tiene_cuerpo = bool(d.get("puntos") or d.get("texto"))
        layout = _layout(prs, "Title and Content", "Título y objetos", con_cuerpo=tiene_cuerpo) \
            if tiene_cuerpo else _layout(prs, "Title Only", "Solo el título", con_cuerpo=False)
        slide = prs.slides.add_slide(layout)
        if slide.shapes.title is not None:
            slide.shapes.title.text = str(d.get("titulo") or "")

        # Todo lo que no va en un marcador —tablas, imágenes, texto suelto— se coloca
        # DEBAJO del título, donde termine en este diseño. A una altura fija, en el tema
        # Retrospect la tabla quedaba montada sobre el título.
        titulo_forma = slide.shapes.title
        arriba = (titulo_forma.top + titulo_forma.height + Cm(0.6)) if titulo_forma is not None             else Cm(4.5)
        alto_libre = max(prs.slide_height - arriba - Cm(1.5), Cm(4))

        cuerpo = next((ph for ph in slide.placeholders if ph.placeholder_format.idx == 1), None)
        if tiene_cuerpo and cuerpo is not None:
            tf = cuerpo.text_frame
            tf.clear()
            primero = True
            puntos = d.get("puntos") or ([d["texto"]] if d.get("texto") else [])
            for punto in puntos:
                nivel_items = [(0, punto)] if not isinstance(punto, (list, tuple)) \
                    else [(1, sub) for sub in punto]
                for nivel, texto in nivel_items:
                    p = tf.paragraphs[0] if primero else tf.add_paragraph()
                    primero = False
                    p.text = str(texto)
                    p.level = nivel
        elif tiene_cuerpo:
            caja = slide.shapes.add_textbox(Cm(2), arriba, prs.slide_width - Cm(4), alto_libre)
            tf = caja.text_frame
            tf.word_wrap = True
            for i, punto in enumerate(d.get("puntos") or [d.get("texto")]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = ("• " if d.get("puntos") else "") + str(punto)
                p.font.size = Pt(18)

        tabla = d.get("tabla")
        if isinstance(tabla, dict) and (tabla.get("filas") or tabla.get("encabezados")):
            enc = [str(c) for c in (tabla.get("encabezados") or [])]
            filas = [[("" if c is None else str(c)) for c in f] for f in (tabla.get("filas") or [])]
            cols = max([len(enc)] + [len(f) for f in filas])
            n_filas = len(filas) + (1 if enc else 0)
            alto = min(Cm(0.9) * n_filas, alto_libre)
            forma = slide.shapes.add_table(n_filas, cols, Cm(1.5), arriba,
                                           prs.slide_width - Cm(3), alto)
            r = 0
            if enc:
                for c, texto in enumerate(enc):
                    forma.table.cell(0, c).text = texto
                r = 1
            for fila in filas:
                for c, texto in enumerate(fila[:cols]):
                    forma.table.cell(r, c).text = texto
                r += 1

        imagen = d.get("imagen")
        if imagen:
            if os.path.isfile(str(imagen)):
                try:
                    ancho = prs.slide_width - Cm(4)
                    slide.shapes.add_picture(str(imagen), Cm(2), arriba,
                                             width=ancho if not tiene_cuerpo else ancho // 2)
                except Exception as e:
                    avisos.append(f"No pude insertar la imagen «{os.path.basename(str(imagen))}»: {e}.")
            else:
                avisos.append(f"No encontré la imagen «{imagen}».")

        if d.get("notas"):
            slide.notes_slide.notes_text_frame.text = str(d["notas"])

    prs.save(str(ruta))
    detalle = f"{len(prs.slides)} diapositivas"
    if sustituidos:
        detalle += f", {sustituidos} marcadores rellenados"
    if plantilla:
        detalle += f", con el tema de {plantilla.name}"
    return Resultado(ruta=str(ruta), formato="pptx", detalle=detalle, avisos=avisos)


#: Tema de diseño de Office que se aplica cuando no hay plantilla. Sin esto, python-pptx
#: produce el blanco 4:3 de hace veinte años, y una presentación que parece de 2003 no es un
#: entregable aunque el contenido esté completo. "Retrospect" es sobrio: sirve para una
#: junta y para una clase.
TEMA_POR_DEFECTO = "Retrospect"

_CARPETAS_DE_TEMAS = (
    r"C:\Program Files\Microsoft Office\root\Document Themes 16",
    r"C:\Program Files (x86)\Microsoft Office\root\Document Themes 16",
    r"C:\Program Files\Microsoft Office\Document Themes 16",
)


def temas_disponibles() -> List[str]:
    """Return los nombres de los temas de diseño que Office tiene instalados."""
    for carpeta in _CARPETAS_DE_TEMAS:
        if os.path.isdir(carpeta):
            return sorted(os.path.splitext(f)[0] for f in os.listdir(carpeta)
                          if f.lower().endswith(".thmx"))
    return []


def _ruta_de_tema(nombre: str) -> Optional[str]:
    buscado = str(nombre or "").strip().lower()
    for carpeta in _CARPETAS_DE_TEMAS:
        if not os.path.isdir(carpeta):
            continue
        for archivo in os.listdir(carpeta):
            if archivo.lower().endswith(".thmx") and os.path.splitext(archivo)[0].lower() == buscado:
                return os.path.join(carpeta, archivo)
    return None


def _aplicar_tema(ruta_pptx: str, tema: str) -> bool:
    """Aplica un tema de diseño de Office a una presentación ya guardada. Return si pudo.

    Lo hace el propio PowerPoint: aplicar un tema es recolocar cada marcador según los
    diseños del tema, y eso python-pptx no lo sabe hacer.
    """
    thmx = _ruta_de_tema(tema)
    if not thmx or os.name != "nt":
        return False
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False

    pythoncom.CoInitialize()
    app = None
    try:
        app = win32com.client.DispatchEx("PowerPoint.Application")
        pres = app.Presentations.Open(ruta_pptx, ReadOnly=False, WithWindow=False)
        pres.ApplyTheme(thmx)
        pres.Save()
        pres.Close()
        return True
    except Exception as e:
        logger.warning(f"no se pudo aplicar el tema «{tema}»: {e}")
        return False
    finally:
        try:
            if app is not None:
                app.Quit()
        except Exception as e:
            logger.debug(f"PowerPoint no cerró limpio: {e}")
        pythoncom.CoUninitialize()


def crear_presentacion(nombre: str, contenido: Any, plantilla: Optional[str] = None,
                       reemplazos: Optional[Dict[str, str]] = None,
                       carpeta: Optional[str] = None, tema: Optional[str] = None) -> Resultado:
    """Produce una presentación .pptx (o su .pdf). Levanta `DocumentoRechazado`.

    `contenido` trae `titulo`, `subtitulo` y `diapositivas`; cada una `titulo`, `puntos`
    (una lista dentro de la lista es un subnivel), `texto`, `tabla` (`encabezados`,
    `filas`), `imagen` (ruta) y `notas` para el orador.
    """
    extension = _extension(nombre)
    if extension not in EXTENSIONES_PRESENTACION + ("pdf",):
        raise DocumentoRechazado(f"«{nombre}» no es una presentación: hace falta .pptx (o .pdf).")
    reemplazos = {str(k): str(v) for k, v in (reemplazos or {}).items()}
    spec = _como_estructura(contenido)
    rechazar_relleno(spec)
    cabecera, diapositivas = _diapositivas_de(spec)
    _validar_presentacion(cabecera, diapositivas, con_reemplazos=bool(reemplazos))
    destino = carpeta_de_salida(carpeta)
    ruta = ruta_libre(destino, nombre)
    ruta_plantilla = _plantilla_valida(plantilla, ("pptx",)) if plantilla else None

    def _producir(destino_pptx: Path) -> Resultado:
        resultado = _pptx(cabecera, diapositivas, destino_pptx, ruta_plantilla, reemplazos)
        if ruta_plantilla is None:
            elegido = str(tema or TEMA_POR_DEFECTO)
            if _ruta_de_tema(elegido) is None:
                resultado.avisos.append(
                    f"No existe el tema «{elegido}» en este Office; los que hay: "
                    f"{', '.join(temas_disponibles()[:12]) or 'ninguno'}. Quedó con el diseño básico."
                )
            elif _aplicar_tema(str(destino_pptx), elegido):
                resultado.detalle += f", tema {elegido}"
            else:
                resultado.avisos.append("No pude aplicar el tema de diseño (hace falta "
                                        "PowerPoint); quedó con el diseño básico.")
        return resultado

    if extension == "pptx":
        return _producir(ruta)

    with tempfile.TemporaryDirectory() as temporal:
        intermedio = Path(temporal) / (ruta.stem + ".pptx")
        resultado = _producir(intermedio)
        pdf_temporal = Path(temporal) / (ruta.stem + ".pdf")
        if _con_office("PowerPoint", str(intermedio), str(pdf_temporal)):
            os.replace(str(pdf_temporal), str(ruta))
            return Resultado(ruta=str(ruta), formato="pdf",
                             detalle=resultado.detalle + ", convertido con PowerPoint",
                             avisos=resultado.avisos)
    raise DocumentoRechazado(
        "Para pasar una presentación a PDF hace falta PowerPoint y no pude usarlo. Te la "
        "puedo hacer en .pptx."
    )


# ============================================================================ otros

def crear_archivo(nombre: str, contenido: Any, carpeta: Optional[str] = None) -> Resultado:
    """Produce cualquier otro archivo de texto (.json, .csv suelto, .sql, .py, lo que sea)."""
    extension = _extension(nombre)
    if not extension:
        raise DocumentoRechazado("El nombre del archivo tiene que llevar extensión.")
    spec = _como_estructura(contenido)
    rechazar_relleno(spec)
    destino = carpeta_de_salida(carpeta)
    ruta = ruta_libre(destino, nombre)

    if extension in EXTENSIONES_DATOS and not isinstance(spec, str):
        ruta.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        return Resultado(ruta=str(ruta), formato="json", detalle="JSON con sangría")

    texto = spec if isinstance(spec, str) else json.dumps(spec, ensure_ascii=False, indent=2)
    if not texto.strip():
        raise DocumentoRechazado("El archivo quedaría vacío: no hay contenido que escribir.")
    ruta.write_text(texto, encoding="utf-8")
    return Resultado(ruta=str(ruta), formato=extension,
                     detalle=f"{len(texto.splitlines())} líneas")


# ======================================================================= PDF con Office

def _con_office(aplicacion: str, origen: str, destino_pdf: str) -> bool:
    """Convierte con Word, Excel o PowerPoint en una instancia propia e invisible. Return si pudo.

    Instancia propia (`DispatchEx`) y no la que el usuario tenga abierta: cerrar la nuestra
    al terminar no puede llevarse la suya, ni su documento a medio escribir.
    """
    if os.name != "nt":
        return False
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False

    pythoncom.CoInitialize()
    app = None
    try:
        if aplicacion == "Word":
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible = False
            doc = app.Documents.Open(origen, ReadOnly=True)
            doc.ExportAsFixedFormat(destino_pdf, 17)        # wdExportFormatPDF
            doc.Close(False)
        elif aplicacion == "Excel":
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible = False
            app.DisplayAlerts = False
            libro = app.Workbooks.Open(origen, ReadOnly=True)
            libro.ExportAsFixedFormat(0, destino_pdf)          # xlTypePDF
            libro.Close(False)
        elif aplicacion == "PowerPoint":
            app = win32com.client.DispatchEx("PowerPoint.Application")
            pres = app.Presentations.Open(origen, ReadOnly=True, WithWindow=False)
            pres.SaveAs(destino_pdf, 32)                       # ppSaveAsPDF
            pres.Close()
        else:
            return False
        return os.path.isfile(destino_pdf)
    except Exception as e:
        logger.warning(f"no se pudo convertir a PDF con {aplicacion}: {e}")
        return False
    finally:
        try:
            if app is not None:
                app.Quit()
        except Exception as e:
            logger.debug(f"{aplicacion} no cerró limpio: {e}")
        pythoncom.CoUninitialize()


def convertir_a_pdf(ruta: str, carpeta: Optional[str] = None) -> Resultado:
    """Convierte un .docx, .xlsx o .pptx existente a PDF con Office. Levanta si no se puede."""
    origen = Path(os.path.expanduser(str(ruta or "").strip()))
    if not origen.is_file():
        raise DocumentoRechazado(f"No encuentro «{ruta}».")
    aplicacion = {"docx": "Word", "doc": "Word", "xlsx": "Excel", "xls": "Excel",
                  "pptx": "PowerPoint", "ppt": "PowerPoint"}.get(_extension(origen.name))
    if aplicacion is None:
        raise DocumentoRechazado(f"No sé convertir «{origen.name}» a PDF: solo Word, Excel y PowerPoint.")
    destino = carpeta_de_salida(carpeta) if carpeta else origen.parent
    salida = ruta_libre(destino, origen.stem + ".pdf")
    if not _con_office(aplicacion, str(origen), str(salida)):
        raise DocumentoRechazado(f"No pude convertir «{origen.name}» con {aplicacion}. "
                                 f"¿Está instalado y sin diálogos abiertos?")
    return Resultado(ruta=str(salida), formato="pdf", detalle=f"convertido con {aplicacion}")


# ======================================================================== inspeccionar

_MARCADOR_RE = re.compile(r"\{\{[^}]{1,60}\}\}|\[[A-ZÁÉÍÓÚÑ_ ]{2,40}\]|<<[^>]{1,60}>>|«[A-ZÁÉÍÓÚÑ_ ]{2,40}»")


def inspeccionar(ruta: str) -> str:
    """Return qué tiene una plantilla: estilos, diseños, hojas y marcadores. Para usarla bien.

    Sin esto, seguir una plantilla es adivinar cómo se llaman sus estilos y sus marcadores.
    """
    archivo = Path(os.path.expanduser(str(ruta or "").strip()))
    if not archivo.is_file():
        for base in [_escritorio(), Path.home() / "Documents", Path.home() / "OneDrive" / "Documentos",
                     Path.home() / "Downloads"]:
            if (base / archivo).is_file():
                archivo = base / archivo
                break
    if not archivo.is_file():
        return f"No encuentro «{ruta}»."

    extension = _extension(archivo.name)
    try:
        if extension == "docx":
            return _inspeccionar_docx(archivo)
        if extension == "xlsx":
            return _inspeccionar_xlsx(archivo)
        if extension == "pptx":
            return _inspeccionar_pptx(archivo)
    except Exception as e:
        logger.warning(f"no se pudo inspeccionar {archivo}: {e}")
        return f"Pude abrir «{archivo.name}» pero no leer su estructura: {type(e).__name__}."
    return f"«{archivo.name}» no es un documento de Office que sepa inspeccionar (.docx, .xlsx, .pptx)."


def _marcadores_en(texto: str) -> List[str]:
    return sorted(set(_MARCADOR_RE.findall(texto or "")))


def _inspeccionar_docx(archivo: Path) -> str:
    from docx import Document

    doc = Document(str(archivo))
    usados = []
    textos = []
    for p in doc.paragraphs:
        if p.text.strip():
            textos.append(p.text.strip())
            if p.style is not None and p.style.name not in usados:
                usados.append(p.style.name)
    for t in doc.tables:
        for fila in t.rows:
            for c in fila.cells:
                textos.append(c.text)
    encabezados = []
    for s in doc.sections:
        for parte, nombre in ((s.header, "encabezado"), (s.footer, "pie")):
            contenido = " / ".join(p.text.strip() for p in parte.paragraphs if p.text.strip())
            if contenido:
                encabezados.append(f"{nombre}: {contenido[:120]}")
                textos.append(contenido)
    marcadores = _marcadores_en("\n".join(textos))
    lineas = [f"Plantilla Word «{archivo.name}»: {len(doc.paragraphs)} párrafos, "
              f"{len(doc.tables)} tablas, {len(doc.sections)} sección(es)."]
    if usados:
        lineas.append("Estilos que usa: " + ", ".join(usados[:15]))
    if encabezados:
        lineas += ["Encabezados y pies:"] + [f"  {e}" for e in encabezados]
    if marcadores:
        lineas.append("Marcadores para rellenar (pasalos en 'reemplazos'): " + ", ".join(marcadores))
    muestra = [t for t in textos if t][:6]
    if muestra:
        lineas += ["Empieza así:"] + [f"  {t[:100]}" for t in muestra]
    return "\n".join(lineas)


def _inspeccionar_xlsx(archivo: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(archivo), read_only=True)
    lineas = [f"Plantilla Excel «{archivo.name}»: {len(wb.sheetnames)} hoja(s)."]
    textos = []
    for ws in wb.worksheets:
        encabezado = []
        for fila in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            encabezado = [str(c) for c in fila if c is not None]
        for fila in ws.iter_rows(min_row=1, max_row=min(ws.max_row or 1, 30), values_only=True):
            textos += [str(c) for c in fila if isinstance(c, str)]
        lineas.append(f"  «{ws.title}»: {ws.max_row} filas × {ws.max_column} columnas"
                      + (f"; encabezado: {', '.join(encabezado[:12])}" if encabezado else ""))
    marcadores = _marcadores_en("\n".join(textos))
    if marcadores:
        lineas.append("Marcadores: " + ", ".join(marcadores))
    lineas.append("Para escribir en una hoja existente usá su mismo 'nombre' y, si hace falta, 'desde'.")
    return "\n".join(lineas)


def _inspeccionar_pptx(archivo: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(archivo))
    lineas = [f"Plantilla PowerPoint «{archivo.name}»: {len(prs.slides)} diapositivas, "
              f"{len(prs.slide_layouts)} diseños."]
    lineas.append("Diseños disponibles: " + ", ".join(f"«{l.name}»" for l in prs.slide_layouts))
    textos = []
    for i, slide in enumerate(prs.slides, 1):
        titulo = slide.shapes.title.text if slide.shapes.title is not None else ""
        for shape in slide.shapes:
            if shape.has_text_frame:
                textos.append(shape.text_frame.text)
        if i <= 8:
            lineas.append(f"  {i}. {titulo[:80] or '(sin título)'}")
    marcadores = _marcadores_en("\n".join(textos))
    if marcadores:
        lineas.append("Marcadores para rellenar (pasalos en 'reemplazos'): " + ", ".join(marcadores))
    return "\n".join(lineas)
