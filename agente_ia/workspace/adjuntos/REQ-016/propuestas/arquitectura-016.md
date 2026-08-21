# Arquitectura REQ-016 — Sidebar tipo DeepSeek + Tareas programadas + Proyectos + tipografía Inter

**Estado:** ✅ APROBADA — Aprobado por Johan (2026-08-20), tal cual, sin ajustes, incluidas todas las
decisiones de §0 (esquema de 2 tablas nuevas, asignación desde el panel de Proyectos, Tareas/Proyectos
como modales, descarga puntual del `.zip` oficial de Inter) y la recomendación de §11 (no se invoca
`orion-security` como paso dedicado — la revisión de sus 2 puntos de seguridad queda a cargo del DoD
estándar de `orion-qa`).
**Agente:** orion-architect
**Fecha:** 2026-08-20
**Fuentes leídas:** `REQ-016-context.md` (íntegro), `spec/SPEC-016.md` (34 CA), `origen/baseline-016.md` (íntegro) — más verificación directa contra el código real de `ai/memory_manager.py`, `ui/webview/bridge.py`, `core/security_manager.py`, `tasks/task_manager.py`, `tasks/task_scheduler.py`, `main.py`, `ui/webview/frontend/index.html`, `css/sidebar.css`, `css/theme.css`, `css/reset.css`, `css/composer.css`, `css/modal.css`, `js/sidebar.js`, `js/app.js`, `js/bridge_client.js`, `js/confirm_modal.js`, `ui/webview/confirmation_adapter.py`, `tests/test_webview_bridge.py`, `tests/test_memory_manager_delete_conversation.py`, `tests/test_webview_safe_dom_insertion.py`, y `workspace/adjuntos/REQ-015/propuestas/arquitectura-015.md` (§0.2, §4, §10.1, §10.2 — patrones a replicar, no a reabrir).

---

## 0. Decisiones técnicas centrales (sin preferencia previa del humano — a validar en el gate)

### 0.1 Esquema de "proyectos": 2 tablas nuevas, CERO cambios a `memories`

`projects` + `project_conversations`, ambas nuevas, en la MISMA base (`ai/unified_memory.db`, mismo
archivo que ya usa `UnifiedMemory`) — no una columna nueva en `memories`, no una DB nueva. Motivo:
las 5 funciones protegidas por CA-21 (`new_conversation_id`, `store_turn`, `list_conversations`,
`get_conversation_turns`, `delete_conversation`) leen/escriben exclusivamente sobre `memories`; si el
esquema de proyectos no toca esa tabla en absoluto, la no-regresión de CA-21 queda garantizada
estructuralmente (0 líneas modificadas en esas 5 funciones), no solo "con cuidado". Ver §4 para el
detalle completo, incluida la limpieza de huérfanos al borrar una conversación.

### 0.2 Asignar conversación a proyecto: desde el panel de Proyectos, no un ícono nuevo por fila

CA-16 exige poder asignar "una conversación ya existente (del listado del sidebar)" a un proyecto.
En vez de agregar un botón nuevo a cada `.conv-item` (tocaría `sidebar.js::buildConversationItem()`,
ya validado por REQ-015/CA-06..CA-11 y protegido por CA-25 de esta SPEC), el picker de conversaciones
para asignar vive **dentro del panel de Proyectos**, alimentado por el mismo array de conversaciones
que `sidebar.js` ya mantiene en memoria tras el último `conversation_list_updated` — sin pedirle nada
nuevo al bridge para poblar el picker. Resultado: `sidebar.js` solo gana una función exportada nueva
(getter de su estado interno), ninguna de sus funciones existentes cambia una sola línea. Este es un
ASUMIDO de diseño — Johan no fue consultado puntualmente sobre el mecanismo, ver §15.

### 0.3 Vista de "Tareas"/"Proyectos": modal propio, no panel embebido en el sidebar

El ASUMIDO de SPEC-016 dice "cada uno abre su propio panel/modal". Se elige **modal**, con su propia
raíz `#panel-modal-root` (nueva, separada de `#confirm-modal-root`) — nunca la misma raíz que el
modal de confirmación YELLOW. Motivo concreto: si se compartiera la raíz, borrar una tarea desde
dentro del panel de Tareas dispara `confirmation_requested`, y el modal de confirmación haría
`root.replaceChildren()` sobre esa raíz — si esa raíz fuera la misma que aloja el panel de Tareas
abierto, el panel desaparecería del DOM al mostrarse la confirmación, y no habría a dónde volver tras
confirmar/cancelar. Con raíces separadas ambos coexisten (confirmación por encima, panel debajo,
z-index compartido rango 1000+).

### 0.4 Refresco de datos tras mutar tareas/proyectos: recarga completa + emit, no eventos "delta"

Igual que `_on_resolve_done()` ya hace hoy (guarda el turno y llama `self._load_conversations(offset=0)`
completo, no un evento incremental), cada mutación de tareas/proyectos (crear, completar, borrar,
asignar, desasignar) termina releyendo la lista completa y reemitiendo `tasks_loaded`/`projects_loaded`.
Se agregan solo 2 señales "targeted" además de eso — `project_removed` — para que una vista de detalle
abierta (conversaciones de un proyecto) pueda cerrarse/salir si el proyecto activo se borra mientras
se está viendo, algo que un simple refresco de la lista no resuelve por sí solo.

### 0.5 Tipografía Inter: descarga puntual del release oficial, no CDN en runtime

Verificado en vivo (no asumido) contra la API de GitHub: `rsms/inter` release `v4.1` (SIL OFL 1.1),
asset único `Inter-4.1.zip` en
`https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip`. Es una descarga de
**build-time/dev-time**, hecha una vez por `orion-dev` para vendorizar los `.woff2` dentro del repo —
no tiene nada que ver con la CSP de runtime (que sigue sin tocarse, CA-26). Ver §9 para el
procedimiento exacto y los nombres de archivo verificados.

---

## 1. Cobertura de criterios de la SPEC (34 CA)

| CA | Cómo lo satisface esta propuesta |
|----|-----------------------------------|
| CA-01 | Nuevo `#sidebar-toolbar.icon-pill` en `index.html`/`sidebar.css` agrupa colapsar+búsqueda+nuevo chat en un único contenedor (fondo, borde, sombra) — reemplaza el `#sidebar-header`+`#new-conversation-btn` sueltos actuales. Ver §8.1. |
| CA-02 | `.pill-btn:hover`/`.pill-btn.active` en `sidebar.css`, mismo criterio que `.composer-icon-btn:hover` ya existente. Ver §8.1. |
| CA-03 | `#sidebar-search-input` filtra client-side sobre `.conv-item` ya renderizados, por `textContent` de `.conv-title` — sin round-trip al bridge. Ver §8.2. |
| CA-04 | `new-conversation-btn` se mueve dentro de la píldora sin tocar su listener (`newConversation()` en `initSidebar()`) — comportamiento de CA-07/SPEC-015 intacto. Ver §8.1. |
| CA-05 | Botón "Tareas" (ubicación ASUMIDO) abre modal que llama `request_tasks()` → `task_manager.list_all_tasks(user_id="default")`, sin filtro de canal. Ver §5.1. |
| CA-06 | `Bridge.create_task(title, description, due_date, priority)` → `task_manager.create_task(..., channel="desktop")` sin modificar la función. Ver §5.1. |
| CA-07 | `Bridge.complete_task(task_id)` → `task_manager.complete_task()`; distinción visual pendiente/completada en CSS del panel (`.task-item.completed`). Ver §5.1, §8.3. |
| CA-08 | `Bridge.request_delete_task(task_id)` replica EXACTO el flujo de `_delete_conversation_flow()`: `security_manager.require_confirmation("delete_task", ...)` antes de `task_manager.delete_task()`. Ver §5.1, §6. |
| CA-09 | `list_all_tasks()` ya ordena pendientes-primero-luego-fecha en SQL — el payload se serializa tal cual, sin reordenar en JS. Ver §5.1. |
| CA-10 | `main.py`: `from tasks.task_scheduler import task_scheduler` + `task_scheduler.start()` junto a `proactive_engine.start()` (línea ~104). Ver §7. |
| CA-11 | Cero tablas nuevas para tareas — mismo `tasks.db`, mismo `user_id="default"`, mismas 4 funciones de `task_manager.py` sin modificar. Ver §5.1. |
| CA-12 | `request_tasks()` es un slot separado, NO se llama en `request_initial_state()` — solo se dispara al abrir el modal de Tareas (`openTasksPanel()` en JS). Ver §5.1, §8.3. |
| CA-13 | Botón "Proyectos" (ubicación ASUMIDO) abre modal que llama `request_projects()`. Ver §5.2. |
| CA-14 | `Bridge.create_project(name)` valida `name.strip()` no vacío server-side (y JS valida antes de llamar) → `memory.create_project()`. Ver §4.2, §5.2. |
| CA-15 | `memory.list_projects(user_id="default")` — nueva query agregada sobre `projects`+`project_conversations`. Ver §4.2. |
| CA-16 | Picker dentro del panel de Proyectos, alimentado por el estado ya cargado en `sidebar.js` (§0.2) → `Bridge.assign_conversation_to_project(conversation_id, project_id)`. Ver §5.2, §8.4. |
| CA-17 | `Bridge.request_project_conversations(project_id)` → `memory.list_conversations_by_project()` → vista de detalle dentro del mismo modal de Proyectos (botón "← Volver"). Ver §5.2, §8.4. |
| CA-18 | `Bridge.request_delete_project(project_id)` replica el mismo flujo YELLOW que `delete_task`/`delete_conversation`. Ver §5.2, §6. |
| CA-19 | `memory.delete_project()` solo hace `DELETE` sobre `projects`/`project_conversations` — nunca toca `memories`, así que las conversaciones sobreviven estructuralmente (no por cuidado al codear, por diseño de tablas separadas). Ver §4.2. |
| CA-20 | `project_conversations.conversation_id` es `PRIMARY KEY` — a nivel de esquema SQLite es físicamente imposible que una conversación tenga 2 filas de asignación simultáneas; `assign_conversation_to_project()` usa `INSERT OR REPLACE` para reasignar. Ver §4.1. |
| CA-21 | 0 líneas modificadas en las 5 funciones protegidas (ver §0.1). Limpieza de huérfanos: `Bridge._delete_conversation_flow()` (único call-site real de `memory.delete_conversation()` en todo el código, confirmado por grep) se extiende para llamar también `memory.unassign_conversation_from_project()` tras un borrado exitoso — `ai/memory_manager.py::delete_conversation()` en sí no se toca ni una línea. Defensa adicional: `list_conversations_by_project()` hace `INNER JOIN` contra `memories`, así que una fila huérfana en `project_conversations` (si alguna vez existiera) es estructuralmente invisible, nunca se renderiza. Ver §4.3. |
| CA-22 | `#sidebar.collapsed .sidebar-action-btn, #sidebar.collapsed .pill-btn { justify-content: center; }` nuevo en `sidebar.css` — gap confirmado por baseline, no existe hoy. Ver §8.5. |
| CA-23 | `title="..."` agregado a los 5 botones del sidebar (colapsar, búsqueda, nuevo chat, Tareas, Proyectos) en `index.html` — no existe en ninguno hoy (confirmado por baseline). Ver §8.5. |
| CA-24 | Se mantiene la única regla de `transition: width 200ms ease` ya existente en `#sidebar`; el nuevo `justify-content:center` de CA-22 no agrega ninguna transición de layout adicional que pueda recortarse a medio camino. Ver §8.5. |
| CA-25 | Cero funciones de `sidebar.js` relacionadas a conversaciones (`buildConversationItem`, `renderConversationList`, `setActiveConversationId`, `removeConversationFromList`) se modifican — solo se agrega código nuevo alrededor. Ver §8.2, §8.4. |
| CA-26 | `ui/webview/frontend/fonts/` nueva + `css/fonts.css` nuevo con `@font-face` de rutas relativas (`../fonts/Inter-*.woff2`) — sin `<link>`/`@import` externo, sin tocar `index.html`'s CSP. Ver §9. |
| CA-27 | `reset.css` línea 18: `font-family: "Inter", -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;` — fallback intacto, solo se antepone `"Inter"`. Ver §9.2. |
| CA-28 | 3 archivos vendorizados: `Inter-Regular.woff2` (400), `Inter-Medium.woff2` (500), `Inter-Bold.woff2` (700) — nombres verificados contra la distribución real de Inter (§9.1). Encabezados usan `font-weight:700` ya heredado de las reglas existentes de `h1`/`.modal-title`/etc. |
| CA-29 | `css/chat.css` línea 133 (`"Cascadia Code", Consolas, "Courier New", monospace`) no se toca — cero archivos de esta propuesta tocan `chat.css`. |
| CA-30 | Los tokens de color de `theme.css` no cambian — el cambio es solo `font-family`, no `color`/`background-color`; los pares ya auditados en CA-36/SPEC-015 no se alteran. Ver §9.3 para el detalle de por qué un cambio de fuente no reabre esa auditoría. |
| CA-31 | `python -m py_compile` sobre los 4 módulos Python tocados (`ai/memory_manager.py`, `ui/webview/bridge.py`, `core/security_manager.py`, `main.py`) — sin sintaxis nueva riesgosa (mismo estilo que el resto del archivo). Ver §14. |
| CA-32 | Ningún test existente cambia de contrato — todo lo nuevo son funciones/tablas aditivas. Los 2 fallos pre-existentes (`anthropic` no instalado) siguen ahí, no atribuibles. Ver §14. |
| CA-33 | `delete_task`/`delete_project` pasan siempre por `security_manager.require_confirmation()` antes de tocar `task_manager`/`memory` — igual que `delete_conversation` (§10.2 de arquitectura-015.md), nunca un segundo mecanismo de confirmación en JS. Ver §5, §6. |
| CA-34 | Docstring de `ui/webview/bridge.py` (líneas 1-27) actualizado enumerando las 4 funciones de `task_manager.py` y las 6 funciones nuevas de `ai/memory_manager.py` usadas por los slots nuevos. Ver §5.3. |

