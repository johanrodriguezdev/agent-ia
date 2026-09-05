"""
ai/provider_health.py
Cooldown por proveedor de LLM: cuando uno se queda sin cuota o se pasa de límite de tasa,
se lo aparta un rato en vez de reintentarlo en cada mensaje.

El problema que resuelve: `ai/llm_provider.py` ya sabía caer a un respaldo cuando el
proveedor principal fallaba, pero solo dentro de UNA llamada. Al mensaje siguiente volvía a
empezar por el principal, volvía a esperar su timeout y volvía a fallar. Con la cuota
agotada eso son varios segundos perdidos por cada cosa que el usuario diga, durante todas
las horas que tarde en reponerse la cuota. El respaldo salvaba la respuesta; no evitaba la
espera.

Dos decisiones que vale la pena no perder:

- **Fail-open.** Un archivo de estado ausente, corrupto o con basura adentro se trata
  SIEMPRE como "ningún proveedor en cooldown". El peor caso de este módulo es no ahorrar
  tiempo — nunca dejar al agente sin proveedor al que preguntar.
- **Reordena, no descarta.** Un proveedor en cooldown baja al final de la cola, no sale de
  ella. Si todos están en cooldown se los prueba igual. El cooldown es una optimización,
  no una restricción.
"""

import json
import logging
import os
import re
import tempfile
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

#: Sibling de config.json y security_overrides.json, mismo patrón de ruta.
COOLDOWN_FILE = os.path.join(os.path.dirname(__file__), "..", "provider_cooldowns.json")

CATEGORIA_CUOTA = "cuota"
CATEGORIA_CREDENCIALES = "credenciales"
CATEGORIA_LIMITE_TASA = "limite_tasa"
CATEGORIA_OTRO = "otro"

#: Cuánto se aparta a un proveedor según por qué falló. Una categoría ausente de este mapa
#: (`otro`: caída de red, timeout, error puntual) NO genera cooldown — es transitoria y el
#: proveedor probablemente funcione en el mensaje siguiente.
SEGUNDOS_POR_CATEGORIA: Dict[str, int] = {
    # La cuota o el saldo no se reponen en un minuto: apartarlo media hora ahorra decenas
    # de timeouts sin arriesgar nada (`registrar_exito` lo devuelve antes si revive).
    CATEGORIA_CUOTA: 30 * 60,
    # Una API key ausente o inválida no se arregla sola mientras el proceso viva.
    CATEGORIA_CREDENCIALES: 30 * 60,
    # Un límite por minuto sí se repone solo: apartarlo media hora sería desperdiciarlo.
    CATEGORIA_LIMITE_TASA: 60,
}
_COOLDOWN_MAXIMO = max(SEGUNDOS_POR_CATEGORIA.values())

#: Señales inequívocas de "no queda cuota/saldo". Se evalúan ANTES que las de límite de
#: tasa: varios proveedores devuelven 429 tanto por exceso de velocidad como por cuota
#: agotada, y confundirlas haría reintentar en 60s algo que no vuelve en horas.
_PATRONES_CUOTA = (
    "insufficient_quota", "insufficient quota", "insufficient balance",
    "insufficient_balance", "exceeded your current quota", "quota exceeded",
    "out of credits", "credit balance", "billing", "payment required",
)
_PATRONES_CREDENCIALES = (
    "no está configurada", "no esta configurada", "invalid_api_key", "invalid api key",
    "incorrect api key", "authentication_error", "authentication error", "unauthorized",
    "permission_denied",
)
_PATRONES_LIMITE_TASA = (
    "rate limit", "rate_limit", "ratelimit", "too many requests", "resource_exhausted",
    "resource has been exhausted", "overloaded", "server is overloaded",
)
#: Códigos HTTP anclados con \b a propósito: un "429" suelto dentro de un conteo de tokens
#: ("4293 tokens") no debe apartar a un proveedor que funciona.
_CODIGOS_HTTP = (
    (CATEGORIA_CUOTA, r"\b402\b"),
    (CATEGORIA_CREDENCIALES, r"\b401\b"),
    (CATEGORIA_LIMITE_TASA, r"\b429\b"),
    (CATEGORIA_LIMITE_TASA, r"\b529\b"),
)

#: {proveedor: {"hasta": epoch_segundos, "categoria": str}}. La autoridad está en memoria;
#: el archivo solo evita que un reinicio vuelva a quemar la cuota recién agotada.
_cooldowns: Dict[str, Dict[str, Any]] = {}
_cargado = False


def _norm(proveedor: str) -> str:
    return str(proveedor).strip().lower()


