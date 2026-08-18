# Arquitectura REQ-011 — Auto-inicio con Windows (arranque minimizado a bandeja)

**Agente:** orion-architect
**Fecha:** 2026-08-05
**Estado:** ⏸️ PENDIENTE DE APROBACIÓN HUMANA

## Decisión 1 — Mecanismo de auto-inicio elegido: entrada de registro `HKCU\...\Run`

Se evaluaron las tres opciones habilitadas por la SPEC:

| Opción | Permisos | Resiliencia (carpeta movida/borrada) | Desinstalar | Dependencias nuevas | Idempotencia (CA-05) |
|---|---|---|---|---|---|
| **Registro `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`** | Por-usuario, sin admin | Falla la entrada puntual sin bloquear el login (comportamiento nativo de Windows: cada valor de `Run` se ejecuta de forma independiente y no bloqueante) | Un solo `DeleteValue` | Ninguna — `winreg` es stdlib | Trivial: `SetValueEx` sobrescribe el mismo nombre de valor, no puede duplicarse |
| Acceso directo `.lnk` en carpeta de Inicio | Por-usuario, sin admin | Igual de resiliente | Borrar un archivo | Requiere `pywin32` (COM `IShellLink`) o construir el binario `.lnk` a mano (frágil) | Hay que chequear existencia del archivo antes de recrearlo — más código |
| Tarea Programada (`schtasks /Create /SC ONLOGON`) | Por-usuario posible sin admin, pero la superficie de `schtasks.exe` es más grande y más fácil de configurar mal (ej. "Ejecutar con más privilegios") | Igual de resiliente | `schtasks /Delete` | Ninguna (subprocess a binario del sistema), pero exige validar argumentos dinámicos por `python-style.md` (nunca pasar input sin validar a `subprocess`) | `schtasks /Create` sin `/F` falla si la tarea ya existe — hay que manejarlo explícitamente |

**Elegido: registro `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.**

Motivos:
- Es la opción con **cero dependencias nuevas** (usa `winreg`, stdlib), tal como pide el punto 4 de los
  criterios de esta decisión — se descarta `pywin32`/`winshell` explícitamente.
- Es inherentemente **idempotente** (CA-05): `SetValueEx` con el mismo nombre de valor sobrescribe, no
  duplica. Las otras dos opciones requieren código adicional para lograr lo mismo.
- Cumple el caso borde de la SPEC "el usuario mueve/borra la carpeta del proyecto sin desactivar" sin
  código extra: cada entrada de `Run` se ejecuta de forma aislada y no bloqueante — si el intérprete o
  `main.py` no existen, esa entrada puntual falla silenciosamente sin colgar el inicio de sesión de
  Windows ni afectar otras entradas de `Run`.
- No requiere permisos elevados (hive `HKEY_CURRENT_USER`), consistente con el supuesto de la SPEC
  ("por-usuario, sin admin").
- `DeleteValue` es una operación atómica de un solo valor — revertir por completo (CA-02) no deja
  rastros adicionales que limpiar.

Se descarta la Tarea Programada por tener más superficie de configuración (riesgo de marcar sin
querer "ejecutar con privilegios más altos", lo que violaría el supuesto "sin admin" de la SPEC) y por
requerir manejo explícito de idempotencia. Se descarta el acceso directo `.lnk` porque, sin `pywin32`,
construir el binario `.lnk` a mano es fràgil y propenso a errores, y `pywin32` es la dependencia nueva
más pesada de las tres opciones — contradice la preferencia explícita por minimizar dependencias.

## Decisión 2 — Comando registrado: nuevo flag `--tray` en `main.py`, `start_jarvis.py` sin cambios

`start_jarvis.py` fuerza `boot_mode='3'` (manos libres por consola) y **no pasa** por el bloque
`if __name__ == "__main__":` de `main.py` (confirmado por baseline) — no inicializa `QApplication` ni
`JarvisMainWindow`, por lo tanto no hay bandeja. Reutilizarlo forzaría cambiar el significado de un
lanzador que ya tiene un propósito distinto y estable (manos libres headless), con riesgo de romper su
uso actual.

**Se agrega un tercer modo a `main.py`, activado con `--tray`, dejando `start_jarvis.py` intacto.**

Cambio en `agente_ia/main.py`, bloque `if __name__ == "__main__":` (líneas ~182-222 hoy):

```python
if __name__ == "__main__":
    import sys
    import os
    import threading

    headless = "--headless" in sys.argv
    tray_mode = "--tray" in sys.argv          # REQ-011 — arranque minimizado a bandeja

    if not headless:
        try:
            from ui.gui import QApplication, JarvisMainWindow
            app = QApplication(sys.argv)
            window = JarvisMainWindow()
            if not tray_mode:
                window.showMaximized()
            # tray_mode=True: JarvisMainWindow ya corrió _setup_tray_icon() dentro de
            # _init_ui() (incondicional, ver ui/gui.py línea 139) — la bandeja queda
            # funcional sin haber llamado show()/showMaximized() (CA-03, CA-04).
        except Exception as e:
            print(f"[GUI] No disponible, modo headless: {e}")
            headless = True
    ...
