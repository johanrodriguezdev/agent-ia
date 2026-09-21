"""
tests/test_mejoras_escritorio.py
Las piezas nuevas del escritorio que NO son interfaz: cancelar un turno, avisar de algo que
pasó, ver la respuesta escribirse, renombrar y buscar conversaciones, y agrupar flujos y
módulos en un proyecto.

Los botones que las usan se prueban aparte, sobre la ventana real, en
`tests/test_webview_buttons.py`. Acá se prueba la lógica: qué pasa con un stop que llega
tarde, qué queda registrado, qué devuelve una búsqueda.

Ninguno de estos tests toca la base de datos real ni la configuración real: la memoria se
apunta a un archivo temporal y `config.json` se lee y escribe en `tmp_path`. Lo mismo vale
para el log — ver la última sección de este archivo.
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


# --------------------------------------------------------------------------- log de la suite

def test_el_log_se_puede_mandar_a_otro_archivo(monkeypatch, tmp_path):
    from core import logger_setup

    otro = tmp_path / "otro.log"
    monkeypatch.setenv(logger_setup.LOG_FILE_ENV, str(otro))
    assert logger_setup.log_file_path() == str(otro)


def test_sin_variable_el_log_va_al_de_la_aplicacion(monkeypatch):
    from core import logger_setup

    monkeypatch.delenv(logger_setup.LOG_FILE_ENV, raising=False)
    assert logger_setup.log_file_path() == logger_setup.LOG_FILE


def test_la_suite_no_escribe_en_el_log_de_la_aplicacion():
    """`tests/conftest.py` fija `ORION_LOG_FILE` antes de cualquier import. Si alguien lo
    saca, los tests vuelven a mezclarse con el log real y depurar un problema del usuario
    se convierte en arqueología: al investigar por qué el micrófono ignoró un comando
    (2026-09-03) aparecían errores de terminal y de wake word que eran de la propia suite.
    """
    import os

    from core import logger_setup

    destino = os.environ.get(logger_setup.LOG_FILE_ENV, "")
    assert destino, "conftest.py tiene que fijar ORION_LOG_FILE"
    assert destino != logger_setup.LOG_FILE
    assert destino.endswith("orion-tests.log")


# --------------------------------------------------------------------------- adjuntos

@pytest.fixture
def bridge_minimo(monkeypatch):
    """`Bridge` sin `QObject.__init__`: solo el estado que tocan estos caminos."""
    from unittest.mock import MagicMock

    from ui.webview.bridge import Bridge

    bridge = Bridge.__new__(Bridge)
    bridge._pending_attachments = []
    bridge._pending_user_text = ""
    bridge._resolution_in_flight = False
    bridge._turno_id = None
    bridge._turno_cancelado_id = None
    bridge._conversation_id = "c1"
    bridge.file_attached = MagicMock()
    bridge.attachment_preview = MagicMock()
    bridge.attachments_cleared = MagicMock()   # REQ-063
    bridge.notice_shown = MagicMock()
    return bridge


def test_adjuntar_un_archivo_lo_deja_listo_para_el_proximo_mensaje(bridge_minimo, tmp_path):
    """Antes la ruta se emitía hacia JS y ahí moría: se veía el nombre en un chip y el
    agente nunca se enteraba de que había un archivo."""
    from ui.webview.bridge import Bridge

    archivo = tmp_path / "informe.txt"
    archivo.write_text("contenido", encoding="utf-8")

    assert Bridge.attach_file(bridge_minimo, str(archivo)) is True
    assert bridge_minimo._pending_attachments == [str(archivo)]
    bridge_minimo.file_attached.emit.assert_called_once()


def test_un_archivo_rechazado_no_queda_pendiente(bridge_minimo, tmp_path):
    """La validación es la misma del drag&drop (`file_drop.validate_dropped_file`): lo que
    no pasa el filtro tampoco puede viajar con el mensaje."""
    from ui.webview.bridge import Bridge

    prohibido = tmp_path / "cosa.exe"
    prohibido.write_bytes(b"MZ")

    assert Bridge.attach_file(bridge_minimo, str(prohibido)) is False
    assert bridge_minimo._pending_attachments == []


def test_el_mensaje_lleva_la_ruta_completa_del_adjunto(bridge_minimo, tmp_path):
    from ui.webview.bridge import Bridge

    archivo = tmp_path / "informe.txt"
    archivo.write_text("contenido", encoding="utf-8")
    bridge_minimo._pending_attachments = [str(archivo)]

    texto, imagen = Bridge._con_adjunto(bridge_minimo, "resumime esto")

    assert "resumime esto" in texto
    assert str(archivo) in texto
    assert "[Archivo adjunto:" in texto
    assert imagen is None          # un .txt no es una imagen: el modelo no recibe nada que ver


def test_el_adjunto_viaja_una_sola_vez(bridge_minimo, tmp_path):
    """Adjuntar una vez y que se pegue a los diez mensajes siguientes sería peor que no
    adjuntar."""
    from ui.webview.bridge import Bridge

    archivo = tmp_path / "informe.txt"
    archivo.write_text("contenido", encoding="utf-8")
    bridge_minimo._pending_attachments = [str(archivo)]

    primero, _ = Bridge._con_adjunto(bridge_minimo, "uno")
    segundo, _ = Bridge._con_adjunto(bridge_minimo, "dos")

    assert str(archivo) in primero
    assert str(archivo) not in segundo
    assert segundo == "dos"


def test_un_adjunto_que_ya_no_existe_avisa_y_no_ensucia_el_mensaje(bridge_minimo, tmp_path):
    """El archivo se pudo mover o borrar entre adjuntarlo y mandar el mensaje: mejor
    decirlo que mandarle al agente una ruta que no lleva a nada."""
    from ui.webview.bridge import Bridge

    bridge_minimo._pending_attachments = [str(tmp_path / "no-esta.txt")]

    texto, imagen = Bridge._con_adjunto(bridge_minimo, "resumime esto")

    assert texto == "resumime esto"
    assert imagen is None
    bridge_minimo.notice_shown.emit.assert_called_once()
    assert bridge_minimo._pending_attachments == []


def test_una_imagen_adjunta_va_marcada_en_el_texto_y_vuelve_como_imagen_del_turno(bridge_minimo, tmp_path):
    """REQ-054: por Telegram el modelo VE la foto (`image_path`); en el escritorio solo le
    llegaba la ruta escrita. Ahora la imagen vuelve aparte para que `resolve()` la lleve
    hasta el modelo, y el texto la marca como «Imagen adjunta»."""
    from ui.webview.bridge import Bridge

    PIL = pytest.importorskip("PIL")
    from PIL import Image

    captura = tmp_path / "captura.png"
    Image.new("RGB", (8, 8), (255, 0, 0)).save(captura)
    bridge_minimo._pending_attachments = [str(captura)]

    texto, imagen = Bridge._con_adjunto(bridge_minimo, "¿qué dice esto?")

    assert imagen == str(captura)
    assert texto == f"¿qué dice esto?\n\n[Imagen adjunta: {captura}]"


def test_adjuntar_una_imagen_emite_su_miniatura_y_un_archivo_no(bridge_minimo, tmp_path):
    """REQ-054: el chip muestra la imagen que va a viajar; para un .txt no hay nada que
    mostrar y la señal va vacía (la página esconde el `<img>`)."""
    from ui.webview.bridge import Bridge

    PIL = pytest.importorskip("PIL")
    from PIL import Image

    captura = tmp_path / "captura.png"
    Image.new("RGB", (8, 8), (0, 0, 255)).save(captura)
    assert Bridge.attach_file(bridge_minimo, str(captura)) is True
    miniatura = bridge_minimo.attachment_preview.emit.call_args[0][1]
    assert miniatura.startswith("data:image/")

    bridge_minimo.attachment_preview.reset_mock()
    archivo = tmp_path / "notas.txt"
    archivo.write_text("hola", encoding="utf-8")
    assert Bridge.attach_file(bridge_minimo, str(archivo)) is True
    bridge_minimo.attachment_preview.emit.assert_called_once_with(str(archivo), "")


def test_sacar_el_chip_descarta_el_adjunto(bridge_minimo, tmp_path):
    from ui.webview.bridge import Bridge

    bridge_minimo._pending_attachments = [str(tmp_path / "algo.txt")]
    Bridge.clear_attachment(bridge_minimo)
    assert bridge_minimo._pending_attachments == []


def test_la_skill_de_archivos_entiende_una_ruta_absoluta():
    """El marcador que arma el bridge tiene que ser legible por el camino que de verdad
    abre el archivo. Antes ganaba el fallback que se quedaba solo con el nombre y después
    lo buscaba en el Escritorio y en Documentos: en cualquier otra carpeta, no aparecía."""
    from skills.file_analysis_skill import FileAnalysisSkill

    skill = FileAnalysisSkill()
    texto = "resumime esto\n\n[Archivo adjunto: C:\\Users\\yo\\informe.pdf]"
    assert skill.extract_params("FILE_ANALYSIS", texto)["filename"] == "C:\\Users\\yo\\informe.pdf"

    posix = "que dice el archivo /home/yo/notas.md"
    assert skill.extract_params("FILE_ANALYSIS", posix)["filename"] == "/home/yo/notas.md"


def test_la_skill_de_archivos_sigue_entendiendo_lo_de_siempre():
    """Sin ruta absoluta, el comportamiento no cambia."""
    from skills.file_analysis_skill import FileAnalysisSkill

    skill = FileAnalysisSkill()
    assert skill.extract_params(
        "FILE_ANALYSIS", "analiza el archivo reporte.csv")["filename"] == "reporte.csv"


# --------------------------------------------------------------------------- avisos que llegan

def test_lo_proactivo_sale_por_el_canal_de_avisos(monkeypatch):
    """El motor pensaba, gastaba una llamada al modelo, y la respuesta moría en un archivo
    de log que nadie mira."""
    import main

    recibidos = []
    notificaciones.register_notifier(lambda t, m, n: recibidos.append((t, m, n)))
    try:
        main._avisar_proactivo("Tenés tres correos sin leer")
    finally:
        notificaciones.clear_notifier()

    assert len(recibidos) == 1
    assert "tres correos" in recibidos[0][1]


def test_un_aviso_proactivo_vacio_no_molesta_a_nadie():
    import main

    recibidos = []
    notificaciones.register_notifier(lambda t, m, n: recibidos.append(t))
    try:
        main._avisar_proactivo("")
    finally:
        notificaciones.clear_notifier()

    assert recibidos == []


def test_el_recordatorio_usa_la_ventana_y_no_levanta_powershell(monkeypatch):
    """Con la aplicación abierta, el globo de Windows era un segundo aviso para lo mismo —
    y levantar PowerShell para dibujarlo, el camino más caro de todos."""
    import subprocess

    from tasks.task_scheduler import TaskScheduler

    monkeypatch.setattr("ui.tts_engine.speak", lambda *a, **k: None, raising=False)

    corridos = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: corridos.append(a))

    avisos = []
    notificaciones.register_notifier(lambda t, m, n: avisos.append((t, m)))
    try:
        TaskScheduler._notify_local(TaskScheduler(), "llamar al contador", 7)
    finally:
        notificaciones.clear_notifier()

    assert avisos and avisos[0][1] == "llamar al contador"
    assert corridos == [], "con la ventana escuchando, el globo del sistema sobra"


def test_sin_ventana_el_recordatorio_cae_al_globo_de_windows(monkeypatch):
    """Sin aplicación de escritorio (solo bots, o la ventana cerrada) el recordatorio tiene
    que seguir llegando: para eso queda el camino viejo."""
    import subprocess

    from tasks.task_scheduler import TaskScheduler

    monkeypatch.setattr("ui.tts_engine.speak", lambda *a, **k: None, raising=False)

    corridos = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: corridos.append(a))
    notificaciones.clear_notifier()

    TaskScheduler._notify_local(TaskScheduler(), "llamar al contador", 7)

    assert len(corridos) == 1


# --------------------------------------------------------------------------- arranque

def test_el_modelo_semantico_se_carga_del_cache_sin_tocar_la_red(monkeypatch):
    """45 segundos y ~20 peticiones a huggingface.co en cada arranque, con el modelo ya
    descargado (medido en el log del 2026-09-03). Sin conexión, además, se queda esperando
    a que expiren los timeouts."""
    import ai.embedding_engine as engine

    llamadas = []

    class _ModeloFalso:
        def __init__(self, nombre, device=None, local_files_only=False):
            llamadas.append(local_files_only)

    monkeypatch.setattr(engine, "SentenceTransformer", _ModeloFalso)
    monkeypatch.setattr(engine, "_model", None)

    engine.get_model()

    assert llamadas == [True], "el primer intento tiene que ser sin red"


def test_si_no_esta_en_cache_se_descarga_igual(monkeypatch):
    """La primera vez de todas no hay caché: ahí tiene que caer a la descarga normal, que
    es exactamente lo que hacía antes."""
    import ai.embedding_engine as engine

    llamadas = []

    class _ModeloFalso:
        def __init__(self, nombre, device=None, local_files_only=False):
            llamadas.append(local_files_only)
            if local_files_only:
                raise OSError("no está en el caché")

    monkeypatch.setattr(engine, "SentenceTransformer", _ModeloFalso)
    monkeypatch.setattr(engine, "_model", None)

    engine.get_model()

    assert llamadas == [True, False]


# --------------------------------------------------------------------------- modelo por tarea

@pytest.fixture
def bridge_modelos(monkeypatch, tmp_path):
    """Bridge minimo + un config.json temporal: nunca se toca el real."""
    from unittest.mock import MagicMock

    import config_manager
    from ui.webview.bridge import Bridge

    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(tmp_path / "config.json"))

    bridge = Bridge.__new__(Bridge)
    bridge.notice_shown = MagicMock()
    bridge.task_models_loaded = MagicMock()
    return bridge


def _guardado(bridge):
    """El JSON que el bridge le mando a la pantalla en la ultima emision."""
    return json.loads(bridge.task_models_loaded.emit.call_args[0][0])


def test_el_catalogo_ofrece_modelos_gratuitos_con_herramientas():
    """Los `:free` de OpenRouter son la razon de ser de todo esto, y el agente necesita
    tool-calling: un catalogo sin gratuitos no serviria para lo que se pidio."""
    import ui.webview.bridge as bridge_module

    catalogo = bridge_module._build_task_models_payload()["catalogo"]
    gratuitos = [m for m in catalogo if m["gratis"]]

    assert len(gratuitos) >= 10
    assert all(m["modelo"].endswith(":free") for m in gratuitos)
    assert any(m["proveedor"] == "openrouter" for m in gratuitos)


def test_las_tareas_ofrecidas_son_las_que_el_codigo_etiqueta():
    """Ofrecer una tarea que ningun `generate_response()` nombra seria una perilla que no
    hace nada: se configura, se guarda, y no cambia el comportamiento."""
    from pathlib import Path

    import ui.webview.bridge as bridge_module

    raiz = Path(__file__).resolve().parent.parent
    fuentes = "\n".join(
        p.read_text(encoding="utf-8")
        for p in raiz.rglob("*.py")
        if "openclaw-main" not in p.parts and "tests" not in p.parts
    )
    for tarea in bridge_module._TAREAS_ENRUTABLES:
        # «vision» (REQ-061) no es una `tarea=` de `generate_response()`: la consulta
        # `_destinos_iniciales` cuando hay una imagen, por `destinos_de_tarea("vision")`.
        usada = (f'tarea="{tarea["id"]}"' in fuentes
                 or f'destinos_de_tarea("{tarea["id"]}")' in fuentes)
        assert usada, (
            f"la tarea '{tarea['id']}' se ofrece en la pantalla pero ningun "
            f"generate_response() la usa"
        )


def test_elegir_un_modelo_para_una_tarea_lo_deja_escrito(bridge_modelos):
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(
        bridge_modelos, "codigo",
        json.dumps([{"proveedor": "openrouter", "modelo": "cohere/north-mini-code:free"}]),
    )

    assert config_manager.get_task_providers()["codigo"] == {
        "proveedor": "openrouter", "modelo": "cohere/north-mini-code:free",
    }


def test_varios_modelos_se_guardan_en_orden(bridge_modelos):
    """El orden ES la configuracion: es el que se prueba cuando el anterior se queda sin
    cuota."""
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "ligera", json.dumps([
        {"proveedor": "openrouter", "modelo": "google/gemma-4-31b-it:free"},
        {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
    ]))

    guardado = config_manager.get_task_providers()["ligera"]
    assert [d["modelo"] for d in guardado] == [
        "google/gemma-4-31b-it:free", "z-ai/glm-5.2:free",
    ]


def test_una_lista_vacia_devuelve_la_tarea_al_modelo_general(bridge_modelos):
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "codigo", json.dumps(
        [{"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"}]))
    Bridge.save_task_models(bridge_modelos, "codigo", "[]")

    assert "codigo" not in config_manager.get_task_providers()


def test_un_modelo_fuera_del_catalogo_no_se_escribe(bridge_modelos):
    """Los slots del bridge son invocables desde cualquier script de la pagina: lo que
    llega NO decide que se escribe en config.json."""
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "codigo", json.dumps(
        [{"proveedor": "openrouter", "modelo": "modelo/inventado:free"}]))

    assert config_manager.get_task_providers() == {}
    bridge_modelos.notice_shown.emit.assert_called()


def test_una_tarea_inventada_no_se_escribe(bridge_modelos):
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "loquesea", json.dumps(
        [{"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"}]))

    assert config_manager.get_task_providers() == {}


def test_un_json_roto_no_rompe_nada(bridge_modelos):
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "codigo", "{esto no es json")

    assert config_manager.get_task_providers() == {}
    bridge_modelos.notice_shown.emit.assert_called()


def test_un_modelo_repetido_se_guarda_una_sola_vez(bridge_modelos):
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "ligera", json.dumps([
        {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
        {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
    ]))

    guardado = config_manager.get_task_providers()["ligera"]
    assert guardado == {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"}


def test_lo_guardado_vuelve_a_la_pantalla(bridge_modelos):
    """Lo que se guarda tiene que verse reflejado sin recargar nada."""
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "codigo", json.dumps(
        [{"proveedor": "openrouter", "modelo": "poolside/laguna-s-2.1:free"}]))

    payload = _guardado(bridge_modelos)
    codigo = next(t for t in payload["tareas"] if t["id"] == "codigo")
    assert [d["modelo"] for d in codigo["destinos"]] == ["poolside/laguna-s-2.1:free"]
    assert codigo["destinos"][0]["gratis"] is True


def test_un_modelo_que_salio_del_catalogo_se_puede_quitar(bridge_modelos):
    """Los IDs `:free` de OpenRouter entran y salen del catalogo. Si uno guardado deja de
    figurar, la tarea NO puede quedar congelada: hay que poder sacarlo y reordenar lo que
    queda, o la pantalla rechaza cada intento por culpa del modelo que se quiere sacar."""
    import config_manager
    from ui.webview.bridge import Bridge

    # Estado previo escrito a mano, con un modelo que el catalogo de hoy no conoce.
    config_manager.set_task_providers({"ligera": [
        {"proveedor": "openrouter", "modelo": "modelo/retirado:free"},
        {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
    ]})

    # Quitar el retirado: el que queda tampoco esta en el catalogo... pero ya estaba escrito.
    Bridge.save_task_models(bridge_modelos, "ligera", json.dumps(
        [{"proveedor": "openrouter", "modelo": "modelo/retirado:free"}]))
    assert config_manager.get_task_providers()["ligera"] == {
        "proveedor": "openrouter", "modelo": "modelo/retirado:free",
    }

    # Y sigue sin poder inventarse uno nuevo fuera del catalogo.
    Bridge.save_task_models(bridge_modelos, "ligera", json.dumps(
        [{"proveedor": "openrouter", "modelo": "modelo/jamas-visto:free"}]))
    assert config_manager.get_task_providers()["ligera"] == {
        "proveedor": "openrouter", "modelo": "modelo/retirado:free",
    }


def test_una_clave_vacia_en_config_no_pisa_la_del_entorno(monkeypatch, tmp_path):
    """El estado de una instalacion recien clonada: config.json trae la clave presente
    pero vacia. Si eso pisa la variable de entorno, el proveedor se queda sin credencial y
    el error que se ve ("no esta configurada") contradice lo que el humano si configuro."""
    import config_manager

    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"openai_api_key": "", "gemini_api_key": ""}), encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", str(ruta))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-del-entorno")
    monkeypatch.setenv("GEMINI_API_KEY", "gm-del-entorno")

    assert config_manager.get_api_key("openai") == "sk-del-entorno"
    assert config_manager.get_api_key("gemini") == "gm-del-entorno"

    # Y lo que si esta escrito en config.json manda cuando no hay variable de entorno.
    ruta.write_text(json.dumps({"openrouter_api_key": "sk-or-de-config"}), encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert config_manager.get_api_key("openrouter") == "sk-or-de-config"

    # Ollama es local: no lleva credencial y no debe inventarse ninguna.
    assert config_manager.get_api_key("ollama") == ""


def test_elegir_un_modelo_sin_clave_lo_avisa_en_la_pantalla(bridge_modelos, monkeypatch):
    """Sin esto, configurar OpenRouter sin clave se ve como un cambio exitoso y el error
    aparece mucho despues, en medio de una respuesta, sin relacion visible con lo tocado."""
    import config_manager
    from ui.webview.bridge import Bridge

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    Bridge.save_task_models(bridge_modelos, "ligera", json.dumps(
        [{"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"}]))

    avisos = _guardado(bridge_modelos)["avisos"]
    assert any("OPENROUTER_API_KEY" in a for a in avisos), avisos

    # Con la clave puesta, el aviso desaparece: no se le insiste al humano por algo hecho.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-de-prueba")
    Bridge.request_task_models(bridge_modelos)
    assert _guardado(bridge_modelos)["avisos"] == []


def test_lo_que_se_guarda_es_lo_que_el_proveedor_lee(bridge_modelos):
    """La prueba que cierra el circulo: lo escrito por la pantalla tiene que ser
    exactamente lo que `ai/llm_provider.py` entiende como destinos de esa tarea."""
    import ai.llm_provider as prov
    import config_manager
    from ui.webview.bridge import Bridge

    Bridge.save_task_models(bridge_modelos, "ligera", json.dumps([
        {"proveedor": "openrouter", "modelo": "google/gemma-4-31b-it:free"},
        {"proveedor": "openrouter", "modelo": "z-ai/glm-5.2:free"},
    ]))

    # Sin trucos: la pantalla escribe y el proveedor lee el MISMO archivo, el que dice
    # `config_manager.CONFIG_FILE` (aqui, el temporal del fixture).
    assert config_manager.get_task_providers()["ligera"]
    assert prov.destinos_de_tarea("ligera") == [
        ("openrouter", "google/gemma-4-31b-it:free"),
        ("openrouter", "z-ai/glm-5.2:free"),
    ]
