"""
filesystem_actions.py
Operaciones reales de sistema de archivos usando pathlib, os y shutil.
Sin simulación de interfaz gráfica.
"""

import os
import shutil
from pathlib import Path
from datetime import datetime


# ─────────────────────────────────────────────────────────────────
#  BÚSQUEDA DE ARCHIVOS
# ─────────────────────────────────────────────────────────────────

def search_files(name: str, path: str = "~") -> str:
    """
    Busca archivos que contengan 'name' en su nombre dentro de 'path'.
    Retorna los primeros 15 resultados con su ruta completa.
    """
    search_root = Path(path).expanduser()
    if not search_root.exists():
        return f"La ruta '{path}' no existe."

    matches = []
    try:
        for entry in search_root.rglob(f"*{name}*"):
            if entry.is_file():
                matches.append(str(entry))
                if len(matches) >= 15:
                    break
    except PermissionError:
        pass

    if not matches:
        return f"No encontré archivos con '{name}' en '{search_root}'."

    lines = [f"🔍 Archivos que contienen '{name}' en '{search_root.name}':"]
    for path_str in matches:
        lines.append(f"  📄 {path_str}")
    if len(matches) == 15:
        lines.append("  ... (limitado a los primeros 15 resultados)")
    return "\n".join(lines)


def search_folders(name: str, path: str = "~") -> str:
    """Busca carpetas cuyo nombre contenga 'name'."""
    search_root = Path(path).expanduser()
    if not search_root.exists():
        return f"La ruta '{path}' no existe."

    matches = []
    try:
        for entry in search_root.rglob(f"*{name}*"):
            if entry.is_dir():
                matches.append(str(entry))
                if len(matches) >= 10:
                    break
    except PermissionError:
        pass

    if not matches:
        return f"No encontré carpetas con '{name}' en '{search_root.name}'."

    lines = [f"🗂 Carpetas que contienen '{name}':"]
    for p in matches:
        lines.append(f"  📁 {p}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
#  ANÁLISIS DE TAMAÑO
# ─────────────────────────────────────────────────────────────────

def get_folder_size(path: str = "~") -> str:
    """
    Calcula el tamaño total de una carpeta en MB.
    Maneja errores de permisos silenciosamente.
    """
    folder = Path(path).expanduser()
    if not folder.exists():
        return f"La carpeta '{path}' no existe."

    total_bytes = 0
    try:
        for entry in folder.rglob("*"):
            if entry.is_file():
                try:
                    total_bytes += entry.stat().st_size
                except (PermissionError, OSError):
                    pass
    except PermissionError:
        return f"Sin permisos suficientes para leer '{folder}'."

    mb = total_bytes / (1024 * 1024)
    gb = mb / 1024
    if gb >= 1:
        return f"'{folder.name}' ocupa {gb:.2f} GB ({mb:.0f} MB) en disco."
    return f"'{folder.name}' ocupa {mb:.2f} MB en disco."


def find_largest_folders(path: str = "~", top_n: int = 5) -> str:
    """
    Encuentra las N subcarpetas más grandes dentro de 'path'.
    Ideal para limpiar disco.
    """
    root = Path(path).expanduser()
    if not root.exists():
        return f"La ruta '{path}' no existe."

    sizes = []
    try:
        for entry in root.iterdir():
            if entry.is_dir():
                total = 0
                try:
                    for f in entry.rglob("*"):
                        if f.is_file():
                            try:
                                total += f.stat().st_size
                            except (PermissionError, OSError):
                                pass
                except (PermissionError, OSError):
                    pass
                sizes.append((entry, total))
    except PermissionError:
        return f"Sin permisos para analizar '{root}'."

    # Ordenar de mayor a menor
    sizes.sort(key=lambda x: x[1], reverse=True)

    if not sizes:
        return f"No hay subcarpetas en '{root.name}'."

    lines = [f"📊 Las {top_n} carpetas más grandes en '{root.name}':"]
    for entry, size_bytes in sizes[:top_n]:
        mb = size_bytes / (1024 * 1024)
        gb = mb / 1024
        size_str = f"{gb:.2f} GB" if gb >= 1 else f"{mb:.1f} MB"
        lines.append(f"  📁 {entry.name:<30} {size_str}")

    return "\n".join(lines)


def find_largest_files(path: str = "~", top_n: int = 10) -> str:
    """Encuentra los N archivos más pesados dentro de 'path'."""
    root = Path(path).expanduser()
    if not root.exists():
        return f"La ruta '{path}' no existe."

    files_with_size = []
    try:
        for f in root.rglob("*"):
            if f.is_file():
                try:
                    files_with_size.append((f, f.stat().st_size))
                except (PermissionError, OSError):
                    pass
    except PermissionError:
        return f"Sin permisos para analizar '{root}'."

    files_with_size.sort(key=lambda x: x[1], reverse=True)

    if not files_with_size:
        return f"No hay archivos en '{root.name}'."

    lines = [f"📊 Los {top_n} archivos más grandes en '{root.name}':"]
    for f, size_bytes in files_with_size[:top_n]:
        mb = size_bytes / (1024 * 1024)
        size_str = f"{mb:.2f} MB"
        lines.append(f"  📄 {f.name:<40} {size_str}")

    return "\n".join(lines)


def list_recent_files(path: str = "~", days: int = 7) -> str:
    """Lista los archivos modificados en los últimos N días."""
    import time
    root = Path(path).expanduser()
    cutoff = time.time() - (days * 86400)

    recent = []
    try:
        for f in root.rglob("*"):
            if f.is_file():
                try:
                    if f.stat().st_mtime > cutoff:
                        recent.append((f, f.stat().st_mtime))
                except (PermissionError, OSError):
                    pass
    except PermissionError:
        return f"Sin permisos para analizar '{root}'."

    recent.sort(key=lambda x: x[1], reverse=True)

    if not recent:
        return f"No hubo archivos modificados en los últimos {days} días en '{root.name}'."

    lines = [f"🕒 Archivos modificados en los últimos {days} días en '{root.name}':"]
    for f, mtime in recent[:15]:
        dt = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
        lines.append(f"  📄 {f.name:<40} [{dt}]")
    if len(recent) > 15:
        lines.append(f"  ... y {len(recent) - 15} archivos más.")
    return "\n".join(lines)
