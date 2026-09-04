import os
import re
from typing import Dict, List, Tuple, Any
from skills.base_skill import BaseSkill
from ai.llm_provider import generate_response
from core.address import vocative, vocative_start

#: Ruta absoluta dentro de un texto: "C:\Users\yo\informe.pdf" o "/home/yo/informe.pdf".
#: Se corta en el corchete de cierre para que el marcador "[Archivo adjunto: ...]" no se
#: lleve el corchete pegado al nombre.
_RUTA_ABSOLUTA = re.compile(
    r"([A-Za-z]:\\[^\n\]\"<>|?*]+\.\w{2,5}"     # C:\Users\yo\informe.pdf
    r"|/[^\s\]\"<>|?*]+\.\w{2,5})"              # /home/yo/informe.pdf
)


class FileAnalysisSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "FileAnalysisSkill"

    @property
    def description(self) -> str:
        return "Lee el contenido de un archivo y genera un resumen usando el LLM."

    def get_intents(self) -> List[str]:
        return ["FILE_ANALYSIS"]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("analiza el archivo reporte", "FILE_ANALYSIS"),
            ("resumen del documento de notas", "FILE_ANALYSIS"),
            ("lee este archivo y dame un resumen de codigo.py", "FILE_ANALYSIS"),
            ("dame un resumen de documento.txt", "FILE_ANALYSIS"),
            ("analiza el contenido de", "FILE_ANALYSIS"),
            ("que dice el archivo", "FILE_ANALYSIS"),
            ("haz un resumen de", "FILE_ANALYSIS")
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        import re
        params = {}
        # Busca algo como "analiza el archivo [nombre]" o "resumen de [nombre]"
        m = re.search(r'(?:analiza el archivo|resumen de(?:l)?(?: documento| archivo)?|que dice el archivo|haz un resumen de)\s+(.+)', text.lower())
        if m:
            params["filename"] = m.group(1).strip()
        elif _RUTA_ABSOLUTA.search(text):
            # Una ruta completa en el texto es la referencia mas fuerte que puede haber, y
            # es lo que manda el adjunto del panel de escritorio ("[Archivo adjunto: ...]").
            # Antes ganaba el fallback de mas abajo, que se quedaba solo con el nombre del
            # archivo y despues lo buscaba en el Escritorio y en Documentos: si estaba en
            # cualquier otra carpeta, no aparecia.
            params["filename"] = _RUTA_ABSOLUTA.search(text).group(1).strip()
        else:
            # Fallback a capturar cualquier extension de archivo si la hay
            nums_out = re.findall(r'\b([\w\-.]+\.\w{2,4})\b', text)
            if nums_out:
                params["filename"] = nums_out[0]
            else:
                params["filename"] = text.replace("analiza", "").replace("resumen", "").strip()
        return params

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        filename = params.get("filename", "").strip()
        if not filename:
            return f"{vocative_start()}no logré identificar el nombre del archivo que desea que analice."

        # Buscar el archivo en el directorio actual o en rutas comunes
        target_path = None
        
        # 1. Rutas absolutas
        if os.path.isabs(filename) and os.path.exists(filename):
            target_path = filename
            
        # 2. Directorio actual
        elif os.path.exists(filename):
            target_path = filename
            
        # 3. Escritorio / Documentos / Descargas
        else:
            home = os.path.expanduser("~")
            base_name = os.path.basename(filename)
            common_dirs = [
                os.path.join(home, "Desktop"),
                os.path.join(home, "OneDrive", "Escritorio"),
                os.path.join(home, "Documents"),
                os.path.join(home, "OneDrive", "Documentos"),
                os.path.join(home, "Downloads"),
                os.getcwd()
            ]
            
            for d in common_dirs:
                if os.path.exists(d):
                    # Búsqueda simple en el primer nivel
                    for f in os.listdir(d):
                        if base_name.lower() in f.lower():
                            target_path = os.path.join(d, f)
                            break
                if target_path:
                    break

        if not target_path:
            return f"Lo lamento{vocative()}. No pude encontrar el archivo '{filename}'."

        if not os.path.isfile(target_path):
            return f"{vocative_start()}'{target_path}' no es un archivo válido o es un directorio."

        # Identificar extensión
        ext = os.path.splitext(target_path)[1].lower()
        content = ""
        
        try:
            if ext == ".pdf":
                try:
                    import PyPDF2
                    with open(target_path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        text_pages = []
                        # Leer hasta las primeras 10 páginas para no desbordar al LLM
                        for i in range(min(10, len(reader.pages))):
                            text_pages.append(reader.pages[i].extract_text() or "")
                        content = "\n".join(text_pages)[:10000]
                except ImportError:
                    return f"{vocative_start()}para leer PDFs necesito la librería 'PyPDF2'. Puede instalarla ejecutando: pip install PyPDF2"
            
            elif ext in [".docx", ".doc"]:
                try:
                    import docx
                    doc = docx.Document(target_path)
                    full_text = [para.text for para in doc.paragraphs]
                    content = "\n".join(full_text)[:10000]
                except ImportError:
                    return f"{vocative_start()}para leer documentos de Word necesito la librería 'python-docx'. Puede instalarla ejecutando: pip install python-docx"
            
            elif ext in [".xlsx", ".xls"]:
                try:
                    import pandas as pd
                    # Leer la primera hoja y convertir las primeras filas a formato CSV/Texto
                    df = pd.read_excel(target_path, sheet_name=0)
                    content = df.head(100).to_csv(index=False)[:10000]
                except ImportError:
                    return f"{vocative_start()}para leer archivos Excel necesito las librerías 'pandas' y 'openpyxl'. Instálelas con: pip install pandas openpyxl"
                    
            else:
                # Lectura como texto plano por defecto (txt, py, json, md, csv, etc)
                with open(target_path, "r", encoding="utf-8") as f:
                    content = f.read(10000)
                    
            if len(content) == 10000:
                content += "\n... [Contenido truncado]"
                
        except UnicodeDecodeError:
            return f"{vocative_start()}el archivo parece tener una codificación extraña o binaria que no puedo procesar directamente."
        except Exception as e:
            return f"Hubo un error al intentar leer y analizar el archivo: {e}"

        # Preparar llamada a LLM
        system_prompt = "Eres un asistente formal y profesional. Analiza el siguiente contenido de archivo y proporciona un resumen conciso y claro de sus puntos más importantes o su estructura general."
        messages = [{"role": "user", "content": f"Por favor, dame un resumen de este archivo:\n\n{content}"}]

        response = generate_response(messages, system_prompt)
        
        return f"Análisis del archivo '{os.path.basename(target_path)}':\n\n{response}"
