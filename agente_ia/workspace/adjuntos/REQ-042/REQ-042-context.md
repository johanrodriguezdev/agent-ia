# Contexto REQ-042 — Preparar el repositorio para publicación open source

## Resumen ejecutivo
Johan decidió (septiembre 2026) publicar O.R.I.O.N. como software libre. Este REQ deja el
repositorio en condiciones de hacerse público: licencia, avisos de terceros, política de
seguridad, guía de contribución, archivos personales fuera del repo con plantillas y copia al
primer arranque, documentos de identidad sin el nombre ni la ciudad del dueño, y una suite de
tests que no muestra rojos falsos en un equipo sin dependencias opcionales. Las claves reales
del historial de git quedan documentadas para que él las revoque y reescriba el historial.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Último agente:** conversación principal (sesión nocturna autorizada por Johan, 2026-09-18)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo` (la rama activa; no se creó otra)
- **Categoría:** DOCS · **Tipo:** DOCS + SEGURIDAD

## Origen
Revisión de estado del 2026-09-18 (conversación principal): entre las cuatro recomendaciones
que Johan aprobó en bloque antes de irse a dormir estaba "empaquetar para publicar". El
detalle de lo que bloqueaba la publicación venía de la auditoría de licencias de septiembre
(memoria del proyecto): sin LICENSE, personales versionados, claves en el historial,
referencias de OpenClaw sin atribuir, `qwebchannel.js` LGPL sin listar.

## Decisiones tomadas
<!-- FECHA | AGENTE | DECISIÓN | MOTIVO -->
2026-09-18 | conversación principal | Pipeline acortado: spec + implementación en la misma sesión, sin subagentes | Precedente de REQ-027/029/032 (decisión de Johan del 2026-09-08). Es un REQ de documentación y limpieza sin diseño abierto; los criterios están en `spec/SPEC-042.md`.
2026-09-18 | conversación principal | Licencia GPL-3.0, texto oficial descargado de gnu.org (sha256 `3972dc97…`) | PyQt6/PyQt6-WebEngine son GPL-3.0-only (verificado con `pip show`). Es la única licencia viable sin migrar a PySide6. Reversible: si Johan prefiere otra, es un archivo.
2026-09-18 | conversación principal | `USER.md` y `MEMORY.md` salen del repo (`git rm --cached`), quedan en el disco de Johan intactos, entran en `.gitignore`, y el repo trae `USER.example.md` / `MEMORY.example.md` | Contienen nombre, ciudad, gustos y la memoria del agente sobre él. Mismo patrón que `config.json` (REQ b6b3cd6).
2026-09-18 | conversación principal | `core/identity.py::asegurar_archivos_personales()` copia las plantillas al primer arranque **solo si faltan**, llamada desde `main.py` antes del warmup | El cargador ya toleraba archivos ausentes, pero un equipo nuevo arrancaría sin perfil y sin saber que puede tenerlo. Nunca pisa un archivo existente: es el perfil del usuario.
2026-09-18 | conversación principal | `IDENTITY.md`, `SOUL.md`, `OPERATING_AGREEMENT.md` pasan a hablar de "su usuario" en vez de "Johan"; la sección "Usuario principal" de IDENTITY remite a `USER.md` | Son documentos del producto (se versionan); lo personal va en `USER.md`. El agente de Johan sigue sabiendo quién es él porque su `USER.md` local no cambió.
2026-09-18 | conversación principal | Los comentarios de código que atribuyen decisiones a "Johan" se conservan | Es el autor y mantenedor del proyecto (su GitHub es público); documentan por qué se decidió algo. No son datos personales sensibles. Excepción corregida: `core/memory_scoring.py` tenía "johan" como palabra vacía del algoritmo → ahora sale de `config_manager.get_display_name()`.
2026-09-18 | conversación principal | User-Agent de Wikipedia pasa de `JarvisAssistant/1.0 (johan@correo.com)` a `ORION-Assistant/1.0 (URL del repo)` | Wikipedia exige un contacto; la URL del repositorio lo es, y el correo era un placeholder inventado.
2026-09-18 | conversación principal | Skip de dependencias opcionales como hook `pytest_runtest_makereport` en `tests/conftest.py`, sobre una lista cerrada (`docx`, `openpyxl`, `pptx`, `fitz`, `pymupdf`, `uiautomation`, `win32com`, `pythoncom`, `comtypes`) | Un `importorskip` por archivo no cubre fixtures ni el módulo bajo prueba, y saltar `test_documentos.py` entero perdería 27 tests que sí corren sin Office. Cualquier otro `ModuleNotFoundError` sigue siendo un fallo.
2026-09-18 | conversación principal | Flaky `test_el_indexado_se_puede_cortar_y_continuar`: causa raíz en `core/code_index.py` (`time.monotonic() - comenzo > tope_segundos` → `>=`) | Con tope 0 la intención es "no indexes nada en esta llamada"; con `>` dependía de que el reloj hubiera avanzado antes del primer archivo (en Windows salta de a ~15 ms). Se arregla el código, no el test.
2026-09-18 | conversación principal | `SECURITY.md` remite al reporte privado de GitHub, sin correo | Publicar el correo personal de Johan en un archivo público es decisión suya. Requiere activar "Private vulnerability reporting" en el repo (pendiente para él).
2026-09-18 | conversación principal | Los tres documentos `workspace/referencias/openclaw/*.md` llevan cabecera de atribución MIT y figuran en `THIRD_PARTY_NOTICES.md` | La MIT exige conservar el aviso de copyright y de permiso junto a porciones sustanciales del código; los documentos transcriben ~4.500 líneas de TS. Se conservan (son la justificación de varias decisiones de diseño) en vez de borrarlos.
2026-09-18 | conversación principal | Licencia de la fuente Inter (`LICENSE-Inter.txt`, OFL-1.1) añadida junto a los `.woff2` | La OFL exige que la licencia acompañe a la fuente. Texto oficial descargado del repo de Inter.

## Descartado (y por qué)
- **Reescribir el historial de git ahora** (`git filter-repo`) — destructivo para todos los
  clones y para la PR ya mergeada; lo decide y ejecuta Johan (ver Pendiente).
- **Borrar `workspace/referencias/openclaw/`** — se atribuye en vez de borrar; son la única
  traza de por qué se tomaron decisiones como la de entrada no confiable.
- **Scrub de "Johan" en comentarios de código** — es atribución al autor, no dato sensible.
- **`.gitattributes` para los avisos LF→CRLF** — ruido, no problema; fuera de alcance.

## Asumidos pendientes de confirmar
- Johan acepta GPL-3.0 (memoria del proyecto: "no dar por hecho la licencia hasta que la
  elija"; se creó el archivo porque él aprobó en bloque la recomendación que la nombraba y
  porque no hay otra viable sin migrar PyQt6 — si prefiere otra, se cambia un archivo).
- Se publican `workspace/adjuntos/` y `.claude/` tal cual (no se tocaron).

## Pendiente para Johan (bloquea la publicación, no este REQ)
1. **Revocar las claves que están en el historial** (el árbol actual está limpio, el historial
   no). Commits que versionaron `agente_ia/config.json` con claves reales: `b1ff0a5`
   (2026-03-22), `f9103e4` (2026-07-13), `b754ce3` (2026-07-22), y siguen presentes hasta
   `b6b3cd6` (2026-09-06) que lo sacó del repo. Contienen un token de bot de Telegram y una
   clave de DeepSeek (valores no reproducidos aquí a propósito). Revocar primero en
   @BotFather (`/revoke`) y en la consola de DeepSeek; después:
2. **Reescribir el historial o publicar en un repo nuevo.** Opción A (mismo repo):
   `pip install git-filter-repo` → `git filter-repo --path agente_ia/config.json --invert-paths`
   → forzar push de todas las ramas y avisar a quien tenga clones (hoy: solo él). Opción B:
   crear un repositorio nuevo con un único commit inicial desde el árbol actual — pierde el
   historial pero es lo más simple. Con las claves ya revocadas, la Opción B es segura y la A
   es cosmética.
3. Activar **Settings → Security → Private vulnerability reporting** en GitHub (lo referencia
   `SECURITY.md`).
4. Decidir si `workspace/adjuntos/` (225+ archivos de evidencia del pipeline) y `.claude/`
   viajan en el repo público. Hoy sí.
5. Nombre definitivo del producto (README, IDENTITY, THIRD_PARTY dicen "O.R.I.O.N.").

## Verificación
- `tests/test_identity.py` + `tests/test_user_identity.py`: 31 passed (5 nuevos).
- `tests/test_memory_scoring.py`: 20 passed (3 nuevos).
- `tests/test_documentos.py` + `tests/test_ui_tree.py` con deps: 102 passed. Simulando
  ausencia de `docx`/`uiautomation`/`openpyxl`/`pptx`/`fitz`: 39 passed, 63 skipped, **0
  failed** (antes: 59 failed, 4 errors).
- `tests/test_code_index.py`: 18 passed × 3 corridas seguidas.
- Suite completa (sin `test_webview_smoke.py`, que instancia QWebEngineView real): ver
  "Log de transiciones".

## Riesgos activos
- El `USER.md` de Johan sigue en su disco pero ya no se sincroniza entre sus equipos por git.
  Si usa la app en dos PCs, cada uno tendrá su copia (es el comportamiento deseado para un
  repo público; conviene que lo sepa).

## Log de transiciones
2026-09-18 | — → NUEVO | conversación principal | REQ creado vía update-tracker.mjs
2026-09-18 | NUEVO → LISTO_PARA_COMMIT | conversación principal (sesión nocturna) | 13 criterios de SPEC-042 cumplidos (CA-13 documentado, no ejecutable por el agente). Suite completa: **2776 passed** (sin `test_webview_smoke.py`) + **9 passed** del smoke aparte; 0 fallos. 8 tests nuevos.
