# Auditoría de seguridad — REQ-021

**Fecha:** 2026-08-26
**Auditor:** sesión principal (Claude Code). `orion-security` se lanzó dos veces y terminó por
límite de sesión de la API antes de escribir nada; la auditoría se hizo directamente sobre
`arquitectura-021.md`, `SPEC-021.md` y el código real de `core/security_manager.py`,
`core/resolution.py` y `ui/webview/bridge.py`.
**Objeto auditado:** el DISEÑO, antes de que exista código nuevo.
**Alcance:** los 6 puntos del encargo (vía de escape del diálogo, deuda P2, ventana de micrófono
como superficie nueva, aislamiento por `(user_id, canal)`, invariante de canal REQ-005/REQ-019,
y validación de input no confiable).

---

## Veredicto

**APROBADO CON DOS CORRECCIONES OBLIGATORIAS ANTES DE `orion-dev`.**

Ninguna de las dos es una vulnerabilidad: el gate de seguridad queda intacto y **no existe camino de
escalada de privilegios** en el diseño. La primera es una **contradicción entre dos criterios
aprobados** que haría fallar un test que la propia SPEC exige escribir; la segunda es una fuga de
contexto conversacional dentro de mensajes de denegación.

| # | Hallazgo | Nivel | Bloquea a `orion-dev` |
|---|----------|-------|------------------------|
| H1 | CA-18 y CA-30 se contradicen para el slot `cuando` | 🟡 Amarillo | **Sí** — hay que reescribir CA-18 |
| H2 | El post-hook de CA-31 se adhiere también a respuestas denegadas | 🟡 Amarillo | **Sí** — 1 condición extra |
| H3 | `DialogStore.open()` no valida `user_id` vacío | 🟢 Verde | No — endurecimiento |
| H4 | Ventana de micrófono + deuda P2: cambia el volumen, no la naturaleza | 🟡 Amarillo | No — aceptado con condiciones |
| H5 | El gate `require_confirmation()` queda intacto | 🟢 Verde | No — verificado correcto |
| H6 | Aislamiento por `(user_id, canal)` correcto | 🟢 Verde | No — verificado correcto |

---

## H1 — 🟡 CA-18 y CA-30 se contradicen para el slot `cuando`

### El problema

CA-18 dice, literalmente:

> Con un diálogo abierto, una frase que contenga un trigger de una acción `YELLOW` o `RED` se trata
> como texto del slot pendiente y **no** ejecuta esa acción. Test explícito con al menos un trigger
> `YELLOW` y uno `RED`.

CA-30 dice, literalmente:

> Con un diálogo abierto, una frase que claramente no responde al slot pendiente ("qué hora es") se
> resuelve como comando nuevo por el orden normal de `RESOLVERS`, el agente **responde esa
> pregunta**, y el diálogo pendiente **sigue vivo**.

Los dos no pueden ser ciertos a la vez. El diseño de `_answers_slot()` (§4.3 de
`arquitectura-021.md`) es **asimétrico a propósito**, y esa asimetría decide cuál gana en cada caso:

| Slot pendiente | Criterio | Qué pasa con `"apaga el pc"` |
|---|---|---|
| `que` | Acepta todo lo que no sea interrogativo | Se guarda como **título del recordatorio**. No se ejecuta. **CA-18 se cumple.** |
| `cuando` | Exige match positivo de `_parse_natural_date()` | No parsea como fecha → `_try_pending_dialog` retorna `None` → cae a los resolvers → **se ejecuta**. **CA-18 se incumple.** |

Con el slot `cuando` pendiente, el test que CA-18 obliga a escribir **falla por diseño**.

### Por qué NO es una vulnerabilidad

Verificado contra el código real: cuando la frase se desvía y se ejecuta, lo hace por el camino
normal de `RESOLVERS`, que termina en `execute_tool()` / `dispatch()`, que llaman a
`security_manager.require_confirmation()` con **el canal real que pasó el caller**. El estado del
diálogo no toca esa cadena en ningún punto:

- El nivel efectivo de la acción es el mismo con diálogo abierto que sin él.
- Una acción `YELLOW` sigue pidiendo confirmación.
- Una acción `RED` sigue bloqueada por el fail-closed de REQ-005.
- `PendingDialog.action` se fija en `open()` y no tiene setter, así que el contenido de un slot
  **nunca** puede cambiar la acción destino (CA-19 se cumple sin reservas).

Es decir: el diálogo **no abre ninguna puerta que no estuviera ya abierta**. Lo que está roto es la
redacción de CA-18, que promete más de lo que el diseño hace — y más de lo que conviene que haga,
porque cumplir CA-18 al pie de la letra obligaría a tragarse silenciosamente cualquier frase durante
un diálogo abierto, rompiendo CA-30 y el comportamiento conversacional que Johan pidió.

