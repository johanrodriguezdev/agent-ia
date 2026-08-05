"""
system_info.py
Informacion del sistema operativo en tiempo real.
Usa psutil, platform y subprocess para datos 100% reales.
Sin emojis para compatibilidad con terminales cp1252 de Windows.
"""

import logging
import platform
import subprocess
import os
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def _has_psutil() -> bool:
    try:
        import psutil
        return True
    except ImportError:
        return False


def get_system_overview() -> str:
    """Resumen completo del sistema operativo y hardware."""
    proc_str = (platform.processor() or "Desconocido")
    proc_str = proc_str[:80] if len(proc_str) > 80 else proc_str
    ver_str  = (platform.version() or "")
    ver_str  = ver_str[:40] if len(ver_str) > 40 else ver_str
    lines = [
        "Sistema operativo:",
        f"  OS:          {platform.system()} {platform.release()} ({ver_str})",
        f"  Maquina:     {platform.machine()} | Nodo: {platform.node()}",
        f"  Procesador:  {proc_str}",
        f"  Python:      {platform.python_version()}",
        f"  Hora actual: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
    ]
    return "\n".join(lines)


def get_cpu_info() -> str:
    """Uso actual de la CPU."""
    if not _has_psutil():
        return "psutil no esta instalado. Ejecuta: pip install psutil"
    import psutil
    pct      = psutil.cpu_percent(interval=1)
    count    = psutil.cpu_count(logical=True)
    count_p  = psutil.cpu_count(logical=False)
    freq     = psutil.cpu_freq()
    freq_str = f"{freq.current:.0f} MHz" if freq else "Desconocida"
    return (
        f"CPU:\n"
        f"  Uso actual:      {pct}%\n"
        f"  Nucleos fisicos: {count_p}\n"
        f"  Nucleos logicos: {count}\n"
        f"  Frecuencia:      {freq_str}"
    )


def get_ram_info() -> str:
    """Informacion de la memoria RAM."""
    if not _has_psutil():
        return "psutil no disponible."
    import psutil
    mem      = psutil.virtual_memory()
    swap     = psutil.swap_memory()
    total_gb = mem.total       / (1024 ** 3)
    used_gb  = mem.used        / (1024 ** 3)
    avail_gb = mem.available   / (1024 ** 3)
    swap_gb  = swap.total      / (1024 ** 3)
    return (
        f"Memoria RAM:\n"
        f"  Total:      {total_gb:.1f} GB\n"
        f"  Usada:      {used_gb:.1f} GB ({mem.percent}%)\n"
        f"  Disponible: {avail_gb:.1f} GB\n"
        f"  SWAP:       {swap_gb:.1f} GB (usado: {swap.percent}%)"
    )


def get_disk_info(drive: str = "C:\\") -> str:
    """Espacio de disco de una unidad especifica."""
    import shutil
    try:
        usage = shutil.disk_usage(drive)
        total = usage.total / (1024 ** 3)
        used  = usage.used  / (1024 ** 3)
        free  = usage.free  / (1024 ** 3)
        pct   = (usage.used / usage.total) * 100
        return (
            f"Disco {drive}:\n"
            f"  Total:  {total:.1f} GB\n"
            f"  Usado:  {used:.1f} GB ({pct:.1f}%)\n"
            f"  Libre:  {free:.1f} GB"
        )
    except Exception as e:
        return f"No pude obtener info del disco '{drive}': {e}"


def get_network_info() -> str:
    """Informacion basica de red."""
    if not _has_psutil():
        return "psutil no disponible."
    import psutil
    addrs = psutil.net_if_addrs()
    lines = ["Interfaces de red activas:"]
    for iface, addr_list in addrs.items():
        for addr in addr_list:
            if addr.family.name == "AF_INET":
                lines.append(f"  {iface:<20} {addr.address}")
    return "\n".join(lines) if len(lines) > 1 else "No se encontraron interfaces de red activas."


