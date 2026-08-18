"""
tests/test_autostart.py

REQ-011 — pruebas para `setup_autostart.py` (auto-inicio con Windows, arranque
minimizado a bandeja). Todas mockean `winreg` por completo (`unittest.mock.patch`) —
nunca tocan el registro real de Windows, según `.claude/rules/testing.md` y el riesgo
ya documentado en `propuestas/arquitectura-011.md` ("Tests que ejerciten
activar()/desactivar() toquen el registro real del usuario que corre pytest").

Escrito por `orion-tester`: `orion-dev` no entregó tests en este paso (ver
`propuestas/desarrollo-log-011.md`), así que este archivo cubre CA-01, CA-02, CA-05,
CA-06, CA-07, CA-08 y los dos casos extra sugeridos en `arquitectura-011.md`
("Pruebas sugeridas"): `_resolver_pythonw` fallback y `esta_activo` en ambos sentidos.
CA-03/CA-04 se prueban en `tests/test_main.py` y `tests/test_gui_widgets.py`
respectivamente. CA-09 no es testeable por unidad (revisión de código, ver
test-results-011.md); CA-10 ya está cubierto por el test de REQ-009 existente.
"""

import logging
from unittest.mock import MagicMock, patch

import setup_autostart
import ui.gui as gui_module


# ---------------------------------------------------------------------------
# _resolver_pythonw() / construir_comando_autostart() — extras sugeridos por
# arquitectura-011.md
# ---------------------------------------------------------------------------

def test_resolver_pythonw_usa_pythonw_si_existe():
    with patch("os.path.isfile", return_value=True), \
         patch("sys.executable", r"C:\Python\python.exe"):
        resultado = setup_autostart._resolver_pythonw()
    assert resultado == r"C:\Python\pythonw.exe"


def test_resolver_pythonw_fallback_a_sys_executable(caplog):
    with patch("os.path.isfile", return_value=False), \
         patch("sys.executable", r"C:\Python\python.exe"), \
         caplog.at_level(logging.WARNING, logger="setup_autostart"):
        resultado = setup_autostart._resolver_pythonw()
    assert resultado == r"C:\Python\python.exe"
    assert any("pythonw.exe" in r.message for r in caplog.records)
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_construir_comando_autostart_incluye_tray_y_main_py():
    with patch("setup_autostart._resolver_pythonw", return_value=r"C:\Python\pythonw.exe"):
        comando = setup_autostart.construir_comando_autostart()
    assert "--tray" in comando
    assert setup_autostart.MAIN_SCRIPT in comando
    assert r"C:\Python\pythonw.exe" in comando


# ---------------------------------------------------------------------------
# esta_activo() — extra sugerido por arquitectura ("esta_activo refleja el registro")
# ---------------------------------------------------------------------------

def test_esta_activo_true_si_la_entrada_existe():
    with patch("setup_autostart.winreg.OpenKey") as mock_open, \
         patch("setup_autostart.winreg.QueryValueEx", return_value=("comando", 1)):
        assert setup_autostart.esta_activo() is True
    mock_open.assert_called_once()


def test_esta_activo_false_si_no_existe():
    with patch("setup_autostart.winreg.OpenKey", side_effect=FileNotFoundError):
        assert setup_autostart.esta_activo() is False


# ---------------------------------------------------------------------------
# CA-01 / CA-05 — activar() registra el comando con --tray, es idempotente
# ---------------------------------------------------------------------------

def test_activar_registra_comando_con_flag_tray_ca01():
    with patch("setup_autostart.winreg.CreateKeyEx"), \
         patch("setup_autostart.winreg.SetValueEx") as mock_set, \
         patch("setup_autostart.construir_comando_autostart",
               return_value=r'"C:\Python\pythonw.exe" "C:\proj\main.py" --tray'):
        resultado = setup_autostart.activar()

    assert resultado is True
    mock_set.assert_called_once()
    args, _ = mock_set.call_args
    # winreg.SetValueEx(key, value_name, reserved, type, value)
    assert args[1] == setup_autostart.AUTOSTART_VALUE_NAME
    assert "--tray" in args[4]
    assert "main.py" in args[4]


