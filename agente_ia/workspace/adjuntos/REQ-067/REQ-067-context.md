# Contexto REQ-067 — O.R.I.O.N. en Linux: instalador por Docker para escritorio

## Resumen ejecutivo
Johan preguntó si es posible tener un instalador del proyecto para Linux y si funcionaría
bien. Se auditó el código —no se respondió de memoria— y la respuesta es **sí, con un
alcance que hay que decir en voz alta**: 41 de las 68 herramientas del agente no tienen una
sola línea dependiente de Windows, y varias piezas que se daban por atadas (terminal
embebida, ejecución de proyectos, voz) ya estaban portadas. Lo que no funciona son las
**once herramientas construidas sobre UI Automation** —manejar el navegador, pulsar
controles de otras aplicaciones y el OCR de pantalla—, que en Linux exigen reescribirse
sobre AT-SPI. Johan eligió **escritorio Linux** + **Docker**.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** DOCS | **Tipo:** FEATURE_NUEVA
- **Fecha:** 2026-09-22

## La auditoría, que es lo que sostiene todo lo demás
Script: `pruebas/auditoria-linux.py` (clasifica cada herramienta registrada mirando el
código de su `invoke` y cruzándolo con los módulos atados a Windows).

| Estado | Herramientas |
|---|---|
| **Sin dependencia alguna de Windows** | 41 — chat, proyectos, archivos, git, web, investigación, tareas, intenciones, MCP, imágenes, workspaces |
| **Ya portadas** (tenían rama POSIX escrita de antes) | `terminal_run_command`, `terminal_read_output`, `connection_map` (usa `$SHELL` y `ptyprocess`), `project_run`, `code_index`, `code_search` (usan `/bin/sh`) |
| **Funcionan con reemplazo** | Las 8 de documentos: crear Word/Excel/PowerPoint es multiplataforma; el PDF fiel pasa de Office COM a **LibreOffice** (añadido en este REQ) |
| **Degradadas** | `pc_click`, `pc_type`, `pc_screenshot`: pyautogui **solo bajo X11**; en Wayland no funcionan |
| **No funcionan** | `browser_*` (7), `pc_act`/`pc_find`/`pc_enable_tree` (3), `pc_read` (1) — todas UI Automation |

Fuera del registro de herramientas: apagar/reiniciar (`shutdown /s`), cerrar aplicaciones
(`taskkill`), abrir el explorador (`explorer.exe`), el arranque automático (`winreg`) y las
rutas `C:\Program Files` de Chrome y Spotify.

## Qué se construyó
- `docker/Dockerfile` — `python:3.12-slim-bookworm` + las bibliotecas de Qt y Chromium que
  PyQt6 necesita del sistema, ffmpeg (el TTS reproduce con `ffplay`), portaudio (micrófono),
  **LibreOffice** (el PDF fiel), Tesseract (el reemplazo del OCR de Windows, todavía sin
  usar desde el código), scrot y xdg-utils. `torch` se instala desde el índice **CPU-only**:
  la rueda normal arrastra CUDA y son varios GB que en un escritorio sin NVIDIA no se usan.
- `docker/entrypoint.sh` — el estado (config, claves, memoria, tareas, logs) vive en
  `/datos`, un volumen del equipo, y se enlaza a las rutas donde el código lo busca. **No se
  tocó el código por Docker**: `config_manager.py` sigue leyendo `config.json` al lado suyo.
- `docker/docker-compose.yml` — pantalla (socket X11), audio (PulseAudio + `/dev/snd`),
  la carpeta personal del usuario y `/datos`. Comentado línea por línea.
- `docker/orion.sh` — el lanzador: resuelve el UID para que los archivos que cree el agente
  sean del usuario y no de root, da permiso sobre la pantalla **solo al usuario local**
  (`xhost +SI:localuser:$(id -un)`, no `xhost +`) y lo revoca al salir, y avisa si la sesión
  es Wayland antes de que el usuario descubra solo que el ratón no se mueve.
- `docker/README.md` — qué funciona, qué no (una tabla con las once herramientas), dónde
  queda su información y qué hacer si algo no arranca.
