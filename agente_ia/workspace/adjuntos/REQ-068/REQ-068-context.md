# Contexto REQ-068 — Linux, fase 1: las acciones del sistema, sin tocar Windows

## Resumen ejecutivo
Johan preguntó qué se puede hacer para que funcione en Linux **sin romper nada de
Windows**. La respuesta de método es esta: en vez de sumar `if os.name == "nt"` a cada
función, se creó una capa de adaptadores (`os_integration/plataforma/`) donde el código de
Windows está **mudado tal cual, no reescrito**, y al lado vive el de Linux. La
implementación se elige una sola vez, al importar. Además, el OCR usa Tesseract fuera de
Windows (`pc_read` deja de estar muerto en Linux) y se agregó CI que corre la suite en
Ubuntu **y** en Windows, que es lo único que impide que el soporte de Linux se rompa sin
que nadie se entere.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE | **Tipo:** MEJORA
- **Fecha:** 2026-09-22

## Origen
Johan, 2026-09-22, tras REQ-067: eligió las fases 1 (acciones del sistema), el CI de Linux
y la 2 (navegador por CDP). Esta es la fase 1 más el CI; la 2 va aparte porque toca código
que hoy funciona en Windows y merece su propio REQ.

## SPEC — criterios de aceptación
| # | Criterio |
|---|---|
| CA-01 | Existe `os_integration/plataforma` con una implementación por sistema, elegida una sola vez al importar; ambas ofrecen exactamente las mismas funciones |
| CA-02 | En Windows, apagar sigue siendo `shutdown /s /t`, cerrar sigue siendo `tasklist`+`taskkill` y abrir una carpeta sigue siendo `explorer.exe`, con los mismos mensajes que antes |
| CA-03 | En Linux: `systemctl poweroff`/`reboot`, `pgrep`+`pkill`, `xdg-open` |
| CA-04 | Los nombres de programa se traducen: «cerrá word» cierra `soffice` en Linux y `WINWORD.EXE` en Windows |
| CA-05 | Lo que no se puede, se explica: sin permiso de logind («pide autenticación»), dentro de un contenedor («apagarlo cerraría la aplicación, no el equipo») y sin la herramienta instalada. Nunca un fallo en silencio |
| CA-06 | El catálogo de aplicaciones de Linux prueba varios candidatos (cada escritorio trae el suyo) y abre el primero instalado |
| CA-07 | `pc_read` funciona en Linux con Tesseract, con los idiomas que haya instalados; en Windows sigue usando `Windows.Media.Ocr` |
| CA-08 | Hay CI que corre la suite en Ubuntu y en Windows, y que además construye la imagen de Docker y comprueba por dentro que los módulos importan |

## Arquitectura
- **`os_integration/plataforma/__init__.py`** — la API (`apagar`, `reiniciar`,
  `cerrar_aplicacion`, `abrir_carpeta`, `abrir_aplicacion`) y `_elegir()`, que resuelve el
  módulo una vez. `NOMBRE` para los mensajes.
- **`_windows.py`** — mudanza literal de lo que estaba en `system_ctrl.py` y
  `system_actions.py`, incluidos los mapas de `.exe` y los textos.
- **`_linux.py`** — el equivalente, con tres decisiones que no son traducción:
  apagar puede no estar permitido (logind) y se dice; dentro de un contenedor apagar
  significa otra cosa y se avisa (`_en_contenedor()` mira `/.dockerenv` y `/proc/1/cgroup`);
  y las aplicaciones se buscan entre varios candidatos por escritorio.
- **`system_ctrl.py` / `system_actions.py`** — conservan su firma y su invariante de
  seguridad (REQ-005: no se auto-protegen), y delegan el «cómo». `open_app_by_name`
  mantiene el menú de inicio **solo en Windows**: teclear en el buscador del escritorio no
  tiene equivalente único en Linux y fingir que sí lo tiene sería peor que decir que no se
  encontró.
- **`ocr.py`** — `disponible()` e `idiomas()` responden por Tesseract fuera de Windows, y
  `leer_imagen()` lo usa (`tesseract <img> stdout -l spa+eng`). El resto del módulo —la
  corrección de cifras, la lectura de una ventana— no cambia.
- **`.github/workflows/tests.yml`** — en la raíz del repositorio (no en `agente_ia/`: ahí
  GitHub no lo lee, y el CI no habría corrido nunca). Dos trabajos: la suite en Ubuntu y
  Windows, y la construcción de la imagen con una comprobación por dentro.

## Decisiones tomadas
2026-09-22 | conversación principal | Adaptadores por plataforma, no más `if` | Windows tenía que quedar igual: su código se muda, y los tests que ya existían lo siguen probando. Un `if` en cada función es una función tocada, y una función tocada puede romperse.
2026-09-22 | conversación principal | Los dos adaptadores se prueban desde cualquier sistema | Se simula `subprocess`; así el CI de Ubuntu verifica el comportamiento de Windows y al revés. Sin esto, la mitad del código nunca se probaría.
2026-09-22 | conversación principal | El menú de inicio queda solo en Windows | No hay un equivalente único en Linux; inventarlo daría una respuesta falsa.
2026-09-22 | conversación principal | El CI también construye la imagen de Docker | Es lo único que detecta que el instalador de Linux dejó de servir (un paquete que desaparece de Debian, una dependencia que cambia).

## Qué puede hacer ahora en Linux
- «Apagá el PC» / «reiniciá» → lo hace, o dice por qué no puede (permiso, contenedor).
- «Cerrá Firefox», «cerrá Word» → cierra el proceso correcto, con su nombre de Linux.
- «Abrí la carpeta de Descargas» → `xdg-open`, con el gestor que el usuario tenga puesto.
- «Abrí la calculadora» → prueba los de cada escritorio y abre el que esté.
- «Leé lo que hay en pantalla» (`pc_read`) → Tesseract.

## Qué no hace todavía
- `window_tracker.py` (listar y enfocar ventanas) sigue siendo solo Windows: en Linux haría
  falta `wmctrl`/`xdotool` y no está resuelto.
- `setup_autostart.py` sigue siendo `winreg`; en Linux sería un `.desktop` en
  `~/.config/autostart`.
- El volumen (`volume_up`/`down`/`mute`) va por teclas multimedia de pyautogui: funciona en
  X11 y no en Wayland.
- Las 11 herramientas de UI Automation (navegador, árbol, `pc_act`) siguen sin funcionar:
  eso es la fase 2 (CDP) y la 3 (AT-SPI).

## Verificación
- `pruebas/suite-068.txt`: suite completa en Windows.
- `tests/test_plataforma.py`: 18 tests nuevos que prueban **los dos** adaptadores.
- El CI probará esto mismo en Ubuntu en el primer push.

## Prueba manual sugerida (Johan / su amigo, en Linux)
1. «Cerrá Firefox» con Firefox abierto: tiene que cerrarse.
2. «Abrí la carpeta de Descargas»: tiene que abrir el gestor de archivos del escritorio.
3. «Apagá el PC» **dentro del contenedor**: debe avisar que es un contenedor, no apagarse.
4. «Leé lo que dice esta imagen» con un PNG con texto: debe leerlo con Tesseract.

## Log de transiciones
2026-09-22 | NUEVO → EN_DESARROLLO | conversación principal | Fase 1 + CI. La fase 2 (navegador por CDP) queda como REQ aparte.
