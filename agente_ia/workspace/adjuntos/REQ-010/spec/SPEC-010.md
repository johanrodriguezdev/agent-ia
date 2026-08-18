# SPEC-010 — Branding visual Noddoo (íconos + colores GUI)

**Estado:** ⏸️ ESPERANDO VALIDACIÓN
**Categoría:** UI
**Tipo:** MEJORA
**Fecha:** 2026-08-05

## Objetivo
Reemplazar el ícono genérico de Python/Qt por el logo de Noddoo (una "N" azul con degradé) en los
tres lugares donde hoy se ve el ícono equivocado o dibujado en código: ícono de ventana, barra de
tareas de Windows y bandeja del sistema. Aplicar además el tono de azul del degradé del logo, de
forma consistente, sobre los acentos visuales de color que ya existen en la GUI JARVIS de
REQ-008/REQ-009 — sin rediseñar layout, tamaños ni estructura de ningún widget.

## Alcance

**Incluye:**
- Ícono de ventana: `setWindowIcon()` en la ventana principal (`ui/gui.py`), hoy inexistente.
- Ícono de bandeja del sistema: reemplazo del `QPixmap(16,16)` azul sólido dibujado en código
  (`ui/gui.py::_setup_tray_icon()`, línea ~193-197) por el logo real cargado desde archivo.
  Ícono **estático** — no reacciona a los estados IDLE/LISTENING/PROCESSING/RESPONDING (confirmado
  por Johan; reactividad queda fuera de este REQ, evaluable como REQ futuro).
- Ícono de la barra de tareas de Windows: mecanismo técnico concreto (posible `ctypes`
  AppUserModelID dado que no hay empaquetado PyInstaller) queda a definición de
  `orion-architect`, pero el resultado visual observable es obligatorio en este REQ.
- Generación de un archivo `.ico` multi-resolución (16/32/48/256 px) a partir de
  `assets/branding/noddoo-icon-mark.png`, usando Pillow, como parte del trabajo de `orion-dev`
  (confirmado por Johan — no se usa el PNG único directo en `QIcon`).
- Recoloreo de los acentos de marca ya existentes en la GUI (ver CA-06) a un tono extraído del
  degradé real de `noddoo-icon-mark.png`, centralizado en una constante de color compartida (el
  mecanismo concreto —módulo `ui/theme.py`, diccionario, etc.— queda a definición de
  `orion-architect`).
- Recoloreo del fondo del estado "escuchando" (`LISTENING_WAKE`) del indicador de wake word de
  REQ-009 (`header_bar.py`), manteniendo el emoji (`🎙`) sin cambios — confirmado por Johan,
  opción (b) de las alternativas planteadas.

**No incluye:**
- Rediseño de layout, tamaños, posiciones o estructura de cualquier widget existente de REQ-008 o
  REQ-009 — el diff se limita a íconos (archivos de imagen) y valores de color.
- Recoloreo de los verdes semánticos `#00e08a` (estado "despierto" del wake word) y `#33d17a`
  (indicador "Sistema activo" del sidebar) — son colores de estado/éxito, no de marca; confirmado
  por Johan que quedan fuera de alcance.
- Recoloreo de grises de texto secundario (`#8a93a6`, `#5a6478`, `#c3c9d6`, etc.).
- Reemplazo de los emojis del indicador de wake word (`🎙`, `🟢`) por íconos de imagen propios —
  quedan como están; solo cambia el color de fondo QSS (confirmado por Johan).
- Reactividad del ícono de la bandeja del sistema según estado del asistente — queda estático en
  este REQ (confirmado por Johan).
- Empaquetado del proyecto con PyInstaller/`.spec` — no existe hoy y no se introduce en este REQ
  salvo que `orion-architect` determine que es la única vía técnica viable para el ícono de
  taskbar (ver Asumidos).
- Generar, dibujar o inventar el logo — los 2 archivos de imagen (`noddoo-logo-full.png`,
  `noddoo-icon-mark.png`) los provee Johan; si no existen al momento de `orion-dev`, se reporta
  como bloqueado (ver CA-05).

