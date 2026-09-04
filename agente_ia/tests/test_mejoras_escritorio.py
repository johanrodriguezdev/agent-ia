"""
tests/test_mejoras_escritorio.py
Las piezas nuevas del escritorio que NO son interfaz: cancelar un turno, avisar de algo que
pasó, ver la respuesta escribirse, renombrar y buscar conversaciones, y agrupar flujos y
módulos en un proyecto.

Los botones que las usan se prueban aparte, sobre la ventana real, en
`tests/test_webview_buttons.py`. Acá se prueba la lógica: qué pasa con un stop que llega
tarde, qué queda registrado, qué devuelve una búsqueda.

Ninguno de estos tests toca la base de datos real ni la configuración real: la memoria se
apunta a un archivo temporal y `config.json` se lee y escribe en `tmp_path`.
"""

import json

import pytest

from core import notificaciones, streaming
from core.cancelacion import (
    TurnoCancelado,
    abortar_si_cancelado,
    cancelar,
    cerrar_turno,
    esta_cancelado,
    nuevo_turno,
)


@pytest.fixture(autouse=True)
def turno_limpio():
    """Ningún test hereda un turno cancelado del anterior."""
    cerrar_turno()
    yield
    cerrar_turno()


# --------------------------------------------------------------------------- cancelar

def test_sin_turno_abierto_no_hay_nada_que_cancelar():
    assert cancelar() is False
    assert esta_cancelado() is False


def test_cancelar_el_turno_en_curso():
    turno = nuevo_turno()
    assert esta_cancelado() is False
    assert cancelar(turno) is True
    assert esta_cancelado() is True


def test_un_stop_que_llega_tarde_no_se_lleva_puesto_el_turno_siguiente():
    """El caso que motiva los identificadores: se cancela un turno, se empieza otro, y el
    stop del primero llega con retraso. Sin identificador, cancelaría el nuevo."""
    viejo = nuevo_turno()
    cerrar_turno(viejo)
    nuevo = nuevo_turno()

    assert cancelar(viejo) is False
    assert esta_cancelado() is False
    assert cancelar(nuevo) is True


def test_cerrar_el_turno_limpia_la_cancelacion():
    """Sin esto, una cancelación quedaría pegada y el turno siguiente arrancaría creyéndose
    cancelado antes de empezar."""
    turno = nuevo_turno()
    cancelar(turno)
    cerrar_turno(turno)
    assert esta_cancelado() is False

    otro = nuevo_turno()
    assert esta_cancelado() is False
    cerrar_turno(otro)


def test_cerrar_un_turno_ajeno_no_hace_nada():
    turno = nuevo_turno()
    cancelar(turno)
    cerrar_turno(turno - 1)          # otro turno, no el actual
    assert esta_cancelado() is True


def test_el_punto_de_control_aborta_solo_si_se_cancelo():
    turno = nuevo_turno()
    abortar_si_cancelado("prueba")   # no lanza: nadie canceló
    cancelar(turno)
    with pytest.raises(TurnoCancelado):
        abortar_si_cancelado("prueba")


