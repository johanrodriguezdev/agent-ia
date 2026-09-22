#!/usr/bin/env bash
# Deja el estado del agente fuera de la imagen, sin tocar una línea del código (REQ-067).
#
# O.R.I.O.N. guarda su configuración y su memoria al lado del código
# (`config_manager.py:16` → `os.path.dirname(__file__)/config.json`), que es lo correcto
# para una aplicación de escritorio y lo peor posible para un contenedor: al reconstruir la
# imagen se irían las conversaciones, las tareas y las claves.
#
# En vez de cambiar el código para que lea una variable —un cambio que solo existiría por
# Docker y que habría que mantener para siempre—, acá se enlaza cada archivo de estado a
# /datos, que es un volumen del equipo. El código sigue viendo `/app/config.json`; ese
# archivo es un enlace a `/datos/config.json`, que sobrevive a todo.
set -euo pipefail

DATOS="${ORION_DATA_DIR:-/datos}"
APP=/app

# Archivos de estado: lo que es de esta máquina y de este usuario, no del proyecto.
#
# `IDENTITY.md` y `SOUL.md` NO están acá a propósito: están versionados, son del proyecto
# y definen el carácter del agente. Enlazarlos a /datos los dejaría vacíos y el agente del
# contenedor no sería el mismo. `USER.md` y `MEMORY.md` sí, que son tuyos.
ARCHIVOS=(
  config.json
  .env
  authorized_users.json
  security_overrides.json
  mcp_allowlist.json
  USER.md
  MEMORY.md
  memory.db
  semantic_memory.db
  agent_context.db
  audit.db
  flows.db
  standing_intents.db
  tasks.db
  code_index.db
  ai/unified_memory.db
  intent/saved_model.pkl
)

# Carpetas de estado.
CARPETAS=(logs users_data)

enlazar() {
  local relativo="$1"
  local destino="${DATOS}/${relativo}"
  local origen="${APP}/${relativo}"

  mkdir -p "$(dirname "${destino}")" "$(dirname "${origen}")"

  # La primera vez: si la imagen trae una plantilla (`config.example.json`), se copia; si
  # no, se deja que la aplicación lo cree ella misma. Nunca se inventa contenido.
  if [[ ! -e "${destino}" ]]; then
    local plantilla="${origen%.*}.example.${origen##*.}"
    if [[ -f "${plantilla}" ]]; then
      cp "${plantilla}" "${destino}"
      echo "  · ${relativo} creado desde $(basename "${plantilla}")"
    elif [[ -f "${origen}" ]]; then
      cp "${origen}" "${destino}"
    fi
  fi

  # El enlace se rehace siempre: la imagen nueva trae su propio archivo en esa ruta.
  if [[ -e "${destino}" ]]; then
    ln -sfn "${destino}" "${origen}"
  fi
}

echo "O.R.I.O.N. — preparando el estado en ${DATOS}"
for archivo in "${ARCHIVOS[@]}"; do
  enlazar "${archivo}"
done

for carpeta in "${CARPETAS[@]}"; do
  mkdir -p "${DATOS}/${carpeta}"
  rm -rf "${APP:?}/${carpeta}"
  ln -sfn "${DATOS}/${carpeta}" "${APP}/${carpeta}"
done

# Sin claves no hay con qué responder, y el síntoma sería un error del modelo en mitad de
# la conversación. Mejor decirlo acá.
if [[ ! -s "${DATOS}/config.json" && ! -s "${DATOS}/.env" ]]; then
  echo "  · Aviso: todavía no hay claves de API. La aplicación abre sola" >&2
  echo "    Configuración → Conexiones para que las pegues." >&2
fi

# Aviso honesto sobre lo que este contenedor NO puede hacer, para que no se busque el
# error en otro lado (ver docker/README.md).
if [[ -z "${DISPLAY:-}" ]]; then
  echo "  · Aviso: no hay DISPLAY. La ventana no va a abrir; usá 'orion.sh --consola'." >&2
fi

exec "$@"
