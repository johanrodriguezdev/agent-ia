# Resultados de prueba REQ-041 — Rediseño de icono de app y bandeja del sistema

**Agente:** orion-tester
**Fecha:** 2026-09-14

## Compilación
- `python -m py_compile ui/webview/app_icon.py ui/webview/main_window.py tests/test_app_icon.py main.py`: **OK**, sin errores.

## Tests existentes (`tests/test_app_icon.py`)
- Pasados: **10/10** (verificado de forma independiente, no solo el reporte de `orion-dev`).
- Nuevos fallos: ninguno.

```
tests/test_app_icon.py::test_trae_todos_los_tamanos PASSED
tests/test_app_icon.py::test_bandeja_trae_los_dos_tamanos PASSED
tests/test_app_icon.py::test_el_fondo_del_icono_de_app_es_negro_solido PASSED
tests/test_app_icon.py::test_las_esquinas_del_icono_de_app_son_transparentes_por_el_redondeo PASSED
tests/test_app_icon.py::test_a_16_pixeles_todavia_hay_una_figura PASSED
tests/test_app_icon.py::test_bandeja_16_y_24_son_legibles PASSED
tests/test_app_icon.py::test_bandeja_usa_color_plano_sin_degradado PASSED
tests/test_app_icon.py::test_bandeja_no_es_el_icono_de_app_reescalado PASSED
tests/test_app_icon.py::test_la_app_declara_su_propia_identidad_en_windows PASSED
tests/test_app_icon.py::test_se_declara_antes_de_crear_la_ventana PASSED
```

## Criterios de la SPEC (SPEC-041.md)

| # | Criterio | Resultado | Nota |
|---|----------|-----------|------|
| 1 | Icono de app muestra el Concepto A (3 anillos + nodo, degradado metálico, fondo negro) en 16/24/32/48/64/128/256 px, sin recortes ni deformación 1:1 | PASS | `_app_icon_svg()` usa un único `viewBox="0 0 240 240"` cuadrado, escalado uniforme por `QSvgRenderer`. Verificado por código, por test (`test_trae_todos_los_tamanos`) y visualmente (render real de `dibujar_app(256)`: se ven claramente los 3 anillos entrelazados, degradado blanco-gris, nodo central, fondo negro con esquinas redondeadas). |
| 2 | Ningún tamaño muestra el diseño anterior (anillo+punto azul plano) ni restos de auriculares/mascota | PASS | `dibujar()`/`_ACENTO` viejos eliminados por completo del código; `app_icon()` solo puede producir el Concepto A. Confirmado por inspección directa de `app_icon.py`. |
| 3 | Icono de bandeja usa variante monocroma (`#f2f2f3` sin degradado, chip `#1b1b1d`) a 16/24 px, distinta del icono de app reescalado | PASS | `_tray_icon_svg()` es una estructura SVG separada (sin `<linearGradient>`); `test_bandeja_no_es_el_icono_de_app_reescalado` confirma que el fondo difiere del icono de app. |
| 4 | En "iconos ocultos" la marca de bandeja se sigue reconociendo como 3 anillos + nodo, no como mancha | PASS | Confirmado visualmente: renders reales de `dibujar_bandeja(16)` y `dibujar_bandeja(24)` (ampliados x12 para inspección) muestran con claridad los 3 arcos entrelazados y el nodo central, no una mancha uniforme ni un vacío. |
| 5 | Tooltip de bandeja (`"{nombre} — Panel de control"`) sigue funcionando sin cambios | PASS | `main_window.py` L229 (`self.tray_icon.setToolTip(...)`) intacto, usa `self._agent_name` sin diff respecto a antes del REQ. |
| 6 | `fijar_identidad_en_windows()` se sigue ejecutando antes de crear la `QApplication` | PASS | `main.py` sin cambios; `test_se_declara_antes_de_crear_la_ventana` (verifica el orden textual en el archivo) y `test_la_app_declara_su_propia_identidad_en_windows` pasan. |
| 7 | `tests/test_app_icon.py` actualizado para describir/verificar la forma nueva (tamaños, legibilidad a 16px, fondo ya no transparente para APP, transparencia del chip de bandeja si aplica) | PASS | Los 10 tests cubren exactamente esos puntos; la aserción de "fondo transparente" del diseño viejo fue reemplazada por `test_el_fondo_del_icono_de_app_es_negro_solido` (fondo opaco a propósito) y la transparencia de esquinas por redondeo se prueba aparte. |
| 8 | `python -m pytest tests/test_app_icon.py --tb=short -v` pasa completo | PASS | 10/10 PASSED, ejecutado de forma independiente por `orion-tester` (no solo el reporte de `orion-dev`). |
| 9 | No quedan referencias al color anterior (`_ACENTO = "#58a6ff"`) como color final del icono | PASS | `grep` de `_ACENTO`/`58a6ff` en todo el repo: la única coincidencia es `ui/webview/theme.py:32` (`text_accent`), un token del tema del webview totalmente ajeno al icono (ya confirmado por `orion-ui` que este REQ no toca `theme.py`/`theme.css`) — no es una referencia al icono viejo. |

**Veredicto de criterios: 9/9 PASS.**

## Regresión — suite completa

```
python -m pytest tests/ --tb=short -q
→ 41 failed, 2730 passed, 1 skipped, 12 warnings, 4 errors in 177.28s
```

