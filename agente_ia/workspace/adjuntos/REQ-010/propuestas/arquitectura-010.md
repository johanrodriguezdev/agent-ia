# Arquitectura REQ-010 — Branding visual Noddoo (íconos + colores GUI)

**Fecha:** 2026-08-05
**Agente:** orion-architect
**Estado:** ✅ APROBADA por Johan tal cual (2026-08-05), incluyendo la expansión de alcance del
Punto 4 (`system_status_card.py`) confirmada explícitamente al aprobar.

## Cobertura de criterios de la SPEC

| Criterio | Cómo lo satisface esta propuesta |
|----------|-----------------------------------|
| CA-01 | `JarvisMainWindow._init_ui()` agrega `self.setWindowIcon(QIcon(str(theme.WINDOW_ICON_PATH)))`. `theme.WINDOW_ICON_PATH` apunta a `assets/branding/noddoo-icon.ico`. |
| CA-02 | Mecanismo de dos capas sin empaquetar: (a) `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(...)` en `main.py`, antes de crear `QApplication`; (b) `app.setWindowIcon(...)` a nivel `QApplication` + `window.setWindowIcon(...)` a nivel ventana. Ver sección "Punto 1" abajo — **resultado no 100% garantizado, requiere verificación manual (ya así en la SPEC) y contempla fallback documentado**. |
| CA-03 | `_setup_tray_icon()` reemplaza `QPixmap(16,16)` + `QColor(0,100,255)` por `QIcon(str(theme.TRAY_ICON_PATH))` cargado desde `assets/branding/noddoo-icon.ico`. Sin cambios al resto de la función (menú, `activated`, `aboutToQuit`). |
| CA-04 | Script de un solo uso (dev-time, no runtime) documentado en "Punto 3" que usa Pillow `Image.save(..., format="ICO", sizes=[(16,16),(32,32),(48,48),(256,256)])` a partir de `noddoo-icon-mark.png`, preservando canal alfa. |
| CA-05 | Sin cambios de diseño — `orion-dev` verifica existencia de los 2 PNG antes de escribir código, tal como exige la SPEC. Ver "Dependencia pendiente" abajo. |
| CA-06 | Módulo nuevo `ui/theme.py` centraliza `BRAND_ACCENT_RGB` (fuente única) y deriva `BRAND_ACCENT_HEX` + `brand_accent_rgba(alpha)`. `header_bar.py`, `center_panel.py`, `sidebar.py` importan estas constantes y las interpolan en sus QSS (`_HEADER_QSS`, `_CENTER_QSS`, `_SIDEBAR_QSS`) en vez de hardcodear `#4fc3ff`/`rgba(79,195,255,...)`. **Expansión de alcance confirmada por Johan al aprobar esta arquitectura:** `system_status_card.py:41` se suma al mismo recoloreo (ver Punto 4, ya no condicional) — no estaba en CA-06/"Módulos afectados" de SPEC-010, pero Johan autorizó explícitamente incluirlo por consistencia visual. |
| CA-07 | No se toca ninguna línea con `#00e08a` ni `#33d17a` — confirmado en el diseño: `header_bar.py:98`, `center_panel.py:180`, `sidebar.py:80` quedan fuera del diff. |
| CA-08 | `_WAKE_STATE_ICONS` (`header_bar.py:26-30`) no se modifica — solo la línea QSS `#WakeIndicator[wakeState="LISTENING_WAKE"]` (línea 97) cambia su `color`/`background-color` a la constante de marca. |
| CA-09 | Ningún cambio de diseño toca layouts, tamaños, márgenes o estructura — todos los cambios propuestos son: (1) archivos nuevos en `assets/branding/`, (2) una línea de carga de ícono en `gui.py`, (3) sustitución de valores de color dentro de QSS/`QPen` ya existente, (4) un módulo nuevo hoja (`ui/theme.py`) sin widgets. |
| CA-10 | Ningún cambio propuesto introduce dependencias nuevas (Pillow ya está en `requirements.txt`) ni lógica que rompa imports existentes — `ui/theme.py` es un módulo sin dependencias de PyQt6, sin riesgo de ciclos de import. |

