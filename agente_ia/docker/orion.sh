#!/usr/bin/env bash
# O.R.I.O.N. en Linux — lanzador (REQ-067)
#
# Una aplicación de escritorio dentro de un contenedor necesita tres cosas que un
# `docker compose up` no hace solo: permiso para dibujar en tu pantalla, tu UID para que
# los archivos que cree sean tuyos, y saber si tu sesión es X11 o Wayland. Eso es esto.
#
# Uso:
#   ./orion.sh                 la aplicación con su ventana
#   ./orion.sh --consola       modo texto, sin ventana (sirve por SSH)
#   ./orion.sh --bots          solo los bots de Telegram y Discord
#   ./orion.sh --construir     reconstruye la imagen
#   ./orion.sh --terminal      una shell dentro del contenedor, para mirar
set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${AQUI}"

ORION_UID="$(id -u)"
ORION_GID="$(id -g)"
export ORION_UID ORION_GID
export HOME="${HOME:-/home/$(id -un)}"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

# ----------------------------------------------------------------- la pantalla
preparar_pantalla() {
  if [[ -z "${DISPLAY:-}" ]]; then
    echo "No hay DISPLAY: no estás en una sesión gráfica." >&2
    echo "Usá './orion.sh --consola' si entraste por SSH." >&2
    return 1
  fi

  # Wayland: pyautogui (clic, teclado, captura) NO funciona ahí, y conviene decirlo
  # antes y no cuando el agente intente mover el ratón y no pase nada.
  if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
    echo "Aviso: tu sesión es Wayland." >&2
    echo "  La ventana y el chat funcionan (XWayland), pero controlar el ratón, el" >&2
    echo "  teclado y tomar capturas no: pyautogui necesita X11. Si vas a usar esas" >&2
    echo "  funciones, entrá a la sesión 'Xorg' desde la pantalla de inicio." >&2
  fi

  # El contenedor corre con tu mismo UID, así que alcanza con darle permiso a ese
  # usuario local en vez de abrir X a todo el mundo (`xhost +`, que es lo que suele
  # recomendarse y deja la pantalla expuesta a cualquiera).
  if command -v xhost >/dev/null 2>&1; then
    xhost "+SI:localuser:$(id -un)" >/dev/null
  else
    echo "Aviso: no encontré 'xhost' (paquete x11-xserver-utils). Si la ventana no" >&2
    echo "  abre, instalalo o ejecutá: xhost +SI:localuser:\$(id -un)" >&2
  fi
}

liberar_pantalla() {
  if command -v xhost >/dev/null 2>&1; then
    xhost "-SI:localuser:$(id -un)" >/dev/null 2>&1 || true
  fi
}

mkdir -p "${AQUI}/datos"

case "${1:-}" in
  --construir)
    compose build
    ;;
  --consola)
    compose run --rm orion python main.py --headless
    ;;
  --bots)
    compose run --rm orion python start_bots.py --all
    ;;
  --terminal)
    compose run --rm orion bash
    ;;
  --ayuda|-h|--help)
    sed -n '2,15p' "${BASH_SOURCE[0]}"
    ;;
  *)
    preparar_pantalla || exit 1
    trap liberar_pantalla EXIT
    compose run --rm orion python main.py "$@"
    ;;
esac