---

## 2. Módulos a modificar / crear

### Modificados
- `ai/memory_manager.py` — 2 tablas nuevas (`projects`, `project_conversations`) + 6 funciones nuevas
  como métodos de `UnifiedMemory`. Las 5 funciones protegidas por CA-21 no cambian ni una línea.
- `ui/webview/bridge.py` — 4 `pyqtSignal` nuevas, 10 `@pyqtSlot` nuevos (5 tareas, 5 proyectos),
  docstring del módulo actualizado (CA-34). Ningún slot/señal existente cambia de firma.
- `core/security_manager.py::_register_default_actions()` — 2 líneas nuevas
  (`delete_task`, `delete_project` como `RiskLevel.YELLOW`). Nada más se toca en el archivo.
- `main.py` — 1 import nuevo + 1 línea (`task_scheduler.start()`) junto a `proactive_engine.start()`;
  opcionalmente `task_scheduler.stop()` junto a `proactive_engine.stop()` (ver §7, no exigido
  literalmente por CA-10 pero mismo criterio de simetría ya usado en el archivo).
- `ui/webview/frontend/index.html` — nuevo `#sidebar-toolbar` (píldora), fila de búsqueda, 2 botones
  nuevos ("Tareas"/"Proyectos"), `#panel-modal-root` nuevo, `title=""` en los 5 botones del sidebar,
  `<link rel="stylesheet" href="css/fonts.css">` nuevo.
- `ui/webview/frontend/css/sidebar.css` — píldora, fila de búsqueda, estilos de los 2 botones nuevos,
  centrado de íconos en colapsado (CA-22).
- `ui/webview/frontend/css/reset.css` — 1 línea (`font-family` del `body`, CA-27).
- `ui/webview/frontend/js/sidebar.js` — 1 función nueva exportada (getter del estado interno de
  conversaciones cargadas, para el picker de §0.2/§8.4); **cero** funciones existentes modificadas.
- `ui/webview/frontend/js/app.js` — wiring de las 4 señales nuevas del bridge a los paneles nuevos
  (mismo patrón que el resto de `bootstrap()`).
- `ui/webview/frontend/js/bridge_client.js` — 10 funciones wrapper nuevas + 4 `on*` nuevos, mismo
  patrón 1:1 ya usado para cada slot/señal existente.

### Nuevos
- `ui/webview/frontend/fonts/` — `Inter-Regular.woff2`, `Inter-Medium.woff2`, `Inter-Bold.woff2`,
  `LICENSE-OFL.txt` (licencia SIL OFL 1.1 de Inter, vendorizada junto a los binarios — ver §9).
- `ui/webview/frontend/css/fonts.css` — 3 bloques `@font-face` (CA-26).
- `ui/webview/frontend/css/panels.css` — estilos de los modales de Tareas/Proyectos (reutiliza
  `.modal-overlay`/`.modal-box` de `modal.css`, agrega clases propias de contenido: `.panel-list`,
  `.panel-item`, `.panel-form`, `.panel-empty`, `.task-item.completed`).
- `ui/webview/frontend/js/tasks_panel.js` — construcción del modal de Tareas, formulario de creación,
  lista con completar/eliminar.
- `ui/webview/frontend/js/projects_panel.js` — construcción del modal de Proyectos, formulario de
  creación, lista, vista de detalle (conversaciones del proyecto), picker de asignación.
- `tests/test_memory_manager_projects.py` — esquema y CRUD de proyectos, no-regresión de las 5
  funciones protegidas, limpieza de huérfanos.
- Tests nuevos agregados a `tests/test_webview_bridge.py` (slots de tareas/proyectos) y a
  `tests/test_security_manager.py` (clasificación YELLOW de `delete_task`/`delete_project`) — mismo
  patrón de archivo por área que ya usa el proyecto (nota de baseline-016.md), no archivos nuevos
  para estos dos casos.
- `tests/test_webview_safe_dom_insertion.py` — se **extiende** la lista `_MUST_NOT_USE_INNERHTML`
  con `tasks_panel.js` y `projects_panel.js` (archivo existente, no nuevo — ver §10).

### Sin modificar (confirmado, no requieren cambios)
- `tasks/task_manager.py`, `tasks/task_scheduler.py` — ya tienen todo lo necesario (confirmado por
  baseline y re-verificado en esta sesión).
- `ui/webview/frontend/js/chat.js`, `composer.js`, `confirm_modal.js`, `window_chrome.js`, `theme.js` —
  ninguno necesita cambios para este REQ.
- `ui/webview/frontend/css/composer.css`, `css/chat.css`, `css/layout.css`, `css/animations.css` —
  sin cambios.
- `ui/webview/confirmation_adapter.py` — se reutiliza tal cual, cero cambios (mismo adaptador ya
  registrado en `MainWindow.__init__`, ver §6).

---

## 3. Nuevas clases/funciones — resumen

| Nombre | Archivo | Responsabilidad |
|--------|---------|------------------|
| `ProjectSummary` (dataclass) | `ai/memory_manager.py` | Fila del listado de proyectos — mismo criterio que `ConversationSummary` ya existente. |
| `UnifiedMemory.create_project()` | `ai/memory_manager.py` | CA-14 — crea proyecto, valida nombre no vacío. |
| `UnifiedMemory.list_projects()` | `ai/memory_manager.py` | CA-15 — lista proyectos del usuario con conteo de conversaciones. |
| `UnifiedMemory.assign_conversation_to_project()` | `ai/memory_manager.py` | CA-16, CA-20 — asigna/reasigna (1 proyecto a la vez, garantizado por PK). |
| `UnifiedMemory.unassign_conversation_from_project()` | `ai/memory_manager.py` | CA-16 (desasignar) y CA-21 (limpieza de huérfanos, reutilizada). |
| `UnifiedMemory.list_conversations_by_project()` | `ai/memory_manager.py` | CA-17 — vista de detalle, `INNER JOIN` defensivo contra huérfanos. |
| `UnifiedMemory.delete_project()` | `ai/memory_manager.py` | CA-18, CA-19 — borra proyecto y sus asignaciones, nunca `memories`. |
| `Bridge.request_tasks/create_task/complete_task/request_delete_task` | `ui/webview/bridge.py` | CA-05..CA-12 — ver §5.1. |
| `Bridge.request_projects/create_project/assign_conversation_to_project/unassign_conversation_from_project/request_project_conversations/request_delete_project` | `ui/webview/bridge.py` | CA-13..CA-21 — ver §5.2. |
| `openTasksPanel()` / `closeTasksPanel()` | `js/tasks_panel.js` | CA-05, CA-12 — construcción del modal, carga perezosa. |
| `openProjectsPanel()` / `closeProjectsPanel()` | `js/projects_panel.js` | CA-13, CA-17 — construcción del modal, vista maestro/detalle. |

---

## 4. Esquema de datos — `ai/memory_manager.py`

### 4.1 Tablas nuevas (migración aditiva dentro de `_init_db()`)

Se agregan dentro del mismo bloque `with sqlite3.connect(DB_PATH) as conn:` de `_init_db()`, junto a
la creación ya existente de `memories`/`summaries` (antes o después de `self._migrate_schema(conn)` —
no hay dependencia de orden, estas tablas no leen columnas de `memories`):

```python
conn.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_projects_user
    ON projects(user_id)
""")
conn.execute("""
    CREATE TABLE IF NOT EXISTS project_conversations (
        conversation_id TEXT PRIMARY KEY,
        project_id INTEGER NOT NULL,
        user_id TEXT NOT NULL,
        assigned_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    )
""")
conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_project_conversations_project
    ON project_conversations(project_id, user_id)
""")
```

**Por qué `conversation_id` es la `PRIMARY KEY` de `project_conversations` (y no un `id INTEGER`
autoincremental con un índice único aparte):** CA-20 exige que una conversación pertenezca a lo sumo
a un proyecto a la vez. Declarar `conversation_id TEXT PRIMARY KEY` hace que esa regla sea una
restricción física del esquema, no algo que la lógica de Python tenga que verificar y pueda
eventualmente olvidar verificar — `INSERT OR REPLACE INTO project_conversations (conversation_id,
project_id, user_id, assigned_at) VALUES (?, ?, ?, ?)` reasigna atómicamente sin duplicar filas,
SQLite lo garantiza. No se declara `FOREIGN KEY (conversation_id) REFERENCES memories(conversation_id)`
porque `memories.conversation_id` no es `UNIQUE`/`PRIMARY KEY` (hay múltiples filas por conversación,
una por turno) — SQLite no permite una FK contra una columna no única; la integridad referencial hacia
`memories` se resuelve en la capa de aplicación (§4.3), no en el esquema.

Estas dos tablas son las **únicas** estructuras nuevas. `memories` no gana ninguna columna — cero
riesgo de interferir con cualquiera de las 5 funciones protegidas por CA-21, que ni siquiera saben que
`projects`/`project_conversations` existen.

```python
@dataclass
class ProjectSummary:
    """Fila del listado de proyectos del sidebar (REQ-016/CA-15), mismo criterio que
    `ConversationSummary` (REQ-013/CA-10)."""
    id: int
    name: str
    created_at: str
    conversation_count: int
```

### 4.2 Funciones nuevas (métodos de `UnifiedMemory`)