## Módulos a modificar

- `agente_ia/main.py` — agrega la llamada `ctypes` de `AppUserModelID` antes de instanciar `QApplication` (solo rama `if not headless:`, guardada por `sys.platform == "win32"`).
- `agente_ia/ui/gui.py` — `_init_ui()`: agrega `setWindowIcon()`. `_setup_tray_icon()`: reemplaza el `QPixmap` dibujado por carga de `.ico` desde archivo. Import nuevo: `from ui import theme` (o `from ui.theme import WINDOW_ICON_PATH, TRAY_ICON_PATH`). Se elimina el uso de `QColor`/`QPixmap` en `_setup_tray_icon()` si ya no se usan en otro lado del archivo (verificar antes de borrar el import).
- `agente_ia/ui/widgets/header_bar.py` — usa `theme.BRAND_ACCENT_HEX` en `_HEADER_QSS` (líneas 84 y 97, vía f-string).
- `agente_ia/ui/widgets/center_panel.py` — usa `theme.BRAND_ACCENT_HEX` en `_CENTER_QSS` (líneas 162, 168, 177).
- `agente_ia/ui/widgets/sidebar.py` — usa `theme.brand_accent_rgba(0.12)` en `_SIDEBAR_QSS` (línea 78), preservando el alpha `0.12` ya existente.
- `agente_ia/ui/widgets/system_status_card.py` — **confirmado por Johan al aprobar esta arquitectura** (expansión explícita de alcance respecto de SPEC-010, ver "Punto 4" abajo): `QPen(QColor(79, 195, 255), 8)` (línea 41) pasa a `QPen(QColor(*theme.BRAND_ACCENT_RGB), 8)`.

## Nuevas clases/funciones

### `ui/theme.py` (módulo nuevo)

```python
"""
ui/theme.py
Constantes de color y rutas de branding de Noddoo, centralizadas para no duplicar el
hex de acento de marca en múltiples archivos QSS (REQ-010/CA-06). Módulo hoja: no
importa PyQt6 ni ningún otro módulo del proyecto, para evitar ciclos de import.
"""

from pathlib import Path

# --- Rutas de assets ---
BRANDING_DIR: Path = Path(__file__).resolve().parent.parent / "assets" / "branding"
WINDOW_ICON_PATH: Path = BRANDING_DIR / "noddoo-icon.ico"
TRAY_ICON_PATH: Path = BRANDING_DIR / "noddoo-icon.ico"  # mismo .ico multi-resolución

# --- Color de marca ---
# Fuente única de verdad. orion-dev reemplaza esta tupla por el valor extraído de
# noddoo-icon-mark.png (ver arquitectura-010.md, "Punto 3"). El hex se deriva, nunca
# se mantiene por separado, para que no puedan desincronizarse.
BRAND_ACCENT_RGB: tuple[int, int, int] = (79, 195, 255)  # TODO(orion-dev): reemplazar


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """Return the '#rrggbb' hex string for an (r, g, b) tuple."""
    return "#{:02x}{:02x}{:02x}".format(*rgb)


BRAND_ACCENT_HEX: str = _rgb_to_hex(BRAND_ACCENT_RGB)


def brand_accent_rgba(alpha: float) -> str:
    """Return the CSS rgba() string for the brand accent color at the given opacity."""
    r, g, b = BRAND_ACCENT_RGB
    return f"rgba({r}, {g}, {b}, {alpha})"
```

Notar que el valor inicial `(79, 195, 255)` es exactamente el `#4fc3ff` actual — un placeholder
neutro para que el código compile y los tests de estructura (import, QSS válido) pasen incluso
antes de que `orion-dev` tenga el tono real extraído del logo. `orion-dev` lo reemplaza como
último paso antes de cerrar CA-06 (ver Punto 3).

### Cambios de uso en los 3 (o 4) archivos QSS

Cada `_XXX_QSS` pasa de string literal a f-string, ej. en `header_bar.py`:

