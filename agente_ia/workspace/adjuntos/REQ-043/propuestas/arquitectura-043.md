# Arquitectura REQ-043 — MCP desde la app

## Piezas

```
┌ chat ──────────────┐        ┌ Configuración → Conexiones ─────────────────┐
│ mcp_add_server     │        │ Bridge slots:                               │
│ mcp_allow_tools    │        │  request_mcp_servers / set_mcp_server_enabled│
│ mcp_set_server_… │  🟡 gate  │  remove_mcp_server / probe_mcp_server        │
│ mcp_remove_server  │───────▶│  save_mcp_allowed_tools / login_mcp_server   │
│ mcp_list_servers 🟢│        │  save_mcp_variable / clear_mcp_variable      │
│ mcp_probe_server 🟢│        └──────────────┬──────────────────────────────┘
└─────────┬──────────┘                       │
          ▼                                  ▼
      core/mcp_config.py  ← único escritor de config.json→mcp_servers/mcp_variables
          │                  y de mcp_allowlist.json
          ├─ recarga en caliente → core/mcp_manager.recargar_servidor()
          └─ estado → core/mcp_manager.estado() + remote_tools_policy.load_allowlist()
```

`core/mcp_manager.py`, `core/mcp_client.py`, `core/remote_tools_policy.py` y
`core/mcp_oauth.py` **no cambian de responsabilidad**. Un solo cambio en `mcp_client`:
`expandir_secreto()` resuelve `${VAR}` del entorno y, si no está, de
`config.json → mcp_variables` (vía `mcp_config.valor_de_variable()`).

## `core/mcp_config.py`

```python
class MCPConfigRechazada(ValueError): ...

CANALES_HABILITABLES = ("desktop", "telegram", "discord", "voice")
_PATRON_NOMBRE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_PATRON_REF = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")

def normalizar_nombre(nombre) -> str                      # CA-01
def agregar_servidor(nombre, *, command=None, args=None, url=None,
                     env=None, headers=None) -> dict       # CA-01, CA-02
def quitar_servidor(nombre) -> bool                        # CA-04
def habilitar_servidor(nombre, activo: bool) -> None       # CA-04
def permitir_herramientas(nombre, patrones, canales=None) -> dict   # CA-03
def listar_servidores() -> list[dict]                      # CA-05
def variables_referenciadas() -> dict[str, list[str]]      # {VAR: [servidores]}
def origen_de_variable(nombre) -> str                      # "entorno" | "archivo" | ""
def valor_de_variable(nombre) -> Optional[str]             # lo usa mcp_client
def definir_variable(nombre, valor) -> bool                # CA-06
def borrar_variable(nombre) -> bool
def aplicar_y_resumir(nombre) -> str                       # CA-07: recarga + palabras
```

- Escribe `config.json` con `config_manager.load_config()/save_config()` (mismo archivo
  que `mcp_manager.CONFIG_FILE`, otra constante al mismo path; los tests redirigen las dos).
- Escribe `mcp_allowlist.json` de forma atómica (`os.replace` sobre un `.tmp`), mismo patrón
  que `core/security_config.py`. Conserva las entradas de otros servidores tal cual.
- `listar_servidores()` es solo lectura: no conecta nada. "Conectado" = está en
  `mcp_manager.estado()`; "herramientas registradas" = `_tools_de(nombre)` sin el prefijo.
- El nombre de variable admitido en `definir_variable` es una **lista cerrada derivada**:
  las que aparecen como `${VAR}` en algún servidor declarado. Igual que `_CONEXIONES`, lo
  que llega del JS no decide qué clave se escribe.

## Herramientas del agente (`agents/tool_registry.py`, al final)

| Tool | params | invoke |
|---|---|---|
| `mcp_list_servers` | — | `listar_servidores()` formateado |
| `mcp_probe_server` | `name` | `mcp_manager.probar_servidor(name)` |
| `mcp_add_server` | `name`, `command?`, `args?[]`, `url?`, `env?{}`, `headers?{}` | `agregar_servidor` → `aplicar_y_resumir` |
| `mcp_allow_tools` | `name`, `herramientas[]`, `canales?[]` | `permitir_herramientas` → `aplicar_y_resumir` |
| `mcp_set_server_enabled` | `name`, `enabled` | `habilitar_servidor` → `aplicar_y_resumir` |
| `mcp_remove_server` | `name` | `mcp_manager.desregistrar_servidor` + `quitar_servidor` |

