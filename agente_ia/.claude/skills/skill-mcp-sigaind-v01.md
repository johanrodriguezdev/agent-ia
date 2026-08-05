# Skill — Módulo MCP de SIGAIND (Agro BI)
## Guía de uso para clientes y agentes de IA

**Versión:** 1.0 · **Fecha:** 2026-07-31 · **Módulo:** MCP (Model Context Protocol) / Agro BI

---

## 1. ¿Qué es el MCP de SIGAIND?

El **MCP (Model Context Protocol)** es el canal de integración de SIGAIND que permite a un **agente de IA externo** (Claude, GPT, copilotos propios, etc.) interactuar con tu información agroindustrial de forma **segura y controlada**, usando lenguaje natural.

Con el MCP, tu agente puede:

- **Consultar informes dinámicos** (los mismos que ves en la web) y traerte los datos.
- **Consultar, crear y aprobar órdenes de agronomía**.
- **Consultar, crear y editar maestros**: Lotes, Labores y Vehículos.
- **Consultar catálogos** relacionados (plantaciones, zonas, siembras, materiales, tipos de labor, unidades de medida, contratistas, etc.).

Todo lo que el agente hace queda **limitado por tus permisos**: solo ve y toca lo que tu usuario ya puede ver y tocar en SIGAIND. Nada más.

---

## 2. Cómo conectarse

### 2.1 Endpoint

| Ambiente | URL base |
|----------|----------|
| Producción | `https://<tu-dominio>/mcp/agro-bi` |
| Pruebas | `https://test.sigaind.com/mcp/agro-bi` |

**Endpoints disponibles:**

| Endpoint | Método | Uso |
|----------|--------|-----|
| `/mcp/agro-bi` | GET | Discovery: lista las tools disponibles y su esquema |
| `/mcp/agro-bi/invoke` | POST | Ejecutar una tool |
| `/mcp/agro-bi/health` | GET | Estado del servicio |

### 2.2 Autenticación (Bearer Token)

Toda llamada a `/invoke` requiere un **token MCP** en el header:

```
Authorization: Bearer <TU_TOKEN>
Content-Type: application/json
```

**El token se crea desde SIGAIND web** (menú *Maestros → Seguridad → Tokens MCP*). Al crearlo defines:

- **Usuario asociado** → de este usuario hereda los permisos (módulo + plantaciones).
- **Empresa** → el token queda atado a tu empresa (multi-tenant, ver §3).
- **Plan** → define qué nivel de tools puede usar (ver §3.4).
- **Informe asociado (opcional)** → si es para consultar informes dinámicos.

> ⚠️ **Importante:** el token **debe tener un usuario asociado** para usar las tools de maestros, órdenes y catálogos. Sin usuario, esas tools responden `TOKEN_WITHOUT_USER`.

### 2.3 Cuerpo de la llamada (invoke)

```json
{
  "tool": "agro_consultar_lotes",
  "params": {
    "filtros": { "limite": 20 }
  }
}
```

Respuesta exitosa:

```json
{
  "mcp_version": "1.0",
  "tool": "agro_consultar_lotes",
  "timestamp": "2026-07-31T20:00:00-05:00",
  "data": { "lotes": [ ... ], "total": 20, "filtros": { ... } }
}
```

---

## 3. Modelo de seguridad

El MCP aplica **varias capas de seguridad en orden**. Tu agente debe entenderlas para interpretar los errores.

### 3.1 Licencia de IA (`empresa.licAI`)

**Regla de oro:** si tu empresa **no tiene activa la licencia de IA**, **ninguna** tool responde, aunque el token sea válido.

- Error: `LICENSE_INACTIVE` (403) — *"La empresa no tiene activa la licencia de Inteligencia Artificial."*
- Se valida en **toda** ejecución de tool, antes de hacer nada.

### 3.2 Multi-tenant (aislamiento por empresa)

- La empresa (`empId`) se toma **siempre del token**, nunca de lo que pida el agente.
- **Nunca** verás datos de otra empresa. Es imposible cruzar tenants por el MCP.
- Los vehículos se aíslan por su empresa contratista asociada.

### 3.3 Permisos del usuario (heredados por el token)

El agente opera **con los permisos del usuario asociado al token**:

**a) Permisos de módulo** (qué pantallas puede usar), validados por acción:

| Acción | Permiso requerido |
|--------|-------------------|
| Consultar | `lectura` |
| Crear | `escritura` |
| Editar | `update` |
| Aprobar orden | permiso módulo **AprobarOrdenes (34)** |

Si el usuario no tiene el permiso → `FORBIDDEN` (403).

