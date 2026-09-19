"""
core/memory_scoring.py
Decide qué recuerdos merecen promoverse a la memoria durable, y cuáles no.

La primera versión de la destilación aceptaba todo lo que el modelo devolvía. Eso trata
igual a "Johan trabaja con Unipalma" —que salió en veinte conversaciones a lo largo de
meses— que a algo que se dijo una vez de pasada. Y como el resultado se inyecta en cada
respuesta, lo que entra de más no es neutro: desplaza a lo que importa.

La idea que se toma de la consolidación por fases de OpenClaw es la puntuación: un candidato
no se promueve por existir, sino por ganárselo. Aquí se gana de tres formas:

- **Repetición.** Si el mismo hecho aparece al destilar tramos distintos de la conversación,
  es que se sostiene en el tiempo. Es la señal más fiable que hay sin preguntarle a nadie.
- **Concreción.** Un hecho con nombres, cifras o rutas es comprobable. "Le gusta la
  tecnología" no dice nada que no supiéramos.
- **Longitud útil.** Ni telegráfico ni un párrafo: lo primero no informa, lo segundo es un
  resumen disfrazado de hecho.

La deduplicación es léxica y no semántica a propósito: comparar con embeddings costaría una
pasada del modelo por candidato para afinar un ordenamiento que ya funciona. Aquí el error
barato —dejar pasar dos formulaciones parecidas— lo corrige después la consolidación, que
sí las ve juntas y las fusiona.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

#: Cuántos hechos se promueven como mucho. Por encima, `MEMORY.md` deja de ser una memoria
#: y pasa a ser una transcripción — y se paga en cada llamada al modelo.
MAX_PROMOVIDOS = 40

#: Solapamiento a partir del cual dos hechos se consideran el mismo. Con 0.5, "Unipalma en
#: backups" y "Unipalma haciendo copias" se agrupan; "escucha Bon Jovi" y "su equipo se
#: llama Hansel" no comparten nada y quedan separados. Lo que se cuele de más lo fusiona
#: después la consolidación, que sí ve los dos textos juntos.
UMBRAL_DUPLICADO = 0.5

#: Longitud, en caracteres, del hecho que se considera "de tamaño útil".
LARGO_IDEAL = (30, 160)

#: Solo se descartan las palabras que aparecerían en CUALQUIER hecho: artículos,
#: preposiciones y el propio nombre del usuario (ese sale de la configuración, ver
#: `_nombre_del_usuario()`: estaba escrito acá y el repositorio es de quien lo instale).
#: Los verbos de contenido —"trabaja", "prefiere", "usa"— se conservan a propósito:
#: quitarlos dejaba dos o tres términos por frase, y con tan poca señal dos formulaciones
#: del mismo hecho ya no se parecían.
_PALABRAS_VACIAS = frozenset({
    "el", "la", "los", "las", "un", "una", "de", "del", "al", "a", "en", "y", "o", "que",
    "por", "para", "con", "sin", "su", "sus", "se", "es", "son", "sobre", "como",
    "más", "mas", "usuario",
})

#: Señales de que un hecho es concreto: cifras, rutas, direcciones, nombres propios.
_RE_NUMERO = re.compile(r"\d")
_RE_RUTA_O_URL = re.compile(r"[A-Za-z]:\\|/|https?://|\.\w{2,4}\b")
_RE_NOMBRE_PROPIO = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}")


def _normalizar(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in plano if not unicodedata.combining(c))


def _nombre_del_usuario() -> Set[str]:
    """Return las palabras del nombre configurado del usuario, ya normalizadas.

    Casi todos los hechos empiezan por su nombre ("Johan usa VS Code"), así que contarlo
    como palabra significativa haría que dos hechos distintos se parecieran. Sin nombre
    configurado, o si la configuración no se puede leer, no se descarta nada.
    """
    try:
        from config_manager import get_display_name

        nombre = get_display_name()
    except Exception as e:
        logger.debug(f"no se pudo leer el nombre del usuario para el puntaje: {e}")
        return set()
    return set(re.findall(r"[a-z0-9]+", _normalizar(nombre or "")))


def _palabras_significativas(texto: str, vacias: Optional[FrozenSet[str]] = None) -> Set[str]:
    """Return las palabras de `texto` que cuentan para compararlo con otro hecho.

    `vacias` es el conjunto ya resuelto (`palabras_vacias()`); se pasa desde el bucle de
    agrupamiento, que compara cada par de candidatos, para no releer la configuración en
    cada comparación (con 200 hechos son ~20.000 llamadas).
    """
    palabras = re.findall(r"[a-z0-9]+", _normalizar(texto))
    if vacias is None:
        vacias = palabras_vacias()
    return {p for p in palabras if len(p) > 3 and p not in vacias}


def palabras_vacias() -> FrozenSet[str]:
    """Return las palabras vacías de esta ejecución: las fijas más el nombre del usuario."""
    return _PALABRAS_VACIAS | frozenset(_nombre_del_usuario())


def _similitud(a: Set[str], b: Set[str]) -> float:
    """Return cuánto del conjunto MÁS PEQUEÑO está contenido en el otro.

    Se usa el coeficiente de solapamiento y no el de Jaccard porque los hechos son frases
    cortas y, quitadas las palabras vacías, quedan dos o tres términos útiles. Con Jaccard,
    "trabaja con Unipalma en backups" y "trabaja con Unipalma haciendo copias" comparten
    una palabra de cuatro (0.25) y no se agrupaban, aunque dicen lo mismo. El solapamiento
    mide lo que de verdad interesa aquí: si uno está contenido en el otro — que es
    exactamente el caso de "usa VS Code" frente a "usa VS Code en Windows 11".
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


