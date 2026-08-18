# Resultados de prueba REQ-011 — Auto-inicio con Windows (arranque minimizado a bandeja)

**Agente:** orion-tester
**Fecha:** 2026-08-05

## Nota de alcance

`orion-dev` entregó `agente_ia/setup_autostart.py` y el cambio en `agente_ia/main.py` sin
tests (ver `propuestas/desarrollo-log-011.md`, sección "Decisiones de implementación").
`orion-tester` escribió en este paso todos los tests sugeridos por
`propuestas/arquitectura-011.md` ("Pruebas sugeridas"), siguiendo `.claude/rules/testing.md`:

- `agente_ia/tests/test_autostart.py` — **nuevo**, 16 tests. Cubre CA-01, CA-02, CA-05,
  CA-06, CA-07, CA-08 y los dos casos extra (`_resolver_pythonw` fallback,
  `esta_activo()` en ambos sentidos), más `construir_comando_autostart()` y `_confirmar()`
  (gate 🟡 Amarillo). `winreg` mockeado por completo en todos los casos — nunca se tocó el
  registro real de Windows.
- `agente_ia/tests/test_main.py` — **extendido**, +2 tests (CA-03). El bloque
  `if __name__ == "__main__":` de `main.py` no fue extraído a una función testeable por
  `orion-dev`, así que se probó el código real ejecutándolo vía `exec()` del texto fuente
  leído directamente del archivo en cada test (nunca copiado a mano), con `ui.gui`,
  `threading.Thread` y `sys.exit` mockeados. Se evitó `runpy.run_path(main.py)` a propósito:
  hubiera re-ejecutado también el código de import de nivel de módulo de `main.py`
  (registro de skills/orchestrator/tools sobre singletons globales), duplicando ese
  registro y contaminando el resto de la suite. `threading.Thread` se mockeó para que el
  hilo `jarvis_runner` — que termina en `os._exit(0)` — nunca se ejecute de verdad dentro
  del proceso de pytest.
- `agente_ia/tests/test_gui_widgets.py` — **extendido**, +1 test (CA-04). Se instanció
  `JarvisMainWindow()` real (offscreen, mismo patrón que el resto del archivo) sin llamar
  `show()`/`showMaximized()`, replicando el arranque `--tray`.

## Compilación

- `python -m py_compile main.py setup_autostart.py tests/test_autostart.py
  tests/test_main.py tests/test_gui_widgets.py` → **OK**, sin errores.

## Tests existentes (suite completa)

- Comando: `python -m pytest tests/ --tb=short -v`
- Resultado: **216 passed, 0 failed** (216 = 197 del baseline + 19 nuevos de este REQ:
  16 en `test_autostart.py`, 2 en `test_main.py`, 1 en `test_gui_widgets.py`).
- Warnings: los mismos 3 preexistentes del baseline (`DeprecationWarning` de
  `aifc`/`audioop` en `speech_recognition`, `PytestReturnNotNoneWarning` en
  `test_agents.py::test_ca1_orchestrator`). **Cero warnings nuevos, cero fallos nuevos.**
- Nuevos fallos respecto al baseline: **ninguno**.

## Criterios de la SPEC

| Criterio | Resultado | Nota |
|----------|-----------|------|
| CA-01 — activar() registra el mecanismo apuntando a `--tray` | PASS | `test_activar_registra_comando_con_flag_tray_ca01` — `SetValueEx` llamado con `AUTOSTART_VALUE_NAME` y comando que contiene `--tray` y `main.py`. |
| CA-02 — desactivar() revierte por completo, sin rastros | PASS | `test_desactivar_borra_la_entrada_por_completo_ca02` — `DeleteValue` llamado con el mismo valor; `esta_activo()` refleja `False` después. Un solo artefacto (entrada de registro), nada más que limpiar. |
| CA-03 — `--tray` nunca muestra ventana (`show()`/`showMaximized()`) | PASS | `test_main_tray_mode_no_llama_show_ca03` (ejecuta el bloque `__main__` real vía `exec()` del código fuente, con GUI/threading/exit mockeados) — `showMaximized` y `show` no se llaman. Test de contraste `test_main_sin_tray_si_llama_showmaximized` confirma que sin `--tray` sí se llama `showMaximized()` una vez (el condicional depende realmente del flag). |
| CA-04 — bandeja funcional sin ventana mostrada | PASS | `test_tray_icon_activo_sin_ventana_mostrada_ca04` — `JarvisMainWindow()` real, nunca mostrada; `tray_icon` existe, menú tiene "Mostrar/Ocultar" y "Salir", y `_toggle_visible()` alterna visibilidad correctamente. |
| CA-05 — activar() dos veces es idempotente | PASS | `test_activar_dos_veces_es_idempotente_ca05` — `SetValueEx` llamado 2 veces con el mismo nombre y comando, sin excepción. |
| CA-06 — desactivar() sin autostart previo no falla | PASS | `test_desactivar_sin_autostart_previo_no_falla_ca06` — `FileNotFoundError` de `winreg` capturado, retorna `True` sin propagar traza. |
| CA-07 — logging WARNING en cada modificación | PASS | `test_activar_loguea_warning_ca07` y `test_desactivar_loguea_warning_solo_si_borro_algo_ca07` — nivel `WARNING`, mensaje incluye mecanismo (`registro HKCU Run`) y acción; `desactivar()` sin nada que borrar NO loguea (comportamiento esperado por CA-06, verificado explícitamente). |
| CA-08 — sin controles de autostart en `ui/gui.py` | PASS | `test_gui_sin_controles_de_autostart_ca08` (búsqueda estática de las 3 variantes de keyword) + `git diff --stat ui/gui.py` confirma cero cambios en el archivo. |
| CA-09 — sin watchdog/supervisión/reinicio | PASS | Revisión de código (no testeable por unidad, según la propia arquitectura): `grep -in "watchdog\|supervis\|restart\|reinicio automat\|crash" setup_autostart.py main.py` → sin coincidencias. |
| CA-10 — `closeEvent()` sin cambios | PASS | `git diff --stat ui/gui.py` → 0 cambios (archivo intacto). El test existente `test_jarvis_main_window_close_hides_without_quitting_app` (REQ-009) sigue pasando sin modificación. |

**10/10 criterios PASS.**

## Regresión

| Área revisada | Resultado |
|---------------|-----------|
| `ui/gui.py` (tray icon, `closeEvent`, REQ-008/REQ-009) | PASS — sin cambios en el archivo, tests existentes (`test_gui_widgets.py`, `test_wake_word_gui.py`) siguen en verde. |
| `ui/cli.py` (`gui_active`, REQ-009) | PASS — sin tocar, `test_cli_gui_active.py` en verde. |
| `main.py` — resto del bloque `__main__` (`--headless`, `jarvis_runner`, `_ProactiveAssistant`) | PASS — `test_main.py` completo en verde, incluido el caso sin `--tray` (contraste). |
| `start_jarvis.py`, `requirements.txt` | PASS — confirmado sin cambios vía `git diff --stat` (0 archivos afectados). |
| Suite completa (`security_manager`, `dispatcher`, `resolution`, `reasoning_loop`, etc.) | PASS — 216/216, sin fallos nuevos. |

## Veredicto: PASS

10/10 criterios de SPEC-011 verificados. Compilación limpia. 216/216 tests (197 baseline +
19 nuevos de este REQ), cero regresiones, mismos 3 warnings preexistentes. Listo para
`orion-qa`.
