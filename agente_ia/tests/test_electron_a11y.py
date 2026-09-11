"""
tests/test_electron_a11y.py
Pruebas de `os_integration/electron_a11y.py` — encender el árbol de las apps Electron.

Dos cosas distintas se protegen aquí, y las dos hacen daño de forma distinta si fallan:

1. **Que se detecte el caso.** Una ventana Electron devuelve los botones de su marco y
   nada más. Si eso se confunde con "no está el control", el agente cae a la visión y
   adivina coordenadas para siempre, cuando bastaba con encender el árbol.
2. **Que la edición no rompa nada.** `argv.json` es del usuario, lleva comentarios y un
   `crash-reporter-id` que no se debe perder. Reescribirlo con `json.dump` lo dejaría
   limpio de comentarios; dejarlo con un JSON inválido haría que VS Code arrancara por
   defecto sin que nadie supiera por qué.

Ningún test toca el `argv.json` real: el home va redirigido a `tmp_path`.
"""

import json
import os

import pytest

from os_integration import electron_a11y as a11y


ARGV_REAL = """\
// This configuration file allows you to pass permanent command line arguments to VS Code.
// Only a subset of arguments is currently supported.
//
// NOTE: Changing this file requires a restart of VS Code.
{
\t// Use software rendering instead of hardware accelerated rendering.
\t// "disable-hardware-acceleration": true,

\t"enable-crash-reporter": true,

\t// Do not edit this value.
\t"crash-reporter-id": "ac7294c5-e157-4b10-bb3b-4e54f346d8a8"
}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Redirige el home para no tocar la configuración real de VS Code."""
    monkeypatch.setattr(a11y.os.path, "expanduser", lambda _: str(tmp_path))
    return tmp_path


def _escribir_argv(home, contenido=ARGV_REAL, app="vscode"):
    ruta = home / a11y.APPS[app]["argv"]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


class _Elem:
    def __init__(self, nombre):
        self.nombre = nombre


# ── Reconocer la aplicación ─────────────────────────────────────────

def test_se_reconoce_vs_code_por_el_titulo():
    assert a11y.detectar_app("main.py - agente_ia - Visual Studio Code") == "vscode"


def test_insiders_no_se_confunde_con_vs_code():
    """El título de Insiders contiene el de VS Code: gana la pista más larga."""
    assert a11y.detectar_app("x - Visual Studio Code - Insiders") == "vscode-insiders"


def test_una_aplicacion_desconocida_no_se_inventa():
    assert a11y.detectar_app("Documento1 - Word") is None


# ── Distinguir "árbol apagado" de "aquí no hay nada" ────────────────

def test_una_ventana_electron_muda_se_reconoce():
    elementos = [_Elem("Close"), _Elem("Chrome Legacy Window")]

    assert a11y.parece_electron_sin_arbol(elementos, "x - Visual Studio Code") is True


def test_con_el_arbol_encendido_ya_no_es_el_caso():
    """El marcador sigue ahí con el flag activo: VS Code tenía además otros 220 controles."""
    elementos = [_Elem("Chrome Legacy Window")] + [_Elem(f"Botón {i}") for i in range(40)]

    assert a11y.parece_electron_sin_arbol(elementos, "x - Visual Studio Code") is False


def test_una_app_conocida_sin_nada_tambien_cuenta():
    assert a11y.parece_electron_sin_arbol([], "x - Cursor") is True


def test_una_ventana_normal_con_pocos_controles_no_es_el_caso():
    """Un diálogo pequeño tiene tres botones y está perfectamente sano."""
    elementos = [_Elem("Aceptar"), _Elem("Cancelar")]

    assert a11y.parece_electron_sin_arbol(elementos, "Guardar cambios") is False


# ── Leer JSONC ──────────────────────────────────────────────────────

def test_se_leen_los_flags_con_comentarios_de_por_medio(home):
    _escribir_argv(home)

    assert a11y.leer_flags("vscode")["enable-crash-reporter"] is True


