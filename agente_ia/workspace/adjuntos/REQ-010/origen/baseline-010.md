# Baseline REQ-010 — Branding visual Noddoo (íconos + colores GUI)

**Fecha:** 2026-08-05
**Agente:** orion-baseline

## Estado actual del sistema

### Ícono de ventana (`ui/gui.py`)
- `JarvisMainWindow._init_ui()` (líneas 99-139) NO llama a `setWindowIcon()` en ningún punto.
  La ventana usa el ícono default de Qt/`python.exe` — confirma el comportamiento descrito en
  SPEC-010 ("Comportamiento actual vs deseado", fila 1).
- `main.py:187-197` lanza `JarvisMainWindow()` + `window.showMaximized()` solo si no se pasa
  `--headless` y el import de `ui.gui` no falla (fallback a modo headless si PyQt6/la GUI no
  están disponibles).

### Ícono de bandeja del sistema (`ui/gui.py::_setup_tray_icon()`, líneas 193-207)
- Dibuja un `QPixmap(16, 16)` relleno con `QColor(0, 100, 255)` (azul sólido genérico, sin
  degradé ni archivo de imagen) y lo envuelve en `QIcon(pixmap)` (línea 195-197).
- El resto de la función (menú contextual "Mostrar/Ocultar" / "Salir", `activated` →
  `_on_tray_activated`, conexión a `aboutToQuit` para detener el wake word worker) es lógica de
  comportamiento que SPEC-010 exige dejar intacta (Casos borde, última viñeta) — solo cambia la
  fuente del ícono.
- No existe ningún ícono `.ico` ni carga desde archivo en el módulo — imports actuales de
  `PyQt6.QtGui`: `QColor, QIcon, QPixmap` (línea 18).

### Carpeta `assets/branding/`
- **No existe todavía en el repo** (`Glob assets/**` no devuelve resultados). Confirma el
  riesgo ya documentado en `REQ-010-context.md`: ni `noddoo-logo-full.png` ni
  `noddoo-icon-mark.png` están presentes. Este es un bloqueo conocido exclusivamente para
  `orion-dev` (CA-05 de la SPEC) — no bloquea baseline ni arquitectura.

### Acentos de color `#4fc3ff` — inventario exacto encontrado

| Archivo | Línea | Selector / contexto | Valor |
|---|---|---|---|
| `ui/widgets/header_bar.py` | 84 | `#ModePill { color: #4fc3ff; ... }` (píldora "Modo activo") | `#4fc3ff` |
| `ui/widgets/header_bar.py` | 97 | `#WakeIndicator[wakeState="LISTENING_WAKE"] { color: #4fc3ff; ... }` | `#4fc3ff` |
| `ui/widgets/center_panel.py` | 162 | `#VoiceStatusLabel { color: #4fc3ff; ... }` | `#4fc3ff` |
| `ui/widgets/center_panel.py` | 168 | `#CommandSendButton { ...; color: #4fc3ff; ... }` (botón enviar ➤) | `#4fc3ff` |
| `ui/widgets/center_panel.py` | 177 | `#WakeToggleButton[wakeState="LISTENING_WAKE"] { color: #4fc3ff; border: 1px solid #4fc3ff; }` | `#4fc3ff` (x2) |
| `ui/widgets/sidebar.py` | 78 | `#SidebarNavButton:enabled { ...; background-color: rgba(79, 195, 255, 0.12); }` | `rgba(79,195,255,...)` = `#4fc3ff` en RGBA |

Todos estos usos están dentro de bloques QSS como constantes de módulo (`_HEADER_QSS`,
`_CENTER_QSS`, `_SIDEBAR_QSS`) aplicados vía `setStyleSheet()` — no hay un módulo de tema/color
centralizado hoy; el hex está repetido de forma suelta en cada archivo.

