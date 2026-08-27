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

Después, configura la clave de la API del modelo:

```bash
setup_api_key.bat
```

Guarda `ANTHROPIC_API_KEY` como variable de entorno permanente. Hay que abrir una terminal nueva
(o reiniciar el editor) para que el cambio se detecte.

Si vas a usar los bots, ejecuta también `setup_bots.bat`: instala sus dependencias y guarda los
tokens de Telegram y Discord.

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

`config.json` guarda el nombre del agente, cómo se dirige a ti, el tema visual y las preferencias
de voz. Se puede editar desde la pantalla de Configuración de la aplicación; no hace falta tocarlo
a mano.

`security_overrides.json` es un archivo aparte, a propósito: guarda las subidas de nivel de
seguridad que hayas hecho, y vive separado para que una configuración corrupta nunca pueda
rebajar la seguridad del sistema.

Variables de entorno relevantes: `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`,
y `ORION_AUTH_PIN` para las acciones que exigen verificación.

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
—escritorio, voz, Telegram, Discord— entran por ahí y recorren la misma lista ordenada de
estrategias: rutinas aprendidas, planes autónomos, comandos enseñados, tareas, capacidades del
sistema, intenciones clasificadas, y por último el modelo de lenguaje.

Que sea uno solo es deliberado: antes había tres motores divergentes y el comportamiento cambiaba
según por dónde le hablaras.

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
escrito.

> Dos tests de `tests/test_llm_provider.py` fallan si el paquete `anthropic` no está instalado
> (está comentado en `requirements.txt`). Es un fallo de entorno conocido, no de código.

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
