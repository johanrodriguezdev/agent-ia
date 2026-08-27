# MEMORY.md — Memoria persistente de O.R.I.O.N.

> Contexto activo que O.R.I.O.N. debe recordar entre sesiones.
> Para el perfil completo del usuario, ver `USER.md`.
> Para la identidad del asistente, ver `IDENTITY.md` y `SOUL.md`.
>
> La parte de abajo, entre los marcadores `MEMORIA-GENERADA`, la escribe el propio agente
> al pedirle "actualiza tu memoria". Todo lo que esté por encima se conserva tal cual: es
> el sitio para lo que quieras fijar a mano.

## Contexto activo del proyecto

- **Proyecto principal**: O.R.I.O.N. — asistente personal local en Python
- **Objetivo actual**: sistema operativo personal completo (identidad → memoria →
  herramientas → canales → voz → automatizaciones)
- **En curso**: REQ-021 (conversación multi-turno + ventana de micrófono, pendiente de
  prueba manual). REQ-016 a REQ-020 en QA.
- **Rama de trabajo**: `feature/REQ-021-conversacion-multiturno`

## Estado del sistema

- Proveedor principal: DeepSeek (`deepseek-chat`), clave en `.env`
- Backend: Python 3.12 + SQLite (memoria unificada, contexto, auditoría, tareas)
- Interfaz: aplicación de escritorio PyQt6 + WebView, y consola con `--headless`
- Canales: escritorio, voz, Telegram y Discord — los remotos exigen identidad autorizada
  en `authorized_users.json`
- Memoria: 351 registros consolidados en `ai/unified_memory.db`, todos bajo un único
  usuario canónico. 89 con embedding para búsqueda semántica
- Voz: palabra de activación, TTS con edge-tts, y ventana de conversación de ~15 s
- Skills: 12 módulos cargados automáticamente

<!-- MEMORIA-GENERADA:INICIO -->
<!-- Generado automáticamente el 27/08/2026 12:42. Todo lo que esté FUERA de estos dos marcadores se conserva tal cual. -->

## Sobre el usuario
- El usuario se llama Johan y prefiere ser tratado como "Señor".
- Su color favorito es el azul verdoso oscuro.
- Tiene perros.
- Prefiere respuestas en español.
- Escucha rock clásico, sobre todo Bon Jovi y Aerosmith.
- Está interesado en dropshipping.
- Está interesado en entrenar y enseñar modelos de IA.
- Muestra interés en la inteligencia artificial y la computación en la nube.

## Preferencias de trabajo
- Usa un computador con sistema operativo Windows 11, con nombre de usuario "johan".
- Tiene una carpeta de documentos en C:\Users\johan\OneDrive\Documentos.
- Tiene una carpeta llamada "Apps" dentro de sus documentos.
- Usa YouTube para reproducir música.
- Interactúa con el asistente a través de Telegram.

## Proyectos y contexto técnico
- Tiene un proyecto de agente de IA llamado "agente_ia" ubicado en C:\Users\johan\Documentos\Apps\Agent IA\agente_ia.
- Trabaja o colabora con Unipalma y maneja copias de seguridad de esa empresa.
- Usa un asistente de IA llamado "O.R.I.O.N" para gestionar tareas y archivos.
- Usa un sistema operativo con funciones que puede controlar remotamente (encender, apagar, etc.).

## Decisiones tomadas
- Decide usar el asistente personal "O.R.I.O.N" como su asistente principal.

## Correcciones que me hizo
- (Sin contenido)

<!-- MEMORIA-GENERADA:FIN -->
