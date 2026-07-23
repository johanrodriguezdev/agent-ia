"""
start_bots.py
Lanzador de todos los canales de Glass en paralelo.

Corre Telegram + Discord (y en el futuro más canales) simultáneamente
en hilos separados, sin bloquear el núcleo principal.

Uso:
  python start_bots.py              → inicia todos los bots configurados
  python start_bots.py --telegram   → solo Telegram
  python start_bots.py --discord    → solo Discord
  python start_bots.py --all        → todos (igual que sin argumentos)
"""

import sys
import asyncio
import threading
import time
import json
import os
from pathlib import Path


def _has_token(key_env: str, key_config: str) -> bool:
    if os.environ.get(key_env):
        return True
    from config_manager import load_config
    try:
        cfg = load_config()
        return bool(cfg.get(key_config, ""))
    except Exception:
        return False


def run_telegram():
    """Corre el bot de Telegram con su propio event loop async."""
    try:
        from channels.telegram_bot import run_telegram_bot
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        run_telegram_bot()
    except Exception as e:
        print(f"[Telegram] Error fatal: {e}")


def run_discord():
    """Corre el bot de Discord con su propio event loop async."""
    try:
        from channels.discord_bot import run_discord_bot
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        run_discord_bot()
    except Exception as e:
        print(f"[Discord] Error fatal: {e}")


def main():
    args = sys.argv[1:]
    run_all      = not args or "--all" in args
    run_telegram_flag = run_all or "--telegram" in args
    run_discord_flag  = run_all or "--discord"  in args

    try:
        from config_manager import get_agent_name
        agent = get_agent_name().upper()
    except Exception:
        agent = "O.R.I.O.N."

    print(f"\n{'='*50}")
    print(f"  {agent} - Iniciando canales de comunicación")
    print(f"  Sistema de tareas y recordatorios: activo")
    print(f"{'='*50}\n")

    threads = []

    # ── Telegram ───────────────────────────────────────────────────
    if run_telegram_flag:
        if _has_token("TELEGRAM_BOT_TOKEN", "telegram_token"):
            t = threading.Thread(target=run_telegram, daemon=True, name="TelegramBot")
            t.start()
            threads.append(("Telegram", t))
            print("  [+] Telegram Bot - iniciando...")
        else:
            print("  [-] Telegram Bot - sin token (agrega TELEGRAM_BOT_TOKEN)")

    # ── Discord ────────────────────────────────────────────────────
    if run_discord_flag:
        if _has_token("DISCORD_BOT_TOKEN", "discord_token"):
            t = threading.Thread(target=run_discord, daemon=True, name="DiscordBot")
            t.start()
            threads.append(("Discord", t))
            print("  [+] Discord Bot - iniciando...")
        else:
            print("  [-] Discord Bot - sin token (agrega DISCORD_BOT_TOKEN)")

    if not threads:
        print("\n  Sin canales configurados.")
        print("  Configura al menos un token en config.json o variables de entorno.\n")
        print("  Ejemplo config.json:")
        print(f'  {{ "agent_name": "{agent.lower()}", "telegram_token": "TU_TOKEN" }}\n')
        return

    print(f"\n  {len(threads)} canal(es) activo(s). Presiona Ctrl+C para detener.\n")

    # Mantener el proceso vivo mientras los hilos corren
    try:
        while True:
            time.sleep(5)
            # Verificar que los hilos siguen vivos
            for name, thread in threads:
                if not thread.is_alive():
                    print(f"  [Aviso] El canal {name} se detuvo inesperadamente.")
    except KeyboardInterrupt:
        print(f"\n\n  {agent} apagando canales... ¡Hasta pronto!\n")


if __name__ == "__main__":
    main()
