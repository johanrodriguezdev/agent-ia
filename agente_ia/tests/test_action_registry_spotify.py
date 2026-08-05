"""
tests/test_action_registry_spotify.py
Pruebas de `agents/action_registry.py:open_spotify()` y de su registro en
`ACTION_REGISTRY` (REQ-008/CA-08). Sin lanzar procesos ni abrir el navegador reales
(.claude/rules/testing.md) — `subprocess.Popen`/`webbrowser.open` siempre mockeados.
"""

from unittest.mock import MagicMock, patch

from agents import action_registry


def test_open_spotify_registered_in_action_registry():
    assert "open_spotify" in action_registry.ACTION_REGISTRY
    entry = action_registry.ACTION_REGISTRY["open_spotify"]
    assert entry["fn"] is action_registry.open_spotify
    assert entry["category"] == "app"


def test_open_spotify_launches_installed_exe(monkeypatch):
    monkeypatch.setattr(action_registry.os.path, "isfile", lambda path: path.endswith("Spotify.exe"))
    monkeypatch.setattr(action_registry.time, "sleep", lambda *_a, **_k: None)
    with patch.object(action_registry.subprocess, "Popen") as mock_popen:
        result = action_registry.open_spotify()

    mock_popen.assert_called_once()
    assert "abierto" in result.lower()


def test_open_spotify_falls_back_to_browser_when_not_installed(monkeypatch):
    monkeypatch.setattr(action_registry.os.path, "isfile", lambda path: False)
    mock_webbrowser = MagicMock()
    with patch.dict("sys.modules", {"webbrowser": mock_webbrowser}):
        result = action_registry.open_spotify()

    mock_webbrowser.open.assert_called_once_with("https://open.spotify.com")
    assert "no está instalado" in result.lower() or "no esta instalado" in result.lower()


def test_open_spotify_handles_exception_without_crashing(monkeypatch):
    monkeypatch.setattr(action_registry.os.path, "isfile", lambda path: True)

    def boom(*_a, **_k):
        raise OSError("no se pudo lanzar el proceso")

    with patch.object(action_registry.subprocess, "Popen", side_effect=boom):
        result = action_registry.open_spotify()

    assert "no pude abrir spotify" in result.lower()


def test_open_spotify_executes_via_execute_action_on_desktop(monkeypatch):
    """Recorre el punto de entrada real (`execute_action`), no la función suelta — el
    gate de seguridad (core/security_manager.py) se evalúa acá, no dentro de la skill.
    Se parchea la entrada de ACTION_REGISTRY (no el atributo de módulo `open_spotify`):
    el dict guarda una referencia directa a la función tomada en tiempo de import, así
    que reasignar `action_registry.open_spotify` no la afecta."""
    monkeypatch.setitem(
        action_registry.ACTION_REGISTRY,
        "open_spotify",
        {"fn": lambda: "Spotify abierto.", "desc": "stub de prueba", "category": "app"},
    )
    result = action_registry.execute_action("open_spotify", channel="desktop")
    assert result == "Spotify abierto."
