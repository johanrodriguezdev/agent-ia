# Contexto REQ-037 — El nombre del agente es el que eligió el usuario

## Resumen ejecutivo
Johan reportó que el panel de Flujos vacío decía *"Pedíselo a O.R.I.O.N. hablando"*, con el
nombre escrito a mano. Quien renombró a su agente —él lo llama VIERNES— leía un nombre que
nunca puso. Buscándolo aparecieron **siete lugares** con el nombre fijo, y debajo un
problema de fondo peor.

## Estado actual
- **Estado tracker:** EN_PRUEBAS | **Categoría:** UI | **Tipo:** BUG_FIX
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo` | **Fecha:** 2026-09-10

## El problema de fondo
`window.__ORION_AGENT_NAME__` la inyecta `MainWindow` **al cargar la página**, y
`setAgentIdentity()` repintaba tres nodos del DOM a mano sin actualizar esa variable. O sea
que:

- cualquier panel que quisiera nombrar al agente tenía que escribirlo a mano (de ahí los
  siete lugares), y
- al renombrarlo, **la global seguía con el nombre del arranque hasta reiniciar**.

Arreglar solo el texto de Flujos habría dejado la causa intacta.

## Lo que se hizo
| Dónde | Qué |
|---|---|
| `js/agente.js` (nuevo) | Un único lugar que sabe el nombre: `nombreDelAgente()` y `fijarNombreDelAgente()` |
| `js/app.js` | `setAgentIdentity()` publica el nombre cada vez que entra uno nuevo — al arrancar y al renombrar |
| `js/flows_panel.js` | El texto que reportó Johan |
| `js/settings_panel.js` | El `placeholder` del campo de nombre dejó de sugerir "O.R.I.O.N": proponer un nombre en el campo donde el usuario elige el suyo es empujarlo a uno que no es suyo. Y el texto del modo autonomía dice "su propio código" |
| `core/autonomy.py` | El error de "no es un repositorio git" habla en primera persona |
| `core/workspace_files.py` | El mensaje de confinamiento, que **lo lee el modelo y termina en la conversación** |
| `core/mcp_oauth.py` | La página que se ve en el navegador al autorizar un servidor MCP |

## Decisiones tomadas
2026-09-10 | conversación principal | Un módulo propio para el nombre, no una variable suelta | Es lo que evita que el próximo texto lo escriba a mano otra vez. La variable global se mantiene sincronizada porque hay código que la lee directo
2026-09-10 | conversación principal | El guard revisa TODO el frontend, no el mensaje de Flujos | Un test del mensaje puntual no habría encontrado los otros seis, ni encontraría el séptimo que escriba alguien mañana
2026-09-10 | conversación principal | Los logs SÍ pueden nombrar al producto | Un log es para quien mantiene el código; el mensaje que lee una persona o el modelo, no. El primer intento de test no hacía esa distinción y marcaba dos `logger.critical()` como si fueran bugs
2026-09-10 | conversación principal | `mcp_oauth.registrar_cliente()` sigue diciendo "O.R.I.O.N" | Es el nombre con que la app se identifica ante un proveedor OAuth: ahí corresponde el nombre del producto, no cómo el usuario llamó a su asistente

## Verificación
El test del panel de Flujos **renombra al agente en caliente** (emitiendo `profile_loaded`,
que es lo que llega al guardar el perfil) y comprueba que el mensaje diga "VIERNES". Así se
prueba la mitad de fondo —la propagación sin reiniciar— y no solo el texto.

## Log de transiciones
2026-09-10 | — → EN_PRUEBAS | conversación principal | 7 lugares corregidos, módulo nuevo, guard de toda la interfaz y 7 tests
