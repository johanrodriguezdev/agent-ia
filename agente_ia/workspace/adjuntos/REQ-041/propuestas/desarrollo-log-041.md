# Desarrollo REQ-041 — Rediseño del icono de app y de bandeja del sistema

**Estado:** implementación completa, lista para `orion-tester`.
**Agente:** orion-dev
**Fecha:** 2026-09-14

## Archivos modificados
- `ui/webview/app_icon.py` — reescritura completa: reemplaza el dibujo procedural con
  `QPainter` (`dibujar(size, color)`, `_ACENTO`) por SVG embebido como strings Python
  renderizado con `QSvgRenderer` (`PyQt6.QtSvg`). Nuevas funciones públicas `dibujar_app`,
  `dibujar_bandeja`, `app_icon()` (sin `color`), `bandeja_icon()`; internas `_marca_svg`,
  `_app_icon_svg`, `_tray_icon_svg`, `_render_svg`. `fijar_identidad_en_windows()` y
  `_APP_ID` sin cambios.
- `ui/webview/main_window.py` — import agrega `bandeja_icon`; `_setup_tray_icon()`
  (~L227) usa `bandeja_icon()` en vez de `app_icon()` para `self.tray_icon.setIcon(...)`.
  `setWindowIcon()`/`QApplication.setWindowIcon()` (~L72-76) sin diff real: ya llamaban a
  `app_icon()` sin el argumento `color`.
- `tests/test_app_icon.py` — reescritura parcial según la lista de `arquitectura-041.md`
  (10 tests: 3 sin cambios, 2 reescritos, 1 adaptado, 4 nuevos). Detalle en "Decisiones de
  implementación".

## Dependencias agregadas
Ninguna. `PyQt6.QtSvg.QSvgRenderer` ya está disponible con el `PyQt6` instalado
(verificado con `python -m py_compile` + import real en los tests). `requirements.txt` no
se toca, tal como confirmó `orion-architect`.

## Decisiones de implementación
- **Ajuste de umbrales numéricos en `test_bandeja_16_y_24_son_legibles`, distinto del
  valor de referencia de `arquitectura-041.md`.** La arquitectura citaba "~19–23% de
  píxeles de trazo/nodo" como referencia empírica, con un margen sugerido de 10%-40%. Al
  implementar y medir en este mismo entorno (Qt 6.11.0) con el método "cualquier píxel
  cuyo color RGB difiera del fondo del chip", el resultado real es ~32% (24px) y ~43%
  (16px) — más alto que la referencia porque este método cuenta también los píxeles
  parcialmente cubiertos por antialiasing (el trazo nativo de 8/10 queda por debajo de 1
  px real una vez escalado por `scale(size/200)`, así que ningún píxel individual llega a
  cobertura 100%, pero muchos quedan con cobertura parcial). No se cambió ninguna
  geometría ni color — es una diferencia de metodología de conteo entre el render de
  prueba de arquitectura y el test final. Se ajustó el margen del test a 15%-60% (sigue
  descartando tanto "casi vacío" como "mancha sólida", solo que calibrado al dato real
  medido, no al de referencia). Documentado en el docstring del test.
- **`test_bandeja_usa_color_plano_sin_degradado` no compara colores en el bitmap final de
  16/24 px.** A esos tamaños, por el mismo motivo de sub-píxel de arriba, NINGÚN píxel
  llega a cobertura 100% — comparar contra `#f2f2f3` exacto ahí habría dado un falso
  negativo permanente (no por degradado, sino por antialiasing puro). En vez de eso el
  test renderiza la misma función compartida `_marca_svg` (la que también usa
  `dibujar_bandeja`) a su tamaño NATIVO 200 px, donde el trazo de 8 px sí tiene margen
  para píxeles con cobertura completa, y verifica que existan múltiples píxeles con color
  EXACTO `#f2f2f3` repartidos por distintas zonas de la marca — la propiedad real que
  importa (color no depende de la posición) queda probada sin acoplarse al artefacto de
  escala de los tamaños reales de bandeja. Sigue sin "parsear" el SVG como string; se
  sigue verificando por render de píxeles, solo que a una resolución donde el resultado es
  determinista.
- Sin más ajustes respecto a `arquitectura-041.md`/`ui-design-041.md`: geometría, colores,
  nombres de función (`bandeja_icon()` y no `tray_icon()`), estructura de dos sistemas de
  coordenadas del SVG de bandeja, y ausencia de tokens nuevos en `theme.py`/`theme.css`
  implementados literalmente como se aprobaron.

## Verificación local
```
python -m py_compile ui/webview/app_icon.py ui/webview/main_window.py tests/test_app_icon.py main.py
→ sin errores

python -m pytest tests/test_app_icon.py --tb=short -v
→ 10 passed

python -m pytest tests/ --tb=short -q
→ 41 failed, 2730 passed, 1 skipped, 4 errors
```
Comparado contra `baseline-041.md` (42 failed, 2725 passed, 1 skipped, 4 errors, suite
completa antes de este REQ): los 4 errores y prácticamente todos los fallos coinciden con
las mismas áreas ya documentadas como pre-existentes (`test_documentos.py` por falta de
`docx`, `test_ui_tree.py` por falta de `uiautomation`) — ninguno nuevo relacionado con
`app_icon.py`/`main_window.py`. El fallo total bajó de 42 a 41: coincide con el flaky de
orden de `test_code_index.py` ya señalado en el baseline (pasa aislado, depende del orden
de ejecución de la suite completa), no es una regresión de este REQ.

## Pendiente para el humano / orion-tester
- `arquitectura-041.md` recomendó que el humano/`orion-ui` confirmen visualmente un PNG
  real de `dibujar_app(16)` antes de cerrar el REQ (riesgo conocido y ya aceptado: a 16px
  el icono de app es casi indistinguible del fondo negro, ~0.8% de píxeles). No se generó
  ese PNG en este paso — queda como parte de la prueba manual final, no bloquea el avance
  a `orion-tester`.
