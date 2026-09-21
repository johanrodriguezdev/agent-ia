"""
tests/conftest.py

REQ-006/CA-10 — infraestructura de test, no producción.

`core/security_manager.py::require_confirmation()` ya no llama a `input()` directamente
en la rama YELLOW: consulta el adaptador de confirmación registrado para el canal
resuelto (`core/confirmation.py`). En producción, el único punto que registra el
adaptador de DESKTOP es `main.py` (import-time), tal como especifica
`arquitectura-006.md`. Varios tests pre-existentes de REQ-005
(`tests/test_security_manager.py`) invocan `security_manager.require_confirmation()` o
`dispatcher.dispatch()` directamente con `channel="desktop"` SIN importar `main.py`
—que además arrastra dependencias de GUI/voz no aptas para pytest, ver
`.claude/rules/testing.md`— y mockean `builtins.input` esperando que siga siendo
alcanzable.

Este adaptador reproduce EXACTAMENTE la implementación de `main.py::_desktop_confirm`
(mismo prompt recibido, misma llamada a `input()`, misma comparación de respuesta) para
que esos tests seguros funcionen sin depender del módulo pesado `main.py`. No sustituye
el registro real de producción — es una única fuente de verdad duplicada a propósito en
un solo lugar (acá), documentada como desviación de infraestructura de test en
`desarrollo-log-006.md`.
"""

import os

import pytest

# REQ-008 — los widgets PyQt6 nuevos (`tests/test_gui_workers.py`, `tests/test_gui_widgets.py`)
# usan pytest-qt, que necesita el backend "offscreen" de Qt para construir QWidgets sin una
# ventana real ni un servidor gráfico disponible (CI, este entorno). Se fija acá, antes de
# cualquier import de PyQt6, para que aplique a toda la suite sin tocar cada test individual.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# REQ-015/§6 — este entorno tiene PyQt6 Y PySide6 instalados a la vez; sin fijar esta
# variable, `pytest-qt` puede resolver el backend equivocado y `qtbot.addWidget()` falla
# con un conflicto `isinstance()` entre ambos bindings (66 fallos falsos, documentados por
# `orion-baseline` en `baseline-015.md`). Fix ya probado en el stash de REQ-014. Fijado
# ANTES de cualquier import de PyQt6, igual que `QT_QPA_PLATFORM` arriba.
os.environ.setdefault("PYTEST_QT_API", "pyqt6")

# La suite importa `main.py` (tests/test_main.py), y `main.py` llama a `setup_logging()` al
# importarse: desde ese momento TODO lo que registra la suite va al log de la aplicación.
# Investigando por qué el micrófono ignoró un comando real (2026-09-03) aparecían mezclados
# errores de terminal y de wake word que eran de los propios tests — ruido indistinguible
# del problema que se estaba buscando. Se manda a un archivo aparte, en la misma carpeta
# para poder mirarlo cuando un test falle.
os.environ.setdefault(
    "ORION_LOG_FILE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "logs", "orion-tests.log"),
)

# La memoria unificada de los tests va a una base TEMPORAL, nunca a `ai/unified_memory.db`.
# Se descubrió el 2026-09-21 que los tests del bridge que llegaban a `store_turn()` sin
# stubear la memoria habían dejado 84 conversaciones de prueba en la barra lateral del
# usuario (y `conv-1`/`conv-9` con cientos de filas), algunas con llamadas reales al
# modelo. Los tests que necesitan una base propia siguen redirigiendo `DB_PATH` a
# `tmp_path`; esto es la red de abajo para los que no lo hacen. Fijado ANTES de importar
# `ai.memory_manager`, que lee la variable al cargarse.
import tempfile  # noqa: E402

os.environ.setdefault(
    "ORION_MEMORY_DB",
    os.path.join(tempfile.gettempdir(), "orion-tests-unified_memory.db"),
)

# REQ-015 — `QtWebEngineWidgets`/`QtWebEngineCore` exigen ser importados ANTES de que
# exista cualquier instancia de `QApplication` en todo el proceso (si no, PyQt6 lanza
# `ImportError: QtWebEngineWidgets must be imported... before a QCoreApplication instance
# is created`). Sin esto, el orden real dependería de qué archivo de test corra primero y
# de si ya se creó un `QApplication` vía `qtbot`/`qapp` en un test anterior — se fija acá,
# a nivel de sesión, antes de que cualquier test tenga oportunidad de crear una app Qt.
import PyQt6.QtWebEngineWidgets  # noqa: F401