```

- `--headless` y `--tray` son mutuamente excluyentes en la práctica: si ambos están presentes,
  `headless` gana (la rama `if not headless` ni siquiera evalúa `tray_mode`) porque el gate de
  `headless` es el primero. Se documenta esto como comportamiento esperado, no se agrega validación
  cruzada extra: el único invocador real de `--tray` es el comando que construye `setup_autostart.py`
  (Decisión 3), que nunca combina ambos flags.
- No se toca `ui/gui.py` — `_setup_tray_icon()` y `closeEvent()` se reutilizan exactamente como están
  (confirmado por baseline: corren sin depender de si `show()` fue llamado). Esto satisface CA-04,
  CA-08 y CA-10 sin tocar ese archivo.
- No se toca `jarvis_runner()` ni la llamada `main(gui_active=(not headless))` — con `--tray`,
  `headless` es `False`, así que `gui_active=True` se propaga igual que en un arranque GUI normal
  (consistente con el comentario existente de REQ-009 sobre ocultar la opción "3" del CLI cuando hay
  GUI activa).

## Decisión 3 — Script standalone: `agente_ia/setup_autostart.py` (raíz del proyecto)

Un único archivo en la raíz (junto a `main.py` y `start_jarvis.py`), tal como sugiere la SPEC como
ejemplo. Se mantiene en un solo archivo (no se crea un paquete nuevo) porque la SPEC pide
explícitamente "un script standalone" y el alcance es acotado; las funciones de lógica de negocio se
separan del bloque `if __name__ == "__main__":` para que sean testeables con `winreg` mockeado, mismo
patrón que ya usa el repo en `main.py`/`start_jarvis.py`.

### API interna (funciones puras, sin `input()`, no lanzan excepciones al caller)

```python
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "Noddoo"   # constante fija — independiente de get_agent_name(),
                                   # para que activar/desactivar detecten la misma entrada
                                   # aunque cambie el nombre de marca mostrado en la UI (REQ-010)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(PROJECT_ROOT, "main.py")

def _resolver_pythonw() -> str:
    """Devuelve pythonw.exe junto al intérprete actual (sys.executable) si existe;
    si no, cae a sys.executable y registra un WARNING (ver Riesgos)."""

def construir_comando_autostart() -> str:
    """Arma la línea de comando a registrar: '"<pythonw>" "<main.py>" --tray'."""

def esta_activo() -> bool:
    """True si AUTOSTART_VALUE_NAME existe hoy en HKCU\\...\\Run."""

def activar() -> bool:
    """Crea/actualiza la entrada (idempotente, CA-05). Loggea WARNING (CA-07).
    Devuelve False solo ante un OSError inesperado (logueado, nunca propagado)."""