```python
from ui import theme

_HEADER_QSS = f"""
#HeaderBar {{ background-color: transparent; }}
#ModePill {{
    color: {theme.BRAND_ACCENT_HEX}; background-color: rgba(20, 40, 70, 0.6);
    ...
}}
...
#WakeIndicator[wakeState="LISTENING_WAKE"] {{ color: {theme.BRAND_ACCENT_HEX}; background-color: rgba(20, 40, 70, 0.6); }}
"""
```

(Llaves literales de QSS deben escaparse `{{ }}` al convertir a f-string — recordatorio para
`orion-dev`.) Mismo patrón en `center_panel.py` (`_CENTER_QSS`) y `sidebar.py` (`_SIDEBAR_QSS`,
usando `theme.brand_accent_rgba(0.12)` en vez de `rgba(79, 195, 255, 0.12)` literal).

## Flujo de datos

1. **Arranque (`main.py`)**: si `not headless` y `sys.platform == "win32"`, se llama
   `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)` **antes**
   de `QApplication(sys.argv)`. Esto fija la identidad de agrupación de Windows para el proceso
   actual, para que el taskbar no lo agrupe bajo el ícono genérico de `python.exe`.
2. `QApplication(sys.argv)` se crea; opcionalmente `app.setWindowIcon(QIcon(str(theme.WINDOW_ICON_PATH)))`
   se llama sobre la instancia de `QApplication` (refuerzo, no solo la ventana).
3. `JarvisMainWindow()` se instancia → `_init_ui()` llama `self.setWindowIcon(...)` con la misma
   ruta, y al final llama `self._setup_tray_icon()`, que carga el mismo `.ico` en el
   `QSystemTrayIcon`.
4. Los widgets (`HeaderBar`, `CenterPanel`, `Sidebar` y `SystemStatusCard`) importan
   `ui.theme` a nivel de módulo (import time, no runtime) y usan sus constantes al construir el
   QSS/QColor antes de `setStyleSheet()`/`paintEvent()`.
5. El `.ico` (`assets/branding/noddoo-icon.ico`) y el valor de `BRAND_ACCENT_RGB` en `theme.py` son
   **artefactos generados offline, una sola vez, durante `orion-dev`** — no se recalculan en cada
   arranque de la app. El único costo en runtime es leer el `.ico` ya generado desde disco.

## Archivos a modificar/crear

- `agente_ia/ui/theme.py` — **nuevo**.
- `agente_ia/main.py` — modificar.
- `agente_ia/ui/gui.py` — modificar.
- `agente_ia/ui/widgets/header_bar.py` — modificar.
- `agente_ia/ui/widgets/center_panel.py` — modificar.
- `agente_ia/ui/widgets/sidebar.py` — modificar.
- `agente_ia/ui/widgets/system_status_card.py` — modificar. **Expansión de alcance confirmada por
  Johan al aprobar esta arquitectura** (no estaba en "Módulos afectados" de SPEC-010, ver Punto 4).
- `agente_ia/assets/branding/noddoo-logo-full.png` — provisto por Johan (no generado, no consumido
  por código en este REQ — ver nota abajo).
- `agente_ia/assets/branding/noddoo-icon-mark.png` — provisto por Johan, fuente del `.ico`.
- `agente_ia/assets/branding/noddoo-icon.ico` — generado por `orion-dev` con el script del Punto 3.

**Nota sobre `noddoo-logo-full.png`:** SPEC-010/CA-05 exige verificar su existencia, pero ningún
flujo de código de este REQ lo carga o muestra — solo `noddoo-icon-mark.png` alimenta el `.ico` y,
por lo tanto, el ícono de ventana/taskbar/bandeja. `logo-full` queda guardado en el repo sin
consumidor en este REQ (probablemente para un uso futuro, ej. splash screen o about-dialog, fuera
de alcance). Se documenta para que `orion-dev` no asuma que debe insertarlo en algún widget.

## Dependencias nuevas

**Ninguna.** Se verificó `requirements.txt`: `Pillow` ya está listada (línea del bloque
"Automatización del PC (pyautogui)"), suficiente para generar el `.ico` multi-resolución y para el
script de extracción de color del Punto 3. No hace falta agregar ninguna línea nueva.

