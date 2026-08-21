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