### Corrección obligatoria

Reescribir CA-18 para que afirme lo que de verdad importa y es verificable:

> **CA-18 (reescrito)** — El diálogo **no altera el nivel efectivo de riesgo de ninguna acción ni
> evita el gate de confirmación**. Con un diálogo abierto, una frase con trigger `YELLOW` o `RED`
> que **no responde** al slot pendiente se resuelve por el camino normal y pasa por
> `require_confirmation()` exactamente igual que si no hubiera diálogo (test con un trigger `YELLOW`
> y uno `RED`: se verifica que el gate se evalúa con el canal real, no que la acción no ocurra).
> Con el slot `que` pendiente, una frase no interrogativa se guarda como texto del slot y no se
> ejecuta — comportamiento *fail-safe* deliberado, no defecto.

---

## H2 — 🟡 El post-hook de CA-31 se pega también a las denegaciones

### El problema

El post-hook de `resolve()` (§4.4) añade `"\n\nPor cierto, {dialog.question}"` a **cualquier**
resultado que no venga del propio resolver de diálogo. Incluidos:

- `ResolutionResult(..., denied=True)` — el mensaje `⛔ Acción 'X' no autorizada.`
- Los mensajes de error de un resolver que falló.

Resultado para el usuario:

```
⛔ Acción 'shutdown_pc' no autorizada.

Por cierto, ¿para cuándo se lo recuerdo?
```

Mezclar un aviso de seguridad con una repregunta conversacional degrada el aviso: lo convierte en
parte de una charla en vez de en un corte. Es exactamente el patrón que `.claude/rules/security-levels.md`
quiere evitar cuando exige que las acciones denegadas queden claras y registradas.

### Corrección obligatoria

Excluir del post-hook los resultados con `denied=True`. Una condición más en el `if` que ya existe:

```python
if not result.denied \
        and not result.matched_by.startswith("pending_dialog") \
        and result.matched_by != "task_tool:dialog_open":
```

El diálogo sigue vivo (no se cancela), simplemente no se le cuelga la repregunta a un mensaje de
denegación. La repregunta reaparece en el turno siguiente.

---

## H3 — 🟢 `DialogStore.open()` debe rechazar `user_id` vacío

`resolve()` tiene `user_id: str = "default"`, pero en Telegram y Discord el `user_id` lo aporta el
bot. Si alguna vez llegara vacío o `None`, todos esos usuarios compartirían la clave `("", canal)` y
**el diálogo de uno respondería al de otro**.

No hay hoy ningún camino conocido que produzca eso, por lo que es endurecimiento y no corrección.
Recomendación para `orion-dev`: `open()` lanza `ValueError` si `user_id` es falsy. Un diálogo sin
dueño no debe existir. Cuesta una línea y cierra la única vía de fuga entre usuarios que tiene el
diseño.

---

## H4 — 🟡 Ventana de micrófono y deuda P2: veredicto explícito

### La pregunta del encargo

¿La ventana de ~15 s convierte la deuda P2 (la voz del webview se resuelve como `DESKTOP`, no como
`VOICE`, así que la regla "por voz solo acciones verdes" no se le aplica) en bloqueante?

### Veredicto: **sigue siendo aceptable en v1**, con tres condiciones.

El razonamiento, siguiendo lo que puede pasar de verdad. Durante los ~15 s se acepta y ejecuta una
frase sin wake word. Peor caso por nivel:

| Nivel | Qué pasa hoy con una transcripción espuria | ¿Agravado por la ventana? |
|---|---|---|
| 🔴 Rojo | Bloqueado por el fail-closed de REQ-005, sin importar el canal | No |
| 🟡 Amarillo | Pide confirmación; Johan la ve y la rechaza | No en naturaleza — sí en frecuencia |
| 🟢 Verde | Se ejecuta (abrir app, buscar, decir la hora) | Sí, en frecuencia |

La ventana **no cambia qué puede ejecutarse**, solo **cuántas veces se intenta**. Ninguna acción
destructiva pasa sin confirmación humana, ni antes ni después de este REQ.

Lo que sí cambia de naturaleza, y conviene decirlo sin adornos: **hasta ahora la palabra de
activación funcionaba de facto como control de acceso a la ejecución por voz.** Con la ventana
abierta hay ~15 s por turno en los que la televisión, o cualquiera en la sala, puede disparar una
acción verde sin decir "Orión". Es una decisión de producto que Johan tomó a sabiendas (fue una de
las tres decisiones cerradas), y el diseño la mitiga razonablemente.

### Condiciones para que siga siendo aceptable

