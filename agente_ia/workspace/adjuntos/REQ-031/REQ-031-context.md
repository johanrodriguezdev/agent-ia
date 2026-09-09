# Contexto REQ-031 — Salida HTTP segura: cerrar el SSRF y poder llamar APIs

## Resumen ejecutivo
Dos caras de la misma superficie. **La que hay que cerrar:** hoy `web_read` (🟢 verde,
alcanzable desde Telegram) abre cualquier dirección, incluidas `localhost` y la red local —
probado, no teórico. **La que falta:** no existe forma de llamar a una API (POST con
cabeceras y cuerpo), que es el hueco real del punto 5 de las 7 capacidades.

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** conversación principal
- **Fecha última actualización:** 2026-09-09
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** SEGURIDAD
- **Tipo de cambio:** SEGURIDAD + FEATURE_NUEVA

## Origen
Johan pidió terminar los puntos pendientes y que el agente sea cada vez más capaz de
ejecutar tareas. Al relevar el punto 5 ("herramientas y APIs") aparecieron dos cosas:

1. **MCP no está sin construir: está sin configurar.** 1.603 líneas en `core/mcp_client.py`,
   `core/mcp_manager.py` y `core/mcp_oauth.py`, ya enganchadas en `main.py` (conecta al
   arrancar, cierra al salir), con allowlist por herramienta y niveles de riesgo por tool.
   Falta declarar servidores en `config.json` y permitir sus tools en `mcp_allowlist.json`
   — decisión de Johan, no trabajo de código.
2. **El hueco de código es la salida HTTP**, y al mirarla apareció el agujero de abajo.

## El hallazgo — SSRF vivo en `web_read`

`os_integration/web_search.py::leer_pagina()` valida **solo el esquema** (`http://` o
`https://`). No mira a dónde apunta. Reproducido con un servidor local de mentira
(`origen/reproduccion-ssrf.py`):

```
servicio interno simulado en http://127.0.0.1:52073
  !!! ALCANZADO | localhost: 'Contenido de http://127.0.0.1:52073/: PANEL INTERNO SECRETO_DE_LA_RED...'
  !!! ALCANZADO | nombre localhost: 'Contenido de http://localhost:52073/: ...'

  metadatos de nube -> 'No pude abrir esa página: ConnectionError.'
```

Lo del endpoint de metadatos (`169.254.169.254`) importa por el matiz: **intentó
conectarse** y falló por red inaccesible en este equipo. No lo rechazó por política.

Por qué es serio acá y no una nota teórica:

- **`web_read` es 🟢 verde**, así que `CHANNEL_ALLOWED_LEVELS` lo habilita en Telegram,
  Discord, voz y API. Un mensaje de Telegram puede pedirle que lea `http://192.168.1.1/` (el
  router), un panel de desarrollo en `localhost:3000`, o cualquier servicio de la LAN — y el
  contenido vuelve al chat.
- **No hace falta que el atacante sea el usuario.** El agente lee páginas durante una
  investigación (`web_search` → `web_read`): un texto inyectado en una de esas páginas puede
  pedirle que lea una dirección interna.
- `requests` **sigue redirecciones por defecto**: una URL pública puede redirigir a una
  interna, así que validar solo la dirección original no alcanza.

`skills/web_browsing_skill.py` tiene el mismo problema y además usa `urlopen()` **sin
validar el esquema**. Ahí `file://` no es alcanzable hoy porque `extract_params()` solo
extrae `https?://` del texto (`agents/skill_tools.py:182` arma los params desde el texto, no
desde el modelo), pero el `execute()` no se defiende solo: es defensa en profundidad.

## Diseño

### `core/http_seguro.py` (nuevo)
Un solo lugar que decide si una dirección se puede pedir:

- esquema `http`/`https` únicamente,
- **se resuelve el nombre y se mira la IP**, no el texto: se rechazan loopback, privadas
  (10/8, 172.16/12, 192.168/16), link-local (169.254/16, incluido el endpoint de metadatos),
  reservadas y multicast, en IPv4 e IPv6,
- las redirecciones se siguen **a mano**, revalidando cada salto (máximo 5),
- tope de tamaño de respuesta y timeout.