def _clave(proveedor: str, modelo: str = "") -> str:
    """Clave bajo la que se aparta un destino.

    Con modelo, aparta SOLO ese modelo de ese proveedor. Es lo que hace falta para los
    catalogos gratuitos: en OpenRouter, que un modelo se quede sin cuota no dice nada de
    los otros veinte, y apartar "openrouter" entero por un 429 de uno solo dejaba fuera a
    todos los que seguian funcionando.

    Sin modelo, la clave es el proveedor — el comportamiento de siempre para quien no
    distingue modelos (DeepSeek, Anthropic: la cuota es de la cuenta, no del modelo).
    """
    base = _norm(proveedor)
    modelo = str(modelo or "").strip().lower()
    return f"{base}:{modelo}" if modelo else base


def _destino(candidato) -> tuple:
    """Normaliza un candidato a `(proveedor, modelo)`.

    Acepta un string (proveedor suelto, como siempre) o una tupla. Asi las dos formas
    conviven en la misma lista sin que el caller tenga que uniformarlas.
    """
    if isinstance(candidato, (tuple, list)) and candidato:
        proveedor = candidato[0]
        modelo = candidato[1] if len(candidato) > 1 else ""
        return _norm(proveedor), str(modelo or "").strip()
    return _norm(candidato), ""


def clasificar_error(error: Any) -> str:
    """Return la categoría de `error`: cuota, credenciales, limite_tasa u otro.

    Acepta tanto una excepción como el string "Error: ..." que algunos proveedores
    devuelven en vez de lanzar (ver `_intentar_respaldos` en llm_provider.py).
    """
    texto = str(error).lower()
    if not texto:
        return CATEGORIA_OTRO

    for patron in _PATRONES_CUOTA:
        if patron in texto:
            return CATEGORIA_CUOTA
    for patron in _PATRONES_CREDENCIALES:
        if patron in texto:
            return CATEGORIA_CREDENCIALES
    for patron in _PATRONES_LIMITE_TASA:
        if patron in texto:
            return CATEGORIA_LIMITE_TASA
    for categoria, patron in _CODIGOS_HTTP:
        if re.search(patron, texto):
            return categoria
    # Última red: una mención suelta de "quota" sin ninguna de las señales de arriba.
    if "quota" in texto:
        return CATEGORIA_CUOTA
    return CATEGORIA_OTRO


def _leer_archivo() -> Dict[str, Dict[str, Any]]:
    """Return el estado persistido, o {} ante cualquier problema. Nunca lanza."""
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    try:
        with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
            crudo = json.load(f)
    except Exception as e:
        # `except Exception` amplio y logueado, igual que core/security_config.py: el caso
        # real es un archivo truncado a mitad de escritura (UnicodeDecodeError), no solo
        # JSON inválido.
        logger.warning(f"provider_cooldowns.json ilegible ({type(e).__name__}), se ignora: {e}")
        return {}

    if not isinstance(crudo, dict):
        logger.warning("provider_cooldowns.json no es un objeto JSON — se ignora")
        return {}

    valido: Dict[str, Dict[str, Any]] = {}
    for proveedor, entrada in crudo.items():
        if not isinstance(proveedor, str) or not isinstance(entrada, dict):
            logger.warning(f"Entrada inválida en provider_cooldowns.json ignorada: {proveedor!r}")
            continue
        hasta = entrada.get("hasta")
        # `bool` es subclase de `int`: sin excluirlo, {"hasta": true} pasaría como 1.0.
        if isinstance(hasta, bool) or not isinstance(hasta, (int, float)):
            logger.warning(f"'hasta' inválido para {proveedor!r} en provider_cooldowns.json")
            continue
        categoria = entrada.get("categoria")
        valido[_norm(proveedor)] = {
            "hasta": float(hasta),
            "categoria": categoria if isinstance(categoria, str) else CATEGORIA_OTRO,
        }
    return valido


def _cargar_si_hace_falta() -> None:
    global _cargado
    if _cargado:
        return
    _cargado = True
    _cooldowns.clear()
    _cooldowns.update(_leer_archivo())


def _guardar() -> None:
    """Persiste el estado con un swap atómico.

    Un fallo de disco se loguea y se sigue: perder la persistencia solo cuesta reintentar
    una vez un proveedor caído después de un reinicio.
    """
    directorio = os.path.dirname(os.path.abspath(COOLDOWN_FILE)) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".provider_cooldowns_", dir=directorio)
    except OSError as e:
        logger.error(f"No se pudo crear el temporal de provider_cooldowns.json: {e}")
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_cooldowns, f, indent=2, sort_keys=True)
        os.replace(tmp_path, COOLDOWN_FILE)  # atómico en Windows (MoveFileEx) y POSIX
    except OSError as e:
        logger.error(f"No se pudo guardar provider_cooldowns.json: {e}")
        try:
            os.remove(tmp_path)
        except OSError as e_rm:
            logger.debug(f"Tampoco se pudo borrar el temporal {tmp_path}: {e_rm}")