```python
def create_project(self, user_id: str = "default", name: str = "") -> Optional[int]:
    """Crea un proyecto y devuelve su id (o None si el nombre es vacío/solo espacios,
    CA-14, caso borde de SPEC-016). Sin unicidad de nombre — dos proyectos pueden llamarse
    igual (caso borde explícito de SPEC-016: "es solo una etiqueta visual, no un
    identificador")."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                "INSERT INTO projects (user_id, name, created_at) VALUES (?, ?, ?)",
                (user_id, name, datetime.now().isoformat()),
            )
            return cur.lastrowid
    except Exception as e:
        logger.error(f"Error creando proyecto: {e}")
        return None

def list_projects(self, user_id: str = "default") -> List[ProjectSummary]:
    """CA-15 — proyectos del usuario, más reciente primero, con conteo de conversaciones
    asignadas (subquery, sin N+1: una sola consulta)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                """SELECT p.id, p.name, p.created_at,
                          (SELECT COUNT(*) FROM project_conversations pc
                            WHERE pc.project_id = p.id) AS conversation_count
                   FROM projects p
                   WHERE p.user_id = ?
                   ORDER BY p.created_at DESC""",
                (user_id,),
            ).fetchall()
        return [ProjectSummary(id=r[0], name=r[1], created_at=r[2], conversation_count=r[3])
                for r in rows]
    except Exception as e:
        logger.error(f"Error listando proyectos: {e}")
        return []

def assign_conversation_to_project(self, conversation_id: str, project_id: int,
                                    user_id: str = "default") -> bool:
    """CA-16, CA-20 — asigna (o reasigna) una conversación a un proyecto. Verifica que
    AMBOS existan y pertenezcan a `user_id` antes de escribir (defensa en profundidad:
    a diferencia de `conversation_id` (uuid4, no adivinable), `project_id` es un entero
    autoincremental chico — sí es adivinable, mismo criterio conservador que ya usa
    `delete_conversation()` para su propio filtro de `user_id`, aplicado acá con más
    razón)."""
    if not conversation_id:
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            owns_project = conn.execute(
                "SELECT 1 FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
            ).fetchone()
            if not owns_project:
                return False
            owns_conversation = conn.execute(
                "SELECT 1 FROM memories WHERE conversation_id = ? AND user_id = ? LIMIT 1",
                (conversation_id, user_id),
            ).fetchone()
            if not owns_conversation:
                return False
            conn.execute(
                """INSERT OR REPLACE INTO project_conversations
                       (conversation_id, project_id, user_id, assigned_at)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, project_id, user_id, datetime.now().isoformat()),
            )
        return True
    except Exception as e:
        logger.error(f"Error asignando conversación a proyecto: {e}")
        return False

def unassign_conversation_from_project(self, conversation_id: str,
                                        user_id: str = "default") -> bool:
    """CA-16 (desasignar explícito desde la UI) y CA-21 (limpieza de huérfanos al borrar
    una conversación, ver §4.3) — misma función para ambos casos, DELETE idempotente:
    llamarla sobre una conversación sin proyecto asignado no lanza, retorna False."""
    if not conversation_id:
        return False
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                "DELETE FROM project_conversations WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
        return bool(cur.rowcount)
    except Exception as e:
        logger.error(f"Error desasignando conversación de proyecto: {e}")
        return False

def list_conversations_by_project(self, project_id: int,
                                   user_id: str = "default") -> List[ConversationSummary]:
    """CA-17 — mismo shape de salida que `list_conversations()` (reutiliza
    `ConversationSummary`), pero es una query separada (no una modificación de
    `list_conversations()`, que CA-21 protege) con un INNER JOIN adicional contra
    `project_conversations`. Esto también actúa como red de seguridad contra huérfanos:
    si por algún motivo quedara una fila en `project_conversations` sin fila
    correspondiente en `memories` (no debería pasar, ver §4.3), el INNER JOIN la excluye
    automáticamente — nunca se renderiza una conversación "fantasma"."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                """SELECT  m.conversation_id,
                           MAX(m.timestamp) AS last_activity,
                           COUNT(*)         AS turn_count,
                           (SELECT u.text FROM memories u
                             WHERE u.conversation_id = m.conversation_id
                               AND u.role = 'user'
                             ORDER BY u.id ASC LIMIT 1) AS title_src
                   FROM memories m
                   INNER JOIN project_conversations pc
                           ON pc.conversation_id = m.conversation_id
                          AND pc.user_id = m.user_id
                   WHERE m.user_id = ? AND m.archived = 0
                         AND m.conversation_id IS NOT NULL
                         AND pc.project_id = ?
                   GROUP BY m.conversation_id
                   ORDER BY last_activity DESC""",
                (user_id, project_id),
            ).fetchall()
        return [ConversationSummary(conversation_id=r[0], last_activity=r[1] or "",
                                     turn_count=r[2], title=_derive_title(r[3]))
                for r in rows]
    except Exception as e:
        logger.error(f"Error listando conversaciones del proyecto: {e}")
        return []

def delete_project(self, project_id: int, user_id: str = "default") -> bool:
    """CA-18, CA-19 — borra el proyecto y sus filas de asignación. NUNCA toca `memories`:
    las conversaciones que agrupaba quedan intactas por construcción (tablas separadas),
    no por una condición si/no en el código."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.execute(
                "DELETE FROM projects WHERE id = ? AND user_id = ?", (project_id, user_id)
            )
            deleted = cur.rowcount
            if deleted:
                conn.execute(
                    "DELETE FROM project_conversations WHERE project_id = ?", (project_id,)
                )
        return bool(deleted)
    except Exception as e:
        logger.error(f"Error eliminando proyecto: {e}")
        return False
```

Nota de estilo: las 6 funciones siguen exactamente el mismo patrón que ya usa todo el archivo —
`with sqlite3.connect(DB_PATH) as conn:`, `try/except Exception as e: logger.error(...); return
False/None/[]` (nunca `except: pass`), sin `SELECT *` (columnas explícitas), y `user_id` siempre en
el `WHERE` de cualquier lectura/escritura — cero patrones nuevos introducidos al módulo.

### 4.3 Limpieza de huérfanos al borrar una conversación — dónde vive exactamente

Confirmado por grep (baseline y esta sesión, independientemente): `ai/memory_manager.py::
delete_conversation()` tiene **un único call-site real** en todo el proyecto —
`ui/webview/bridge.py::_delete_conversation_flow()` (líneas 248-264). Ningún bot, CLI ni test de
producción la invoca desde otro lugar. Por eso la limpieza de la segunda mitad de CA-21 se agrega ahí,
**no** dentro de `delete_conversation()`:

```python
def _delete_conversation_flow(self, conversation_id: str) -> None:
    from ai.memory_manager import memory
    from core.security_manager import format_details, security_manager

    confirmed = security_manager.require_confirmation(
        "delete_conversation", ChannelType.DESKTOP,
        details=format_details("webview:delete_conversation", {"name": conversation_id}),
        user_id="default",
    )
    if not confirmed:
        return
    deleted = memory.delete_conversation(conversation_id, user_id="default")
    if deleted:
        memory.unassign_conversation_from_project(conversation_id, user_id="default")  # REQ-016/CA-21
        self.conversation_removed.emit(conversation_id)
```

Solo se agrega la línea marcada `# REQ-016/CA-21` — el resto de la función queda idéntico a como la
dejó REQ-015. Consecuencia directa: **`ai/memory_manager.py::delete_conversation()` no cambia ni una
sola línea** — la lectura más estricta posible de "no debe modificar el comportamiento de
`delete_conversation()` ya existente" (CA-21) queda satisfecha de forma literal, no solo funcional.
`unassign_conversation_from_project()` es idempotente (DELETE simple, `rowcount` puede ser 0 sin
lanzar) — llamarla sobre una conversación que nunca estuvo en un proyecto es un no-op seguro, así que
no hace falta verificar antes si la conversación pertenecía a alguno.

Doble capa de defensa contra huérfanos (documentado explícitamente, no accidental):
1. **Activa:** el DELETE de arriba, disparado en el único call-site real.
2. **Pasiva/estructural:** `list_conversations_by_project()` (§4.2) usa `INNER JOIN` contra
   `memories` — aunque la limpieza activa fallara o un caller futuro hipotético invocara
   `memory.delete_conversation()` sin pasar por el bridge, una fila huérfana en
   `project_conversations` nunca se renderiza ni se cuenta como conversación real (aunque sí seguiría
   contando en `conversation_count` de `list_projects()`, que no hace ese mismo JOIN — ver "Riesgos"
   §13 para esta asimetría conocida y su mitigación).

---

## 5. Bridge — nuevos `pyqtSlot`/`pyqtSignal`

Patrón replicado en las 10 acciones nuevas: los slots que solo leen (`request_*`) despachan un
`run_async()` normal (worker en `QThreadPool`, callback `on_done` en el hilo de la GUI). Los slots que
mutan (crear/completar/asignar/desasignar/borrar) también despachan `run_async()`, pero la función que
corre en el worker **emite la señal directamente al terminar** (mismo patrón ya probado por
`_delete_conversation_flow()`, que emite `conversation_removed` desde el hilo worker sin pasar por
`on_done`) — evita anidar un segundo `run_async()` dentro del primero.

### 5.1 Tareas

```python
# ------------------------------------------------------------ Python → JS (nuevas)
tasks_loaded = pyqtSignal(str)   # json: lista cruda de task_manager.list_all_tasks() (SELECT * → dict)

# ------------------------------------------------------------ JS → Python (nuevas)
@pyqtSlot()
def request_tasks(self) -> None:
    """CA-05, CA-12 — se llama solo al abrir el modal de Tareas, NUNCA desde
    request_initial_state()."""
    run_async(self._fetch_tasks, self._on_tasks_loaded, self._on_task_error)

def _fetch_tasks(self):
    from tasks.task_manager import task_manager
    return task_manager.list_all_tasks(user_id="default")

def _on_tasks_loaded(self, tasks) -> None:
    self.tasks_loaded.emit(json.dumps(tasks))

def _emit_tasks_loaded(self) -> None:
    """Se llama SIEMPRE desde el hilo worker que ya está ejecutando una mutación (crear/
    completar/borrar) — nunca agenda un run_async() anidado, solo relee la lista en el
    mismo hilo y emite (mismo patrón cross-thread ya usado por
    `conversation_removed.emit()` en `_delete_conversation_flow`)."""
    from tasks.task_manager import task_manager
    tasks = task_manager.list_all_tasks(user_id="default")
    self.tasks_loaded.emit(json.dumps(tasks))

@pyqtSlot(str, str, str, str)
def create_task(self, title: str, description: str, due_date: str, priority: str) -> None:
    """CA-06 — título obligatorio; el resto opcional. `due_date`/`priority` en blanco
    ("") delegan el default a `task_manager.create_task()` (vence en 1h, prioridad
    'normal'), sin reimplementar esa lógica acá."""
    if not title.strip():
        return
    run_async(self._create_task_flow, None, self._on_task_error,
              title.strip(), description, due_date, priority)

def _create_task_flow(self, title, description, due_date, priority) -> None:
    from tasks.task_manager import task_manager
    task_manager.create_task(
        user_id="default", title=title, channel="desktop",
        description=description or "", due_date=due_date or None,
        remind_at=due_date or None, priority=priority or "normal",
    )
    self._emit_tasks_loaded()

@pyqtSlot(int)
def complete_task(self, task_id: int) -> None:
    """CA-07 — sin confirmación (no es destructivo, no está en el alcance YELLOW de
    CA-33)."""
    run_async(self._complete_task_flow, None, self._on_task_error, task_id)

def _complete_task_flow(self, task_id: int) -> None:
    from tasks.task_manager import task_manager
    task_manager.complete_task(task_id, user_id="default")
    self._emit_tasks_loaded()

@pyqtSlot(int)
def request_delete_task(self, task_id: int) -> None:
    """CA-08, CA-33 — replica EXACTO el flujo de `request_delete_conversation()`/
    `_delete_conversation_flow()` (arquitectura-015.md §10.2): confirmación YELLOW antes
    de tocar `task_manager.delete_task()`, nunca al revés."""
    run_async(self._delete_task_flow, None, self._on_task_error, task_id)

def _delete_task_flow(self, task_id: int) -> None:
    from tasks.task_manager import task_manager
    from core.security_manager import format_details, security_manager

    confirmed = security_manager.require_confirmation(
        "delete_task", ChannelType.DESKTOP,
        details=format_details("webview:delete_task", {"name": str(task_id)}),
        user_id="default",
    )
    if not confirmed:
        return
    task_manager.delete_task(task_id, user_id="default")
    self._emit_tasks_loaded()

def _on_task_error(self, message: str) -> None:
    logger.error(f"Error en operación de tareas: {message}")
    self.error_occurred.emit(message)
```

