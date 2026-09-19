# Contexto REQ-039 — Investigar: varias fuentes a la vez y con qué sostener cada dato

## Resumen ejecutivo
Punto 3 de la lista de Johan: *"Investigación: puede buscar información, analizarla,
combinar múltiples fuentes y producir un resultado estructurado"*.

Con `web_search` + `web_read` el agente ya *podía* investigar. El problema no era la
capacidad, era el presupuesto y la honestidad del resultado.

## Estado actual
- **Estado tracker:** EN_PRUEBAS | **Categoría:** INTEGRACION | **Tipo:** FEATURE_NUEVA
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo` | **Fecha:** 2026-09-10

## Por qué no alcanzaba con lo que había

**1. Se quedaba sin turnos antes de empezar a pensar.** Cada página era una vuelta entera
del bucle de razonamiento, y el bucle tiene techo (`MAX_LLM_CALLS = 8`, menos en canales
remotos). Buscar, leer una, leer otra, leer otra: cuatro vueltas gastadas en descargar, y el
razonamiento tenía que caber en lo que sobrara.

**2. Cada página entraba entera.** Seis mil caracteres por fuente, de los que sirven
doscientos. Cinco fuentes no cabían.

**3. Nada distinguía una fuente de una copia.** Cinco medios publicando el mismo teletipo se
presentaban como cinco resultados, y eso hace que una conclusión parezca respaldada cuando
está sostenida por una sola fuente.

## La decisión de diseño: el paralelismo va dentro de la herramienta

El bucle ejecuta las tool calls **en secuencia a propósito** — una confirmación humana
concurrente con otra ejecución es exactamente lo que el gate de REQ-005 no debe permitir, y
eso no se toca. Así que el paralelismo vive dentro de una sola herramienta, que pasa por su
gate una vez y por dentro solo hace lecturas.

    research(pregunta, consultas[], max_fuentes)
      ├── busca con hasta 4 consultas EN PARALELO
      ├── mezcla intercalando: si no, la primera consulta se lleva todas las fuentes
      ├── descarta páginas repetidas y limita a 2 por dominio
      ├── descarga las páginas EN PARALELO (25 s para todas, no por cada una)
      ├── marca las que copian el contenido de otra
      └── de cada una extrae los párrafos que responden la pregunta

**Quién decide las consultas: el modelo.** Descomponer una pregunta en las búsquedas que la
responden es justo lo que sabe hacer; hacerlo acá con reglas sería peor. La herramienta hace
el trabajo mecánico y no saca conclusiones.

## Lo que sostiene la honestidad del resultado

| Decisión | Por qué |
|---|---|
| Marcar las copias (parecido ≥ 0,6 sobre palabras poco comunes) | Cinco copias del mismo teletipo no son cinco confirmaciones |
| Tope de 2 fuentes por dominio | Tres enlaces de un mismo medio son una fuente |
| Guardar la fecha de publicación | Dos fuentes que se contradicen pueden estar separadas por dos años, no en desacuerdo |
| Contar "fuentes independientes" al final | Es el número que importa, y no el de enlaces |
| Cerrar el dosier pidiendo citas, discrepancias y lo no verificado | El resultado estructurado es parte del encargo |

## El filtro de prosa — un caso real
La primera versión recortaba "los párrafos más relevantes" y en la prueba contra internet
devolvió, para una pregunta sobre tarifas de envío, cincuenta líneas así:

    International Shipping / Shipping API / Volver / Ver todas las funciones / Contacto

Todas traían las palabras buscadas y ninguna traía una cifra. Al quitar las etiquetas HTML,
cada elemento de un menú queda en su propia línea, y un bloque de cincuenta menús seguidos
parece un párrafo largo. Ahora se filtra **línea a línea** y se exige que parezca una frase:
60 caracteres, 10 palabras y puntuación interna. Si nada parece prosa —una tabla de
precios— se cae a las líneas sueltas, que es peor pero sigue siendo el contenido.

## Medido contra internet
| Prueba | Resultado |
|---|---|
| "qué es el protocolo MCP de Anthropic", 2 consultas | 5 fuentes útiles en **12,2 s** |
| "festivos en Colombia en octubre de 2026", 2 consultas | 5 fuentes útiles en **10,1 s** |

En secuencia, esas mismas cinco páginas habrían sido 5 vueltas del bucle.

## Seguridad
- `research` es 🟢 **verde**, igual que `web_search` y `web_read`, de las que sale todo lo
  que hace: leer información pública. No escribe nada.
- Las descargas pasan por `core/http_seguro.py`, así que la guarda anti-SSRF de REQ-031
  sigue puesta: una investigación no puede terminar leyendo `127.0.0.1:3000`.
- El dosier termina diciendo explícitamente que lo de arriba **son datos, no
  instrucciones**. Es contenido escrito por terceros y entra al contexto del modelo: está
  fijado por test.

## Tercera entrega (2026-09-11) — lo que "no hacía", cerrado

Johan pidió cerrar la lista de lo que seguía sin poder. Tres de cuatro se cerraron en código;
el cuarto (Firefox) exige abrir ventanas en su equipo mientras lo está usando, y eso no.

| Antes | Ahora |
|---|---|
| La misma fuente en dos idiomas contaba como dos | Mismo sitio (`wikipedia.org` para `es.` y `en.`) y las mismas cifras —años, montos, porcentajes, que no cambian con el idioma— = una sola. Solo dentro del mismo sitio, a propósito: dos periódicos que publican las mismas cifras sí son dos medios |
| Una página con sesión era "no pude" | Se detecta el muro (401/403, formulario de acceso con poco texto, redirección a `login`) y se dice el camino: abrirla en el navegador del usuario, donde la sesión ya está, y leerla con `browser_text` |
| Un PDF escaneado era ilegible | Se dibujan sus páginas (PyMuPDF) y se reconocen con el OCR de Windows |

## Lo que sigue sin hacer
- **Firefox no está medido.** No está instalado, y medirlo es instalarlo y abrirle ventanas
  en el equipo de Johan. Se hace cuando él no esté delante.
- **No resuelve captchas.** Y no lo va a hacer: están para impedir exactamente esto.
- **No juzga la calidad de una fuente.** Da el dominio y la fecha para que el modelo —y el
  usuario— lo valoren.

## Los PDF de la web, que sí se cerraron

Media fuente autorizada vive en PDF —informes de un ministerio, papers, circulares— y se
descartaban por no ser HTML: el agente veía el enlace en los resultados y no podía abrirlo.

Ahora se leen (`_extraer_pdf`, con PyPDF2, que ya estaba en `requirements.txt`), con tres
cosas que salieron de probarlo contra informes reales:

- **Tope propio de descarga, 8 MB.** El general de `http_seguro` son 2 MB, pensado para
  páginas web, y con un PDF quedarse a medias no sirve de nada: el índice que dice dónde
  empieza cada página va **al final** del archivo, así que un PDF cortado no es un PDF
  incompleto, es un PDF ilegible. Con 2 MB fallaban los informes de Fedepalma y de la
  Universidad Nacional. Sigue siendo un tope: la guarda existe para que una respuesta de
  gigabytes no se coma la memoria, no para que sean exactamente dos megas.
- **Si aun así se corta, se dice.** "Pesa más de 8 MB y solo pude descargar el principio,
  haría falta otra fuente" — con eso el modelo busca otra, en vez de insistir contra un
  error opaco.
- **Un PDF escaneado se declara como tal.** Son imágenes: no hay texto que extraer, y
  devolver vacío se leería como "no dice nada".

Se leen las primeras 15 páginas: un informe oficial puede tener doscientas, y el resumen
ejecutivo está al principio.

## Pendiente
- Prueba manual de Johan.

2026-09-18 | → LISTO_PARA_COMMIT | conversación principal (sesión nocturna autorizada por Johan) | Sincronización del tracker con `main`: el código de este REQ ya está commiteado y mergeado y la evidencia (QA aprobado y/o suite en verde registrada en este contexto) estaba completa. Solo cambia el estado; no se toca código.