def list_running_processes(limit: int = 10) -> str:
    """Lista los procesos con mayor uso de RAM."""
    if not _has_psutil():
        return "psutil no disponible."
    import psutil
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    procs.sort(key=lambda x: x.get("memory_percent") or 0, reverse=True)
    lines = [f"Top {limit} procesos por uso de RAM:"]
    for proc in list(procs)[:limit]:
        name = str(proc.get("name") or "?")[:30]
        pid  = proc.get("pid", 0)
        mem  = proc.get("memory_percent") or 0
        cpu  = proc.get("cpu_percent") or 0
        lines.append(f"  PID {pid:>6} | {name:<30} RAM: {mem:.1f}% | CPU: {cpu:.1f}%")
    return "\n".join(lines)


def get_uptime() -> str:
    """Tiempo que lleva encendido el sistema."""
    if not _has_psutil():
        return "psutil no disponible."
    import psutil, time
    boot_time = psutil.boot_time()
    uptime_s  = time.time() - boot_time
    hours     = int(uptime_s // 3600)
    minutes   = int((uptime_s % 3600) // 60)
    boot_dt   = datetime.fromtimestamp(boot_time).strftime("%d/%m/%Y %H:%M")
    return f"El sistema lleva encendido {hours}h {minutes}m (desde las {boot_dt})."


def get_environment_variable(var: str) -> str:
    value = os.environ.get(var)
    if value:
        return f"Variable de entorno {var} = {value}"
    return f"La variable '{var}' no existe o no esta definida."


def get_windows_username() -> str:
    return f"Usuario actual de Windows: {os.environ.get('USERNAME', 'Desconocido')}"


# ─────────────────────────────────────────────
#  Variantes numéricas (REQ-008/CA-06) — consumo directo por widgets de GUI,
#  no strings formateados para voz/chat. No bloqueantes: usadas dentro de un
#  QTimer del hilo de la GUI (ver ui/widgets/system_status_card.py).
# ─────────────────────────────────────────────

def get_cpu_percent() -> float:
    """Return current CPU usage percentage. 0.0 if psutil is unavailable or fails."""
    if not _has_psutil():
        return 0.0
    import psutil
    try:
        # interval=None: lectura no bloqueante (compara contra la última llamada).
        return float(psutil.cpu_percent(interval=None))
    except Exception as e:
        logger.error(f"Error obteniendo porcentaje de CPU: {e}")
        return 0.0


def get_ram_percent() -> float:
    """Return current RAM usage percentage. 0.0 if psutil is unavailable or fails."""
    if not _has_psutil():
        return 0.0
    import psutil
    try:
        return float(psutil.virtual_memory().percent)
    except Exception as e:
        logger.error(f"Error obteniendo porcentaje de RAM: {e}")
        return 0.0


def get_disk_percent(drive: str = "C:\\") -> float:
    """Return disk usage percentage for `drive`. 0.0 if the lookup fails."""
    import shutil
    try:
        usage = shutil.disk_usage(drive)
        if not usage.total:
            return 0.0
        return float((usage.used / usage.total) * 100)
    except Exception as e:
        logger.error(f"Error obteniendo porcentaje de disco '{drive}': {e}")
        return 0.0


def get_network_io_counters() -> tuple[int, int]:
    """Return raw cumulative (bytes_sent, bytes_recv) counters. (0, 0) on failure.

    Devuelve el contador crudo acumulado, no un porcentaje ni un delta — el
    cálculo de tasa entre dos lecturas vive en el widget consumidor, para que
    esta función siga siendo pura y testeable sin estado oculto entre llamadas.
    """
    if not _has_psutil():
        return (0, 0)
    import psutil
    try:
        counters = psutil.net_io_counters()
        return (int(counters.bytes_sent), int(counters.bytes_recv))
    except Exception as e:
        logger.error(f"Error obteniendo contadores de red: {e}")
        return (0, 0)