def test_resolve_y_el_loop_de_razonamiento_tienen_punto_de_corte():
    """El botón de detener solo sirve si alguien pregunta. Se verifica que los dos caminos
    largos —elegir resolver y pensar con herramientas— consulten la cancelación."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    for modulo in ("core/resolution.py", "core/reasoning_loop.py"):
        fuente = (raiz / modulo).read_text(encoding="utf-8")
        assert "abortar_si_cancelado(" in fuente, f"{modulo} no consulta la cancelación"


def test_un_turno_cancelado_no_se_muestra_como_error():
    """`resolve()` termina levantando `TurnoCancelado` desde el punto de corte y eso llega
    al bridge como cualquier otro fallo. Pintarlo como "Error: ..." seria acusar al agente
    de romperse por haber obedecido."""
    from unittest.mock import MagicMock

    from ui.webview.bridge import Bridge

    bridge = Bridge.__new__(Bridge)
    bridge._pending_user_text = "hola"
    bridge._resolution_in_flight = True
    bridge._turno_id = 7
    bridge._turno_cancelado_id = 7
    bridge._stop_progress = lambda: None
    bridge.message_appended = MagicMock()
    bridge.typing_stopped = MagicMock()
    bridge._open_conversation_window = MagicMock()

    Bridge._on_resolve_error(bridge, "reasoning_loop, vuelta 2")

    bridge.message_appended.emit.assert_not_called()
    assert bridge._resolution_in_flight is False


# --------------------------------------------------------------------------- avisos

def test_sin_destinatario_el_aviso_no_revienta():
    notificaciones.clear_notifier()
    notificaciones.notificar("algo pasó", "detalle")     # no lanza


def test_el_aviso_llega_con_su_nivel():
    recibidos = []
    notificaciones.register_notifier(lambda t, m, n: recibidos.append((t, m, n)))
    notificaciones.notificar("Flujo fallado", "el paso 2", "error")
    notificaciones.clear_notifier()
    assert recibidos == [("Flujo fallado", "el paso 2", "error")]


def test_un_nivel_inventado_cae_en_info():
    recibidos = []
    notificaciones.register_notifier(lambda t, m, n: recibidos.append(n))
    notificaciones.notificar("hola", "", "catastrofico")
    notificaciones.clear_notifier()
    assert recibidos == ["info"]


def test_un_aviso_sin_titulo_no_se_manda():
    recibidos = []
    notificaciones.register_notifier(lambda t, m, n: recibidos.append(t))
    notificaciones.notificar("", "cuerpo sin titulo")
    notificaciones.clear_notifier()
    assert recibidos == []


def test_si_el_notificador_falla_no_tumba_lo_que_se_estaba_haciendo():
    """Avisar de un flujo terminado no puede romper el flujo."""
    def _explota(titulo, mensaje, nivel):
        raise RuntimeError("la bandeja no está")

    notificaciones.register_notifier(_explota)
    notificaciones.notificar("algo", "pasó")     # no lanza
    notificaciones.clear_notifier()


def test_los_flujos_avisan_cuando_fallan():
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent / "core" / "flows.py").read_text(encoding="utf-8")
    assert "notificar(" in fuente, "un flujo que falla de madrugada tiene que avisar"


# --------------------------------------------------------------------------- streaming

def test_sin_sumidero_no_se_pide_streaming():
    streaming.clear_sink()
    assert streaming.hay_sink() is False
    streaming.emitir("algo")     # no lanza, no hace nada


def test_los_pedazos_llegan_en_orden():
    pedazos = []
    streaming.register_sink(pedazos.append)
    for texto in ("Hola", " ", "mundo"):
        streaming.emitir(texto)
    streaming.clear_sink()
    assert "".join(pedazos) == "Hola mundo"


def test_un_pedazo_vacio_no_se_emite():
    pedazos = []
    streaming.register_sink(pedazos.append)
    streaming.emitir("")
    streaming.clear_sink()
    assert pedazos == []


def test_si_la_pantalla_falla_la_respuesta_sigue():
    """Un fallo pintando la respuesta no puede tumbar la respuesta."""
    def _explota(_pedazo):
        raise RuntimeError("la ventana se cerró")

    streaming.register_sink(_explota)
    streaming.emitir("hola")     # no lanza
    streaming.clear_sink()


def test_sin_permiso_no_se_transmite_aunque_haya_sumidero():
    """Durante un turno el sistema le habla al modelo por cosas que NO son la respuesta
    (resumir la memoria, reescribir una repregunta, leer una captura). Ese texto no puede
    aparecer en la burbuja del chat."""
    streaming.register_sink(lambda _p: None)
    assert streaming.hay_sink() is False      # sin permiso, no se transmite
    with streaming.permitido():
        assert streaming.hay_sink() is True
    assert streaming.hay_sink() is False      # el permiso no se queda pegado
    streaming.clear_sink()


def test_el_permiso_no_alcanza_sin_sumidero():
    streaming.clear_sink()
    with streaming.permitido():
        assert streaming.hay_sink() is False


def test_los_dos_caminos_conversacionales_piden_permiso():
    """Si alguien saca el `with streaming.permitido()`, el streaming deja de funcionar en
    silencio (o peor, empieza a transmitir lo que no debe)."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    for modulo in ("core/reasoning_loop.py", "ai/claude_brain.py"):
        fuente = (raiz / modulo).read_text(encoding="utf-8")
        assert "streaming.permitido()" in fuente, f"{modulo} no marca su llamada al modelo"