### Aplicado en
- `os_integration/web_search.py::leer_pagina()` — cierra el agujero de `web_read`.
- `skills/web_browsing_skill.py` — mismo camino, y de paso se le exige el esquema.

### `http_request` (herramienta nueva, 🟡)
Para llamar APIs: método, cabeceras y cuerpo. Amarilla porque tiene efectos y manda datos
afuera; la confirmación muestra método y URL (`url` ya está en `_DETAILS_ALLOWED_KEYS`).
Las cabeceras admiten `${MI_TOKEN}` y se resuelven con `core/mcp_client.py::expandir_secreto()`,
que ya existe y ya usan los módulos de correo: **el token nunca pasa por el texto del modelo**.

## Decisiones tomadas
2026-09-09 | conversación principal | El guard mira la IP resuelta, no el texto de la URL | `http://127.0.0.1`, `http://localhost`, `http://0x7f.1` y un dominio que resuelve a una IP interna son el mismo ataque
2026-09-09 | conversación principal | Las redirecciones se siguen a mano, revalidando cada salto | `requests` las sigue solo; validar la primera URL y confiar en el resto es el error clásico
2026-09-09 | conversación principal | Se arregla `leer_pagina()`, no se sube `web_read` a amarillo | Leer una página pública es verde con razón; lo que estaba mal era no mirar a dónde apunta. Subirlo a amarillo rompería la investigación con una confirmación por página
2026-09-09 | conversación principal | `http_request` es 🟡, no verde | Manda datos afuera y tiene efectos. Amarillo además lo deja fuera de todos los canales remotos
2026-09-09 | conversación principal | Los tokens se pasan como `${VAR}`, no literales | Reusa `expandir_secreto()`. Un token literal en los params quedaría en el historial del modelo y en el log de auditoría

## Riesgos activos
- Un servicio público que resuelve a una IP interna **entre la validación y la conexión**
  (DNS rebinding) no lo cierra este diseño: haría falta fijar la IP validada en la conexión.
  Se documenta como límite conocido.
- El guard puede molestar a alguien que de verdad quiera leer algo de su red local. Es el
  precio correcto: hoy eso mismo lo puede pedir un mensaje de Telegram.

## Log de transiciones
2026-09-09 | — → NUEVO | conversación principal | REQ creado con el SSRF ya reproducido y guardado en `origen/`

---

## Implementado (2026-09-09)

- `core/http_seguro.py` — nuevo. `validar_url()` y `pedir()`, con la escalera completa:
  esquema, IP resuelta, revalidación por salto de redirección, tope de descarga y timeout.
- `os_integration/web_search.py::leer_pagina()` — usa el guard. Cierra el agujero de `web_read`.
- `skills/web_browsing_skill.py` — usa el guard, y de paso:
  - se le agregó el `logger` que el módulo **no tenía** (lo detecté porque mi propio parche
    metió un `logger.info` en un archivo que nunca lo había definido: habría reventado con
    `NameError` la primera vez que alguien pidiera una dirección interna);
  - su `except Exception` devolvía `str(e)` al canal **sin loguear** — el mismo patrón que
    arreglaron REQ-024 (gateway) y REQ-025 (Discord), y este camino es alcanzable desde
    Telegram. Ahora el detalle va al log y al canal va una frase.
  - quedaron sin uso `import urllib.request` / `urllib.error` y se sacaron.
- `agents/tool_registry.py` — `http_request` (🟡).
- `core/acciones_legibles.py` — su frase en castellano.
- `tests/test_http_seguro.py` — 28 tests, ninguno toca la red.

### Verificación del arreglo, con el mismo script que reprodujo el bug
```
  OK  bloqueado | localhost: '«127.0.0.1» apunta a la propia máquina o a la red local...'
  OK  bloqueado | nombre localhost: '«localhost» apunta a la propia máquina...'
  metadatos de nube -> '«169.254.169.254» apunta a la propia máquina o a la red local...'
```
El de metadatos ahora se rechaza **por política**: el log del bloqueo aparece antes de
cualquier intento de conexión.

## Log de transiciones
2026-09-09 | NUEVO → EN_PRUEBAS | conversación principal | Guard, cableado en los dos caminos, herramienta nueva y 28 tests
