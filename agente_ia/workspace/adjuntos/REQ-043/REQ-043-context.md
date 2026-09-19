# Contexto REQ-043 — Conectar servidores MCP desde la app, sin editar JSON

## Resumen ejecutivo
Cierra el punto 5 de la auditoría de capacidades del 2026-09-08 ("Herramientas y APIs:
MCP construido pero apagado"). El soporte MCP ya era completo por debajo (cliente
stdio/HTTP, OAuth, allow-list fail-closed, recarga en caliente, CLI) pero solo se manejaba
editando `config.json` y `mcp_allowlist.json` a mano. Ahora el agente declara, prueba,
habilita, apaga y quita servidores por instrucción (seis herramientas `mcp_*`, gate
amarillo con el comando a la vista, solo escritorio), la pantalla Configuración → Conexiones
los muestra y administra, y los secretos se pegan ahí — nunca pasan por el chat.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión nocturna autorizada por Johan, 2026-09-18)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** INTEGRACION · **Tipo:** FEATURE_NUEVA + SEGURIDAD

## Origen
Revisión de estado del 2026-09-18: de las 7 capacidades auditadas el 2026-09-08, la 5 era
la única que seguía en "construido pero apagado". Johan aprobó en bloque las
recomendaciones antes de irse a dormir, y pidió que al terminar siguiera mejorando solo.
Nivel de referencia: OpenClaw (`openclaw-main/docs/tools/mcp.md`): Settings → MCP con
agregar/habilitar/deshabilitar/quitar/probar, composer, CLI, y "las credenciales nunca van
literales en la configuración".

## Qué se puede hacer ahora (ejemplos)
- *«Conectate al servidor MCP de Notion: el comando es `npx -y @notionhq/notion-mcp-server`
  y necesita la variable NOTION_TOKEN»* → modal con el comando exacto → conecta → «Publica 8
  herramientas: search, create_page, … Ninguna está habilitada todavía: ¿cuáles querés?»
- *«Habilitale search y create_page»* → modal con `herramientas search / create_page` →
  quedan disponibles en el mismo turno.
- *«¿Qué servidores MCP tengo?»*, *«probá el de Notion»*, *«deshabilitá el de calendario»*,
  *«quitá el servidor docs»*.
- Configuración → Conexiones → «Servidores MCP»: estado por servidor, interruptor, Probar,
  Autorizar (OAuth, solo HTTP), Quitar, herramientas permitidas + canales, y el bloque
  «Variables» para pegar los tokens.

## Qué NO se puede (y por qué)
- Pasarle el token al agente por el chat: rechazado por construcción (`env`/`headers` solo
  `${VARIABLE}`); el mensaje dice dónde ponerlo.