- `.dockerignore` — fuera de la imagen: claves, `config.json`, bases de datos, `USER.md`,
  `MEMORY.md`, `openclaw-main/` (444 MB) y la evidencia del pipeline.

## Cambios de código (mínimos y con valor fuera de Docker)
1. **`requirements.txt`**: `uiautomation` no tenía marcador de plataforma y su dependencia
   `comtypes` es COM puro — `pip install -r requirements.txt` **fallaba entero en Linux**.
   Ahora lleva `; sys_platform == "win32"`, como ya tenían `pywinpty` y `winsdk`.
2. **`core/documentos.py`**: `_con_libreoffice()` ocupa fuera de Windows el lugar de Office.
   Sin esto, un `.docx` hecho sobre la plantilla del usuario se maquetaba a mano con PyMuPDF
   y perdía el membrete y los estilos — justo lo que REQ-040 fue a resolver. Usa un perfil
   descartable: con el perfil de siempre, una segunda instancia se cuelga esperando a la
   que el usuario tenga abierta.
3. **`os_integration/navegador.py`**: el catálogo acepta nombres de ejecutable además de
   rutas, y se resuelven con `shutil.which`. En Linux **abrir** el navegador funciona; leer
   la página sigue sin funcionar y `disponible()` lo dice.

## Decisiones tomadas
2026-09-22 | Johan | Escritorio Linux, no servidor, y por Docker | Elegido en la pregunta con las cuatro opciones.
2026-09-22 | conversación principal | El estado se enlaza desde el entrypoint, no se cambia el código | Una variable de entorno que solo existiera por Docker habría que mantenerla para siempre en un código que corre en Windows.
2026-09-22 | conversación principal | Permiso de pantalla solo al usuario local, y revocado al salir | `xhost +` —lo que suele recomendarse— deja la pantalla abierta a cualquiera mientras dure la sesión.
2026-09-22 | conversación principal | Se monta la carpeta personal entera | Es lo que se parece a Windows, donde el agente escribe en el Escritorio y lee lo que se le pida. Queda dicho en el README y es una línea de cambiar si se quiere acotar.
2026-09-22 | conversación principal | LibreOffice entra en la imagen aunque pese | Sin él, la mitad de REQ-040/065 (seguir la plantilla del usuario) no llega al PDF.
2026-09-22 | conversación principal | El Dockerfile va en dos etapas | PyAudio no publica rueda para Linux y se compila desde fuente: el primer build falló ahí. Compilar en una etapa aparte deja ~250 MB de herramientas fuera de la imagen que se distribuye.
2026-09-22 | conversación principal | `.gitattributes` con `eol=lf` para los scripts | El repositorio se trabaja en Windows y git estaba convirtiendo a CRLF. Un `.sh` con CRLF falla en Linux con «bad interpreter» y el mensaje no menciona los finales de línea: se habría descubierto recién al clonar.

## Qué NO se hizo (y por qué)
- **No se portó UI Automation a AT-SPI.** Es el trabajo grande: son once herramientas y un
  modelo distinto de árbol de accesibilidad. Va como REQ aparte si Johan lo quiere.
- **El OCR no usa Tesseract todavía.** El binario está en la imagen, pero `os_integration/ocr.py`
  sigue siendo solo `Windows.Media.Ocr`. Es un REQ chico y acotado.
- **No se portaron apagar/reiniciar/cerrar aplicaciones** (`shutdown`, `taskkill`).
- **No se tocó Wayland.** No hay arreglo posible desde acá: es una decisión de diseño de
  Wayland. El lanzador avisa.

## Cuatro fallos encontrados **construyendo y ejecutando** la imagen
Ninguno se veía leyendo el Dockerfile. Por eso se construyó de verdad en vez de entregar
los archivos sin probar.

1. **PyAudio no compila**: no publica rueda para Linux y `python:slim` no trae compilador.
   De ahí el build en dos etapas (y la imagen final se queda sin las herramientas).
