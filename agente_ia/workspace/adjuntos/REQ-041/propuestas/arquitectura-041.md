# Arquitectura REQ-041 — Rediseño del icono de app y del icono de bandeja

## Decisión de mecanismo (lo que la SPEC dejó abierto)

**Se pasa de dibujo procedural puro con `QPainter` a un asset vectorial embebido**: la
geometría exacta del canvas aprobado se guarda como **strings SVG construidos desde
constantes Python** (no archivos `.svg`/`.ico`/`.png` en el repo) y se rasteriza en cada
tamaño con `QSvgRenderer` (`PyQt6.QtSvg`) sobre un `QPixmap`, dentro del mismo
`QPainter`/`QPen` que ya se usaba — no se reemplaza el mecanismo de "generar en tiempo de
ejecución, nítido en cada tamaño que Windows pida", solo lo que se dibuja.

**Por qué no `QPainter` puro (arcos manuales):**
`stroke-dasharray="180 30"` sobre una circunferencia de radio 46 (perímetro ≈289.03) con
solo dos números en el patrón se reduce matemáticamente a **un solo arco continuo con un
solo hueco** por anillo (259.03 unidades de trazo ≈ 322.7°, un hueco de 30 unidades ≈
37.3°) — así que SÍ sería viable reconstruirlo con `drawArc`/`QPainterPath.arcMoveTo` sin
librerías nuevas. Pero el degradado lineal (`userSpaceOnUse`, tres paradas) y el offset de
rotación de cada anillo habría que replicarlos a mano con `QLinearGradient` + trigonometría
por anillo, con riesgo real de desviarse un poco del canvas real cada vez que alguien
retoque el código — justo lo que la SPEC prohíbe ("no hay margen de reinterpretación de la
forma").

**Por qué SVG + `QSvgRenderer` sí:** permite pegar los números del canvas (`cx`, `cy`, `r`,
`stroke-dasharray`, `stroke-dashoffset`, paradas del gradiente) **tal cual**, sin ninguna
conversión manual a ángulos. Se validó empíricamente en el entorno real de este proyecto
(no es una suposición):

```
python -c "from PyQt6.QtSvg import QSvgRenderer" → OK, sin instalar nada
PyQt6 6.11.0 / Qt 6.11.0 instalados
```

Y renderizando el SVG exacto de la especificación (gradiente + 3 `<circle>` con
`stroke-dasharray`/`stroke-dashoffset` + fondo con esquinas redondeadas) a 16/24/32/48/64/
128/256 px con `QSvgRenderer.render(painter, QRectF(0,0,size,size))`: el degradado se ve
correctamente, el `dasharray`/`dashoffset` se respeta, y el rect con `rx` deja las 4
esquinas verdaderamente transparentes (alpha 0) incluso a 16 px — ver "Riesgos" para el
único hallazgo relevante de esa prueba (legibilidad del icono de app a 16 px).

**Dependencias nuevas: ninguna.** `PyQt6.QtSvg.QSvgRenderer` viene incluido en el paquete
`PyQt6` que ya está en `requirements.txt` (no es un componente aparte como
`PyQt6-WebEngine`). No se toca `requirements.txt`.

## Cobertura de criterios de la SPEC

| Criterio (SPEC-041) | Cómo lo satisface esta propuesta |
|---|---|
| Icono de app (16–256 px) muestra el Concepto A sin recortes ni deformación | `_app_icon_svg()` genera UN SOLO SVG de aspecto 1:1 (viewBox 240×240); `QSvgRenderer` lo escala uniformemente a cada tamaño de `_TAMANOS`, validado en los 7 tamaños |
| Ningún tamaño muestra el diseño anterior (anillo+punto azul) | `dibujar()`/`_ACENTO` viejos se eliminan por completo; `app_icon()` solo llama a `dibujar_app()`, que solo sabe dibujar el Concepto A |
| Icono de bandeja usa variante simplificada/monocroma (`#f2f2f3` sin degradado, chip `#1b1b1d`) a 16/24 px, distinta del icono de app reescalado | Nueva función pública `bandeja_icon()` + `_tray_icon_svg(size)`: SVG estructuralmente distinto (sin `<linearGradient>`, colores planos, fondo propio), no una reutilización escalada de `_app_icon_svg()` |
| En "iconos ocultos" la marca de bandeja se sigue reconociendo (no mancha) | `stroke-width`/`node_r` de bandeja usan los valores más gruesos de la SPEC (8/10 y 10/12) sobre el mismo espacio 200×200 de los anillos; render de prueba a 16 y 24 px da 19–23% de píxeles "de trazo" distribuidos en 3 arcos + nodo, no un bloque sólido ni casi vacío |
| Tooltip de bandeja sigue funcionando sin cambios | `main_window.py` L228 (`setToolTip`) no se toca; este REQ no toca `_agent_name` |
| `fijar_identidad_en_windows()` sigue antes de `QApplication` | `main.py` no se modifica; el orden de llamadas no depende de qué dibuja `app_icon.py` |
| `tests/test_app_icon.py` actualizado para la forma nueva | Ver "Pruebas sugeridas" — 2 tests se reescriben, 1 se adapta, se agregan tests nuevos para bandeja, 2 quedan intactos |
| `pytest tests/test_app_icon.py -v` pasa completo | Diseño en funciones puras (`dibujar_app`/`dibujar_bandeja` devuelven `QPixmap` desde un string SVG determinista) — fácil de testear sin mocks nuevos |
| No quedan referencias a `_ACENTO`/color anterior salvo justificado | `_ACENTO` y el parámetro `color` de `dibujar()` se eliminan enteros (confirmado como aceptable en ASUMIDO 3 de la SPEC, aprobado por el humano) |

## Módulos a modificar

- `ui/webview/app_icon.py` — reescritura completa del generador de iconos.
- `ui/webview/main_window.py` — import y el punto donde se arma el `QSystemTrayIcon`
  (`~L227`).
- `tests/test_app_icon.py` — reescritura parcial (ver "Pruebas sugeridas").

No se crean archivos nuevos. No hay `.ico`/`.png`/`.svg` en el repo antes ni después de
este REQ — el SVG vive como strings Python dentro de `app_icon.py`, generado desde
constantes, igual que hoy el dibujo procedural vivía como llamadas a `QPainter`.

## Nuevas clases/funciones

Todo en `ui/webview/app_icon.py` (ningún archivo nuevo, ninguna clase — se mantiene el
estilo de funciones sueltas del módulo actual):

- **Constantes de geometría compartida** (la "familia" de marca, sección "Especificación
  exacta" de SPEC-041, transcritas literalmente sin aritmética):
  - `_RINGS`: los 3 `(cx, cy, dashoffset)` — `(100.0, 76.0, 0)`, `(120.8, 112.0, 96)`,
    `(79.2, 112.0, 192)`.
  - `_RING_R = 46.0`, `_RING_DASHARRAY = "180 30"`, `_NODE_CENTER = (100.0, 100.0)`.
  - `_GRADIENT_ID`, `_GRADIENT_DEF` — el `<linearGradient>` con las 3 paradas exactas.
- **Constantes del icono de app**: `_APP_BG = "#0a0a0b"`, `_APP_CANVAS = 240`,
  `_APP_BG_RX = 54`, `_APP_MARCA_SCALE = 0.9` (=180/200, la marca ocupa el 75% de 240),
  `_APP_MARCA_OFFSET = 30` (=(240-180)/2), `_APP_RING_STROKE_WIDTH = 3.2`,
  `_APP_NODE_R = 8.5`. `_TAMANOS = (16, 24, 32, 48, 64, 128, 256)` se mantiene sin cambios.
- **Constantes del icono de bandeja**: `_TRAY_BG = "#1b1b1d"`, `_TRAY_STROKE = "#f2f2f3"`,
  `_TRAY_VARIANTS = {24: dict(corner_rx=5, stroke_width=8, node_r=10), 16: dict(corner_rx=4,
  stroke_width=10, node_r=12)}`, `_TRAY_TAMANOS = (16, 24)`.
- **`_marca_svg(*, stroke: str, stroke_width: float, node_r: float) -> str`** — construye
  los 3 `<circle>` de los anillos + el `<circle>` relleno del nodo, en el viewBox nativo
  200×200 de `_RINGS`. `stroke` acepta un color plano (bandeja) o `"url(#id)"` (app, con
  degradado). Es el único lugar que conoce la geometría de los anillos — la comparte el
  icono de app y el de bandeja, así que un ajuste futuro de geometría no puede quedar
  desincronizado entre ambos.
- **`_app_icon_svg() -> str`** — arma el SVG completo del icono de app: `viewBox="0 0 240
  240"`, `<defs>` con el gradiente, `<rect rx=54>` de fondo, y `_marca_svg(...)` envuelta en
  `<g transform="translate(30,30) scale(0.9)">`.
- **`_tray_icon_svg(size: int) -> str`** — arma el SVG del icono de bandeja para `size` (16
  o 24; `_TRAY_VARIANTS[size]` lanza `KeyError` si se pide otro tamaño, a propósito: no hay
  ningún tamaño de bandeja "razonable por defecto", solo los 2 que pide la SPEC). Estructura:
  `viewBox="0 0 {size} {size}"` (el propio tamaño final, no 200×200), `<rect rx=...>` de
  fondo en ESE espacio, y `_marca_svg(...)` envuelta en `<g transform="scale(size/200)">`
  para llevar la geometría nativa 200×200 al tamaño final. Ver "Riesgos" sobre por qué el
  fondo y la marca usan dos sistemas de coordenadas distintos dentro del mismo SVG.
- **`_render_svg(svg: str, size: int) -> QPixmap`** — reemplaza el cuerpo de la vieja
  `dibujar()`: crea un `QSvgRenderer` desde el string, pinta sobre un `QPixmap(size, size)`
  con fondo inicial transparente (relevante solo para las esquinas fuera del `rx`, que el
  `<rect>` redondeado deja sin pintar) y `Antialiasing` activado, igual que antes.
- **`dibujar_app(size: int) -> QPixmap`** — `_render_svg(_app_icon_svg(), size)`.
  Reemplaza a la vieja `dibujar(size, color)` para el caso de app (ya no recibe `color`).
- **`dibujar_bandeja(size: int) -> QPixmap`** — `_render_svg(_tray_icon_svg(size), size)`.
  Función nueva.
- **`app_icon() -> QIcon`** — firma pública sin cambios salvo que pierde el parámetro
  `color` (confirmado en ASUMIDO 3); arma el `QIcon` iterando `_TAMANOS` con `dibujar_app`.
- **`bandeja_icon() -> QIcon`** — función pública nueva, arma el `QIcon` iterando
  `_TRAY_TAMANOS` con `dibujar_bandeja`. **Nombrada así y no `tray_icon()` a propósito**:
  `main_window.py` ya tiene un atributo de instancia `self.tray_icon` (el
  `QSystemTrayIcon`); importar una función `tray_icon` en el mismo archivo no rompería nada
  en tiempo de ejecución (son namespaces distintos) pero sería confuso de leer al lado de
  `self.tray_icon.setIcon(tray_icon())`.
- `fijar_identidad_en_windows()`, `_APP_ID` — sin cambios.
- `_ACENTO` y el parámetro `color` de la vieja `dibujar()` — **eliminados**, no reemplazados
  (confirmado aceptable en ASUMIDO 3 de SPEC-041).

## Flujo de datos

No hay entrada de usuario ni de red: es generación pura a partir de constantes.

```
constantes de geometría (_RINGS, _APP_*, _TRAY_VARIANTS)
        │
        ▼
_marca_svg(...)  ──► string SVG de los 3 anillos + nodo (sin fondo)
        │
        ▼
_app_icon_svg() / _tray_icon_svg(size)  ──► string SVG completo (fondo + marca envuelta)
        │
        ▼
_render_svg(svg, size)  ──► QSvgRenderer parsea el string, QPainter lo pinta sobre un
        │                    QPixmap(size, size) nuevo
        ▼
dibujar_app(size) / dibujar_bandeja(size)  ──► QPixmap de un tamaño
        │
        ▼
app_icon() / bandeja_icon()  ──► QIcon con todos los QPixmap de _TAMANOS / _TRAY_TAMANOS
        │
        ▼
main_window.py:
  ~L72-76   MainWindow.setWindowIcon(app_icon()) + QApplication.setWindowIcon(app_icon())
  ~L227     self.tray_icon.setIcon(bandeja_icon())   ← ÚNICO cambio de comportamiento real
```

## Archivos a modificar/crear

- `ui/webview/app_icon.py` (reescritura completa — ver "Nuevas clases/funciones")
- `ui/webview/main_window.py`:
  - Import: `from ui.webview.app_icon import app_icon, bandeja_icon` (agrega
    `bandeja_icon`, `app_icon` se mantiene).
  - `~L227`: `self.tray_icon.setIcon(app_icon())` → `self.tray_icon.setIcon(bandeja_icon())`.
  - `~L72-76`: sin cambios de código (siguen llamando a `app_icon()`, ahora sin `color`;
    ya se llamaba sin ese argumento, así que no hay diff real ahí).
- `tests/test_app_icon.py` (reescritura parcial — ver "Pruebas sugeridas")

No se toca `main.py`, `_APP_ID`, ni `fijar_identidad_en_windows()`.

## Dependencias nuevas

Ninguna. `PyQt6.QtSvg` (incluye `QSvgRenderer`) ya está disponible con el `PyQt6` instalado
hoy — verificado en el entorno real del proyecto (`PyQt6 6.11.0` / `Qt 6.11.0`), sin
necesidad de instalar `PyQt6-Svg` ni tocar `requirements.txt`.

## Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| **Medido, no hipotético**: renderizando el icono de app EXACTO de la SPEC a 16 px, solo ≈0.8% de los píxeles se distinguen del fondo negro (2 de 256) — el trazo de 3.2 (escalado a través de `scale(0.9)` y luego a 16/240) queda por debajo de 1 px real. El test viejo exigía 15%–80% "pintado"; con la geometría exacta y fiel al canvas, el icono de APP a 16 px es casi indistinguible de un cuadrado negro liso. | No se reinterpreta la geometría (la SPEC lo prohíbe explícitamente y así lo pidió el humano en el canvas). Se documenta el hallazgo aquí, se ajusta el UMBRAL NUMÉRICO del test adaptado (no su intención) para reflejar este comportamiento esperado por diseño, y se recomienda que el humano/`orion-ui` vea un PNG real de `dibujar_app(16)` antes de cerrar el REQ. Nota de contexto: Windows rara vez muestra el icono de VENTANA (no bandeja) a 16 px literales en uso real — taskbar/alt-tab usan tamaños mayores en la práctica — así que el impacto es más cosmético que funcional, pero debe confirmarse con una imagen real, no asumirse. |
| Ambigüedad en la SPEC sobre si `stroke-width`/`node_r`/`corner_rx` de bandeja están en el espacio 200×200 de los anillos o en píxeles finales literales (el texto dice "(sobre el mismo viewBox 200×200)" solo para `stroke-width`, no lo repite para `node_r` ni para el radio del chip). | Resuelto con DOS sistemas de coordenadas dentro del mismo SVG de bandeja: el `<rect>` de fondo vive en el espacio final (`viewBox="0 0 {size} {size}"`, `rx` literal 5 o 4 sin escalar), y la marca vive dentro de un `<g transform="scale(size/200)">` en su espacio nativo 200×200 (`stroke-width`/`node_r` literales 8/10/10/12 tal como los da la SPEC, que SÍ se escalan junto con el resto de la marca). Esto satisface ambas lecturas a la vez sin inventar ningún número — validado con un render de prueba en este entorno. |
| Soporte de `QSvgRenderer` para `stroke-dasharray`/`stroke-dashoffset`/gradientes puede variar entre versiones de Qt. | Validado empíricamente en el Qt/PyQt6 real de este proyecto (6.11.0), no asumido. Si el entorno de build/distribución final usa una versión de Qt bastante más vieja, `orion-dev` debe repetir la verificación (`QSvgRenderer(...).isValid()` + inspección de píxeles) antes de dar la implementación por buena. |
| El fondo pasa de transparente a negro sólido (`#0a0a0b`); si la taskbar de Windows algún día no es negra pura, podría notarse un borde sutil entre el icono y el fondo real. | Es una decisión de diseño ya aprobada por el humano en el canvas (caso borde ya resuelto en la SPEC: "el humano indicó que no hace falta que orion-ui lo revise aparte"); no es un problema de arquitectura, se deja constancia por si `orion-qa` lo nota. |
| `bandeja_icon()`/`dibujar_bandeja()` con un `size` fuera de `{16, 24}` lanza `KeyError` sin mensaje descriptivo. | Aceptado a propósito: es un error de programación (nadie debería pedir un tamaño de bandeja que la SPEC no define), no una entrada de usuario — no amerita un `try/except` que lo silencie. Si `orion-dev` prefiere un mensaje más claro, puede envolver el `KeyError` en un `ValueError` con el tamaño pedido, sin cambiar el comportamiento de fallar rápido. |

## Pruebas sugeridas

Todas en `tests/test_app_icon.py`, siguiendo la convención de `qapp` (fixture `offscreen`)
ya existente:

1. `test_trae_todos_los_tamanos` — **sin cambios**, sigue verificando
   `app_icon().availableSizes()` contra `_TAMANOS`.
2. **Nuevo** `test_bandeja_trae_los_dos_tamanos` — `bandeja_icon().availableSizes()`
   incluye `(16,16)` y `(24,24)`.
3. **Reescribir** `test_el_fondo_es_transparente` → renombrar a
   `test_el_fondo_del_icono_de_app_es_negro_solido`: verificar que un punto del borde
   (dentro del `rect` redondeado, ej. `(size//2, 1)`, no la esquina) de `dibujar_app(64)`
   sea `#0a0a0b` con alpha 255 — el fondo ahora es opaco a propósito.
4. **Reescribir** `test_no_es_el_cuadrado_liso_de_antes` → renombrar a
   `test_las_esquinas_del_icono_de_app_son_transparentes_por_el_redondeo`: las 4 esquinas
   de `dibujar_app(64)` (no 16, para tener margen de antialiasing) siguen con alpha 0 —
   ahora por el `rx` del `rect`, no por transparencia total; el docstring debe decir
   explícitamente por qué cambió el motivo aunque el resultado (esquina transparente) se
   mantenga.
5. **Adaptar** `test_a_16_pixeles_todavia_hay_una_figura`: cambiar el conteo de "alpha >
   40" a "color perceptiblemente distinto del fondo `#0a0a0b`" (con fondo opaco, alpha ya
   no sirve para distinguir tinta de hueco). Ajustar el rango numérico según el hallazgo de
   esta arquitectura (~0.8% a 16 px con la geometría exacta): exigir "más de 0 píxeles
   distintos del fondo" en vez del viejo 15%–80%, y documentar en el docstring por qué el
   umbral es tan bajo (referencia a `arquitectura-041.md`, sección Riesgos).
6. **Nuevo** `test_bandeja_16_y_24_son_legibles`: mismo tipo de conteo que el anterior
   pero sobre `dibujar_bandeja(16)` y `dibujar_bandeja(24)`, con un rango más exigente dado
   el trazo más grueso (referencia empírica: ~19–23% de píxeles de trazo/nodo; sugerido
   10%–40% de margen).
7. **Nuevo** `test_bandeja_usa_color_plano_sin_degradado`: dos píxeles distintos sobre el
   mismo trazo de `dibujar_bandeja(24)` deben tener el mismo color exacto (`#f2f2f3`) — a
   diferencia del icono de app, donde el color varía por posición por el degradado. Forma
   determinista de verificar "sin degradado" sin parsear el SVG generado.
8. **Nuevo** `test_bandeja_no_es_el_icono_de_app_reescalado`: el color de fondo de
   `dibujar_bandeja(24)` (`#1b1b1d`) debe ser distinto del de `dibujar_app(24)` reescalado
   (`#0a0a0b`) — verifica directamente el criterio de aceptación "no es el mismo icono de
   app reescalado".
9. `test_la_app_declara_su_propia_identidad_en_windows` — **sin cambios**.
10. `test_se_declara_antes_de_crear_la_ventana` — **sin cambios**.

Ejecución final esperada: `python -m pytest tests/test_app_icon.py --tb=short -v` en 10/10
verde. `orion-tester` debe además correr la suite completa y comparar contra los 42
failed/1 skipped/4 errors ya documentados en `baseline-041.md` (todos por dependencias
opcionales ausentes en `test_documentos.py`/`test_ui_tree.py`, más el flaky de
`test_code_index.py`) para no confundirlos con algo roto por este REQ.