---

## Punto 1 — Ícono de la barra de tareas de Windows sin empaquetar (CA-02)

**Decisión:** combinar `ctypes` + `AppUserModelID` con `setWindowIcon()` a dos niveles
(QApplication y QMainWindow). Es la técnica estándar para este problema en apps PyQt/Tkinter no
empaquetadas en Windows, y no requiere introducir PyInstaller.

```python
# main.py, antes de crear QApplication, dentro de `if not headless:`
if sys.platform == "win32":
    try:
        import ctypes
        app_user_model_id = "Noddoo.JarvisGUI.1"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_user_model_id)
    except Exception as e:
        logger.warning(f"No se pudo fijar AppUserModelID: {e}")
```

**Por qué no está 100% garantizado:** `SetCurrentProcessExplicitAppUserModelID` resuelve el
problema de *agrupación* (que Windows no mezcle este proceso con otros `python.exe`), y
`setWindowIcon()` resuelve el ícono mostrado vía `WM_SETICON`, que es lo que la mayoría de
versiones de Windows 10/11 usan para el botón de la barra de tareas. En la práctica esta
combinación **suele ser suficiente** sin empaquetar, pero no hay garantía formal para todas las
builds de Windows/configuraciones de Explorer — de ahí que CA-02 ya esté marcado en la SPEC como
verificación manual, no test automatizado.

**Punto a confirmar con Johan en la aprobación de esta arquitectura:** si, tras la prueba manual de
CA-02, el ícono de taskbar sigue sin verse correcto con este mecanismo, la única alternativa
técnica adicional conocida es empaquetar con PyInstaller (que la SPEC deja fuera de alcance salvo
que se determine "la única vía viable" — Asumidos de SPEC-010). **No se recomienda introducir
PyInstaller en este REQ** salvo que la prueba manual falle y Johan lo autorice explícitamente en
una iteración posterior; se documenta como fallback conocido, no como plan activo.

## Punto 2 — Centralización del color de marca

**Decisión:** módulo nuevo `ui/theme.py` (ver "Nuevas clases/funciones" arriba). `BRAND_ACCENT_RGB`
es la única fuente de verdad; `BRAND_ACCENT_HEX` se deriva programáticamente (nunca se mantienen
dos constantes independientes que puedan desincronizarse). `brand_accent_rgba(alpha)` cubre el caso
de `sidebar.py`, que necesita el mismo tono con alpha `0.12` en vez de hex sólido.

Se descartó (i) un diccionario genérico de "tema" con muchas claves (excede el alcance — SPEC-010
no pide un sistema de theming completo, solo evitar el hex duplicado) y (ii) definir la constante
directamente en `ui/gui.py` e importarla desde ahí en los widgets (crearía una dependencia de los
widgets hacia el módulo de la ventana principal, invirtiendo la dirección de import actual del
proyecto — `gui.py` ya importa de `ui/widgets/*`, no al revés).

## Punto 3 — Extracción del tono de azul del degradé real

**Decisión:** script de un solo uso (dev-time), no parte del código de producción, con un método
determinista y reproducible: promedio de color ponderado por canal alfa sobre todos los píxeles no
totalmente transparentes de `noddoo-icon-mark.png`. Se prefiere sobre "elegir un píxel a ojo" o
usar un color picker externo porque es scriptable, reproducible, y deja registro exacto en el log
de desarrollo (consistente con el espíritu de CA-04, que exige documentar script/pasos, no un
valor puesto a mano sin trazabilidad).

```python
from PIL import Image

def extract_brand_accent(png_path: str) -> tuple[int, int, int]:
    """Compute a single representative RGB tone from the gradient logo, weighted by
    alpha so transparent/near-transparent pixels don't skew the average."""
    img = Image.open(png_path).convert("RGBA")
    total_r = total_g = total_b = total_weight = 0
    for r, g, b, a in img.getdata():
        if a == 0:
            continue
        total_r += r * a
        total_g += g * a
        total_b += b * a
        total_weight += a
    if total_weight == 0:
        raise ValueError(f"{png_path}: no hay píxeles con canal alfa > 0")
    return (
        round(total_r / total_weight),
        round(total_g / total_weight),
        round(total_b / total_weight),
    )
```

