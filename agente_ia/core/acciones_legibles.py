"""
core/acciones_legibles.py
Cómo se le NOMBRA al humano lo que se le está pidiendo autorizar.

Hasta ahora la pregunta salía con el nombre interno de la función:

    ¿Estás seguro de que quieres ejecutar 'terminal_run_command'?
    ¿Estás seguro de que quieres ejecutar 'pc_key'?   (por voz sonaba "ejecutar kit")

Eso es pedirle permiso a alguien en un idioma que no habla. Y una confirmación que no se
entiende no es una confirmación: o se dice que sí a ciegas, o se dice que no por las dudas.
Las dos son malas, y la primera es peor.

Acá vive la traducción. El detalle concreto —qué comando, a quién, qué archivo— NO se toca:
sigue viniendo de `format_details()` y sigue siendo lo que liga el permiso a la acción
puntual. Lo que cambia es el envoltorio.
"""

import logging
import re
from typing import Dict

logger = logging.getLogger(__name__)

#: Qué hace cada acción, dicho como se lo diría una persona a otra. El texto completa la
#: frase "¿Quieres que ...?", así que va en infinitivo y sin nombres de función.
#:
#: Están las 35 amarillas y las 11 rojas que hoy pueden pedir autorización. Una acción que
#: falte no rompe nada: `describir()` la deja legible por su cuenta. Pero conviene sumarla
#: acá, porque escrita a mano siempre se lee mejor que derivada.
_DESCRIPCIONES: Dict[str, str] = {
    # ── Aplicaciones y sistema ──
    "CLOSE_APP": "cierre una aplicación",
    "close_app": "cierre una aplicación",
    "SYS_POWER_OFF": "apague el computador",
    "shutdown": "apague el computador",
    "restart": "reinicie el computador",

    # ── Ratón y teclado ──
    "PC_CLICK": "haga clic en la pantalla",
    "pc_click": "haga clic en la pantalla",
    "PC_TYPE": "escriba con el teclado",
    "pc_type": "escriba con el teclado",
    "pc_key": "pulse una tecla",
    "PC_SCROLL": "desplace la pantalla",
    "pc_scroll": "desplace la pantalla",
    "pc_enable_tree": "lea lo que hay en pantalla",

    # ── Terminal ──
    "terminal_open": "abra una terminal",
    "terminal_run_command": "ejecute un comando en la terminal",
    "terminal_read_output": "lea lo que hay escrito en la terminal",

    # ── Archivos ──
    "delete_file": "borre un archivo",
    "delete_folder": "borre una carpeta",
    "save_file_desktop": "guarde un archivo en el escritorio",
    "write_file_direct": "escriba un archivo",
    # REQ-029 — las dos amarillas de las herramientas de repositorio. Las 6 verdes (leer,
    # listar, buscar, git status/diff/log) nunca preguntan, así que no necesitan traducción.
    "file_write": "cree o reescriba un archivo del repositorio",
    "file_edit": "cambie un fragmento de un archivo del repositorio",
    # REQ-030 — la frase dice "para trabajar" a propósito: quien confirma tiene que
    # entender que está dando permiso permanente sobre esa carpeta, no autorizando una
    # operación suelta.
    "workspace_add_folder": "habilite una carpeta para trabajar con sus archivos",
    "workspace_remove_folder": "deje de tener acceso a una carpeta de trabajo",
    # REQ-031 — la frase dice "mande datos" a propósito: lo que hay que entender al
    # confirmar es que algo sale del equipo hacia afuera, no que se hace una petición.
    "http_request": "llame a un servicio de internet y le mande datos",
    # REQ-032 — la frase nombra la carpeta a proposito: lo que hay que entender al
    # confirmar es que algo se va a EJECUTAR en tu proyecto, no que se abre una app.
    "project_run": "ejecute un comando dentro de la carpeta del proyecto",
    # REQ-035 — las dos del refactor. "borre" y "mueva" en castellano llano: lo que hay que
    # entender al confirmar es que un archivo va a dejar de estar donde estaba.
    "file_delete": "borre un archivo del repositorio",
    "file_move": "mueva o renombre un archivo del repositorio",
    # REQ-036 — la unica amarilla de las tres: leer la salida y detener lo que el propio
    # agente levanto no necesitan permiso aparte.
    "project_start": "deje corriendo un programa del proyecto en segundo plano",

    # ── Código y habilidades ──
    "EXECUTE_CODE": "ejecute un programa que acabo de escribir",
    "execute_code": "ejecute un programa que acabo de escribir",
    "CREATE_SKILL": "cree una habilidad nueva",
    "create_skill": "cree una habilidad nueva",
    "MODIFY_SKILL": "modifique una de mis habilidades",
    "modify_skill": "modifique una de mis habilidades",
    "DELETE_SKILL": "borre una de mis habilidades",
    "delete_skill": "borre una de mis habilidades",

    # ── Correo y mensajes ──
    "SEND_EMAIL": "envíe un correo",
    "send_email_as_user": "envíe un correo en su nombre",
    "MARK_EMAIL_READ": "marque un correo como leído",
    "SAVE_EMAIL_ATTACHMENT": "guarde un archivo adjunto de un correo",
    "send_message": "envíe un mensaje",
    "post_social_media": "publique algo en sus redes sociales",

    # ── Datos y memoria ──
    "delete_conversation": "borre una conversación",
    "delete_project": "borre un proyecto",
    "delete_task": "borre una tarea",
    "delete_database": "borre su base de datos de memoria",
    "UPDATE_MEMORY_FILE": "actualice lo que recuerdo sobre usted",

    # ── Flujos ──
    "CREATE_FLOW": "cree un flujo de trabajo",

    # ── Las que nunca deberían llegar sin permiso explícito ──
    "format_disk": "formatee un disco",
    "modify_source_code": "modifique mi propio código",
    "expose_secrets": "muestre sus claves y contraseñas",
    "elevated_system_command": "ejecute algo como administrador",
    "install_uninstall_software": "instale o desinstale un programa",
    "modify_system_env_vars": "cambie las variables de entorno del sistema",
    "grant_third_party_access": "le dé acceso a un tercero",
}

