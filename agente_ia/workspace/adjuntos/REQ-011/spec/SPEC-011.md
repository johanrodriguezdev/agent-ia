# SPEC-011 — Auto-inicio con Windows (arranque minimizado a bandeja)

**Estado:** ✅ COMPLETADO (aprobado por Johan)
**Categoría:** AUTOMATIZACION
**Tipo:** FEATURE_NUEVA
**Fecha:** 2026-08-05

## Objetivo
Hacer que la app arranque sola al iniciar sesión de Windows, sin depender de que Johan la abra
manualmente, quedando minimizada a la bandeja del sistema desde el primer instante (sin mostrar
ninguna ventana en pantalla). La activación/desactivación de este comportamiento es un paso manual
único que corre Johan (no una opción dentro de la GUI).

## Alcance
- Incluye:
  - Un mecanismo de auto-inicio con la sesión de Windows (registro / acceso directo en carpeta de
    Inicio / Tarea Programada — la elección concreta es decisión de `orion-architect`).
  - Un script standalone (ej. `setup_autostart.py` o nombre equivalente que defina arquitectura)
    que activa y desactiva ese mecanismo. Se corre manualmente una vez para activar, y de nuevo
    (con otro flag/argumento) para desactivar.
  - Un modo de arranque de la app en el que la ventana principal (`JarvisMainWindow`) NO se muestra
    (nada de `showMaximized()`/`show()`), pero el ícono de bandeja sí se inicializa y queda
    funcional igual que hoy (`_setup_tray_icon()` en `ui/gui.py`, que ya corre incondicionalmente
    dentro de `__init__`).
- No incluye:
  - Checkbox, toggle ni panel de "Configuración" en la GUI para activar/desactivar el auto-inicio
    — confirmado explícitamente por Johan. Hoy no existe un panel de settings en `ui/gui.py` y
    agregarlo es alcance mayor, fuera de este REQ.
  - Watchdog, supervisión del proceso o reinicio automático ante crash — descartado explícitamente
    por Johan, no agregar aunque parezca relacionado.
  - Empaquetado de la app (PyInstaller / `.exe`) — el repo hoy corre con `python main.py` directo;
    el auto-inicio debe apuntar a ese mismo modo de ejecución, no a un ejecutable nuevo.
  - Elección del mecanismo técnico concreto de auto-inicio de Windows — la decide `orion-architect`
    evaluando tradeoffs (permisos, resiliencia, facilidad de desinstalar).

## Módulos afectados
- `main.py` — hoy el bloque `if __name__ == "__main__":` solo contempla dos modos: GUI visible
  (`window.showMaximized()`) o `--headless` (sin GUI, sin bandeja, loop de consola/voz). Ninguno de
  los dos cumple "minimizado a bandeja, sin ventana visible". Se necesita un tercer modo de arranque
  que construya `JarvisMainWindow` (para que `_setup_tray_icon()` corra) pero nunca llame a
  `show()`/`showMaximized()`.
- `ui/gui.py` — `_setup_tray_icon()` (línea ~193) y `closeEvent()` (línea ~221, ya minimiza a bandeja
  en vez de cerrar el proceso) se reutilizan sin cambios de comportamiento. Verificar en pruebas que
  el tray funciona igual cuando la ventana nunca fue mostrada (no solo cuando fue ocultada después).
- Script nuevo de activación/desactivación (ubicación y nombre exactos = decisión de arquitectura,
  ej. `setup_autostart.py` en la raíz del proyecto) — escribe/borra la entrada de auto-inicio elegida
  por `orion-architect`.
- `start_jarvis.py` — evaluar si se reutiliza como base del comando registrado en el auto-inicio o si
  se necesita un lanzador nuevo; hoy este archivo llama a `main()` directo sin pasar por el bloque
  `if __name__ == "__main__"` de `main.py`, por lo tanto NO inicializa ninguna GUI/bandeja tal cual
  está escrito hoy. Documentar la decisión en la arquitectura.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| El usuario debe abrir la app manualmente cada vez (`python main.py` o acceso directo) | La app arranca sola al iniciar sesión de Windows, sin intervención del usuario |
