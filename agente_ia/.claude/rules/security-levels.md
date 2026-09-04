# Regla: Niveles de Seguridad (Verde/Amarillo/Rojo) — O.R.I.O.N.

## Principio
Toda acción que O.R.I.O.N. puede ejecutar se clasifica en uno de tres niveles.
El sistema debe pedir confirmación humana en Amarillo y Rojo.

## 🟢 Verde — puede actuar sin preguntar
- Leer información del sistema (CPU, RAM, disco, uptime)
- Buscar archivos (solo lectura)
- Buscar en Wikipedia o web
- Responder preguntas conversacionales (chat)
- Consultar clima
- Listar archivos y directorios
- Decir la hora/fecha
- Reproducir música/video en el navegador
- Tomar screenshots (guardar en disco local)
- Abrir aplicaciones conocidas (no destructivas)
- Recordar y recuperar información de la memoria

## 🟡 Amarillo — debe confirmar antes de ejecutar
- Apagar o reiniciar el PC
- Cerrar aplicaciones (especialmente con taskkill /F)
- Borrar archivos o carpetas
- Modificar archivos existentes
- Enviar mensajes por canales externos (Telegram, Discord)
- Ejecutar código generado por IA (code_execution_skill)
- Crear/modificar skills automáticamente (skill_creator_skill)
- Mover o renombrar archivos
- Ejecutar comandos del sistema con argumentos dinámicos
- Cambiar configuraciones del sistema (volumen, brillo, etc.)

## 🔴 Rojo — no ejecuta sin permiso explícito y verificado
- Formatear discos o particiones
- Borrar bases de datos (memory.db, semantic_memory.db, tasks.db)
- Modificar/borrar el propio código de O.R.I.O.N.
- Exponer API keys, tokens o credenciales
- Enviar correos electrónicos como si fuera el usuario
- Publicar en redes sociales
- Ejecutar comandos con privilegios elevados (sudo/admin)
- Instalar o desinstalar software del sistema
- Modificar variables de entorno del sistema
- Dar acceso a terceros a sistemas internos

## Implementación técnica
### Por confirmar
```python
# EJEMPLO — nivel Amarillo
def shutdown_pc():
    if not confirmar_con_usuario("¿Estás seguro de que quieres apagar el PC?"):
        return "Apagado cancelado."
    os.system("shutdown /s /t 5")
    return "Apagando el PC en 5 segundos..."
```

### Por canal
- **Desktop**: respeta la clasificación completa
- **Telegram/Discord**: Amarillo siempre requiere confirmación explícita, Rojo bloqueado
- **Voz**: solo acciones Verdes permitidas; Amarillo se responde "No puedo hacer eso por voz"

### Logging obligatorio
Toda acción Amarillo o Rojo debe quedar registrada en logs:
```python
logger.warning(f"Acción amarilla ejecutada: {accion} | usuario: {user} | confirmación: {confirmada}")
logger.critical(f"Acción roja ejecutada: {accion} | usuario: {user} | permiso_explicito: {permiso}")
```

## REQ-005 — deny-list Rojo aplicada en código
Desde REQ-005, las 10 categorías 🔴 Rojo de este documento (las 4 ya implementadas más las 6 sin
implementación real: `send_email_as_user`, `post_social_media`, `elevated_system_command`,
`install_uninstall_software`, `modify_system_env_vars`, `grant_third_party_access`) están
registradas como `RiskLevel.RED` en `core/security_manager.py` y bloqueadas por defecto por
`require_confirmation()`, incluso si ninguna función las implementa todavía. El sistema pasa a ser
**fail-closed**: cualquier acción no clasificada explícitamente se bloquea (antes se permitía por
defecto). El gate se ejecuta en el punto de entrada de cada camino de ejecución real
(`dispatch()`, `SkillManager.execute()`, `get_agent_tools()`, `agents/action_registry.execute_action()`,
`os_integration/capabilities_router.execute_capability()`), nunca dentro del cuerpo de la skill o
handler, y nunca lee `params` de la invocación para decidir el canal — solo el canal real pasado
explícitamente por el caller. Ver `workspace/adjuntos/REQ-005/` para el detalle completo (spec,
arquitectura, auditoría de seguridad).

