"""
tests/test_webview_file_drop.py
REQ-015/CA-23 — `ui/webview/file_drop.py::validate_dropped_file()`.

Usa `tmp_path` de pytest para archivos reales (nunca rutas inventadas cuando se prueba el
caso "existe") — `.claude/rules/testing.md`.
"""

from ui.webview.file_drop import MAX_SIZE_BYTES, validate_dropped_file


def test_ruta_vacia_se_rechaza():
    accepted, reason = validate_dropped_file("")
    assert accepted is False
    assert reason


def test_extension_permitida_se_acepta(tmp_path):
    f = tmp_path / "notas.txt"
    f.write_text("hola")
    accepted, reason = validate_dropped_file(str(f))
    assert accepted is True
    assert reason == ""


def test_extension_no_permitida_se_rechaza(tmp_path):
    f = tmp_path / "virus.exe"
    f.write_bytes(b"MZ")
    accepted, reason = validate_dropped_file(str(f))
    assert accepted is False
    assert "extensi" in reason.lower()


def test_archivo_inexistente_se_rechaza(tmp_path):
    f = tmp_path / "no-existe.txt"
    accepted, reason = validate_dropped_file(str(f))
    assert accepted is False
    assert reason


def test_directorio_se_rechaza(tmp_path):
    """Un directorio soltado (no un archivo) debe rechazarse, no lanzar."""
    accepted, reason = validate_dropped_file(str(tmp_path))
    assert accepted is False
    assert reason


def test_archivo_demasiado_grande_se_rechaza(tmp_path, monkeypatch):
    f = tmp_path / "grande.txt"
    f.write_text("contenido de mas de un byte")
    monkeypatch.setattr("ui.webview.file_drop.MAX_SIZE_BYTES", 1)  # cualquier archivo > 1 byte falla
    accepted, reason = validate_dropped_file(str(f))
    assert accepted is False
    assert "grande" in reason.lower()


def test_limite_de_tamano_por_defecto_es_positivo():
    assert MAX_SIZE_BYTES > 0


def test_extensiones_de_imagen_permitidas(tmp_path):
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        f = tmp_path / f"foto{ext}"
        f.write_bytes(b"\x00")
        accepted, _ = validate_dropped_file(str(f))
        assert accepted is True, f"extensión {ext} debería estar permitida"


def test_extensiones_de_documento_permitidas(tmp_path):
    for ext in (".pdf", ".docx", ".xlsx", ".md", ".py", ".json", ".csv", ".log"):
        f = tmp_path / f"doc{ext}"
        f.write_bytes(b"\x00")
        accepted, _ = validate_dropped_file(str(f))
        assert accepted is True, f"extensión {ext} debería estar permitida"
