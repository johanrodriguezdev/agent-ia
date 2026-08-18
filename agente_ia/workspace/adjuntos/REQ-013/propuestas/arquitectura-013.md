# Arquitectura REQ-013 — Rediseño UI escritorio NODDOO estilo chat de IA

**Fecha:** 2026-08-17
**Agente:** orion-architect
**Estado:** ✅ COMPLETADO — Aprobado por Johan (2026-08-17), sin ajustes
**Base:** `spec/SPEC-013.md` (22 criterios, aprobada 2026-08-17) + `origen/baseline-013.md`

## Aprobación humana

**APROBADO por Johan — 2026-08-17, sin ajustes.**

Puntos señalados en la presentación de la propuesta y su resolución:

1. **Ubicación del `VoiceOrb` — CONFIRMADO EXPLÍCITAMENTE.** El orbe vive **solo en el bloque de
   estado vacío** de `CenterPanel`, no de forma permanente. CA-16 se satisface con
   `HeaderBar._mode_pill` (indicador siempre visible de los 4 estados) más el toggle de manos libres
   mudado tal cual al `Composer`. `orion-dev` y `orion-tester` deben tratar esto como decisión
   cerrada, no reabrirla.
2. **Comandos de CLI/voz fuera del sidebar** — se mantiene tal como se propuso (§3.4).
3. **Resultado de los chips de acción sin burbuja ni persistencia** — se mantiene (§4.5).
4. **`orion-dev` parte del working tree sucio actual, no de HEAD** — se mantiene (§6, riesgo 12).

---

## 0. Resumen de la propuesta en una pantalla

Tres bloques independientes, en este orden de implementación:

1. **Sistema de tema** (`ui/theme.py` nuevo + `config_manager.py`): un único punto de paleta
   (`Palette` congelada, `LIGHT_PALETTE` / `DARK_PALETTE`), un `ThemeManager` singleton con señal
   `theme_changed`, y QSS por widget generado desde plantillas `string.Template`. Todo widget con
   estilo propio expone `apply_theme(palette)`.
2. **Persistencia conversacional** (`ai/memory_manager.py`): dos columnas nuevas **aditivas** en la
   tabla `memories` (`conversation_id`, `role`) vía `ALTER TABLE` idempotente, más
   `store_turn()`, `list_conversations()`, `get_conversation_turns()`, `new_conversation_id()`.
   Sin tabla `conversations` (el listado se **deriva** por agregación). Sin backfill de filas legacy.
3. **Layout de chat** (`ui/widgets/`): 4 widgets nuevos (`ChatBubble`, `ChatFeed`, `Composer`,
   `ConversationList`), `CenterPanel` se convierte en compositor delgado conservando su API pública,
   `Sidebar` hospeda el listado funcional, `HeaderBar` hospeda el selector de tema.

**Dependencias nuevas: ninguna.** Todo es PyQt6 + stdlib (`uuid`, `sqlite3`, `string`, `dataclasses`).

**Nivel de seguridad (`.claude/rules/security-levels.md`): 🟢 Verde en su totalidad.** No hay acción
destructiva nueva; los chips de acceso directo pasan por el gate fail-closed existente
(`execute_action(..., channel=ChannelType.DESKTOP)`, CA-19). No requiere pasada por `orion-security`.

---

## 1. Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|----------------------------------|
| **CA-01** Selector de tema en header, aplicación en caliente | `HeaderBar._theme_toggle` (QPushButton checkable ☀/🌙) llama `theme_manager.set_theme()`. `ThemeManager.theme_changed(Palette)` está conectada al `apply_theme()` de cada widget con estilo propio (registro vía `ui/theme.py:register_themed()`), que hace `setStyleSheet(_qss(palette))` + `unpolish/polish`. Sin reinicio y sin reconstruir widgets. |
| **CA-02** Persistencia del tema | `config_manager.get_ui_theme()` / `set_ui_theme()` siguiendo el patrón `get_weather_city`/`set_weather_city`; clave `ui_theme` en `DEFAULT_CONFIG` + fallback en `load_config()`. `JarvisMainWindow.__init__` llama `theme_manager.load_from_config()` **antes** de construir widgets. |
| **CA-03** Paleta claro y oscuro con contraste legible | `ui/theme.py` define los tokens de ambos modos con valores hex concretos (§3.1). Todos los pares texto/fondo del layout apuntan a ≥ 4.5:1 WCAG AA; verificable programáticamente (§8, `test_palette_contrast_ratios`). |
| **CA-04 / CA-21** Panel derecho respeta el tema | `RightPanel` y sus 4 tarjetas migran su QSS constante a `_qss(palette)` + `apply_theme()`, y se registran en el `ThemeManager` igual que el resto. Ningún cambio funcional en las tarjetas. |
| **CA-05** Listado ordenado por última actividad | `ConversationList.set_conversations()` alimentado por `memory.list_conversations(user_id, limit, offset)`, cuya query hace `GROUP BY conversation_id ORDER BY MAX(timestamp) DESC`. |
| **CA-06** Click carga los turnos y marca activa | `ConversationList.conversation_selected(str)` → `Sidebar` la re-emite → `JarvisMainWindow._on_conversation_selected()` → `run_async(memory.get_conversation_turns, ...)` → `CenterPanel.load_turns()` + `Sidebar.set_active_conversation(cid)`. |
| **CA-07** "Nueva conversación" limpia el feed sin borrar nada | `ConversationList.new_conversation_requested()` → `JarvisMainWindow._on_new_conversation()`: `self._conversation_id = None` + `CenterPanel.clear_feed()`. No se ejecuta ningún DELETE. El id nuevo se acuña recién con el primer mensaje (§4.3). |
| **CA-08** Ítems placeholder se conservan deshabilitados | `_NAV_ITEMS` de `sidebar.py` se mantiene íntegro; solo `("conversaciones", …)` pasa a `enabled=True`. Los 5 restantes (memoria, tareas, archivos, aplicaciones, configuración) siguen `setEnabled(False)` sin handler. |
| **CA-09** Se persisten usuario y respuesta con `conversation_id` común | `memory.store_turn(user_text, assistant_text, conversation_id, …)` escribe **dos filas** con el mismo `conversation_id` y `role` `"user"` / `"assistant"`. Invocado desde `_on_command_done` vía `run_async` (fuera del hilo GUI). |
| **CA-10** Función de listado | `UnifiedMemory.list_conversations(user_id="default", limit=30, offset=0) -> List[ConversationSummary]` — `(conversation_id, title, last_activity, turn_count)`. Título derivado del primer mensaje `role='user'`, truncado a 60 chars. |
| **CA-11** Función de turnos en orden cronológico | `UnifiedMemory.get_conversation_turns(conversation_id, user_id="default", limit=200) -> List[MemoryItem]`, ordenados por `id ASC` (monotónico e inmune a colisiones de timestamp del mismo segundo, a diferencia de `ORDER BY timestamp`). |
| **CA-12** Filas legacy no rompen listado ni arranque | Migración **aditiva** (`ALTER TABLE ADD COLUMN` nullable, idempotente vía `PRAGMA table_info`) — las filas viejas quedan con `conversation_id IS NULL`. Todas las queries de conversación filtran `conversation_id IS NOT NULL`, así que las legacy son invisibles al sidebar pero siguen intactas para `get_recent`, `search_semantic` y `consolidate`. Sin backfill ni reescritura de datos (§3.2). |
| **CA-13** Burbuja de usuario inmediata y distinguible | `JarvisMainWindow._handle_command()` llama `CenterPanel.add_user_message(text)` **antes** de disparar `run_async(resolve, …)`. La burbuja usa propiedad dinámica `role="user"` (alineada a la derecha, fondo `accent`). |
| **CA-14** Burbuja de IA separada | `CenterPanel.show_response(text)` (misma firma pública de hoy) pasa a hacer `self._feed.add_message(text, "assistant")` — texto completo, sin truncar a 200 chars, sin pisar la respuesta anterior. |
| **CA-15** Feed scrolleable con autoscroll | `ChatFeed(QScrollArea)` con `widgetResizable=True`; autoscroll al añadir mediante `verticalScrollBar().rangeChanged` + flag `_autoscroll_pending` (no basta con setear `value` al añadir: el layout todavía no se recalculó). Respeta el scroll manual del usuario (§4.2). |
| **CA-16** Indicador de estado y toggle manos libres visibles y funcionales | El indicador siempre visible de los 4 estados es `HeaderBar._mode_pill` (ya existente, ya alimentado por `_poll_state`), reforzado por `HeaderBar._wake_indicator`. El `VoiceOrb` se conserva íntegro dentro del bloque de estado vacío de `CenterPanel`. El toggle de manos libres se muda tal cual (mismo `objectName`, misma señal, mismo guard `_updating_wake_toggle`) al `Composer`. |
| **CA-17** Composer funcionalmente equivalente | `Composer` re-emite `command_submitted(str)`; `CenterPanel` la reexpone con la misma firma; `JarvisMainWindow._handle_command` sigue llamando `run_async(resolve, …, ChannelType.DESKTOP, user_id="default")` sin cambios. |
| **CA-18** Fila de chips con al menos una plantilla y un acceso directo | `composer.py:_CHIPS` implementa las 5 entradas aprobadas en SPEC-013 (3 plantillas + 2 accesos directos), dentro de un `QScrollArea` horizontal sobre el input. |
| **CA-19** Accesos directos vía `run_async(execute_action, …, DESKTOP)` | `Composer._run_action()` es copia literal del patrón de `QuickActionsCard._run_action()` — nunca importa ni llama la función subyacente. |
| **CA-20** Panel derecho coexiste | `JarvisMainWindow._init_ui` conserva el `QHBoxLayout` de 3 columnas: `Sidebar(280)` — columna central (`HeaderBar` + `CenterPanel`, stretch=1) — `RightPanel(350)`. El rediseño ocurre **dentro** de la columna central. |
| **CA-22** Regresión | El nombre de clase, el archivo y la API pública de `CenterPanel` (`command_submitted`, `hands_free_toggled`, `set_state`, `set_wake_state`, `show_response`) se conservan; `_greeting_label`, `_greeting_timer`, `_refresh_greeting`, `_display_name` y `_resolve_display_name` **no se mueven de `center_panel.py`** — los 4 tests de REQ-012 quedan intactos (§7). Único cambio de contrato documentado: `RecentActivityCard` pasa a filtrar por rol (§3.4). |

