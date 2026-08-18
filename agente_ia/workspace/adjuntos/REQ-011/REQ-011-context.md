# Contexto REQ-011 — Auto-inicio con Windows

## Resumen ejecutivo
Hacer que la app arranque sola al iniciar sesión de Windows, minimizada a la bandeja del sistema
(sin ventana visible), sin depender de que el usuario la abra manualmente cada vez. No incluye
watchdog ni reinicio automático ante crash.

## Estado actual
- **Estado tracker:** EN_QA (pendiente de prueba manual de Johan antes de LISTO_PARA_COMMIT)
- **Último agente:** orion-qa
- **Fecha última actualización:** 2026-08-05
- **Rama git:** feature/REQ-011-autostart-windows
- **Categoría:** AUTOMATIZACION
- **Tipo de cambio:** FEATURE_NUEVA

## Decisiones tomadas
2026-08-05 | orion-coordinador | REQ creado — categoría=AUTOMATIZACION | Confirmado explícitamente por Johan vía pregunta relayada por la sesión orquestadora, tras dudar entre CORE (keyword "startup" en CLAUDE.md) y AUTOMATIZACION. Se prefirió AUTOMATIZACION porque "startup" en CORE refiere a la secuencia de inicialización interna de la app, no a que el SO la lance sola sin intervención del usuario — más parecido en espíritu a lo que ya cubre tasks/task_scheduler.py
2026-08-05 | orion-coordinador | Split en dos REQs independientes (REQ-010 branding / REQ-011 auto-inicio) | Confirmado explícitamente por Johan — REQ-011 no depende de los archivos de imagen de branding y puede avanzar en paralelo a REQ-010
2026-08-05 | orion-coordinador | Alcance = solo auto-inicio minimizado a bandeja, SIN watchdog/reinicio ante crash | Descartado explícitamente por Johan — no agregar esa funcionalidad aunque parezca relacionada
2026-08-05 | orion-spec | Activación/desactivación del auto-inicio = script manual único (`setup_autostart.py` o similar), SIN checkbox/panel de Configuración en la GUI | Confirmado explícitamente por Johan — hoy no existe panel de Settings en ui/gui.py y agregarlo sería alcance mayor, fuera de REQ-011
2026-08-05 | orion-spec | SPEC-011 redactada y aprobada | Aprobado por Johan ("APROBADO tal cual")
2026-08-05 | orion-spec | Tipo de cambio confirmado: FEATURE_NUEVA | Identificado en la entrevista, sin cambios respecto al valor fijado por orion-coordinador
2026-08-05 | orion-baseline | Baseline redactado (`workspace/adjuntos/REQ-011/origen/baseline-011.md`) | Confirmado: no existe hoy ningún mecanismo de auto-inicio de Windows en el repo (búsqueda exhaustiva de `winreg`/`HKCU`/`schtasks`/`.lnk` — el único hit relacionado, `proactive_engine.py` trigger `"startup"`, es interno a la app y no toca el inicio de sesión de Windows). `main.py` solo tiene modo GUI visible (`showMaximized()`) o `--headless` (sin bandeja) — falta el tercer modo "minimizado a bandeja". `start_jarvis.py` llama `main()` directo sin pasar por el bloque `__main__` de `main.py`, por lo tanto hoy NO inicializa GUI/bandeja — no sirve tal cual como comando de auto-inicio si se requiere bandeja funcional (CA-04). `requirements.txt` no tiene `pywin32`/`winshell` hoy — cualquier mecanismo que los requiera es dependencia nueva a documentar en arquitectura.
2026-08-05 | orion-architect | Mecanismo elegido: registro `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (vía `winreg`, stdlib) | Cero dependencias nuevas, idempotente por naturaleza (`SetValueEx` sobrescribe, no duplica — CA-05), sin admin, y el caso borde "carpeta movida/borrada" (SPEC-011) se resuelve gratis porque cada entrada de `Run` falla de forma aislada y no bloqueante. Se descartó `.lnk` (requiere `pywin32`) y Tarea Programada (más superficie de configuración, riesgo de marcar "privilegios elevados" sin querer). Ver `propuestas/arquitectura-011.md`, Decisión 1.
2026-08-05 | orion-architect | Comando registrado: nuevo flag `--tray` en `main.py`; `start_jarvis.py` NO se modifica | `start_jarvis.py` fuerza `boot_mode='3'` (manos libres headless) y tiene un propósito ya estable distinto — reutilizarlo arriesgaba romper su uso actual. Se agrega `tray_mode = "--tray" in sys.argv` al bloque `__main__` de `main.py`, condicionando solo `showMaximized()`; `_setup_tray_icon()` sigue corriendo incondicional (sin tocar `ui/gui.py`). Ver Decisión 2.
2026-08-05 | orion-architect | Script standalone: `agente_ia/setup_autostart.py` (archivo único en la raíz, funciones a nivel de módulo, sin clases) | Nombre y ubicación sugeridos por SPEC-011 como ejemplo, confirmados como definitivos. API: `activar()` / `desactivar()` / `esta_activo()`, más helpers `_resolver_pythonw()` y `construir_comando_autostart()`. Confirmación interactiva (`_confirmar()`, mismo patrón que `main.py::_desktop_confirm`) implementa el gate 🟡 Amarillo fuera de `security_manager` porque no hay canal/dispatch involucrado — es un script de terminal. Ver Decisión 3.
2026-08-05 | orion-architect | Sin dependencias nuevas — `requirements.txt` no se modifica | El mecanismo elegido (winreg) es 100% stdlib; se descartó `pywin32`/`winshell` explícitamente por requerir dependencia nueva sin necesidad, cumpliendo la preferencia explícita de minimizar dependencias.
2026-08-05 | orion-architect | Arquitectura APROBADA por Johan ("APROBADO tal cual") | Aprobación relayada por la sesión orquestadora tras revisar `propuestas/arquitectura-011.md`. Sin ajustes solicitados. CSV actualizado vía `update-tracker.mjs` (Aprobacion_Arquitectura=APROBADO, Rama=feature/REQ-011-autostart-windows, Estado=ARQUITECTURA_APROBADA).
2026-08-05 | orion-dev | Implementado exactamente lo aprobado en arquitectura-011.md: `agente_ia/setup_autostart.py` (nuevo) con `_resolver_pythonw()`, `construir_comando_autostart()`, `esta_activo()`, `activar()`, `desactivar()`, `_confirmar()` + CLI argparse mutuamente exclusiva; `agente_ia/main.py` con `tray_mode = "--tray" in sys.argv` condicionando `showMaximized()` | Sin desviaciones respecto a la propuesta. `ui/gui.py` y `start_jarvis.py` no se tocaron (confirmado por arquitectura). No se agregaron dependencias (`winreg` es stdlib). Ver `propuestas/desarrollo-log-011.md`.
2026-08-05 | orion-dev | No se escribieron los archivos de test sugeridos por arquitectura (`tests/test_autostart.py`, extensión de `tests/test_main.py`) en este paso | El alcance de la tarea recibida por orion-dev en esta sesión listó explícitamente solo los dos archivos de código a implementar (`setup_autostart.py`, cambio en `main.py`), sin incluir tests. Queda documentado para que `orion-tester` los cubra usando la sección "Pruebas sugeridas" de `arquitectura-011.md` (casos CA-01 a CA-10 + 2 casos extra) como guía.
2026-08-05 | orion-dev | Verificación local: `python -m py_compile main.py setup_autostart.py` sin errores; `python -m pytest tests/` → 197 passed, 0 failed (mismos 3 warnings preexistentes del baseline, cero fallos nuevos) | Confirma que el cambio no introduce regresiones sobre el baseline-011.md (0 fallos pre-existentes).
2026-08-05 | orion-tester | Tests escritos por orion-tester (orion-dev no los entregó, ver desarrollo-log-011.md): `tests/test_autostart.py` (nuevo, 16 tests: CA-01, CA-02, CA-05, CA-06, CA-07, CA-08 + extras `_resolver_pythonw`/`esta_activo`, `winreg` mockeado por completo); `tests/test_main.py` (+2 tests, CA-03); `tests/test_gui_widgets.py` (+1 test, CA-04) | Siguiendo `.claude/rules/testing.md` y la sección "Pruebas sugeridas" de `arquitectura-011.md`. Detalle de la estrategia para CA-03 (bloque `__main__` no extraído a función testeable por orion-dev): se ejecuta el texto fuente real del bloque vía `exec()`, leído del archivo en cada test, con `ui.gui`/`threading.Thread`/`sys.exit` mockeados — se evitó `runpy.run_path(main.py)` porque re-ejecutaría el código de import de nivel de módulo (registro de skills/orchestrator/tools) sobre los singletons globales ya poblados por el `import main` de la suite, contaminando el resto de los tests. `threading.Thread` mockeado también evita que el hilo `jarvis_runner` (termina en `os._exit(0)`) se ejecute de verdad dentro del proceso de pytest.
2026-08-05 | orion-tester | Veredicto: PASS, 10/10 criterios de SPEC-011 | `python -m py_compile` limpio; `python -m pytest tests/` → 216 passed, 0 failed (197 baseline + 19 nuevos de este REQ), mismos 3 warnings preexistentes, cero fallos nuevos. CA-09 (sin watchdog) verificado por revisión de código (`grep` sin coincidencias en los archivos tocados) según indica la propia arquitectura que no es testeable por unidad. CA-08 y CA-10 verificados también vía `git diff --stat` confirmando que `ui/gui.py`, `start_jarvis.py` y `requirements.txt` no fueron tocados. Ver `pruebas/test-results-011.md` para el detalle completo por criterio. CSV actualizado vía `update-tracker.mjs` (Estado=EN_QA). Handoff documentado a `orion-qa` — no invocado por este agente, queda a la espera de que la sesión orquestadora lo dispare.
2026-08-05 | orion-qa | Veredicto: ✅ COMPLETADO — sin hallazgos de seguridad | Confirmación explícita (`_confirmar()`) verificada en la capa CLI de `setup_autostart.py` antes de `activar()`/`desactivar()` — aborta sin mutar si la respuesta no es afirmativa. `grep` repo-wide confirmó que ningún otro módulo invoca `activar()`/`desactivar()` fuera del propio `__main__` y de los tests — no hay camino de ejecución que mute el registro sin pasar por confirmación. `logger.warning()` verificado en cada mutación real (y correctamente ausente cuando `desactivar()` no borra nada, comportamiento ya testeado por orion-tester). Sin API keys/tokens hardcodeados (`grep -i "api_key\|token\|secret\|password"` sin coincidencias). Sin `except: pass` silencioso — `esta_activo()` captura `FileNotFoundError` como parte del flujo normal esperado, `activar()`/`desactivar()` loguean `OSError` inesperado con `logger.error()` antes de devolver `False`, nunca lo ignoran. Fallback `pythonw.exe → python.exe` bien logueado (no oculto), advierte explícitamente sobre la consola visible. `tests/test_autostart.py` mockea `winreg` por completo — verificado leyendo el archivo íntegro línea por línea, ninguna llamada real a `winreg.*` sin parchear. Re-ejecución independiente de la suite relevante: `pytest tests/test_autostart.py tests/test_main.py tests/test_gui_widgets.py` → 31 passed, 0 failed, consistente con lo reportado por orion-tester. `ui/gui.py`, `start_jarvis.py`, `requirements.txt` confirmados sin cambios vía `git status --short`. Convenciones de `python-style.md` respetadas (type hints, snake_case, docstrings imperativos, sin dead code/prints de debug). Ver `pruebas/qa-audit-011.md` para el detalle completo. CSV sin cambios de Estado en este paso (sigue EN_QA) — se solicitó a Johan la prueba manual final antes de mover a LISTO_PARA_COMMIT.

## Descartado (y por qué)
- Watchdog / reinicio automático de la app ante crash: descartado explícitamente por Johan — fuera de alcance de este REQ.
- Categoría CORE: descartada — el keyword "startup" de CLAUDE.md aplica a la secuencia de arranque interna de la app, no a integración con el inicio de sesión de Windows.
- Un solo REQ combinando branding + auto-inicio: descartado — ver REQ-010 para el detalle del split.

## Asumidos pendientes de confirmar
- Mecanismo concreto de auto-inicio (entrada de registro `HKCU\...\Run`, acceso directo `.lnk` en la
  carpeta de Inicio de Windows, o Tarea Programada al inicio de sesión) sigue SIN decidir — es una
  decisión de arquitectura que le corresponde a `orion-architect`, quien debe evaluar tradeoffs
  (permisos requeridos, resiliencia, facilidad de desinstalar/desactivar). Ver SPEC-011.md, sección
  "Alcance" y "Asumidos", para el detalle que arquitectura debe resolver.
- ~~No se confirmó si debe haber una opción de UI...~~ RESUELTO por orion-spec: paso manual único vía
  script (`setup_autostart.py` o similar), sin opción de UI. Ver "Decisiones tomadas".
- ASUMIDO en SPEC-011 (pendiente de confirmar en arquitectura si cambia el mecanismo elegido): el
  auto-inicio es por-usuario (no a nivel de todos los usuarios de la máquina), y el comando
  registrado ejecuta el proyecto vía `python main.py` (nuevo modo "minimizado") en vez de un
  ejecutable empaquetado, dado que no hay PyInstaller/.spec en el repo.

## Riesgos activos
- **Clasificación de seguridad:** modificar la configuración de inicio de Windows (registro,
  carpeta de Inicio, o Task Scheduler) cae bajo 🟡 Amarillo en `.claude/rules/security-levels.md`
  ("Cambiar configuraciones del sistema"). Este REQ es categoría AUTOMATIZACION, no SEGURIDAD, por
  lo que `orion-security` NO se dispara automáticamente en el pipeline estándar. `orion-architect`
  debe documentar explícitamente el nivel de riesgo elegido y el mecanismo, dejando registrado en
  este contexto si amerita una revisión de seguridad manual antes de `orion-dev`. Confirmación con
  el usuario recomendada si el mecanismo elegido requiere privilegios elevados.
- No depende de los archivos de imagen de branding (REQ-010) — puede avanzar en paralelo sin
  bloqueos cruzados.
- **[orion-architect, 2026-08-05]** El mecanismo elegido (registro `HKCU\...\Run`) NO requiere
  privilegios elevados, así que el riesgo de "confirmación si requiere admin" (SPEC-011, casos
  borde) no se materializa. El riesgo 🟡 Amarillo se mitiga en `setup_autostart.py` con confirmación
  interactiva explícita + `logger.warning()` en cada activación/desactivación — implementado fuera
  de `core/security_manager.py` porque ese gate media acciones vía canal/dispatch, y este script
  corre directo en la terminal de Johan, sin canal involucrado. Queda documentado para que una
  revisión de seguridad manual lo objete si corresponde — ver detalle completo en
  `propuestas/arquitectura-011.md`, sección "Por qué el gate Amarillo se implementa acá".
- **[orion-architect, 2026-08-05]** Riesgo nuevo identificado: si `pythonw.exe` no existe junto al
  intérprete activo, el comando registrado cae a `python.exe`, que muestra una consola visible en
  cada login (no viola CA-03 literal, que es solo sobre la ventana Qt, pero contradice el espíritu
  "sin ventana visible"). Mitigado con `logger.warning()` + aviso al usuario al momento de activar.
  Ver tabla de riesgos en `propuestas/arquitectura-011.md`.

## Log de transiciones
2026-08-05 | — → NUEVO | orion-coordinador | REQ creado, split confirmado por Johan, handoff a orion-spec
2026-08-05 | NUEVO → SPEC_APROBADO | orion-spec | SPEC-011.md redactada, pregunta de clarificación resuelta (script manual, sin UI), aprobada por Johan ("APROBADO tal cual"), handoff a orion-baseline
2026-08-05 | SPEC_APROBADO → EN_ARQUITECTURA | orion-baseline | Baseline-011.md redactado — 0 fallos pre-existentes (py_compile limpio, pytest 197 passed/0 failed), archivos previstos identificados (main.py, start_jarvis.py, script nuevo de autostart, requirements.txt condicional). Handoff a orion-architect.
2026-08-05 | EN_ARQUITECTURA (sin cambio, pendiente aprobación) | orion-architect | Propuesta técnica redactada (`propuestas/arquitectura-011.md`). Estado del tracker NO se mueve a ARQUITECTURA_APROBADA todavía — pendiente de aprobación humana explícita de Johan (Paso 4 de orion-architect). El CSV se actualizará recién cuando llegue esa aprobación.
2026-08-05 | EN_ARQUITECTURA → ARQUITECTURA_APROBADA | orion-architect | Johan aprobó la arquitectura ("APROBADO tal cual"). CSV actualizado vía `update-tracker.mjs` (Aprobacion_Arquitectura=APROBADO, Rama=feature/REQ-011-autostart-windows, Estado=ARQUITECTURA_APROBADA). Handoff documentado a `orion-dev` — no invocado por este agente, queda a la espera de que la sesión orquestadora lo dispare.
2026-08-05 | ARQUITECTURA_APROBADA → EN_PRUEBAS | orion-dev | Implementación completa (`setup_autostart.py` nuevo, `main.py` modificado), `py_compile` limpio, `pytest` 197 passed/0 failed sin regresiones. `desarrollo-log-011.md` generado. CSV actualizado vía `update-tracker.mjs` (Estado=EN_PRUEBAS). Handoff documentado a `orion-tester` — no invocado por este agente, queda a la espera de que la sesión orquestadora lo dispare.
2026-08-05 | EN_PRUEBAS → EN_QA | orion-tester | Tests escritos (`tests/test_autostart.py` nuevo + extensiones de `tests/test_main.py` y `tests/test_gui_widgets.py`), 10/10 criterios de SPEC-011 en PASS, `pytest` 216 passed/0 failed (197 baseline + 19 nuevos), cero regresiones. `pruebas/test-results-011.md` generado. CSV actualizado vía `update-tracker.mjs` (Estado=EN_QA). Handoff documentado a `orion-qa` — no invocado por este agente, queda a la espera de que la sesión orquestadora lo dispare.
2026-08-05 | EN_QA (sin cambio, pendiente prueba manual) | orion-qa | Auditoría de seguridad APROBADA sin hallazgos (ver `pruebas/qa-audit-011.md`). Se solicitó a Johan la prueba manual (8 pasos: activar, reiniciar sesión, confirmar arranque minimizado a bandeja + ícono funcional, closeEvent, desactivar, reiniciar sesión de nuevo, confirmar que ya no arranca) antes de mover el estado a LISTO_PARA_COMMIT. CSV sin cambios en este paso (Estado sigue EN_QA).