def test_el_proveedor_reensambla_una_tool_call_partida_en_pedazos():
    """Con streaming, las llamadas a herramientas llegan partidas: el nombre en un delta y
    los argumentos de a cachos de JSON. Si se reensamblan mal, el agente pierde la
    herramienta y contesta cualquier cosa."""
    import types as _types

    import ai.llm_provider as lp

    class _ClienteFalso:
        def __init__(self, chunks):
            self._chunks = chunks

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            assert kwargs.get("stream") is True
            return iter(self._chunks)

    def _chunk(content=None, tool_calls=None):
        delta = _types.SimpleNamespace(content=content, tool_calls=tool_calls)
        return _types.SimpleNamespace(choices=[_types.SimpleNamespace(delta=delta)])

    def _tc(index, id=None, name=None, args=None):
        return _types.SimpleNamespace(
            index=index, id=id, function=_types.SimpleNamespace(name=name, arguments=args),
        )

    pedazos = []
    streaming.register_sink(pedazos.append)
    cliente = _ClienteFalso([
        _chunk("dejame ver"),
        _chunk(None, [_tc(0, id="c1", name="task_list", args='{"user')]),
        _chunk(None, [_tc(0, args='_id": "yo"}')]),
    ])
    texto, llamadas = lp._llamada_en_streaming(cliente, "modelo", [], [{"x": 1}])
    streaming.clear_sink()

    assert texto == "dejame ver"
    assert pedazos == ["dejame ver"]
    assert llamadas[0].name == "task_list"
    assert llamadas[0].arguments == {"user_id": "yo"}


def test_una_tool_call_con_json_roto_no_revienta():
    import types as _types

    import ai.llm_provider as lp

    class _ClienteFalso:
        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            delta = _types.SimpleNamespace(content=None, tool_calls=[
                _types.SimpleNamespace(
                    index=0, id="c1",
                    function=_types.SimpleNamespace(name="task_list", arguments="{roto"),
                ),
            ])
            return iter([_types.SimpleNamespace(
                choices=[_types.SimpleNamespace(delta=delta)])])

    _texto, llamadas = lp._llamada_en_streaming(_ClienteFalso(), "modelo", [], [{"x": 1}])
    assert llamadas[0].arguments == {}


# --------------------------------------------------------------------------- memoria

@pytest.fixture
def memoria(tmp_path, monkeypatch):
    """Memoria contra una base temporal: nunca la real."""
    import ai.memory_manager as mm

    import numpy as np

    monkeypatch.setattr(mm, "DB_PATH", str(tmp_path / "memoria.db"))
    # Sin esto, cada `store()` carga el modelo de embeddings: dos minutos de test para algo
    # que no tiene nada que ver con lo que se esta probando (.claude/rules/testing.md).
    monkeypatch.setattr(mm.UnifiedMemory, "_get_embedding",
                        lambda self, texto: np.zeros(8, dtype=np.float32))
    instancia = mm.UnifiedMemory.__new__(mm.UnifiedMemory)
    instancia._embeddings = []
    instancia._embedding_ids = []
    instancia._embedding_user_ids = []
    instancia._init_db()
    return instancia


def _con_charla(memoria, textos=("como configuro el certificado ssl", "se hace con certbot")):
    import ai.memory_manager as mm

    cid = mm.UnifiedMemory.new_conversation_id()
    memoria.store(textos[0], conversation_id=cid, role="user", category="interaction")
    memoria.store(textos[1], conversation_id=cid, role="assistant", category="interaction")
    return cid


