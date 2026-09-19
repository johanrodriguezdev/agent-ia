# Contexto REQ-052 — Pulido de diseño: la marca en la app, controles limpios y el Mapa de conexiones

## Resumen ejecutivo
Tres frentes pedidos por Johan en una sola frase («que esté limpio y bonito», «el logo… que
se viera mejor», «los inputs de la configuración se ven muy genéricos», «visualizar en la
misma app la interfaz de los nodos o conexión… algo futurista»):

1. **La marca dentro de la interfaz.** Los tres anillos entrelazados del icono de la app
   (REQ-041) ahora también se ven adentro: chicos al lado del nombre en la barra superior y
   grandes, con los anillos girando despacio y un halo tenue, en la pantalla vacía —
   reemplazan a la inicial del agente en un cuadrado. Misma geometría exacta que el icono
   (fijado por test), con el degradado según el tema (metálico claro sobre oscuro, y al
   revés).
2. **Controles de formulario unificados** (`css/controles.css`): campos de texto,
   selectores con chevron propio, interruptores tipo switch, chips para elegir canales,
   botones principal/secundario. Una sola receta con los tokens del tema para
   Configuración, Tareas y la barra lateral. Antes varios controles no tenían ningún estilo
   y el motor los pintaba blancos con borde de sistema.
3. **Panel «Mapa»** (botón nuevo en la barra superior): un SVG con el agente en el centro y,
   alrededor, los modelos con los que responde, los canales por los que se le habla, los
   servidores MCP y los flujos, cada uno con su estado (activo / configurado / inactivo /
   con problema). Los enlaces de lo activo llevan un pulso; click en un nodo abre el detalle
   (comando del servidor, herramientas, canales…) con atajo a la sección de Configuración.
   Se refresca solo cada 5 s mientras está abierto.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** UI · **Tipo:** MEJORA

## Origen
Pedido de Johan (2026-09-19, tarde): «mejorar más el diseño tiene que estar limpio y bonito…
el logo está bacano pero me gustaría que se viera mejor… los diseños de los inputs de la
configuración se ven como muy genéricos… que podamos visualizar en la misma app la
interfaz de los nodos o conexión que realice algo como futurista, te apruebo las
modificaciones». Autorización en bloque; se validó con capturas offscreen.

## Decisiones tomadas
2026-09-19 | conversación principal | La marca se dibuja en JS (`js/marca.js`) con una COPIA de la geometría de `app_icon.py`, y `tests/test_marca_webview.py` compara ambas | Un solo origen habría exigido inyectar SVG desde Python; el test de drift es el mismo patrón que theme.py ↔ theme.css.
2026-09-19 | conversación principal | El degradado va en `<defs>` dentro de cada `<svg>`, con `stop-color` puesto por CSS desde `--marca-1/2/3` (tokens nuevos en theme.py y theme.css) | Un gradiente en el sprite oculto no se resuelve fiable vía `<use>`; con tokens el cambio de tema repinta sin tocar el DOM.
2026-09-19 | conversación principal | El icono de la app (ICO/bandeja) NO cambia | Fue aprobado en un canvas de diseño en REQ-041; lo que se pidió es que se vea mejor, y eso se logra con cómo se presenta en la ventana.
2026-09-19 | conversación principal | `controles.css` se carga después de `layout.css` y antes de las hojas de cada pantalla; las reglas viejas por pantalla se recortan a tamaño/posición | Así cada pantalla puede ajustar sin repetir la receta, y no queda un control sin estilo.
2026-09-19 | conversación principal | Los interruptores son `<input type=checkbox>` reales dibujados con `appearance: none`; los chips de canal son `<label>` con `:has(input:checked)` | Teclado, lector de pantalla y el JS existente (`.checked`) siguen funcionando sin tocar settings_panel.js.
2026-09-19 | conversación principal | El chevron de los `<select>` es un SVG en `url()` con un hex por tema (= `--text-secondary`) | `url()` no admite `var()`.
2026-09-19 | conversación principal | El Mapa es SOLO LECTURA: mira, no configura. Desde el detalle, «Abrir en Configuración» | Configurar ya tiene su pantalla y su chat; un segundo lugar para editar sería un segundo lugar para equivocarse.
2026-09-19 | conversación principal | `ui/webview/mapa_conexiones.py` nunca incluye una credencial: solo `origen_de_credencial` (puesta/entorno/archivo) y lo que `mcp_config.listar_servidores` ya da sin valores. Fijado por test con claves de prueba | Mismo criterio que `_build_connections_payload` (REQ-050).
2026-09-19 | conversación principal | `request_connection_map` corre por `run_async`; `wake_state` y las pestañas de la terminal se toman en el hilo de la GUI antes de salir | `telegram_launcher._ya_hay_uno_corriendo()` recorre procesos con psutil.
2026-09-19 | conversación principal | Cada grupo del mapa tiene su lado fijo (Modelos izquierda, Canales arriba, MCP derecha, Flujos abajo); los nodos se abren en abanico ≤ 76°, paso ≤ 26°; arriba/abajo las etiquetas alternan dos distancias; máximo 6 por grupo + «+N más» | Con reparto proporcional los grupos "giraban" según cuántos nodos tuviera cada uno y los títulos pisaban etiquetas (se vio en la primera captura).
2026-09-19 | conversación principal | Un nodo del mapa es `<g role=button tabindex=0>`; los tests le despachan `MouseEvent` porque `SVGElement` no tiene `.click()` | Accesible por teclado (Enter/Espacio) como el resto de la interfaz.
2026-09-19 | conversación principal | El detalle va al lado del lienzo (flex), no flotando encima; el lienzo tiene alto fijo y el SVG se escala adentro | Flotando tapaba justo el grupo del nodo elegido; sin alto fijo la caja del modal saltaba al abrir el detalle.

