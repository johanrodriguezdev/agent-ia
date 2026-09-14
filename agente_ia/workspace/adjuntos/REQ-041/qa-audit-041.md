# Auditoría QA REQ-041 — Rediseño de icono de app y bandeja del sistema

**Agente:** orion-qa
**Fecha:** 2026-09-14

## Insumos leídos
`REQ-041-context.md` completo, `spec/SPEC-041.md`, `propuestas/arquitectura-041.md`,
`propuestas/ui-design-041.md`, `propuestas/desarrollo-log-041.md`, `pruebas/test-results-041.md`.
Código auditado directamente (no solo lo reportado por agentes anteriores):
`ui/webview/app_icon.py` (íntegro), el diff real de `ui/webview/main_window.py`
(`git diff HEAD`, 2 hunks: import y `_setup_tray_icon()`), y `tests/test_app_icon.py` (íntegro).

## Seguridad

**Confirmado explícitamente, no asumido: este REQ no tiene superficie de seguridad real.**
Es generación pura de imágenes (SVG embebido → `QSvgRenderer` → `QPixmap`) a partir de
constantes fijas en el código — sin input de usuario, sin red, sin filesystem, sin
subprocess/`os.system()`.

- **Secretos:** sin hallazgos. `grep` de `_ACENTO`/`58a6ff` en todo el repo: la única
  coincidencia es `ui/webview/theme.py:32` (`text_accent`), un token del tema del webview
  ajeno al icono — no es un secreto ni una referencia residual al diseño viejo. No hay API
  keys, tokens ni contraseñas en `app_icon.py`, `main_window.py` (diff) ni
  `tests/test_app_icon.py`.
- **Acciones destructivas:** ninguna. El único efecto lateral fuera de dibujar píxeles es
  `fijar_identidad_en_windows()` (sin cambios de este REQ, ya existía) — fija un
  `AppUserModelID` para el agrupado de la barra de tareas; no es destructivo y no necesita
  confirmación.
- **Niveles verde/amarillo/rojo:** no aplica ningún caso de `security-levels.md` —
  generar/mostrar un icono no está en ninguna de las tres listas y no debería estarlo (es
  puramente visual, sin acción sobre el sistema, archivos ni terceros).
- **Confirmaciones en acciones destructivas:** no aplica, no hay ninguna acción destructiva
  en el alcance de este REQ.
- **`except: pass` silencioso:** ninguno. El único `except` dentro del código tocado por
  este REQ es `fijar_identidad_en_windows()` (`ui/webview/app_icon.py:236`, sin cambios),
  que captura `Exception` y registra con `logger.warning(...)` antes de continuar — no es
  silencioso. `_render_svg()` usa `try/finally` (no `except`) para garantizar
  `painter.end()`, correcto y no oculta errores. `tests/test_app_icon.py` no tiene ningún
  `except`.
- **Validación de inputs:** no aplica — no hay inputs externos; `_tray_icon_svg(size)`
  falla rápido con `KeyError` si `size` no es 16/24, decisión ya justificada por
  arquitectura como error de programación (no de usuario), consistente con el resto del
  módulo.

## Niveles de riesgo
- Verde (puede actuar): generar/renderizar el icono de app y de bandeja (lectura de
  constantes, dibujo en memoria) — no requiere confirmación, coherente con
  `security-levels.md` (equivalente a "leer información" / "abrir aplicaciones conocidas").
- Amarillo (debe confirmar): ninguna acción de este REQ cae acá.
- Rojo (no ejecuta): ninguna acción de este REQ cae acá.
- Se implementaron confirmaciones: no aplica (no hay acciones amarillas/rojas en el alcance).

## Logging
- `ui/webview/app_icon.py` usa `logging`/`logger = logging.getLogger(__name__)` (patrón
  correcto, ya existente). El único punto de logging (`fijar_identidad_en_windows()`)
  registra la excepción con `logger.warning(f"no se pudo fijar la identidad... {e}")` antes
  de continuar — cumple la regla de nunca tragar un error sin registrarlo.
- Sin `print()` de depuración en `app_icon.py`, en el diff de `main_window.py` ni en
  `tests/test_app_icon.py` (verificado por grep).
- El resto de `main_window.py` (excepts en L159/213/261/270/293) queda fuera del diff real
  de este REQ (confirmado con `git diff HEAD -- ui/webview/main_window.py`: solo 2 hunks,
  el import y la línea de `_setup_tray_icon()`) — no corresponde auditarlos como parte de
  REQ-041.

## Consistencia de código
- Type hints presentes en todas las funciones nuevas/reescritas (`_marca_svg`,
  `_app_icon_svg`, `_tray_icon_svg`, `_render_svg`, `dibujar_app`, `dibujar_bandeja`,
  `app_icon`, `bandeja_icon`) — cumple `python-style.md`.
- Naming: `snake_case` para funciones/variables, `UPPER_CASE` para constantes (`_RINGS`,
  `_APP_BG`, `_TRAY_VARIANTS`, etc.) — correcto.
- Imports en `app_icon.py`: estándar (`logging`, `os`) → third-party (`PyQt6.*`), con línea
  en blanco separando los grupos — correcto. En `main_window.py` el import de
  `bandeja_icon()` se agregó a una línea local ya existente en medio de imports de PyQt6
  (orden pre-existente al REQ, confirmado con `git diff`: el único cambio ahí es agregar el
  nombre `bandeja_icon` a una importación que ya estaba en esa posición) — no es una
  regresión introducida por este REQ, no bloquea.
- Sin dependencias nuevas (`requirements.txt` no se tocó, confirmado) — coherente con lo
  documentado por arquitectura/dev.
- Sin `git commit` ejecutado por ningún agente hasta ahora (verificado con `git status`:
  todos los cambios siguen sin commitear).

**Dos hallazgos menores, no bloqueantes (solo en el archivo de test, sin impacto de
seguridad ni funcional):**
1. `tests/test_app_icon.py:180` excede el límite de 100 caracteres por línea de
   `python-style.md` (102 caracteres): `assert len(exactos) >= 2, "no se encontraron
   suficientes píxeles de trazo con cobertura completa"`.
2. `tests/test_app_icon.py:106`, dentro de `test_a_16_pixeles_todavia_hay_una_figura`: la
   variable `total = 16 * 16` se calcula pero no se usa (la aserción final quedó como
   `distintos > 0`, sin comparar contra `total`) — variable muerta, probablemente residual
   de una versión anterior del test con umbral porcentual.

Ninguno de los dos afecta seguridad, comportamiento ni el veredicto de los tests (10/10
siguen en verde); son correcciones triviales de una línea cada una. Se documentan para que
`orion-dev` los limpie en la próxima oportunidad de tocar este archivo — no ameritan, por sí
solos, rechazar un REQ visual/UI ya validado en 3 rondas de aprobación humana y con 9/9
criterios de SPEC en PASS.

## Veredicto: ✅ COMPLETADO

Seguridad verificada explícitamente (sin hallazgos, superficie de seguridad confirmada como
inexistente para este REQ, no asumida). Logging correcto, sin `except` silenciosos ni
`print()` de depuración. Convenciones de código respetadas salvo dos hallazgos cosméticos
triviales en el archivo de test (línea larga por 2 caracteres, una variable sin uso), que se
documentan pero no bloquean.

Hallazgos ya conocidos y aceptados por el humano en etapas previas (legibilidad del icono de
app a 16px, contraste ≈3.0:1 en el extremo oscuro del degradado) se dan por vigentes — no se
reabren en esta auditoría, quedan para que el humano los tenga presentes en la prueba manual
final.
