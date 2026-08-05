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

## Verificación en QA
- [ ] Toda acción destructiva tiene su nivel clasificado
- [ ] Las acciones Amarillo piden confirmación antes de ejecutar
- [ ] Las acciones Rojo están bloqueadas o requieren permiso explícito
- [ ] Los logs registran las acciones sensibles
- [ ] No hay `os.system()` o `subprocess` sin validación de input