---

## 2. Estructura visual resultante

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ Sidebar (280)          │ HeaderBar        [☀/🌙] [〜 Modo] [🎙] [🔔]  │ RightPanel│
│ ─────────────────────  ├──────────────────────────────────────────────┤   (350)   │
│ NODDOO                 │                                              │ ┌───────┐ │
│ 🏠 Inicio              │        (bloque de estado vacío)              │ │Estado │ │
│ 💬 Conversaciones ✅   │            🤖  (avatar placeholder)          │ │sistema│ │
│ 🧠 Memoria      (dis)  │         Buenas tardes, Johan                 │ └───────┘ │
│ ✅ Tareas       (dis)  │         ¿En qué puedo ayudarte hoy?          │ ┌───────┐ │
│ 📁 Archivos     (dis)  │             (VoiceOrb 220px)                 │ │Accesos│ │
│ 🔳 Aplicaciones (dis)  │                                              │ │rápidos│ │
│ ⚙️ Configuración(dis)  │  ── o, con conversación activa: ──           │ └───────┘ │
│ ─────────────────────  │   ChatFeed (QScrollArea)                     │ ┌───────┐ │
│ ＋ Nueva conversación  │     ┌──────────────────────────┐             │ │Activ. │ │
│ ┌───────────────────┐  │     │ burbuja assistant (izq)  │             │ │recient│ │
│ │ Resumen del día   │  │     └──────────────────────────┘             │ └───────┘ │
│ │ Clima en Bogotá   │  │              ┌─────────────────────────────┐ │ ┌───────┐ │
│ │ Abre el navegador │  │              │ burbuja user (der, accent)  │ │ │ Clima │ │
│ │ … (scroll)        │  │              └─────────────────────────────┘ │ └───────┘ │
│ │ [Ver más]         │  ├──────────────────────────────────────────────┤           │
│ └───────────────────┘  │ Composer                                     │           │
│ ● Sistema activo       │ [Resumen del día][Recuérdame][Investigación]… │           │
│ Todo funcionando       │ [ Escribe un comando…        ] [🎙] [➤]      │           │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Resolución de los **ASUMIDOS** de la SPEC:

- **Selector de tema:** confirmado en `HeaderBar`, a la **izquierda** de `_mode_pill` (no a la
  derecha del `_wake_indicator`), para que los tres indicadores de estado de voz queden agrupados y
  el control de preferencia quede separado de ellos.
- **Mascota/avatar de Nodo:** `QLabel` con emoji `🤖` a 56px dentro del bloque de estado vacío de
  `CenterPanel`, con `objectName("NodeAvatar")`. Se declara explícitamente como placeholder en el
  docstring del módulo, con la ruta de sustitución señalada (reemplazar el `QLabel` por un
  `QLabel` con `QPixmap` cuando exista el asset). Ningún archivo binario se agrega en este REQ.
- **Paginación del listado:** página de **30 conversaciones**, botón "Ver más" al pie que emite
  `more_requested()` y dispara `list_conversations(offset=len(actuales))`. El primer cargue ocurre
  vía `run_async` después de mostrar la ventana, así que cientos de conversaciones no degradan el
  arranque (caso borde de la SPEC).
- **Migración de filas legacy:** §3.2.

---

## 3. Bloque 1 y 2 — tema y persistencia

### 3.1 `ui/theme.py` (NUEVO) — punto único de paleta

```python
@dataclass(frozen=True)
class Palette:
    name: str
    bg_window: str
    bg_surface: str      # sidebar
    bg_elevated: str     # tarjetas, burbuja assistant
    bg_input: str
    bg_hover: str
    border: str
    border_subtle: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_disabled: str
    accent: str
    accent_soft: str     # fondos tintados (rgba-like en hex sólido)
    on_accent: str       # texto sobre accent (burbuja de usuario)
    success: str
    warning: str
    danger: str
    bubble_user_bg: str
    bubble_user_fg: str
    bubble_ai_bg: str
    bubble_ai_fg: str
    scroll_handle: str
    orb_colors: Dict[str, Dict[str, tuple]]   # 4 estados x core/glow/ring
```

**Valores concretos.** El modo oscuro reproduce exactamente los colores que hoy están dispersos por
los 10+ archivos, para que activar el tema oscuro después del REQ se vea idéntico a hoy y cualquier
diferencia visual sea señal de un token mal cableado.

| Token | 🌙 dark | ☀ light |
|-------|---------|---------|
| `bg_window` | `#070b14` | `#f4f6fa` |
| `bg_surface` | `#0d1220` | `#ffffff` |
| `bg_elevated` | `#111a2c` | `#ffffff` |
| `bg_input` | `#10182a` | `#ffffff` |
| `bg_hover` | `#14203a` | `#eef2f8` |
| `border` | `#1e2a42` | `#d7dee9` |
| `border_subtle` | `#1a2333` | `#e6ebf2` |
| `text_primary` | `#ffffff` | `#101828` |
| `text_secondary` | `#8a93a6` | `#4d5769` |
| `text_muted` | `#5a6478` | `#6d7889` |
| `text_disabled` | `#555f73` | `#a6b0bf` |
| `accent` | `#4fc3ff` | `#0b6fbf` |
| `accent_soft` | `#132a3f` | `#e4f0fb` |
| `on_accent` | `#06121f` | `#ffffff` |
| `success` | `#33d17a` | `#1a7f43` |
| `warning` | `#ffb84d` | `#9a5b00` |
| `danger` | `#ff6b6b` | `#b3261e` |
| `bubble_user_bg` | `#1b4a6e` | `#0b6fbf` |
| `bubble_user_fg` | `#eaf6ff` | `#ffffff` |
| `bubble_ai_bg` | `#111a2c` | `#eef2f7` |
| `bubble_ai_fg` | `#e6eaf2` | `#101828` |
| `scroll_handle` | `#24304a` | `#c3cddb` |

