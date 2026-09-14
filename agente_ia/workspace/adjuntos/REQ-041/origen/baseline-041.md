# Baseline REQ-041 — Rediseño de icono de app y de bandeja del sistema

## Estado actual del sistema

Hoy no existe ningún archivo `.ico`/`.png` de icono en el repo. El icono se genera 100% por
código, en tiempo de ejecución, con `QPainter`, en un único punto: `ui/webview/app_icon.py`.

### `ui/webview/app_icon.py` (único generador del icono hoy)
- `_ACENTO = "#58a6ff"` — azul plano, único color usado hoy (sin degradado).
- `_TAMANOS = (16, 24, 32, 48, 64, 128, 256)` — los 7 tamaños que se dibujan siempre, para
  todo uso (ventana, barra de tareas, alt-tab Y bandeja — hoy no hay distinción).
- `dibujar(size: int, color: Optional[str] = None) -> QPixmap`:
  - Fondo **transparente** (`Qt.GlobalColor.transparent`).
  - Dibuja un **anillo simple** (`drawEllipse` solo con `QPen`, `NoBrush`) — grosor
    proporcional (`size * 0.11`, mínimo 1.5px) — y un **punto centrado relleno**
    (`radio_punto = size * 0.17`), ambos del mismo color plano (`tinte`, por defecto
    `_ACENTO`, sin degradado).
  - No hay ningún trazo tipo arco/dasharray, ni múltiples anillos, ni nodo con radio fijo en
    unidades de un viewBox — todo está en proporciones directas de `size` en píxeles.
- `app_icon(color: Optional[str] = None) -> QIcon`: arma un único `QIcon` agregando
  `dibujar(size, color)` para cada tamaño de `_TAMANOS`. **Es el mismo objeto que se usa
  tanto para la ventana/taskbar como para la bandeja** — no hay una variante "app" y otra
  "bandeja", son idénticas salvo el tamaño con que Windows las escala.
- `fijar_identidad_en_windows()`: fija el `AppUserModelID` (`_APP_ID =
  "orion.agente.escritorio"`) vía `ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID`
  en Windows, no-op fuera de Windows, con manejo de excepción logueado (no silencioso). No
  tiene relación con el diseño visual del icono, solo con el agrupado en la barra de tareas.
  No se espera que este REQ lo toque.
- El docstring del módulo documenta explícitamente por qué se eligió dibujo procedural en
  vez de un `.ico` fijo: (a) el nombre del agente cambia (VIERNES/ORION/Noddoo) y no quería
  un logo con nombre incrustado — el REQ-041 confirma que el nuevo diseño tampoco lleva
  texto, así que este razonamiento sigue aplicando aunque cambie el mecanismo; (b) Qt elige
  la resolución exacta según dónde pinte, evitando escalado borroso — esto es relevante para
  la decisión abierta de `orion-architect` sobre mantener `QPainter` vs. pasar a asset
  estático (si se usa `.ico` pre-generado con múltiples resoluciones embebidas, este
  beneficio se conserva; si se usa un único PNG, se pierde nitidez en algunos tamaños).

### `ui/webview/main_window.py` — dos puntos de consumo, hoy idénticos
- **`~L72-76`** (dentro de `__init__` de la ventana principal):
  ```python
  icono = app_icon()
  self.setWindowIcon(icono)
  ...
  app.setWindowIcon(icono)
  ```
  Un solo `QIcon` se usa tanto para `self` (la ventana) como para la `QApplication` completa
  (que es lo que determina el icono del alt-tab/taskbar cuando no hay ventana activa).
- **`~L221-237`** (`_setup_tray_icon()`):
  ```python
  self.tray_icon = QSystemTrayIcon(self)
  self.tray_icon.setIcon(app_icon())          # L227 — MISMO app_icon(), sin variante
  self.tray_icon.setToolTip(f"{self._agent_name} — Panel de control")
  ...
  self.tray_icon.setContextMenu(menu)
  self.tray_icon.activated.connect(self._on_tray_activated)
  self.tray_icon.show()
  ```
  Confirmado: `_setup_tray_icon()` llama a `app_icon()` de nuevo (segunda instancia del
  mismo `QIcon`, no una reutilización del primero), pero con el mismo diseño — no hay hoy
  ninguna rama de código que dibuje algo distinto para la bandeja. El REQ-041 introduce esa
  bifurcación (variante monocroma sin degradado para bandeja).
  El tooltip (`f"{self._agent_name} — Panel de control"`, L228) no depende del icono y la
  SPEC exige explícitamente que siga funcionando sin cambios — no toca esta línea.
- `import` relevante: `from ui.webview.app_icon import app_icon` (L24). Si `orion-architect`
  decide separar la función de bandeja (p. ej. `tray_icon()` además de `app_icon()`), este
  import tendrá que ampliarse.

### `main.py` — orden de arranque (no se espera que cambie)
- `fijar_identidad_en_windows()` se llama antes de `QApplication(sys.argv)` (confirmado por
  grep: la primera aparece antes que la segunda en el archivo). El test
  `test_se_declara_antes_de_crear_la_ventana` verifica exactamente ese orden leyendo el
  código fuente como texto. Este REQ no debería tocar `main.py`.

### `tests/test_app_icon.py` — 6 tests, todos sobre el diseño VIEJO
1. `test_trae_todos_los_tamanos` — verifica que `app_icon().availableSizes()` incluya los 7
   tamaños de `_TAMANOS`. **Sigue aplicando en espíritu** al diseño nuevo (la SPEC mantiene
   los mismos 7 tamaños para el icono de app).