## Módulos afectados
- `ui/gui.py` — agrega `setWindowIcon()` a la ventana principal; reemplaza el `QPixmap` dibujado
  en `_setup_tray_icon()` por carga de ícono desde archivo; posible mecanismo adicional para el
  ícono de taskbar de Windows (a definir por `orion-architect`).
- `ui/widgets/header_bar.py` — color de acento `#4fc3ff` (píldora "Modo activo", fondo del estado
  `LISTENING_WAKE` del indicador de wake word) migrado a la constante de color de marca.
- `ui/widgets/center_panel.py` — color de acento `#4fc3ff` (foco de la barra de comando, botón
  enviar ➤) migrado a la constante de color de marca.
- `ui/widgets/sidebar.py` — color de acento `#4fc3ff` (highlight de ítem de navegación habilitado,
  `rgba(79, 195, 255, 0.12)`) migrado a la constante de color de marca.
- `assets/branding/` (carpeta nueva) — contendrá `noddoo-logo-full.png` y `noddoo-icon-mark.png`
  (provistos por Johan, pendientes hoy) y el `.ico` multi-resolución generado por `orion-dev` a
  partir del segundo.
- Posible módulo/constante nueva de color centralizado (nombre y ubicación a definir por
  `orion-architect`) para no duplicar el hex de marca suelto en 3 archivos QSS distintos.

## Comportamiento actual vs deseado
| Actual | Deseado |
|--------|---------|
| No hay ningún `setWindowIcon()` — la ventana usa el ícono default de Qt/python.exe. | La ventana muestra el logo Noddoo como ícono, vía `setWindowIcon()`. |
| La barra de tareas de Windows muestra el ícono genérico de `python.exe` (no hay empaquetado). | La barra de tareas muestra el logo Noddoo. |
| `_setup_tray_icon()` dibuja un `QPixmap(16,16)` azul sólido en código — sin archivo de imagen. | El ícono de bandeja carga `noddoo-icon-mark.png`/`.ico` real desde `assets/branding/`, estático. |
| El acento de color en `header_bar.py`, `center_panel.py` y `sidebar.py` es un celeste genérico (`#4fc3ff`) sin relación con ninguna identidad de marca. | El mismo acento usa el tono extraído del degradé real del logo Noddoo, centralizado en una constante compartida. |
| El fondo del estado "escuchando" del wake word (REQ-009) usa el mismo `#4fc3ff` genérico. | Usa el mismo tono de marca que el resto de los acentos; el emoji no cambia. |

## Criterios de aceptación
- [ ] CA-01: Al lanzar `main.py` sin `--headless`, la ventana principal tiene un ícono asignado vía
      `setWindowIcon()` cargado desde `assets/branding/` (visible en la barra de título de la
      ventana), reemplazando la ausencia actual de ícono/ícono default de Qt.
- [ ] CA-02: El ícono mostrado en la barra de tareas de Windows para el proceso corresponde al
      logo Noddoo, no al ícono genérico de `python.exe` — verificación manual del humano (no
      automatizable con pytest); `orion-dev` debe documentar en el log de desarrollo el mecanismo
      técnico usado para lograrlo.
- [ ] CA-03: `_setup_tray_icon()` ya no dibuja un `QPixmap` sólido en código — carga
      `noddoo-icon-mark.png` o el `.ico` generado desde `assets/branding/`; el ícono es estático
      (no cambia con IDLE/LISTENING/PROCESSING/RESPONDING).
- [ ] CA-04: Existe un archivo `.ico` multi-resolución (16, 32, 48 y 256 px embebidos) en
      `assets/branding/`, generado a partir de `noddoo-icon-mark.png` con Pillow como parte del
      trabajo de `orion-dev` (documentado con el script o pasos usados, no generado a mano fuera
      del repo).
- [ ] CA-05: Antes de escribir cualquier código de este REQ, `orion-dev` verifica la existencia de
      `assets/branding/noddoo-logo-full.png` y `assets/branding/noddoo-icon-mark.png`; si alguno
      falta, reporta bloqueado y no continúa — en ningún caso genera, dibuja o inventa un logo
      placeholder.