`complete_task()`/`delete_task()`/`delete_task` retornan `bool` en `task_manager.py` — si el `id` ya
no existe (doble click, caso borde de SPEC-016), simplemente no hacen efecto; `_emit_tasks_loaded()`
igual se llama y refresca la lista tal como está, sin lanzar.

### 5.2 Proyectos

```python
# ------------------------------------------------------------ Python → JS (nuevas)
projects_loaded = pyqtSignal(str)               # json: [{id, name, created_at, conversation_count}]
project_conversations_loaded = pyqtSignal(str, int)  # json (shape de conversation_list_updated), project_id
project_removed = pyqtSignal(int)               # project_id

# ------------------------------------------------------------ JS → Python (nuevas)
def _projects_payload(self, projects) -> str:
    return json.dumps([
        {"id": p.id, "name": p.name, "created_at": p.created_at,
         "conversation_count": p.conversation_count}
        for p in projects
    ])

@pyqtSlot()
def request_projects(self) -> None:
    """CA-13 — carga perezosa, solo al abrir el modal de Proyectos."""
    run_async(self._fetch_projects, self._on_projects_loaded, self._on_project_error)

def _fetch_projects(self):
    from ai.memory_manager import memory
    return memory.list_projects(user_id="default")

def _on_projects_loaded(self, projects) -> None:
    self.projects_loaded.emit(self._projects_payload(projects))

def _emit_projects_loaded(self) -> None:
    from ai.memory_manager import memory
    self.projects_loaded.emit(self._projects_payload(memory.list_projects(user_id="default")))

@pyqtSlot(str)
def create_project(self, name: str) -> None:
    """CA-14 — nombre vacío/solo espacios rechazado en el cliente Y acá (defensa en
    profundidad, mismo criterio que `send_message()` con texto vacío)."""
    if not name.strip():
        return
    run_async(self._create_project_flow, None, self._on_project_error, name.strip())

def _create_project_flow(self, name: str) -> None:
    from ai.memory_manager import memory
    memory.create_project(user_id="default", name=name)
    self._emit_projects_loaded()

@pyqtSlot(str, int)
def assign_conversation_to_project(self, conversation_id: str, project_id: int) -> None:
    """CA-16, CA-20 — reasigna si ya pertenecía a otro proyecto (garantizado por la PK de
    `project_conversations`, §4.1)."""
    run_async(self._assign_flow, None, self._on_project_error, conversation_id, project_id)

def _assign_flow(self, conversation_id: str, project_id: int) -> None:
    from ai.memory_manager import memory
    memory.assign_conversation_to_project(conversation_id, project_id, user_id="default")
    self._emit_projects_loaded()

@pyqtSlot(str)
def unassign_conversation_from_project(self, conversation_id: str) -> None:
    """CA-16 (desasignar) — llamado desde la vista de detalle de un proyecto."""
    run_async(self._unassign_flow, None, self._on_project_error, conversation_id)

def _unassign_flow(self, conversation_id: str) -> None:
    from ai.memory_manager import memory
    memory.unassign_conversation_from_project(conversation_id, user_id="default")
    self._emit_projects_loaded()

@pyqtSlot(int)
def request_project_conversations(self, project_id: int) -> None:
    """CA-17 — vista de detalle. El `project_id` viaja también en la señal de vuelta
    (`project_conversations_loaded(json, project_id)`) para que la UI descarte una
    respuesta tardía si el usuario ya cambió de proyecto (caso borde de SPEC-016: doble
    click rápido no debe mezclar datos de dos proyectos distintos)."""
    run_async(self._fetch_project_conversations, None, self._on_project_error, project_id)

def _fetch_project_conversations(self, project_id: int) -> None:
    from ai.memory_manager import memory
    conversations = memory.list_conversations_by_project(project_id, user_id="default")
    payload = json.dumps([
        {"conversation_id": c.conversation_id, "title": c.title,
         "last_activity": c.last_activity, "turn_count": c.turn_count}
        for c in conversations
    ])
    self.project_conversations_loaded.emit(payload, project_id)

@pyqtSlot(int)
def request_delete_project(self, project_id: int) -> None:
    """CA-18, CA-33 — mismo flujo YELLOW que `delete_task`/`delete_conversation`."""
    run_async(self._delete_project_flow, None, self._on_project_error, project_id)

def _delete_project_flow(self, project_id: int) -> None:
    from ai.memory_manager import memory
    from core.security_manager import format_details, security_manager

    confirmed = security_manager.require_confirmation(
        "delete_project", ChannelType.DESKTOP,
        details=format_details("webview:delete_project", {"name": str(project_id)}),
        user_id="default",
    )
    if not confirmed:
        return
    deleted = memory.delete_project(project_id, user_id="default")
    if deleted:
        self.project_removed.emit(project_id)   # CA-19: las conversaciones NO se tocan
        self._emit_projects_loaded()

def _on_project_error(self, message: str) -> None:
    logger.error(f"Error en operación de proyectos: {message}")
    self.error_occurred.emit(message)
```

### 5.3 Docstring del módulo (§ whitelisting, CA-34)

Se extiende el párrafo de `ui/webview/bridge.py` líneas 1-9 (la enumeración explícita que hoy dice
"5 funciones de `ai/memory_manager.py`... y `WakeWordWorker`") agregando, al final de esa misma
enumeración:

> ...y (REQ-016) 4 funciones de `tasks/task_manager.py` (`create_task`, `list_all_tasks`,
> `complete_task`, `delete_task`, todas ya existentes, sin modificar) + 6 funciones nuevas de
> `ai/memory_manager.py` (`create_project`, `list_projects`, `assign_conversation_to_project`,
> `unassign_conversation_from_project`, `list_conversations_by_project`, `delete_project`). Ningún
> slot nuevo importa `tasks/task_manager.py` ni el código de proyectos de `ai/memory_manager.py` fuera
> de esta lista — JS nunca los toca directo (CA-34).

No se retira ni renombra nada de la enumeración existente.

---

## 6. Seguridad — `core/security_manager.py`

Una línea nueva junto a cada una de las dos ya explicadas por el comentario existente sobre
`delete_conversation` (líneas 307-311), reutilizando el mismo razonamiento textual:

```python
def _register_default_actions():
    sm = security_manager
    ...
    sm.register_action("delete_conversation", RiskLevel.YELLOW)
    # REQ-016/CA-08, CA-18, CA-33 — mismo patrón que delete_conversation: son @pyqtSlot
    # invocables desde cualquier script que corra en la página del WebView, no solo desde
    # el botón visible; se clasifican YELLOW y pasan por el mismo
    # `security_manager.require_confirmation()` antes de ejecutarse.
    sm.register_action("delete_task", RiskLevel.YELLOW)
    sm.register_action("delete_project", RiskLevel.YELLOW)
    ...
```

No se toca `CHANNEL_ALLOWED_LEVELS` (`ChannelType.DESKTOP` ya permite `YELLOW`, confirmado por
baseline), no se toca `_DETAILS_ALLOWED_KEYS` (la clave `"name"` ya está permitida y es la que se
reutiliza para `str(task_id)`/`str(project_id)`, mismo criterio que `delete_conversation` con
`conversation_id`), y no se reclasifica ninguna acción existente. `require_confirmation()` en sí
(`core/security_manager.py:232`) no cambia — es el mismo punto de entrada único que ya usa todo el
resto del sistema.

---

## 7. `main.py` — arranque de `task_scheduler` (CA-10)

```python
from core.proactive_engine import proactive_engine
from tasks.task_scheduler import task_scheduler   # REQ-016/CA-10
...

def main(boot_mode=None, gui_active=False):
    ui = CLI(gui_active=gui_active)

    proactive_engine.start()
    task_scheduler.start()   # REQ-016/CA-10 — antes solo arrancaba desde channels/telegram_bot.py
    ...
    if choice == 'q':
        proactive_engine.stop()
        task_scheduler.stop()   # simetría con proactive_engine — TaskScheduler.stop() ya existe
                                 # (tasks/task_scheduler.py:63), no exigido literal por CA-10 pero
                                 # mismo criterio que ya usa este mismo bloque para el otro engine
        ...
```

`TaskScheduler.start()` es idempotente (`if self._running: return`, confirmado por baseline) — si en
algún momento también corre el bot de Telegram en el mismo proceso y llama `task_scheduler.start()`
de nuevo, no crea un segundo hilo. Caso borde documentado (no un bug a corregir en este REQ, ver §13):
una vez que el scheduler de escritorio está activo, una tarea con `channel="telegram"` que vence
también dispara `_notify_local()` (TTS + Toast) si la app de escritorio está abierta en simultáneo —
comportamiento ya existente de `_send_notification()` línea 151 (`if channel == "desktop" or
channel == "telegram": self._notify_local(...)`), no algo que este REQ introduce ni que
`tasks/task_scheduler.py` necesite modificar para cumplir CA-10.

---

## 8. Frontend

### 8.1 Header en píldora (CA-01, CA-02, CA-04)

`index.html` — el `#sidebar-header` actual (logo + botón `«`) se reduce a solo el logo; el botón de
colapso se muda dentro de la píldora nueva junto con búsqueda y nuevo chat:

```html
<aside id="sidebar">
  <div id="sidebar-header">
    <span id="sidebar-logo"></span>
  </div>
  <div id="sidebar-toolbar" class="icon-pill">
    <button type="button" id="sidebar-collapse-toggle" class="pill-btn"
            aria-label="Colapsar panel lateral" title="Colapsar panel lateral">&#171;</button>
    <button type="button" id="sidebar-search-toggle" class="pill-btn"
            aria-label="Buscar conversaciones" title="Buscar conversaciones">&#128269;</button>
    <button type="button" id="new-conversation-btn" class="pill-btn"
            aria-label="Nuevo chat" title="Nuevo chat">+</button>
  </div>
  <div id="sidebar-search-row" hidden>
    <input type="search" id="sidebar-search-input" aria-label="Buscar conversaciones"
           placeholder="Buscar conversaciones…">
  </div>
  <button type="button" id="tasks-btn" class="sidebar-action-btn" title="Tareas">
    <span class="icon" aria-hidden="true">&#128203;</span>
    <span class="label">Tareas</span>
  </button>
  <button type="button" id="projects-btn" class="sidebar-action-btn" title="Proyectos">
    <span class="icon" aria-hidden="true">&#128193;</span>
    <span class="label">Proyectos</span>
  </button>
  <div id="conversation-list" role="list"></div>
  ...
</aside>
```

`#new-conversation-btn` conserva el mismo `id` — su listener en `initSidebar()`
(`newConversation()`, CA-04/CA-07 de SPEC-015) sigue funcionando sin ningún cambio de código, solo
cambió su padre en el DOM. `#sidebar-collapse-toggle` idem: mismo `id`, mismo listener
(`$("sidebar").classList.toggle("collapsed")`), solo cambia de contenedor.

`sidebar.css` — nuevo bloque:

