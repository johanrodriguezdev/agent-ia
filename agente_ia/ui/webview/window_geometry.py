"""
ui/webview/window_geometry.py
`fit_size_to_screen()` — función pura, sin dependencia de Qt en su firma (REQ-015/CA-04,
arquitectura-015.md §1, §5.1).

Bug #2 de REQ-014 (ventana más alta que el área disponible, input bar detrás de la barra
de tareas de Windows) NO era consecuencia de usar QWidget/QSS — era aritmética de
geometría de ventana Qt sin clamp contra `availableGeometry()`. La mitigación es la misma
que ya se probó y funcionó en el stash de REQ-014: clampear siempre contra el área de
trabajo disponible, llamada ANTES de `show()`, sin `showMaximized()` (ver arquitectura-015.md
§5.1 para por qué se evita maximizado con frameless).
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def fit_size_to_screen(
    screen_available: Tuple[int, int, int, int],
    minimum: Tuple[int, int] = (1024, 640),
    fraction: float = 0.85,
) -> Tuple[int, int, int, int]:
    """Calcula el tamaño/posición de ventana que entra en el área de pantalla disponible.

    `screen_available` es `(x, y, width, height)` del área de trabajo (ya excluye la
    barra de tareas — `QApplication.primaryScreen().availableGeometry()` del lado del
    caller). Devuelve `(width, height, x, y)` de la ventana, centrada en el área
    disponible, sin exceder nunca sus límites.

    - El tamaño objetivo es `fraction` del área disponible, pero nunca menor que
      `minimum` NI mayor que el área disponible misma (si el área disponible es más chica
      que `minimum`, se usa el área disponible completa — nunca se desborda la pantalla).
    - `x`/`y` centran la ventana dentro del área disponible (nunca negativos respecto al
      origen del área — `x >= screen_x`, `y >= screen_y`).
    """
    screen_x, screen_y, screen_w, screen_h = screen_available
    min_w, min_h = minimum

    target_w = int(screen_w * fraction)
    target_h = int(screen_h * fraction)

    width = max(target_w, min_w)
    height = max(target_h, min_h)

    # Nunca exceder el área disponible, incluso si `minimum` es mayor que la pantalla.
    width = min(width, screen_w)
    height = min(height, screen_h)

    x = screen_x + (screen_w - width) // 2
    y = screen_y + (screen_h - height) // 2

    return width, height, x, y
