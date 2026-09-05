"""
tests/test_confirmation.py

REQ-006/CA-10 — confirmación agnóstica de canal (`core/confirmation.py`).

Convenciones (.claude/rules/testing.md): sin red, sin mic/altavoces, `input()` siempre
mockeado cuando aplica.
"""

import pytest

from core.confirmation import get_confirmation_adapter, register_confirmation_adapter
from core.security_manager import ChannelType, security_manager


def test_desktop_adapter_registered_by_conftest():
    """`tests/conftest.py` registra el mismo adaptador que `main.py` registraría en
    producción — este test confirma que el registro llegó, no que sea 'el' de producción."""
    adapter = get_confirmation_adapter(ChannelType.DESKTOP)
    assert adapter is not None


def test_canal_sin_adaptador_bloquea_sin_colgar():
    """CA-10: un canal sin adaptador registrado (p.ej. DISCORD, hoy sin adaptador real)
    nunca debe colgarse esperando input — se bloquea de inmediato, fail-closed."""
    assert get_confirmation_adapter(ChannelType.DISCORD) is None

    result = security_manager.require_confirmation("close_app", ChannelType.DISCORD)
    assert result is False


def test_desktop_adapter_llamado_correctamente(monkeypatch):
    """`require_confirmation()` en YELLOW consulta el adaptador registrado con
    `(action_name, mensaje)` y respeta su valor de retorno."""
    calls = []

    def fake_adapter(action_name: str, message: str) -> bool:
        calls.append((action_name, message))
        return True

    register_confirmation_adapter(ChannelType.DESKTOP, fake_adapter)
    try:
        result = security_manager.require_confirmation("close_app", ChannelType.DESKTOP)
        assert result is True
        assert calls and calls[0][0] == "close_app"
        # El nombre de la acción sigue llegando como PRIMER argumento —es lo que identifica
        # qué se autoriza— pero ya no aparece dentro del texto: ahí va la descripción en
        # español, porque es lo que el humano tiene que entender para decidir.
        assert "cierre una aplicación" in calls[0][1]
        assert "close_app" not in calls[0][1]
    finally:
        # Restaurar el adaptador real de test (el de conftest.py) para no filtrar
        # este fake a otros tests del mismo proceso.
        from tests.conftest import _desktop_confirm

        register_confirmation_adapter(ChannelType.DESKTOP, _desktop_confirm)


def test_register_confirmation_adapter_reemplaza_no_acumula():
    """Registrar dos veces el mismo canal reemplaza el adaptador, no lo apila.

    Se prueba el adaptador directo (no vía `require_confirmation()`): `CHANNEL_ALLOWED_LEVELS`
    no admite YELLOW en API (solo GREEN, no se toca esa matriz — CA-07), así que pasar por
    `require_confirmation()` nunca llegaría a consultar el adaptador.
    """
    calls_a, calls_b = [], []

    register_confirmation_adapter(ChannelType.API, lambda a, m: calls_a.append(1) or True)
    register_confirmation_adapter(ChannelType.API, lambda a, m: calls_b.append(1) or True)

    adapter = get_confirmation_adapter(ChannelType.API)
    assert adapter("accion", "mensaje") is True
    assert calls_a == [] and calls_b == [1]