def test_renombrar_gana_sobre_el_titulo_derivado(memoria):
    cid = _con_charla(memoria)
    assert memoria.list_conversations()[0].title.startswith("como configuro")

    assert memoria.rename_conversation(cid, "  Certificados  del server ") is True
    assert memoria.list_conversations()[0].title == "Certificados del server"


def test_renombrar_con_vacio_vuelve_al_derivado(memoria):
    cid = _con_charla(memoria)
    memoria.rename_conversation(cid, "Otro nombre")
    memoria.rename_conversation(cid, "")
    assert memoria.list_conversations()[0].title.startswith("como configuro")


def test_no_se_puede_renombrar_una_conversacion_ajena(memoria):
    cid = _con_charla(memoria)
    assert memoria.rename_conversation(cid, "mia", user_id="otro") is False
    assert memoria.rename_conversation("no-existe", "mia") is False


def test_buscar_encuentra_dentro_de_lo_dicho(memoria):
    """Lo que el filtro de títulos no puede: la palabra está en la respuesta, no en el
    título."""
    _con_charla(memoria)
    resultados = memoria.search_conversations("certbot")
    assert len(resultados) == 1
    assert "certbot" in resultados[0]["snippet"]
    assert resultados[0]["title"].startswith("como configuro")


def test_buscar_no_distingue_mayusculas(memoria):
    _con_charla(memoria)
    assert memoria.search_conversations("CERTBOT")
    assert memoria.search_conversations("CertBot")


def test_buscar_con_una_letra_no_devuelve_media_base(memoria):
    _con_charla(memoria)
    assert memoria.search_conversations("a") == []
    assert memoria.search_conversations("") == []


def test_el_fragmento_recorta_alrededor_de_la_coincidencia(memoria):
    largo = "bla " * 60 + "certificado vencido" + " bla" * 60
    _con_charla(memoria, textos=("pregunta", largo))
    fragmento = memoria.search_conversations("certificado vencido")[0]["snippet"]
    assert "certificado vencido" in fragmento
    assert len(fragmento) < 200
    assert fragmento.startswith("…") and fragmento.endswith("…")


def test_buscar_respeta_el_titulo_propio(memoria):
    cid = _con_charla(memoria)
    memoria.rename_conversation(cid, "Servidor de producción")
    assert memoria.search_conversations("certbot")[0]["title"] == "Servidor de producción"


# --------------------------------------------------------------------------- proyectos

def test_un_flujo_y_un_modulo_viven_en_un_proyecto(memoria):
    pid = memoria.create_project(name="Servidor")
    assert memoria.assign_item_to_project("flujo", "7", pid, label="modo trabajo") is True
    assert memoria.assign_item_to_project("modulo", "terminal", pid, label="Terminal") is True

    items = memoria.list_items_by_project(pid)
    assert {i["kind"] for i in items} == {"flujo", "modulo"}
    assert memoria.project_of_item("flujo", "7") == pid


def test_un_elemento_vive_en_un_solo_proyecto(memoria):
    """Reasignar es mover, no duplicar — mismo criterio que las conversaciones."""
    primero = memoria.create_project(name="Uno")
    segundo = memoria.create_project(name="Dos")
    memoria.assign_item_to_project("flujo", "7", primero, label="modo trabajo")
    memoria.assign_item_to_project("flujo", "7", segundo, label="modo trabajo")

    assert memoria.list_items_by_project(primero) == []
    assert memoria.project_of_item("flujo", "7") == segundo


def test_no_se_puede_asignar_a_un_proyecto_que_no_existe(memoria):
    assert memoria.assign_item_to_project("flujo", "7", 999) is False


def test_no_se_puede_asignar_al_proyecto_de_otro(memoria):
    """`project_id` es un entero chico y adivinable: se verifica el dueño, igual que en
    `assign_conversation_to_project()`."""
    pid = memoria.create_project(name="Mio")
    assert memoria.assign_item_to_project("flujo", "7", pid, user_id="otro") is False


