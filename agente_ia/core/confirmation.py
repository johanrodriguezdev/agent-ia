"""
core/confirmation.py
Registro de adaptadores de confirmación agnósticos de canal (REQ-006, CA-10).

`security_manager.require_confirmation()` ya no llama a `input()` directamente en la
rama YELLOW: consulta el adaptador registrado para el canal resuelto. Si no hay
adaptador registrado para ese canal, la acción se deniega (fail-closed) — nunca se
bloquea esperando una entrada que el canal no puede ofrecer (p.ej. Telegram, que es
async y no tiene una consola bloqueante a mano).

Cada adaptador es una función síncrona `(action_name, mensaje) -> bool`. Si un canal
async (Telegram/Discord) necesita confirmar de verdad en el futuro, es responsabilidad
de ese canal construir el puente async→sync al registrar su adaptador — este módulo
permanece 100% síncrono (CA-11).
"""

import logging
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# (action_name, mensaje) -> confirmado. Siempre síncrono/bloqueante.
ConfirmFn = Callable[[str, str], bool]

_ADAPTERS: Dict["ChannelType", ConfirmFn] = {}


def register_confirmation_adapter(channel, fn: ConfirmFn) -> None:
    """Registra (o reemplaza) el adaptador de confirmación de un canal."""
    _ADAPTERS[channel] = fn
    logger.info(f"Adaptador de confirmación registrado para canal '{getattr(channel, 'value', channel)}'")


def get_confirmation_adapter(channel) -> Optional[ConfirmFn]:
    """Retorna el adaptador registrado para `channel`, o None si no hay ninguno.

    Ausencia de adaptador es una condición válida y esperada (no un error): significa
    que ese canal no puede confirmar acciones YELLOW y el caller debe denegar.
    """
    return _ADAPTERS.get(channel)