> Nota para `orion-dev`: cualquier duda sobre si un valor concreto sirve se resuelve con el test de
> contraste de §8, no a ojo. Si un par no llega al umbral, se ajusta el hex y se anota el cambio en
> `desarrollo-log-013.md`.

`orb_colors` en modo oscuro son exactamente las 4 entradas actuales de
`voice_orb.py:_STATE_COLORS`. En modo claro se oscurecen los `core` y se reduce el alfa de `glow`
para que el orbe no se lave sobre fondo blanco:

```python
LIGHT_ORB = {
  "IDLE":       {"core": (11, 111, 191),  "glow": (11, 111, 191, 45),  "ring": (11, 111, 191, 170)},
  "LISTENING":  {"core": (0, 150, 120),   "glow": (0, 170, 140, 70),   "ring": (0, 120, 100, 200)},
  "PROCESSING": {"core": (124, 58, 179),  "glow": (124, 58, 179, 80),  "ring": (110, 40, 160, 220)},
  "RESPONDING": {"core": (30, 90, 190),   "glow": (60, 90, 200, 90),   "ring": (30, 70, 160, 230)},
}
```

**Contraste (CA-03).** Los pares que el test debe verificar con ≥ 4.5:1 (texto normal) o ≥ 3:1
(texto grande ≥ 24px y bordes de UI):

| Par | dark | light |
|-----|------|-------|
| `text_primary` / `bg_window` | ~18.9:1 | ~16.3:1 |
| `text_primary` / `bg_surface` | ~17.4:1 | ~17.5:1 |
| `text_secondary` / `bg_surface` | ~6.4:1 | ~7.9:1 |
| `text_muted` / `bg_elevated` | ~4.6:1 | ~4.6:1 |
| `accent` / `bg_input` | ~8.1:1 | ~5.1:1 |
| `bubble_user_fg` / `bubble_user_bg` | ~8.9:1 | ~5.9:1 |
| `bubble_ai_fg` / `bubble_ai_bg` | ~12.6:1 | ~15.4:1 |

Los valores de la tabla son la referencia de diseño; la **fuente de verdad es el test**
(§8, `test_palette_contrast_ratios`), que recalcula el ratio WCAG real y falla si algún par baja del
umbral. Si un par no llega, se ajusta el hex y se anota en `desarrollo-log-013.md` — no se relaja el
umbral del test.

#### `ThemeManager`

```python
THEMES: Dict[str, Palette] = {"dark": DARK_PALETTE, "light": LIGHT_PALETTE}
DEFAULT_THEME = "dark"

def resolve_theme_name(raw: str) -> str:
    """Normaliza un nombre de tema de origen no confiable (config.json) al catálogo."""
    name = (raw or "").strip().lower()
    if name not in THEMES:
        logger.warning("tema desconocido en config: %r — se usa %s", raw, DEFAULT_THEME)
        return DEFAULT_THEME
    return name

class ThemeManager(QObject):
    theme_changed = pyqtSignal(object)   # emite Palette

    def current_name(self) -> str: ...
    def palette(self) -> Palette: ...
    def load_from_config(self) -> None:      # lee config_manager.get_ui_theme() + resolve
    def set_theme(self, name: str) -> None:  # normaliza, persiste, emite (no-op si no cambió)
    def toggle(self) -> str: ...             # dark <-> light, devuelve el nuevo nombre

theme_manager = ThemeManager()   # singleton de módulo

def register_themed(widget) -> None:
    """Aplica la paleta actual al widget y lo suscribe a cambios futuros."""
    widget.apply_theme(theme_manager.palette())
    theme_manager.theme_changed.connect(widget.apply_theme)
```

Puntos de diseño que `orion-dev` **no** debe cambiar sin volver a arquitectura:

- **`string.Template`, no `str.format`.** El QSS está lleno de llaves `{ }`; `"...".format(**tokens)`
  reventaría con `KeyError`/`IndexError` en cada bloque de reglas. Cada módulo define su QSS como
  `_QSS_TEMPLATE = Template("""#Sidebar { background-color: $bg_surface; ... }""")` y su
  `_qss(palette) -> str` hace `_QSS_TEMPLATE.substitute(asdict(palette))` (con `orb_colors`
  excluido del dict de sustitución por no ser un string).
- **Los colores nunca vienen de `config.json`.** La preferencia solo elige cuál de las dos paletas
  constantes se usa; ningún valor de un archivo editable llega a `setStyleSheet()`. Esto cierra el
  vector de inyección de hoja de estilo vía `config.json` y es lo que hace este REQ 🟢 Verde.
- **`ChatBubble` NO se registra en `theme_changed`.** Se crean y destruyen a decenas por
  conversación; suscribir cada una dejaría cientos de conexiones vivas. Las burbujas se estilan por
  **herencia de QSS**: los selectores `#ChatBubble[role="user"] {...}` viven en el stylesheet de
  `ChatFeed`, que sí está registrado. Al cambiar el tema, Qt repinta los hijos automáticamente.
- `register_themed()` conecta un **bound method de un `QObject`**, que PyQt6 desconecta solo cuando
  el widget se destruye. No hace falta `disconnect()` manual.

Widgets que implementan `apply_theme(palette)` y se registran: `JarvisMainWindow`, `Sidebar`,
`ConversationList`, `HeaderBar`, `CenterPanel`, `ChatFeed`, `Composer`, `VoiceOrb`, `RightPanel`,
`SystemStatusCard`, `QuickActionsCard`, `RecentActivityCard`, `WeatherCard`. (13 puntos de registro,
1 punto de paleta.)

### 3.2 `ai/memory_manager.py` — esquema y compatibilidad legacy

**Decisión: extender `memories` con dos columnas aditivas. NO se crea una tabla nueva de turnos.**

Motivo: los turnos *son* memorias. Hoy alimentan `get_recent()` (→ `RecentActivityCard`),
`search_semantic()`, `get_important_memories()` y `consolidate()`. Moverlos a una tabla aparte
dejaría el texto real del usuario fuera de la memoria semántica — una regresión de comportamiento
disfrazada de limpieza de esquema.

```sql
-- Ejecutado por _migrate_schema(conn), llamado desde _init_db() en cada arranque
ALTER TABLE memories ADD COLUMN conversation_id TEXT;   -- NULL = fila legacy / no conversacional
ALTER TABLE memories ADD COLUMN role TEXT;              -- 'user' | 'assistant' | NULL
CREATE INDEX IF NOT EXISTS idx_memories_conversation
  ON memories(user_id, conversation_id, id);
```

`_migrate_schema()` lee `PRAGMA table_info(memories)` y solo emite el `ALTER` de las columnas que
faltan, envuelto en `try/except` con `logger.error` (nunca `except: pass`). Propiedades:

- **Idempotente:** correr la app N veces no vuelve a alterar nada.
- **O(1) y no destructivo:** `ADD COLUMN` sin `NOT NULL` ni `DEFAULT` no reescribe la tabla en
  SQLite; no hay `DROP`, `RENAME` ni copia. No hace falta un plan de rollback más allá de una copia
  de `ai/unified_memory.db` (recomendada antes del primer arranque en desarrollo).