```css
#sidebar-toolbar.icon-pill {
  display: flex;
  align-items: center;
  gap: 2px;
  margin: 0 12px 12px;
  padding: 4px;
  background-color: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 999px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.pill-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 999px;
  color: var(--text-secondary);
  transition: background-color 150ms, color 150ms;
}

/* CA-02: cada uno de los 3 controles distingue hover/activo por separado — mismo selector
   ya usado para .composer-icon-btn:hover, sin inventar un mecanismo nuevo. */
.pill-btn:hover {
  background-color: var(--bg-hover);
  color: var(--text-primary);
}

.pill-btn.active {
  background-color: var(--bg-hover);
  color: var(--text-accent);
}

#sidebar-search-row {
  margin: 0 12px 12px;
}

#sidebar-search-input {
  width: 100%;
  border: 1px solid var(--border);
  background-color: var(--bg-input);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  color: var(--text-primary);
}

#sidebar-search-input:focus {
  outline: none;
  border-color: var(--text-accent);
}
```

`#sidebar-header` pierde `justify-content: space-between` (ya no tiene 2 hijos, solo el logo) —
ajuste trivial de una regla ya existente, sin efecto en nada más.

### 8.2 Búsqueda client-side (CA-03) — precisión sobre el alcance en `sidebar.js`

Aclaración que afina lo dicho en §2: además de la función nueva exportada (`getLoadedConversations()`,
para el picker de asignación a proyecto de §8.4), `sidebar.js` recibe:

1. **Código nuevo dentro de `initSidebar()`** — 2 listeners nuevos (toggle de la fila de búsqueda,
   filtrado en `input`). Aditivo: ningún listener existente (`sidebar-collapse-toggle`,
   `new-conversation-btn`, `load-more-btn`) se toca.
2. **Una línea nueva al final de `renderConversationList()`** — reaplica el filtro de búsqueda activo
   tras cualquier recarga de la lista (p. ej., después de enviar un mensaje, que dispara
   `_load_conversations(offset=0)` en el bridge). Sin esta línea, escribir un término de búsqueda y
   luego enviar un mensaje mostraría de nuevo la lista completa sin filtrar — regresión de UX real,
   no solo cosmética.
3. **Dos líneas nuevas dentro del loop existente de `renderConversationList()`** — acumulan
   `{conversation_id, title}` en un array module-level nuevo (`_loadedConversations`), fuente de datos
   del picker de §8.4. No cambian el orden ni el contenido de lo que ya hace el loop (seguir
   construyendo y montando cada `.conv-item` exactamente igual).

Con término de búsqueda vacío (estado por defecto al abrir la app, y caso borde explícito de
SPEC-016: "Buscar con el término vacío... muestra la lista completa ya cargada, sin filtrar nada") el
comportamiento observable es **idéntico** al de hoy — CA-25 no se reabre: `buildConversationItem()`,
`setActiveConversationId()` y `removeConversationFromList()` no cambian ni una línea.

```js
let _searchTerm = "";
let _loadedConversations = [];   // REQ-016/§0.2 — fuente del picker de projects_panel.js

function applySearchFilter() {
  for (const item of document.querySelectorAll(".conv-item")) {
    const title = item.querySelector(".conv-title").textContent.toLowerCase();
    item.hidden = _searchTerm !== "" && !title.includes(_searchTerm);
  }
}

export function initSidebar() {
  // ... listeners existentes de sidebar-collapse-toggle / new-conversation-btn / load-more-btn,
  // SIN CAMBIOS ...

  $("sidebar-search-toggle").addEventListener("click", () => {
    const row = $("sidebar-search-row");
    row.hidden = !row.hidden;
    $("sidebar-search-toggle").classList.toggle("active", !row.hidden);
    if (!row.hidden) $("sidebar-search-input").focus();
  });

  $("sidebar-search-input").addEventListener("input", (evt) => {
    _searchTerm = evt.target.value.trim().toLowerCase();
    applySearchFilter();
  });
}

export function renderConversationList(items) {
  const container = $("conversation-list");
  if (!_pendingAppend) {
    container.replaceChildren();
    _count = 0;
    _loadedConversations = [];
  }
  for (const conv of items) {
    container.appendChild(buildConversationItem(conv));
    _loadedConversations.push({ conversation_id: conv.conversation_id, title: conv.title });
    _count += 1;
  }
  $("load-more-btn").hidden = items.length < PAGE_SIZE;
  _pendingAppend = false;
  setActiveConversationId(_activeConversationId);
  applySearchFilter();   // REQ-016/CA-03
}

export function getLoadedConversations() {
  return [..._loadedConversations];   // copia — no expone el array mutable interno
}
```

`item.hidden = true/false` (en vez de tocar `display` por CSS) es la misma técnica que ya usa el
proyecto para `#load-more-btn`/`#typing-indicator`/`#attachment-chip` — cero mecanismo nuevo.

---

### 8.3 Panel de Tareas (CA-05..CA-12)

`index.html` gana `<div id="panel-modal-root"></div>` como hermano de `#confirm-modal-root` (§0.3 —
raíz separada, nunca compartida con el modal de confirmación YELLOW).

`js/tasks_panel.js` (nuevo), estructura:

```js
import { requestTasks, createTask, completeTask, requestDeleteTask } from "./bridge_client.js";

let _panelOpen = false;   // guard contra doble click (caso borde de SPEC-016)

export function openTasksPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  renderShell();
  requestTasks();   // CA-12: carga perezosa, solo acá
}

function closeTasksPanel() {
  _panelOpen = false;
  document.getElementById("panel-modal-root").replaceChildren();
}

function renderShell() {
  const root = document.getElementById("panel-modal-root");
  root.replaceChildren();

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.addEventListener("click", (evt) => { if (evt.target === overlay) closeTasksPanel(); });

  const box = document.createElement("div");
  box.className = "modal-box modal-box-wide";

  const header = document.createElement("div");
  header.className = "panel-header";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Tareas";   // texto propio, no viene de Python — no aplica §10.1
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "panel-close-btn";
  closeBtn.setAttribute("aria-label", "Cerrar");
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", closeTasksPanel);
  header.appendChild(title);
  header.appendChild(closeBtn);

  const form = buildTaskForm();
  const list = document.createElement("div");
  list.id = "tasks-panel-list";
  list.className = "panel-list";

  box.appendChild(header);
  box.appendChild(form);
  box.appendChild(list);
  overlay.appendChild(box);
  root.appendChild(overlay);
}

function buildTaskForm() {
  const form = document.createElement("form");
  form.className = "panel-form";

  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.placeholder = "Título de la tarea";
  titleInput.required = true;

  const dateInput = document.createElement("input");
  dateInput.type = "datetime-local";

  const prioritySelect = document.createElement("select");
  for (const [value, label] of [["normal", "Normal"], ["high", "Alta prioridad"]]) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    prioritySelect.appendChild(opt);
  }

  const descInput = document.createElement("input");
  descInput.type = "text";
  descInput.placeholder = "Descripción (opcional)";

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  submitBtn.className = "panel-submit-btn";
  submitBtn.textContent = "Agregar";

  form.append(titleInput, dateInput, prioritySelect, descInput, submitBtn);
  form.addEventListener("submit", (evt) => {
    evt.preventDefault();
    const titleValue = titleInput.value.trim();
    if (!titleValue) return;   // CA-06: título obligatorio, guard también del lado JS
    createTask(titleValue, descInput.value, dateInput.value, prioritySelect.value);
    form.reset();
  });
  return form;
}

export function renderTasks(tasks) {
  const list = document.getElementById("tasks-panel-list");
  if (!list) return;   // panel ya fue cerrado antes de que llegara la respuesta
  list.replaceChildren();

  if (tasks.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "No hay tareas todavía.";
    list.appendChild(empty);
    return;
  }

  for (const task of tasks) {
    list.appendChild(buildTaskItem(task));
  }
}

function buildTaskItem(task) {
  const item = document.createElement("div");
  item.className = "panel-item task-item";
  if (task.status === "completed") item.classList.add("completed");   // CA-07: distinción visual

  const info = document.createElement("div");
  info.className = "panel-item-info";
  const titleEl = document.createElement("span");
  titleEl.className = "panel-item-title";
  titleEl.textContent = task.title;   // §10.1 — nunca innerHTML
  info.appendChild(titleEl);
  if (task.due_date) {
    const dateEl = document.createElement("span");
    dateEl.className = "panel-item-meta";
    dateEl.textContent = task.due_date;
    info.appendChild(dateEl);
  }

  const actions = document.createElement("div");
  actions.className = "panel-item-actions";

  if (task.status !== "completed") {
    const doneBtn = document.createElement("button");
    doneBtn.type = "button";
    doneBtn.className = "panel-item-btn";
    doneBtn.setAttribute("aria-label", "Marcar como completada");
    doneBtn.textContent = "✓";
    doneBtn.addEventListener("click", () => completeTask(task.id));
    actions.appendChild(doneBtn);
  }

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "panel-item-btn panel-item-btn-danger";
  deleteBtn.setAttribute("aria-label", "Eliminar tarea");
  deleteBtn.textContent = "✕";
  deleteBtn.addEventListener("click", () => requestDeleteTask(task.id));   // CA-08: dispara YELLOW
  actions.appendChild(deleteBtn);

  item.append(info, actions);
  return item;
}
```

`app.js` cablea el botón de apertura y la señal de datos (ambos agregados al `bootstrap()` existente,
sin tocar ninguna línea previa):

```js
import { openTasksPanel, renderTasks } from "./tasks_panel.js";
...
document.getElementById("tasks-btn").addEventListener("click", openTasksPanel);
onTasksLoaded((json) => renderTasks(JSON.parse(json)));
```

`bridge_client.js` gana los wrappers 1:1 de siempre: `requestTasks()`, `createTask(...)`,
`completeTask(id)`, `requestDeleteTask(id)`, `onTasksLoaded(cb)`.

`request_delete_task(task_id)` NO abre su propio modal de confirmación en JS — dispara
`confirmation_requested` del lado Python (§5.1, §6), que `confirm_modal.js` ya maneja de forma
genérica sobre `#confirm-modal-root` (raíz separada de `#panel-modal-root`, §0.3): el panel de Tareas
sigue montado debajo mientras se confirma/cancela.

---

### 8.4 Panel de Proyectos (CA-13..CA-21) — maestro/detalle + picker de asignación

`js/projects_panel.js` (nuevo) — mismo esqueleto de modal que `tasks_panel.js` (`_panelOpen` guard,
`#panel-modal-root`, `.modal-overlay`/`.modal-box`), con 2 vistas dentro del mismo modal:

1. **Vista maestro** (por defecto al abrir, CA-13/CA-15): formulario "Crear proyecto" (un `<input>` +
   botón, mismo guard de nombre vacío que CA-14) + lista de proyectos (`name`, `conversation_count`,
   botón "Ver" y botón "✕" eliminar).
2. **Vista detalle** (CA-17, al hacer click en "Ver" de un proyecto): botón "← Volver" + lista de las
   conversaciones de ese proyecto (`request_project_conversations(project_id)`) con botón "Quitar" por
   ítem (`unassign_conversation_from_project`) + botón "+ Agregar conversación" que abre el **picker**.