1. **`consume()` debe estar implementado de verdad**: una frase por ventana. Es la mitigación
   principal — sin ella, un ruido continuo podría encadenar ejecuciones durante los 15 s completos.
2. **`MIC_WINDOW_SECONDS` en un único lugar** (ya está en el diseño), para poder bajarlo tras la
   prueba en vivo sin rediseñar nada.
3. **La deuda P2 se convierte en REQ propio**, no se queda como nota. Con la ventana abierta, el
   volumen de frases que entran por esa vía deja de ser marginal. Recomendación: REQ posterior que
   resuelva `_on_voice_command` como `VOICE` y, a la vez, revise qué acciones amarillas se quieren
   permitir por voz — porque hacerlo sin esa revisión rompería cosas que hoy le funcionan a Johan.

---

## H5 — 🟢 El gate queda intacto (verificado)

- `scan_task_slots()` se llama fuera del gate, pero es **función pura**: no ejecuta, no persiste, no
  consulta red. Correcto — el gate sigue donde estaba.
- La rama de ejecución del diálogo completo llama a `execute_tool(action, {...}, channel, user_id)`
  con el `channel` que recibió el resolver, resuelto una sola vez por `security_manager.resolve_channel()`
  en `resolve()`. **Nunca se deduce del texto ni del estado del diálogo.** Invariante de REQ-005 y
  REQ-019 respetado.
- `PendingDialog.action` se fija en `open()` y no se puede reasignar → CA-19 cumplido.
- Las ramas `list` / `complete` / `complete_all` de `_try_task_tool` no se tocan.
- La única acción alcanzable por diálogo en v1 es `task_create`, clasificada `GREEN`.

## H6 — 🟢 Aislamiento correcto (verificado)

- Clave `(user_id, channel.value)`, construida siempre desde los argumentos del resolver.
- `threading.RLock` en todos los métodos — necesario, porque `resolve()` corre en el hilo de
  `QThreadPool` en el webview, en el del bot en Telegram/Discord y en el principal en la consola.
- Expiración evaluada al leer, sin hilo de fondo: un diálogo abandonado no ejecuta nada por su
  cuenta. Coherente con la decisión de descartar en silencio.
- Único punto débil: H3.

---

## Secretos

Ninguno nuevo. El REQ no introduce API keys, tokens ni credenciales, y no añade dependencias
(`requirements.txt` no se toca). `ask_question()` envía al LLM el nombre del slot y los slots ya
llenos —contenido que el usuario acaba de dictar—, por el mismo proveedor y camino que ya usa
`reasoning_loop`. Sin cambio en la superficie de exposición.

---

## Lo que le queda PROHIBIDO a `orion-dev`

1. **Debilitar el guard `_resolution_in_flight`** para que pase el segundo turno. La arquitectura lo
   resuelve por construcción del timeline (§7); aflojarlo abriría resoluciones concurrentes sobre
   estado compartido.
2. **Leer el canal de `params`** o del texto en cualquier punto nuevo. El canal viaja resuelto desde
   `resolve()` y solo desde ahí.
3. **Mover el gate.** `require_confirmation()` se queda dentro de `execute_tool()`. Nada de gatear
   dentro del cuerpo del diálogo, del scan o de la ventana de micrófono.
4. **Permitir que el contenido de un slot cambie `PendingDialog.action`.** Sin setters, sin
   reasignación.
5. **Persistir el diálogo en disco.** Es memoria del proceso, por decisión de Johan — y además
   persistirlo crearía un estado de seguridad que sobrevive al reinicio sin haber sido auditado.
6. **Añadir un hilo de fondo o un timer** para la expiración. Se evalúa al leer.
7. **Colgar la repregunta de CA-31 a un mensaje de denegación** (H2).
8. **Aceptar un `user_id` vacío en `open()`** (H3).

---

## Pruebas de seguridad que deben existir

- Con diálogo abierto y slot `que`: `"apaga el pc"` se guarda como título y `dispatch` **no** se
  invoca. (fail-safe)
- Con diálogo abierto y slot `cuando`: `"apaga el pc"` se desvía, y `require_confirmation()` se
  invoca **con el canal real**, no con uno deducido. (CA-18 reescrito)
- Con diálogo abierto, una acción `RED` sigue bloqueada por el fail-closed.
- Dos `user_id` distintos en el mismo canal: sin fuga de diálogo. Dos canales del mismo `user_id`:
  sin fuga.
- `open()` con `user_id` vacío lanza.
- Un resultado `denied=True` **no** lleva la repregunta colgada.
- `resolve()` con `dialog_store` vacío produce el mismo `matched_by` que hoy para los 7 resolvers.
