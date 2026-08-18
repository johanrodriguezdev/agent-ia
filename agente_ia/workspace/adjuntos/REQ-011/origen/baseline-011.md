# Baseline REQ-011 — Auto-inicio con Windows (arranque minimizado a bandeja)

**Agente:** orion-baseline
**Fecha:** 2026-08-05

## Estado actual del sistema

Funcionalidad nueva — no existe hoy ningún mecanismo de auto-inicio con Windows (ni entrada de
registro `HKCU\...\Run`, ni acceso directo `.lnk` en la carpeta de Inicio, ni Tarea Programada, ni
ningún script `setup_autostart.py` o equivalente). Búsqueda exhaustiva (`winreg`, `HKCU`,
`CurrentVersion\Run`, `schtasks`, `Task Scheduler`, `.lnk`, `autostart`) en todo el árbol de código
solo encontró dos coincidencias, ambas ajenas al alcance de este REQ:
- `core/proactive_engine.py:111` y `main.py:62` — un trigger `"startup"` del motor de rituales
  proactivos internos de la app (dispara un saludo/briefing cuando `main()` arranca). Esto es la
  secuencia de inicialización *interna* de Noddoo una vez que el proceso ya está corriendo, no
  integración con el inicio de sesión de Windows — coincide con lo ya descartado en el contexto al
  elegir categoría AUTOMATIZACION sobre CORE.

`requirements.txt` no incluye `pywin32` ni `winshell` — cualquier mecanismo que arquitectura elija
que dependa de esas librerías implicaría una dependencia nueva (a documentar en la propuesta de
arquitectura). El módulo estándar `winreg` sí está disponible sin dependencias extra.

### `main.py` — bloque `if __name__ == "__main__":` (líneas ~234-269 del archivo actual)
Hoy contempla exactamente dos modos, ninguno cumple "minimizado a bandeja, sin ventana visible":
- **Modo GUI (default, sin `--headless`):** crea `QApplication`, instancia `JarvisMainWindow()` y
  llama `window.showMaximized()` incondicionalmente — la ventana siempre se muestra.
- **Modo `--headless`:** salta por completo la creación de `QApplication`/`JarvisMainWindow` (bloque
  `try` no se ejecuta) — no hay bandeja, no hay ícono, solo el loop de consola/voz en un hilo
  (`jarvis_runner` vía `main(gui_active=False)`).

No existe hoy un tercer modo que construya `JarvisMainWindow` (para que `_setup_tray_icon()` corra)
sin invocar `show()`/`showMaximized()`.

### `start_jarvis.py`
Llama a `main()` (de `main.py`) **directamente**, sin pasar por el bloque `if __name__ ==
"__main__":` de `main.py`. Confirmado por lectura del archivo completo:
```python
from main import main

if __name__ == "__main__":
    main(boot_mode='3')
```
Por lo tanto, tal como está escrito hoy, `start_jarvis.py` **no inicializa ninguna GUI ni bandeja**
— es un lanzador headless real (fuerza `boot_mode='3'`, manos libres/wake word por consola). No
sirve tal cual como comando de auto-inicio si CA-04 (bandeja funcional) debe cumplirse; arquitectura
debe decidir si se modifica, se reemplaza o si el auto-inicio apunta directo al nuevo modo de
`main.py`.

### `ui/gui.py` — comportamiento de bandeja a reutilizar sin cambios
- `JarvisMainWindow.__init__()` (línea 91) llama a `_init_ui()` (línea 97), que en su última línea
  (línea 139) llama a `self._setup_tray_icon()` **incondicionalmente** — corre siempre que se
  instancia la clase, sin depender de que `show()`/`showMaximized()` se haya llamado antes o
  después. Esto confirma el supuesto de SPEC-011: instanciar `JarvisMainWindow()` sin mostrarla es
  suficiente para que la bandeja quede activa.