- Habilitar herramientas para correo/API: `CANALES_HABILITABLES` no los incluye.
- Nada de esto desde Telegram/Discord/voz: las seis `mcp_*` están en `DESKTOP_ONLY_ACTIONS`.
- Agregar un servidor desde la pantalla con formulario: se le pide al agente (decisión de
  diseño: asistente, no CRUD — `feedback_asistente_no_crud`).

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->
2026-09-18 | conversación principal | Pipeline acortado: spec + arquitectura + implementación en la misma sesión, sin subagentes; aprobación cubierta por la autorización nocturna en bloque | Precedente REQ-027/029/032/038-040. Spec en `spec/SPEC-043.md`, arquitectura en `propuestas/arquitectura-043.md`.
2026-09-18 | conversación principal | Módulo nuevo `core/mcp_config.py` como único escritor de `mcp_servers`, `mcp_variables` y `mcp_allowlist.json`; `mcp_manager`/`mcp_client`/`remote_tools_policy`/`mcp_oauth` no cambian de responsabilidad | Un solo sitio que valida y escribe; los tres módulos existentes siguen haciendo lo suyo (protocolo, registro, política).
2026-09-18 | conversación principal | `env`/`headers` solo aceptan `${VARIABLE}`; un literal se rechaza con el mensaje de dónde ponerlo | Lo que el modelo escribe viaja al proveedor del modelo. Regla tomada de OpenClaw ("keep credentials out of config literals") y llevada a "rechazo", no a "recomendación".
2026-09-18 | conversación principal | Los valores viven en `config.json → mcp_variables`, escritos solo desde la pantalla; `expandir_secreto()` resuelve entorno → archivo | Mismo lugar y misma prioridad que las claves de API (`_ENV_KEY_MAP`). `definir_variable()` solo acepta nombres que algún servidor referencie: lista cerrada derivada, criterio de `_CONEXIONES`.
2026-09-18 | conversación principal | `mcp_add_server` recibe `command` como cadena completa y `partir_comando()` la parte con `shlex` (posix=False, comillas envolventes quitadas) | Con `args` aparte el modal decía solo "npx". `command` ya estaba en `_DETAILS_ALLOWED_KEYS`. Rutas de Windows con espacios entre comillas funcionan (test).
2026-09-18 | conversación principal | `herramientas` y `canales` entran en `_DETAILS_ALLOWED_KEYS` y `format_details()` escribe las listas con " / " en vez de su `repr` | El `repr` de una lista trae comas, que es el separador con el que `detalle_legible()` parte los campos: el modal mostraba «herramientas ['search', desde ['desktop'?». Bug latente que afectaría a cualquier parámetro lista futuro.
2026-09-18 | conversación principal | `desktop` se agrega siempre a los canales de la allow-list; `email`/`api`/`unknown` nunca | El escritorio es donde se confirma; sin él una amarilla quedaría solo en canales que no muestran el modal. La entrada no confiable no alcanza amarillas (constraint del proyecto).
2026-09-18 | conversación principal | Las seis `mcp_*` en `DESKTOP_ONLY_ACTIONS`; listar y probar 🟢, el resto 🟡 | Declarar un servidor stdio arranca un proceso: mismo caso que `terminal_open`. No rojo por el autobloqueo sin PIN (mismo motivo que `_nivel_declarado()`).
2026-09-18 | conversación principal | `describir()` reconoce `mcp__servidor__tool` → «use la herramienta 'X' del servidor MCP 'Y'» | La derivada decía «ejecute mcp notion search»: ni dice que es remota ni de quién.
2026-09-18 | conversación principal | Quitar y cambiar la allow-list desde la pantalla pasan por `require_confirmation` con los mismos `action_name` que las herramientas | Los slots son alcanzables desde cualquier script de la página (criterio de `delete_conversation`/`terminal_open`). Un solo nombre → una sola clasificación, un solo texto, una sola entrada de auditoría.
2026-09-18 | conversación principal | Sin formulario "Agregar servidor" en la pantalla; la tarjeta explica cómo pedírselo al agente con un ejemplo | `feedback_asistente_no_crud`. La pantalla es para lo que NO debe pasar por el chat (secretos) y para ver/apagar/probar/quitar.
2026-09-18 | conversación principal | Sin catálogo de servidores conocidos con un clic | Los nombres de paquete npm cambian; un catálogo desactualizado es peor que ninguno. `config.example.json` muestra la forma con una entrada deshabilitada.
2026-09-18 | conversación principal | Arreglo colateral: los botones «Quitar» de la tarjeta de claves usaban la clase `panel-secondary-btn`, que no existe en ningún CSS (texto blanco sobre gris claro); pasan a `panel-submit-btn panel-submit-btn-secundario` | Se vio en la captura offscreen (`project_captura_ui_offscreen`) al renderizar la sección con datos de demo, oscuro y claro.
2026-09-18 | conversación principal | `renderConnections()` reemplaza por `#connections-card` y no por la primera `.settings-card` | Con dos tarjetas en la sección, la selección por clase habría pisado la tarjeta equivocada.

### Revisión de código posterior (misma noche)
2026-09-18 | conversación principal (`/code-review` sobre los commits de la noche) | 15 hallazgos; corregidos en el commit de fixes | (1) `mcp_add_server` aceptaba un `args` que el modal no mostraba → eliminado, el comando va completo en `command`. (2) `set_mcp_server_enabled` del bridge encendía un servidor (arranca su proceso) sin gate → ahora confirma con `mcp_set_server_enabled`, como la herramienta. (3) Nombres con `__` o `_` final colisionaban con el separador `mcp__servidor__tool` → rechazados. (4) `detalle_legible()` partía por toda coma y un comando con comas se mostraba cortado → parte solo en `, clave=`. (5) `env` con `url` / `headers` con `command` se descartaban en silencio → se rechazan con el motivo. (6) Una allow-list ilegible se reescribía desde `{}` borrando lo de los demás → se rechaza la escritura. (7) El toast de la pantalla mostraba texto redactado para el modelo → `aplicar()` devuelve datos y hay `resumen_para_modelo` / `resumen_para_humano`. (8) `memory_scoring` releía config.json en el bucle O(N²) → palabras vacías una vez por agrupamiento y caché por candidato. (9) Gemini y Ollama no pasaban techo de salida → `max_output_tokens` / `num_predict`. (10) `save_config()` no era atómico y tragaba el error → temporal + `os.replace`, devuelve `bool`, y `mcp_config` lanza `OSError` si no se escribió. (12) El login OAuth se detectaba buscando "autorizado" en el texto → `login_servidor_detallado()` devuelve `(bool, texto)`. (13) Se ofrecían `discord`/`voice` sin adaptador de confirmación (la herramienta se habría denegado) → `CANALES_HABILITABLES = (desktop, telegram)`. (14) `_cerrar_sin_herramientas` duplicaba `_llamada_de_cierre` → `reasoning_loop.cerrar_sin_herramientas()` compartida. (15) `_mcp_nombre_valido` listaba todo para validar un nombre → `mcp_config.existe()`. Y el riesgo pre-existente de que `load_config()` pisara un config.json corrupto con los valores por defecto (borrando claves de API, servidores MCP y tokens) se mitigó: el archivo roto se aparta como `config.json.corrupto-<fecha>` (ignorado por git) antes de crear uno nuevo, con test.

## Descartado (y por qué)
- Herramientas por sesión (OpenClaw "This session") — el modelo de seguridad es por acción y
  canal, no por sesión.
- Exponer recursos/prompts MCP al modelo — el sondeo los cuenta; no hacen falta para lo que
  el agente necesita hoy.
- Rojo para `mcp_add_server` — autobloqueo sin `ORION_AUTH_PIN`.

## Asumidos pendientes de confirmar
- Que Johan esté de acuerdo en que agregar un servidor sea 🟡 (con el comando a la vista) y
  no 🔴. Está argumentado arriba; si prefiere rojo, es cambiar el nivel en `ToolSpec`.
- La pantalla no tiene formulario de alta; si en la prueba manual lo echa de menos, es una
  tarjeta más sobre los mismos slots (`agregar_servidor` ya existe en `mcp_config`).

## Prueba manual sugerida (para Johan)
1. Abrir la app → Configuración → Conexiones: debe verse «Servidores MCP» vacío con el texto
   de ayuda.
2. En el chat: *«conectate a un servidor MCP llamado prueba, el comando es
   `npx -y @modelcontextprotocol/server-everything`»* (requiere Node). Confirmar en el modal
   (tiene que mostrar el comando completo). Debe responder cuántas herramientas publica y que
   ninguna está habilitada.
3. *«habilitale echo y add»* → modal con «herramientas echo / add» → *«usá echo con hola»*
   → debe pedir confirmación «use la herramienta 'echo' del servidor MCP 'prueba'».
4. Volver a Configuración → Conexiones: fila «prueba», Conectado · 2 herramientas. Probar
   (sale el listado), apagar con el interruptor (el chat deja de tener las herramientas),
   Quitar (pide confirmación).
5. Intentar *«conectate a X con NOTION_TOKEN=ntn_abc»* → debe rechazar y decir dónde va el
   token.

## Verificación
- `tests/test_mcp_config.py`: 36 passed (nuevo).
- `tests/test_mcp_tools.py`: 22 passed (nuevo).
- `tests/test_webview_mcp.py`: 18 passed (nuevo).
- `tests/test_mcp_manager.py`, `test_mcp_client.py`, `test_remote_tools_policy.py`,
  `test_voice_confirmation.py`, `test_security_manager.py`: sin cambios de resultado.
- Captura offscreen de Configuración → Conexiones con 3 servidores de demo (conectado /
  desconectado con sondeo 401 / deshabilitado) en oscuro y claro: layout correcto, botones
  legibles tras el arreglo colateral.
- Suite completa: ver "Log de transiciones".

## Riesgos activos
- `aplicar_y_resumir()` conecta dentro del turno: un servidor stdio que tarde en arrancar
  bloquea hasta `connect_timeout` (10 s). Aceptado: es una vez, al declararlo.
- Un servidor stdio que el usuario declare ejecuta lo que ese paquete haga (como cualquier
  `npx -y`). El modal muestra el comando; la responsabilidad de qué se instala es del usuario,
  igual que en la terminal embebida.

## Log de transiciones
2026-09-18 | — → NUEVO | conversación principal | REQ creado vía update-tracker.mjs
2026-09-18 | NUEVO → LISTO_PARA_COMMIT | conversación principal (sesión nocturna) | 23 criterios de SPEC-043 cumplidos. Suite completa: **2851 passed** (sin `test_webview_smoke.py`) + **9 passed** del smoke; el único rojo fue `test_ca06_desktop_only_actions_son_exactamente_las_declaradas`, que fija el conjunto exacto de `DESKTOP_ONLY_ACTIONS` y se actualizó con las 6 `mcp_*` (es su función avisar). 76 tests nuevos. Prueba manual pendiente de Johan (ver sección).
