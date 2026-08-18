# Auditoría QA REQ-011 — Auto-inicio con Windows (arranque minimizado a bandeja)

**Agente:** orion-qa
**Fecha:** 2026-08-05

## Insumos revisados
- `workspace/adjuntos/REQ-011/REQ-011-context.md`
- `workspace/adjuntos/REQ-011/spec/SPEC-011.md`
- `workspace/adjuntos/REQ-011/propuestas/arquitectura-011.md`
- `workspace/adjuntos/REQ-011/propuestas/desarrollo-log-011.md`
- `workspace/adjuntos/REQ-011/pruebas/test-results-011.md` (10/10 PASS, 216/216 tests)
- Código: `setup_autostart.py`, `main.py` (bloque `__main__`), `tests/test_autostart.py`,
  `tests/test_main.py`, `tests/test_gui_widgets.py`

## Seguridad

- **Clasificación correcta:** modificar `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  es 🟡 Amarillo ("Cambiar configuraciones del sistema") según `security-levels.md`. No requiere
  privilegios elevados (hive `HKEY_CURRENT_USER`), consistente con el análisis de arquitectura.
- **Confirmación explícita antes de mutar:** verificado en `setup_autostart.py` líneas 135-162.
  El bloque `if __name__ == "__main__":` llama `_confirmar(...)` **antes** de invocar `activar()`
  o `desactivar()`, y aborta (`sys.exit(0)`) sin tocar el registro si la respuesta no es afirmativa.
  `_confirmar()` (línea 107) reutiliza el mismo patrón que `main.py::_desktop_confirm()`
  (prompt + comparación `sí/si/yes/s`), cubierto por `test_confirmar_acepta_variantes_afirmativas`
  y `test_confirmar_rechaza_cualquier_otra_respuesta` en `tests/test_autostart.py`.
- **Nota de diseño (no bloqueante):** `activar()`/`desactivar()` en sí mismas (líneas 70-104) no
  llaman a `_confirmar()` — son funciones "puras" según arquitectura-011.md, Decisión 3, y la
  confirmación vive solo en la capa CLI. Verificado con `grep` que ningún otro módulo del repo
  importa o llama `setup_autostart.activar()`/`desactivar()` fuera del propio `__main__` y de los
  tests — no hay camino de ejecución que dispare la mutación sin pasar por `_confirmar()`. Si en
  el futuro se agrega otro invocador (ej. un botón de GUI o un handler), ese invocador nuevo debe
  volver a pasar por una confirmación equivalente; queda anotado para vigilancia futura.
- **Logging obligatorio de acciones Amarillo/Rojo (`security-levels.md`):** verificado.
  `activar()` loguea `logger.warning(...)` en cada mutación real (línea 77-81), con mecanismo y
  comando. `desactivar()` loguea `logger.warning(...)` **solo cuando efectivamente borró algo**
  (línea 94-97) — comportamiento correcto y explícitamente testeado
  (`test_desactivar_loguea_warning_solo_si_borro_algo_ca07`, distingue el caso "borró" del caso
  "no había nada que borrar").
- **Secretos:** sin hallazgos. `grep -i "api_key|token|secret|password"` sobre `setup_autostart.py`
  no arroja coincidencias. No hay credenciales ni valores sensibles hardcodeados en ningún archivo
  nuevo o modificado de este REQ.
- **Fallback `pythonw.exe` → `python.exe`:** revisado el caso borde. `_resolver_pythonw()`
  (línea 37-51) no lo oculta: cuando `pythonw.exe` no existe junto al intérprete activo, cae a
  `sys.executable` y ejecuta `logger.warning(...)` con el detalle completo (directorio buscado y
  ruta usada), advirtiendo explícitamente que esto mostrará una consola visible en cada login.
  Está cubierto por `test_resolver_pythonw_fallback_a_sys_executable`, que verifica tanto el
  valor de retorno como que el mensaje incluye "pythonw.exe" y nivel `WARNING`. No es un fallo
  silencioso — correctamente logueado, tal como pide la arquitectura.

## Niveles de riesgo

- **Verde (puede actuar):** `esta_activo()` / `--estado` — solo lectura del registro, no muta nada.
- **Amarillo (debe confirmar):** `activar()` / `desactivar()` vía CLI (`--activar`, `--desactivar`)
  — modifican `HKCU\...\Run`. Confirmación implementada.
- **Rojo (no ejecuta):** no aplica — este REQ no toca ninguna categoría 🔴 Rojo (no borra BDs, no
  expone credenciales, no eleva privilegios, no instala software).
- **Se implementaron confirmaciones:** sí, en la capa CLI de `setup_autostart.py` antes de
  `activar()`/`desactivar()`.

## Logging

- Sin `except: pass` ni `except Exception: pass` silenciosos en `setup_autostart.py` (verificado
  con grep dirigido, cero coincidencias). `esta_activo()` captura `FileNotFoundError` como parte
  del flujo normal esperado (la entrada no existe todavía) sin necesidad de log — comportamiento
  correcto, no un error que se esté tragando. `activar()`/`desactivar()` capturan `OSError`
  inesperado y lo registran con `logger.error(...)` antes de devolver `False` — nunca se ignora
  en silencio.
- `esta_activo()` no loguea nada en su camino "False" — correcto, ya que consultar el estado es
  una operación 🟢 Verde y no una mutación, no le aplica el requisito de logging de CA-07.

## Consistencia de código

- Sigue `.claude/rules/python-style.md`: type hints en todas las funciones nuevas (`-> str`,
  `-> bool`), `snake_case` consistente, imports ordenados (stdlib únicamente, sin third-party),
  docstrings en modo imperativo ("Devolver...", "Crear...", "Borrar...").
- Sin dead code ni `print()` de debug — los `print()` presentes en el bloque `__main__` son
  mensajes de salida CLI intencionales para el usuario (no debug), consistentes con el patrón
  usado en `main.py`.
- Sin dependencias nuevas — `requirements.txt` sin cambios (confirmado por `git status`), `winreg`
  es stdlib. Cambio en `main.py` acotado (5-8 líneas) exactamente como documenta la arquitectura;
  `ui/gui.py`, `start_jarvis.py` no modificados (confirmado por `git status --short`: no aparecen
  en la lista de archivos tocados).
- `AUTOSTART_VALUE_NAME = "Noddoo"` fijo, independiente de `get_agent_name()` — decisión
  deliberada y documentada, correcta.

## Tests

- Verificado independientemente: `python -m pytest tests/test_autostart.py tests/test_main.py
  tests/test_gui_widgets.py --tb=short -q` → **31 passed, 0 failed** (16 de `test_autostart.py`
  + 2 de CA-03 en `test_main.py` + resto ya existentes de `test_gui_widgets.py` con 1 nuevo de
  CA-04), consistente con lo reportado por `orion-tester`.
- `tests/test_autostart.py` mockea `winreg` por completo en **todos** los casos vía
  `patch("setup_autostart.winreg.*")` — no hay ninguna llamada directa a `winreg.OpenKey` /
  `CreateKeyEx` / `SetValueEx` / `DeleteValue` / `QueryValueEx` sin mockear. Confirmado leyendo el
  archivo completo: no se toca el registro real de la máquina en ningún test, cumpliendo
  `.claude/rules/testing.md` y el riesgo ya identificado en arquitectura-011.md.
- CA-03 se prueba ejecutando el texto fuente real del bloque `__main__` de `main.py` vía `exec()`
  (leído del archivo en cada test, con `ui.gui`, `threading.Thread` y `sys.exit` mockeados) — no
  se ejecuta contra un proceso real ni cuelga pytest. Técnica razonable dado que el bloque no fue
  extraído a una función testeable; documentado con motivo claro en el propio archivo de test.

## Veredicto: ✅ COMPLETADO

Sin hallazgos de seguridad. El gate 🟡 Amarillo está correctamente implementado (confirmación
explícita + logging `WARNING` en cada mutación real), sin secretos hardcodeados, sin
`except/pass` silenciosos, sin acciones que requieran privilegios elevados. El caso borde del
fallback `pythonw.exe → python.exe` está bien logueado y visible, no oculto. Tests mockean
`winreg` por completo — no hay riesgo de tocar el registro real de la máquina de CI/desarrollo.
Código consistente con `.claude/rules/python-style.md`. No se modificaron `ui/gui.py`,
`start_jarvis.py` ni `requirements.txt`, tal como exige la arquitectura aprobada.

**Se requiere prueba manual del humano antes de cerrar** (ver sección siguiente) — QA no puede
verificar por sí mismo que Windows realmente lanza la app al iniciar sesión, ni que la bandeja
es interactiva en un arranque real.

## Prueba manual solicitada a Johan

1. Desde una consola en `agente_ia/`, correr `python setup_autostart.py --estado` — debe
   informar "NO está activo" (asumiendo que nunca se activó antes en esta máquina).
2. Correr `python setup_autostart.py --activar`, confirmar con "sí" cuando lo pida. Verificar
   que el script imprime "Auto-inicio ACTIVADO." y que aparece la entrada `Noddoo` en
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (se puede confirmar con
   `python setup_autostart.py --estado` de nuevo, o abriendo `regedit` en esa ruta).
3. Cerrar sesión de Windows y volver a iniciar sesión (o reiniciar el equipo).
4. Confirmar que la app arranca sola, **sin mostrar ninguna ventana visible** (CA-03), y que el
   ícono aparece en la bandeja del sistema (CA-04).
5. Verificar que el ícono de bandeja es funcional: doble clic muestra/oculta la ventana, el menú
   contextual tiene "Mostrar/Ocultar" y "Salir" y ambos funcionan.
6. Cerrar la ventana principal (si la mostraste en el paso 5) con el botón "X" y confirmar que la
   app se minimiza a la bandeja en vez de cerrarse (CA-10, comportamiento ya existente de
   REQ-009 que no debía cambiar).
7. Correr `python setup_autostart.py --desactivar`, confirmar con "sí". Verificar que imprime
   "Auto-inicio DESACTIVADO." y que `--estado` ya no lo muestra activo.
8. Cerrar sesión y volver a iniciar (o reiniciar) una vez más — confirmar que la app **ya no**
   arranca sola.

Responde:
- OK → entrego el mensaje de commit sugerido
- FALLA [descripción] → vuelve a orion-dev