def test_desasignar_es_idempotente(memoria):
    pid = memoria.create_project(name="Servidor")
    memoria.assign_item_to_project("flujo", "7", pid)
    assert memoria.unassign_item_from_project("flujo", "7") is True
    assert memoria.unassign_item_from_project("flujo", "7") is False


def test_borrar_el_proyecto_se_lleva_sus_elementos_pero_no_los_flujos(memoria):
    """Igual que con las conversaciones (CA-18/CA-19): el agrupador se borra, lo agrupado
    sigue existiendo — son tablas separadas, no una condición en el código."""
    pid = memoria.create_project(name="Servidor")
    memoria.assign_item_to_project("flujo", "7", pid)
    assert memoria.delete_project(pid) is True
    assert memoria.list_items_by_project(pid) == []
    assert memoria.project_of_item("flujo", "7") is None


def test_el_catalogo_de_asignables_no_se_cae_sin_flujos(monkeypatch):
    """La pantalla tiene que servir para módulos aunque el almacén de flujos falle."""
    import ui.webview.bridge as bridge

    payload = bridge._build_assignable_payload()
    assert payload["modulos"], "el catálogo de módulos no puede estar vacío"
    assert isinstance(payload["flujos"], list)


# --------------------------------------------------------------------------- configuración

def test_la_geometria_de_ventana_va_y_vuelve(tmp_path, monkeypatch):
    import config_manager

    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    assert config_manager.get_window_geometry() == {}

    config_manager.set_window_geometry(1200, 800, 40, 30, maximized=True)
    guardada = config_manager.get_window_geometry()
    assert guardada == {"width": 1200, "height": 800, "x": 40, "y": 30, "maximized": True}


def test_una_geometria_corrupta_se_ignora(tmp_path, monkeypatch):
    """Un valor roto no puede impedir que la app abra: se vuelve al cálculo normal."""
    import config_manager

    ruta = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(ruta))
    ruta.write_text(json.dumps({"window_geometry": {"width": "ancho"}}), encoding="utf-8")
    assert config_manager.get_window_geometry() == {}


def test_una_ventana_ridiculamente_chica_se_ignora(tmp_path, monkeypatch):
    import config_manager

    ruta = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(ruta))
    ruta.write_text(json.dumps({"window_geometry": {
        "width": 10, "height": 10, "x": 0, "y": 0}}), encoding="utf-8")
    assert config_manager.get_window_geometry() == {}


def test_el_proveedor_y_el_modelo_se_guardan_juntos(tmp_path, monkeypatch):
    """Dejar el proveedor nuevo con el modelo del anterior es la forma más fácil de pedirle
    a DeepSeek un modelo de Anthropic y ver un 404 sin explicación."""
    import config_manager

    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))
    config_manager.set_ai_provider_and_model("anthropic", "claude-3-5-haiku-20241022")
    assert config_manager.get_ai_provider() == "anthropic"
    assert config_manager.get_ai_model() == "claude-3-5-haiku-20241022"


def test_la_configuracion_se_guarda_legible(tmp_path, monkeypatch):
    """Los acentos se escribían como \\u00f1 y el archivo dejaba de ser legible para quien
    lo abre a mano."""
    import config_manager

    ruta = tmp_path / "config.json"
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(ruta))
    config_manager.save_config({"display_name": "Johan Peña"})
    assert "Peña" in ruta.read_text(encoding="utf-8")


def test_el_catalogo_de_modelos_no_acepta_cualquier_cosa():
    """`set_model()` valida contra el catálogo: los slots del bridge son invocables desde
    cualquier script de la página, y sin la lista cerrada se podría escribir cualquier cosa
    en config.json."""
    import ui.webview.bridge as bridge

    assert "deepseek" in bridge._MODELOS_CONOCIDOS
    for datos in bridge._MODELOS_CONOCIDOS.values():
        assert datos["modelos"], "un proveedor sin modelos no se puede elegir"
        assert datos["label"]