def test_activar_dos_veces_es_idempotente_ca05():
    with patch("setup_autostart.winreg.CreateKeyEx"), \
         patch("setup_autostart.winreg.SetValueEx") as mock_set, \
         patch("setup_autostart.construir_comando_autostart",
               return_value=r'"C:\Python\pythonw.exe" "C:\proj\main.py" --tray'):
        primero = setup_autostart.activar()
        segundo = setup_autostart.activar()

    assert primero is True and segundo is True
    assert mock_set.call_count == 2
    primera, segunda = mock_set.call_args_list
    assert primera[0][1] == segunda[0][1] == setup_autostart.AUTOSTART_VALUE_NAME
    assert primera[0][4] == segunda[0][4]


def test_activar_loguea_warning_ca07(caplog):
    with patch("setup_autostart.winreg.CreateKeyEx"), \
         patch("setup_autostart.winreg.SetValueEx"), \
         patch("setup_autostart.construir_comando_autostart", return_value="comando-x"), \
         caplog.at_level(logging.WARNING, logger="setup_autostart"):
        setup_autostart.activar()

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "ACTIVADO" in warnings[0].message
    assert "registro HKCU Run" in warnings[0].message


def test_activar_retorna_false_ante_oserror_inesperado():
    with patch("setup_autostart.winreg.CreateKeyEx", side_effect=OSError("boom")):
        assert setup_autostart.activar() is False


# ---------------------------------------------------------------------------
# CA-02 / CA-06 / CA-07 — desactivar()
# ---------------------------------------------------------------------------

def test_desactivar_borra_la_entrada_por_completo_ca02():
    with patch("setup_autostart.winreg.OpenKey"), \
         patch("setup_autostart.winreg.DeleteValue") as mock_delete:
        resultado = setup_autostart.desactivar()

    assert resultado is True
    mock_delete.assert_called_once()
    args, _ = mock_delete.call_args
    assert args[1] == setup_autostart.AUTOSTART_VALUE_NAME

    # No queda ningún otro artefacto que limpiar: tras borrar, esta_activo() refleja
    # que ya no existe (CA-02 — "no deja rastros").
    with patch("setup_autostart.winreg.OpenKey", side_effect=FileNotFoundError):
        assert setup_autostart.esta_activo() is False


def test_desactivar_sin_autostart_previo_no_falla_ca06():
    with patch("setup_autostart.winreg.OpenKey", side_effect=FileNotFoundError):
        resultado = setup_autostart.desactivar()
    assert resultado is True


def test_desactivar_retorna_false_ante_oserror_inesperado():
    with patch("setup_autostart.winreg.OpenKey", side_effect=PermissionError("boom")):
        resultado = setup_autostart.desactivar()
    assert resultado is False


def test_desactivar_loguea_warning_solo_si_borro_algo_ca07(caplog):
    with patch("setup_autostart.winreg.OpenKey"), \
         patch("setup_autostart.winreg.DeleteValue"), \
         caplog.at_level(logging.WARNING, logger="setup_autostart"):
        setup_autostart.desactivar()
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "DESACTIVADO" in warnings[0].message

    caplog.clear()
    with patch("setup_autostart.winreg.OpenKey", side_effect=FileNotFoundError), \
         caplog.at_level(logging.WARNING, logger="setup_autostart"):
        setup_autostart.desactivar()
    warnings_sin_borrar = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings_sin_borrar) == 0


# ---------------------------------------------------------------------------
# _confirmar() — implementación del gate 🟡 Amarillo (security-levels.md) para este
# script (ver arquitectura-011.md, "Por qué el gate Amarillo se implementa acá").
# ---------------------------------------------------------------------------

def test_confirmar_acepta_variantes_afirmativas():
    for respuesta in ("sí", "si", "SI", "yes", "s", "S"):
        with patch("builtins.input", return_value=respuesta):
            assert setup_autostart._confirmar("¿Confirmás?") is True


def test_confirmar_rechaza_cualquier_otra_respuesta():
    for respuesta in ("no", "", "cancelar", "n"):
        with patch("builtins.input", return_value=respuesta):
            assert setup_autostart._confirmar("¿Confirmás?") is False


# ---------------------------------------------------------------------------
# CA-08 — sin controles de autostart en ui/gui.py
# ---------------------------------------------------------------------------

def test_gui_sin_controles_de_autostart_ca08():
    with open(gui_module.__file__, encoding="utf-8") as f:
        source = f.read().lower()
    for keyword in ("autostart", "auto-inicio", "auto_inicio"):
        assert keyword not in source