**b) Permisos de plantaciones** (qué fincas puede ver), para Lotes, Zonas y Plantaciones:

- El agente solo ve lotes/zonas/plantaciones **autorizadas al usuario**.
- Si intenta usar una plantación no autorizada → `PLANTATION_NOT_ALLOWED` (403).

> 💡 **Consejo al cliente:** crea un **usuario dedicado para el MCP** (o restringe sus plantaciones y permisos) en vez de usar un usuario administrador. Así limitas el alcance del agente exactamente a lo que quieres permitir.

### 3.4 Plan del token (nivel de tools)

Cada token tiene un **plan** que limita el *tier* de tools utilizables:

| Plan | Tier alcanzado | Tools habilitadas |
|------|----------------|-------------------|
| `starter` | TIER1 | Solo **consultas** |
| `professional` | TIER1 + TIER2 | Consultar + **crear + editar + aprobar** |
| `enterprise` | Todos | Todas las actuales y futuras |

Si el plan no alcanza el tier de la tool → `TOOL_NOT_ALLOWED` (403).

### 3.5 Otras protecciones

- **Rate limiting** por plan (requests/hora y burst/minuto) → `RATE_LIMIT_EXCEEDED` (429).
- **Payload máximo 1 MB** por llamada → `INVALID_PARAMS` (400).
- **Borrado lógico:** nunca se elimina físicamente; los registros se inactivan.
- **Sin caché** en tools de datos sensibles por plantación (evita fuga de datos entre usuarios).

---

## 4. Catálogo de tools (31)

### 4.1 Informes dinámicos (5) — requieren `widget_id` del informe

| Tool | Tier | Qué hace | Parámetros clave |
|------|------|----------|------------------|
| `agro_get_resumen_informe` | Starter | Estructura del informe (elementos, series) | `widget_id` |
| `agro_get_kpis` | Starter | KPIs del informe con contexto de negocio | `widget_id`, `periodo` |
| `agro_query_elemento` | Starter | **Datos reales** de un elemento del informe | `widget_id`, `elemento_id`, `periodo`, `limite`, `filters` |
| `agro_comparar_periodos` | Starter | Compara un elemento entre dos periodos | `widget_id`, `elemento_id`, `base_periodo`, `comp_periodo` |
| `agro_detectar_anomalias` | Starter | Detecta anomalías en las series | `widget_id`, `elemento_id` |

> 📌 El `widget_id` es el **ID del informe dinámico** (visible en la URL del editor de informes). El informe debe tener **MCP activado** (se configura en el editor de informes, panel MCP) y el usuario debe tener permiso sobre él.

### 4.2 Órdenes de agronomía (3)

| Tool | Tier | Qué hace | Parámetros clave |
|------|------|----------|------------------|
| `agro_consultar_ordenes` | Starter | Lista órdenes con filtros (estado, labor, lote, fechas) | `filtros.estado` = `todas`/`abiertas`/`cerradas`/`pendientes_aprobar` |
| `agro_crear_orden` | Professional | Crea una orden | `laborId`, `loteId`, `fechaInicio`, `fechaFin`, `supervisorId`, `cantidadProgramada` |
| `agro_aprobar_orden` | Professional | Aprueba una orden pendiente | `orden_id` |

**Reglas:** consultar exige módulo *Ordenes Agronomia (23)*; crear exige `escritura` en 23; aprobar exige módulo *AprobarOrdenes (34)*.

### 4.3 Maestros (9) — consultar / crear / editar

| Maestro | Consultar (TIER1) | Crear (TIER2) | Editar (TIER2) |
|---------|-------------------|---------------|----------------|
| **Lotes** (mod 10) | `agro_consultar_lotes` | `agro_crear_lote` | `agro_editar_lote` |
| **Labores** (mod 15) | `agro_consultar_labores` | `agro_crear_labor` | `agro_editar_labor` |
| **Vehículos** (mod 117) | `agro_consultar_vehiculos` | `agro_crear_vehiculo` | `agro_editar_vehiculo` |

**Obligatorios al crear:**
- Lote: `zonaId`, `codigo`, `nombre` (zona debe estar autorizada).
- Labor: `codigo`, `nombre` (código ≤10, nombre ≤200).
- Vehículo: `placa`, `ecoId` (la contratista define el tenant; **obligatoria**).

### 4.4 Catálogos relacionados (14) — solo consulta (TIER1)

Para resolver los IDs de las llaves foráneas antes de crear/editar:

