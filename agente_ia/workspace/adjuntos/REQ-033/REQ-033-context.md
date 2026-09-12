# Contexto REQ-033 — El modo autonomía

## Resumen ejecutivo
Que el agente pueda trabajar sin preguntar **cuando el dueño decide que así sea**. Tres
niveles configurables desde la pantalla de Seguridad: `normal` (como siempre), `proyectos`
(escribe, edita y ejecuta sin interrumpir dentro de las carpetas habilitadas) y `total`
(además puede modificar su propio código, con PIN maestro y rama de git).

## Estado actual
- **Estado tracker:** EN_PRUEBAS
- **Último agente:** conversación principal
- **Fecha última actualización:** 2026-09-09
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** SEGURIDAD
- **Tipo de cambio:** FEATURE_NUEVA + SEGURIDAD

## Origen
Johan, 2026-09-09: *"quiero que desde configuración podamos dejar una opción para esas
reglas de decisión (...) si quiero que trabaje toda la noche me va a hacer preguntas y no voy
a estar disponible, entonces quiero darle toda la aprobación"*. Y explícitamente: *"quiero
que él pueda tocar su propio código si es para mejorarlo, sé que puse reglas pero me gustaría
poder tener la libertad de quitarlas"*.

El pedido es legítimo y el diagnóstico es correcto: **un agente que pregunta cuando no hay
nadie no es seguro, es inútil**. El permiso se pide igual, nadie lo contesta, la acción se
cancela y la noche se pierde.

## La idea que hace esto defendible
No se bajan los niveles de riesgo. Bajarlos sería permanente y alcanzaría a **todos los
canales** — un `modify_source_code` en verde lo vuelve alcanzable desde Telegram y desde una
inyección en una página que el agente lea mientras investiga.

Se invierte: se cambia **un permiso débil repetido** (veinte confirmaciones a las 3 de la
mañana que nadie va a leer) por **una autorización humana fuerte, hecha una vez, delante de
la máquina**. Es la misma forma del modelo de aprobaciones de OpenClaw que la auditoría
`01-seguridad-y-aislamiento.md` llamó *"la pieza más transferible a O.R.I.O.N."*.

Y para su propio código, la protección que sirve **no es adivinar si "es para mejorar"** —
ningún gate puede evaluar esa intención— sino que **todo sea reversible**: rama de git
propia, y a la mañana se ve el diff y se vuelve atrás con un comando.

## Lo que queda fuera del interruptor, y no es configurable
1. **Los canales remotos.** El modo solo vale en `DESKTOP`. Está fijado con un test por cada
   uno de los seis canales.
2. **Los otros nueve rojos de REQ-005.** Formatear discos, borrar bases, exponer
   credenciales, mandar correo como el usuario, instalar software, privilegios elevados. El
   pedido era sobre programar.
3. **Las amarillas que no son de trabajo.** Apagar el equipo, mandar un mensaje, habilitar
   otra carpeta: siguen preguntando. La lista blanca es `file_write`, `file_edit`,
   `project_run` y nada más.
4. **Encenderlo no es una herramienta del agente.** No existe ninguna `ToolSpec` que llegue
   a `core/autonomy.py`, y hay un test que lo verifica. Si el agente pudiera encender su
   propia autonomía, bastaría una instrucción inyectada en una página para que se suelte
   solo. **Esta es la regla que sostiene a las otras tres.**

## Decisiones de Johan
1. **Vigencia: hasta que él lo apague** (se le ofreció que expirara en horas). Mitigación
   que no contradice su elección: el modo es imposible de no ver — insignia permanente en la
   barra de la ventana, con la fecha desde la que está encendido, y `logger.critical` al
   encenderlo.
2. **Su propio código: siempre en una rama de git aparte.** Sin repositorio git, el nivel
   total no se enciende.
3. **El nivel total pide el PIN maestro.**

## Decisiones tomadas
2026-09-09 | conversación principal | Sin `ORION_AUTH_PIN` configurado, el nivel total NO se enciende | `verify_pin()` devuelve `True` cuando no hay PIN: permitirlo así sería una verificación de mentira. Johan eligió que lo pidiera
2026-09-09 | conversación principal | El modo autoriza acciones puntuales, no baja niveles | `modify_source_code` sigue siendo 🔴 con el modo encendido, y hay un test que lo fija. Bajarlo sería permanente y alcanzaría a todos los canales
2026-09-09 | conversación principal | La aprobación se evalúa DESPUÉS del chequeo de canal | Así la autonomía nunca le da permisos a un canal que no los tenía: solo se saltea la pregunta donde la acción ya estaba permitida
2026-09-09 | conversación principal | El nivel `proyectos` no pide PIN | Es el caso de todos los días; pedir PIN para trabajar en un repo propio sería fricción sin ganancia

## Riesgo que Johan acepta, dicho sin adornos
Con el modo encendido y sin nadie delante, una inyección de prompt en algo que el agente lea
puede hacerle escribir archivos o correr comandos dentro de las carpetas habilitadas sin que
nadie confirme. Eso es inherente a lo que se pidió. Lo que lo acota: solo el escritorio, solo
esas tres acciones, solo esas carpetas, todo en `audit.db`, y en el nivel total todo en una
rama de git que se puede revisar y descartar entera.

## Segunda entrega (2026-09-10) — la promesa del historial, cumplida

El documento decía: *"el trabajo va a una rama propia, **cada cosa queda en el historial**, y
a la mañana se ve el diff completo y se vuelve atrás con un comando"*.

La rama se creaba. **Nadie confirmaba nada.** A la mañana, el trabajo de ocho horas era un
único bulto sin commitear: se podía tirar entero, pero no revisar paso a paso ni quedarse con
la mitad buena. La promesa estaba escrita y no implementada — que es peor que no haberla
hecho, porque se decide encender el modo confiando en ella.

`autonomy.registrar_cambio(accion, ruta)` deja ahora un commit por cada cambio, y está
enganchado en `core/workspace_files.py`, que es el único sitio donde una escritura ocurre de
verdad: así ninguna vía nueva de escritura puede olvidarse de dejar rastro.

Tres límites, y los tres importan:

- **Se confirma solo el archivo tocado** (`git commit -- <ruta>`), nunca `git add -A`. Si
  Johan se fue a dormir con trabajo suyo a medias, barrérselo dentro de un commit del agente
  sería mezclarle sus cambios con los de la noche.
- **Solo su propio código.** El repositorio del usuario es suyo: el agente no le escribe el
  historial aunque esté trabajando ahí.
- **Solo en la rama de autonomía.** Si al volver la rama activa es otra, no se escribe nada
  y queda en el log: confirmar sobre una rama que no es la del trabajo es justo lo que este
  modo existe para evitar.

Que git falle no deshace una escritura que ya se hizo bien: se avisa en el log y se sigue.

## Log de transiciones
2026-09-09 | — → EN_PRUEBAS | conversación principal | Núcleo, gate, confinamiento, interruptor, indicador y 56 tests
2026-09-10 | EN_PRUEBAS | conversación principal | Segunda entrega: cada cambio queda en el historial, 9 tests más
