# SPEC-042 — Preparar el repositorio para publicación open source

**Categoría:** DOCS (+ SEGURIDAD) · **Tipo:** DOCS + SEGURIDAD · **Fecha:** 2026-09-18
**Origen:** decisión de Johan (septiembre 2026) de publicar O.R.I.O.N. como software libre en
vez de venderlo, y autorización nocturna en bloque del 2026-09-18 para ejecutar las
recomendaciones de la revisión de estado.

## Problema

El repositorio es privado y fue escrito para una sola persona. Hoy publicarlo tal cual:

1. No tiene licencia → legalmente nadie puede usarlo ni contribuir.
2. Versiona archivos personales del dueño (`USER.md`, `MEMORY.md`: nombre, ciudad, gustos,
   memoria del agente) y nombra al dueño y su ciudad en los documentos de identidad del
   producto.
3. Trae código de terceros (qwebchannel.js, xterm.js, fuente Inter) y transcripciones de
   código de OpenClaw sin avisos de licencia.
4. La suite de tests muestra 42 rojos y 4 errores en un equipo que no tenga `python-docx` o
   `uiautomation`, y un test flaky de reloj — quien clone creerá que el proyecto está roto.
5. El historial de git contiene claves reales (commits de marzo–julio de 2026).

## Criterios de aceptación

| # | Criterio | Verificación |
|---|---|---|
| CA-01 | Existe `LICENSE` con el texto oficial e íntegro de la GPL-3.0 | sha256 igual al de `gnu.org/licenses/gpl-3.0.txt`; 674 líneas |
| CA-02 | `THIRD_PARTY_NOTICES.md` lista todo recurso de terceros que viaja en el repo con autor y licencia, y cada uno conserva su archivo de licencia al lado | tabla con qwebchannel.js, xterm.js, Inter; `LICENSE-Inter.txt` presente; referencias OpenClaw con aviso MIT en cabecera |
| CA-03 | `SECURITY.md` explica cómo reportar (sin canal público), qué cuenta como vulnerabilidad y el modelo de seguridad en corto | revisión |
| CA-04 | `CONTRIBUTING.md` explica entorno, tests, reglas de `.claude/rules/`, commits y licencia del aporte | revisión |
| CA-05 | `USER.md` y `MEMORY.md` dejan de estar versionados, siguen en el disco del dueño y están en `.gitignore` | `git ls-files` no los lista; `git status` no los muestra como borrados del disco |
| CA-06 | Existen `USER.example.md` y `MEMORY.example.md` como plantillas sin datos personales, y al arrancar la app se copian a `USER.md`/`MEMORY.md` **solo si faltan** | tests `test_identity.py::test_los_personales_se_crean_*`, `*_no_se_toca`, `*_sin_plantilla_*`, `*_error_al_copiar_*`, `*_plantillas_*_viajan_*` |
| CA-07 | `IDENTITY.md`, `SOUL.md` y `OPERATING_AGREEMENT.md` no nombran al dueño ni su ciudad | `grep -i "johan\|villavicencio"` vacío en esos tres |
| CA-08 | El nombre del usuario deja de estar escrito en el código (`core/memory_scoring.py`) y sale de la configuración | tests `test_memory_scoring.py::test_el_nombre_configurado_*`, `*_sin_nombre_*`, `*_si_la_configuracion_falla_*` |
| CA-09 | Sin una dependencia opcional instalada, los tests que la necesitan se **saltan** con el nombre del paquete, no fallan | simulación con `builtins.__import__` bloqueando `docx`/`uiautomation`/`openpyxl`/`pptx`/`fitz`: 0 failed, 63 skipped; con deps: 102 passed |
| CA-10 | `test_el_indexado_se_puede_cortar_y_continuar` deja de ser flaky | causa raíz en `core/code_index.py` (`>` → `>=` con tope 0); 3 corridas seguidas en verde |
| CA-11 | README enlaza licencia, avisos de terceros, contribución y seguridad, y explica los archivos personales | revisión |
| CA-12 | La suite completa no introduce fallos nuevos | pytest completo en verde (registrado en el contexto) |
| CA-13 | Las claves del historial quedan **documentadas** con commits y archivo, sin reproducir su valor, y con el procedimiento para revocarlas/reescribir | sección "Pendiente para Johan" del contexto |

## Fuera de alcance (decisiones de Johan, no del REQ)

- Reescribir el historial de git (`git filter-repo`) o crear un repositorio nuevo limpio.
  Es destructivo y afecta a todos los clones: lo ejecuta él. Este REQ deja el procedimiento.
- Revocar las claves expuestas: solo él tiene acceso a esas cuentas.
- Publicar o no `workspace/adjuntos/` y `.claude/` (evidencia del pipeline y configuración del
  asistente de desarrollo).
- El nombre definitivo del producto (pendiente desde agosto).
- Activar "Private vulnerability reporting" en GitHub (lo referencia `SECURITY.md`).

## Decisiones de diseño

- **GPL-3.0 y no Apache/MIT**: PyQt6 y PyQt6-WebEngine son GPL-3.0-only; la alternativa exige
  migrar a PySide6. El archivo es reversible si Johan decide otra cosa.
- **Plantillas `.example` + copia al primer arranque**, mismo patrón que `config.json`: el
  agente sigue funcionando sin los personales (`core/identity.py` ya los omitía), pero un
  equipo nuevo arranca con un `USER.md` que invita a rellenarse.
- **El skip de dependencias opcionales va en `conftest.py` como hook**, no como
  `importorskip` por archivo: cubre fixtures y módulos bajo prueba, y solo actúa sobre una
  lista cerrada de paquetes — un `ModuleNotFoundError` de cualquier otro nombre sigue siendo
  rojo.
- **El flaky se arregla en producción, no en el test**: con `tope_segundos=0` la intención es
  "no indexes nada en esta llamada", y `>` lo hacía depender del reloj.
- **`SECURITY.md` no publica un correo**: usa el reporte privado de GitHub. Poner el correo
  personal del dueño en un archivo público es decisión suya.