- **Compatible hacia atrás:** un binario anterior al REQ que abra la misma DB ignora las columnas
  nuevas, porque todos los `SELECT` existentes enumeran columnas explícitamente (verificado: no hay
  ningún `SELECT *` en el módulo).

**Tratamiento de filas legacy (CA-12): se ignoran, no se migran.** Toda fila anterior al REQ queda
con `conversation_id IS NULL`, y las tres queries conversacionales filtran
`conversation_id IS NOT NULL`. No se inventa una "conversación legacy":

- Las filas viejas son un único string combinado `f"{matched_by} | {result_text}"` sin separación
  usuario/IA — convertirlas en burbujas produciría contenido falso atribuido al usuario.
- No se pierde nada: siguen visibles en `get_recent()`, en la memoria semántica y en la actividad
  reciente, exactamente como hoy.

**Riesgo evaluado y descartado:** un backfill que asignara un `conversation_id` sintético por día o
por bloque temporal. Descartado por inventar estructura que el dato no tiene (§6).

### 3.3 API nueva de `UnifiedMemory`

```python
@dataclass
class ConversationSummary:
    conversation_id: str
    title: str            # primer mensaje 'user', recortado a 60 chars (+ "…")
    last_activity: str    # ISO, MAX(timestamp) de la conversación
    turn_count: int

# MemoryItem gana dos campos opcionales al final (todos los callers usan kwargs → compatible):
#   conversation_id: Optional[str] = None
#   role: Optional[str] = None
```

| Función | Firma | Nota |
|---------|-------|------|
| `new_conversation_id` | `@staticmethod () -> str` | `uuid.uuid4().hex`. Sin PII, sin secuencia adivinable. |
| `store` | `store(text, user_id="default", category="general", importance=0.5, source="conversation", conversation_id=None, role=None) -> Optional[int]` | **Dos kwargs nuevos al final** con default `None` → los 3 callers actuales (`main.py` x2, `gui.py`) siguen compilando y comportándose igual. Pasa a devolver el `lastrowid` (o `None` si falló), útil para `store_turn` y para tests. |
| `store_turn` | `store_turn(user_text, assistant_text, conversation_id, user_id="default", matched_by="", importance=0.5) -> None` | Escribe **dos** filas con `category="interaction"`: `(user_text, role="user")` y `(assistant_text, role="assistant")`, ambas con el mismo `conversation_id`. `matched_by` se guarda en la columna `source` de la fila del asistente (`source=f"desktop:{matched_by}"`) para no perder la trazabilidad que hoy vive dentro del texto. Si `user_text` o `assistant_text` viene vacío, no escribe esa fila y loguea a nivel `warning`. |
| `list_conversations` | `list_conversations(user_id="default", limit=30, offset=0) -> List[ConversationSummary]` | Una sola query (§ abajo). Devuelve `[]` ante excepción, con `logger.error` — igual que `get_recent()`. |
| `get_conversation_turns` | `get_conversation_turns(conversation_id, user_id="default", limit=200) -> List[MemoryItem]` | `ORDER BY id ASC`. `limit` acota conversaciones muy largas (últimos N turnos, en orden cronológico: subquery `ORDER BY id DESC LIMIT ?` reordenada ascendente). |
| `get_recent` | se le agrega `role: Optional[str] = None` | Sin el kwarg, el comportamiento es idéntico a hoy. Con `role="user"` filtra `(role = ? OR role IS NULL)` — el `OR NULL` es lo que evita que `RecentActivityCard` quede vacío tras la migración (§3.4). |

Query de `list_conversations` (una sola ida a la DB, sin N+1):

```sql
SELECT  m.conversation_id,
        MAX(m.timestamp)  AS last_activity,
        COUNT(*)          AS turn_count,
        (SELECT u.text FROM memories u
          WHERE u.conversation_id = m.conversation_id
            AND u.role = 'user'
          ORDER BY u.id ASC LIMIT 1) AS title_src
FROM memories m
WHERE m.user_id = ? AND m.archived = 0 AND m.conversation_id IS NOT NULL
GROUP BY m.conversation_id
ORDER BY last_activity DESC
LIMIT ? OFFSET ?
```

Consecuencias que resuelven casos borde de la SPEC **sin código extra**:

- Una conversación "vacía" (id acuñado pero sin filas) **no puede existir**, porque el id solo se
  materializa al escribir la primera fila → no aparece entrada vacía en el sidebar, y el doble clic
  en "Nueva conversación" es idempotente por construcción.
- `title_src` es `NULL` si por algún motivo una conversación no tuviera fila `role='user'`; el
  fallback en Python es `"(sin título)"`, nunca una excepción.

### 3.4 Impacto en `main.py` y `RecentActivityCard` — pregunta abierta del baseline, resuelta