| `python main.py` siempre muestra la ventana maximizada (`showMaximized()`) | En el arranque automático, ninguna ventana es visible al usuario |
| No existe forma de activar/desactivar un auto-inicio | Un script manual (`setup_autostart.py` o similar) activa/desactiva el auto-inicio en un solo paso |
| `start_jarvis.py` arranca sin GUI ni bandeja (headless real) | El arranque automático sí inicializa la bandeja del sistema (ícono, menú "Mostrar/Ocultar" y "Salir") aunque la ventana no se muestre |

## Criterios de aceptación
- [ ] CA-01: Ejecutar el script de activación registra el mecanismo de auto-inicio elegido por
      arquitectura, apuntando al modo de arranque "minimizado a bandeja" de la app.
- [ ] CA-02: Ejecutar el script en modo desactivación revierte por completo lo creado por CA-01
      (borra la entrada de registro / acceso directo / tarea programada, según el mecanismo
      elegido) — no deja rastros.
- [ ] CA-03: Al iniciar la app mediante el mecanismo de auto-inicio, no se muestra ninguna ventana
      visible en pantalla (no se invoca `show()` ni `showMaximized()` sobre `JarvisMainWindow`).
- [ ] CA-04: Al iniciar por auto-inicio, el ícono de la app aparece en la bandeja del sistema y es
      completamente funcional: doble clic muestra/oculta la ventana, el menú contextual con
      "Mostrar/Ocultar" y "Salir" funciona igual que en un arranque manual normal.
- [ ] CA-05: Ejecutar el script de activación dos veces seguidas es idempotente — no duplica la
      entrada de auto-inicio ni genera errores.
- [ ] CA-06: Ejecutar el script de desactivación cuando el auto-inicio no estaba activo no falla ni
      genera una traza de error visible para el usuario (maneja el caso "nada que borrar").
- [ ] CA-07: El script deja un registro en logs (nivel `WARNING`, según 🟡 Amarillo de
      `.claude/rules/security-levels.md`) cada vez que modifica la configuración de inicio de
      Windows, indicando qué mecanismo se usó y si la acción fue activar o desactivar.
- [ ] CA-08: No existe ningún control (checkbox, menú, panel) dentro de `ui/gui.py` para
      activar/desactivar el auto-inicio — la única vía es correr el script manualmente.
- [ ] CA-09: No se implementa ninguna lógica de watchdog, supervisión de proceso, ni reinicio
      automático ante crash de la app.
- [ ] CA-10: El comportamiento existente de `closeEvent()` (cerrar la ventana minimiza a bandeja en
      vez de terminar el proceso, ver REQ-009/CA-13) no se modifica.

## Casos borde
- El usuario corre el script de desactivación en una máquina donde nunca se activó el auto-inicio
  → no debe fallar (ver CA-06).
- El usuario mueve o borra la carpeta del proyecto sin desactivar antes el auto-inicio → al reiniciar
  Windows, el mecanismo falla al no encontrar el intérprete/proyecto; debe fallar de forma silenciosa
  para el usuario (sin bloquear el login de Windows), no hace falta limpieza automática pero sí que
  no cuelgue el arranque de sesión.
- El mecanismo elegido por arquitectura requiere permisos elevados para activarse/desactivarse → el
  script debe advertir explícitamente antes de ejecutar (no fallar en silencio con una traza confusa).
- Reinicio de sesión rápido (logoff/login sin apagar Windows) mientras la app ya estaba corriendo →
  fuera de alcance de este REQ evitar una segunda instancia (no era un requisito planteado por
  Johan); anotarlo como riesgo conocido, no como criterio de aceptación.

## Asumidos
- ASUMIDO: el auto-inicio es por-usuario (no a nivel de todos los usuarios de la máquina) — no se
  mencionó necesidad multiusuario y evita depender de privilegios de administrador garantizados.
  Confirmar antes de implementar si esto cambia según el mecanismo que elija `orion-architect`.
- ASUMIDO: el comando registrado por el auto-inicio ejecuta el proyecto vía intérprete Python
  (`python main.py` + el nuevo modo/flag "minimizado" de CA-03), no un ejecutable empaquetado — no
  hay PyInstaller ni `.spec` en el repo hoy.
- ASUMIDO: "sin ventana visible" no implica desactivar la creación de `JarvisMainWindow` — implica
  no llamar a `show()`/`showMaximized()` sobre ella, dado que `_setup_tray_icon()` depende de que la
  instancia exista (corre en `__init__`, línea 139 de `ui/gui.py`).
