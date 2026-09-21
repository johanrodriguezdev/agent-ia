# O.R.I.O.N.

Asistente personal de escritorio para Windows. Escucha por voz, responde por voz, y ejecuta
acciones reales en el sistema — abrir aplicaciones, buscar archivos, crear recordatorios, consultar
el estado del equipo. Funciona desde una ventana de escritorio, desde la consola, o a distancia por
Telegram y Discord.

No es un chatbot con botones: la idea es hablarle como se le habla a una persona. Si le falta un
dato, lo pregunta en vez de inventárselo.

---

## Requisitos

- **Python 3.12+**
- **Windows** — el control del sistema (`pyautogui`, `setx`, gestión de procesos) es específico de
  Windows. El núcleo es portable, pero la integración con el sistema operativo no.
- **FFmpeg en el PATH** — necesario para la síntesis y el reconocimiento de voz.
- **Micrófono** — solo para los modos de voz. El modo texto no lo necesita.

## Instalación

```bash
pip install -r requirements.txt
```

Después hace falta una clave de API: sin ninguna, el agente no tiene con qué responder.

**Desde la aplicación** (lo normal): arranca `python main.py`. En un equipo recién clonado no hay
`config.json`, así que la aplicación abre sola **Configuración → Conexiones**, donde se pegan las
claves. Se guardan en `config.json`, en ese equipo, y no hace falta reiniciar nada ni editar
ningún archivo a mano.

**Como variables de entorno**, si prefieres no dejarlas en un archivo: `setup_api_key.bat` guarda
`ANTHROPIC_API_KEY` de forma permanente, y `setup_bots.bat` instala las dependencias de los bots y
guarda los tokens de Telegram y Discord. Hay que abrir una terminal nueva (o reiniciar el editor)
para que el cambio se detecte.

Si pones las dos, **manda la variable de entorno**. La pantalla de Conexiones lo dice en cada
clave, para que nadie pegue una nueva, la vea guardada, y no entienda por qué sigue sin funcionar.

## Arranque

| Comando | Qué hace |
|---------|----------|
| `python main.py` | Aplicación de escritorio (ventana PyQt6 + WebView). Es el modo normal. |
| `python main.py --tray` | Igual, pero arranca minimizado en la bandeja del sistema. |
| `python main.py --headless` | Consola, con un menú de tres modos: texto, dictado por voz, y manos libres. |
| `python start_bots.py` | Los bots de Telegram y Discord. Acepta `--telegram`, `--discord` o `--all`. |

En modo manos libres, se activa diciendo el nombre del agente (configurable) y a partir de ahí se
mantiene la conversación abierta unos segundos sin repetirlo.

## Configuración

`config.json` guarda el nombre del agente, cómo se dirige a ti, el tema visual, las preferencias
de voz y —si las pones ahí— las claves de API. Se edita desde la pantalla de Configuración de la
aplicación; no hace falta tocarlo a mano.

**No se versiona.** Es estado de una máquina, no del proyecto: `.gitignore` lo excluye y
`config.example.json` queda como plantilla. Si el archivo falta o está corrupto, la aplicación crea
uno nuevo con los valores por defecto — perderlo no rompe nada, solo hay que volver a poner las
claves.

### Quién eres tú y quién es el agente

Cuatro documentos en la raíz le dan al agente su voz y su contexto, y entran en cada llamada al
modelo:

- `SOUL.md` e `IDENTITY.md` — carácter, rol y límites del agente. Son del proyecto y se versionan;
  edítalos si quieres otro tono. El **nombre** del agente no está ahí: se elige en Configuración.
- `USER.md` — quién eres, dónde estás, cómo quieres que te hable. Es tuyo.
- `MEMORY.md` — lo que el agente recuerda entre sesiones. Lo escribe él cuando le pides
  "actualiza tu memoria"; lo que pongas encima de los marcadores se conserva.

`USER.md` y `MEMORY.md` **no se versionan**: al primer arranque se copian de `USER.example.md` y
`MEMORY.example.md`, y desde ahí viven solo en tu equipo.

### El canal de Telegram

