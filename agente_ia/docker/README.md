# O.R.I.O.N. en Linux

Instalación por Docker de la aplicación **de escritorio** completa: su ventana, su voz, su
terminal y sus documentos. No es una versión recortada para servidor — pero tampoco es la
de Windows, y esta página dice exactamente en qué se diferencia.

## Instalar

```bash
git clone <el repositorio>
cd agente_ia/docker
./orion.sh --construir     # la primera vez: descarga y arma la imagen
./orion.sh                 # abre la aplicación
```

Hace falta Docker con el complemento `compose`, y una sesión gráfica. En el primer
arranque no hay claves de API: la aplicación abre sola **Configuración → Conexiones** para
que las pegues, y quedan en `docker/datos/config.json`.

| Comando | Qué hace |
|---|---|
| `./orion.sh` | La aplicación con su ventana |
| `./orion.sh --consola` | Modo texto, sin ventana (sirve por SSH) |
| `./orion.sh --bots` | Solo los bots de Telegram y Discord |
| `./orion.sh --construir` | Reconstruye la imagen |
| `./orion.sh --terminal` | Una shell dentro del contenedor |

## Dónde queda tu información

Nada que te importe vive dentro de la imagen: reconstruirla no se lleva tus conversaciones.

- **`docker/datos/`** — configuración, claves, memoria, tareas, logs. Es lo que hay que
  respaldar. Tu clave de API está acá: no subas esta carpeta a ningún lado.
- **Tu carpeta personal** se monta entera en el contenedor, así que el agente crea los
  documentos en tu Escritorio de verdad y puede leer los archivos que le pidas. Si
  preferís acotarlo a una sola carpeta, cambiá esa línea en `docker-compose.yml`.

El código sigue leyendo `config.json` al lado suyo, como en Windows; el `entrypoint.sh` lo
deja apuntando a `datos/`. No se tocó el código por Docker.

## Qué funciona igual que en Windows

Medido sobre el código, no estimado: **41 de las 68 herramientas del agente no tienen una
sola línea dependiente de Windows.**

- Chat, memoria, proyectos de conversación, búsqueda dentro del chat.
- Archivos, git, búsqueda e investigación en la web, Wikipedia.
- Tareas, recordatorios, rituales, intenciones permanentes.
- Servidores MCP, bots de Telegram y Discord, órdenes por correo.
- **Voz**: el TTS (`edge-tts`) y la reproducción (`ffplay`) son multiplataforma.
- **Terminal embebida**: ya estaba portada — usa tu `$SHELL` (bash, zsh, fish) en vez de
  PowerShell, sobre una PTY real (`ptyprocess`).
- **Ejecutar proyectos, indexar y buscar en código**: ya tenían rama POSIX (`/bin/sh`).
- **Documentos**: crear Word, Excel y PowerPoint funciona idéntico. El PDF fiel, que en
  Windows hace Office, acá lo hace **LibreOffice** (viene en la imagen).
- **Imágenes**: mirar una imagen, pegarla en el chat, la tarea de visión.

## Qué NO funciona en Linux

Esto no es una lista de pendientes menores: son capacidades que hoy no existen fuera de
Windows porque están construidas sobre **UI Automation**, la API de accesibilidad de
Windows. El equivalente en Linux es AT-SPI, y no es una traducción: es volver a escribirlo.

| Herramientas | Qué se pierde |
|---|---|
| `browser_open`, `browser_act`, `browser_page`, `browser_text`, `browser_tabs`, `browser_tab_switch`, `browser_tab_close` | Manejar el navegador: leer la página, pulsar enlaces, cambiar de pestaña |
| `pc_act`, `pc_find`, `pc_enable_tree` | Encontrar y pulsar controles de otras aplicaciones por su nombre |
| `pc_read` | Leer texto dibujado en pantalla (el OCR de Windows). La imagen trae Tesseract, pero el código todavía no lo usa |

Además:

- **Apagar, reiniciar y cerrar aplicaciones** usan `shutdown /s` y `taskkill`.
- **Abrir aplicaciones conocidas** busca rutas `C:\Program Files\...`.
- **El arranque automático** se escribe en el registro de Windows.
- **Los temas de diseño de PowerPoint** los aplica el propio PowerPoint; sin él, una
  presentación sin plantilla sale con el diseño básico.

### La trampa de Wayland

`pc_click`, `pc_type` y `pc_screenshot` usan pyautogui, que **solo funciona bajo X11**.
Ubuntu 22.04+ y Fedora arrancan en Wayland por defecto, donde no se puede mover el ratón ni
capturar la pantalla desde otra aplicación — es una decisión de seguridad de Wayland, no un
fallo. El lanzador te avisa si estás en Wayland. Para usar esas funciones hay que entrar en
la sesión **Xorg** desde la pantalla de inicio de sesión.

## Por qué un contenedor para una aplicación de escritorio

Porque instala en un paso y no ensucia el equipo, y porque las dependencias del sistema de
esta aplicación no son pocas: las bibliotecas de Qt y de Chromium, ffmpeg, portaudio,
LibreOffice. Resolverlas a mano en cada distribución es el problema que Docker evita.

El precio es que hay que prestarle al contenedor cosas del equipo: la pantalla (el socket
X11), el audio y tu carpeta personal. Eso está en `docker-compose.yml`, comentado línea por
línea. En particular, el lanzador le da permiso sobre tu pantalla **solo a tu usuario**
(`xhost +SI:localuser:$(id -un)`) y no a todo el mundo, que es lo que suele recomendarse por
ahí, y lo revoca al salir.

## Si algo no arranca

| Síntoma | Qué pasa |
|---|---|
| `could not load the Qt platform plugin "xcb"` | Falta permiso sobre la pantalla: corré `xhost +SI:localuser:$(id -un)` o usá `./orion.sh`, que lo hace solo |
| La ventana abre pero no se escucha nada | Falta el socket de PulseAudio; comprobá que existe `/run/user/$(id -u)/pulse` |
| El micrófono no capta | El contenedor necesita `/dev/snd`; en algunas distribuciones hay que agregar tu usuario al grupo `audio` |
| Los archivos que crea el agente son de root | La imagen se construyó con otro UID: `./orion.sh --construir` de nuevo, desde tu usuario |
| El agente dice que no puede ver la página del navegador | No es un error: en Linux esa capacidad todavía no existe (arriba) |
