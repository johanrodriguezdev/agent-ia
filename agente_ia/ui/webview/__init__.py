"""
ui/webview
Paquete de la interfaz de escritorio WebView (REQ-015): shell PyQt6 (`QMainWindow` +
`QWebEngineView`) con frontend HTML/CSS/JS real en `ui/webview/frontend/`, conectado por
un bridge Python↔JS (`ui/webview/bridge.py::Bridge`) vía `QWebChannel`.

Vacío a propósito — cada módulo se importa directo (`from ui.webview.bridge import
Bridge`, etc.), sin lógica ni re-exports acá (mismo criterio que `ui/widgets/__init__.py`
en REQ-008/REQ-013).
"""