## Archivos
- Herramienta `connection_map` en `agents/tool_registry.py` (+ `DESKTOP_ONLY_ACTIONS`,
  `NIVELES_REQ052` en `tests/test_workspace_tools_seguridad.py`).
- Nuevos: `ui/webview/frontend/js/marca.js`, `js/map_panel.js`, `css/marca.css`,
  `css/controles.css`, `css/map_panel.css`, `ui/webview/mapa_conexiones.py`,
  `tests/test_marca_webview.py`, `tests/test_mapa_conexiones.py`.
- Tocados: `index.html` (hojas nuevas, `#brand-mark`, `#map-btn`, símbolos `ic-map`,
  `ic-monitor`, `ic-mail`, `ic-message`, `ic-plug`), `js/app.js`, `js/bridge_client.js`,
  `ui/webview/bridge.py` (`connection_map_loaded`, `request_connection_map`),
  `ui/webview/theme.py` + `css/theme.css` (`--marca-1/2/3`), `css/chat.css`,
  `css/settings_panel.css`, `css/panels.css`, `css/sidebar.css`,
  `tests/test_webview_buttons.py`, `tests/test_webview_safe_dom_insertion.py`.

## Qué puede hacer ahora
- Chat: *«¿qué tenés conectado?»*, *«¿qué canales están activos?»*, *«¿por qué no responde
  Telegram?»* → herramienta `connection_map` (verde, solo escritorio, como
  `mcp_list_servers`): el mismo mapa en texto (`mapa_conexiones.resumen_para_modelo`).
- Barra superior: icono de nodos → «Mapa». Se ve de un vistazo con qué modelo responde,
  qué canales están vivos (escritorio, voz, Telegram, Discord, correo), qué servidores MCP
  conectaron y cuántas herramientas tienen, y qué flujos hay. Click en un nodo → detalle;
  «Abrir en Configuración» salta a la sección que corresponde.
- Configuración: los campos, interruptores y chips se ven parte de la misma app en claro y
  oscuro; el nivel de autonomía activo se lee como estado («Activo» en verde), no como
  botón roto.

## Verificación
- `tests/test_mapa_conexiones.py`: 20 passed (nuevo). `tests/test_marca_webview.py`: 6
  passed (nuevo). `tests/test_webview_buttons.py` + `test_webview_smoke.py`: 52 passed
  (3 tests nuevos + `map-btn` en el inventario y en la parametrización de paneles).
- Suite completa: ver `pruebas/suite-052.txt`.
- Capturas offscreen (oscuro y claro): pantalla vacía con la marca, Configuración → MCP /
  Perfil / Seguridad / Modelos, Tareas, Mapa con y sin detalle.

## Prueba manual sugerida (Johan)
1. Abrir la app: la marca al lado de «ORION» y grande en la pantalla vacía (los anillos
   giran despacio). Cambiar de tema: el degradado se invierte.
2. Configuración → MCP: los campos oscuros, el switch de cada servidor, los chips de canal
   marcables, «Guardar» a la derecha de los chips.
3. Barra superior → Mapa: el centro con la marca y el modelo; Escritorio en verde; un
   servidor MCP conectado en verde con pulso en su enlace; click en él → detalle con el
   comando; «Abrir en Configuración» → sección MCP.
4. Con el mapa abierto, encender el manos libres: «Voz» pasa a verde en ≤ 5 s.

## Riesgos activos
- Las animaciones del mapa (pulso, halos, anillos) corren solo con el panel abierto; con
  `prefers-reduced-motion` se apagan. Si en alguna máquina el webview va lento con el mapa
  abierto, bajar `REFRESCO_MS` no ayuda: son las animaciones CSS, no el refresco.
- `_ya_hay_uno_corriendo()` (psutil) se llama en cada refresco del mapa (cada 5 s mientras
  está abierto), fuera del hilo de la GUI. Es lo mismo que hace la app al arrancar.

## Log de transiciones
2026-09-19 | — → NUEVO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión, con capturas.
