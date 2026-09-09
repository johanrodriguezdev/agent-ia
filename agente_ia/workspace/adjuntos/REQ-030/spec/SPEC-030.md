# SPEC-030 — Habilitar carpetas por instrucción + la búsqueda no lee secretos

**Categoría:** CORE | **Tipo:** MEJORA + SEGURIDAD | **Fecha:** 2026-09-09

Cierra los dos pendientes que dejó REQ-029: la feature nacía inerte y solo se encendía
editando un JSON a mano, y la búsqueda podía devolver el contenido de un `.env`.

## Criterios de aceptación

### Habilitar y quitar carpetas
- [x] **CA-01** — `workspace_add_folder` habilita una carpeta y el permiso persiste entre
  arranques (se guarda en `code_workspaces.json`, con escritura atómica).
- [x] **CA-02** — Es idempotente: pedir una carpeta ya habilitada no falla ni la duplica.
- [x] **CA-03** — `workspace_remove_folder` quita una carpeta y **avisa** si no estaba
  habilitada, en vez de decir "listo" — quien se equivocó de carpeta creería haber cerrado
  un acceso que sigue abierto. Quitar una no toca las demás.
- [x] **CA-04** — La ruta que se le devuelve al usuario conserva su capitalización original,
  no la normalizada en minúsculas que se usa para comparar.

### Qué no se puede habilitar (aunque el humano confirme)
- [x] **CA-05** — La raíz de un disco.
- [x] **CA-06** — Una carpeta del sistema (`Windows`, `Program Files`, `ProgramData`,
  `System32`, `SysWOW64`, `$Recycle.Bin`).
- [x] **CA-07** — La carpeta personal entera (`C:\\Users\\alguien`) y la que las contiene.
  Pero **sí** una carpeta de adentro: `Documentos/repos/proyecto` se habilita sin problema.
- [x] **CA-08** — El código de O.R.I.O.N. ni ninguna subcarpeta suya, rechazado **antes** de
  escribir la configuración y logueado con `logger.critical`.
- [x] **CA-09** — Una carpeta que no existe.
- [x] **CA-10** — Una carpeta rechazada **no deja rastro**: el archivo de configuración no se
  crea ni se modifica.

### Alcance por canal
- [x] **CA-11** — Las dos son 🟡 YELLOW y están en `DESKTOP_ONLY_ACTIONS`: 2/2 en escritorio,
  0/2 en Telegram, Discord, voz, API, correo y canal desconocido.
- [x] **CA-12** — La confirmación muestra la ruta (`path` ya está en
  `_DETAILS_ALLOWED_KEYS`), y las dos tienen su frase en castellano en
  `core/acciones_legibles.py` — sin eso el modal diría "¿Quiere que ejecute workspace add
  folder?".

### La búsqueda no lee credenciales
- [x] **CA-13** — `buscar()` saltea `.env`, `.env.*`, `*.pem`, `*.key`, `*.pfx`, `*.p12`,
  `*.ppk`, `*.jks`, `id_rsa`, `id_dsa`, `id_ecdsa`, `id_ed25519`, `.netrc`,
  `credentials.json`, `service-account*.json` y `*.keystore`.
- [x] **CA-14** — Avisa cuántos salteó. Saltearlos en silencio dejaría al modelo concluyendo
  que el dato no existe.
- [x] **CA-15** — `file_read` **sí** los lee si se los piden por su nombre: pedir `.env`
  explícitamente es la decisión de alguien; que aparezca solo en una búsqueda amplia, no.

### Regresión
- [x] **CA-16** — Los tests de REQ-029 que fijaban "las 8" pasan a fijar "las 8 + las 2", y
  las pruebas de canal recorren las 10.
- [x] **CA-17** — Ningún test toca el `code_workspaces.json` real ni carpetas fuera de
  `tmp_path`. Suite completa sin fallos nuevos.