```js
import {
  requestProjects, createProject, assignConversationToProject,
  unassignConversationFromProject, requestProjectConversations, requestDeleteProject,
} from "./bridge_client.js";
import { getLoadedConversations } from "./sidebar.js";   // REQ-016/§0.2

let _panelOpen = false;
let _detailProjectId = null;   // null = vista maestro; distinto de null = vista detalle

export function openProjectsPanel() {
  if (_panelOpen) return;
  _panelOpen = true;
  _detailProjectId = null;
  renderMasterShell();
  requestProjects();
}

function closeProjectsPanel() {
  _panelOpen = false;
  _detailProjectId = null;
  document.getElementById("panel-modal-root").replaceChildren();
}

// ... renderMasterShell()/buildProjectItem() construyen la vista maestro con document.createElement
// + .textContent en cada campo (nombre del proyecto, conteo) — mismo criterio que tasks_panel.js,
// nunca innerHTML (ver §10).

export function renderProjects(projects) {
  if (_detailProjectId !== null) return;   // hay una vista de detalle abierta, no pisar su lista
  const list = document.getElementById("projects-panel-list");
  if (!list) return;
  list.replaceChildren();
  if (projects.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel-empty";
    empty.textContent = "No hay proyectos todavía.";
    list.appendChild(empty);
    return;
  }
  for (const project of projects) {
    list.appendChild(buildProjectItem(project));
  }
}

function buildProjectItem(project) {
  const item = document.createElement("div");
  item.className = "panel-item";

  const info = document.createElement("div");
  info.className = "panel-item-info";
  const nameEl = document.createElement("span");
  nameEl.className = "panel-item-title";
  nameEl.textContent = project.name;   // §10.1 — nunca innerHTML
  const countEl = document.createElement("span");
  countEl.className = "panel-item-meta";
  countEl.textContent = `${project.conversation_count} conversación(es)`;
  info.appendChild(nameEl);
  info.appendChild(countEl);

  const actions = document.createElement("div");
  actions.className = "panel-item-actions";

  const viewBtn = document.createElement("button");
  viewBtn.type = "button";
  viewBtn.className = "panel-item-btn";
  viewBtn.textContent = "Ver";
  viewBtn.addEventListener("click", () => openProjectDetail(project.id, project.name));
  actions.appendChild(viewBtn);

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "panel-item-btn panel-item-btn-danger";
  deleteBtn.setAttribute("aria-label", "Eliminar proyecto");
  deleteBtn.textContent = "✕";
  deleteBtn.addEventListener("click", () => requestDeleteProject(project.id));   // CA-18: YELLOW
  actions.appendChild(deleteBtn);

  item.append(info, actions);
  return item;
}

function openProjectDetail(projectId, projectName) {
  _detailProjectId = projectId;
  renderDetailShell(projectId, projectName);   // "← Volver" + lista vacía + "+ Agregar conversación"
  requestProjectConversations(projectId);
}

// El handler de `project_conversations_loaded(json, projectId)` (cableado en app.js) descarta la
// respuesta si `projectId` no coincide con `_detailProjectId` — caso borde de SPEC-016: doble click
// rápido entre dos proyectos no debe mezclar datos de un proyecto con la vista del otro.
export function renderProjectConversations(conversations, projectId) {
  if (projectId !== _detailProjectId) return;
  const list = document.getElementById("project-detail-list");
  if (!list) return;
  list.replaceChildren();
  for (const conv of conversations) {
    const row = document.createElement("div");
    row.className = "panel-item";
    const titleEl = document.createElement("span");
    titleEl.className = "panel-item-title";
    titleEl.textContent = conv.title;   // §10.1 — nunca innerHTML
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "panel-item-btn";
    removeBtn.textContent = "Quitar";
    removeBtn.addEventListener("click", () => {
      unassignConversationFromProject(conv.conversation_id);
      row.remove();   // feedback inmediato — projects_loaded (conteo) llega poco después igual
    });
    row.append(titleEl, removeBtn);
    list.appendChild(row);
  }
}

// Picker de asignación (CA-16) — fuente: getLoadedConversations() de sidebar.js, sin round-trip
// nuevo al bridge (§0.2). Se abre desde el botón "+ Agregar conversación" de la vista detalle.
function openAssignPicker(projectId) {
  const picker = document.createElement("div");
  picker.className = "modal-overlay";
  const box = document.createElement("div");
  box.className = "modal-box";
  const title = document.createElement("div");
  title.className = "modal-title";
  title.textContent = "Elegí una conversación";
  box.appendChild(title);

  for (const conv of getLoadedConversations()) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "panel-item panel-item-pickable";
    row.textContent = conv.title;   // §10.1 — nunca innerHTML
    row.addEventListener("click", () => {
      assignConversationToProject(conv.conversation_id, projectId);
      picker.remove();
    });
    box.appendChild(row);
  }
  picker.appendChild(box);
  document.getElementById("panel-modal-root").appendChild(picker);   // se apila sobre el panel
}
```

`app.js` — cableo agregado (aditivo):

```js
import { openProjectsPanel, renderProjects, renderProjectConversations } from "./projects_panel.js";
...
document.getElementById("projects-btn").addEventListener("click", openProjectsPanel);
onProjectsLoaded((json) => renderProjects(JSON.parse(json)));
onProjectConversationsLoaded((json, projectId) => renderProjectConversations(JSON.parse(json), projectId));
onProjectRemoved((projectId) => { /* si es el proyecto en vista detalle, projects_panel.js vuelve al maestro */ });
```

`bridge_client.js` gana los 6 wrappers 1:1 correspondientes (`requestProjects`, `createProject`,
`assignConversationToProject`, `unassignConversationFromProject`, `requestProjectConversations`,
`requestDeleteProject`) + 3 `on*` (`onProjectsLoaded`, `onProjectConversationsLoaded`,
`onProjectRemoved`), mismo patrón mecánico que el resto del archivo.

### 8.5 Colapso pulido (CA-22..CA-25) + `css/panels.css`

Gap confirmado por baseline: hoy no existe ninguna regla que centre íconos en `.collapsed`, ni
`title` en ningún botón del sidebar. `sidebar.css` gana:

```css
/* CA-22: iconos centrados en colapsado — incluye el toolbar en píldora y los 2 botones nuevos */
#sidebar.collapsed .sidebar-action-btn,
#sidebar.collapsed .pill-btn {
  justify-content: center;
}

#sidebar.collapsed #sidebar-toolbar.icon-pill {
  flex-direction: column;
  border-radius: 16px;
}

#sidebar.collapsed #sidebar-search-row {
  display: none;   /* mismo criterio que #conversation-list/#sidebar-footer ya ocultos en .collapsed */
}
```

`index.html`: `title="..."` agregado a los 5 controles del sidebar (colapsar, búsqueda, nuevo chat,
Tareas, Proyectos) — ya incluido en el markup de §8.1/§8.3 arriba, gap de CA-23 cerrado sin CSS/JS
adicional (los `title` nativos del navegador aparecen solos al hacer hover, sin listener propio).

CA-24 (transición sin recortes abruptos): la única regla de transición del layout,
`#sidebar { transition: width 200ms ease; }`, no se toca — el `justify-content: center` de CA-22 es
una propiedad que no participa de ninguna animación (no está en una lista de `transition-property`
explícita en ningún lado), así que no introduce un segundo timing que pueda desincronizarse del
existente. No se agrega ninguna transición nueva.

CA-25 (no-regresión de CA-06..CA-11/SPEC-015): confirmado en §8.2 (cero cambios a
`buildConversationItem`/`setActiveConversationId`/`removeConversationFromList`) y en esta sección
(las reglas de colapso nuevas son selectores adicionales — `.pill-btn`, `.icon-pill`, `#sidebar-search-row`
— que no existían antes; ninguna regla ya existente de `#sidebar.collapsed .label,
#conversation-list, #sidebar-footer, .sidebar-load-more { display: none; }` se modifica ni se
reordena).

`css/panels.css` (nuevo) — estilos de contenido de los modales de Tareas/Proyectos, reutilizando
`.modal-overlay`/`.modal-box` de `modal.css` sin duplicarlas (agrega un modificador de ancho y clases
de contenido nuevas):

```css
.modal-box-wide {
  width: 480px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.panel-close-btn {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  width: 24px;
  height: 24px;
}

.panel-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.panel-form input,
.panel-form select {
  border: 1px solid var(--border);
  background-color: var(--bg-input);
  border-radius: 8px;
  padding: 7px 10px;
  font-size: 13px;
  color: var(--text-primary);
}

.panel-submit-btn {
  background-color: var(--text-accent);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
}

.panel-list {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.panel-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 8px;
  background-color: var(--bg-secondary);
}

.panel-item-pickable {
  width: 100%;
  text-align: left;
  border: none;
  cursor: pointer;
}

.panel-item-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.panel-item-title {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-item-meta {
  font-size: 11px;
  color: var(--text-secondary);
}

.task-item.completed .panel-item-title {
  text-decoration: line-through;
  color: var(--text-secondary);   /* CA-07: distinción visual pendiente/completada */
}

.panel-item-actions {
  display: flex;
  gap: 4px;
  flex: none;
}

.panel-item-btn {
  border: none;
  background: transparent;
  color: var(--text-secondary);
  border-radius: 6px;
  width: 26px;
  height: 26px;
  transition: background-color 150ms, color 150ms;
}

.panel-item-btn:hover {
  background-color: var(--bg-hover);
  color: var(--text-primary);
}

.panel-item-btn-danger:hover {
  background-color: var(--danger);
  color: #ffffff;
}

.panel-empty {
  padding: 24px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-secondary);
}
```

`index.html` gana `<link rel="stylesheet" href="css/panels.css">` junto a los demás `<link>` de CSS.

---

## 9. Tipografía Inter — de dónde salen los `.woff2` (CA-26..CA-30)

### 9.1 Mecanismo de obtención — verificado en vivo, no asumido

Inter es software libre, licencia **SIL Open Font License 1.1**. Se verificó en esta sesión, contra
la API real de GitHub (no se asume el nombre del asset ni la versión):

- Repositorio oficial: `rsms/inter`. Release más reciente: **`v4.1`**.
- Asset único del release: `Inter-4.1.zip`, descargable de
  `https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip` (33.7 MB) — confirmado vía
  `GET https://api.github.com/repos/rsms/inter/releases/latest`.
- Licencia: `https://raw.githubusercontent.com/rsms/inter/v4.1/LICENSE.txt` (SIL OFL 1.1) —
  confirmado en la página oficial `rsms.me/inter`.
- Nombres de archivo exactos de los 3 pesos estáticos que pide CA-28, verificados contra la hoja de
  estilos real que usa el propio sitio de Inter (`rsms.me/inter/inter.css`, que enumera cada
  `@font-face` con su `src` literal):

  | Peso | Archivo |
  |------|---------|
  | 400 (Regular) | `Inter-Regular.woff2` |
  | 500 (Medium)  | `Inter-Medium.woff2` |
  | 700 (Bold)    | `Inter-Bold.woff2` |

**Procedimiento para `orion-dev` (una sola vez, en tiempo de build/dev — no en runtime, no toca la
CSP en absoluto):**

1. Descargar `Inter-4.1.zip` del asset URL de arriba.
2. Extraer el zip; localizar dentro los 3 archivos por su **nombre exacto** (`Inter-Regular.woff2`,
   `Inter-Medium.woff2`, `Inter-Bold.woff2`) — la distribución oficial de Inter organiza el zip en
   varias carpetas por formato (desktop, web, variable, hinted-Windows); el nombre de archivo es único
   dentro del zip, así que una búsqueda recursiva por esos 3 nombres literales los ubica sin ambigüedad
   sin depender de memorizar la estructura interna exacta de carpetas (que puede variar levemente
   entre versiones del release).
3. Copiar los 3 archivos a `ui/webview/frontend/fonts/`, sin renombrar.
4. Copiar también el `LICENSE.txt` del zip (o descargarlo de la URL de arriba) a
   `ui/webview/frontend/fonts/LICENSE-OFL.txt` — vendorizar el binario de una fuente OFL sin su
   licencia adjunta es una omisión de cumplimiento, no solo prolijidad.
5. Verificar que los 3 archivos sean binarios `.woff2` reales (no HTML de una página de error de
   descarga fallida) antes de commitear — un `file ui/webview/frontend/fonts/*.woff2` o equivalente
   debe reportar `Web Open Font Format`.