### Hallazgo no cubierto explícitamente por "Módulos afectados" de SPEC-010
- `ui/widgets/system_status_card.py:41` usa el mismo azul en su variante RGB de código Qt (no
  QSS): `QPen(QColor(79, 195, 255), 8)` — es el color del arco de progreso ("salud del
  sistema") en `CircularProgress.paintEvent()`. Es visualmente el mismo acento `#4fc3ff` que
  los otros tres archivos, pero la SPEC-010 solo lista `header_bar.py`, `center_panel.py` y
  `sidebar.py` en "Módulos afectados" y en CA-06. **Se documenta aquí para que
  `orion-architect` decida explícitamente si incluirlo en el alcance de recoloreo o dejarlo
  fuera** — no se asume ninguna de las dos opciones en este baseline.

### Colores explícitamente fuera de alcance (verificados, sin tocar)
- `#00e08a` — estado "despierto" del wake word: `header_bar.py:98`, `center_panel.py:180`.
- `#33d17a` — `sidebar.py:80` (`#SidebarStatusActive`).
- Confirmado que ninguno de los dos aparece en los archivos ni líneas listadas como "en
  alcance" — no hay riesgo de confusión de recoloreo accidental.

## Archivos que serán modificados (previsión)

- `agente_ia/ui/gui.py` — agregar `setWindowIcon()`; reemplazar el `QPixmap` dibujado a mano en
  `_setup_tray_icon()` por carga de ícono real desde `assets/branding/`; posible mecanismo
  adicional (p. ej. `ctypes` AppUserModelID) para el ícono de la barra de tareas de Windows.
- `agente_ia/ui/widgets/header_bar.py` — migrar `#4fc3ff` (líneas 84 y 97) a la constante de
  color de marca que defina `orion-architect`.
- `agente_ia/ui/widgets/center_panel.py` — migrar `#4fc3ff` (líneas 162, 168, 177) a la misma
  constante.
- `agente_ia/ui/widgets/sidebar.py` — migrar `rgba(79, 195, 255, 0.12)` (línea 78) a la misma
  constante (con el alpha existente preservado).
- `agente_ia/assets/branding/` (carpeta nueva, no existe hoy) — destino de
  `noddoo-logo-full.png`, `noddoo-icon-mark.png` (provistos por Johan) y el `.ico`
  multi-resolución generado por `orion-dev` con Pillow.
- Posible archivo nuevo de módulo/constante de color centralizado (nombre y ubicación a
  definir por `orion-architect` — SPEC-010 no lo fija).
- `agente_ia/ui/widgets/system_status_card.py` (línea 41) — **candidato posible**, pendiente de
  decisión explícita de `orion-architect` (ver hallazgo arriba); no confirmado como "será
  modificado".

## Fallos pre-existentes (no atribuibles a este REQ)

- **Ninguno.** `python -m py_compile` sobre los 6 módulos relevantes
  (`ui/gui.py`, `ui/widgets/header_bar.py`, `ui/widgets/center_panel.py`,
  `ui/widgets/sidebar.py`, `ui/widgets/system_status_card.py`, `ui/widgets/right_panel.py`)
  compila sin errores.
- `pytest tests/ --tb=short` completo: **197 passed, 0 failed** (3 warnings no relacionados:
  2 `DeprecationWarning` de `speech_recognition`/`aifc`/`audioop` de terceros, 1
  `PytestReturnNotNoneWarning` en `tests/test_agents.py::test_ca1_orchestrator` — preexistente,
  no relacionado con GUI/branding).
- No existen tests hoy que cubran `setWindowIcon()`, `_setup_tray_icon()` ni los colores QSS de
  los widgets afectados (`tests/test_gui_widgets.py` no tiene ningún match para
  `tray|setWindowIcon|QIcon`) — confirma que CA-10 ("pytest no introduce ningún fallo nuevo")
  parte de una base limpia sin cobertura previa de íconos, y que cualquier test nuevo de
  `orion-tester` para CA-01/CA-03/CA-04/CA-06 será enteramente nuevo, no una modificación de
  test existente.

## Nota sobre CA-02 (ícono de barra de tareas de Windows)
No hay empaquetado con PyInstaller ni `.spec` en el repo — se confirma corriendo
`python main.py` directo (ver `main.py:187-197`). Esto es exactamente el riesgo ya anotado en
`REQ-010-context.md` bajo "Riesgos activos"; queda para `orion-architect` definir el mecanismo
técnico (p. ej. `ctypes` AppUserModelID).