## REQ-019 — override de configuración de usuario (solo subir, nunca bajar)
Desde REQ-019, el usuario puede subir (nunca bajar) el nivel de confirmación de una
categoría acotada de acciones (v1: apertura de aplicaciones y navegación) desde la
pantalla "Configuración" del webview de escritorio. El nivel efectivo de cualquier acción
es siempre `max(nivel_código, nivel_config)` — nunca `min` —, calculado en
`core/security_manager.py::SecurityManager._merge_with_override()` cada vez que se
registra una acción (`register_action()`), sin importar en qué de los 4 puntos de
registro del sistema ocurra (los 3 de `core/security_manager.py` +
`agents/tool_registry.py:73`). El override se persiste en `security_overrides.json`
(`core/security_config.py`), archivo separado de `config.json` para que una corrupción de
configuración general nunca borre ni afecte la configuración de seguridad, ni viceversa.
Un archivo de overrides ausente, corrupto, o con una clave/valor inválido se trata SIEMPRE
como "sin overrides" (nivel de código puro) — nunca como "sin restricciones". El cambio
requiere reiniciar la app para tomar efecto (no hay aplicación en caliente en v1). Las
acciones sin clasificar y las 10 acciones 🔴 Rojo de REQ-005 quedan completamente fuera de
este mecanismo — el catálogo `_SECURITY_ROWS_V1` de `ui/webview/bridge.py` nunca las
incluye, y además el propio `_merge_with_override()` bloquea cualquier intento de
downgrade de una acción RED aunque `security_overrides.json` se edite a mano. El catálogo
v1 tiene además un techo de `yellow` (`_V1_MAX_OFFERABLE_LEVEL`, `ui/webview/bridge.py`):
ninguna fila de v1 ofrece ni acepta subir a `red`, para evitar que el usuario autobloquee
una acción benigna sin `ORION_AUTH_PIN` configurado.

## Terminal embebida — el permiso se pide al abrir, no por comando

La terminal del panel de escritorio (`core/terminal_session.py`, PowerShell sobre ConPTY)
introduce una superficie que puede ejecutar cualquier cosa. Se acota así:

- **`terminal_open` es 🟡 amarillo.** Es la única acción con confirmación humana. Pedirla
  por comando no sería una terminal; pedirla una vez, al abrir la sesión, sí es una
  decisión real que el usuario toma con el modal delante. El gate está en
  `Bridge.terminal_open()`, que es el único camino que crea la sesión desde la pantalla —
  y por ser un `@pyqtSlot` alcanzable desde cualquier script de la página (mismo criterio
  que `delete_conversation`, REQ-015/§10.2), es justamente ahí donde tiene que estar.
- **Cada shell nueva se confirma aparte.** Hay pestañas: el botón "+" abre otra sesión y
  vuelve a pedir permiso, porque es otra capacidad de ejecución, no la misma.
- **`terminal_run_command` (herramienta del agente) es 🟡 amarillo**, y su confirmación
  muestra el comando exacto: `command` está en `_DETAILS_ALLOWED_KEYS` de
  `format_details()`. Autorizar sin ver qué se va a ejecutar sería autorizar a ciegas.
- **`terminal_read_output` (leer lo que se ve en la terminal) es 🟡 amarillo**, y no verde
  como el resto de las lecturas: en una terminal puede haber quedado impresa una clave o la
  salida de algo privado, y leerla significa mandarla al proveedor del modelo. Que el
  usuario lo autorice cada vez es el precio correcto.
- **Ningún canal remoto la alcanza.** Al ser amarillas, `CHANNEL_ALLOWED_LEVELS` las deja
  fuera de voz, Telegram, Discord y correo, y no existe ninguna entrada para ellas en
  `CHANNEL_ACTION_EXCEPTIONS`. Una shell libre disparable por un mensaje —o por un correo
  que puede mandar cualquiera— es exactamente lo que el modelo de canales existe para
  impedir. Está fijado por test en `tests/test_terminal_session.py`.
- **Todo lo que se ejecuta queda auditado**, venga del teclado del usuario o del agente,
  con `security_manager.log_action("terminal_command", ...)`. La auditoría no se conforma
  con lo tecleado: `_LineaVisual` reconstruye la línea que de verdad se está viendo en la
  consola, así que un comando traído con ↑ o completado con Tab —que el usuario nunca
  escribió— también queda registrado tal cual se ejecutó.
- **La sesión muere con la ventana.** Cerrar el panel o salir de la app termina el proceso
  (`MainWindow.aboutToQuit`): nunca queda una shell viva sin nada que la muestre.

## Verificación en QA
- [ ] Toda acción destructiva tiene su nivel clasificado
- [ ] Las acciones Amarillo piden confirmación antes de ejecutar
- [ ] Las acciones Rojo están bloqueadas o requieren permiso explícito
- [ ] Los logs registran las acciones sensibles
- [ ] No hay `os.system()` o `subprocess` sin validación de input
