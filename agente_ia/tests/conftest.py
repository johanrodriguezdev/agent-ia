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

from core.confirmation import register_confirmation_adapter
from core.security_manager import ChannelType


def _desktop_confirm(action_name: str, message: str) -> bool:
    response = input(message)
    return response.strip().lower() in ("sí", "si", "yes", "s")


register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)
