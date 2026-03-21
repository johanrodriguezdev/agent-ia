import os
import shutil
from pathlib import Path
from datetime import datetime

# Mapa de alias comunes a rutas del sistema
FOLDER_ALIASES = {
    "escritorio":  Path.home() / "OneDrive" / "Desktop",
    "desktop":     Path.home() / "OneDrive" / "Desktop",
    "documentos":  Path.home() / "Documents",
    "documents":   Path.home() / "Documents",
    "descargas":   Path.home() / "Downloads",
    "downloads":   Path.home() / "Downloads",
    "musica":      Path.home() / "Music",
    "music":       Path.home() / "Music",
    "fotos":       Path.home() / "Pictures",
    "pictures":    Path.home() / "Pictures",
    "imagenes":    Path.home() / "Pictures",
    "videos":      Path.home() / "Videos",
}

def resolve_path(raw: str) -> Path:
    """Convierte alias comunes o rutas relativas a Path absolutos."""
    key = raw.lower().strip()
    if key in FOLDER_ALIASES:
        base = FOLDER_ALIASES[key]
        # Fallback si la ruta de OneDrive no existe
        if not base.exists():
            alt = Path.home() / base.name
            return alt if alt.exists() else base
        return base
    p = Path(raw)
    if p.is_absolute():
        return p
    return Path.home() / raw

def analyze_folder_storage(folder_path: str = "escritorio") -> str:
    """
    Analiza el espacio ocupado por una carpeta y sus subcarpetas.
    Devuelve un reporte legible con tamaños en MB.
    """
    path = resolve_path(folder_path)
    if not path.exists():
        return f"La carpeta '{folder_path}' no existe en el sistema."

    try:
        total_bytes = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        total_mb = total_bytes / (1024 * 1024)

        # Espacio de disco libre
        disk = shutil.disk_usage(path)
        free_gb = disk.free / (1024 ** 3)
        total_gb = disk.total / (1024 ** 3)

        return (
            f"Análisis de '{path.name}':\n"
            f"  - Tamaño total: {total_mb:.2f} MB\n"
            f"  - Disco libre:  {free_gb:.1f} GB de {total_gb:.1f} GB totales"
        )
    except Exception as e:
        return f"Error al analizar almacenamiento: {e}"

def create_text_file(filename: str, content: str = "", folder: str = ".") -> str:
    """
    Crea un archivo de texto en la carpeta indicada (default: directorio actual).
    Si no tiene extensión, añade .txt automáticamente.
    """
    # Aseguramos extensión
    if "." not in filename:
        filename += ".txt"

    save_dir = resolve_path(folder)
    save_dir.mkdir(parents=True, exist_ok=True)
    filepath = save_dir / filename

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Archivo '{filename}' creado en {save_dir}."
    except Exception as e:
        return f"Error al crear el archivo: {e}"

def list_files_detailed(folder_path: str = ".") -> str:
    """Lista archivos con tamaño y fecha de modificación."""
    path = resolve_path(folder_path)
    if not path.exists():
        return f"La ruta '{folder_path}' no existe."

    try:
        entries = sorted(path.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        entries_list = list(entries)
        if not entries_list:
            return f"La carpeta '{path.name}' está vacía."

        lines = [f"📂 Contenido de '{path.name}':"]
        for entry in entries_list[:20]:  # Limitamos a 20 para no saturar la respuesta
            stat = entry.stat()
            size_kb = stat.st_size / 1024
            mod_date = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y")
            icon = "📁" if entry.is_dir() else "📄"
            lines.append(f"  {icon} {entry.name}  ({size_kb:.1f} KB)  [{mod_date}]")

        if len(entries) > 20:
            lines.append(f"  ... y {len(entries) - 20} elementos más.")

        return "\n".join(lines)
    except Exception as e:
        return f"Error al listar archivos: {e}"

def get_disk_info() -> str:
    """Devuelve el estado de almacenamiento del disco principal."""
    try:
        disk = shutil.disk_usage(Path.home())
        total = disk.total / (1024 ** 3)
        used  = disk.used  / (1024 ** 3)
        free  = disk.free  / (1024 ** 3)
        pct   = (disk.used / disk.total) * 100
        return (
            f"Disco principal:\n"
            f"  - Total: {total:.1f} GB\n"
            f"  - Usado: {used:.1f} GB ({pct:.1f}%)\n"
            f"  - Libre: {free:.1f} GB"
        )
    except Exception as e:
        return f"No pude obtener info del disco: {e}"