def test_una_barra_dentro_de_un_texto_no_se_toma_por_comentario():
    texto = '{"ruta": "http://x//y", "a": 1}'

    assert json.loads(a11y._sin_comentarios(texto))["ruta"] == "http://x//y"


def test_los_comentarios_de_bloque_tambien_se_quitan():
    texto = '{/* fuera */ "a": 1}'

    assert json.loads(a11y._sin_comentarios(texto)) == {"a": 1}


def test_una_coma_colgante_no_rompe_la_lectura():
    assert json.loads(a11y._sin_comentarios('{"a": 1,}')) == {"a": 1}


def test_sin_archivo_no_hay_flags_y_no_revienta(home):
    assert a11y.leer_flags("vscode") == {}
    assert a11y.esta_activo("vscode") is False


def test_un_archivo_corrupto_se_reporta_vacio(home):
    _escribir_argv(home, "{ esto no es json")

    assert a11y.leer_flags("vscode") == {}


# ── Encontrar dónde insertar ────────────────────────────────────────

def test_la_llave_de_los_comentarios_de_cabecera_no_cuenta():
    """El archivo real empieza con seis líneas de comentario; una `{` ahí sería la falsa."""
    texto = "// ejemplo: { no es esta }\n{\n\t\"a\": 1\n}"

    assert texto[a11y._pos_llave_raiz(texto)] == "{"
    assert a11y._pos_llave_raiz(texto) > texto.index("\n")


def test_una_llave_dentro_de_un_texto_tampoco_cuenta():
    texto = '// nada\n{"plantilla": "{x}"}'

    assert a11y._pos_llave_raiz(texto) == texto.index('{"plantilla"')


# ── Activar ─────────────────────────────────────────────────────────

def test_activar_escribe_el_flag(home):
    _escribir_argv(home)

    cambio, mensaje = a11y.activar("vscode")

    assert cambio is True
    assert a11y.esta_activo("vscode") is True
    assert "reiniciar" in mensaje.lower()


def test_activar_conserva_los_comentarios_y_el_identificador(home):
    """Reescribir el archivo con `json.dump` los perdería: por eso se inserta una línea."""
    ruta = _escribir_argv(home)

    a11y.activar("vscode")

    texto = ruta.read_text(encoding="utf-8")
    assert "PLEASE DO NOT" in texto or "NOTE: Changing this file" in texto
    assert "// Use software rendering" in texto
    assert a11y.leer_flags("vscode")["crash-reporter-id"] == "ac7294c5-e157-4b10-bb3b-4e54f346d8a8"


def test_activar_deja_copia_del_original(home):
    ruta = _escribir_argv(home)

    a11y.activar("vscode")

    copia = str(ruta) + ".orion-backup"
    assert os.path.isfile(copia)
    assert open(copia, encoding="utf-8").read() == ARGV_REAL


def test_activar_dos_veces_no_duplica_el_flag(home):
    ruta = _escribir_argv(home)
    a11y.activar("vscode")

    cambio, mensaje = a11y.activar("vscode")

    assert cambio is False
    assert ruta.read_text(encoding="utf-8").count(a11y.FLAG) == 1
    assert "ya tiene" in mensaje


def test_sin_configuracion_se_explica_en_vez_de_crearla(home):
    """Inventar un argv.json donde no había puede dejar la aplicación en un estado raro."""
    cambio, mensaje = a11y.activar("vscode")

    assert cambio is False
    assert "no encontré" in mensaje.lower()


def test_un_archivo_ilegible_no_se_sobrescribe(home):
    """Si no se entiende lo que hay, se deja como está: es configuración del usuario."""
    ruta = _escribir_argv(home, "esto no tiene forma de objeto")

    cambio, _ = a11y.activar("vscode")

    assert cambio is False
    assert ruta.read_text(encoding="utf-8") == "esto no tiene forma de objeto"