Esta descarga es una acción de un único momento, ejecutada por quien implementa (`orion-dev`), igual
que se instalaría cualquier asset estático de terceros — no es una dependencia de `requirements.txt`
(no es Python) ni una dependencia de runtime (el `@font-face` de CA-26 apunta a la copia local, nunca
a GitHub). Si el entorno de `orion-dev` no tiene acceso de red en el momento de implementar, la
alternativa es que el humano (Johan) provea los 3 archivos ya descargados — de cualquier fuente que
preserve los nombres/pesos exactos de arriba, dado que Inter es de descarga pública libre — y
`orion-dev` los coloque directamente en `fonts/`, saltándose el paso de descarga pero sin cambiar
nada del resto del diseño.

### 9.2 `@font-face` y `font-family` (CA-26, CA-27, CA-28)

`ui/webview/frontend/css/fonts.css` (nuevo):

```css
/* ui/webview/frontend/css/fonts.css
   REQ-016/CA-26..CA-28 — Inter vendorizada localmente (SIL OFL 1.1, ver fonts/LICENSE-OFL.txt).
   Rutas relativas, sin ningún <link>/@import a un CDN externo — cumple la CSP actual
   (default-src 'self') sin modificarla. */

@font-face {
  font-family: "Inter";
  src: url("../fonts/Inter-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: "Inter";
  src: url("../fonts/Inter-Medium.woff2") format("woff2");
  font-weight: 500;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: "Inter";
  src: url("../fonts/Inter-Bold.woff2") format("woff2");
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}
```

`index.html` gana `<link rel="stylesheet" href="css/fonts.css">` (antes de `reset.css`, aunque el
orden no es estrictamente necesario — `@font-face` se registra globalmente sin importar el orden de
hojas de estilo).

`css/reset.css` línea 18 — único cambio de esta sección en el archivo, todo lo demás igual:

```css
body {
  font-family: "Inter", -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  ...
}
```