Para que el modal muestre lo que importa, el invoke NO es quien arma el detalle: el gate
lee `params` con `_DETAILS_ALLOWED_KEYS`. Por eso `mcp_add_server` recibe `command` como
**cadena completa** ("npx -y @notionhq/notion-mcp-server") — el modelo la manda así y el
módulo la parte con `shlex.split` — y se agregan las claves `herramientas` y `canales` a
`_DETAILS_ALLOWED_KEYS` y a `_ETIQUETAS` de `acciones_legibles`. Con `args` aparte, el
modal habría dicho solo "npx".

`security_manager`: las 6 en `DESKTOP_ONLY_ACTIONS`; `register_action` de las 6 con su
nivel. `acciones_legibles._DESCRIPCIONES`: las 4 amarillas. `describir()`: rama para
`mcp__servidor__tool` (CA-15).

## Bridge (`ui/webview/bridge.py`)

Señales nuevas: `mcp_servers_loaded(str)` (json `{servidores, variables, ayuda}`),
`mcp_probe_result(str, str)` (nombre, texto).

Slots: `request_mcp_servers()`, `set_mcp_server_enabled(str, bool)`,
`remove_mcp_server(str)` [gate 🟡 vía `run_async`, mismo patrón que `terminal_new`],
`probe_mcp_server(str)` [hilo], `save_mcp_allowed_tools(str, str, str)` [gate 🟡 vía
`run_async`], `login_mcp_server(str)` [hilo], `save_mcp_variable(str, str)`,
`clear_mcp_variable(str)`.

Los gates usan **los mismos `action_name`** que las herramientas del agente
(`mcp_remove_server`, `mcp_allow_tools`): una sola clasificación, un solo texto de
confirmación, una sola entrada en la auditoría, venga del chat o del botón.

## Frontend (`settings_panel.js`, `settings_panel.css`, `bridge_client.js`, `app.js`)

`buildMcpCard(payload)` debajo de `buildConnectionsCard` en la sección "conexiones".
Sin `innerHTML` (§10.1 REQ-015). Estado por fila con la misma clase `conexion-estado-*`.
El resultado de "Probar" se pinta en un `<pre>` dentro de la fila (texto plano del
sondeo). Variables: reutiliza `buildConnectionRow`-like con `type="password"`.

## Riesgos y mitigación

- **`mcp_add_server` ejecuta un programa** (el servidor stdio) al conectar. Es el mismo
  caso que `terminal_open`: 🟡 con el comando exacto a la vista, solo escritorio. No es
  rojo por el mismo motivo que `_nivel_declarado()` no sube a rojo las destructivas: rojo
  sin `ORION_AUTH_PIN` es un autobloqueo.
- **Un secreto pasado por el chat**: rechazado por construcción (CA-02). El mensaje de
  rechazo dice dónde ponerlo.
- **Un servidor que cuelga al conectar** bloquearía el turno: `connect_timeout` 10 s ya
  existe en el cliente; `aplicar_y_resumir` no reintenta.
- **Concurrencia**: recargar mientras el modelo está a mitad de turno cambia el catálogo
  debajo suyo. Es el comportamiento que `recargar_servidor()` ya documenta; la recarga
  ocurre dentro del mismo turno que la pidió.

## Pruebas

- `tests/test_mcp_config.py`: CA-01..CA-07 con `config.json` y `mcp_allowlist.json` en
  `tmp_path`; `mcp_manager.recargar_servidor` mockeado.
- `tests/test_mcp_tools.py`: CA-08..CA-16 (niveles, `DESKTOP_ONLY_ACTIONS`, catálogo por
  canal, detalle de confirmación con `format_details`, frases legibles, flujo add → allow).
- `tests/test_webview_mcp.py`: CA-18..CA-21 (payload sin valores, validación de nombres,
  gate en quitar y en permitir).
