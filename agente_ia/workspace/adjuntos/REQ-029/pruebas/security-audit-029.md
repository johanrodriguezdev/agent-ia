# Auditoría de seguridad REQ-029

**Fecha:** 2026-09-09 (sesión nocturna) | **Auditor:** conversación principal
**Nota:** se lanzó `orion-security` para esta auditoría y se cortó por límite de sesión
antes de leer el código. La auditoría la hizo la conversación principal, con pruebas
ejecutadas de verdad contra el código —no revisión de lectura solamente.

## Veredicto

**APROBADO con un hallazgo bloqueante ya corregido.** El confinamiento resiste los 17
intentos de escape que se le tiraron. El hallazgo A era una fuga real de contenido fuera de
la raíz y está cerrado, con test de regresión que corre de verdad en esta máquina.

Queda pendiente de Johan la revisión personal del diseño completo, no de estos hallazgos.

---

## Hallazgo A — 🔴 BLOQUEANTE (corregido) — fuga de contenido por el recorrido de `buscar()`

**Dónde:** `core/workspace_files.py`, `buscar()` y `_coincidencias()`.

**Qué pasaba:** `resolver()` protege la ruta que **pide** el modelo, pero `buscar()` recorre
directorios y visita rutas que nadie pidió. `_coincidencias()` recibía las raíces y las
usaba solo para mostrar la ruta relativa — nunca para validar. Resultado: un enlace de
directorio dentro de una raíz habilitada, apuntando afuera, hacía que la búsqueda devolviera
el contenido de archivos de afuera. Y devolverlo significa mandarlo al proveedor del modelo.

**Por qué no lo tapaba `os.walk`:** `os.walk()` no desciende por symlinks, pero **en Windows
una junction no es un symlink para Python** (`os.path.islink()` devuelve `False`), así que
el recorrido entraba igual. No es teórico — se creó una junction real con `mklink /J`, que
no requiere privilegios de administrador:

```
== buscar() ==   (ANTES del arreglo)
Coincidencias de «PALABRA_MAGICA» (2):
  adentro.txt:1: PALABRA_MAGICA_ADENTRO
  atajo\secreto.txt:1: PALABRA_MAGICA_FUERA_DE_LA_RAIZ     <-- fuga
```

Lo llamativo: `resolver()` y `listar()` **sí** bloqueaban ese mismo enlace. El agujero
estaba solo en el camino que no pasa por `resolver()`.

**Corrección aplicada:** `_confinado(ruta, raices)` — resuelve con `realpath` y verifica
contra las raíces y contra el directorio de instalación. Se aplica en dos lugares, y los dos
hacen falta:
1. Podando `subdirs` en el `os.walk()`, para no descender por una carpeta que se escapa.
2. En `_coincidencias()`, antes de abrir cada archivo, para un enlace a nivel de archivo.

```
== buscar() ==   (DESPUÉS)
Coincidencias de «PALABRA_MAGICA» (1):
  adentro.txt:1: PALABRA_MAGICA_ADENTRO
```

**Regresión:** `tests/test_workspace_files.py` —
`test_buscar_no_se_lleva_contenido_de_afuera_por_un_enlace` y su contracara
`test_buscar_sigue_entrando_por_un_enlace_que_apunta_adentro`, para que el arreglo no
degenere en "no seguir ningún enlace". Los dos corren de verdad acá (la junction se crea, no
hay `skip`).

---

## Hallazgo B — 🟡 Aceptado, no bloqueante — TOCTOU entre validar y escribir

**Dónde:** `escribir()`/`editar()`, entre `resolver()` y el `open()`.

Quien pueda escribir en la carpeta habilitada podría, en la ventana entre la validación y la
escritura, reemplazar un directorio por un enlace que salga. Requiere acceso local de
escritura a una carpeta que el usuario ya decidió confiarle al agente, y Windows no ofrece
un equivalente simple de `O_NOFOLLOW` para cerrarlo del todo. **No bloquea el commit.**

---

## Hallazgo C — 🟡 Riesgo aceptado con recomendación — secretos dentro de una raíz habilitada

Un `.env`, un `id_rsa` o un `.git/config` con token que vivan **dentro** de una carpeta
habilitada son legibles, y leerlos los manda al proveedor del modelo. Es consecuencia
directa del diseño aprobado (el permiso se da por carpeta, no por archivo) y de que el
humano eligió esa carpeta.

**Recomendación para un REQ posterior, no para este:** que `buscar()` saltee por defecto los
nombres típicos de secretos (`.env`, `*.pem`, `id_rsa`, `*.key`) igual que hoy saltea
`node_modules`. Que `file_read` los siga leyendo si se los pide explícitamente es defendible;
que aparezcan solos en una búsqueda amplia, menos.

---

## Verificado sin hallazgos

| Punto | Resultado |
|---|---|
| **Confinamiento de rutas** | 17/17 intentos bloqueados: `..`, absoluta afuera, `hosts` de Windows, prefijo engañoso (`proyecto-malo` vs raíz `proyecto`), junction que sale, `~`, UNC, sin raíces, y 4 variantes contra el código de O.R.I.O.N. incluyéndolo habilitado como raíz. **Nada se escribió fuera de la raíz** (verificado en disco, no por el valor de retorno) |
| **Contenido de archivos en el modal y en `audit.db`** | No se filtra. `_DETAILS_ALLOWED_KEYS` incluye `path`/`ruta`/`filename`/`folder` pero **no** el contenido ni los fragmentos de `file_edit`. La confirmación muestra dónde se escribe, que es lo que hay que ver, sin arrastrar un `.env` entero al log |
| **Caminos que salteen el gate** | Ninguno. Las 8 funciones se importan solo desde `agents/tool_registry.py`, dentro de los `invoke` de sus `ToolSpec` — todas pasan por `execute_tool()` |
| **Inyección en git** | Sin `shell=True`; lista blanca `{status, diff, log}` verificada antes de armar el comando; la ruta del diff va detrás de `--` (aunque empezara con guion, git la trata como ruta); `cantidad` forzada a entero y acotada a 50; `status` con argumentos fijos |
| **`DESKTOP_ONLY_ACTIONS` solo resta** | Probado metiendo `open_app`, `delete_task` y `pc_type` en la tabla y comparando el antes/después en los 7 canales: ninguna acción pasó de denegada a permitida |
| **Alcance por canal** | 8/8 en escritorio, **0/8** en Telegram, Discord, voz, API, correo y canal desconocido |
| **`modify_source_code` sigue 🔴** | El intento de bajarlo a verde devuelve `False` y queda logueado como `CRITICAL`. El nivel no cambia |

## Suite
2143 tests en verde antes del arreglo del hallazgo A; el arreglo suma 2 tests de regresión.
