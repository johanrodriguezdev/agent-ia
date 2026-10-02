# Contexto REQ-071/072/073 — La especificación de comportamiento, hecha código

## Resumen ejecutivo
Johan pasó la **especificación de comportamiento de O.R.I.O.N.** (40 secciones: identidad,
personalidad, economía de la respuesta, errores, estados, transparencia) y el diagrama de
arquitectura, y pidió analizarlos. El análisis: la arquitectura del diagrama **ya está
construida casi entera**; lo que faltaba era que la personalidad fuera un mecanismo y no
prosa. Tres REQs lo cierran:

- **REQ-071** — la regla fundamental (§3, §24, §27, §38): economía de la respuesta, con
  medición.
- **REQ-072** — §12: errores que se entienden.
- **REQ-073** — §11/§14/§28/§39: no fingir, cuándo callarse el humor, hecho vs inferencia.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT (los tres)
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE | **Fecha:** 2026-10-02

## El análisis que sostiene todo esto

### La arquitectura del diagrama ya existía
| En el diagrama | En el código |
|---|---|
| Intent Detection | `intent/`, `nlp/` (TF-IDF + SVM) |
| Context Manager | `core/agent_context.py` |
| Memory Manager | `ai/memory_manager.py` + semántica + `MEMORY.md` (las tres capas) |
| Task Planner | `agents/task_planner.py` |
| Safety Layer | `core/security_manager.py` |
| Tools | `agents/tool_registry.py` (68 herramientas) |
| System | `os_integration/`, `system_actions/` |
| Response Generator → TTS | `ui/tts_engine.py` |
| Response Generator → **Tone/Personality** | **el eslabón débil: solo prosa en SOUL.md** |

### La medición que disparó REQ-071
Sobre las **170 respuestas reales** guardadas en la memoria del agente, antes de este REQ:

    mediana 374 caracteres · media 778 · p90 1.804 · máxima 6.570
    de una línea (≤80): 24 %   ·   largas (>400): 49 %

La mitad de las respuestas pasaba de 400 caracteres, con el prompt pidiendo ya «concisa y
directa». **Pedir brevedad en prosa no la produce.**

### Lo que se encontró para REQ-072
58 sitios devolvían la excepción cruda pegada a una frase (`f"No pude abrir Spotify: {e}"`),
que en pantalla es «[WinError 5] Acceso denegado» o una ruta completa del disco del usuario.

## Arquitectura
- **`core/estilo_respuesta.py`** — el `CONTRATO` que viaja en el prompt (con el contraste
  MAL/BIEN, que es lo que un modelo copia; un adjetivo, no) y el medidor:
  `registrar()` anota **longitud, canal y si hubo herramientas, nunca el texto**, en
  `logs/longitud_respuestas.jsonl` acotado a 5.000 medidas; `estadisticas()` devuelve
  mediana, media, p90 y el reparto, con la opción de mirar solo los turnos sin herramientas
  —un turno que investigó cinco fuentes puede ser largo con razón, y mezclarlo haría que la
  media no dijera nada—.
- **El contrato viaja por los dos caminos**: `core/reasoning_loop.py` (escritorio y voz) y
  `ai/claude_brain.py` (Telegram y Discord), desde **una sola fuente**. Ya divergieron una
  vez y el agente sonaba distinto según el canal.
- **`core/errores.py`** — `causa(e)` traduce la excepción a castellano llano por tipo
  primero y por código después (`winerror`, `errno`); `explicar(e, intento)` arma la frase
  del usuario y manda el detalle completo al log; `detalle_tecnico(e)` es lo que se da si
  lo piden, en una línea.

## Decisiones tomadas
2026-10-02 | conversación principal | Medir, no solo pedir | Sin medición, dentro de un mes nadie sabría si el contrato sirvió. Ahora hay un antes (mediana 374) contra el que comparar.
2026-10-02 | conversación principal | El registro no guarda el texto | Para leer conversaciones está la memoria; un archivo de métricas no tiene por qué contener nada que el usuario haya escrito.
2026-10-02 | conversación principal | Lo que no se reconoce NO se inventa | Decir «parece un problema de permisos» sin saberlo manda al usuario a buscar donde no es. Se nombra el tipo, que es un dato real.
2026-10-02 | conversación principal | El contrato se mantiene por debajo de 2.600 caracteres, con test | Cada regla cuesta tokens en cada llamada: un contrato de economía que engorda el prompt sin límite se contradice a sí mismo.
2026-10-02 | conversación principal | **SOUL.md no se toca** | Define quién es O.R.I.O.N. y es de Johan. Si hay que alinearlo con la especificación nueva, se propone el texto y lo aprueba él.

## Qué cambia en el uso
- «Abrí Chrome» → «Abriendo Chrome.» en vez de un párrafo.
- Un fallo de permisos → «No pude abrir Spotify: no tengo permisos para hacerlo.» en vez de
  «[WinError 5] Acceso denegado». El detalle técnico queda en el log y se puede pedir.
- Una suposición se dice como suposición («Creo que este es el que buscas»), no como hecho.
- El humor se calla ante un error importante, un usuario frustrado o algo peligroso.

## Qué no hace todavía
- **Los estados de la §22**: hay 4 (`IDLE`, `LISTENING`, `PROCESSING`, `RESPONDING`); la
  especificación define 9. Faltan `THINKING`, `EXECUTING`, `WAITING_CONFIRMATION`, `ERROR`,
  `COMPLETED` como estados visibles. `core/progress.py` ya cubre buena parte con más
  detalle («Creando el documento», «Buscando en internet»), por eso no era lo urgente.
- **La variación de frases (§6, §33)** se deja al modelo, que ya varía. No hay un rotador
  de frases en el código.
- **Los 49 sitios restantes** con excepción cruda: se tocaron los 9 más visibles (abrir
  programas, navegador, terminal, teclado, clic). El patrón queda para el resto.

## Verificación
- `tests/test_estilo_respuesta.py`: 15 tests — que el contrato llegue por **los dos**
  caminos, que medir no pueda romper una conversación, que no se guarde el texto, y las
  reglas de REQ-073.
- `tests/test_errores.py`: 19 tests — cada tipo de fallo, los códigos del sistema, que no
  se inventen causas, que el mensaje no lleve rutas ni volcados, y que el detalle sí quede
  en el log.
- `pruebas/suite-071.txt`: suite completa.

## Prueba manual sugerida (Johan)
1. «Abrí Chrome» → tiene que contestar en una línea, sin párrafo de cortesía.
2. Pedile algo que falle por permisos → el mensaje tiene que explicar la causa, sin
   `WinError` ni rutas.
3. Preguntale algo que requiera explicar («¿por qué conviene X sobre Y?») → ahí **sí** debe
   extenderse: el contrato pide economía, no mutismo.
4. Después de unos días: pedile sus propias estadísticas de longitud y comparar con la
   mediana de 374 de antes.

## Log de transiciones
2026-10-02 | NUEVO → LISTO_PARA_COMMIT | conversación principal | Análisis de la especificación + los tres REQs. Autorizado en bloque por Johan.