def segundos_restantes(proveedor: str, modelo: str = "") -> float:
    """Return cuántos segundos le quedan de cooldown (0.0 si ya está listo).

    Con `modelo`, se toma el MAYOR de los dos cooldowns: el del modelo y el del proveedor
    entero. Un problema de credenciales aparta al proveedor completo y ningun modelo suyo
    puede responder mientras dure.
    """
    _cargar_si_hace_falta()
    if modelo:
        return max(_restante_de(_clave(proveedor, modelo)), _restante_de(_norm(proveedor)))
    return _restante_de(_norm(proveedor))


def _restante_de(clave: str) -> float:
    entrada = _cooldowns.get(clave)
    if not entrada:
        return 0.0
    restante = entrada["hasta"] - time.time()
    if restante <= 0:
        return 0.0
    # Tope defensivo: si el reloj del sistema saltó hacia atrás (cambio de hora, VM
    # suspendida), un "hasta" guardado quedaría vivo días enteros. Nunca más del máximo.
    return min(restante, float(_COOLDOWN_MAXIMO))


def en_cooldown(proveedor: str, modelo: str = "") -> bool:
    """Return True si a ese destino conviene no preguntarle todavía."""
    return segundos_restantes(proveedor, modelo) > 0


def registrar_fallo(proveedor: str, error: Any, modelo: str = "") -> float:
    """Aparta a `proveedor` si `error` lo amerita. Return los segundos aplicados (0 si no).

    Solo los fallos que no se arreglan en el mensaje siguiente generan cooldown: quedarse
    sin cuota, sin credenciales o pasarse de límite. Una caída de red no cuenta.
    """
    _cargar_si_hace_falta()
    categoria = clasificar_error(error)
    segundos = SEGUNDOS_POR_CATEGORIA.get(categoria, 0)
    if not segundos:
        logger.debug(f"Fallo de '{proveedor}' sin cooldown (categoría '{categoria}'): {error}")
        return 0.0

    # Las credenciales son del proveedor, no del modelo: sin clave valida no responde
    # ninguno de sus modelos, asi que se aparta el proveedor entero. Cuota y limite de
    # tasa, en cambio, son del modelo cuando se sabe cual — es lo que permite seguir
    # usando los otros gratuitos del mismo catalogo.
    if categoria == CATEGORIA_CREDENCIALES:
        clave = _norm(proveedor)
    else:
        clave = _clave(proveedor, modelo)
    _cooldowns[clave] = {"hasta": time.time() + segundos, "categoria": categoria}
    logger.warning(
        f"Proveedor '{clave}' apartado {segundos}s por '{categoria}'. Mientras dure se "
        f"empieza por otro sin gastar su timeout. Motivo: {error}"
    )
    _guardar()
    return float(segundos)


def registrar_exito(proveedor: str, modelo: str = "") -> None:
    """Devuelve ese destino a la rotación. No toca disco si no estaba apartado.

    Una respuesta buena levanta el cooldown del modelo Y el del proveedor: si contesto, ni
    las credenciales ni la cuota de la cuenta estaban rotas.
    """
    _cargar_si_hace_falta()
    claves = [_norm(proveedor)]
    if modelo:
        claves.insert(0, _clave(proveedor, modelo))

    levantadas = [c for c in claves if _cooldowns.pop(c, None) is not None]
    if not levantadas:
        return
    logger.info(f"'{'/'.join(levantadas)}' respondió bien: se levanta su cooldown")
    _guardar()


def ordenar_por_disponibilidad(candidatos: List[Any]) -> List[Any]:
    """Return `candidatos` con los disponibles primero, respetando el orden relativo.

    Cada candidato puede ser un proveedor suelto (string) o un `(proveedor, modelo)`: se
    devuelven tal como entraron, solo cambia el orden. Reordena, nunca descarta: si todos
    están en cooldown se devuelven igual, en su orden original. Que el agente pierda unos
    segundos es preferible a que se quede mudo.
    """
    disponibles: List[Any] = []
    esperando: List[Any] = []
    for candidato in candidatos:
        proveedor, modelo = _destino(candidato)
        (esperando if en_cooldown(proveedor, modelo) else disponibles).append(candidato)
    return disponibles + esperando


def estado() -> Dict[str, Dict[str, Any]]:
    """Return los cooldowns vigentes, para diagnóstico. Los ya vencidos no aparecen."""
    _cargar_si_hace_falta()
    vigentes: Dict[str, Dict[str, Any]] = {}
    for proveedor, entrada in _cooldowns.items():
        restante = segundos_restantes(proveedor)
        if restante > 0:
            vigentes[proveedor] = {
                "segundos_restantes": round(restante, 1),
                "categoria": entrada.get("categoria", CATEGORIA_OTRO),
            }
    return vigentes


def limpiar(borrar_archivo: bool = False) -> None:
    """Olvida todos los cooldowns. Para tests y para un reset manual."""
    global _cargado
    _cooldowns.clear()
    _cargado = True  # deliberado: no releer el disco después de un reset explícito
    if not borrar_archivo:
        return
    try:
        os.remove(COOLDOWN_FILE)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"No se pudo borrar provider_cooldowns.json: {e}")
