# Arquitectura REQ-029

## Principio
Todo el REQ se juega en un solo punto: **una función que convierte una ruta pedida por el
modelo en una ruta real dentro de una raíz habilitada, o falla**. Si esa función es
correcta, las 8 herramientas son envoltorios finos. Si tiene un agujero, el resto no importa.
Por eso vive sola, es pura, y se testea aparte.

## Módulos nuevos

### `core/workspace_config.py`
Persistencia de las raíces habilitadas, calcada de `core/security_config.py` (REQ-019):
archivo propio `code_workspaces.json`, escritura atómica, y **fail-closed**: archivo
ausente, corrupto, JSON que no es lista, entrada que no es string o que no existe en disco
→ se descarta esa entrada con `logger.warning`. El peor caso posible es la lista vacía, que
significa "el agente no puede tocar nada" (CA-02).

```python
def cargar_raices() -> List[str]   # realpath de cada raíz válida, deduplicadas
def guardar_raices(raices: List[str]) -> None
```

### `core/workspace_files.py`
El confinamiento y las operaciones.

```python
class RutaFueraDeRaiz(Exception): ...

_INSTALACION = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))

def resolver(ruta: str, raices: List[str]) -> str
    """Devuelve la ruta REAL si cae dentro de alguna raíz. Levanta RutaFueraDeRaiz si no."""
```

`resolver()` es el corazón (CA-01, CA-03, CA-04):
1. `os.path.realpath()` de la ruta pedida — resuelve `..` y symlinks **antes** de comparar,
   que es lo que hace que un symlink no pueda escaparse.
2. Comparación **por segmentos** con `os.path.commonpath([raiz, candidata]) == raiz`, nunca
   `startswith`: si no, `/home/proyecto-malo` pasaría por estar "dentro" de `/home/proyecto`.
3. Si la ruta cae dentro de `_INSTALACION`, se rechaza **aunque la raíz esté habilitada**, y
   se loguea con `logger.critical`. Es `modify_source_code` (🔴, `security_manager.py:619`)
   aplicado donde se puede aplicar. Mismo criterio con que `_merge_with_override()` bloquea
   bajar un RED aunque se edite el JSON a mano.
4. En Windows la comparación es case-insensitive; `commonpath` no lo es por sí solo.

Operaciones, todas pasando primero por `resolver()`:
`listar()`, `leer()` (tope `_MAX_LECTURA` y rango de líneas, CA-10), `buscar()`,
`escribir()` (crea intermedios dentro de la raíz, CA-12), `editar()` (coincidencia única,
CA-11).

### `core/workspace_git.py`
`estado()`, `diff()`, `log()` con `subprocess.run([...], cwd=raiz, shell=False)` y lista
blanca `{"status", "diff", "log"}` (CA-13). Sin `shell=True` y sin pasar argumentos que
vengan crudos del modelo a la línea de comando: los parámetros aceptados son una ruta (que
pasa por `resolver()`) y un entero de cantidad.

## Cambios en módulos existentes

| Archivo | Cambio |
|---|---|
| `core/security_manager.py` | `DESKTOP_ONLY_ACTIONS: set[str]` + su evaluación al principio de `is_action_allowed()`. **Solo resta, nunca suma** (CA-07): si el nombre está en el set y el canal no es DESKTOP, deniega; en cualquier otro caso, sigue el camino de siempre. |
| `agents/tool_registry.py` | Las 8 `ToolSpec` + su `register_action()` con el nivel de CA-05. |
| `core/security_manager.py` (`format_details`) | `path` y `ruta` en `_DETAILS_ALLOWED_KEYS`, para que la confirmación amarilla muestre dónde se va a escribir (CA-08). |
| `core/composer_modes.py` | Los nombres nuevos al frente de `tool_names` del modo `codigo`. `presupuesto=40` no se toca. |

## Flujo
```
modelo pide file_edit(path=..., buscar=..., reemplazar=...)
  → reasoning_loop ejecuta la tool call
    → execute_tool()                      gate REQ-005: DESKTOP_ONLY + nivel + confirmación
      → workspace_files.editar()
        → resolver(path, cargar_raices()) confinamiento; falla ruidosamente si se escapa
          → lectura, verificación de coincidencia única, escritura
```

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| Escape del confinamiento (`..`, symlink, ruta absoluta, prefijo engañoso) | `realpath` + `commonpath` por segmentos + tests con symlink real (CA-01, CA-04) |
| Exfiltración por canal remoto: una tool verde de lectura la alcanza Telegram | `DESKTOP_ONLY_ACTIONS` (CA-06), con test que recorre los 7 canales |
| El agente reescribiendo su propio código | `_INSTALACION` excluida en código, no en configuración (CA-03). `modify_source_code` sigue 🔴 |
| Un archivo enorme revienta el turno | Tope + truncado avisado + lectura por rango (CA-10) |
| `file_edit` pisando la ocurrencia equivocada | Coincidencia única obligatoria (CA-11) |
| Inyección de comandos por los parámetros de git | Sin shell, lista blanca de subcomandos (CA-13) |
| La feature nace inerte (lista de raíces vacía) | Es deliberado y es lo correcto: se documenta en el log de desarrollo cómo habilitar la primera raíz |

## Pruebas sugeridas
- `tests/test_workspace_files.py` — `resolver()` contra todos los escapes, con `tmp_path` y
  un symlink real; truncado; coincidencia única de `editar()`.
- `tests/test_workspace_config.py` — fail-closed ante archivo ausente/corrupto/inválido.
- `tests/test_workspace_tools_seguridad.py` — niveles registrados, los 7 canales, y que la
  carpeta de instalación se rechaza aunque esté habilitada como raíz.
