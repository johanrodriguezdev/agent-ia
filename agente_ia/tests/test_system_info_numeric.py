"""
tests/test_system_info_numeric.py
Pruebas de las 4 funciones numéricas nuevas de REQ-008/CA-06
(`system_actions/system_info.py`) consumidas por `ui/widgets/system_status_card.py`.
Sin red, sin mockear psutil salvo para el caso de fallo — el resto usa el psutil real
del entorno (ya es una dependencia instalada, no hace I/O externa).
"""

from unittest.mock import patch

from system_actions import system_info


def test_get_cpu_percent_returns_float_in_range():
    value = system_info.get_cpu_percent()
    assert isinstance(value, float)
    assert 0.0 <= value <= 100.0


def test_get_ram_percent_returns_float_in_range():
    value = system_info.get_ram_percent()
    assert isinstance(value, float)
    assert 0.0 <= value <= 100.0


def test_get_disk_percent_returns_float_in_range():
    value = system_info.get_disk_percent()
    assert isinstance(value, float)
    assert 0.0 <= value <= 100.0


def test_get_disk_percent_invalid_drive_degrades_to_zero():
    value = system_info.get_disk_percent("Z:\\ruta-que-no-existe\\")
    assert value == 0.0


def test_get_network_io_counters_returns_tuple_of_two_ints():
    sent, recv = system_info.get_network_io_counters()
    assert isinstance(sent, int)
    assert isinstance(recv, int)
    assert sent >= 0
    assert recv >= 0


def test_get_cpu_percent_degrades_gracefully_without_psutil():
    with patch.object(system_info, "_has_psutil", return_value=False):
        assert system_info.get_cpu_percent() == 0.0


def test_get_network_io_counters_degrades_gracefully_on_exception():
    with patch("psutil.net_io_counters", side_effect=RuntimeError("boom")):
        assert system_info.get_network_io_counters() == (0, 0)
