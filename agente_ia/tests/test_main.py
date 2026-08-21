"""
tests/test_main.py

REQ-006/CA-12 — bug de `main.py:_ProactiveAssistant.can_handle()`: antes de este REQ, el
método tenía un ternario que retornaba `0.0` en ambas ramas (nunca `0.6`), así que este
agente nunca podía ganar la selección de `AgentOrchestrator`. El fix es un `if/else` real.

Importar `main` completo dispara el registro de skills/logging habitual de arranque (ya
verificado en sesiones previas: no cuelga, no depende de red/mic). Se importa una sola vez
a nivel de módulo para no repetir ese costo por test.
"""

from unittest.mock import MagicMock, patch

import main
import ui.webview.main_window  # noqa: F401 — asegura que el módulo ya está en
# sys.modules antes de parcharlo (REQ-015: reemplaza el antiguo "import ui.gui").


# ---------------------------------------------------------------------------
# REQ-011/CA-03 — arranque `--tray`: nunca se llama show() sobre `MainWindow`.
# REQ-015/§5.1: además ya no existe `showMaximized()` en el bloque real — el
# tamaño/posición quedan resueltos por `fit_size_to_screen()` dentro del constructor de
# `MainWindow` (evita los márgenes extra que DWM añade en maximizado+frameless en
# Windows, ver arquitectura-015.md §5.1).
#
# El bloque `if __name__ == "__main__":` de main.py no fue extraído a una función
# testeable (ver propuestas/desarrollo-log-011.md — fuera del alcance recibido por
# orion-dev), así que `orion-tester` prueba el código real ejecutando exactamente el
# texto fuente de ese bloque vía `exec()` (leído del archivo en cada test, nunca
# copiado/reescrito a mano, para no divergir de la implementación real). Se evita
# `runpy.run_path(main.py)` a propósito: reejecutaría también todo el código de
# import de main.py (registro de skills/orchestrator/tools), duplicando ese registro
# sobre los singletons globales ya poblados por el `import main` de arriba y
# contaminando el resto de la suite. `threading.Thread` se mockea para que el hilo
# `jarvis_runner` (que termina en `os._exit(0)`) nunca llegue a ejecutarse de verdad.
# ---------------------------------------------------------------------------

def _extraer_bloque_main() -> str:
    with open(main.__file__, encoding="utf-8") as f:
        source = f.read()
    marker = 'if __name__ == "__main__":'
    idx = source.index(marker)
    cuerpo = source[idx:].splitlines()[1:]
    return "\n".join(linea[4:] if linea.startswith("    ") else linea for linea in cuerpo)


def _ejecutar_bloque_main(argv, mock_window):
    fake_main_window_module = MagicMock()
    fake_main_window_module.MainWindow.return_value = mock_window
    fake_qtwidgets_module = MagicMock()
    fake_qtwidgets_module.QApplication.return_value = MagicMock()

    namespace = {"__name__": "__main__", "main": main.main}
    with patch("sys.argv", argv), \
         patch.dict("sys.modules", {
             "ui.webview.main_window": fake_main_window_module,
             "PyQt6.QtWidgets": fake_qtwidgets_module,
         }), \
         patch("threading.Thread") as mock_thread_cls, \
         patch("sys.exit") as mock_exit:
        mock_thread_cls.return_value = MagicMock()
        exec(compile(_extraer_bloque_main(), main.__file__, "exec"), namespace)
    return mock_exit


def test_main_tray_mode_no_llama_show_ca03():
    mock_window = MagicMock()

    _ejecutar_bloque_main(["main.py", "--tray"], mock_window)

    mock_window.show.assert_not_called()
    mock_window.showMaximized.assert_not_called()


def test_main_sin_tray_si_llama_show():
    """Contraste con CA-03: confirma que el condicional realmente depende de `--tray` y
    no que `show()` dejó de llamarse en general. REQ-015: ya no existe
    `showMaximized()` en el bloque real (arquitectura-015.md §5.1)."""
    mock_window = MagicMock()

    _ejecutar_bloque_main(["main.py"], mock_window)

    mock_window.show.assert_called_once()
    mock_window.showMaximized.assert_not_called()


def test_proactive_assistant_can_handle_briefing():
    assistant = main._ProactiveAssistant()
    assert assistant.can_handle("quiero un briefing") == 0.6
    assert assistant.can_handle("ponme un recordatorio") == 0.6


def test_proactive_assistant_can_handle_no_coincide():
    assistant = main._ProactiveAssistant()
    assert assistant.can_handle("hola, como estas") == 0.0


def test_proactive_assistant_ramas_devuelven_valores_distintos():
    """El bug H original: ambas ramas del ternario devolvían 0.0. Confirma que ahora
    difieren cuando el texto coincide vs. cuando no."""
    assistant = main._ProactiveAssistant()
    con_match = assistant.can_handle("dame el briefing de hoy")
    sin_match = assistant.can_handle("cuentame un chiste")
    assert con_match != sin_match
