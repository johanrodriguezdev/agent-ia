# Desarrollo REQ-029 — Manos para trabajar con repos: archivos y git, confinados

**Fecha:** 2026-09-08 | **Agente:** orion-dev | **Rama:** `feature/REQ-027-reasoning-loop-nativo`

---

## Cómo se habilita la primera raíz (la feature nace inerte a propósito)

Sin configuración, las 8 herramientas están **registradas pero no operan sobre nada**: la
lista de carpetas habilitadas está vacía y `resolver()` rechaza cualquier ruta. Es
deliberado y es lo correcto — una herramienta de archivos sin confinamiento es acceso
total al disco.

Para habilitar la primera carpeta, crear `agente_ia/code_workspaces.json` (al lado de
`config.json` y `security_overrides.json`) con la lista de carpetas:

```json
[
  "C:\\Users\\WHOAMI\\Documents\\repos\\mi-proyecto"
]
```

También se acepta la forma con clave, por si más adelante se le agregan campos:

```json
{ "raices": ["C:\\Users\\WHOAMI\\Documents\\repos\\mi-proyecto"] }
```

Detalles que conviene saber antes de escribirlo:

- **Hay que reiniciar la app.** La lista se lee en cada llamada, así que en rigor toma
  efecto enseguida; pero el catálogo que ve el modelo se arma al inicio del turno, y el
  arranque es el momento en que esto se revisa de verdad.
- **Una entrada inválida se descarta sola, sin invalidar el resto.** Carpeta inexistente,
  archivo en vez de carpeta, entrada que no es texto: se ignora con `logger.warning` y las
  demás siguen funcionando. Descartar nunca agrega permisos.
- **Un archivo roto no habilita nada.** JSON corrupto, bytes no-UTF-8, un número en vez de
  una lista → lista vacía → el agente no toca nada. Nunca "sin restricciones".
- **La carpeta de O.R.I.O.N. no sirve como raíz.** Se puede escribir en el archivo, pero
  `resolver()` la rechaza igual y deja un `logger.critical`. Ver más abajo.
- **El archivo no está en `.gitignore`.** Contiene rutas absolutas de la máquina de Johan.
  No se agregó la línea porque `security_overrides.json` tampoco está y la decisión no
  estaba en la arquitectura aprobada — **queda como pregunta para el humano**: si se quiere,
  una línea `code_workspaces.json` en `.gitignore` lo resuelve.

Verificación rápida, ya con la carpeta habilitada: pedirle al agente *"listá las carpetas
que tenés habilitadas"* (llama a `file_list` sin ruta) y después *"¿cómo está el git de ese
repo?"* (`git_status`). Con el modo **Código/script** activo en el composer, las 8 aparecen
primero en el catálogo.

---

## Archivos modificados

### Nuevos

| Archivo | Qué es |
|---|---|
| `agente_ia/core/workspace_config.py` | Persistencia fail-closed de las carpetas habilitadas (`code_workspaces.json`), calcada de `core/security_config.py` (REQ-019) |
| `agente_ia/core/workspace_files.py` | `resolver()` —el confinamiento— más `listar/leer/buscar/escribir/editar` |
| `agente_ia/core/workspace_git.py` | `estado/diff/log` con `subprocess` sin shell y lista blanca de subcomandos |
| `agente_ia/tests/test_workspace_config.py` | 22 tests de fail-closed (CA-02) |
| `agente_ia/tests/test_workspace_files.py` | 45 tests de confinamiento y operaciones (CA-01, CA-03, CA-04, CA-10, CA-11, CA-12) |
| `agente_ia/tests/test_workspace_tools_seguridad.py` | 170 tests de niveles, canales, confirmación y git (CA-05 a CA-09, CA-13, CA-14, CA-15) |

### Tocados

