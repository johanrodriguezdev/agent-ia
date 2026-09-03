"""
skills/flow_skill.py
Crear, ejecutar, retomar y cancelar flujos durables hablando (`core/flows.py`).

**Por qué esto es una skill y no una pantalla.** El flujo se arma diciéndolo: "aprendé el
flujo modo trabajo: abrí chrome, después el bloc de notas". La pantalla de flujos —cuando
exista— es para VER lo que ya se creó y corregir un paso, no para armarlo arrastrando
cajas. Un asistente al que hay que llenarle un formulario para enseñarle una rutina no es
un asistente.

Ninguna de estas acciones ejecuta nada por su cuenta: cada paso del flujo pasa por
`agents/action_registry.execute_action()`, que es un punto de gate del sistema. Por eso
ejecutar un flujo es verde y crearlo es amarillo — crear deja escrito algo que va a correr
después, quizá sin nadie mirando.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)

INTENT_CREAR = "CREATE_FLOW"
INTENT_EJECUTAR = "RUN_FLOW"
INTENT_LISTAR = "LIST_FLOWS"
INTENT_RETOMAR = "RESUME_FLOW"
INTENT_CANCELAR = "CANCEL_FLOW"

#: "aprendé el flujo modo trabajo: abrí chrome, después el bloc" → nombre y cuerpo.
_RE_DEFINICION = re.compile(
    r"(?:flujo|rutina)\s+(?:llamad[oa]\s+)?[\"'«]?(.+?)[\"'»]?\s*[:：]\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)
#: "ejecutá el flujo modo trabajo" → nombre.
_RE_NOMBRE = re.compile(
    r"(?:flujo|rutina)\s+(?:llamad[oa]\s+)?[\"'«]?([^\"'»:]+?)[\"'»]?\s*$",
    re.IGNORECASE,
)
#: Separadores "fuertes": siempre parten pasos. La coma NO está acá a propósito — dentro de
#: "si contiene error, tomá una captura" la coma es parte de la condición, no un separador.
#: Se parte primero por estos y solo después, dentro de cada trozo sin condición, por comas.
_RE_SEPARADOR_FUERTE = re.compile(
    r"\s*(?:;|\n|\bdespu[ée]s\b|\bluego\b|\by\s+despu[ée]s\b|\bseguido\s+de\b)\s*",
    re.IGNORECASE,
)
_RE_SEPARADOR_DEBIL = re.compile(r"\s*,\s*|\s+y\s+", re.IGNORECASE)

#: "si (no) contiene X, ACCIÓN" / "si dice X entonces ACCIÓN"
_RE_CONDICION = re.compile(
    r"^si\s+(?:el\s+resultado\s+|la\s+respuesta\s+|eso\s+)?(?:(no)\s+)?"
    r"(?:contiene|dice|tiene|incluye|menciona)\s+"
    r"[\"'«]?(.+?)[\"'»]?\s*(?:,\s*|\s+entonces\s+)(.+)$",
    re.IGNORECASE,
)
#: "si no hay nada, ACCIÓN" / "si hay algo entonces ACCIÓN"
_RE_CONDICION_VACIO = re.compile(
    r"^si\s+(?:(no)\s+hay\s+(?:nada|resultados?)|hay\s+(?:algo|resultados?))\s*"
    r"(?:,\s*|\s+entonces\s+)(.+)$",
    re.IGNORECASE,
)

#: Palabras que no aportan para desambiguar una acción por su descripción.
_VACIAS = frozenset({
    "abre", "abrir", "abri", "el", "la", "los", "las", "un", "una", "de", "del",
    "en", "con", "para", "que", "por", "me", "mi", "y", "a", "al", "lo",
})

#: Frases sueltas → acción del registro. Es un mapeo chico y explícito a propósito: se
#: prefiere no entender un paso y decirlo, antes que adivinar mal y dejar escrito un flujo
#: que hace algo distinto de lo que el usuario dijo.
_SINONIMOS: List[Tuple[Tuple[str, ...], str]] = [
    (("chrome", "google chrome"), "open_chrome"),
    (("bloc de notas", "bloc", "notepad"), "open_notepad"),
    (("explorador", "explorador de archivos"), "open_explorer"),
    (("calculadora",), "open_calculator"),
    (("navegador",), "open_browser"),
    (("spotify", "musica", "música"), "open_spotify"),
    (("captura", "screenshot", "pantallazo"), "take_screenshot"),
    (("hora", "fecha", "fecha y hora"), "get_current_datetime"),
    (("disco", "espacio en disco"), "get_disk_info"),
    (("cerrar ventana", "cierra la ventana", "cerra la ventana"), "close_window"),
    (("ventana activa", "que ventana"), "get_active_window_info"),
    (("guarda el archivo", "guardar el archivo"), "save_file_desktop"),
    (("busca en google", "buscar en google", "google"), "search_google"),
    (("abre la url", "abri la url", "abrir url"), "open_url"),
    (("resumen", "resumi", "resume"), "generate_ai_summary"),
]
_RE_ESPERA = re.compile(r"esper[aá]?\s+(\d+)\s*(?:segundos?|s\b)?", re.IGNORECASE)

#: "todos los días a las 16:00" → el formato que entiende `proactive_engine._should_fire()`.
_RE_DIARIO = re.compile(
    r",?\s*(?:todos\s+los\s+d[ií]as|cada\s+d[ií]a|diariamente)\s+a\s+la[s]?\s+"
    r"(\d{1,2})(?::(\d{2}))?\s*(?:h(?:s|oras)?)?",
    re.IGNORECASE,
)
_RE_CADA_HORA = re.compile(r",?\s*cada\s+hora", re.IGNORECASE)


def extraer_horario(texto: str):
    """Return `(horario, texto_sin_el_horario)`.

    El horario se saca ANTES de separar nombre y pasos: si no, "todos los días a las 16:00"
    quedaría pegado al nombre del flujo o se intentaría interpretar como un paso.
    """
    diario = _RE_DIARIO.search(texto or "")
    if diario:
        hora = int(diario.group(1))
        minuto = int(diario.group(2) or 0)
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return f"daily:{hora:02d}:{minuto:02d}", _RE_DIARIO.sub(" ", texto, count=1)

    if _RE_CADA_HORA.search(texto or ""):
        return "hourly", _RE_CADA_HORA.sub(" ", texto, count=1)
    return "", texto or ""


class FlowSkill(BaseSkill):
    """Rutinas de varios pasos que sobreviven a un reinicio."""

    @property
    def name(self) -> str:
        return "FlowSkill"

    @property
    def description(self) -> str:
        return (
            "Crea y ejecuta flujos de varios pasos que se pueden retomar donde quedaron, "
            "cancelar a mitad, y que se detienen solos cuando necesitan permiso."
        )

    def get_intents(self) -> List[str]:
        return [INTENT_CREAR, INTENT_EJECUTAR, INTENT_LISTAR, INTENT_RETOMAR, INTENT_CANCELAR]

    def get_training_data(self) -> List[Tuple[str, str]]:
        return [
            ("aprende el flujo", INTENT_CREAR),
            ("crea un flujo", INTENT_CREAR),
            ("guarda esta rutina como flujo", INTENT_CREAR),
            ("define el flujo", INTENT_CREAR),
            ("aprende esta secuencia", INTENT_CREAR),

            ("ejecuta el flujo", INTENT_EJECUTAR),
            ("corre el flujo", INTENT_EJECUTAR),
            ("arranca la rutina", INTENT_EJECUTAR),
            ("dale al flujo", INTENT_EJECUTAR),

            ("que flujos tenes", INTENT_LISTAR),
            ("lista los flujos", INTENT_LISTAR),
            ("mostrame las rutinas", INTENT_LISTAR),
            ("como va el flujo", INTENT_LISTAR),

            ("continua el flujo", INTENT_RETOMAR),
            ("retoma el flujo", INTENT_RETOMAR),
            ("segui con el flujo", INTENT_RETOMAR),

            ("cancela el flujo", INTENT_CANCELAR),
            ("detene el flujo", INTENT_CANCELAR),
            ("para la rutina", INTENT_CANCELAR),
        ]

    def extract_params(self, intent: str, text: str) -> Dict[str, Any]:
        crudo = (text or "").strip()
        if intent == INTENT_CREAR:
            horario, sin_horario = extraer_horario(crudo)
            definicion = _RE_DEFINICION.search(sin_horario)
            if not definicion:
                return {"name": "", "cuerpo": "", "horario": horario, "raw_text": crudo}
            return {
                # `name` va con ese nombre porque `format_details()` lo muestra en la
                # confirmación: crear es amarillo y hay que ver QUÉ se está guardando.
                "name": definicion.group(1).strip(" ,"),
                "cuerpo": definicion.group(2).strip(),
                "horario": horario,
                "raw_text": crudo,
            }
        if intent in (INTENT_EJECUTAR, INTENT_RETOMAR, INTENT_CANCELAR):
            nombre = _RE_NOMBRE.search(crudo)
            return {"name": nombre.group(1).strip() if nombre else ""}
        return {}

    # ── Traducción de la frase a pasos ──────────────────────────────

    @staticmethod
    def resolver_accion(frase: str) -> Optional[str]:
        """Traduce una frase suelta al nombre de una acción del registro, o None.

        Tres intentos, del más seguro al menos: nombre exacto, sinónimo escrito a mano, y
        —solo si la coincidencia es ÚNICA— la descripción de la acción en el registro. Ese
        último paso es el que amplía el vocabulario sin adivinar: si dos acciones encajan,
        no se elige ninguna.
        """
        from agents.action_registry import ACTION_REGISTRY

        limpia = (frase or "").strip().lower()
        if not limpia:
            return None
        if limpia in ACTION_REGISTRY:
            return limpia

        for claves, accion in _SINONIMOS:
            if any(clave in limpia for clave in claves):
                return accion

        palabras = {p for p in re.findall(r"\w+", limpia) if len(p) > 3 and p not in _VACIAS}
        if not palabras:
            return None
        candidatas = [
            nombre for nombre, info in ACTION_REGISTRY.items()
            if palabras <= set(re.findall(r"\w+", str(info.get("desc", "")).lower()))
        ]
        return candidatas[0] if len(candidatas) == 1 else None

    @classmethod
    def interpretar_pasos(cls, cuerpo: str) -> Tuple[List[Any], List[str]]:
        """Return `(pasos, no_entendidos)` a partir del texto del usuario.

        Lo que no se reconoce NO se convierte en un paso "a ver si suena": se devuelve
        aparte para decírselo. Un flujo guardado con un paso adivinado es peor que un flujo
        que no se guardó.
        """
        pasos: List[Any] = []
        no_entendidos: List[str] = []

        for bloque in _RE_SEPARADOR_FUERTE.split(cuerpo or ""):
            bloque = bloque.strip(" .,;")
            if not bloque:
                continue

            condicion, resto = cls._extraer_condicion(bloque)
            if condicion is not None:
                # Un bloque condicional no se parte por comas: la coma de "si contiene X,
                # hacé Y" separa la condición de su acción, no dos pasos.
                cls._agregar(pasos, no_entendidos, resto, condicion)
                continue

            for trozo in _RE_SEPARADOR_DEBIL.split(bloque):
                if trozo.strip(" .,;"):
                    cls._agregar(pasos, no_entendidos, trozo, None)
        return pasos, no_entendidos

    @staticmethod
    def _extraer_condicion(bloque: str):
        """Return `(condicion, texto_de_la_accion)`, o `(None, bloque)` si no hay condición."""
        from core.flows import Condicion

        vacio = _RE_CONDICION_VACIO.match(bloque)
        if vacio:
            operador = "vacio" if vacio.group(1) else "no_vacio"
            return Condicion(operador=operador), vacio.group(2)

        contiene = _RE_CONDICION.match(bloque)
        if contiene:
            operador = "no_contiene" if contiene.group(1) else "contiene"
            return Condicion(operador=operador, valor=contiene.group(2).strip()), \
                contiene.group(3)
        return None, bloque

    @classmethod
    def _agregar(cls, pasos: List[Any], no_entendidos: List[str], frase: str,
                 condicion) -> None:
        from core.flows import Paso

        limpia = frase.strip(" .,;")
        if not limpia:
            return

        espera = _RE_ESPERA.search(limpia.lower())
        if espera:
            pasos.append(Paso(accion="wait_seconds",
                              params={"seconds": int(espera.group(1))},
                              condicion=condicion))
            return

        accion = cls.resolver_accion(limpia)
        if accion:
            pasos.append(Paso(accion=accion, condicion=condicion))
        else:
            no_entendidos.append(limpia)

    # ── Ejecución ───────────────────────────────────────────────────

    def execute(self, intent: str, params: Dict[str, Any]) -> str:
        if intent == INTENT_CREAR:
            return self._crear(params)
        if intent == INTENT_LISTAR:
            return self._listar(params)
        if intent == INTENT_CANCELAR:
            return self._cancelar(params)
        return self._ejecutar(params)   # EJECUTAR y RETOMAR son el mismo camino

    @staticmethod
    def _usuario(params: Dict[str, Any]) -> str:
        return str(params.get("user_id") or "default")

    def _crear(self, params: Dict[str, Any]) -> str:
        from core.address import vocative
        from core.flows import flow_store

        nombre = (params.get("name") or "").strip()
        cuerpo = (params.get("cuerpo") or "").strip()
        if not nombre or not cuerpo:
            return (
                f"No entendí el flujo{vocative()}. Probá con «aprendé el flujo modo "
                f"trabajo: abrí chrome, después el bloc de notas»."
            )

        pasos, no_entendidos = self.interpretar_pasos(cuerpo)
        if not pasos:
            return (
                f"No reconocí ningún paso de ese flujo{vocative()}. Los pasos tienen que "
                f"ser acciones que ya sepa hacer, separadas por comas o por «después»."
            )

        flujo = flow_store.crear(
            nombre, pasos, objetivo=cuerpo, user_id=self._usuario(params),
            horario=(params.get("horario") or ""),
        )
        if flujo is None:
            return f"No pude guardar el flujo{vocative()}."

        respuesta = (
            f"Listo{vocative()}. Guardé el flujo «{flujo.nombre}» con "
            f"{len(flujo.pasos)} paso(s):\n"
            + "\n".join(f"  {i}. {p.accion}" for i, p in enumerate(flujo.pasos, 1))
        )
        if flujo.horario:
            # Se programa AHORA, no al próximo arranque: `proactive_engine` acepta triggers
            # en caliente desde que su lista está protegida por un lock.
            from core.flows import programar

            if programar(flujo):
                respuesta += f"\n\nYa quedó programado: se va a ejecutar solo ({flujo.horario})."
            else:
                respuesta += (
                    f"\n\nGuardé el horario ({flujo.horario}) pero no pude activarlo ahora; "
                    f"va a empezar a dispararse la próxima vez que abras la app."
                )
        if no_entendidos:
            respuesta += (
                "\n\nEsto no lo entendí y lo dejé afuera: "
                + "; ".join(f"«{t}»" for t in no_entendidos)
            )
        return respuesta

    def _ejecutar(self, params: Dict[str, Any]) -> str:
        from core.address import vocative
        from core.flows import ejecutar, flow_store

        user_id = self._usuario(params)
        flujo = self._resolver(params, user_id)
        if flujo is None:
            return self._no_encontrado(params, user_id)

        resultado = ejecutar(flujo.id, canal=params.get("channel"), user_id=user_id)
        if resultado is None:
            return f"No pude ejecutar ese flujo{vocative()}."
        return resultado.resumen()

    def _cancelar(self, params: Dict[str, Any]) -> str:
        from core.address import vocative
        from core.flows import flow_store

        user_id = self._usuario(params)
        flujo = self._resolver(params, user_id)
        if flujo is None:
            return self._no_encontrado(params, user_id)
        if flow_store.cancelar(flujo.id, user_id):
            # También se da de baja el disparo automático: un flujo cancelado que sigue
            # despertándose cada hora sería exactamente lo que el usuario pidió evitar.
            from core.flows import desprogramar

            desprogramar(flujo.id)
            return f"Cancelé el flujo «{flujo.nombre}»{vocative()}."
        return f"El flujo «{flujo.nombre}» ya había terminado{vocative()}."

    def _listar(self, params: Dict[str, Any]) -> str:
        from core.address import vocative
        from core.flows import flow_store

        flujos = flow_store.listar(self._usuario(params))
        if not flujos:
            return (
                f"No tenés ningún flujo guardado todavía{vocative()}. Podés crear uno "
                f"diciendo «aprendé el flujo X: paso uno, después paso dos»."
            )
        return "\n\n".join(f.resumen() for f in flujos)

    @staticmethod
    def _resolver(params: Dict[str, Any], user_id: str):
        """Encuentra el flujo por nombre, o el único que haya quedado a medias."""
        from core.flows import flow_store

        nombre = (params.get("name") or "").strip()
        if nombre:
            return flow_store.buscar_por_nombre(nombre, user_id)
        pendientes = flow_store.reanudables(user_id)
        return pendientes[0] if len(pendientes) == 1 else None

    @staticmethod
    def _no_encontrado(params: Dict[str, Any], user_id: str) -> str:
        from core.address import vocative
        from core.flows import flow_store

        nombre = (params.get("name") or "").strip()
        disponibles = flow_store.listar(user_id)
        if not disponibles:
            return f"No tenés ningún flujo guardado{vocative()}."
        lista = ", ".join(f"«{f.nombre}»" for f in disponibles)
        if nombre:
            return f"No encontré un flujo llamado «{nombre}»{vocative()}. Tenés: {lista}."
        return f"¿Cuál de estos{vocative()}? {lista}."