- `_setup_tray_icon()` (líneas 193-212): crea `QSystemTrayIcon`, ícono, tooltip, menú contextual
  ("Mostrar/Ocultar" → `_toggle_visible()`, "Salir" → `QApplication.instance().quit()`),
  `activated` → `_on_tray_activated()` (doble clic alterna visibilidad), y `.show()` del ícono de
  bandeja. No depende de estado de visibilidad de la ventana.
- `closeEvent()` (líneas 221-231): ya minimiza a bandeja en vez de cerrar el proceso (`event.ignore()`
  + `self.hide()` + notificación toast) — comportamiento de REQ-009/CA-13, a preservar sin cambios
  (CA-10 de SPEC-011).
- Nota aparte (fuera del árbol de ejecución de `main.py`, no mencionado en SPEC-011 pero visible en
  el archivo): `ui/gui.py` tiene su propio bloque `if __name__ == "__main__":` al final (líneas
  234-238) que también llama `showMaximized()` — es un entry point standalone para probar la GUI
  aislada, no el camino que usa `main.py` ni `start_jarvis.py`. No requiere cambios para este REQ.

## Archivos que serán modificados (previsión)

- `agente_ia/main.py` — agregar un tercer modo de arranque en el bloque `if __name__ ==
  "__main__":` (nombre/flag exacto a definir por arquitectura, ej. `--tray` o `--autostart`) que
  instancie `JarvisMainWindow` sin llamar `show()`/`showMaximized()`.
- `agente_ia/start_jarvis.py` — a evaluar por arquitectura: modificarlo para que pase por el nuevo
  modo de `main.py`, o dejarlo intacto si el auto-inicio apunta a `main.py` directo con el flag
  nuevo. Documentado como decisión abierta en SPEC-011.
- Script nuevo de activación/desactivación del auto-inicio — ubicación y nombre exactos pendientes
  de arquitectura (ej. `setup_autostart.py` en la raíz del proyecto, mencionado como ejemplo en
  SPEC-011, no como decisión final).
- `agente_ia/requirements.txt` — condicional: solo si arquitectura elige un mecanismo que requiera
  una librería nueva (ej. `pywin32` para acceso directo `.lnk` vía COM); no es necesario si se usa
  `winreg` (stdlib) o `schtasks` por subprocess.
- `agente_ia/ui/gui.py` — **no se prevé modificación** (`_setup_tray_icon()` y `closeEvent()` se
  reutilizan sin cambios, según SPEC-011); se incluye acá solo para dejar constancia de que fue
  revisado y confirma el comportamiento esperado.

## Fallos pre-existentes (no atribuibles a este REQ)

- `python -m py_compile main.py start_jarvis.py ui/gui.py` → compilación limpia, sin errores
  (exit code 0).
- `python -m pytest tests/ --tb=short` → **197 passed, 0 failed**, 3 warnings no relacionados
  (deprecation de `aifc`/`audioop` en la librería `speech_recognition`, y un
  `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator` por un `return`
  en vez de `assert` — preexistente, no toca ningún archivo de este REQ).
- Ninguno de los tests existentes (`tests/test_main.py`, `tests/test_cli_gui_active.py`,
  `tests/test_gui_widgets.py`, `tests/test_gui_workers.py`, `tests/test_wake_word_gui.py`) ejercita
  directamente el bloque `if __name__ == "__main__":` de `main.py` ni el arranque real de
  `start_jarvis.py` — solo prueban funciones internas (`main(gui_active=...)`, widgets, workers).
  No hay tests hoy para "modo minimizado a bandeja" porque el modo no existe todavía.
- **Conclusión: ninguno**. No hay fallos pre-existentes que este REQ deba arrastrar o que puedan
  confundirse con una regresión introducida por REQ-011.

## Nota sobre REQ-010 (branding, en paralelo)
No se tocó ni se inspeccionó ningún archivo de imagen/branding de REQ-010. Los módulos revisados
acá (`main.py`, `start_jarvis.py`, `ui/gui.py`) son compartidos entre ambos REQs solo en el sentido
de que ambos viven en el mismo repo, pero REQ-011 no modifica nada relacionado a branding.