`font-display: swap` es lo que satisface literalmente el caso borde de SPEC-016 ("el archivo de
fuente Inter no carga... el fallback del stack de sistema sigue siendo legible, la app no rompe
visualmente ni deja texto invisible"): `swap` le dice al navegador que pinte con el fallback
INMEDIATAMENTE y solo reemplace por Inter cuando (y si) el `.woff2` termina de cargar — nunca hay una
ventana de texto invisible (FOIT), a diferencia del valor por defecto (`font-display: auto`, que sí
puede ocultar texto brevemente).

### 9.3 Por qué CA-30 (contraste WCAG AA) no se reabre

CA-36 de SPEC-015 (ya auditado) evalúa pares **color de texto / color de fondo** — un cambio de
`font-family` no toca ni un solo valor de `--text-primary`/`--text-secondary`/`--bg-*`/etc. en
`theme.css` (§2, "Sin modificar"). El contraste de color es independiente de qué tipografía dibuja los
glifos; lo único que un cambio de fuente podría afectar es la legibilidad en tamaños muy pequeños, no
medida por WCAG AA de contraste. Riesgo residual (no de contraste, sino de legibilidad): Inter a
`font-size: 11px` (`.conv-meta`, `.panel-item-meta`) podría verse levemente distinto a la fuente de
sistema actual — se deja como validación visual manual del gate humano (Johan), no bloquea la
arquitectura.

---

## 10. Inserción segura en el DOM — extensión de §10.1 de arquitectura-015.md

**Misma regla, sin excepciones nuevas:** cualquier campo recibido desde Python que no esté
documentado en §5 de esta propuesta (ni en §4.2 de arquitectura-015.md) como `html` ya sanitizado
(`render_markdown()` + `bleach`) se inserta en el DOM **exclusivamente** vía `element.textContent` o
`element.setAttribute()` — nunca `innerHTML`, `insertAdjacentHTML`, ni interpolación en un template
string que luego se asigne a `innerHTML`.

Esta regla ya aplicaba a `sidebar.js`/`composer.js`/`confirm_modal.js` (arquitectura-015.md §10.1) y
se extiende, sin modificarse, a los **2 archivos JS nuevos** de este REQ:

| Archivo | Campos no confiables que inserta | Cómo |
|---|---|---|
| `js/tasks_panel.js` | `task.title` (texto libre escrito por el usuario, CA-06), `task.due_date` | `titleEl.textContent = task.title` / `dateEl.textContent = task.due_date` — cada uno sobre un nodo dedicado creado con `document.createElement`, nunca interpolado en el HTML del `.panel-item` completo. |
| `js/projects_panel.js` | `project.name` (texto libre, CA-14), `conv.title` (ya protegido en `sidebar.js`, reutilizado acá) | `nameEl.textContent = project.name` / `titleEl.textContent = conv.title` — mismo criterio, nodo dedicado por campo. |

Todo texto **propio** de estos 2 archivos ("Tareas", "Proyectos", "No hay tareas todavía.", "Elegí
una conversación", etc.) es literal fijo en el código fuente JS — no viene de Python ni del usuario,
así que no le aplica esta regla (mismo criterio ya usado por `confirm_modal.js` para su propio
"Confirmación requerida").

`js/sidebar.js` no gana ningún campo nuevo no confiable — `getLoadedConversations()` solo reexpone
`conv.title`, que ya pasaba por `textContent` en `buildConversationItem()` desde REQ-015; el picker de
`projects_panel.js` (§8.4) vuelve a insertarlo vía `textContent` en su propio nodo, nunca reutiliza el
nodo DOM original ni copia HTML.

**Prueba estática (extiende la ya existente, no crea un mecanismo nuevo):**
`tests/test_webview_safe_dom_insertion.py::_MUST_NOT_USE_INNERHTML` pasa de
`["sidebar.js", "composer.js", "confirm_modal.js"]` a
`["sidebar.js", "composer.js", "confirm_modal.js", "tasks_panel.js", "projects_panel.js"]` — el mismo
grep estructural (`\.innerHTML\s*=|insertAdjacentHTML\s*\(`) que ya falla el build si aparece en
cualquiera de los archivos de la lista, ahora cubre también los 2 nuevos. El test
`test_ningun_otro_archivo_js_del_frontend_usa_innerhtml()` (que itera todos los `.js` del frontend
excepto `chat.js`) ya cubriría los 2 archivos nuevos automáticamente sin tocarlo — extender la lista
explícita es para que el mensaje de fallo sea específico por archivo, no solo el catch-all.

---

## 11. ¿Corresponde pasar por `orion-security` antes de `orion-dev`?

**Conclusión de esta sesión: NO es necesario un paso dedicado de `orion-security` para este REQ —
alcanza con que `orion-qa` lo revise dentro de su DoD estándar ("Seguridad revisada").** Motivo,
documentado explícitamente como pide el handoff (a validar/objetar por Johan en el gate):

`.claude/rules/skills.md`/la descripción del agente dice que `orion-security` "se invoca cuando un REQ
toca acciones destructivas, autenticación, manejo de secretos, o exposición de APIs". Tomado de forma
literal, `delete_task`/`delete_project` SÍ son acciones destructivas — el criterio no es "¿este REQ
toca algo destructivo?" (eso activaría un audit dedicado en casi cualquier REQ que agregue un botón de
borrar), sino **si el REQ introduce una superficie o un patrón de riesgo que todavía no fue evaluado**.
Con esa vara, los 2 puntos de este REQ que tocan seguridad son ambos **réplica mecánica de un patrón
ya auditado**, no una decisión de política nueva:

1. **`delete_task`/`delete_project` como YELLOW:** reutilizan, byte a byte, el mismo mecanismo que
   `security-audit-015.md` (Hallazgo C) ya evaluó a fondo para `delete_conversation` —
   `security_manager.require_confirmation()` → `WebViewConfirmationAdapter` (sin cambios, §2) → mismo
   modal genérico. No se agrega un segundo adaptador, no se agrega un bypass, no se cambia
   `CHANNEL_ALLOWED_LEVELS` ni `_DETAILS_ALLOWED_KEYS`. Es la misma clase de riesgo
   ("`@pyqtSlot` invocable desde cualquier script de la página, no solo desde el botón visible") que
   ya motivó la reclasificación YELLOW de `delete_conversation`, aplicada a 2 acciones más con el
   mismo remedio ya probado.
2. **Datos nuevos de "proyecto" en SQLite:** nombre elegido por el usuario + referencias a
   `conversation_id` — sin credenciales, tokens, PII más allá de lo que `memories` ya almacena, ni
   escritura fuera de `ai/unified_memory.db` (mismo archivo, mismos permisos de sistema de archivos ya
   existentes). Todas las queries nuevas son parametrizadas (`?`, nunca f-string/concatenación) — cero
   superficie de inyección SQL nueva, mismo patrón que el resto del archivo.

El único punto genuinamente nuevo (no una réplica) es la extensión de la regla de inserción segura en
el DOM a 2 archivos JS más (§10) — pero es una **aplicación mecánica de una regla ya definida** por
`orion-security` en REQ-015 (§10.1 de arquitectura-015.md), no un juicio de seguridad nuevo: la regla
ya existe, ya tiene su test estructural, y este REQ solo la extiende a 2 archivos que siguen el mismo
molde exacto que los 3 ya cubiertos.

**Recomendación concreta:** que `orion-qa` verifique explícitamente estos 3 puntos (clasificación
YELLOW correcta + gate de confirmación real, cero SQL sin parametrizar, los 2 archivos JS nuevos
pasan el test de §10) como parte de su DoD normal, sin un agente `orion-security` dedicado. Si Johan
prefiere el rigor adicional de una auditoría dedicada de todas formas (por ejemplo, por tratarse de
la primera vez que se agregan 2 acciones YELLOW nuevas en un mismo REQ, o por preferencia general de
proceso), este REQ puede pausarse en el gate de aprobación de esta arquitectura para insertar
`orion-security` antes de `orion-dev` — no hay ningún costo de rediseño en hacerlo, la propuesta no
cambia si se decide agregar ese paso.

---

## 12. Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| `project_id` es un entero autoincremental chico, adivinable (a diferencia de `conversation_id`, uuid4) — un script en la página podría intentar `assign_conversation_to_project()`/`request_delete_project()` con un `project_id` de otro contexto hipotético multiusuario futuro. | Hoy el sistema es de un único usuario (`user_id="default"` fijo en todo el bridge) — no hay otro usuario real del que defenderse todavía. Aun así, `assign_conversation_to_project()` verifica `user_id` tanto del proyecto como de la conversación antes de escribir (§4.2), y `delete_project()`/`unassign_conversation_from_project()` filtran por `user_id` en el `WHERE` — mismo criterio defensivo que ya usa `delete_conversation()`, aplicado de entrada, no como parche futuro. |
| Asimetría de huérfanos entre `list_projects()` (conteo) y `list_conversations_by_project()` (detalle, con `INNER JOIN`) — si por algún motivo excepcional quedara una fila huérfana en `project_conversations` (la limpieza activa de §4.3 falla o un caller futuro bypassea el bridge), `conversation_count` en el listado maestro podría mostrar 1 de más aunque la vista de detalle ya la excluya correctamente. | Severidad baja: es un desvío cosmético de un contador, nunca una filtración de datos ni un crash — la conversación fantasma nunca se renderiza en ningún lado (§4.2/§4.3). Mitigado en la práctica por la limpieza activa (único call-site real, confirmado por grep). Si se vuelve un problema real más adelante, `list_projects()` puede migrar a la misma técnica de `INNER JOIN` que ya usa `list_conversations_by_project()` — cambio aislado, sin impacto en el resto del diseño. |
| Working tree compartido con el diff de REQ-015 sin commitear (riesgo heredado, ya registrado en el contexto por `orion-baseline`) — cualquier `git diff`/`git status` durante la implementación de REQ-016 sigue mezclando ambos REQs. | Sin mitigación técnica de este REQ — depende de que Johan decida el orden de commits antes de que `orion-dev` empiece (ya señalado como pendiente en el contexto). |
| `tasks/task_scheduler.py::_notify_local()` línea 158 tiene un `except Exception: pass` silencioso, preexistente — hallazgo colateral de esta sesión, fuera del alcance de REQ-016 (SPEC-016 exige explícitamente no modificar `task_scheduler.py`). | No se corrige en este REQ — modificar ese archivo excedería lo aprobado en la SPEC. Queda documentado acá para que un REQ futuro de limpieza técnica (o `orion-qa` de este mismo REQ, si lo considera bloqueante) lo tenga registrado; no bloquea esta arquitectura porque no es un archivo que REQ-016 toque. |
| CA-10 activa el scheduler también para tareas `channel="telegram"` preexistentes — si la app de escritorio está abierta cuando una de esas tareas vence, ahora también suena una notificación local (TTS + Toast) además de/en vez del mensaje de Telegram, un comportamiento que Johan no pidió explícitamente. | Es un efecto colateral inevitable de la lógica ya existente de `_send_notification()` (línea 151, sin tocar por este REQ) al activar el scheduler en un contexto nuevo — no un bug introducido. Se documenta explícitamente en §7 y acá para que Johan lo conozca antes de aprobar; si lo considera indeseable, ajustar esa condición es un cambio de una línea en `tasks/task_scheduler.py`, pero eso reabriría un archivo que la SPEC actual marca como "sin modificar" — requeriría su visto bueno explícito primero. |
| El picker de asignación a proyecto (§8.4) depende de que `sidebar.js` ya haya cargado conversaciones antes de abrir el panel de Proyectos — si el usuario abre "Proyectos" antes de que `conversation_list_updated` llegue por primera vez, el picker se mostraría vacío. | Bajo impacto: `request_initial_state()` (línea 145 de `bridge.py`) ya dispara la carga de conversaciones apenas arranca la app, antes de que el usuario pueda interactuar con nada — en la práctica la lista ya está poblada para cuando alguien llega a abrir "Proyectos". Caso borde aceptable, no requiere un mecanismo de espera adicional. |
| Dos tablas nuevas en `ai/unified_memory.db` sin ninguna migración de "baja" (no hay `DROP TABLE` si se necesitara revertir el REQ) — si Johan pidiera deshacer REQ-016 después de haberlo usado, los datos de proyectos quedarían huérfanos en el archivo de DB aunque el código se revierta. | Mismo criterio que ya usa todo el proyecto para migraciones aditivas (`_migrate_schema()` de REQ-013 tampoco tiene reversa) — no es un patrón nuevo de este REQ. Si hiciera falta revertir, `DROP TABLE IF EXISTS projects, project_conversations` es una operación manual de una línea, documentable en el momento si llegara a pedirse. |

---

## 13. Dependencias nuevas

**Ninguna dependencia Python nueva.** `requirements.txt` no se toca — todo lo que este REQ usa
(`sqlite3`, `json`, `dataclasses`, `PyQt6.QtCore`) ya está importado en los módulos que se modifican.

**Inter (`.woff2`) es un asset estático, no una dependencia de código** — no se instala vía `pip`, no
aparece en ningún manifiesto de dependencias; se vendoriza como archivo binario dentro del repo (§9),
igual que `vendor/qwebchannel.js` ya vendorizado por REQ-015. Se documenta acá únicamente porque el
handoff pidió una respuesta explícita, no porque genere una entrada nueva en `requirements.txt`.

---

## 14. Pruebas sugeridas (una por bloque de CA, agrupadas por archivo)

### `tests/test_memory_manager_projects.py` (nuevo) — CA-14..CA-21

Mismo patrón exacto de fixture que `tests/test_memory_manager_delete_conversation.py`
(`isolated_memory_db`: `DB_PATH` redirigido a `tmp_path`, `_get_embedding` mockeado, sin red):

- `test_create_project_devuelve_id_y_lo_lista` — CA-14, CA-15.
- `test_create_project_rechaza_nombre_vacio_o_solo_espacios` — CA-14, caso borde.
- `test_create_project_permite_nombres_duplicados` — caso borde explícito de SPEC-016.
- `test_assign_conversation_to_project_reasigna_sin_duplicar` — CA-16, CA-20: asignar dos veces (a
  proyectos distintos) deja la conversación solo en el último.
- `test_assign_conversation_to_project_rechaza_project_id_de_otro_user_id` — defensa en profundidad
  de §12.
- `test_assign_conversation_to_project_rechaza_conversation_id_inexistente` — caso borde.
- `test_unassign_conversation_from_project_es_idempotente` — CA-16, no lanza sobre una conversación
  sin proyecto asignado.
- `test_list_conversations_by_project_excluye_huerfanos_via_inner_join` — inserta una fila cruda en
  `project_conversations` sin fila correspondiente en `memories`, confirma que no aparece en el
  resultado (§4.2/§4.3, la defensa pasiva).
- `test_delete_project_no_borra_conversaciones` — CA-19: crea proyecto, asigna conversación, borra
  proyecto, confirma que `memories` sigue teniendo las filas de esa conversación intactas.
- `test_delete_project_borra_sus_asignaciones` — CA-19: confirma que `project_conversations` queda
  sin filas de ese `project_id` tras borrar.
- **No-regresión de CA-21 (la prueba más importante de este archivo):**
  `test_new_conversation_id_store_turn_list_conversations_get_conversation_turns_delete_conversation_sin_cambios`
  — ejecuta las 5 funciones protegidas exactamente como ya las prueban los tests existentes de
  REQ-013/REQ-015 (mismos casos, mismos asserts), confirmando que agregar el esquema de proyectos no
  altera ni un resultado.
- `test_delete_conversation_no_limpia_project_conversations_por_si_sola` — confirma explícitamente que
  `ai/memory_manager.py::delete_conversation()` NO toca `project_conversations` (la limpieza vive en
  el bridge, §4.3) — evita que un futuro refactor mueva silenciosamente esa responsabilidad sin que un
  test lo note.

### `tests/test_webview_bridge.py` (extendido) — CA-05..CA-21, CA-33

Mismas fixtures ya existentes (`fake_run_async`, `bridge`) — se agregan casos nuevos, sin tocar los
existentes:

- `test_request_tasks_llama_list_all_tasks_y_emite_tasks_loaded` — CA-05, CA-09 (orden intacto, se
  serializa tal cual).
- `test_request_tasks_no_se_llama_en_request_initial_state` — CA-12: inspecciona que
  `request_initial_state()` no dispare `list_all_tasks`.
- `test_create_task_con_titulo_vacio_no_llama_a_task_manager` — CA-06, guard server-side.
- `test_create_task_pasa_channel_desktop_sin_modificar_create_task` — CA-06, CA-11.
- `test_complete_task_no_pide_confirmacion` — CA-07 (a diferencia de `delete_task`).
- `test_request_delete_task_pide_confirmacion_antes_de_delete_task` — CA-08, CA-33: mockea
  `security_manager.require_confirmation` devolviendo `False` primero (confirma que
  `task_manager.delete_task` NUNCA se llama) y `True` después (confirma que sí se llama).
- `test_request_delete_task_usa_action_name_delete_task` — CA-33: verifica el string literal pasado a
  `require_confirmation()`.
- Los mismos 7 casos replicados para `request_projects`/`create_project`/
  `assign_conversation_to_project`/`unassign_conversation_from_project`/
  `request_project_conversations`/`request_delete_project` — CA-13..CA-21.
- `test_request_project_conversations_incluye_project_id_en_la_señal` — CA-17, caso borde de doble
  click entre proyectos (confirma que `project_conversations_loaded` lleva el `project_id` recibido).
- `test_request_delete_project_emite_project_removed_solo_si_delete_project_devuelve_true` — CA-18,
  CA-19.

### `tests/test_security_manager.py` (extendido) — CA-08, CA-18, CA-33

Mismo patrón que el test ya existente para `delete_conversation`:

- `test_delete_task_esta_clasificada_como_yellow`.
- `test_delete_project_esta_clasificada_como_yellow`.
- `test_delete_task_requiere_confirmacion_en_canal_desktop` / `test_delete_project_requiere_confirmacion_en_canal_desktop`
  — vía `require_confirmation()` con un adaptador mockeado, confirma que sin confirmar no retorna
  `True`.
- `test_check_coverage_no_reporta_delete_task_ni_delete_project_como_sin_clasificar` — reutiliza
  `check_coverage()` ya existente para detectar acciones nuevas sin registrar (regresión-guard barata).

### `tests/test_webview_safe_dom_insertion.py` (extendido) — §10

- Parametrización existente (`_MUST_NOT_USE_INNERHTML`) extendida con `tasks_panel.js` y
  `projects_panel.js` — corre automáticamente los 2 tests ya existentes
  (`test_archivo_no_usa_innerhtml_ni_insertadjacenthtml`, `test_archivo_usa_textcontent_para_insertar_texto`)
  sobre los 2 archivos nuevos, sin escribir tests nuevos.

### Frontend/CSS — verificación manual del gate humano (no automatizable con las herramientas actuales del repo)

- CA-01, CA-02, CA-22, CA-23, CA-24, CA-28, CA-30 (legibilidad a 11px): validación visual directa por
  Johan en la app real, mismo criterio ya usado para los CA visuales de SPEC-015 que no tienen
  cobertura de `tests/test_webview_smoke.py`.

### Compilación y regresión general — CA-31, CA-32

- `python -m py_compile ai/memory_manager.py ui/webview/bridge.py core/security_manager.py main.py`
  — CA-31.
- `python -m pytest tests/ --tb=short -q` completo — CA-32: se espera el mismo conteo base de
  `orion-baseline` (365 passed) más los tests nuevos de este REQ, con los 2 mismos `FAIL` preexistentes
  de `test_llm_provider.py` (`anthropic` no instalado) sin cambios ni nuevos fallos.

---

## 15. Resumen para el humano (Johan) — puntos que requieren su validación explícita

Esta arquitectura toma varias decisiones de diseño donde la SPEC dejaba el mecanismo exacto a
criterio técnico (marcado ASUMIDO en SPEC-016 o decidido acá por primera vez, §0). Se listan todas
juntas para que el gate de aprobación sea concreto:

1. **Esquema de datos:** 2 tablas nuevas (`projects`, `project_conversations`) en la misma DB, sin
   tocar `memories` — §0.1, §4.
2. **Mecanismo de asignación de conversación a proyecto:** desde el panel de Proyectos (picker), no un
   ícono nuevo en cada conversación del sidebar — §0.2, §8.4. Si Johan prefiere el ícono por fila, es
   un cambio de UI acotado sin impacto en el esquema de datos ni en el bridge.
3. **Tareas/Proyectos como modales**, no paneles embebidos en el sidebar — §0.3.
4. **Descarga puntual del `.zip` oficial de Inter (GitHub, v4.1, SIL OFL 1.1)** como mecanismo para
   obtener los `.woff2` — §0.5, §9.1. Verificado en vivo, no asumido.
5. **`task_scheduler.start()` también activa notificaciones locales para tareas creadas por Telegram**
   cuando la app de escritorio está abierta — efecto colateral inevitable de código ya existente sin
   modificar, no algo que Johan pidió — §7, §12.
6. **Recomendación de NO pasar por `orion-security` como paso dedicado** — se apoya en que los 2
   puntos de seguridad de este REQ son réplica mecánica de un patrón ya auditado en REQ-015, no una
   decisión de política nueva — §11. Johan puede pedir el paso dedicado igual si prefiere el rigor
   adicional, sin costo de rediseño.

---

**Fin de la propuesta.** Cobertura completa de los 34 CA de SPEC-016 (§1). DoD de `orion-architect`
cumplido: cada CA referenciado, módulos/clases/funciones especificados con firma exacta, flujo de
datos documentado, dependencias nuevas identificadas (ninguna Python; Inter como asset estático),
riesgos con mitigación, pruebas sugeridas por bloque. **Pendiente de aprobación humana explícita antes
de continuar el flujo — no se actualiza el CSV ni se hace handoff a `orion-dev` hasta recibir
APROBADO / AJUSTAR [qué] / RECHAZADO [motivo] de Johan.**