from core.confirmation import register_confirmation_adapter
from core.security_manager import ChannelType


def _desktop_confirm(action_name: str, message: str) -> bool:
    response = input(message)
    return response.strip().lower() in ("sí", "si", "yes", "s")


register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)


@pytest.fixture(autouse=True)
def _sin_canal_de_telegram(monkeypatch):
    """La suite no levanta el canal de Telegram.

    `MainWindow` lo abre al arrancar, así que cada test que construye la ventana lanzaba un
    bot DE VERDAD: con el token real del usuario, hablando con la red, y peleándose por el
    mismo token con el que el usuario tuviera abierto. Además de indeseable, hacía que los
    tests de la terminal contaran una pestaña que no habían abierto ellos.

    Se apaga por configuración, que es el mismo interruptor que tiene el usuario.
    """
    import config_manager

    monkeypatch.setattr(config_manager, "get_telegram_autostart", lambda: False)


@pytest.fixture(autouse=True)
def _clear_dialog_store():
    """REQ-021 — el estado de diálogo pendiente (`core/dialog_state.py`) es un singleton de
    proceso. Sin esto, un diálogo abierto por un test cambiaría la resolución de los demás:
    con diálogo abierto, `_try_pending_dialog` corre primero y puede tragarse la frase.
    """
    from core.dialog_state import dialog_store

    dialog_store.clear_all()
    yield
    dialog_store.clear_all()


@pytest.fixture(autouse=True)
def _aislar_cooldowns_de_proveedor(tmp_path):
    """El estado de cooldown (`ai/provider_health.py`) es un singleton de proceso con
    respaldo en disco. Sin esto, un test que aparta un proveedor cambiaría el orden de
    intentos de los demás, y la suite escribiría `provider_cooldowns.json` en la raíz del
    repositorio en vez de en un temporal.
    """
    from ai import provider_health

    original = provider_health.COOLDOWN_FILE
    provider_health.COOLDOWN_FILE = str(tmp_path / "provider_cooldowns.json")
    provider_health.limpiar()
    yield
    provider_health.limpiar()
    provider_health.COOLDOWN_FILE = original


def pytest_configure(config):
    # REQ-015/§7, §8 — `tests/test_webview_smoke.py` instancia `QWebEngineView` real en
    # modo offscreen; puede ser lento o inestable según el entorno de CI/GPU. Se marca
    # aparte para que se pueda correr/excluir por separado sin bloquear el resto de la
    # suite si el entorno no lo soporta bien (`pytest -m "not webview_smoke"`).
    config.addinivalue_line(
        "markers",
        "webview_smoke: instancia QWebEngineView real offscreen (REQ-015) — puede ser "
        "lento/inestable según el entorno; correr aparte si hace falta.",
    )


# ── Dependencias opcionales: ausentes es "se salta", no "falla" (REQ-042) ──────────────

#: Paquetes que el agente usa solo para una capacidad concreta (documentos de Office,
#: árbol de accesibilidad de Windows, PDF sin Office) y que un equipo recién clonado puede
#: no tener. Antes, sin `python-docx` o `uiautomation`, la suite mostraba 42 rojos y 4
#: errores que no eran ningún bug: eso confunde a quien contribuye y esconde los fallos
#: reales. Un `ModuleNotFoundError` de uno de estos nombres —venga del test, de una fixture
#: o del módulo bajo prueba— se reporta como skip con el nombre del paquete que falta.
_DEPENDENCIAS_OPCIONALES = frozenset({
    "docx", "openpyxl", "pptx", "fitz", "pymupdf", "uiautomation", "win32com", "pythoncom",
    "comtypes",
})


def _dependencia_opcional_ausente(excinfo) -> str:
    """Return el nombre del paquete opcional que falta, o "" si el fallo es otra cosa."""
    exc = excinfo.value if excinfo is not None else None
    if not isinstance(exc, ModuleNotFoundError):
        return ""
    raiz = (exc.name or "").split(".")[0]
    return raiz if raiz in _DEPENDENCIAS_OPCIONALES else ""


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    reporte = outcome.get_result()
    if not reporte.failed:
        return
    paquete = _dependencia_opcional_ausente(call.excinfo)
    if not paquete:
        return
    reporte.outcome = "skipped"
    reporte.longrepr = (
        str(item.fspath),
        item.location[1],
        f"Skipped: dependencia opcional no instalada: {paquete} (ver requirements.txt)",
    )
