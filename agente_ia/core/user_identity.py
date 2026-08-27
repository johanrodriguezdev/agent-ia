"""
core/user_identity.py
Traduce la identidad externa de cada canal a un único usuario canónico.

Antes de este módulo, cada canal usaba su propio identificador como `user_id`: Telegram
pasaba `str(update.effective_user.id)`, Discord `str(message.author.id)` y el escritorio la
constante `"default"`. Como `ai/user_manager.py` crea una carpeta por `user_id` y
`ai/memory_manager.py` filtra por esa columna, el resultado era que **la misma persona era
tres usuarios distintos**: lo que le contabas por voz no lo recordaba por Telegram.

La regla es directa y se apoya en el control de acceso que ya existe: si una identidad está
en `authorized_users.json`, **es el dueño**. No hace falta un mapa aparte que mantener en
dos sitios. Se deriva del modelo de confianza de un solo operador que documenta OpenClaw
para este mismo caso: un agente con herramientas no es una frontera de seguridad entre
varios usuarios, así que "autorizado" y "es el dueño" son la misma cosa.

Una identidad remota NO autorizada conserva su identificador externo y por tanto su propio
espacio aislado. En la práctica no debería llegar hasta acá —`_intercept_no_autorizado`
corta antes—, pero si algún camino futuro se saltara ese filtro, el desenlace seguro es
quedar aislado, nunca heredar la memoria del dueño.
"""

import logging

from core.authorized_users import LOCAL_CHANNELS, is_authorized

logger = logging.getLogger(__name__)

#: Usuario canónico del dueño. Todo lo que llegue por un canal local, o por un canal remoto
#: con identidad autorizada, se guarda y se busca bajo esta clave.
OWNER_USER_ID = "owner"

#: `user_id` que usaba el escritorio antes de este módulo. Se conserva como constante para
#: que la migración de datos sepa qué filas históricas pertenecen al dueño.
LEGACY_DESKTOP_USER_ID = "default"


def canonical_user_id(channel, external_id) -> str:
    """Return el `user_id` con el que guardar y consultar la memoria.

    `channel` es SIEMPRE el canal real que pasa el caller, nunca uno deducido del texto —
    mismo invariante que `core/security_manager.py` y `core/authorized_users.py`.
    """
    if is_authorized(channel, external_id):
        return OWNER_USER_ID

    identity = str(external_id).strip() if external_id is not None else ""
    if not identity:
        # Sin identidad y sin autorización no hay espacio propio al que mandarlo; se le da
        # una clave inerte antes que dejarlo caer en la del dueño.
        logger.warning(f"canonical_user_id(): identidad vacía en '{channel}', se aísla")
        return "desconocido"

    logger.info(f"canonical_user_id(): identidad no autorizada en '{channel}', se aísla")
    return identity


def is_owner(channel, external_id) -> bool:
    """Return True si esa identidad es la del dueño en ese canal."""
    return canonical_user_id(channel, external_id) == OWNER_USER_ID


def owner_legacy_ids(authorized_by_channel: dict) -> set:
    """Return los `user_id` históricos que pertenecían al dueño, para la migración.

    Son los identificadores externos autorizados (uno por canal remoto) más el `"default"`
    que usaba el escritorio. Es el conjunto de carpetas y filas de `users_data/` cuya
    memoria hay que consolidar bajo `OWNER_USER_ID`.
    """
    legacy = {LEGACY_DESKTOP_USER_ID}
    for channel, ids in (authorized_by_channel or {}).items():
        if str(channel).lower() in LOCAL_CHANNELS:
            continue
        legacy.update(str(i).strip() for i in ids if str(i).strip())
    return legacy