#: Trozos del nombre interno que no le dicen nada a nadie. Se quitan al derivar una
#: descripción para una acción que no está en el diccionario.
_RUIDO = ("_tool", "_invoke", "_action", "handle_", "_handler")


def describir(action_name: str) -> str:
    """Return qué hace `action_name`, en español llano y en infinitivo.

    Para lo que no está en el diccionario, se deriva del propio nombre —guiones bajos a
    espacios, sin sufijos técnicos— en vez de mostrarlo crudo. No queda perfecto, pero
    "ejecute terminal run command" se entiende y `terminal_run_command` no.
    """
    nombre = (action_name or "").strip()
    if not nombre:
        return "ejecute una acción"

    if nombre in _DESCRIPCIONES:
        return _DESCRIPCIONES[nombre]

    derivado = nombre
    for ruido in _RUIDO:
        derivado = derivado.replace(ruido, "")
    derivado = re.sub(r"[_\-]+", " ", derivado).strip().lower()
    logger.debug(f"acción sin descripción legible: '{action_name}' -> '{derivado}'")
    return f"ejecute {derivado}" if derivado else "ejecute una acción"


def pregunta(action_name: str, detalle: str = "") -> str:
    """Return la pregunta completa de autorización, lista para leer o escuchar.

    `detalle` es lo que ya arma `format_details()`, y se cuela por `detalle_legible()`
    para que tampoco entre con forma de log.
    """
    texto = f"¿Quiere que {describir(action_name)}"
    concreto = detalle_legible(detalle)
    if concreto:
        texto += f": {concreto}"
    return texto + "?"


#: Cómo se nombra cada dato del detalle. Lo que no esté acá se muestra solo con su valor:
#: mejor un dato suelto que un `skill_name=` delante.
_ETIQUETAS = {
    "app_name": "", "app": "", "command": "", "path": "", "filename": "",
    "folder": "", "query": "", "url": "", "name": "", "task": "", "raw_text": "",
    "skill_name": "la habilidad", "destinatario": "para", "asunto": "asunto",
    "direction": "hacia",
}


def detalle_legible(detalle: str) -> str:
    """Return el detalle sin la forma de línea de log.

    `format_details()` produce `"dispatch:CLOSE_APP | app_name=chrome"`, que es exactamente
    lo que hay que registrar en la auditoría y exactamente lo que no hay que enseñarle a
    alguien a quien se le está pidiendo permiso. Se queda con los valores, que es lo que de
    verdad decide el permiso: no es lo mismo autorizar "cierre una aplicación" que
    "cierre una aplicación: chrome".
    """
    texto = (detalle or "").strip()
    if not texto:
        return ""

    # El prefijo ("dispatch:CLOSE_APP", "webview:delete_conversation") es trazabilidad
    # interna: identifica el camino de invocación, no lo que se va a hacer.
    cuerpo = texto.split("|", 1)[1] if "|" in texto else ""
    if not cuerpo.strip():
        return ""

    partes = []
    for trozo in cuerpo.split(","):
        clave, sep, valor = trozo.partition("=")
        if not sep:
            continue
        valor = valor.strip()
        if not valor:
            continue
        etiqueta = _ETIQUETAS.get(clave.strip(), clave.strip())
        partes.append(f"{etiqueta} {valor}".strip() if etiqueta else valor)
    return ", ".join(partes)
