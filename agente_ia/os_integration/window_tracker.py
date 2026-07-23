import subprocess
import re


def list_open_windows() -> list[dict]:
    """
    Usa PowerShell para listar ventanas con título visible.
    Retorna lista de dicts: [{"pid": 1234, "title": "Bloc de notas", "process": "notepad"}, ...]
    """
    ps_script = """
    Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object {
        [PSCustomObject]@{
            Pid     = $_.Id
            Process = $_.ProcessName
            Title   = $_.MainWindowTitle
        }
    } | ConvertTo-Json
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        import json
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []


def is_app_open(process_name: str) -> bool:
    """Verifica si un proceso (sin .exe) tiene ventana visible."""
    process_name = process_name.lower().replace(".exe", "")
    windows = list_open_windows()
    for w in windows:
        if w.get("process", "").lower() == process_name:
            return True
    return False


def find_window_by_process(process_name: str) -> dict | None:
    """Retorna la primera ventana abierta de un proceso, o None."""
    process_name = process_name.lower().replace(".exe", "")
    windows = list_open_windows()
    for w in windows:
        if w.get("process", "").lower() == process_name:
            return w
    return None


def get_active_window() -> dict | None:
    """Retorna la ventana actualmente activa."""
    ps_script = """
    Add-Type @"
        using System;
        using System.Runtime.InteropServices;
        using System.Diagnostics;
        public class WinAPI {
            [DllImport("user32.dll")]
            public static extern IntPtr GetForegroundWindow();
            [DllImport("user32.dll")]
            public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
        }
"@
    $hwnd = [WinAPI]::GetForegroundWindow()
    $pid = 0
    [void][WinAPI]::GetWindowThreadProcessId($hwnd, [ref]$pid)
    $proc = Get-Process -Id $pid
    [PSCustomObject]@{
        Pid     = $proc.Id
        Process = $proc.ProcessName
        Title   = $proc.MainWindowTitle
    } | ConvertTo-Json
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        import json
        return json.loads(result.stdout)
    except Exception:
        return None


def format_open_windows() -> str:
    """Devuelve una string legible con las ventanas abiertas."""
    windows = list_open_windows()
    if not windows:
        return "No hay ventanas abiertas."
    lines = ["Ventanas abiertas:"]
    for w in windows:
        title = w.get("title", "")
        proc  = w.get("process", "")
        pid   = w.get("pid", "")
        if title:
            lines.append(f"  • {title} ({proc}, PID {pid})")
        else:
            lines.append(f"  • {proc} (PID {pid})")
    return "\n".join(lines)