@dataclass
class Candidato:
    """Un hecho propuesto, con lo que sabemos sobre por qué merece recordarse."""

    texto: str
    apariciones: int = 1
    lotes: Tuple[int, ...] = field(default_factory=tuple)
    puntuacion: float = 0.0
    _palabras: Optional[Set[str]] = field(default=None, repr=False, compare=False)

    @property
    def palabras(self) -> Set[str]:
        # Se calcula una vez: `texto` no cambia y el agrupamiento las consulta por cada par.
        if self._palabras is None:
            self._palabras = _palabras_significativas(self.texto)
        return self._palabras


def _puntuar(candidato: Candidato, total_lotes: int) -> float:
    """Return la puntuación de un candidato, entre 0 y 1 aproximadamente.

    Las tres señales pesan distinto a propósito: la repetición manda, porque es la única que
    no depende de heurísticas sobre el texto.
    """
    # Repetición: aparecer en varios tramos distintos de la conversación.
    repeticion = min(1.0, (candidato.apariciones - 1) / max(1, total_lotes - 1)) if total_lotes > 1 else 0.0

    # Concreción: datos comprobables dentro del hecho.
    texto = candidato.texto
    concreto = sum((
        0.34 if _RE_NUMERO.search(texto) else 0.0,
        0.33 if _RE_RUTA_O_URL.search(texto) else 0.0,
        0.33 if _RE_NOMBRE_PROPIO.search(texto[2:]) else 0.0,   # [2:] salta la viñeta
    ))

    # Tamaño: ni telegráfico ni un párrafo.
    largo = len(texto)
    if LARGO_IDEAL[0] <= largo <= LARGO_IDEAL[1]:
        tamano = 1.0
    elif largo < LARGO_IDEAL[0]:
        tamano = largo / LARGO_IDEAL[0]
    else:
        tamano = max(0.2, LARGO_IDEAL[1] / largo)

    return round(0.55 * repeticion + 0.30 * concreto + 0.15 * tamano, 4)


def agrupar_candidatos(hechos_por_lote: Sequence[Sequence[str]]) -> List[Candidato]:
    """Return los hechos agrupados, contando en cuántos lotes distintos apareció cada uno.

    Se conserva la formulación MÁS LARGA de cada grupo: entre "usa VS Code" y "usa VS Code
    en Windows 11 para el proyecto agente_ia", la segunda contiene a la primera.
    """
    candidatos: List[Candidato] = []
    vacias = palabras_vacias()   # una lectura de configuración por agrupamiento, no por par

    for indice_lote, hechos in enumerate(hechos_por_lote):
        vistos_en_este_lote: Set[int] = set()

        for hecho in hechos:
            texto = hecho.strip()
            if not texto:
                continue
            palabras = _palabras_significativas(texto, vacias)

            for i, existente in enumerate(candidatos):
                if _similitud(palabras, existente.palabras) >= UMBRAL_DUPLICADO:
                    # Solo cuenta como refuerzo si viene de OTRO lote: repetir dentro del
                    # mismo tramo es el modelo insistiendo, no el hecho sosteniéndose.
                    if i not in vistos_en_este_lote and indice_lote not in existente.lotes:
                        existente.apariciones += 1
                        existente.lotes = existente.lotes + (indice_lote,)
                    if len(texto) > len(existente.texto):
                        existente.texto = texto
                        existente._palabras = palabras   # el texto cambió: la caché también
                    vistos_en_este_lote.add(i)
                    break
            else:
                candidatos.append(Candidato(
                    texto=texto, apariciones=1, lotes=(indice_lote,), _palabras=palabras,
                ))
                vistos_en_este_lote.add(len(candidatos) - 1)

    total_lotes = max(1, len(hechos_por_lote))
    for c in candidatos:
        c.puntuacion = _puntuar(c, total_lotes)

    return candidatos


def promover(
    hechos_por_lote: Sequence[Sequence[str]], maximo: int = MAX_PROMOVIDOS,
) -> Tuple[List[Candidato], Dict[str, int]]:
    """Return los candidatos que merecen promoverse, y un resumen de lo que pasó.

    El resumen se usa para el diario: sin él, la consolidación sería una caja negra que
    reescribe la memoria sin poder explicar qué descartó ni por qué.
    """
    candidatos = agrupar_candidatos(hechos_por_lote)
    if not candidatos:
        return [], {"propuestos": 0, "agrupados": 0, "promovidos": 0, "reforzados": 0}

    propuestos = sum(len(lote) for lote in hechos_por_lote)
    reforzados = sum(1 for c in candidatos if c.apariciones > 1)

    ordenados = sorted(candidatos, key=lambda c: (-c.puntuacion, -c.apariciones, c.texto))
    promovidos = ordenados[:maximo]

    resumen = {
        "propuestos": propuestos,
        "agrupados": len(candidatos),
        "promovidos": len(promovidos),
        "reforzados": reforzados,
    }
    logger.info(
        f"[Consolidación] {propuestos} propuestos -> {len(candidatos)} distintos -> "
        f"{len(promovidos)} promovidos ({reforzados} reforzados por repetición)"
    )
    return promovidos, resumen


def formatear_para_consolidar(candidatos: Sequence[Candidato]) -> str:
    """Return los candidatos con su respaldo visible, para que el modelo lo tenga en cuenta.

    Marcar cuáles se repitieron le da al consolidador la información que necesita para
    ordenar: lo que se sostiene en el tiempo va primero.
    """
    lineas = []
    for c in candidatos:
        marca = f"  [visto en {c.apariciones} tramos]" if c.apariciones > 1 else ""
        lineas.append(f"{c.texto}{marca}")
    return "\n".join(lineas)
