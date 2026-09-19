# SPEC-043 — Conectar servidores MCP desde la app, sin editar JSON

**Categoría:** INTEGRACION (+ SEGURIDAD) · **Tipo:** FEATURE_NUEVA + SEGURIDAD · **Fecha:** 2026-09-18
**Origen:** punto 5 de la auditoría de capacidades del 2026-09-08 ("Herramientas y APIs:
construido (MCP) pero apagado"). Recomendación aprobada en bloque por Johan la noche del
2026-09-18.

## Problema

El soporte MCP existe y es completo por debajo —cliente stdio/HTTP escrito a mano
(`core/mcp_client.py`), OAuth con PKCE (`core/mcp_oauth.py`), allow-list fail-closed
(`core/remote_tools_policy.py`), gate de seguridad por herramienta, recarga en caliente,
CLI `python -m core.mcp_manager`— pero **la única forma de usarlo es editar dos JSON a mano
y correr comandos en una consola**: `config.json → mcp_servers` para declarar el servidor y
`mcp_allowlist.json` para decir qué herramientas se aceptan. `config.example.json` ni
siquiera muestra la forma. Resultado: nadie lo usa. Es exactamente lo que REQ-030
descartó para las carpetas de trabajo ("decirle sobre qué carpetas trabajar, en vez de
editar un JSON").

OpenClaw (referencia de nivel, `openclaw-main/docs/tools/mcp.md`) lo resuelve con tres
caminos equivalentes: Settings → MCP (agregar, habilitar, deshabilitar, quitar, probar),
el composer del chat, y la CLI. Y con una regla: **las credenciales nunca van literales en
la configuración**.

## Lo que el usuario va a poder hacer

- Decirle al agente: *«conectate al servidor MCP de Notion; el comando es `npx -y
  @notionhq/notion-mcp-server` y necesita la variable NOTION_TOKEN»* → el agente lo declara
  (con confirmación que muestra el comando exacto), lo conecta, lista qué herramientas
  publica, y le pregunta cuáles habilitar.
- *«habilitale search y create_page»* → confirmación con los nombres → quedan disponibles
  en el mismo turno, sin reiniciar.
- *«¿qué servidores MCP tengo?»*, *«probá el de Notion»*, *«deshabilitá el de calendario»*,
  *«quitá el servidor de Notion»*.
- En **Configuración → Conexiones**, debajo de las claves: ver cada servidor con su estado
  (conectado / desconectado / deshabilitado / sin herramientas permitidas), sus
  herramientas permitidas y desde qué canales; pegar el valor de cada `${VARIABLE}` que
  el servidor necesita (sin que pase por el modelo); habilitar/deshabilitar; probar;
  autorizar por OAuth; quitar; y editar la lista de herramientas permitidas.

## Lo que NO va a poder hacer (y por qué)

- Pasarle un token al agente por el chat para que lo guarde: la herramienta solo acepta
  referencias `${VARIABLE}` en `env`/`headers`; un valor literal se rechaza y se le dice
  dónde ponerlo. Un secreto que pasa por el modelo viaja al proveedor del modelo.
- Habilitar herramientas para el canal de correo: la entrada no confiable nunca alcanza
  herramientas amarillas (constraint del proyecto, `project_entrada_no_confiable`).
- Usar nada de esto desde Telegram, Discord o voz: declarar un servidor es habilitar un
  programa que ejecuta código en la máquina; se decide delante del computador.

## Criterios de aceptación

### A. Módulo de configuración (`core/mcp_config.py`)

| # | Criterio |
|---|---|
| CA-01 | `agregar_servidor(nombre, command=…, args=…)` o `(nombre, url=…)` escribe la entrada en `config.json → mcp_servers`; nombre normalizado a minúsculas, patrón `^[a-z][a-z0-9_-]{0,39}$`, `__proto__` y nombres ya usados se rechazan; `command` y `url` a la vez se rechaza; ninguno de los dos se rechaza. |
| CA-02 | Todo valor de `env` y `headers` tiene que ser una referencia `${VARIABLE}`; un literal se rechaza con un mensaje que dice dónde ponerlo (`MCPConfigRechazada`). |
| CA-03 | `permitir_herramientas(nombre, patrones, canales=None)` escribe `mcp_allowlist.json` (forma larga `{tools, canales}`), con escritura atómica; patrones vacíos se rechazan; canales fuera de `{desktop, telegram, discord, voice}` se rechazan (`email`, `api`, `unknown` nunca); por defecto `["desktop"]`; el patrón `*` se acepta pero se avisa en el resultado. |
| CA-04 | `quitar_servidor(nombre)` borra la entrada de `config.json` y de `mcp_allowlist.json`; `habilitar_servidor(nombre, activo)` escribe `enabled`. |
| CA-05 | `listar_servidores()` devuelve, por servidor: nombre, transporte, destino legible, `enabled`, patrones permitidos, canales, si está conectado ahora, herramientas registradas (sin prefijo), variables `${…}` que referencia y si cada una está definida (entorno / archivo / sin definir). **Nunca** el valor de una variable. |
| CA-06 | `definir_variable(nombre, valor)` / `borrar_variable(nombre)` guardan en `config.json → mcp_variables`; `expandir_secreto()` de `mcp_client` resuelve `${VAR}` primero del entorno y después de `mcp_variables`. El nombre de la variable tiene que ser uno que algún servidor declarado referencie (lista cerrada derivada de la configuración, mismo criterio que `_CONEXIONES`). |
| CA-07 | Cada cambio de configuración recarga el servidor afectado en caliente (`mcp_manager.recargar_servidor`) y el resultado se devuelve en palabras: conectado o no, cuántas herramientas publica, cuántas quedaron habilitadas. Un servidor que no levanta no lanza: se informa. |

### B. Herramientas del agente (`agents/tool_registry.py`)

| # | Herramienta | Nivel | Confirmación muestra |
|---|---|---|---|
| CA-08 | `mcp_list_servers` | 🟢, solo escritorio | — |
| CA-09 | `mcp_probe_server` (conecta y lista sin registrar) | 🟢, solo escritorio | — |
| CA-10 | `mcp_add_server` | 🟡, solo escritorio | nombre y comando completo o URL (`name`, `command`/`url`) |
| CA-11 | `mcp_allow_tools` | 🟡, solo escritorio | nombre, patrones y canales (`name`, `herramientas`, `canales`) |
| CA-12 | `mcp_set_server_enabled` | 🟡, solo escritorio | nombre y si se enciende o apaga |
| CA-13 | `mcp_remove_server` | 🟡, solo escritorio | nombre |
| CA-14 | Las seis están en `DESKTOP_ONLY_ACTIONS`, ninguna en `CHANNEL_ACTION_EXCEPTIONS`, y `catalogo_para_modelo(canal_remoto)` no las ofrece. Las cuatro amarillas tienen frase en `core/acciones_legibles.py`. |
| CA-15 | Las herramientas remotas registradas (`mcp__servidor__tool`) tienen frase legible en la confirmación: «use la herramienta 'X' del servidor MCP 'Y'», no «ejecute mcp servidor tool». |
| CA-16 | El resultado de `mcp_add_server` le dice al modelo qué herramientas publica el servidor y que ninguna está habilitada hasta que el usuario elija (para que pregunte, no para que asuma). |

### C. Pantalla Configuración → Conexiones (`ui/webview/`)

| # | Criterio |
|---|---|
| CA-17 | Tarjeta "Servidores MCP" debajo de "Claves y credenciales": una fila por servidor con nombre, destino, chip de estado, herramientas permitidas y canales; y un texto que explica que para agregar uno se le pide al agente (con un ejemplo). Sin servidores: solo ese texto. |
| CA-18 | Por servidor: interruptor habilitado/deshabilitado, botón **Probar** (corre en hilo; el resultado aparece en la fila), botón **Quitar** (pasa por `require_confirmation("mcp_remove_server")` — el slot es alcanzable desde cualquier script de la página), botón **Autorizar** solo si es HTTP y el sondeo pidió OAuth. |
| CA-19 | Campo editable "Herramientas permitidas" (patrones separados por coma) + "Canales"; guardar pasa por `require_confirmation("mcp_allow_tools")` con los patrones a la vista. |
| CA-20 | Bloque "Variables" con una fila por `${VARIABLE}` referenciada: origen (entorno / archivo / sin definir), campo tipo password, Guardar y Quitar. El payload al JS nunca lleva valores. |
| CA-21 | Todos los slots nuevos validan el nombre del servidor contra la configuración actual y el nombre de variable contra las referenciadas; lo que llega del JS no decide qué se escribe. |

### D. Arranque y plantilla

| # | Criterio |
|---|---|
| CA-22 | `config.example.json` muestra la forma de `mcp_servers` (una entrada deshabilitada de ejemplo) y `mcp_variables` vacío, con `_comentario`. |
| CA-23 | Suite completa sin fallos nuevos; tests nuevos para A, B y los slots de C. |

## Fuera de alcance

- Un "catálogo" de servidores conocidos con un clic: los nombres de paquete npm cambian y
  un catálogo desactualizado es peor que ninguno. El agente conoce los habituales y el
  usuario trae el comando.
- Herramientas por sesión / por conversación (OpenClaw "This session"): el modelo de
  seguridad de O.R.I.O.N. es por acción y canal, no por sesión.
- Recursos y prompts de MCP: el cliente los lista en el sondeo, pero no se exponen al
  modelo (igual que hoy).
- Exponer O.R.I.O.N. como servidor MCP (`openclaw mcp serve`).