2. **El entorno virtual desaparecía en un shell de login.** Estaba en `/opt/venv` y metido
   en el `PATH`, pero `bash -l` —que es lo que abre la terminal embebida— rearma el `PATH`
   desde `/etc/profile`: adentro del contenedor `python` pasaba a ser el del sistema y
   **ninguna** dependencia se encontraba. Ahora se instala en el Python del sistema.
3. **Faltaban `libXtst` y `libxkbfile`**: QtWebEngine —la ventana entera del agente— no
   importaba. El error da el nombre del archivo (`libXtst.so.6`), no el del paquete; se
   encontró con `ldd` sobre `libQt6WebEngineCore`, no adivinando.
4. **El resultado mentía sobre quién convirtió el PDF.** En Linux lo hace LibreOffice y el
   agente decía «convertido con Word», en los cuatro sitios donde se arma ese mensaje.
   Ahora `conversor_de()` dice la verdad, con test.

## Dos errores propios, encontrados antes de entregar
- **`IDENTITY.md` tratado como archivo del usuario.** El `.dockerignore` lo excluía de la
  imagen y el entrypoint lo enlazaba a `/datos`, donde habría quedado vacío: el agente del
  contenedor habría arrancado sin carácter, y el síntoma —«responde raro»— no señala a
  Docker por ningún lado. Está versionado, es del proyecto, igual que `SOUL.md`. Corregido
  en los dos archivos y fijado con un test.
- **Los `.sh` iban a salir con CRLF.** No había `.gitattributes` y este repositorio
  convierte a CRLF; al clonar en Linux, `orion.sh` habría fallado con «bad interpreter».
  Corregido, y verificado sobre lo que git realmente guarda (`git show :0:...`), no sobre
  la copia de trabajo. El bit de ejecución también quedó registrado (`100755`).

## Verificación
- `pruebas/auditoria-linux.py` y su salida: la clasificación de las 68 herramientas.
- `pruebas/build-docker.txt`: la construcción real de la imagen.
- `pruebas/verificacion-en-imagen.txt`: **ejecutado dentro del contenedor** — los binarios
  (ffplay, soffice, tesseract, git, scrot, xdg-open), los 13 módulos de Python importando
  en un shell de login, los 4 paquetes de solo-Windows correctamente ausentes, la identidad
  del proyecto dentro y el estado del usuario fuera, y `ES_WINDOWS = False`.
- Documentos generados dentro del contenedor: `.docx` con estilo, `.xlsx` con su fórmula de
  total, y un `.pdf` convertido por LibreOffice que conserva el título y la tabla.
- Tamaño de la imagen: `pruebas/tamano-imagen.txt` (4,85 GB; la mayor parte son torch,
  PyQt6 + QtWebEngine y LibreOffice).
- Los cambios de código se verificaron **en Windows** (que es lo que no se puede romper):
  `ruta_del_navegador()` sigue devolviendo Chrome, y `tests/test_navegador.py` pasa (62).
- 9 tests nuevos en `tests/test_documentos.py` que protegen la instalabilidad en Linux
  desde una máquina Windows, que es donde nadie se entera de que la rompió: marcadores de
  plataforma en `requirements.txt`, finales de línea y shebang de los scripts, secretos
  fuera de la imagen, el PDF delegando en LibreOffice, el navegador por PATH, y la
  identidad del proyecto viajando dentro de la imagen.

## Prueba manual sugerida (Johan)
Esto no se puede probar del todo desde Windows: hace falta un Linux con sesión gráfica.
1. En un Linux: `cd docker && ./orion.sh --construir && ./orion.sh`. Debe abrir la ventana.
2. Pegar una clave en Configuración → Conexiones y conversar.
3. «Hazme un informe en Word y pasalo a PDF» → comprobar que el PDF conserva el formato
   (eso es LibreOffice ocupando el lugar de Office).
4. Abrir la terminal del panel: debe salir tu shell (bash/zsh), no PowerShell.
5. Pedirle que lea una página web con el navegador: **debe decir que no puede**, no fallar
   en silencio.

## Log de transiciones
2026-09-22 | NUEVO → EN_DESARROLLO | conversación principal | Auditoría primero, luego construcción. Spec y arquitectura en este contexto (pipeline acortado).