`agro_consultar_plantaciones` · `agro_consultar_zonas` · `agro_consultar_siembras` · `agro_consultar_materiales` · `agro_consultar_cecos` · `agro_consultar_umas` · `agro_consultar_manejos_agronomicos` · `agro_consultar_variedades` · `agro_consultar_categorias_labor` · `agro_consultar_unidades_medida` · `agro_consultar_tipos_control_labor` · `agro_consultar_tipos_labor` · `agro_consultar_empresas_contratistas` · `agro_consultar_tipos_vehiculo`

Todas aceptan `filtros.q` (búsqueda) y `filtros.limite`.

---

## 5. Reglas de negocio que el agente debe respetar

1. **Duplicados:** no se permite código de lote/labor ni placa de vehículo repetidos en la empresa → `DUPLICATE_RECORD` (409). Antes de crear, consulta si ya existe.
2. **Aprobación de órdenes:** solo se aprueban órdenes **pendientes** (`oreaprobada=0`). Aprobar una ya aprobada → `ORDER_ALREADY_APPROVED` (400).
3. **Orden duplicada:** no se crea una orden abierta para el mismo lote+labor → `DUPLICATE_ORDER` (409).
4. **Llaves foráneas:** al crear/editar, cada ID de catálogo se valida (existe, es de tu empresa, está activo). IDs inválidos → `INVALID_PARAMS`.
5. **Plantaciones:** en Lotes/Zonas/Plantaciones solo se opera sobre las autorizadas al usuario.
6. **Estados:** para inactivar un registro se edita su `estado` (borrado lógico), nunca se elimina.
7. **Flujo recomendado para crear:** `consultar catálogo → usar ID válido → crear`. Ej.: `agro_consultar_zonas` → `agro_crear_lote(zonaId)`.

---

## 6. Códigos de error (referencia)

Toda respuesta de error tiene esta forma:

```json
{ "mcp_version": "1.0", "tool": "<nombre>", "timestamp": "...",
  "error": { "code": "<CODIGO>", "message": "<texto en español>" } }
```

| Código | HTTP | Significado | Qué revisar |
|--------|:---:|-------------|-------------|
| `LICENSE_INACTIVE` | 403 | Empresa sin licencia IA | Activar licAI en la empresa |
| `UNAUTHORIZED` | 401 | Token inválido/expirado | Regenerar token |
| `TOKEN_WITHOUT_USER` | 403 | Token sin usuario asociado | Asignar usuario al token |
| `USER_INACTIVE` | 403 | Usuario del token inactivo | Reactivar el usuario |
| `FORBIDDEN` | 403 | Usuario sin permiso de módulo | Asignar permiso (lectura/escritura/update) |
| `TOOL_NOT_ALLOWED` | 403 | Plan insuficiente para la tool | Subir plan (professional/enterprise) |
| `PLANTATION_NOT_ALLOWED` | 403 | Plantación no autorizada | Autorizar plantación al usuario |
| `WIDGET_NOT_FOUND` | 404 | Informe no existe/no es de tu empresa | Verificar widget_id |
| `WIDGET_MCP_DISABLED` | 403 | Informe sin MCP activado | Activar MCP en el informe |
| `DUPLICATE_RECORD` | 409 | Código/placa duplicado | Consultar antes de crear |
| `DUPLICATE_ORDER` | 409 | Orden abierta duplicada (lote+labor) | Cerrar la orden previa |
| `ORDER_ALREADY_APPROVED` | 400 | Orden ya aprobada | Consultar estado primero |
| `SUPERVISOR_NOT_FOUND` | 400 | Supervisor de otra empresa | Usar supervisor del tenant |
| `INVALID_PARAMS` | 400 | Parámetros faltantes/inválidos | Revisar schema de la tool |
| `TOOL_NOT_FOUND` | 404 | Tool inexistente | Verificar nombre en /mcp/agro-bi |
| `RATE_LIMIT_EXCEEDED` | 429 | Límite de requests excedido | Esperar / subir plan |
| `TIMEOUT` | 504 | Tool tardó demasiado | Reintentar / reducir límite |
| `INTERNAL_ERROR` | 500 | Error interno | Reportar a soporte SIGAIND |

---

## 7. Ejemplos de uso (casos prácticos)

### 7.1 "Muéstrame los lotes de la plantación X"

```json
{ "tool": "agro_consultar_lotes",
  "params": { "filtros": { "plantacionId": 7, "limite": 50 } } }
```

### 7.2 "¿Cuántas órdenes hay pendientes por aprobar y de qué labores?"

```json
{ "tool": "agro_consultar_ordenes",
  "params": { "filtros": { "estado": "pendientes_aprobar", "limite": 200 } } }
```

→ agrupar la respuesta por `labor` y `supervisor` para responder.

### 7.3 "Aprueba la orden 1380037"

