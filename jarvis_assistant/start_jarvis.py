"""
start_jarvis.py
Lanzador ligero para iniciar a JARVIS directamente en modo manos libres.
Ideal para arranques automáticos.
"""
from main import main

if __name__ == "__main__":
    # Inicia Jarvis forzando el modo 3 (Manos Libres / Wake Word)
    main(boot_mode='3')
