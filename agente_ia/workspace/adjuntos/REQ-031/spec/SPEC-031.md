# SPEC-031 — Salida HTTP segura: cerrar el SSRF y poder llamar APIs

**Categoría:** SEGURIDAD | **Tipo:** SEGURIDAD + FEATURE_NUEVA | **Fecha:** 2026-09-09

## Criterios de aceptación

### El guard (`core/http_seguro.py`)
- [x] **CA-01** — Solo `http://` y `https://`. `file://`, `ftp://`, `data:` y `javascript:`
  se rechazan. Importa porque `urlopen()` entiende `file://`: un esquema sin validar es un
  lector de archivos del disco.
- [x] **CA-02** — Se rechaza la propia máquina: `127.0.0.1`, `localhost` y `[::1]`.
- [x] **CA-03** — Se rechaza la red local: `10/8`, `172.16/12`, `192.168/16`, y también
  reservadas, multicast y `0.0.0.0`.
- [x] **CA-04** — Se rechaza `169.254.169.254` (metadatos de la nube, donde viven las
  credenciales de una instancia) **por política**, sin intentar conectarse.
- [x] **CA-05** — La decisión se toma sobre la **IP resuelta**, no sobre el texto: un
  dominio de aspecto normal que resuelva a `10.0.0.5` se rechaza igual.
- [x] **CA-06** — Si el nombre resuelve a varias IPs y **cualquiera** es interna, se rechaza.
- [x] **CA-07** — Un destino público se acepta: el guard no puede dejar al agente sin internet.
- [x] **CA-08** — Las redirecciones se siguen a mano revalidando **cada salto**: una URL
  pública que redirige a `127.0.0.1` se corta en el salto, no en la primera validación.
- [x] **CA-09** — Un bucle de redirecciones termina (máximo 5 saltos).
- [x] **CA-10** — La respuesta se corta por tamaño **mientras se descarga**, y se avisa.
- [x] **CA-11** — Solo GET, POST, PUT, PATCH, DELETE y HEAD.

### Aplicado a lo que ya existía
- [x] **CA-12** — `os_integration/web_search.py::leer_pagina()` usa el guard: `web_read`
  deja de poder leer servicios locales. Es la regresión del bug reportado.
- [x] **CA-13** — `skills/web_browsing_skill.py` usa el guard, con lo que además queda
  validado el esquema (antes `urlopen()` sin control).
- [x] **CA-14** — El `except Exception` de ese skill deja de mandar `str(e)` al canal y
  loguea el detalle: mismo patrón que arreglaron REQ-024 y REQ-025, y este camino es
  alcanzable desde Telegram.
- [x] **CA-15** — `web_read` **sigue siendo 🟢 verde**: leer una página pública no cambia de
  nivel. Lo que estaba mal no era el nivel, era no mirar a dónde apuntaba.

### La herramienta nueva
- [x] **CA-16** — `http_request` permite método, cabeceras y cuerpo; un objeto en el cuerpo
  se manda como JSON con su `Content-Type`.
- [x] **CA-17** — Es 🟡 YELLOW: manda datos afuera y tiene efectos del otro lado. Amarillo
  además la deja fuera de Telegram, Discord, voz, API y correo.
- [x] **CA-18** — Tiene su frase en castellano en `core/acciones_legibles.py`, y nombra lo
  que importa entender al confirmar: que algo sale del equipo.
- [x] **CA-19** — Las credenciales viajan como `${NOMBRE_DE_LA_VARIABLE}` y se resuelven con
  `core/mcp_client.py::expandir_secreto()`: el token no queda en el historial del modelo ni
  en el log de auditoría.
- [x] **CA-20** — Un destino bloqueado vuelve como frase para el modelo, no como excepción
  que corte el turno.

### Pruebas
- [x] **CA-21** — Ningún test toca la red: `127.0.0.1` y `localhost` resuelven local, y para
  los nombres públicos se sustituye `getaddrinfo`.
- [x] **CA-22** — Suite completa sin fallos nuevos.

## Fuera de alcance
- **DNS rebinding**: entre la validación y la conexión el DNS puede cambiar de respuesta.
  Cerrarlo exige conectarse a la IP ya validada forzando el `Host`, lo que rompe SNI en
  HTTPS. Queda documentado como límite conocido.
- Encender MCP: el código está entero (`core/mcp_client.py`, `mcp_manager.py`, `mcp_oauth.py`,
  ya enganchado en `main.py`), lo que falta es declarar servidores y permitir sus tools —
  decisión de Johan, no trabajo de código.