**`main.py` NO se modifica.** Sus dos llamadas (`memory.store(f"{command} | {result}", …)` en la
línea ~167 y la copia `category="semantic"` en la ~172) pertenecen al camino CLI/voz, no al canal
DESKTOP. La SPEC delimita explícitamente el historial funcional al canal DESKTOP ("Sincronización de
historial entre canales — No incluye"). Al ser el cambio de esquema puramente aditivo, esas filas
siguen insertándose igual y quedan con `conversation_id = NULL`; es decir, los comandos ejecutados
por CLI/voz **no aparecen** en el sidebar de conversaciones. Eso es intencional y coherente con el
alcance aprobado; si a futuro se quiere unificar, es un REQ de MEMORIA aparte.

> Observación fuera de alcance para `orion-qa`: `main.py` ~línea 173 tiene un
> `except Exception: pass` sin logging, que viola `.claude/rules/python-style.md`. Es
> **preexistente** y este REQ no lo toca; se deja anotado para que no se atribuya a REQ-013 ni se
> corrija silenciosamente aquí.

**`RecentActivityCard` cambia una línea.** Como ahora hay dos filas `category="interaction"` por
turno, llamar `get_recent(limit=4)` sin filtro llenaría la tarjeta con pares alternados
usuario/respuesta y mostraría la mitad de turnos que hoy. Cambio mínimo:

```python
self.set_items(memory.get_recent(user_id="default", limit=4, role="user"))
```

Con el filtro `(role = 'user' OR role IS NULL)`, la tarjeta muestra "lo último que el usuario pidió"
(una entrada por turno, semántica más cercana a la actual) **y** sigue mostrando las filas legacy y
las de `main.py`, que tienen `role IS NULL`. Es el único cambio de contrato que este REQ introduce
en el panel derecho, y queda documentado bajo CA-22.

### 3.5 `config_manager.py`

```python
DEFAULT_CONFIG = { ..., "ui_theme": "dark" }        # default = look actual, sin sorpresa visual

# en load_config(), junto a los otros fallbacks (líneas 44-51):
if "ui_theme" not in config:
    config["ui_theme"] = DEFAULT_CONFIG["ui_theme"]

def get_ui_theme() -> str:
    """Return the persisted UI theme name (REQ-013/CA-02)."""
    config = load_config()
    return config.get("ui_theme", "dark")

def set_ui_theme(theme: str) -> None:
    config = load_config()
    config["ui_theme"] = theme.strip().lower()
    save_config(config)
```

Igual que `get_display_name`/`get_weather_city`, el accessor es **acceso puro**: la validación
contra el catálogo de temas vive en `ui/theme.py:resolve_theme_name()`, no acá. Es la misma
separación que la propia docstring de `get_weather_city` documenta.

**Nivel de riesgo de escribir `config.json`:** 🟢 Verde, por el mismo precedente que
`set_weather_city` (REQ-012) y `set_display_name` (REQ-008): la app persiste su propia preferencia
en su propio archivo de configuración; no es "modificar archivos del usuario" en el sentido 🟡
Amarillo de `.claude/rules/security-levels.md`.

---

## 4. Bloque 3 — widgets nuevos y flujo de datos

### 4.1 Archivos nuevos en `ui/widgets/` (nombres y división exactos)

| Archivo | Clase | Responsabilidad | API pública |
|---------|-------|-----------------|-------------|
| `ui/widgets/chat_bubble.py` | `ChatBubble(QFrame)` | Una burbuja. `objectName="ChatBubble"`, propiedad dinámica `role` (`"user"`/`"assistant"`) para el QSS. `QLabel` con `setWordWrap(True)` y `TextSelectableByMouse` (el usuario puede copiar una respuesta — hoy no puede). Ancho máximo 72% del feed. **No se registra en `theme_changed`** (§3.1). | `ChatBubble(text: str, role: str, parent=None)`, `set_text(text)`, `text() -> str`, `role() -> str` |
| `ui/widgets/chat_feed.py` | `ChatFeed(QScrollArea)` | Contenedor scrolleable de burbujas + autoscroll + dueño del QSS de las burbujas. Nada de lógica de negocio. | `add_message(text, role) -> ChatBubble`, `clear_messages()`, `load_turns(turns: List[MemoryItem])`, `message_count() -> int`, `is_empty() -> bool`, `apply_theme(palette)` |
| `ui/widgets/composer.py` | `Composer(QFrame)` | Fila de chips + input + toggle manos libres + botón enviar. Dueño del ciclo de vida de los chips y de la ejecución de accesos directos. | señales `command_submitted(str)`, `hands_free_toggled(bool)`; métodos `set_wake_state(state)`, `set_text(text)`, `clear()`, `apply_theme(palette)` |
| `ui/widgets/conversation_list.py` | `ConversationList(QWidget)` | Botón "＋ Nueva conversación" + `QListWidget` de conversaciones + botón "Ver más". Solo presentación: no consulta la DB, recibe los datos ya cargados. | señales `conversation_selected(str)`, `new_conversation_requested()`, `more_requested()`; métodos `set_conversations(items, append=False)`, `set_active(conversation_id)`, `set_has_more(bool)`, `apply_theme(palette)` |
| `ui/theme.py` | `Palette`, `ThemeManager` | §3.1 | — |

**No se crea** `theme_toggle.py`: el selector es un `QPushButton` checkable privado dentro de
`header_bar.py` (`_theme_toggle`), demasiado pequeño para justificar un módulo propio.

`ConversationList` es un widget aparte de `sidebar.py` (y no código dentro de `Sidebar`) porque es
lo único de la barra con estado dinámico y con tests propios; `Sidebar` queda como un contenedor
declarativo, testeable como hoy.

### 4.2 `ChatFeed` — autoscroll y carga (CA-15)

```
add_message(text, role)
  ├─ crea ChatBubble, la inserta antes del stretch final del QVBoxLayout interno
  ├─ _autoscroll_pending = True   (solo si el usuario ya estaba cerca del fondo)
  └─ el slot conectado a verticalScrollBar().rangeChanged consume el flag y
     hace setValue(maximum())
```

Setear `scrollbar.setValue(maximum())` justo después de `addWidget()` **no funciona**: el layout aún
no se recalculó y `maximum()` todavía es el viejo. Por eso el autoscroll se dispara desde
`rangeChanged`, que Qt emite cuando el rango ya es el nuevo.

"Cerca del fondo" = `value() >= maximum() - 40`. Así, si el usuario subió a releer un mensaje
anterior mientras llega una respuesta, el feed **no** le arranca la vista de las manos.

`load_turns(turns)`: `clear_messages()` → `add_message(t.text, t.role or "assistant")` por turno →
autoscroll forzado al final. `clear_messages()` hace `deleteLater()` de cada burbuja (no
`setParent(None)` a secas) para no filtrar widgets al navegar entre conversaciones.

### 4.3 `ui/gui.py` — orquestación y flujo de datos

Estado nuevo en `JarvisMainWindow`:

```python
self._conversation_id: Optional[str] = None   # None = conversación nueva aún sin acuñar
self._pending_user_text: str = ""             # texto del turno en vuelo
```

**Flujo A — envío de un comando (CA-13, CA-14, CA-09, CA-17):**

```
Composer.command_submitted(text)
  → CenterPanel.command_submitted(text)          (re-emisión, firma intacta)
  → JarvisMainWindow._handle_command(text)
       1. self.center_panel.add_user_message(text)        → burbuja usuario YA visible  [CA-13]
       2. self._pending_user_text = text
       3. run_async(resolve, self._on_command_done, self._on_command_error,
                    text, ChannelType.DESKTOP, user_id="default")     (sin cambios)  [CA-17]

  → _on_command_done(resolution)   [hilo GUI]
       1. self.center_panel.show_response(resolution.text)  → burbuja assistant       [CA-14]
       2. cid = self._ensure_conversation_id()   # acuña uuid4 si era None            [CA-07]
       3. run_async(memory.store_turn, None, None,
                    user_text=self._pending_user_text,
                    assistant_text=resolution.text,
                    conversation_id=cid, user_id="default",
                    matched_by=resolution.matched_by)      → fuera del hilo GUI       [CA-09]
       4. self._reload_conversations()   # refresca el sidebar (también async)        [CA-05]

  → _on_command_error(message)   [hilo GUI]
       muestra la burbuja de error y NO persiste turno (un error no es una respuesta
       de la IA; persistirlo ensuciaría el historial y la memoria semántica).
```

El paso 3 es un cambio deliberado respecto de hoy: `memory.store()` se llamaba **en el hilo de la
GUI** y calcula un embedding (`ai/embedding_engine.create_embedding`). Con dos filas por turno eso
sería el doble de congelamiento de la ventana. `run_async` sin callbacks lo elimina; los errores ya
quedan logueados dentro de `CallableWorker.run()`, así que no se pierde diagnóstico ni se introduce
un `except: pass`.

**Flujo B — cargar una conversación (CA-06):**

```
ConversationList.conversation_selected(cid)
  → Sidebar.conversation_selected(cid)              (re-emisión)
  → JarvisMainWindow._on_conversation_selected(cid)
       self._conversation_id = cid
       run_async(memory.get_conversation_turns, self._on_turns_loaded,
                 self._on_turns_error, cid, user_id="default")
  → _on_turns_loaded(turns)   [hilo GUI]
       self.center_panel.load_turns(turns)
       self.sidebar.set_active_conversation(self._conversation_id)
```

**Flujo C — nueva conversación (CA-07):**

```
ConversationList.new_conversation_requested()
  → Sidebar.new_conversation_requested()
  → JarvisMainWindow._on_new_conversation()
       self._conversation_id = None      # se acuñará con el primer mensaje
       self.center_panel.clear_feed()    # vuelve a mostrarse el bloque de estado vacío
       self.sidebar.set_active_conversation(None)
```

**Flujo D — arranque y listado (CA-05, paginación):**

```
JarvisMainWindow.__init__
  1. theme_manager.load_from_config()      # ANTES de construir widgets → sin flash de tema  [CA-02]
  2. _init_ui()  (cada widget se auto-registra con register_themed en su __init__)
  3. register_themed(self)                 # QMainWindow background
  4. self._reload_conversations()          # run_async(memory.list_conversations, ...)
```

`_reload_conversations(offset=0)` nunca toca SQLite desde el hilo GUI, así que un historial de
cientos de conversaciones no retrasa el `showMaximized()` (caso borde de la SPEC).

**Flujo E — cambio de tema (CA-01):**

```
HeaderBar._theme_toggle.clicked
  → theme_manager.toggle()
       ├─ config_manager.set_ui_theme(nuevo)                                    [CA-02]
       └─ theme_changed.emit(Palette)  →  apply_theme() de los 13 registrados   [CA-01, CA-04, CA-21]
```

El cambio de tema **no toca** `_conversation_id`, `_pending_user_text` ni ningún `QRunnable` en
vuelo: solo reemplaza hojas de estilo. Una resolución en curso (estado PROCESSING) sigue
exactamente igual — caso borde de la SPEC cubierto por construcción, no por código defensivo.

### 4.4 `CenterPanel` — compositor delgado (clave para CA-22)

`ui/widgets/center_panel.py` conserva archivo, clase y **toda su API pública**. Estructura interna
nueva:

```python
class CenterPanel(QFrame):
    command_submitted = pyqtSignal(str)      # re-emitida desde Composer
    hands_free_toggled = pyqtSignal(bool)    # re-emitida desde Composer

    # se conservan sin moverse de archivo (los 4 tests de REQ-012 dependen de ellos):
    #   _display_name, _greeting_label, _greeting_timer, _refresh_greeting(),
    #   _resolve_display_name(), _GREETING_REFRESH_MS
    #
    # layout: [ _empty_state (greeting + subtítulo + avatar 🤖 + VoiceOrb) ]
    #         [ _feed: ChatFeed, stretch=1 ]
    #         [ _composer: Composer ]

    def set_state(self, state)          # → self._orb.set_state(state)   (igual que hoy)
    def set_wake_state(self, state)     # → self._composer.set_wake_state(state)
    def show_response(self, text)       # → self._feed.add_message(text, "assistant")   [CA-14]
    def add_user_message(self, text)    # NUEVO → self._feed.add_message(text, "user")  [CA-13]
    def load_turns(self, turns)         # NUEVO → self._feed.load_turns(turns)          [CA-06]
    def clear_feed(self)                # NUEVO → self._feed.clear_messages()           [CA-07]
    def apply_theme(self, palette)      # NUEVO
    def _sync_empty_state(self)         # muestra/oculta _empty_state según _feed.is_empty()
```

Decisiones dentro de este widget:

- El saludo, el subtítulo y el `VoiceOrb` **no se eliminan**: se agrupan en `_empty_state`, visible
  cuando el feed está vacío (patrón de la referencia WorkBuddy AI). `_greeting_timer` sigue
  corriendo aunque el bloque esté oculto — así los tests de REQ-012 no dependen de la visibilidad.
- `_status_label` (el `QLabel` truncado a 200 chars) **desaparece**: lo reemplaza el feed (CA-14) y
  el texto de estado ya lo muestra `HeaderBar._mode_pill`. `_STATE_STATUS_TEXT` se elimina del
  módulo.
- `VoiceOrb` mantiene su geometría fija de 220x220. **No se parametriza el tamaño**: su
  `paintEvent()` tiene radios absolutos (`base_radius = 60`, núcleos de 22 y 18 px) que no escalan
  con el widget; hacerlo escalable es refactor gratuito fuera del alcance. El único cambio en
  `voice_orb.py` es sustituir el `_STATE_COLORS` de módulo por `self._state_colors`, inicializado
  desde `palette.orb_colors` en `apply_theme()`.

### 4.5 `Composer` — chips (CA-18, CA-19)

```python
_CHIPS = [
    {"label": "Resumen del día",     "kind": "template",
     "payload": "Dame un resumen de mi actividad reciente y tareas pendientes"},
    {"label": "Recuérdame algo",     "kind": "template", "payload": "Recuérdame que "},
    {"label": "Investigación rápida","kind": "template", "payload": "Investiga sobre "},
    {"label": "📷 Captura de pantalla","kind": "action",  "payload": "take_screenshot"},
    {"label": "🌐 Abrir navegador",   "kind": "action",  "payload": "open_browser"},
]
```

- **template** → `self._input.setText(payload)`, `self._input.setFocus()`, cursor al final. No envía
  nada, no ejecuta nada.
- **action** → literalmente el patrón de `QuickActionsCard._run_action()`:

  ```python
  run_async(execute_action, self._on_action_done, self._on_action_error,
            payload, channel=ChannelType.DESKTOP, user_id="default")
  ```

  Nunca importa la función subyacente, nunca la llama directo → el gate fail-closed de
  `core/security_manager.py` se ejecuta igual que en cualquier otro canal (CA-19).

El resultado de un chip de acción se muestra en un `QLabel` de estado dentro del composer
(`objectName="ComposerActionStatus"`), **no** como burbuja y **sin persistirse**: no pasó por
`resolve()`, así que no es un turno de conversación. Mezclarlo en el feed haría que el historial
persistido y el feed visible dejaran de coincidir al recargar la conversación.

La fila de chips vive en un `QScrollArea` horizontal (`setHorizontalScrollBarPolicy(AsNeeded)`,
`setVerticalScrollBarPolicy(AlwaysOff)`, altura fija ~40px), como en la referencia visual.

### 4.6 `Sidebar` y `HeaderBar`

`sidebar.py`:
- `_NAV_ITEMS` intacto salvo `("conversaciones", "💬  Conversaciones", **True**)` (CA-08 para los
  otros 5).
- Debajo del bloque de navegación: separador, luego `self._conversations = ConversationList()` con
  `stretch=1`, luego el pie "● Sistema activo" existente.
- Re-emite `conversation_selected(str)`, `new_conversation_requested()`, `more_requested()`; expone
  `set_conversations(...)`, `set_active_conversation(cid)`, `set_has_more(bool)`.
- Ancho fijo `250 → 280` px (títulos de conversación legibles). `nav_selected` y el test
  `test_sidebar_inicio_emits_nav_selected` no cambian.

`header_bar.py`:
- Nuevo `self._theme_toggle = QPushButton()` checkable, `objectName="ThemeToggle"`, texto `☀`/`🌙`
  según `theme_manager.current_name()`, tooltip "Cambiar a tema claro/oscuro", insertado
  **antes** de `_mode_pill`.
- `_theme_toggle.clicked` → `theme_manager.toggle()`; `theme_changed` → actualiza su propio icono
  dentro de `HeaderBar.apply_theme()`. El toggle se actualiza por la señal, no por el clic, así que
  un cambio de tema disparado desde otro lugar lo dejaría sincronizado igual.
- `set_state()` / `set_wake_state()` sin cambios (CA-16).

---

## 5. Archivos a modificar / crear

**Nuevos (5):**
- `ui/theme.py`
- `ui/widgets/chat_bubble.py`
- `ui/widgets/chat_feed.py`
- `ui/widgets/composer.py`
- `ui/widgets/conversation_list.py`

**Modificados (13):**
- `ui/gui.py` — `_init_ui` (tema + wiring), estado de conversación, `_handle_command`,
  `_on_command_done`, `_on_command_error`, handlers nuevos de conversación, `apply_theme`.
- `ui/widgets/center_panel.py` — reescritura interna, API pública intacta (§4.4).
- `ui/widgets/sidebar.py` — `ConversationList` + activación de "Conversaciones" + QSS por paleta.
- `ui/widgets/header_bar.py` — selector de tema + QSS por paleta.
- `ui/widgets/voice_orb.py` — `_STATE_COLORS` → `self._state_colors` desde `palette.orb_colors`.
- `ui/widgets/right_panel.py` — `apply_theme` + propagación a las 4 tarjetas.
- `ui/widgets/system_status_card.py` — QSS → plantilla + `apply_theme`.
- `ui/widgets/quick_actions_card.py` — QSS → plantilla + `apply_theme`.
- `ui/widgets/recent_activity_card.py` — QSS → plantilla + `apply_theme` + `role="user"` (§3.4).
- `ui/widgets/weather_card.py` — QSS → plantilla + `apply_theme`.
- `ai/memory_manager.py` — `_migrate_schema`, `ConversationSummary`, campos nuevos en `MemoryItem`,
  `store` extendido, `store_turn`, `list_conversations`, `get_conversation_turns`, `get_recent(role=)`,
  lock de embeddings (§6, riesgo 4).
- `config_manager.py` — `ui_theme` en `DEFAULT_CONFIG`, fallback en `load_config()`,
  `get_ui_theme()`, `set_ui_theme()`.
- `tests/test_gui_widgets.py` — ajustes puntuales (§7).

**Explícitamente NO modificados:** `main.py` (§3.4), `requirements.txt`, `ui/cli.py`,
`core/resolution.py`, `agents/action_registry.py`, `core/security_manager.py`, `ui/gui_workers.py`.

---

## 6. Riesgos y mitigación

| # | Riesgo | Mitigación |
|---|--------|------------|
| 1 | Romper los 4 tests de REQ-012 al mover el saludo a un widget nuevo | El saludo, `_greeting_label`, `_greeting_timer`, `_refresh_greeting` y `_display_name` **se quedan en `center_panel.py`** con los mismos nombres privados. El feed no los toca. Cero churn en esos tests. |
| 2 | QSS con llaves `{}` reventaría al usar `str.format` para inyectar tokens | Obligatorio `string.Template` con `$token` + `.substitute()`. Anotado en el docstring de `ui/theme.py` para que no se "simplifique" a `.format()` después. |
| 3 | Doble embedding por turno ejecutado en el hilo GUI → ventana congelada visible | `store_turn` se invoca vía `run_async(...)` sin callbacks. Elimina además el congelamiento que ya existía hoy con `memory.store()` en `_on_command_done`. |
| 4 | Segundo escritor concurrente sobre `self._embeddings` / `_embedding_ids` / `_embedding_user_ids` (listas compartidas mutadas desde hilos) — carrera con `search_semantic()` | Race preexistente (main.py y bots ya escriben desde otros hilos), pero este REQ agrega un escritor más y lo hace explícito: envolver los tres `append` de `store()` y la lectura en `search_semantic()` con un `self._emb_lock = threading.Lock()` dedicado (≈6 líneas). No se reutiliza `_lock`, que es el del singleton. |
| 5 | `ALTER TABLE` sobre la DB real del usuario | `ADD COLUMN` nullable es O(1) y no reescribe la tabla; `_migrate_schema()` es idempotente vía `PRAGMA table_info`; no hay `DROP`/`RENAME`/copia. Recomendación operativa: copiar `ai/unified_memory.db` antes del primer arranque post-cambio en la máquina de desarrollo. |
| 6 | Filas legacy apareciendo como conversaciones basura en el sidebar | Filtro `conversation_id IS NOT NULL` en las 3 queries conversacionales. Sin backfill: las legacy nunca entran al listado (CA-12). |
| 7 | `RecentActivityCard` mostrando el doble de entradas y con contenido partido | `get_recent(role="user")` con predicado `(role = ? OR role IS NULL)`, que además preserva las filas legacy y las de `main.py`. |
| 8 | Cientos de conexiones vivas a `theme_changed` por las burbujas | `ChatBubble` no se registra: hereda el QSS de `ChatFeed`, que sí. Solo 13 receptores fijos en toda la app. |
| 9 | Conversación de cientos de turnos construyendo cientos de widgets en el hilo GUI al hacer click | `get_conversation_turns(..., limit=200)` acota la carga a los últimos 200 turnos, mostrados en orden cronológico. |
| 10 | Autoscroll arrancándole la vista al usuario que está releyendo | El autoscroll solo se aplica si el scroll ya estaba a ≤40px del fondo antes de insertar. |
| 11 | El `theme_manager` es un singleton de módulo que persiste entre tests | Fixture `reset_theme` en los tests: guarda el nombre actual, fuerza `"dark"` y lo restaura al terminar; `config_manager.CONFIG_FILE` monkeypatcheado a `tmp_path` en cualquier test que persista tema. |
| 12 | Working tree con cambios sin commitear de REQ-007 y REQ-012 (baseline tomada sobre ese estado, 226 passed) | `orion-dev` parte del **mismo working tree**, no de `HEAD`. No hacer `git stash`, `checkout` ni `reset` antes de implementar. |
| 13 | Regresión visual del tema oscuro al centralizar 10+ QSS dispersos | Los tokens `dark` reproducen exactamente los hex actuales de cada archivo. Verificación de `orion-tester`: comparar visualmente la app en tema oscuro contra el estado previo — no debe haber diferencia perceptible fuera de la columna central rediseñada. |

**Descartado (y por qué):**

- **Tabla `conversations` dedicada** — el listado se deriva por agregación sobre `memories` con una
  sola query; una tabla espejo agregaría un segundo camino de escritura y un riesgo de
  desincronización a cambio de nada medible con 30 filas por página.
- **Tabla `conversation_turns` separada de `memories`** — dejaría el texto del usuario fuera de la
  memoria semántica y de `get_recent()`, regresión de comportamiento (§3.2).
- **Backfill de filas legacy con un `conversation_id` sintético (por día o por bloque temporal)** —
  inventa estructura que el dato no tiene y produce burbujas de "usuario" con texto que en realidad
  es `matched_by | respuesta`.
- **`QSettings` de Qt para el tema** — el proyecto ya tiene un mecanismo de preferencias
  (`config.json` + patrón `get_/set_`); introducir un segundo store fragmenta la configuración.
- **Recorrer el árbol de widgets desde `JarvisMainWindow` llamando `apply_theme` a lo que lo tenga**
  — funciona, pero acopla la ventana a la jerarquía completa y no cubre widgets creados después. La
  señal + `register_themed()` es igual de simple y desacoplada.
- **`VoiceOrb` escalable / reubicado al header** — su `paintEvent` tiene radios absolutos; hacerlo
  escalable es refactor fuera de alcance (§4.4).
- **Burbuja "escribiendo…" durante PROCESSING** — no lo pide ningún CA; el estado ya se comunica por
  `HeaderBar._mode_pill` y el `VoiceOrb`. Se deja anotado como mejora futura.
- **Resultado de chips de acción como burbuja persistida** — rompería la equivalencia entre el feed
  visible y el historial recargado (§4.5).
- **Modificar `main.py` para acuñar `conversation_id` en CLI/voz** — fuera del alcance aprobado
  (historial exclusivo del canal DESKTOP, §3.4).

---

## 7. Impacto en los tests existentes (CA-22)

| Test | Impacto |
|------|---------|
| `test_sidebar_inicio_emits_nav_selected` | ✅ Sin cambios — `nav_selected` y el ítem "Inicio" intactos. |
| `test_system_status_card_set_values_updates_labels` | ✅ Sin cambios — solo se toca el QSS de la tarjeta. |
| `test_quick_actions_card_click_calls_execute_action_via_channel` | ✅ Sin cambios. |
| `test_recent_activity_card_empty_state` / `..._renders_items_with_time` | ⚠️ Mockean `memory.get_recent`; hay que **actualizar la aserción de la llamada** para incluir `role="user"`. Motivo documentado: §3.4. |
| `test_weather_card_*` (4) | ✅ Sin cambios. |
| `test_center_panel_greeting_matches_personality_helper` | ✅ Sin cambios (§4.4, riesgo 1). |
| `test_center_panel_greeting_timer_*` / `_refresh_greeting_*` (4) | ✅ Sin cambios. |
| `test_jarvis_main_window_close_hides_without_quitting_app` | ✅ Sin cambios — `closeEvent` intacto. |
| `test_tray_icon_activo_sin_ventana_mostrada_ca04` | ✅ Sin cambios. |
| `tests/test_cli_gui_active.py`, `tests/test_wake_word_gui.py` | ✅ Sin cambios esperados — dependen de `update_gui_state`/`WAKE_STATE`/`hands_free_toggled`, todo conservado. `orion-tester` debe confirmarlo. |
| `tests/test_memory_manager_recent.py` | ✅ Sin cambios esperados — `get_recent()` sin el kwarg nuevo se comporta idéntico. |

Baseline a superar: **226 passed, 0 fallos preexistentes.**

---

## 8. Pruebas sugeridas (una o más por criterio)

**`tests/test_theme.py` (nuevo)**
- `test_palette_contrast_ratios` — **CA-03.** Helper local `_contrast_ratio(hex_a, hex_b)` (fórmula
  WCAG de luminancia relativa) sobre los pares de §3.1; assert ≥ 4.5 para texto normal, ≥ 3.0 para
  texto grande/bordes, en **ambas** paletas. Es el criterio objetivo de CA-03.
- `test_ambos_temas_definen_todos_los_tokens` — `asdict(LIGHT_PALETTE).keys() == asdict(DARK_PALETTE).keys()`
  y ningún valor vacío; los 4 estados presentes en `orb_colors` de ambos.
- `test_resolve_theme_name_normaliza_valor_invalido` — `"", "DARK", "azul", None` → `"dark"`.
- `test_qss_templates_sustituyen_sin_keyerror` — para cada módulo con QSS, `_qss(p)` no lanza y el
  resultado no contiene `"$"` (garantiza que ningún token quedó sin sustituir).

**`tests/test_config_manager_ui_theme.py` (nuevo)** — CA-02
- `test_get_ui_theme_default_dark_sin_clave` (config antiguo sin `ui_theme`).
- `test_set_ui_theme_persiste_y_se_relee` con `CONFIG_FILE` monkeypatcheado a `tmp_path`.
- `test_set_ui_theme_normaliza_espacios_y_mayusculas`.

**`tests/test_conversation_memory.py` (nuevo)** — CA-09..CA-12, con `DB_PATH` monkeypatcheado a
`tmp_path` y `_get_embedding` mockeado (`.claude/rules/testing.md`: sin red, sin archivos reales)
- `test_migracion_agrega_columnas_y_es_idempotente` — crear DB con el esquema **viejo** (9 columnas),
  correr `_init_db()` dos veces, verificar `PRAGMA table_info` y que no lanza. **CA-12.**
- `test_filas_legacy_no_aparecen_en_list_conversations` — insertar filas con `conversation_id NULL`
  + una conversación real; el listado devuelve solo la real. **CA-12.**
- `test_store_turn_escribe_dos_filas_mismo_conversation_id` con roles `user`/`assistant`. **CA-09.**
- `test_list_conversations_ordena_por_ultima_actividad_desc` (3 conversaciones con timestamps
  distintos). **CA-05, CA-10.**
- `test_list_conversations_titulo_es_primer_mensaje_de_usuario_truncado`. **CA-10.**
- `test_list_conversations_pagina_con_limit_offset` (35 conversaciones, `limit=30` → 30 + 5).
- `test_get_conversation_turns_orden_cronologico_por_id` — dos filas con **el mismo timestamp**;
  verifica que el orden es de inserción (el caso que `ORDER BY timestamp` rompería). **CA-11.**
- `test_get_recent_sin_role_devuelve_todo_como_antes` (regresión) y
  `test_get_recent_role_user_incluye_filas_legacy_con_role_null`. **§3.4.**
- `test_conversacion_sin_mensajes_no_existe_en_el_listado` — caso borde de la SPEC.

**`tests/test_chat_widgets.py` (nuevo)** — CA-13..CA-15, CA-18, CA-19
- `test_chat_bubble_role_property_user_vs_assistant`.
- `test_chat_feed_add_message_incrementa_conteo_y_conserva_orden`. **CA-13, CA-14.**
- `test_chat_feed_load_turns_reemplaza_contenido_previo`. **CA-06.**
- `test_chat_feed_clear_messages_deja_feed_vacio`. **CA-07.**
- `test_chat_feed_autoscroll_al_agregar_mensaje` — con `qtbot`, tras `add_message` y procesar
  eventos, `verticalScrollBar().value() == maximum()`. **CA-15.**
- `test_chat_feed_no_autoscroll_si_usuario_subio` — scroll a 0, `add_message`, el valor no salta.
- `test_composer_submit_emite_command_submitted_y_limpia_input`. **CA-17.**
- `test_composer_chip_plantilla_prellena_input_sin_emitir_comando`. **CA-18.**
- `test_composer_chip_accion_llama_execute_action_con_channel_desktop` — mockear
  `ui.widgets.composer.execute_action` y `run_async`; assert `channel=ChannelType.DESKTOP` y que la
  acción **no** se invoca directo (espejo del test existente de `QuickActionsCard`). **CA-19.**
- `test_composer_set_wake_state_no_reemite_hands_free_toggled` — regresión del guard de REQ-009.
  **CA-16.**
- `test_conversation_list_click_emite_conversation_selected_con_id`. **CA-06.**
- `test_conversation_list_boton_nueva_emite_new_conversation_requested`. **CA-07.**
- `test_conversation_list_set_active_marca_el_item`. **CA-06.**

**Adiciones a `tests/test_gui_widgets.py`** — integración
- `test_center_panel_show_response_agrega_burbuja_completa_sin_truncar` — respuesta de 500 chars;
  el texto de la burbuja es íntegro. **CA-14.**
- `test_center_panel_add_user_message_agrega_burbuja_user`. **CA-13.**
- `test_center_panel_empty_state_se_oculta_al_primer_mensaje`.
- `test_main_window_handle_command_agrega_burbuja_usuario_antes_de_resolver` — mockear `run_async`;
  la burbuja ya existe cuando `run_async` fue llamado. **CA-13.**
- `test_main_window_on_command_done_persiste_turno_con_conversation_id` — mockear `run_async`;
  verificar que se agenda `memory.store_turn` con un `conversation_id` no vacío. **CA-09.**
- `test_main_window_nueva_conversacion_limpia_feed_y_resetea_id`. **CA-07.**
- `test_main_window_doble_nueva_conversacion_no_acuña_ids` — `_conversation_id is None` tras dos
  clics; caso borde de la SPEC.
- `test_main_window_carga_tema_de_config_al_iniciar`. **CA-02.**
- `test_toggle_tema_cambia_stylesheet_de_sidebar_feed_composer_y_right_panel` — capturar
  `styleSheet()` antes/después de `theme_manager.set_theme("light")` en los 4 widgets; deben
  cambiar todos. **CA-01, CA-04, CA-21.**
- `test_cambio_de_tema_no_altera_conversacion_activa` — con `_conversation_id` seteado y un feed con
  N burbujas, tras cambiar de tema el id y el conteo son los mismos. Caso borde de la SPEC.
- `test_right_panel_y_las_4_tarjetas_siguen_visibles_en_el_layout`. **CA-20.**
- `test_sidebar_conversaciones_habilitado_y_resto_placeholders_deshabilitados`. **CA-08.**

**Regresión completa** — `python -m pytest tests/ --tb=short -v`, objetivo ≥ 226 passed sin fallos
nuevos. **CA-22.**

---

## 9. Orden de implementación sugerido para `orion-dev`

1. `config_manager.py` (`ui_theme`) + `ui/theme.py` + `tests/test_theme.py` y
   `tests/test_config_manager_ui_theme.py` → verde antes de tocar un solo widget.
2. `ai/memory_manager.py` (migración + API + lock) + `tests/test_conversation_memory.py` → verde.
3. Migración de QSS a plantillas en los 6 widgets existentes + `apply_theme` + `HeaderBar` con el
   selector → la app debe verse **idéntica** a hoy en tema oscuro y correcta en claro, con el layout
   viejo todavía.
4. Widgets nuevos (`ChatBubble` → `ChatFeed` → `Composer` → `ConversationList`) +
   `tests/test_chat_widgets.py`.
5. `CenterPanel` como compositor + `Sidebar` con la lista + `ui/gui.py` (wiring de los 5 flujos).
6. Suite completa + adiciones a `tests/test_gui_widgets.py`.

Cada paso deja la app arrancable, lo que permite a `orion-tester` aislar cualquier fallo al paso que
lo introdujo.
