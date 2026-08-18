# Desarrollo REQ-011 — Auto-inicio con Windows (arranque minimizado a bandeja)

**Agente:** orion-dev
**Fecha:** 2026-08-05

## Archivos modificados

- `agente_ia/main.py` — bloque `if __name__ == "__main__":`: se agregó `tray_mode = "--tray" in
  sys.argv` y se condicionó `window.showMaximized()` a `not tray_mode`. Sin cambios en `main()` ni
  en `jarvis_runner()`, tal como especifica la arquitectura (Decisión 2).

## Archivos creados

- `agente_ia/setup_autostart.py` — script standalone (funciones a nivel de módulo, sin clases):
  - `_resolver_pythonw()` — resuelve `pythonw.exe` junto a `sys.executable`; cae a `sys.executable`
    con `logger.warning(...)` si no existe.
  - `construir_comando_autostart()` — arma `'"<pythonw>" "<main.py>" --tray'`.
  - `esta_activo()` — `True` si `AUTOSTART_VALUE_NAME` existe en `HKCU\Software\Microsoft\Windows\
    CurrentVersion\Run`.
  - `activar()` — `winreg.CreateKeyEx` + `SetValueEx` (idempotente, CA-05); `logger.warning(...)` en
    cada activación real (CA-07); retorna `False` solo ante `OSError` inesperado, logueado y nunca
    propagado.
  - `desactivar()` — `winreg.OpenKey` + `DeleteValue`; atrapa `FileNotFoundError` y retorna `True`
    sin fallar (CA-06); `logger.warning(...)` solo cuando sí borró algo (CA-07).
  - `_confirmar()` — mismo patrón que `main.py::_desktop_confirm()` (prompt + comparación
    `sí/si/yes/s`), implementando el gate 🟡 Amarillo de `security-levels.md` para este script (sin
    canal/dispatch involucrado, ver arquitectura-011.md).
  - CLI (`if __name__ == "__main__":`) con `argparse`, grupo mutuamente exclusivo `required=True`:
    `--activar` / `--desactivar` / `--estado`. `--activar` y `--desactivar` piden confirmación
    interactiva antes de mutar el registro; `--estado` solo informa, sin mutar nada.

## Dependencias agregadas

Ninguna. `winreg` es stdlib de Python en Windows (confirmado en baseline-011.md y
arquitectura-011.md, Decisión 1). `requirements.txt` no se modificó.

## Decisiones de implementación

- Ningún ajuste respecto a la propuesta aprobada. Se implementó exactamente la API descrita en
  `arquitectura-011.md` (Decisión 2 y Decisión 3): mismos nombres de función, mismo `RUN_KEY_PATH`,
  mismo `AUTOSTART_VALUE_NAME="Noddoo"` fijo (no derivado de `get_agent_name()`), mismo flujo CLI.
- `ui/gui.py` y `start_jarvis.py` no se tocaron, tal como confirma la arquitectura (Decisión 2 y
  sección "Archivos a modificar/crear").
- No se escribieron los archivos de test sugeridos en la arquitectura
  (`tests/test_autostart.py` nuevo, extensión de `tests/test_main.py`) — el alcance de esta tarea,
  según las instrucciones explícitas recibidas para esta implementación, se limitó a los dos
  archivos de código (`setup_autostart.py`, `main.py`). Queda documentado para que `orion-tester`
  los cubra en su paso, usando la sección "Pruebas sugeridas" de `arquitectura-011.md` como guía
  (casos CA-01 a CA-10 y los dos casos extra: `_resolver_pythonw` fallback y `esta_activo`).

## Verificación local

- `python -m py_compile main.py setup_autostart.py` → sin errores.
- `python -m pytest tests/ --tb=short -q` → **197 passed, 0 failed**, mismos 3 warnings
  preexistentes que registró `baseline-011.md` (deprecations de `aifc`/`audioop` en
  `speech_recognition`, y `PytestReturnNotNoneWarning` en `test_agents.py::test_ca1_orchestrator`).
  Cero fallos nuevos atribuibles a este REQ.

## Cobertura de criterios de la SPEC (a nivel de implementación, pendiente de verificación formal por orion-tester)

| Criterio | Implementado en |
|----------|------------------|
| CA-01 | `setup_autostart.py::activar()` |
| CA-02 | `setup_autostart.py::desactivar()` |
| CA-03 | `main.py`, bloque `__main__`: `if not tray_mode: window.showMaximized()` |
| CA-04 | `main.py`, bloque `__main__`: `JarvisMainWindow()` se instancia igual en modo `--tray`; `_setup_tray_icon()` en `ui/gui.py` no se tocó (corre incondicional en `_init_ui()`) |
| CA-05 | `setup_autostart.py::activar()` — `SetValueEx` sobre nombre de valor fijo |
| CA-06 | `setup_autostart.py::desactivar()` — atrapa `FileNotFoundError` |
| CA-07 | `logger.warning(...)` en `activar()` y en `desactivar()` (solo si borró algo) |
| CA-08 | `ui/gui.py` no se modificó |
| CA-09 | Sin clases/hilos de supervisión, reinicio ni watchdog en ningún archivo tocado |
| CA-10 | `closeEvent()` en `ui/gui.py` no se tocó |

## Handoff

`@orion-tester REQ-011 | dev-log=workspace/adjuntos/REQ-011/propuestas/desarrollo-log-011.md | spec=workspace/adjuntos/REQ-011/spec/SPEC-011.md`

No invocado automáticamente por este agente — queda a la espera de que la sesión orquestadora lo
dispare.