```json
{ "tool": "agro_aprobar_orden", "params": { "orden_id": 1380037 } }
```

### 7.4 "Crea un lote en la zona AGROVALLE"

```
Paso 1: agro_consultar_zonas  →  obtengo zonId=15 (AGROVALLE)
Paso 2: agro_crear_lote { zonaId: 15, codigo: "H01B", nombre: "LOTE H01B",
                          hectareas: 35.5, numeroPalmas: 2567, palmasIniciales: 2567 }
```

### 7.5 "Trae los datos de producción del informe"

```
Paso 1: agro_get_resumen_informe { widget_id: 520 }  →  veo los elementos
Paso 2: agro_query_elemento { widget_id: 520, elemento_id: 2405,
                              periodo: "2025", limite: 10 }  →  datos reales
```

---

## 8. Buenas prácticas para el agente IA del cliente

1. **Describe antes de actuar:** llama `GET /mcp/agro-bi` para conocer las tools y sus schemas.
2. **Consulta antes de crear:** verifica duplicados y obtén IDs válidos de catálogos.
3. **Interpreta los errores por código**, no por el texto (el código es estable, el mensaje puede variar).
4. **Respeta los límites:** usa `limite` razonable (≤200) y no reintentes en bucle ante 429.
5. **No inventes IDs:** si un catálogo no devuelve el ID que necesitas, dilo al usuario en vez de adivinar.
6. **Confirma acciones destructivas o de aprobación** con el usuario antes de ejecutarlas.
7. **Reporta claro:** al consultar, resume (totales, agrupaciones); al escribir, confirma el ID creado/modificado.

---

## 9. System prompt sugerido para el agente del cliente

> *Texto listo para copiar como instrucción/skill del agente.*

```
Eres un asistente con acceso al MCP de SIGAIND (Agro BI), un SaaS agroindustrial multi-tenant.
Conectas por POST a {BASE_URL}/mcp/agro-bi/invoke con header "Authorization: Bearer {TOKEN}"
y body JSON {"tool": "<nombre>", "params": {...}}. Descubre las tools en GET {BASE_URL}/mcp/agro-bi.

REGLAS ESTRICTAS:
- La empresa y los permisos vienen del token. NUNCA pidas ni uses datos de otra empresa.
- Solo puedes ver/tocar lo que el usuario del token puede (módulos y plantaciones autorizadas).
- Si una respuesta es {"error": {"code": X}}, interpreta X: LICENSE_INACTIVE (sin licencia),
  TOKEN_WITHOUT_USER (token sin usuario), USER_INACTIVE (usuario inactivo), FORBIDDEN (sin
  permiso de módulo), TOOL_NOT_ALLOWED (subir plan), PLANTATION_NOT_ALLOWED (plantación no
  autorizada), DUPLICATE_RECORD/ORDER (duplicado), INVALID_PARAMS (parámetros mal).
- Para crear/editar maestros u órdenes necesitas plan professional/enterprise (TIER2).
- Antes de crear, consulta el catálogo para obtener IDs válidos y evita duplicados.
- Antes de aprobar una orden, confirma que esté pendiente y pide confirmación al usuario.
- Usa "limite" <= 200 en las consultas.
- No inventes datos: si falta un ID o un valor, pregunta al usuario.

FLUJOS TIPO:
- Informes: get_resumen_informe -> query_elemento (datos reales) -> comparar_periodos/detectar_anomalias.
- Maestros: consultar catálogo -> consultar maestro -> crear/editar -> consultar de nuevo para confirmar.
- Órdenes: consultar_ordenes (estado) -> crear_orden / aprobar_orden -> consultar_ordenes para confirmar.

Responde siempre en español, con totales y agrupaciones claras al consultar, y confirmando
los IDs al escribir.
```

---

## 10. Checklist de habilitación para el cliente

- [ ] Empresa con **licencia IA activa** (`empresa.licAI = 1`).
- [ ] **Usuario dedicado** para el MCP (recomendado) con permisos de módulo y plantaciones deseados.
- [ ] **Token MCP** creado (Maestros → Seguridad → Tokens MCP) con ese usuario y plan adecuado.
- [ ] Si vas a consultar **informes**: informe con **MCP activado** + permiso del usuario sobre el informe.
- [ ] Si vas a **crear/editar/aprobar**: plan `professional` o `enterprise` en el token.
- [ ] Servidor web pasa el header `Authorization` a PHP (Apache: `CGIPassAuth on` en el `<Directory>`).

---

**Soporte:** ante dudas o el error `INTERNAL_ERROR`, contacta al equipo SIGAIND con el `code` de error, la tool usada y el timestamp de la respuesta.