| Archivo | Cambio |
|---|---|
| `agente_ia/core/security_manager.py` | `DESKTOP_ONLY_ACTIONS` + su evaluación al principio de `is_action_allowed()`; rama propia en `explain_denial()`; `"ruta"` en `_DETAILS_ALLOWED_KEYS`; registro de las 8 acciones con su nivel |
| `agente_ia/agents/tool_registry.py` | Las 8 `ToolSpec` con sus `invoke`; filtro de `DESKTOP_ONLY_ACTIONS` en `catalogo_para_modelo()`; entradas en `_PARAM_DE_DETALLE` |
| `agente_ia/core/composer_modes.py` | Modo `codigo`: las 8 al frente de `tool_names` y `prompt_hint` reescrito. `presupuesto=40` intacto |
| `agente_ia/core/acciones_legibles.py` | Descripción en castellano de `file_write` y `file_edit` (las dos amarillas) |
| `agente_ia/tests/test_composer_modes.py` | Actualizado el `tool_names` esperado del modo `codigo` (CA-15) |

## Dependencias agregadas

**Ninguna.** Todo es biblioteca estándar (`os`, `json`, `subprocess`, `tempfile`,
`logging`). `requirements.txt` no se tocó.

---

## Cómo quedó cada criterio

| CA | Dónde vive | Cómo se verifica |
|---|---|---|
| CA-01 | `workspace_files.resolver()` | 6 tests de escape: absoluta afuera, `..`, prefijo engañoso, **enlace real**, sin raíces, otra unidad |
| CA-02 | `workspace_config.cargar_raices()` | Ausente, corrupto, no-UTF-8, no-lista, entrada inválida → `[]` |
| CA-03 | `_es_instalacion()` en `resolver()` | Rechazo con la instalación FALSA (`tmp_path`) y con la **real**, ambas habilitadas como raíz |
| CA-04 | `_dentro_de()` con `commonpath` + `normcase` | `proyecto-malo` vs `proyecto`; case-insensitive en Windows |
| CA-05 | `_register_default_actions()` + `risk_level` de cada `ToolSpec` | Se fija en los **dos** lugares y que coincidan |
| CA-06 | `DESKTOP_ONLY_ACTIONS` en `is_action_allowed()` | 8 herramientas × 7 canales, y otra vez por `require_confirmation()` |
| CA-07 | El orden y el `return False` único | Test de invariante: agregar una acción a la tabla no puede volver `True` nada que fuera `False` |
| CA-08 | `path` (ya estaba) + `ruta` en `_DETAILS_ALLOWED_KEYS` | La ruta aparece; `content` y `buscar` **no** |
| CA-09 | `execute_tool()` | Ejecuta en escritorio, `ActionDenied` en Telegram/voz, confirmada/cancelada |
| CA-10 | `leer()` con `_MAX_LINEAS`/`_MAX_CARACTERES` | El aviso dice línea de corte y `desde=N` para seguir |
| CA-11 | `editar()` | 0 y >1 no escriben, y los mensajes se distinguen |
| CA-12 | `escribir()` con `resolver()` del padre | Crea intermedios adentro; fuera no crea ni el archivo ni las carpetas |
| CA-13 | `workspace_git.SUBCOMANDOS_PERMITIDOS` | `shell is False`, lista blanca, `cantidad` acotada a entero, `--` antes de la ruta |
| CA-14 | `_con_manejo()` en `tool_registry.py` | Texto explicativo, nunca stacktrace |
| CA-15 | `composer_modes.py` | Las 8 al frente y `presupuesto == 40` |
| CA-16 | Fixtures de los 3 archivos de test | `CODE_WORKSPACES_FILE` redirigido a `tmp_path`; git **nunca** se ejecuta de verdad (doble de `subprocess.run`) |
| CA-17 | Suite completa | **2143 passed, 0 failed** (baseline 1906 + 237 nuevos) |

---

## Decisiones de implementación

Todo lo de abajo son detalles que la arquitectura dejaba abiertos; ninguno se aparta de lo
aprobado.

1. **Rutas relativas resueltas contra las raíces, nunca contra el CWD.** El directorio de
   trabajo del proceso es el de O.R.I.O.N. y no tiene nada que ver con el repo del usuario.
   `_candidatas()` prueba la ruta contra cada raíz (gana la primera donde ya existe), y el
   resultado pasa igual por el confinamiento: elige candidata, no otorga permiso. Sin esto,
   `file_read("main.py")` habría apuntado al `main.py` de O.R.I.O.N.