def desactivar() -> bool:
    """Borra la entrada si existe; si no existe, no falla (CA-06) y retorna True.
    Loggea WARNING solo cuando sí borró algo (CA-07)."""
```

### CLI (`if __name__ == "__main__":`)

```
python setup_autostart.py --activar     # pide confirmación, luego activar()
python setup_autostart.py --desactivar  # pide confirmación, luego desactivar()
python setup_autostart.py --estado      # solo informa esta_activo(), sin mutar nada
```

`argparse` con grupo mutuamente exclusivo y `required=True` (evita ambigüedad de "qué hace si no le
paso nada"). La confirmación (`_confirmar()`) reutiliza el mismo patrón ya existente en
`main.py::_desktop_confirm()` (prompt + comparación de `sí/si/yes/s`) — es la implementación del gate
🟡 Amarillo de `security-levels.md` ("Cambiar configuraciones del sistema") para esta acción.

**Por qué el gate Amarillo se implementa acá y no vía `core/security_manager.py`:** `security_manager`
media acciones que el agente ejecuta en nombre de un usuario a través de un canal (`dispatch()`,
`skill_manager.execute()`, `agents/action_registry.execute_action()`,
`os_integration/capabilities_router.execute_capability()` — ver `security-levels.md`, sección REQ-005).
`setup_autostart.py` es un script que Johan corre directamente en su propia terminal, fuera de
cualquiera de esos caminos de ejecución — no hay canal, no hay `ChannelType`, no hay sesión del agente
involucrada. Aplicar el mismo patrón de confirmación explícita (no el mismo mecanismo de código) es
consistente con el espíritu de la regla sin forzar una integración artificial. Se dejará constancia de
esta decisión en el contexto del REQ para que quede visible si una revisión de seguridad manual la
quiere objetar (ver "Riesgos activos" del contexto, ya señalado por `orion-baseline`).

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `activar()` en `setup_autostart.py` escribe `AUTOSTART_VALUE_NAME` en `HKCU\...\Run` con el comando de `construir_comando_autostart()`, que apunta a `main.py --tray`. |
| CA-02 | `desactivar()` hace `DeleteValue` sobre el mismo y único nombre de valor — no queda ningún otro artefacto que limpiar (no se crean archivos `.lnk` ni tareas programadas). |
| CA-03 | En `main.py`, con `tray_mode=True` nunca se llama `window.show()` ni `window.showMaximized()`. |
| CA-04 | `JarvisMainWindow()` se instancia igual que en modo GUI normal → `_init_ui()` corre `_setup_tray_icon()` incondicionalmente (sin cambios en `ui/gui.py`, confirmado por baseline) → ícono, menú "Mostrar/Ocultar" y "Salir" quedan funcionales. |
| CA-05 | `winreg.SetValueEx` sobre un nombre de valor fijo sobrescribe en vez de duplicar — dos `activar()` seguidos dejan el mismo estado que uno solo. |
| CA-06 | `desactivar()` atrapa `FileNotFoundError` de `winreg.DeleteValue`/`OpenKey` y retorna `True` sin propagar traza. |
| CA-07 | `activar()` y `desactivar()` (cuando sí borran algo) llaman `logger.warning(...)` indicando mecanismo (`registro HKCU Run`) y acción (activar/desactivar), acorde a la convención de `security-levels.md`. |
| CA-08 | No se modifica `ui/gui.py` — ningún control nuevo en sidebar, menú ni panel. |
| CA-09 | No se agrega ninguna clase/hilo de supervisión, reinicio ni watchdog en ningún archivo de esta propuesta. |
| CA-10 | `closeEvent()` no se toca — se reutiliza tal cual (confirmado por baseline). |

## Módulos a modificar

- `agente_ia/main.py` — bloque `if __name__ == "__main__":` (líneas ~182-222): agregar detección de
  `--tray` y condicionar `showMaximized()` a `not tray_mode`. Sin cambios en `main()` ni en
  `jarvis_runner()`.

## Nuevas clases/funciones

- `_resolver_pythonw()`, `construir_comando_autostart()`, `esta_activo()`, `activar()`, `desactivar()`,
  `_confirmar()` — todas en `agente_ia/setup_autostart.py` (archivo nuevo, funciones a nivel de módulo,
  sin clases — no hay estado que justifique una clase).

## Flujo de datos

**Activación (una vez, manual):**
`Johan` ejecuta `python setup_autostart.py --activar` → `_confirmar()` pide confirmación en consola →
`activar()` construye el comando (`_resolver_pythonw()` + `MAIN_SCRIPT` + `--tray`) → `winreg.SetValueEx`
escribe `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\Noddoo` → `logger.warning(...)` registra la
acción.

**Arranque automático (cada inicio de sesión de Windows):**
Windows lee `HKCU\...\Run` al iniciar sesión → ejecuta el comando registrado
(`pythonw.exe main.py --tray`) → `main.py` detecta `tray_mode=True`, no está `--headless` → crea
`QApplication` + `JarvisMainWindow()` → `_init_ui()` corre `_setup_tray_icon()` → la ventana nunca se
muestra, pero la bandeja queda activa e interactiva de inmediato.

**Desactivación (una vez, manual):**
`Johan` ejecuta `python setup_autostart.py --desactivar` → `_confirmar()` → `desactivar()` →
`winreg.DeleteValue` (o `FileNotFoundError` capturado si no había nada) → `logger.warning(...)` solo si
sí borró algo.

## Archivos a modificar/crear

- `agente_ia/setup_autostart.py` — **nuevo**.
- `agente_ia/main.py` — modificado (bloque `__main__`, ~5-8 líneas).
- `agente_ia/tests/test_autostart.py` — nuevo (ver "Pruebas sugeridas").
- `agente_ia/tests/test_main.py` — extendido con el caso `--tray` (no se crea archivo nuevo).
- `agente_ia/ui/gui.py`, `agente_ia/start_jarvis.py` — **sin cambios** (se dejan constancia explícita,
  no se tocan).
- `agente_ia/requirements.txt` — **sin cambios** (mecanismo elegido no requiere dependencias nuevas).

## Dependencias nuevas

Ninguna. `winreg` es parte de la stdlib de Python en Windows. Se descartan `pywin32`/`winshell`
explícitamente por la Decisión 1.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| Modificar el registro de inicio de Windows es 🟡 Amarillo (`security-levels.md`) | Confirmación interactiva explícita antes de mutar (`_confirmar()`) + logging `WARNING` en cada activación/desactivación (CA-07). Ejecutar sin confirmación explícita no está permitido. |
| `pythonw.exe` no existe junto al intérprete (entornos atípicos: venv recortado, distribución embebida) | `_resolver_pythonw()` cae a `sys.executable` (probablemente `python.exe`, con consola visible en cada login) y registra `logger.warning(...)` al momento de `activar()` para que quede visible en logs; se imprime también al usuario en la consola del script. No bloquea CA-03 (que es específicamente sobre la ventana Qt), pero se documenta como desviación del espíritu "sin ventana visible". |
| Usuario mueve/borra la carpeta del proyecto sin desactivar antes | Comportamiento nativo de `HKCU\...\Run`: cada entrada se ejecuta de forma aislada y no bloqueante — un comando roto en esa entrada no cuelga el login de Windows ni afecta otras entradas. Cumple el caso borde de la SPEC sin código adicional. |
| `--tray` combinado sin querer con `--headless` | `headless` tiene precedencia en el gate existente (`if not headless:`) — documentado como comportamiento esperado; el único invocador de `--tray` es el comando fijo que construye `setup_autostart.py`, nunca un uso manual mixto. |
| Doble instancia en logoff/login rápido mientras la app ya corría | Fuera de alcance explícito de la SPEC (no se pidió deduplicación) — aceptado como riesgo conocido, sin mitigación en este REQ. |
| Tests que ejerciten `activar()`/`desactivar()` toquen el registro real del usuario que corre pytest | Mockear `winreg` por completo (`unittest.mock.patch`) en todos los tests — nunca ejecutar contra `HKEY_CURRENT_USER` real, según `testing.md`. |
| El valor de registro `AUTOSTART_VALUE_NAME="Noddoo"` es fijo, no deriva de `get_agent_name()` | Decisión deliberada (Decisión 3): si el nombre de marca cambia (REQ-010 u otro), `activar()`/`desactivar()` siguen detectando la misma entrada porque el nombre técnico del valor no depende de la configuración de branding. |

## Pruebas sugeridas

- **CA-01** — `test_activar_registra_comando_con_flag_tray`: mockear `winreg.CreateKeyEx`/`SetValueEx`,
  verificar que se llama con `AUTOSTART_VALUE_NAME` y un comando que contiene `--tray` y la ruta a
  `main.py`.
- **CA-02** — `test_desactivar_borra_la_entrada_por_completo`: mockear `winreg.DeleteValue`, verificar
  llamada con el mismo `AUTOSTART_VALUE_NAME`; luego `esta_activo()` con `QueryValueEx` mockeado para
  lanzar `FileNotFoundError` debe devolver `False`.
- **CA-03** — `test_main_tray_mode_no_llama_show`: parchear `sys.argv=["main.py","--tray"]` y mockear
  `JarvisMainWindow`, ejecutar el bloque `__main__` (vía `runpy` o extrayendo la lógica a una función
  testeable), verificar `window.showMaximized.assert_not_called()` y `window.show.assert_not_called()`.
- **CA-04** — `test_tray_icon_activo_sin_ventana_mostrada`: instanciar `JarvisMainWindow()` sin llamar
  `show()`, verificar que `self.tray_icon` existe y que `_setup_tray_icon()` corrió (extiende los tests
  ya existentes de REQ-009 con el caso explícito "nunca fue mostrada").
- **CA-05** — `test_activar_dos_veces_es_idempotente`: llamar `activar()` dos veces con mocks,
  verificar que `SetValueEx` se llamó dos veces con el mismo par (nombre, comando) y sin excepción.
- **CA-06** — `test_desactivar_sin_autostart_previo_no_falla`: mockear `DeleteValue`/`OpenKey` para
  lanzar `FileNotFoundError`, verificar que `desactivar()` retorna `True` sin propagar la excepción.
- **CA-07** — `test_logging_warning_al_activar_y_desactivar`: usar `caplog` de pytest, verificar
  nivel `WARNING` y que el mensaje incluye el mecanismo (`registro HKCU Run`) y la acción.
- **CA-08** — `test_gui_sin_controles_de_autostart`: revisión estática/funcional de `ui/gui.py`
  confirmando que no aparece ningún widget, acción de menú ni ítem de sidebar relacionado a
  "autostart"/"auto-inicio".
- **CA-09** — revisión manual en QA (no es un criterio fácilmente testeable por unidad): confirmar que
  el diff de `orion-dev` no introduce clases/hilos de supervisión, reinicio o watchdog.
- **CA-10** — los tests existentes de `closeEvent()` (REQ-009) deben seguir pasando sin modificación;
  agregar un assert explícito si no hay uno que cubra literalmente "cerrar minimiza en vez de cerrar
  el proceso" ya cubierto.
- Extra: `test_resolver_pythonw_fallback_a_sys_executable` (mockear `os.path.isfile` → `False`,
  verificar retorno y `logger.warning`), `test_estado_refleja_registro` (`esta_activo()` con
  `QueryValueEx` mockeado en ambos sentidos).