- [ ] CA-06: Los usos actuales de `#4fc3ff` en `header_bar.py` (píldora "Modo activo" y fondo del
      estado `LISTENING_WAKE`), `center_panel.py` (foco de barra de comando, botón enviar) y
      `sidebar.py` (highlight de navegación habilitado) quedan migrados a una única constante de
      color compartida cuyo valor se extrae del degradé real de `noddoo-icon-mark.png` durante el
      desarrollo — sin hex duplicado suelto en cada archivo QSS.
- [ ] CA-07: `#00e08a` (estado "despierto" del wake word) y `#33d17a` (indicador "Sistema activo"
      del sidebar) permanecen sin modificar — verificable por diff, ningún cambio en esas líneas.
- [ ] CA-08: Los emojis del indicador de wake word (`🎙` para inactivo/escuchando, `🟢` para
      despierto) permanecen sin cambios — solo el color de fondo QSS del estado `LISTENING_WAKE`
      se actualiza (ver CA-06).
- [ ] CA-09: Ningún layout, tamaño, posición, margen o estructura de widgets de REQ-008/REQ-009 se
      modifica — el diff de este REQ toca únicamente: archivos de `assets/branding/`, llamadas de
      carga de ícono, y valores/constantes de color.
- [ ] CA-10: `python -m py_compile` pasa sin errores en todos los módulos modificados, y
      `pytest tests/` no introduce ningún fallo nuevo respecto al baseline que documente
      `orion-baseline`.

## Casos borde
- `assets/branding/noddoo-logo-full.png` y/o `noddoo-icon-mark.png` no existen todavía al llegar a
  `orion-dev` (estado real hoy) → bloqueo explícito, sin generar placeholder (ver CA-05). Esto no
  bloquea spec, baseline ni arquitectura.
- Caché de íconos de Windows: es un comportamiento conocido del SO — la barra de tareas puede
  seguir mostrando el ícono viejo hasta reiniciar Explorer o limpiar la caché de íconos, incluso
  con el código ya corregido. Se documenta como limitación conocida, **no bloqueante y sin
  criterio de aceptación automatizado** (decisión técnica confirmada, no requiere mitigación
  activa en este REQ).
- El PNG fuente tiene transparencia (canal alfa) → Pillow debe preservarlo al generar el `.ico`;
  no se debe introducir un fondo blanco/negro sólido no deseado.
- Multi-monitor / escalado DPI distinto de 100% → el ícono debe verse razonablemente nítido al
  menos en 100% y 150% de escala; no se exige una prueba automatizada de esto, es verificación
  visual manual.
- El menú contextual de la bandeja del sistema (clic derecho → "Salir", etc.) debe seguir
  funcionando exactamente igual — el único cambio es la imagen del ícono, no su comportamiento.

## Asumidos
- ASUMIDO: no se introduce empaquetado con PyInstaller en este REQ. Si el mecanismo de
  `ctypes`/AppUserModelID (u otro sin empaquetar) no logra forzar el ícono correcto en la barra de
  tareas de Windows corriendo `python main.py` directo, `orion-architect` debe documentar la
  limitación técnica explícitamente y proponer alternativa — a confirmar con Johan si este caso se
  presenta.
- ASUMIDO: el tono exacto de azul de marca no está definido en esta SPEC como valor hex fijo,
  porque el archivo de imagen todavía no existe en el repo — Johan no proveyó valores hex de
  antemano. `orion-dev` lo extrae de `noddoo-icon-mark.png` durante el desarrollo y lo fija como
  constante; la validación de consistencia visual queda para `orion-qa`/prueba manual, no como
  comparación de hex exacto en un test automatizado.
- ASUMIDO: el mecanismo concreto para centralizar la constante de color compartida (módulo nuevo,
  diccionario, etc.) queda a definición de `orion-architect` — esta SPEC solo exige que no quede
  el hex duplicado suelto en 3 archivos.
- ASUMIDO: `assets/branding/` con los 2 PNG será provisto por Johan antes de que `orion-dev`
  comience — dependencia pendiente hoy, documentada como bloqueante solo para desarrollo, no para
  spec/baseline/arquitectura.
