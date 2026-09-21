# Contexto REQ-062 — «Mirá esta imagen»: la herramienta `image_look`

## Resumen ejecutivo
Con REQ-054 el agente ve lo que se pega en el chat. Esto es lo mismo por instrucción,
sin pegar nada: «mirá la captura que está en el Escritorio y decime qué error es»,
«describí fotos/gato.jpg», «¿qué dice el cartel de la foto que bajé?». La herramienta
`image_look(path, question)` manda la imagen al modelo de visión (Configuración →
Modelos → «Ver imágenes», REQ-061) en una llamada propia —fuera del streaming del turno,
como el análisis de pantalla— y devuelve la descripción o la respuesta.

## Estado actual
- **Estado tracker:** LISTO_PARA_COMMIT
- **Rama git:** `feature/REQ-027-reasoning-loop-nativo`
- **Categoría:** CORE
- **Tipo:** FEATURE_NUEVA

## Origen
Noche del 2026-09-20, aprobación en bloque de Johan. Es un asistente, no una app: lo que
se puede pedir hablando se pide hablando ([[feedback_asistente_no_crud]]).

## Decisiones tomadas
2026-09-20 | conversación principal | 🟢 verde y solo escritorio (`DESKTOP_ONLY_ACTIONS`), como `file_read` | Leer un archivo es mandárselo al proveedor del modelo; verde no puede significar «alcanzable desde Telegram». Por Telegram las fotos se mandan al chat y ya.
2026-09-20 | conversación principal | Solo dentro de la carpeta personal, los espacios de trabajo habilitados y `users_data/` (imágenes pegadas); nunca en carpetas de configuración (`.ssh`, `AppData`, …) | Mismo criterio que `core/documentos.py` para escribir, aplicado a leer (`core/imagenes.resolver_para_mirar`).
2026-09-20 | conversación principal | La extensión Y la firma del archivo tienen que ser de imagen (`_tipo_por_firma`) | Un `.png` que no es PNG no se manda a ningún lado.
2026-09-20 | conversación principal | Ruta relativa = relativa al Escritorio | Es donde suele estar lo que se acaba de guardar.
2026-09-20 | conversación principal | Sin modelo de visión disponible la herramienta lo dice y apunta a Configuración → Modelos → «Ver imágenes» | Un «no pude» sin la causa obliga a adivinar.

## Archivos
- Tocados: `core/imagenes.py` (`ImagenRechazada`, `_raices_para_mirar`, `resolver_para_mirar`,
  `_tipo_por_firma`), `agents/tool_registry.py` (`image_look`, detalle `path`),
  `core/security_manager.py` (`DESKTOP_ONLY_ACTIONS`), `core/progress.py` («Mirando la
  imagen»), `README.md`, `tests/test_workspace_tools_seguridad.py` (nivel).
- Tests: `tests/test_image_look.py` (5, nuevo), `tests/test_imagenes.py` (+3).

## Qué puede hacer ahora
- «Mirá la última captura del Escritorio» → el agente lista/encuentra el archivo con las
  herramientas de archivos y lo mira con `image_look`; el paso queda como «Mirando la
  imagen: captura.png».
- «¿Qué dice el error de C:\…\error.png?» → transcribe el error.

## Qué no hace todavía
- Varias imágenes en una llamada (una por llamada; el modelo puede encadenarlas).
- Editar o recortar imágenes.

## Verificación
- Suite completa: ver `pruebas/suite-062.txt`.

## Prueba manual sugerida (Johan)
1. Guardar una captura en el Escritorio y pedir «mirá la captura X del Escritorio y
   decime qué dice»: aparece «1 paso · Mirando la imagen» y la descripción.
2. Pedir una imagen fuera de la carpeta personal (p. ej. en `C:\Windows`): el agente
   dice que solo mira imágenes de tu carpeta personal o de un espacio de trabajo.

## Log de transiciones
2026-09-21 | — → NUEVO → EN_DESARROLLO → LISTO_PARA_COMMIT | conversación principal | Implementado y probado en la misma sesión (pipeline acortado, autorización en bloque).