**Procedimiento para `orion-dev`:**
1. Correr este cálculo una vez sobre `assets/branding/noddoo-icon-mark.png` (script suelto en
   `scripts/` o ejecución interactiva puntual — no queda como parte del runtime de la app).
2. Copiar la tupla `(r, g, b)` resultante como valor literal de `BRAND_ACCENT_RGB` en
   `ui/theme.py`, reemplazando el placeholder `(79, 195, 255)`.
3. Documentar el valor resultante y el comando/script usado en `desarrollo-log-010.md` (trazabilidad
   para QA/prueba manual, ya que SPEC-010 no exige un test automatizado de hex exacto).

**Generación del `.ico` (CA-04)**, mismo espíritu de script de un solo uso:

```python
from PIL import Image

img = Image.open("assets/branding/noddoo-icon-mark.png").convert("RGBA")
img.save("assets/branding/noddoo-icon.ico", format="ICO",
         sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
```

`orion-dev` documenta este script (o uno equivalente) en `desarrollo-log-010.md`, tal como exige
CA-04 ("documentado con el script o pasos usados, no generado a mano fuera del repo").

## Punto 4 — `system_status_card.py:41` (hallazgo de `orion-baseline`, fuera de "Módulos afectados" de SPEC-010)

**Análisis:** es visualmente el mismo acento `#4fc3ff`/`rgb(79,195,255)` que los otros tres
archivos migrados — el arco de progreso de "salud del sistema" en `CircularProgress.paintEvent()`.
Si no se migra, quedaría un elemento visible de la GUI con el celeste genérico viejo mientras el
resto de los acentos (píldora de modo, foco de comando, highlight de sidebar, wake indicator) ya
muestran el tono de marca — inconsistencia visual directa, exactamente lo que SPEC-010 dice
resolver en su Objetivo ("aplicar el tono de azul del degradé del logo, de forma consistente,
sobre los acentos visuales de color que ya existen en la GUI").

**Mi recomendación fue incluirlo en el recoloreo, por consistencia** — es un cambio de una sola
línea (`QPen(QColor(79, 195, 255), 8)` → `QPen(QColor(*theme.BRAND_ACCENT_RGB), 8)`), mismo patrón
mecánico que los otros tres archivos, sin tocar el layout ni el comportamiento de
`CircularProgress`.

**RESUELTO — confirmado por Johan al aprobar esta arquitectura (2026-08-05):** SÍ se incluye
`system_status_card.py` en el alcance de recoloreo de REQ-010. Esto es una **expansión explícita
de alcance respecto de SPEC-010** (que no lo listaba en "Módulos afectados" ni en CA-06) —
autorizada verbalmente por Johan en la aprobación de arquitectura, documentada aquí y en
`REQ-010-context.md`, no asumida por `orion-architect`. `system_status_card.py` queda sumado a
"Módulos a modificar"/"Archivos a modificar/crear" arriba (ya no condicional) y `orion-dev` aplica
el mismo cambio de una línea descrito arriba.

## Riesgos y mitigación

| Riesgo | Mitigación |
|--------|-----------|
| `assets/branding/noddoo-*.png` no existen aún en el repo | Ya cubierto por CA-05 — `orion-dev` verifica antes de escribir código y reporta bloqueado si faltan; no bloquea spec/baseline/arquitectura. |
| `ctypes` + `AppUserModelID` no logra forzar el ícono correcto de taskbar en todas las configuraciones de Windows sin empaquetar | Verificación manual ya exigida por CA-02; si falla, se documenta como limitación conocida del entorno no empaquetado. Fallback (PyInstaller) queda fuera de alcance salvo autorización explícita posterior de Johan. |
| Caché de íconos de Windows (barra de tareas puede seguir mostrando el ícono viejo) | Ya aceptado en SPEC-010 como limitación conocida del SO, no bloqueante, sin CA automatizado — sin acción adicional en esta arquitectura. |
| `BRAND_ACCENT_HEX` y `BRAND_ACCENT_RGB` mantenidos como dos constantes independientes podrían desincronizarse | `ui/theme.py` deriva el hex de la tupla RGB programáticamente (`_rgb_to_hex`) — una sola fuente de verdad, imposible que diverjan. |
| Extracción de color por juicio visual/ad-hoc, no reproducible ni auditable | Método scriptado y determinista (promedio ponderado por alfa) especificado en el Punto 3, documentado en el log de desarrollo. |
| Canal alfa del PNG se pierde o se rellena con fondo sólido no deseado al generar el `.ico` | Script de generación abre explícitamente en modo `RGBA` (`Image.open(...).convert("RGBA")`) antes de `.save(format="ICO", ...)`, preservando transparencia. |
| Incluir `system_status_card.py` expande unilateralmente el alcance de una SPEC ya aprobada | Resuelto: Johan confirmó explícitamente la inclusión al aprobar esta arquitectura (Punto 4) — queda documentado como expansión de alcance autorizada, no como interpretación de `orion-architect`. |
| `ui/theme.py` importado por los 3-4 widgets podría introducir un ciclo de import si en el futuro depende de algo de `ui/gui.py` | Se especifica como módulo hoja: solo `pathlib` de la librería estándar, sin imports de PyQt6 ni de otros módulos del proyecto. |

## Pruebas sugeridas

- **CA-01:** test con `qtbot` que instancia `JarvisMainWindow`, y verifica
  `window.windowIcon().isNull() is False` tras `_init_ui()`.
- **CA-02:** sin test automatizado (ya así en la SPEC) — verificación manual; `orion-dev` documenta
  el mecanismo usado en `desarrollo-log-010.md`.
- **CA-03:** test que instancia la ventana y verifica que `window.tray_icon.icon().isNull() is False`,
  y que el ícono no proviene de un `QPixmap` rellenado en memoria (ej. mockeando `QIcon`/`QPixmap`
  y verificando que `_setup_tray_icon()` ya no llama `QPixmap(16, 16)`/`fill(QColor(0, 100, 255))`).
- **CA-04:** test que abre `assets/branding/noddoo-icon.ico` con Pillow y verifica que
  `Image.open(path)` reporta los 4 tamaños esperados (16, 32, 48, 256) — iterando
  `ImageSequence.Iterator` o `img.info` según cómo Pillow exponga los frames del `.ico`.
- **CA-05:** test unitario de la verificación de existencia de los 2 PNG (si `orion-dev` la aísla en
  una función), simulando ausencia con `tmp_path` y confirmando que reporta bloqueo sin lanzar una
  excepción no controlada.
- **CA-06:** test que verifica que `_HEADER_QSS`, `_CENTER_QSS`, `_SIDEBAR_QSS` y el `QPen` de
  `system_status_card.py` (expansión de alcance confirmada, Punto 4) ya no contienen el literal `"#4fc3ff"` ni
  `"79, 195, 255"` hardcodeado, y que sí contienen `theme.BRAND_ACCENT_HEX`/el valor derivado de
  `theme.BRAND_ACCENT_RGB`.
- **CA-07:** test (o verificación de diff) que confirma que `"#00e08a"` y `"#33d17a"` siguen
  presentes sin cambios en `header_bar.py`, `center_panel.py`, `sidebar.py`.
- **CA-08:** test que verifica que `_WAKE_STATE_ICONS == {"INACTIVE": "🎙", "LISTENING_WAKE": "🎙", "AWAKE": "🟢"}`
  sin cambios.
- **CA-09:** revisión de diff por `orion-tester`/`orion-qa` contra `baseline-010.md` — sin cambios
  en líneas de layout/tamaño/margen fuera de las explícitamente listadas aquí.
- **CA-10:** `python -m py_compile` sobre los módulos modificados + `pytest tests/` completo,
  comparado contra el baseline de `orion-baseline` (197 passed, 0 failed).