2. `test_el_fondo_es_transparente` — verifica `pixelColor(0,0).alpha() == 0` en la esquina de
   `dibujar(64)`. **Queda obsoleto para el icono de app**: la SPEC exige fondo negro sólido
   `#0a0a0b`, no transparente. Debe reescribirse (y la SPEC ya lo anticipa como criterio de
   aceptación).
3. `test_a_16_pixeles_todavia_hay_una_figura` — cuenta píxeles con alpha > 40 en `dibujar(16)`
   y exige que estén entre 15% y 80% del total. Depende de que exista transparencia real
   (fondo transparente) para poder contar "tinta vs. hueco" por alpha. Con fondo opaco
   sólido esta técnica de conteo por alpha deja de servir tal cual — debe adaptarse (p. ej.
   contando por diferencia de color entre trazo/nodo y fondo, no por alpha).
4. `test_no_es_el_cuadrado_liso_de_antes` — verifica que las 4 esquinas de `dibujar(16)`
   sigan con alpha 0. Mismo problema que el anterior: con fondo negro sólido las esquinas ya
   no son transparentes por diseño (son parte del cuadrado con esquinas redondeadas del
   Concepto A) — este test deja de tener sentido tal cual y debe reescribirse o eliminarse,
   documentando por qué.
5. `test_la_app_declara_su_propia_identidad_en_windows` — prueba `fijar_identidad_en_windows()`
   y el `AppUserModelID`. No depende del diseño visual — **no debería requerir cambios**.
6. `test_se_declara_antes_de_crear_la_ventana` — lee `main.py` como texto y verifica el
   orden. No depende del diseño visual — **no debería requerir cambios**.

Ejecución real de este archivo en este baseline: **6 passed** (ver sección de fallos
pre-existentes) — confirma que hoy el diseño viejo pasa sus propios tests, como es esperable
antes de tocar nada.

## Archivos que serán modificados (previsión)

- `ui/webview/app_icon.py` — reescritura completa del dibujo (`dibujar()`/`app_icon()`),
  posible función nueva para la variante de bandeja, posible eliminación/reutilización de
  `_ACENTO` y del parámetro `color` (la SPEC no lo exige pero lo permite). No se espera tocar
  `fijar_identidad_en_windows()` ni `_APP_ID`.
- `ui/webview/main_window.py` — línea `~L227` (`self.tray_icon.setIcon(app_icon())`) pasará a
  usar la variante de bandeja en vez de `app_icon()` genérico, si `orion-architect` decide
  separar ambas funciones. Las líneas `~L72-76` (ventana/`QApplication`) probablemente sigan
  usando `app_icon()` sin cambios de firma, solo cambia lo que dibuja internamente.
- `tests/test_app_icon.py` — reescritura de `test_el_fondo_es_transparente` y
  `test_no_es_el_cuadrado_liso_de_antes` (ya no aplican al fondo negro sólido del icono de
  app), adaptación de `test_a_16_pixeles_todavia_hay_una_figura` (el conteo por alpha deja de
  servir con fondo opaco), y probablemente tests nuevos para la variante de bandeja
  (monocromo, chip `#1b1b1d`, sin degradado). Los 2 tests de `AppUserModelID`/orden de
  arranque no deberían cambiar.
- `main.py` — no se prevé cambio real; queda listado porque un test ya lo verifica y
  cualquier reordenamiento accidental de imports podría afectarlo.
- Posibles archivos NUEVOS (no reemplazos, ya que hoy no existe ninguno): si
  `orion-architect` elige assets estáticos en vez de dibujo procedural, aparecerían
  `.ico`/`.png`/`.svg` nuevos en el repo (ubicación a definir en arquitectura).

## Fallos pre-existentes (no atribuibles a este REQ)

`tests/test_app_icon.py` (el área que este REQ toca): **0 fallos** — los 6 tests pasan hoy
sobre el diseño viejo (esperado, ya que aún no se tocó nada).

`python -m py_compile` sobre los 4 archivos afectados (`ui/webview/app_icon.py`,
`ui/webview/main_window.py`, `tests/test_app_icon.py`, `main.py`): **sin errores**.

Suite completa (`python -m pytest tests/ --tb=line -q`, 2026-09-12): **42 failed, 2725
passed, 1 skipped, 4 errors** en 185.6s. Ninguno de los archivos que toca este REQ aparece
en la lista de fallos. Desglose de los fallos existentes, agrupados por causa raíz (todas
por dependencias opcionales no instaladas en este entorno, no por lógica rota):

- `tests/test_documentos.py` (28 fallos + 4 errores) — `ModuleNotFoundError: No module named
  'docx'` (y variantes con PowerPoint/Excel) al ejercitar `core/documentos.py::_docx()` y
  funciones hermanas de generación/edición de documentos Office. No relacionado con iconos.
- `tests/test_ui_tree.py` (13 fallos) — `ModuleNotFoundError: No module named 'uiautomation'`
  al importar el módulo de automatización de UI de Windows. No relacionado con iconos.
- `tests/test_code_index.py::test_el_indexado_se_puede_cortar_y_continuar` (1 fallo en la
  corrida completa) — al ejecutarlo aislado (`pytest tests/test_code_index.py::...`) **pasa**;
  es un fallo dependiente del orden/estado compartido entre tests (posible contaminación de
  estado global o de archivo temporal entre módulos de test), no de lógica de icono ni de
  UI. Se deja registrado como flaky pre-existente para que `orion-tester` no lo confunda con
  algo roto por REQ-041.

Ninguno de estos 42 fallos + 4 errores toca `ui/webview/app_icon.py`, `ui/webview/main_window.py`,
`tests/test_app_icon.py` ni `main.py`. Si tras la implementación de REQ-041 estos mismos
archivos (`test_documentos.py`, `test_ui_tree.py`, `test_code_index.py`) siguen fallando por
las mismas causas, no es una regresión de este REQ.