Arranca **junto con la aplicación de escritorio**, en su propia ventana de terminal, donde se
ve lo que recibe y lo que responde. Antes había que lanzarlo a mano en otra consola, así que
en la práctica el agente casi nunca estaba disponible desde el teléfono.

No arranca si no hay `TELEGRAM_BOT_TOKEN`, si ya hay otro bot corriendo (Telegram solo admite
un cliente por token: el segundo se queda inútil), o si se apaga con `telegram_autostart` en
`false` dentro de `config.json`. Y muere con la aplicación: nunca queda un canal vivo,
hablando con quien sea, sin nada que lo muestre.

Va en un proceso aparte y no dentro de la app por tres motivos, en orden de peso: la terminal
embebida es 🟡 amarilla y exige confirmación humana —arrancar algo ahí solo saltaría ese
gate—, `run_polling()` monta su propio bucle de eventos y sus manejadores de señales, y si el
bot se cae la app no tiene por qué caerse con él.

`security_overrides.json` es un archivo aparte, a propósito: guarda las subidas de nivel de
seguridad que hayas hecho, y vive separado para que una configuración corrupta nunca pueda
rebajar la seguridad del sistema.

Variables de entorno relevantes: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`,
`OPENROUTER_API_KEY`, y `ORION_AUTH_PIN` para las acciones que exigen verificación.

### Servidores MCP

El agente puede tomar prestadas herramientas de otros programas por el Model Context Protocol
(Notion, GitHub, un calendario, un servidor tuyo). No hace falta editar ningún archivo: se le pide
en el chat —*«conectate al servidor MCP de Notion, el comando es `npx -y @notionhq/notion-mcp-server`
y necesita la variable NOTION_TOKEN»*— y él lo declara (con confirmación que muestra el comando
exacto), lo conecta y te dice qué herramientas publica. **Ninguna queda habilitada hasta que digas
cuáles** (*«habilitale search y create_page»*): lo que no se nombra no entra.

En **Configuración → Conexiones** ves cada servidor con su estado, lo pruebas, lo apagas, lo quitas,
editas qué herramientas acepta y desde qué canales, y pegas los tokens que necesita. Los tokens
nunca pasan por el chat: el agente solo acepta referencias `${VARIABLE}` y el valor se pone en esa
pantalla o como variable de entorno.

### Órdenes por correo

Con el interruptor «Atender órdenes por correo» encendido (Configuración → Seguridad), un correo
**tuyo** —remitente de la lista `command_senders`, verificado por tu servidor de correo— con el
asunto `ORION: …` se resuelve y se responde por correo. Solo puede usar las herramientas MCP de
solo lectura que habilitaste para correo; nada más. El correo sigue sin poder tocar la máquina.

### Un modelo distinto para cada tipo de trabajo

No todo lo que hace el agente necesita el mismo modelo. Resumir un correo o compactar el
historial es trabajo mecánico; contestarte en el chat, no. En **Configuración → Modelos**
puedes asignar a cada tipo de trabajo el modelo que lo atienda:

| Tipo de trabajo | Qué cubre |
|---|---|
| Respuesta principal | Lo que te contesta en el chat. Necesita un modelo con tool-calling. |
| Escribir código | Cuando le pides un script. |
| Trabajo mecánico | Resumir, compactar historial, destilar memoria. Lo que más conviene mandar a un modelo gratuito. |

Lo que no esté asignado usa el modelo general de siempre, así que dejarlo todo vacío deja el
comportamiento exactamente como estaba.

**Se pueden poner varios modelos por tarea, y el orden importa.** Los catálogos gratuitos de
OpenRouter se quedan sin cuota a cada rato: con una lista, el agente pasa al siguiente de la
cadena en la misma llamada en vez de abandonar la tarea o irse a un modelo de pago. Un modelo
que falla por cuota queda apartado unos minutos — solo ese modelo, no el proveedor entero,
porque en OpenRouter la cuota es por modelo.

Para usar los modelos `:free` hace falta una cuenta en [openrouter.ai](https://openrouter.ai)
y su clave en `OPENROUTER_API_KEY` (o en `openrouter_api_key` dentro de `config.json`). Son
gratuitos, pero con límite de peticiones por minuto y por día.

Dos avisos sobre los gratuitos: **no todos soportan tool-calling**, así que para "Respuesta
principal" hay que elegir uno que sí (la pantalla lo dice en la descripción de la tarea); y
**los IDs entran y salen del catálogo** de OpenRouter con el tiempo. Si uno empieza a
responder "model not found", se quita desde la misma pantalla y se pone otro.

También se puede editar a mano en `task_providers` de `config.json`, que acepta tanto un
destino suelto como una lista:

```json
"task_providers": {
    "ligera": {"proveedor": "openrouter", "modelo": "google/gemma-4-31b-it:free"},
    "razonamiento": [
        {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
        {"proveedor": "deepseek", "modelo": "deepseek-chat"}
    ]
}
```

### Imágenes en el chat

El agente ve las imágenes que le mandas, en el escritorio igual que por Telegram y Discord.
Pega una captura con **Ctrl+V** (la de Win+Shift+S, o «Copiar imagen» en el navegador),
arrástrala a la ventana o adjúntala con el clip, y pregunta: «¿qué error es este?», «¿qué
dice este cartel?». La imagen aparece como miniatura en tu mensaje —también al reabrir la
conversación— y un click la muestra a tamaño completo.

Las imágenes pegadas se guardan en `users_data/<usuario>/imagenes/`. Las que superan lo que
los proveedores aceptan (1568 px de lado o 4 MB) viajan al modelo como una copia reducida.
Si tu modelo principal no ve imágenes, pon en `vision_provider` (`config.json`) uno que sí
(por ejemplo `gemini` o `anthropic`): con una imagen de por medio el turno va a ese proveedor.

### Guardar una conversación como archivo

«Guardá esta conversación en un archivo» (o «exportá este chat») deja la conversación
entera como un `.md` en el Escritorio —o en la carpeta que le digas—, con la fecha, el
título y cada mensaje con quién lo dijo. Lo mismo desde la barra lateral: el menú de
cualquier chat tiene «Exportar a Markdown…». Como crea un archivo en tu equipo, pide
confirmación antes.

---

## Cómo está organizado

```
core/           Resolución de comandos, razonamiento con el modelo, seguridad, estado de diálogo
intent/         Clasificador de intenciones (TF-IDF + SVM) entrenado con los ejemplos de las skills
skills/         Habilidades modulares. Se descubren solas: basta crear el archivo
executor/        Handlers heredados, anteriores al sistema de skills
router/         Despachador entre intención y ejecución
os_integration/ Todo lo que toca el sistema operativo: procesos, archivos, capturas, navegador
voice/          Palabra de activación, escucha y transcripción
ui/             Consola, motor de voz, y la aplicación de escritorio en ui/webview/
channels/       Telegram, Discord y la pasarela común
ai/             Proveedores de modelo, memoria semántica, perfiles de usuario
tasks/          Recordatorios y su planificador
agents/         Herramientas que el modelo puede invocar, y ejecución autónoma de planes
tests/          Suite de pytest
```

### El punto por el que pasa todo

`core/resolution.py::resolve()` es el **único** punto de resolución del sistema. Los cuatro canales
—escritorio, voz, Telegram, Discord— entran por ahí, y **el modelo lee siempre primero**: es él
quien decide si el mensaje se contesta hablando o llamando a una herramienta.

Que sea uno solo es deliberado: antes había tres motores divergentes y el comportamiento cambiaba
según por dónde le hablaras.

Que el modelo vaya primero también lo es, y es reciente. Antes había siete heurísticas por delante
—rutinas, planes autónomos, comandos enseñados, tareas, capacidades del sistema, intenciones
clasificadas— y cualquiera podía quedarse con el mensaje sin que el modelo llegara a verlo. El caso
que lo cambió: un JSON de rangos de colores, pidiendo mejorar la paleta, se contestó con
`0 × 12 = 0`, porque el clasificador lo leyó como una multiplicación y tomó los dos primeros
números que encontró.

Ninguna de las siete se perdió: todas siguen ahí como herramientas, y ahora es el modelo el que
elige cuál usar. La única excepción que sigue delante es el **diálogo pendiente**: cuando el agente
acaba de preguntar "¿para cuándo?", la respuesta "mañana a las 9" es el dato que falta, no un
mensaje nuevo.

El coste está asumido: una orden simple como "sube el volumen" ya no se resuelve en local en
milisegundos, cuesta una llamada al modelo. A cambio, no hay heurística que pueda contestar rápido
algo que no se le preguntó.

**Sin conexión, las órdenes locales siguen funcionando.** Si no se consigue hablar con ningún
proveedor, el camino de siempre —rutinas, comandos enseñados, tareas, intenciones clasificadas—
actúa como respaldo, y la respuesta lo dice: *"Sin conexión con el modelo, pero esto sí puedo
hacerlo."* Eso no reintroduce el problema de antes, y la diferencia es toda de orden: esas
heurísticas ya no pueden quedarse con un mensaje que el modelo habría contestado, porque solo
corren cuando el modelo no contestó. Lo que era un filtro delante ahora es una red debajo. Y lo
que ninguna reconoce se responde con la verdad —"no consigo comunicarme con ningún proveedor"—
en vez de con una acción inventada.

### Seguridad

Toda acción está clasificada en uno de tres niveles:

- 🟢 **Verde** — se ejecuta sin preguntar (leer información, buscar, consultar).
- 🟡 **Amarillo** — pide confirmación (borrar, cerrar aplicaciones, apagar, ejecutar código).
- 🔴 **Rojo** — bloqueada salvo permiso explícito y verificado (formatear, tocar el propio código,
  exponer credenciales, instalar software).

El sistema es **fail-closed**: una acción que no esté clasificada explícitamente se bloquea. El
control se aplica en el punto de entrada de cada camino de ejecución, nunca dentro de la acción, y
el canal por el que llegó la orden **nunca se deduce del texto** — siempre lo declara quien la
recibe. Es la diferencia entre una regla de seguridad y una sugerencia.

Desde la pantalla de Configuración se puede **subir** el nivel de una acción, nunca bajarlo.

Los detalles están en [.claude/rules/security-levels.md](.claude/rules/security-levels.md).

---

## Desarrollo

### Tests

```bash
python -m pytest tests/ --tb=short -v
```

Los tests no dependen de red, ni de micrófono, ni de altavoces. Si alguno los necesita, está mal
escrito. Si falta una dependencia opcional (`python-docx`, `uiautomation`, `pymupdf`…), los tests
que la necesitan se saltan y dicen cuál falta; un rojo es siempre un bug de verdad.

### Crear una habilidad

Crea un archivo en `skills/` que herede de `BaseSkill` e implemente sus métodos. No hay que
registrarlo en ningún sitio: `skill_manager` lo descubre al arrancar y sus ejemplos de
entrenamiento alimentan solos al clasificador.

Las reglas están en [.claude/rules/skills.md](.claude/rules/skills.md).

### El pipeline de agentes

Este proyecto se desarrolla con un flujo de agentes especializados que llevan cada requerimiento
desde la idea hasta el commit, con dos pausas de aprobación humana. Cada uno deja evidencia en
`workspace/adjuntos/REQ-XXX/`: especificación, estado previo del sistema, arquitectura, auditoría
de seguridad, resultados de prueba y auditoría de calidad.

El flujo, los comandos y las reglas están en [CLAUDE.md](CLAUDE.md). El estado de cada
requerimiento vive en `requerimientos.csv`, que se escribe **únicamente** mediante
`node .claude/scripts/update-tracker.mjs` — nunca a mano.

### Convenciones

Type hints en todo lo nuevo, líneas de hasta 100 caracteres, `logging` en lugar de `print`, y
ningún `except` que se trague un error sin registrarlo. Está todo en
[.claude/rules/python-style.md](.claude/rules/python-style.md).

---

## Contribuir

Lee [CONTRIBUTING.md](CONTRIBUTING.md): cómo preparar el entorno, qué reglas se aplican a todo
cambio y cuándo abrir un issue antes que un PR. Para reportar una vulnerabilidad, sigue
[SECURITY.md](SECURITY.md) — nunca un issue público.

## Licencia

O.R.I.O.N. se distribuye bajo la **GNU General Public License v3.0** ([LICENSE](LICENSE)). La
licencia la fija PyQt6, que es GPL. El código y los recursos de terceros incluidos en el
repositorio están listados, con su licencia, en [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