def test_si_la_insercion_dejara_un_json_invalido_no_se_escribe(home):
    """Con un argv.json roto VS Code arranca por defecto y nadie sabe por qué."""
    ruta = _escribir_argv(home, "{ ][ }")

    cambio, mensaje = a11y.activar("vscode")

    assert cambio is False
    assert ruta.read_text(encoding="utf-8") == "{ ][ }"
    assert "no modifiqué nada" in mensaje.lower()


def test_una_aplicacion_que_no_se_conoce_se_rechaza(home):
    cambio, mensaje = a11y.activar("bloc-de-notas")

    assert cambio is False
    assert "no sé cómo" in mensaje.lower()


# ── Lo que se le dice al modelo ─────────────────────────────────────

def test_el_diagnostico_ofrece_encender_el_arbol(home):
    _escribir_argv(home)

    texto = a11y.diagnostico("main.py - Visual Studio Code", [])

    assert "pc_enable_tree" in texto
    assert "pc_look" in texto          # y qué hacer mientras tanto


def test_si_ya_esta_activo_el_diagnostico_pide_reiniciar(home):
    """El flag no se aplica en caliente: sin reinicio el árbol sigue vacío."""
    _escribir_argv(home)
    a11y.activar("vscode")

    texto = a11y.diagnostico("main.py - Visual Studio Code", [])

    assert "reinic" in texto.lower()
    assert "pc_enable_tree" not in texto      # ya está hecho: repetirlo confunde


def test_con_una_app_desconocida_no_se_promete_lo_que_no_se_puede(home):
    texto = a11y.diagnostico("Reunión - Slack", [])

    assert "pc_enable_tree" not in texto
    assert "pc_look" in texto


# ── Integración ─────────────────────────────────────────────────────

def test_encender_el_arbol_es_amarillo():
    """Toca la configuración de otra aplicación: reversible, pero se pregunta antes."""
    import agents.tool_registry  # noqa: F401  — es al importarlo cuando se clasifica
    from core.security_manager import RiskLevel, security_manager

    assert security_manager._actions["pc_enable_tree"] == RiskLevel.YELLOW


def test_describir_una_ventana_electron_deriva_al_diagnostico(home, monkeypatch):
    """Es el caso que motivó todo: pedir algo en VS Code y que la ventana esté muda."""
    from os_integration import ui_tree

    _escribir_argv(home)
    monkeypatch.setattr(
        ui_tree, "leer_ventana_activa",
        lambda: ([ui_tree.Elemento("Chrome Legacy Window", "PaneControl", 0, 0)],
                 "main.py - Visual Studio Code"),
    )

    texto = ui_tree.describir_ventana_activa()

    assert "pc_enable_tree" in texto


def test_vs_code_ya_no_se_diagnostica_como_arbol_apagado():
    """Medido en esta máquina: VS Code publica 2.399 elementos sin tocar su configuración.

    El "VS Code = 7 elementos" del que salió este módulo era el recorrido a mano, que se
    quedaba sin profundidad. Con la lectura buena, la ventana tiene de sobra, y decirle al
    usuario que cambie su configuración y reinicie el editor sería molestarlo para nada.
    """
    from os_integration.electron_a11y import parece_electron_sin_arbol
    from os_integration.ui_tree import Elemento

    muchos = [Elemento(nombre=f"Control {i}", tipo="ButtonControl", x=i, y=i)
              for i in range(263)]

    assert parece_electron_sin_arbol(muchos, "archivo.py - Visual Studio Code") is False


def test_una_ventana_electron_de_verdad_muda_si_se_diagnostica():
    """El diagnóstico sigue sirviendo donde corresponde: una ventana que no publica nada."""
    from os_integration.electron_a11y import parece_electron_sin_arbol
    from os_integration.ui_tree import Elemento

    casi_nada = [Elemento(nombre="Chrome Legacy Window", tipo="PaneControl", x=1, y=1)]

    assert parece_electron_sin_arbol(casi_nada, "algo - Visual Studio Code") is True