2. **`buscar()` es literal, no una expresión regular.** Una regex que llega del modelo puede
   colgar el proceso con backtracking exponencial. Para encontrar un nombre de función en un
   repo, la búsqueda literal alcanza.

3. **Las raíces se pasan por `realpath` también dentro de `resolver()`**, no solo al
   cargarlas. Así el confinamiento no depende de que el caller haya normalizado bien: un
   llamador futuro que pase una raíz cruda no puede abrir un agujero por descuido.

4. **`catalogo_para_modelo()` no ofrece las 8 fuera del escritorio.** No es el control de
   seguridad —ese es `DESKTOP_ONLY_ACTIONS` dentro de `is_action_allowed()`—, es no ofrecer
   lo que se va a denegar: el filtro por nivel no las sacaba, porque 6 de las 8 son verdes.

5. **`explain_denial()` tiene rama propia para estas acciones.** Sin ella, un `file_read`
   desde Telegram contestaba *"ese canal solo lee y resume"* (la explicación de EMAIL), que
   es otra cosa. Ahora dice que solo funcionan delante del computador.

6. **`file_write` y `file_edit` entraron en `acciones_legibles.py`.** No estaba en la
   arquitectura, pero era obligatorio: el test `test_todas_las_acciones_que_piden_permiso_
   tienen_traduccion` (REQ-023) exige que toda acción amarilla tenga su frase en castellano,
   y sin eso la confirmación decía *"¿Quiere que ejecute file write?"*.

7. **`git_log`/`git_diff` con varias raíces piden que se elija.** Adivinar sobre cuál de
   tres repos preguntó el usuario es peor que preguntar. Con una sola raíz no hace falta.

8. **El contenido a escribir NO va al prompt de confirmación ni a la auditoría.** `path` sí
   (CA-08); `content`, `buscar` y `reemplazar` quedan fuera de `_DETAILS_ALLOWED_KEYS` a
   propósito: son largos y pueden traer secretos, y `details` se imprime al humano y se
   persiste en `audit.db`.

## Lo que NO se implementó, y por qué

- **`modify_source_code` sigue 🔴 RED y no se tocó.** El directorio de instalación queda
  excluido **en código** aunque se agregue como raíz en `code_workspaces.json`: mismo
  criterio con que `_merge_with_override()` (REQ-019) bloquea bajar un RED aunque se edite
  el JSON a mano. El intento queda con `logger.critical`.
- **`git_commit` y `git_push` no existen**, ni siquiera como subcomando alcanzable: la lista
  blanca es `{status, diff, log}` y `_correr()` la verifica antes de armar nada.
- **Borrar, mover y renombrar archivos** quedaron fuera de v1, como dice la SPEC.
- **La pantalla de Configuración para editar las raíces** no se hizo: v1 es el archivo, y la
  UI puede ser un REQ chico aparte (asumido pendiente del contexto).

## Límite conocido y aceptado

Entre el `realpath` y el `open()` hay una ventana **TOCTOU** teórica: alguien podría cambiar
un enlace en el medio. Quien pueda hacer eso ya tiene acceso de escritura a la máquina, así
que no es el vector que este REQ existe para cerrar. Queda documentado en el docstring de
`core/workspace_files.py`.

## Nota sobre los tests de enlaces

En Windows, `os.symlink` exige un privilegio que una sesión normal no tiene. El helper
`_crear_enlace()` intenta primero el symlink y cae a una **unión de directorio**
(`mklink /J`), que se crea sin permisos especiales y es exactamente el mismo vector: un
punto de reanálisis dentro de la raíz cuyo destino real está afuera, que `os.path.realpath`
resuelve igual. **En esta máquina los tests de enlace corren de verdad, no se saltean.**
`subprocess` se usa solo para fabricar el escenario dentro de `tmp_path`; el código bajo
prueba no ejecuta nada.

---

## Verificación

```
python -m py_compile   → OK en los 7 archivos de producción tocados
python -m pytest tests/ -q  → 2143 passed, 0 failed
```

Baseline de la noche: 1906 passed / 0 failed. Tests nuevos: 237. 1906 + 237 = 2143.
**Cero fallos nuevos y cero regresiones.**