| Área revisada | Resultado |
|---|---|
| `tests/test_app_icon.py` (área directa del REQ) | 10/10 PASS |
| `tests/test_documentos.py` (25 fallos + 4 errores) | Pre-existentes — `ModuleNotFoundError` por dependencia opcional `docx` ausente en este entorno, no relacionados con `app_icon.py`/`main_window.py` |
| `tests/test_ui_tree.py` (16 fallos) | Pre-existentes — `ModuleNotFoundError: uiautomation` ausente en este entorno, no relacionados con este REQ |
| Resto de la suite (`tests/test_main_window*.py` si existiera, y todo lo demás) | Sin fallos nuevos |

Comparado contra `baseline-041.md` (42 failed, 2725 passed, 1 skipped, 4 errors) y contra lo reportado por `orion-dev` (41 failed, 2730 passed, 1 skipped, 4 errors): **el resultado de `orion-tester` coincide exactamente** con lo que reportó `orion-dev` — no hay ningún fallo nuevo atribuible a este REQ. La baja de 42→41 fallos coincide con el flaky de orden ya documentado en `test_code_index.py::test_el_indexado_se_puede_cortar_y_continuar` (pasa aislado), no es una regresión de REQ-041. No se encontró ningún archivo de test que ejercite `main_window.py` de forma directa (búsqueda de `app_icon|bandeja_icon|tray_icon` en `tests/` solo devuelve `test_app_icon.py`), así que el cambio de `~L227-228` de `main_window.py` queda cubierto indirectamente por la revisión manual de código de este reporte, no por un test dedicado — no es un gap introducido por este REQ (tampoco existía antes).

## Verificación visual directa (más allá de lo pedido por el DoD, para cerrar el pendiente que dejó `orion-dev`)

Se renderizaron y se inspeccionaron visualmente `dibujar_app(256)`, `dibujar_app(16)`, `dibujar_bandeja(16)` y `dibujar_bandeja(24)`:

- **`dibujar_app(256)`**: se ve con claridad el Concepto A completo — tres anillos entrelazados con degradado metálico blanco→gris, nodo central relleno, fondo negro de esquinas redondeadas. Coincide con la especificación del canvas.
- **`dibujar_app(16)`**: **confirma el hallazgo ya documentado por `orion-architect`/`orion-dev`** — a 16 px literales el icono es casi indistinguible de un cuadrado negro liso; ampliado x12 apenas se adivina una sombra tenue, no una figura reconocible. No es un FAIL de ningún criterio de la SPEC (ninguno de los 9 exige legibilidad del icono de APP a 16 px; ese requisito de legibilidad a tamaño chico solo aplica explícitamente a la bandeja, criterio 4), pero se deja registrado como **hallazgo no bloqueante para `orion-qa`/prueba manual del humano**, cerrando el pendiente que dejó `desarrollo-log-041.md`.
- **`dibujar_bandeja(16)`** y **`dibujar_bandeja(24)`**: ambos se reconocen con claridad como los tres arcos entrelazados + nodo central sobre el chip oscuro, incluso a tamaño real ampliado. Satisface el criterio 4 sin ambigüedad.

## Revisión de las dos desviaciones documentadas por `orion-dev` en `desarrollo-log-041.md`

1. **Umbral de `test_bandeja_16_y_24_son_legibles` ajustado de la referencia de arquitectura (~19-23%) al valor medido en este entorno (~32%/43%), margen final 15%-60%.** Revisado: es un cambio de METODOLOGÍA de conteo (cuenta cualquier píxel con desviación de color por antialiasing, no solo cobertura fuerte), no un cambio de geometría/color. No hay ningún criterio de la SPEC que fije un porcentaje numérico exacto — el criterio 4 solo exige "se sigue reconociendo, no es mancha", y la verificación visual directa de este reporte lo confirma independientemente del umbral del test. **No rompe ningún criterio de aceptación.**
2. **`test_bandeja_usa_color_plano_sin_degradado` verifica el color plano renderizando `_marca_svg` a 200 px nativos, no al bitmap final de 16/24 px.** Revisado: sigue siendo una verificación por render de píxeles (no parseo de string SVG) de la misma función compartida que usa `dibujar_bandeja()` en producción; el motivo (ningún píxel llega a cobertura 100% a 16/24 px por antialiasing puro, no por degradado) es consistente con lo observado en la inspección visual de este reporte. El criterio de la SPEC ("trazo sólido `#f2f2f3` sin degradado") queda probado sobre la geometría real compartida. **No rompe ningún criterio de aceptación.**

Ambas desviaciones son ajustes de metodología de test, no cambios de comportamiento, geometría ni color — consistentes con lo que exige la SPEC.

## Veredicto: PASS

9/9 criterios de la SPEC en PASS, 10/10 tests propios en verde (verificados de forma independiente), sin regresiones nuevas en la suite completa (41 failed/2730 passed/1 skipped/4 errors, idéntico a lo reportado por `orion-dev` y coincidente con las áreas pre-existentes ya documentadas en el baseline). Único hallazgo no bloqueante: el icono de app a 16 px es casi indistinguible del fondo negro (confirmado visualmente), riesgo ya conocido, documentado y aceptado desde `arquitectura-041.md` — se recomienda que quede presente en la prueba manual final del humano.
