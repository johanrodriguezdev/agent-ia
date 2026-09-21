"""
tests/test_webview_bridge.py
REQ-015/CA-07..CA-11, CA-20..CA-25, CA-39, CA-40, CA-42 — `ui/webview/bridge.py::Bridge`.

`pytest-qt` instancia un `Bridge` (QObject headless, sin `QWebEngineView` real) con
`memory`/`execute_action`/`resolve`/`security_manager` mockeados. `run_async()` se
reemplaza por una versión síncrona (`fake_run_async`): ejecuta `fn()` en el mismo hilo y
llama `on_done`/`on_error` de inmediato — sin `QThreadPool` real, determinístico.

Verifica que cada slot llama exactamente a la función esperada con los parámetros
esperados, que `run_chip_action` nunca ejecuta la acción "directo" (siempre vía
`execute_action()`), y que `toggle_wake_word` nunca arranca un `QRunnable` real (evita
tocar `sr.Microphone()`, `.claude/rules/testing.md`).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import ui.webview.bridge as bridge_module
from ui.webview.bridge import Bridge
from ui.webview.wake_word_worker import WakeWordWorker


@pytest.fixture
def fake_run_async(monkeypatch):
    """`run_async(fn, on_done, on_error, *args, **kwargs)` síncrono, sin `QThreadPool`."""
    calls = []

    def _fake_run_async(fn, on_done=None, on_error=None, *args, **kwargs):
        calls.append({"fn": fn, "args": args, "kwargs": kwargs})
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # pragma: no cover - camino defensivo
            if on_error:
                on_error(str(e))
            return None
        if on_done:
            on_done(result)
        return result

    monkeypatch.setattr(bridge_module, "run_async", _fake_run_async)
    return calls


@pytest.fixture
def no_real_threadpool(monkeypatch):
    """Evita que `toggle_wake_word(True)` arranque un `QRunnable` real (tocaría
    `sr.Microphone()`) — mismo patrón que `tests/test_wake_word_gui.py` (REQ-009)."""
    started = []
    fake_pool = MagicMock()
    fake_pool.start = lambda worker: started.append(worker)
    monkeypatch.setattr(bridge_module.QThreadPool, "globalInstance", staticmethod(lambda: fake_pool))
    return started


@pytest.fixture(autouse=True)
def resolve_falso(monkeypatch):
    """`core.resolution.resolve` de mentira para TODO este archivo.

    Con `fake_run_async` síncrono, cada `send_message()`/`regenerate_last()` de estos tests
    llamaba al `resolve()` real —o sea, al modelo por red— salvo que el test lo stubeara a
    mano: 32 llamadas y solo 9 stubs, entre 5 y 60 s cada una. Un test que necesite otra
    respuesta sigue pudiendo `monkeypatch.setattr("core.resolution.resolve", ...)`: el suyo
    corre después y gana. Se llama `resolve` porque varios tests buscan la llamada por
    `fn.__name__`.
    """
    def resolve(*args, **kwargs):
        return SimpleNamespace(text="respuesta de prueba", matched_by="stub")

    monkeypatch.setattr("core.resolution.resolve", resolve)
    # Y el guardado del turno, que calcula embeddings (torch) y escribe en la base: el
    # test que necesite ver qué se guarda lo vuelve a stubear a su manera.
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)


@pytest.fixture
def bridge(qtbot, fake_run_async):
    main_window = MagicMock()
    b = Bridge(main_window)
    return b


# ---------------------------------------------------------------------------
# CA-07: nueva conversación
# ---------------------------------------------------------------------------

def test_new_conversation_limpia_id_y_emite_conversation_cleared(bridge, qtbot):
    bridge._conversation_id = "abc"
    with qtbot.waitSignal(bridge.conversation_cleared, timeout=1000):
        bridge.new_conversation()
    assert bridge._conversation_id is None


# ---------------------------------------------------------------------------
# CA-09: seleccionar conversación existente
# ---------------------------------------------------------------------------

def test_select_conversation_llama_get_conversation_turns_y_emite_turns_loaded(bridge, monkeypatch):
    from ai.memory_manager import memory

    fake_turns = [SimpleNamespace(id=1, role="user", text="hola", timestamp="t1")]
    monkeypatch.setattr(memory, "get_conversation_turns", lambda conversation_id, user_id="default": fake_turns)

    received = []
    bridge.turns_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.select_conversation("conv-1")

    assert bridge._conversation_id == "conv-1"
    assert received[0][0]["role"] == "user"
    assert received[0][0]["id"] == 1


# ---------------------------------------------------------------------------
# El modelo ve la conversación ABIERTA, entera
# ---------------------------------------------------------------------------
#
# Johan le pidió al agente "mejorá ese mensaje" y el agente no tenía el mensaje: recibía el
# contexto por usuario (cinco registros de cualquier conversación, con las respuestas
# cortadas a 200 caracteres). Los turnos completos estaban guardados por conversación desde
# REQ-013; solo faltaba dárselos.

def test_el_historial_que_se_manda_al_modelo_es_el_de_la_conversacion_abierta(bridge, monkeypatch):
    from ai.memory_manager import memory

    respuesta_larga = "Estimado cliente: " + "x" * 900
    fake_turns = [SimpleNamespace(id=1, role="user", text="redactá un correo", timestamp="t1"),
                  SimpleNamespace(id=2, role="assistant", text=respuesta_larga, timestamp="t2"),
                  SimpleNamespace(id=3, role=None, text="ruido sin rol", timestamp="t3")]
    pedidos = []

    def _turnos(conversation_id, user_id="default", limit=200):
        pedidos.append((conversation_id, user_id))
        return fake_turns

    monkeypatch.setattr(memory, "get_conversation_turns", _turnos)
    bridge._conversation_id = "conv-7"

    historial = bridge._historial_de_la_conversacion()

    assert pedidos == [("conv-7", bridge_module.OWNER_USER_ID)]
    assert historial == [{"role": "user", "content": "redactá un correo"},
                         {"role": "assistant", "content": respuesta_larga}]   # entera, no 200


def test_sin_conversacion_abierta_no_se_manda_historial(bridge):
    bridge._conversation_id = None
    assert bridge._historial_de_la_conversacion() is None


def test_send_message_le_pasa_la_conversacion_a_resolve(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "get_conversation_turns",
                        lambda conversation_id, user_id="default", limit=200: [
                            SimpleNamespace(id=1, role="assistant", text="el mensaje", timestamp="t")])
    bridge._conversation_id = "conv-9"

    bridge.send_message("mejorá ese mensaje")

    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert llamada["kwargs"]["historial"] == [{"role": "assistant", "content": "el mensaje"}]


# ---------------------------------------------------------------------------
# REQ-054: imágenes en el chat de escritorio
# ---------------------------------------------------------------------------

def _captura(tmp_path, nombre="captura.png"):
    PIL = pytest.importorskip("PIL")
    from PIL import Image

    ruta = tmp_path / nombre
    Image.new("RGB", (12, 8), (10, 200, 10)).save(ruta)
    return str(ruta)


def test_send_message_con_imagen_adjunta_se_la_pasa_a_resolve_y_muestra_la_miniatura(
    bridge, qtbot, fake_run_async, tmp_path,
):
    """El modelo tiene que VER la imagen (`image_path`), y la burbuja del usuario tiene
    que mostrarla como miniatura en vez de la ruta cruda entre corchetes."""
    ruta = _captura(tmp_path)
    bridge._pending_attachments = [ruta]
    recibidos = []
    bridge.message_appended.connect(lambda payload: recibidos.append(json.loads(payload)))

    bridge.send_message("¿qué error es este?")

    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert llamada["kwargs"]["image_path"] == ruta
    assert llamada["args"][0] == f"¿qué error es este?\n\n[Imagen adjunta: {ruta}]"

    usuario = [m for m in recibidos if m["role"] == "user"][0]
    assert "Imagen adjunta" not in usuario["html"]
    assert "¿qué error es este?" in usuario["html"]
    assert usuario["adjuntos"][0]["nombre"] == "captura.png"
    assert usuario["adjuntos"][0]["miniatura"].startswith("data:image/")


def test_send_message_con_un_archivo_que_no_es_imagen_no_manda_image_path(
    bridge, fake_run_async, tmp_path,
):
    """Los dobles de `resolve` con la firma vieja no conocen el kwarg: solo viaja si hay
    una imagen. El chip del adjunto sí llega, sin miniatura."""
    archivo = tmp_path / "informe.pdf"
    archivo.write_bytes(b"%PDF-1.4")
    bridge._pending_attachments = [str(archivo)]
    recibidos = []
    bridge.message_appended.connect(lambda payload: recibidos.append(json.loads(payload)))

    bridge.send_message("resumime esto")

    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert "image_path" not in llamada["kwargs"]
    usuario = [m for m in recibidos if m["role"] == "user"][0]
    assert usuario["adjuntos"] == [{"nombre": "informe.pdf", "miniatura": "", "ruta": ""}]


def test_send_message_sin_adjunto_no_lleva_el_campo_adjunto(bridge, fake_run_async):
    recibidos = []
    bridge.message_appended.connect(lambda payload: recibidos.append(json.loads(payload)))

    bridge.send_message("hola")

    usuario = [m for m in recibidos if m["role"] == "user"][0]
    assert "adjuntos" not in usuario
    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert "image_path" not in llamada["kwargs"]


def test_al_reabrir_la_conversacion_el_turno_del_usuario_trae_su_miniatura(bridge, monkeypatch, tmp_path):
    """La imagen se guardó en la carpeta del usuario, así que al volver al chat la burbuja
    la vuelve a mostrar. Un turno cuya imagen ya no está muestra el chip con el nombre."""
    from ai.memory_manager import memory

    ruta = _captura(tmp_path)
    turnos = [
        SimpleNamespace(id=1, role="user", text=f"mirá esto\n\n[Imagen adjunta: {ruta}]", timestamp="t1"),
        SimpleNamespace(id=2, role="assistant", text="Es un error de red.", timestamp="t2"),
        SimpleNamespace(id=3, role="user", text="y esto\n\n[Imagen adjunta: C:\\ya\\no\\esta.png]", timestamp="t3"),
    ]
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: turnos)
    recibidos = []
    bridge.turns_loaded.connect(lambda payload: recibidos.append(json.loads(payload)))

    bridge.select_conversation("conv-1")

    cargados = recibidos[0]
    assert cargados[0]["id"] == 1
    assert cargados[0]["adjuntos"][0]["miniatura"].startswith("data:image/")
    assert "Imagen adjunta" not in cargados[0]["html"]
    assert "adjuntos" not in cargados[1]
    assert cargados[2]["adjuntos"][0]["nombre"] == "esta.png"
    assert cargados[2]["adjuntos"][0]["miniatura"] == ""
    # Y la que sí está queda habilitada para el visor a tamaño completo.
    assert cargados[0]["adjuntos"][0]["ruta"] == ruta
    assert ruta in bridge._imagenes_mostradas


def test_request_image_sirve_la_imagen_entera_solo_si_ya_se_mostro(bridge, fake_run_async, tmp_path):
    """El slot lo puede invocar cualquier script de la página (§10.2): solo devuelve las
    imágenes que esta sesión ya puso en una burbuja, nunca un archivo cualquiera."""
    ruta = _captura(tmp_path)
    otra = _captura(tmp_path, "privada.png")
    cargadas = []
    bridge.image_loaded.connect(lambda r, url: cargadas.append((r, url)))

    bridge.request_image(otra)          # nunca mostrada: se ignora
    assert cargadas == []

    bridge._pending_attachments = [ruta]
    bridge.send_message("mirá")
    bridge.request_image(ruta)

    assert len(cargadas) == 1
    assert cargadas[0][0] == ruta
    assert cargadas[0][1].startswith("data:image/")


class _PortapapelesFalso:
    def __init__(self, imagen=None, urls=()):
        from PyQt6.QtCore import QMimeData, QUrl
        from PyQt6.QtGui import QImage

        self._imagen = imagen if imagen is not None else QImage()
        self._mime = QMimeData()
        if urls:
            self._mime.setUrls([QUrl.fromLocalFile(u) for u in urls])

    def image(self):
        return self._imagen

    def mimeData(self):
        return self._mime


def test_pegar_una_imagen_del_portapapeles_la_guarda_y_la_adjunta(bridge, monkeypatch, tmp_path):
    """Ctrl+V con una captura: se guarda como PNG en la carpeta del usuario y queda como
    adjunto pendiente, con su miniatura en el chip."""
    from PyQt6.QtGui import QColor, QImage
    from PyQt6.QtWidgets import QApplication

    from core import imagenes

    imagen = QImage(16, 10, QImage.Format.Format_RGB32)
    imagen.fill(QColor(200, 100, 0))
    monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: _PortapapelesFalso(imagen)))
    monkeypatch.setattr(imagenes, "carpeta_de_imagenes_pegadas", lambda user_id="owner": str(tmp_path))
    miniaturas = []
    bridge.attachment_preview.connect(lambda p, m: miniaturas.append(m))

    bridge.paste_from_clipboard()

    pendiente = (bridge._pending_attachments or [None])[0]
    assert pendiente and pendiente.startswith(str(tmp_path)) and pendiente.endswith(".png")
    assert imagenes.media_type(pendiente) == "image/png"
    assert miniaturas and miniaturas[-1].startswith("data:image/")


def test_pegar_un_archivo_copiado_del_explorador_lo_adjunta_por_su_ruta(bridge, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication

    archivo = tmp_path / "notas.md"
    archivo.write_text("# notas", encoding="utf-8")
    monkeypatch.setattr(QApplication, "clipboard",
                        staticmethod(lambda: _PortapapelesFalso(urls=[str(archivo)])))

    bridge.paste_from_clipboard()

    assert bridge._pending_attachments == [str(archivo)]


def test_pegar_sin_imagen_ni_archivo_solo_avisa(bridge, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: _PortapapelesFalso()))
    avisos = []
    bridge.notice_shown.connect(lambda tipo, texto: avisos.append((tipo, texto)))

    bridge.paste_from_clipboard()

    assert bridge._pending_attachments == []
    assert avisos == [("info", "No hay una imagen ni un archivo en el portapapeles.")]


# ---------------------------------------------------------------------------
# REQ-055: regenerar la última respuesta / editar el último mensaje
# ---------------------------------------------------------------------------

def test_regenerate_last_borra_el_ultimo_par_y_vuelve_a_resolver_el_mismo_texto(
    bridge, monkeypatch, fake_run_async,
):
    from ai.memory_manager import memory

    borrados = []
    monkeypatch.setattr(memory, "delete_last_turn",
                        lambda conversation_id, user_id="default": borrados.append(conversation_id)
                        or SimpleNamespace(id=7, role="user", text="¿qué hora es?", timestamp="t"))
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    bridge._conversation_id = "conv-1"
    quitados = []
    bridge.last_turn_removed.connect(lambda: quitados.append(True))

    bridge.regenerate_last()

    assert borrados == ["conv-1"]
    assert quitados == [True]
    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert llamada["args"][0] == "¿qué hora es?"
    assert "image_path" not in llamada["kwargs"]


def test_regenerate_last_reenvia_la_imagen_si_el_mensaje_la_tenia(bridge, monkeypatch, fake_run_async, tmp_path):
    from ai.memory_manager import memory

    ruta = _captura(tmp_path)
    monkeypatch.setattr(memory, "delete_last_turn",
                        lambda conversation_id, user_id="default": SimpleNamespace(
                            id=7, role="user", text=f"¿qué dice?\n\n[Imagen adjunta: {ruta}]", timestamp="t"))
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    bridge._conversation_id = "conv-1"

    bridge.regenerate_last()

    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert llamada["kwargs"]["image_path"] == ruta
    assert llamada["args"][0].endswith(f"[Imagen adjunta: {ruta}]")


def test_regenerate_last_sin_par_que_borrar_solo_avisa(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "delete_last_turn", lambda *a, **k: None)
    bridge._conversation_id = "conv-1"
    avisos = []
    bridge.notice_shown.connect(lambda tipo, texto: avisos.append((tipo, texto)))

    bridge.regenerate_last()

    assert avisos == [("info", "No hay una respuesta que regenerar.")]
    assert not [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"]
    assert bridge._resolution_in_flight is False


def test_regenerate_last_se_ignora_con_un_turno_en_curso_o_sin_conversacion(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "delete_last_turn",
                        lambda *a, **k: pytest.fail("no debe borrar nada"))
    bridge._conversation_id = None
    bridge.regenerate_last()

    bridge._conversation_id = "conv-1"
    bridge._resolution_in_flight = True
    bridge.regenerate_last()
    bridge._resolution_in_flight = False


def test_edit_last_deja_el_texto_en_el_cuadro_y_devuelve_el_adjunto_al_chip(bridge, monkeypatch, fake_run_async, tmp_path):
    from ai.memory_manager import memory

    ruta = _captura(tmp_path)
    monkeypatch.setattr(memory, "delete_last_turn",
                        lambda conversation_id, user_id="default": SimpleNamespace(
                            id=7, role="user", text=f"¿qué dise esto?\n\n[Imagen adjunta: {ruta}]", timestamp="t"))
    bridge._conversation_id = "conv-1"
    textos, quitados, adjuntos = [], [], []
    bridge.composer_text_requested.connect(textos.append)
    bridge.last_turn_removed.connect(lambda: quitados.append(True))
    bridge.file_attached.connect(lambda path, name, ok, motivo: adjuntos.append((path, ok)))

    bridge.edit_last()

    assert quitados == [True]
    assert textos == ["¿qué dise esto?"]          # sin el marcador
    assert adjuntos == [(ruta, True)]
    assert bridge._pending_attachments == [ruta]
    # No se resuelve nada: el usuario corrige y manda cuando quiere.
    assert not [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"]


def test_edit_last_con_un_adjunto_que_ya_no_existe_solo_deja_el_texto(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "delete_last_turn",
                        lambda conversation_id, user_id="default": SimpleNamespace(
                            id=7, role="user", text="resumí esto\n\n[Archivo adjunto: C:\\ya\\no\\esta.pdf]",
                            timestamp="t"))
    bridge._conversation_id = "conv-1"
    textos = []
    bridge.composer_text_requested.connect(textos.append)

    bridge.edit_last()

    assert textos == ["resumí esto"]
    assert bridge._pending_attachments == []


# ---------------------------------------------------------------------------
# CA-11: paginación "Ver más"
# ---------------------------------------------------------------------------

def test_load_more_conversations_pasa_el_offset_recibido(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: calls.append(kwargs) or [])

    bridge.load_more_conversations(30)

    assert calls[0]["offset"] == 30


def test_request_initial_state_emite_chips_theme_y_conversaciones(bridge, monkeypatch):
    """REQ-026 addendum 1: `chips_loaded` sigue emitiendo `{"modes": [...], "quick_actions":
    [...]}` (CA-39, portados de REQ-015), pero `quick_actions` se redujo de 3 a 1 entrada —
    "📷 Captura de pantalla" y "🌐 Abrir navegador" se eliminaron del composer
    (SPEC-026-addendum-1.md, "Catálogo final"); su capacidad de agente no se toca, solo el
    atajo de UI, y por eso no forman parte de este payload nunca más."""
    from ai.memory_manager import memory
    import config_manager

    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "dark")

    chips_received, theme_received, conv_received = [], [], []
    bridge.chips_loaded.connect(lambda j: chips_received.append(json.loads(j)))
    bridge.theme_changed.connect(theme_received.append)
    bridge.conversation_list_updated.connect(lambda j: conv_received.append(json.loads(j)))

    bridge.request_initial_state()

    payload = chips_received[0]
    assert len(payload["modes"]) == 4
    assert {m["id"] for m in payload["modes"]} == {"codigo", "investigacion", "flujos", "tareas"}
    assert len(payload["quick_actions"]) == 1
    etiquetas = {c["label"] for c in payload["quick_actions"]}
    assert etiquetas == {"Recuérdame algo"}
    # "📷 Captura de pantalla" y "🌐 Abrir navegador" (addendum 1) y "Resumen del día" /
    # "Investigación rápida" (REQ-026 original) ya no aparecen en ningún catálogo.
    assert "📷 Captura de pantalla" not in etiquetas
    assert "🌐 Abrir navegador" not in etiquetas
    assert "Resumen del día" not in etiquetas
    assert "Investigación rápida" not in etiquetas
    # Campo nuevo del addendum 1: el frontend necesita el ícono para renderizar "Recuérdame
    # algo" con el mismo componente que los 4 modos (`#ic-bell`, ver ui-design-026-addendum-1.md §4).
    assert next(iter(payload["quick_actions"]))["icon"] == "bell"
    assert theme_received == ["dark"]
    assert conv_received == [[]]


# ---------------------------------------------------------------------------
# CA-10, §10.2: borrado de conversación pasa por confirmación YELLOW
# ---------------------------------------------------------------------------

def test_request_delete_conversation_pide_confirmacion_y_borra_si_se_confirma(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    confirm_calls = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        confirm_calls.append((action_name, details))
        return True

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)

    delete_calls = []
    monkeypatch.setattr(
        memory, "delete_conversation",
        lambda conversation_id, user_id="default": delete_calls.append(conversation_id) or True,
    )

    received = []
    bridge.conversation_removed.connect(received.append)

    bridge.request_delete_conversation("conv-xyz")

    assert confirm_calls[0][0] == "delete_conversation"
    assert "conv-xyz" in confirm_calls[0][1]  # §10.2: details incluye el id (clave "name")
    assert delete_calls == ["conv-xyz"]
    assert received == ["conv-xyz"]


def test_request_delete_conversation_no_borra_si_se_cancela(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: False)
    delete_calls = []
    monkeypatch.setattr(memory, "delete_conversation", lambda *a, **k: delete_calls.append(1))

    received = []
    bridge.conversation_removed.connect(received.append)

    bridge.request_delete_conversation("conv-xyz")

    assert delete_calls == []
    assert received == []


def test_request_delete_conversation_no_emite_removed_si_delete_devuelve_false(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(memory, "delete_conversation", lambda *a, **k: False)

    received = []
    bridge.conversation_removed.connect(received.append)

    bridge.request_delete_conversation("conv-ya-no-existe")

    assert received == []


# ---------------------------------------------------------------------------
# CA-20..CA-24: mensajes, guard server-side
# ---------------------------------------------------------------------------

def test_send_message_emite_eco_del_usuario_typing_y_resuelve(bridge, monkeypatch):
    from ai.memory_manager import memory

    monkeypatch.setattr("core.resolution.resolve", lambda *a, **k: SimpleNamespace(text="respuesta", matched_by="dispatcher"))
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "new-id")
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])

    messages = []
    typing_events = []
    bridge.message_appended.connect(lambda j: messages.append(json.loads(j)))
    bridge.typing_started.connect(lambda: typing_events.append("started"))
    bridge.typing_stopped.connect(lambda: typing_events.append("stopped"))

    bridge.send_message("hola")

    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert "respuesta" in messages[1]["html"]
    assert typing_events == ["started", "stopped"]
    assert bridge._resolution_in_flight is False


def test_send_message_ignora_llamada_concurrente_ca24(bridge, monkeypatch):
    """CA-24 — guard server-side estricto: el bridge es invocable desde JS sin pasar por
    el estado `disabled` del DOM, a diferencia de un `QWidget` deshabilitado."""
    calls = []

    def fake_run_async_que_no_resuelve(fn, on_done=None, on_error=None, *args, **kwargs):
        calls.append(1)
        # deliberadamente no llama on_done/on_error: simula una resolución en curso

    monkeypatch.setattr(bridge_module, "run_async", fake_run_async_que_no_resuelve)

    bridge.send_message("primero")
    assert bridge._resolution_in_flight is True
    assert len(calls) == 1

    bridge.send_message("segundo")  # debe ser ignorado, no debe llamar run_async otra vez
    assert len(calls) == 1


def test_send_message_con_texto_vacio_no_hace_nada(bridge, monkeypatch):
    calls = []
    monkeypatch.setattr(bridge_module, "run_async", lambda *a, **k: calls.append(1))
    bridge.send_message("")
    assert calls == []
    assert bridge._resolution_in_flight is False


# ---------------------------------------------------------------------------
# REQ-026 — `send_message(text, modo)` threadea el modo activo del composer hasta
# `resolve()`. `test-results-026.md` (orion-tester): la firma nueva no tenía ningún test
# que la ejercitara (ningún test de este archivo pasaba un segundo argumento antes de
# estos dos), así que el cambio de contrato (`_try_claude`/`resolve(modo=...)`,
# desarrollo-log-026.md "Decisiones de implementación") quedaba sin cubrir end-to-end
# desde el único call site real (`composer.js::doSend()`).
# ---------------------------------------------------------------------------

def test_send_message_con_modo_lo_pasa_a_resolve_como_kwarg(bridge, monkeypatch):
    from ai.memory_manager import memory

    recibido = {}

    def fake_resolve(*args, **kwargs):
        recibido.update(kwargs)
        return SimpleNamespace(text="respuesta", matched_by="dispatcher")

    monkeypatch.setattr("core.resolution.resolve", fake_resolve)
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "new-id")
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])

    bridge.send_message("ejecuta un script", "codigo")

    assert recibido["modo"] == "codigo"


def test_send_message_sin_modo_manda_none_no_string_vacio(bridge, monkeypatch):
    """`modo=""` (default del slot, o el frontend sin ningún modo activo) debe llegar a
    `resolve()` como `None` — `get_mode(None)` y `get_mode("")` son equivalentes
    (`test_composer_modes.py`), pero `resolve()`/`_try_claude()` distinguen `is not None`
    para decidir si pasan el kwarg `modo` a `reasoning_loop.run()`, así que el bridge debe
    normalizar antes de llamar."""
    from ai.memory_manager import memory

    recibido = {}

    def fake_resolve(*args, **kwargs):
        recibido.update(kwargs)
        return SimpleNamespace(text="respuesta", matched_by="dispatcher")

    monkeypatch.setattr("core.resolution.resolve", fake_resolve)
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "new-id")
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])

    bridge.send_message("hola")  # sin segundo argumento -> default ""

    assert recibido["modo"] is None


def test_on_resolve_error_no_persiste_turno(bridge, monkeypatch):
    from ai.memory_manager import memory

    store_calls = []
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: store_calls.append(1))

    messages = []
    bridge.message_appended.connect(lambda j: messages.append(json.loads(j)))

    bridge._pending_user_text = "hola"
    bridge._resolution_in_flight = True
    bridge._on_resolve_error("boom")

    assert store_calls == []  # un error no es una respuesta de la IA — no se persiste
    assert messages[-1]["role"] == "assistant"
    assert "Error" in messages[-1]["html"]
    assert bridge._resolution_in_flight is False


# ---------------------------------------------------------------------------
# CA-39, CA-40: chips
# ---------------------------------------------------------------------------

def test_run_chip_action_siempre_pasa_por_execute_action(bridge, monkeypatch):
    import agents.action_registry as action_registry_module

    calls = []
    monkeypatch.setattr(
        action_registry_module, "execute_action",
        lambda name, channel=None, user_id="default": calls.append((name, channel)) or "Captura guardada.",
    )

    received = []
    bridge.message_appended.connect(lambda j: received.append(json.loads(j)))

    bridge.run_chip_action("take_screenshot")

    assert calls[0][0] == "take_screenshot"
    assert received[0]["role"] == "system"  # CA-14: no se persiste, no es un turno
    assert "Captura guardada" in received[0]["html"]


def test_run_chip_action_error_se_reporta_como_mensaje_system(bridge, monkeypatch):
    import agents.action_registry as action_registry_module

    def boom(name, channel=None, user_id="default"):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(action_registry_module, "execute_action", boom)

    received = []
    bridge.message_appended.connect(lambda j: received.append(json.loads(j)))

    bridge.run_chip_action("take_screenshot")

    assert received[0]["role"] == "system"
    assert "Error" in received[0]["html"]


def test_build_quick_actions_payload_consulta_risk_level_en_el_momento(monkeypatch):
    """REQ-026 addendum 1: `_QUICK_ACTIONS` se redujo de 3 entradas (1 template + 2 action)
    a 1 sola entrada `template` ("Recuérdame algo") — "📷 Captura de pantalla" y
    "🌐 Abrir navegador" (los 2 `kind == "action"`) se eliminaron del catálogo. La rama
    `kind == "action"` de `_build_quick_actions_payload()` (CA-40, risk_level consultado en
    el momento) queda sin ningún elemento que la ejercite desde este catálogo — se deja sin
    retirar (ver docstring de la función), así que se verifica acá que sigue sin romper nada
    aunque no tenga consumidor: cero action_chips, `classify_action()` nunca se llama."""
    from core.security_manager import RiskLevel, security_manager

    calls = []
    monkeypatch.setattr(
        security_manager, "classify_action",
        lambda name: calls.append(name) or RiskLevel.YELLOW,
    )

    payload = bridge_module._build_quick_actions_payload()

    action_chips = [c for c in payload if c["kind"] == "action"]
    template_chips = [c for c in payload if c["kind"] == "template"]
    assert len(action_chips) == 0
    assert len(template_chips) == 1
    assert template_chips[0]["risk_level"] is None
    assert template_chips[0]["icon"] == "bell"
    assert calls == []


def test_build_modes_payload_devuelve_4_modos_id_y_label_sin_detalle_interno():
    """REQ-026: el frontend recibe solo `{id, label}` por modo — `tool_names`/`tarea`/
    `prompt_hint` son detalle interno del backend, `composer.js::renderModes()` no lo
    necesita."""
    payload = bridge_module._build_modes_payload()

    assert len(payload) == 4
    for entry in payload:
        assert set(entry.keys()) == {"id", "label"}
    assert [e["id"] for e in payload] == ["codigo", "investigacion", "flujos", "tareas"]


# ---------------------------------------------------------------------------
# REQ-026 — `set_active_mode()` / `_tarea_activa()`: el espejo efímero `_modo_activo` que
# permite a `request_models()` (menú de modelos, disparado desacoplado de `send_message()`)
# reflejar "fijado por el modo" sin esperar al próximo mensaje. `test-results-026.md`
# (orion-tester): sin cobertura previa — ningún test ejercitaba este slot ni `_tarea_activa`.
# ---------------------------------------------------------------------------

def test_set_active_mode_actualiza_el_espejo_y_reemite_models_loaded_con_su_tarea(bridge, monkeypatch):
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {"tarea": tarea},
    )

    recibidos = []
    bridge.models_loaded.connect(lambda j: recibidos.append(json.loads(j)))

    bridge.set_active_mode("codigo")

    assert bridge._modo_activo == "codigo"
    assert tareas_consultadas == ["modo_codigo"]
    assert recibidos[-1] == {"tarea": "modo_codigo"}


def test_set_active_mode_con_modo_sin_tarea_fijada_usa_razonamiento(bridge, monkeypatch):
    """`flujos`/`tareas` (arquitectura-026.md §3) no fijan `tarea` — el modo queda activo
    en el espejo, pero el selector de modelo sigue ruteando como siempre."""
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {},
    )

    bridge.set_active_mode("flujos")

    assert bridge._modo_activo == "flujos"
    assert tareas_consultadas == ["razonamiento"]


def test_set_active_mode_vacio_limpia_el_espejo_ca_toggle_off(bridge, monkeypatch):
    """SPEC-026: togglear el mismo modo activo lo desactiva — el frontend manda `""`."""
    monkeypatch.setattr(bridge_module, "_build_models_payload", lambda tarea="razonamiento": {})

    bridge.set_active_mode("codigo")
    assert bridge._modo_activo == "codigo"

    bridge.set_active_mode("")

    assert bridge._modo_activo is None


def test_set_active_mode_id_desconocido_es_fail_safe_no_lanza(bridge, monkeypatch):
    """Un `modo_id` inválido/obsoleto (frontend con catálogo cacheado) se trata como 'sin
    modo' — nunca rompe el slot (`get_mode()` es fail-safe, `test_composer_modes.py`)."""
    monkeypatch.setattr(bridge_module, "_build_models_payload", lambda tarea="razonamiento": {})

    bridge.set_active_mode("modo_que_no_existe")

    assert bridge._modo_activo is None


def test_request_models_refleja_la_tarea_del_modo_activo_via_el_espejo(bridge, monkeypatch):
    """`request_models()` (abrir el menú de modelos) está desacoplado de `send_message()` —
    debe usar `_modo_activo` (seteado por un `set_active_mode()` previo), no depender de
    que se haya enviado ya un mensaje con ese modo."""
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {},
    )

    bridge._modo_activo = "investigacion"
    bridge.request_models()

    assert tareas_consultadas == ["modo_investigacion"]


def test_request_models_sin_modo_activo_usa_razonamiento(bridge, monkeypatch):
    tareas_consultadas = []
    monkeypatch.setattr(
        bridge_module, "_build_models_payload",
        lambda tarea="razonamiento": tareas_consultadas.append(tarea) or {},
    )

    bridge.request_models()

    assert tareas_consultadas == ["razonamiento"]


# ---------------------------------------------------------------------------
# CA-37: tema
# ---------------------------------------------------------------------------

def test_set_theme_persiste_y_emite(bridge, monkeypatch):
    import config_manager

    persisted = []
    monkeypatch.setattr(config_manager, "set_ui_theme", persisted.append)

    received = []
    bridge.theme_changed.connect(received.append)

    bridge.set_theme("dark")

    assert persisted == ["dark"]
    assert received == ["dark"]


def test_set_theme_normaliza_valor_invalido_ca38(bridge, monkeypatch):
    import config_manager

    persisted = []
    monkeypatch.setattr(config_manager, "set_ui_theme", persisted.append)

    bridge.set_theme("no-existe-este-tema")

    assert persisted == ["light"]  # DEFAULT_THEME


# ---------------------------------------------------------------------------
# CA-25: toggle de modo manos libres — nunca toca sr.Microphone() en tests
# ---------------------------------------------------------------------------

def test_toggle_wake_word_on_arranca_un_worker(bridge, no_real_threadpool):
    bridge.toggle_wake_word(True)

    wake_workers = [w for w in no_real_threadpool if isinstance(w, WakeWordWorker)]
    assert len(wake_workers) == 1
    assert bridge._wake_worker is wake_workers[0]


def test_toggle_wake_word_doble_on_no_arranca_dos_workers(bridge, no_real_threadpool):
    bridge.toggle_wake_word(True)
    bridge.toggle_wake_word(True)

    wake_workers = [w for w in no_real_threadpool if isinstance(w, WakeWordWorker)]
    assert len(wake_workers) == 1


def test_toggle_wake_word_off_setea_stop_event(bridge, no_real_threadpool):
    bridge.toggle_wake_word(True)
    worker = bridge._wake_worker
    assert worker.stop_event.is_set() is False

    bridge.toggle_wake_word(False)

    assert worker.stop_event.is_set() is True


# ---------------------------------------------------------------------------
# §4.3: confirmación YELLOW — confirm_response delega en el adaptador
# ---------------------------------------------------------------------------

def test_confirm_response_delega_en_el_adaptador_registrado(bridge):
    adapter = MagicMock()
    bridge.set_confirmation_adapter(adapter)

    bridge.confirm_response("req-1", True)

    adapter.confirm_response.assert_called_once_with("req-1", True)


def test_confirm_response_sin_adaptador_no_lanza(bridge, caplog):
    bridge.confirm_response("req-1", True)  # sin adaptador registrado — no debe lanzar
    assert any("adaptador" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# CA-01, CA-02: chrome de ventana
# ---------------------------------------------------------------------------

def test_start_resize_llama_startsystemresize_con_edge_valido(bridge):
    handle = MagicMock()
    bridge._main_window.windowHandle.return_value = handle

    bridge.start_resize("se")

    handle.startSystemResize.assert_called_once()


def test_start_resize_edge_desconocido_no_lanza_ni_llama_qt(bridge):
    handle = MagicMock()
    bridge._main_window.windowHandle.return_value = handle

    bridge.start_resize("zz")  # edge inválido

    handle.startSystemResize.assert_not_called()


def test_start_move_llama_startsystemmove(bridge):
    handle = MagicMock()
    bridge._main_window.windowHandle.return_value = handle

    bridge.start_move()

    handle.startSystemMove.assert_called_once()


def test_window_close_delega_en_main_window(bridge):
    bridge.window_close()
    bridge._main_window.close.assert_called_once()


def test_window_minimize_delega_en_main_window(bridge):
    bridge.window_minimize()
    bridge._main_window.showMinimized.assert_called_once()


def test_window_toggle_maximize_alterna_segun_estado_actual(bridge):
    bridge._main_window.isMaximized.return_value = False
    bridge.window_toggle_maximize()
    bridge._main_window.showMaximized.assert_called_once()

    bridge._main_window.isMaximized.return_value = True
    bridge.window_toggle_maximize()
    bridge._main_window.showNormal.assert_called_once()


# ---------------------------------------------------------------------------
# REQ-016/CA-05..CA-12: tareas
# ---------------------------------------------------------------------------

def test_request_tasks_llama_list_all_tasks_y_emite_tasks_loaded(bridge, monkeypatch):
    from tasks.task_manager import task_manager

    fake_tasks = [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]
    calls = []
    monkeypatch.setattr(
        task_manager, "list_all_tasks",
        lambda user_id="default": calls.append(user_id) or fake_tasks,
    )

    received = []
    bridge.tasks_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.request_tasks()

    # Se asevera contra la constante, no contra el literal: el escritorio dejó de usar
    # "default" al unificarse la identidad del dueño entre canales, y fijar el texto aquí
    # solo obligaría a volver a tocar el test la próxima vez que cambie.
    from core.user_identity import OWNER_USER_ID

    assert calls == [OWNER_USER_ID]
    assert received == [fake_tasks]  # CA-09: orden intacto, se serializa tal cual


def test_request_tasks_no_se_llama_en_request_initial_state(bridge, monkeypatch):
    from ai.memory_manager import memory
    from tasks.task_manager import task_manager
    import config_manager

    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "dark")

    calls = []
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: calls.append(1) or [])

    bridge.request_initial_state()

    assert calls == []  # CA-12: request_tasks() nunca se dispara desde el arranque


def test_create_task_con_titulo_vacio_no_llama_a_task_manager(bridge, monkeypatch):
    from tasks.task_manager import task_manager

    calls = []
    monkeypatch.setattr(task_manager, "create_task", lambda **k: calls.append(1))

    bridge.create_task("   ", "", "", "")

    assert calls == []


def test_create_task_pasa_channel_desktop_sin_modificar_create_task(bridge, monkeypatch):
    from tasks.task_manager import task_manager

    calls = []
    monkeypatch.setattr(task_manager, "create_task", lambda **k: calls.append(k) or 1)
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: [])

    bridge.create_task("Comprar leche", "desc", "", "")

    assert calls[0]["channel"] == "desktop"
    assert calls[0]["title"] == "Comprar leche"


def test_complete_task_no_pide_confirmacion(bridge, monkeypatch):
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager

    def fail_confirm(*a, **k):
        raise AssertionError("complete_task no debe pedir confirmación (a diferencia de delete_task)")

    monkeypatch.setattr(security_manager, "require_confirmation", fail_confirm)
    monkeypatch.setattr(task_manager, "complete_task", lambda *a, **k: True)
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: [])

    bridge.complete_task(1)  # no debe lanzar


def test_request_delete_task_pide_confirmacion_antes_de_delete_task(bridge, monkeypatch):
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager

    confirm_calls = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        confirm_calls.append(action_name)
        return False

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)
    delete_calls = []
    monkeypatch.setattr(task_manager, "delete_task", lambda *a, **k: delete_calls.append(1) or True)

    bridge.request_delete_task(42)

    assert confirm_calls == ["delete_task"]
    assert delete_calls == []  # cancelado: nunca se llama a task_manager.delete_task

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(task_manager, "list_all_tasks", lambda **k: [])

    bridge.request_delete_task(42)

    assert delete_calls == [1]  # confirmado: ahora sí se llama


def test_request_delete_task_usa_action_name_delete_task(bridge, monkeypatch):
    from tasks.task_manager import task_manager
    from core.security_manager import security_manager

    captured = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        captured.append((action_name, details))
        return False

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)
    monkeypatch.setattr(task_manager, "delete_task", lambda *a, **k: True)

    bridge.request_delete_task(7)

    assert captured[0][0] == "delete_task"
    assert "7" in captured[0][1]


# ---------------------------------------------------------------------------
# REQ-016/CA-13..CA-21: proyectos
# ---------------------------------------------------------------------------

def test_request_projects_llama_list_projects_y_emite_projects_loaded(bridge, monkeypatch):
    from ai.memory_manager import memory, ProjectSummary

    fake_projects = [ProjectSummary(id=1, name="A", created_at="t", conversation_count=2)]
    monkeypatch.setattr(memory, "list_projects", lambda user_id="default": fake_projects)

    received = []
    bridge.projects_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.request_projects()

    assert received == [[{"id": 1, "name": "A", "created_at": "t", "conversation_count": 2}]]


def test_create_project_con_nombre_vacio_no_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(memory, "create_project", lambda **k: calls.append(1))

    bridge.create_project("   ")

    assert calls == []


def test_create_project_con_nombre_valido_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(memory, "create_project", lambda **k: calls.append(k) or 1)
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    bridge.create_project("Mi proyecto")

    assert calls[0]["name"] == "Mi proyecto"


def test_assign_conversation_to_project_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(
        memory, "assign_conversation_to_project",
        lambda conversation_id, project_id, user_id="default": calls.append((conversation_id, project_id)) or True,
    )
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    bridge.assign_conversation_to_project("conv-1", 5)

    assert calls == [("conv-1", 5)]


def test_unassign_conversation_from_project_llama_a_memory(bridge, monkeypatch):
    from ai.memory_manager import memory

    calls = []
    monkeypatch.setattr(
        memory, "unassign_conversation_from_project",
        lambda conversation_id, user_id="default": calls.append(conversation_id) or True,
    )
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    bridge.unassign_conversation_from_project("conv-1")

    assert calls == ["conv-1"]


def test_request_project_conversations_incluye_project_id_en_la_señal(bridge, monkeypatch):
    from ai.memory_manager import memory, ConversationSummary

    fake_convs = [ConversationSummary(conversation_id="conv-1", title="t", last_activity="a", turn_count=1)]
    monkeypatch.setattr(
        memory, "list_conversations_by_project",
        lambda project_id, user_id="default": fake_convs,
    )

    received = []
    bridge.project_conversations_loaded.connect(lambda j, pid: received.append((json.loads(j), pid)))

    bridge.request_project_conversations(9)

    assert received[0][1] == 9
    assert received[0][0][0]["conversation_id"] == "conv-1"


def test_request_delete_project_pide_confirmacion_antes_de_delete_project(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    confirm_calls = []

    def fake_require_confirmation(action_name, channel, details="", user_id="default"):
        confirm_calls.append(action_name)
        return False

    monkeypatch.setattr(security_manager, "require_confirmation", fake_require_confirmation)
    delete_calls = []
    monkeypatch.setattr(memory, "delete_project", lambda *a, **k: delete_calls.append(1) or True)

    bridge.request_delete_project(3)

    assert confirm_calls == ["delete_project"]
    assert delete_calls == []


def test_request_delete_project_emite_project_removed_solo_si_delete_project_devuelve_true(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)
    monkeypatch.setattr(memory, "delete_project", lambda *a, **k: False)
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])

    removed = []
    bridge.project_removed.connect(removed.append)

    bridge.request_delete_project(3)
    assert removed == []  # delete_project() devolvió False — no se emite

    monkeypatch.setattr(memory, "delete_project", lambda *a, **k: True)
    bridge.request_delete_project(3)
    assert removed == [3]


# ---------------------------------------------------------------------------
# REQ-022/CA-03, CA-04: set_model() no debe tener efecto real cuando hay un destino
# fijado por tarea para "razonamiento" — ni escribir config.json ni emitir el toast.
#
# `test-results-022.md` (hallazgo de orion-tester): el test de GUI más cercano
# (`test_webview_buttons.py::...se_deshabilita_si_esta_fijado_por_tarea`) prueba CA-02 (el
# menú no se abre) pero, justo porque el menú no se abre, nunca llega a invocar el slot
# `set_model()` — así que el gate real del lado servidor (línea 1067 de `bridge.py`, el que
# importa porque el slot es alcanzable desde cualquier script de la página, no solo desde
# el botón) nunca se ejercitaba en ningún test. Estos dos tests lo invocan directo.
# ---------------------------------------------------------------------------

def test_ca03_set_model_no_escribe_config_si_hay_destino_fijado_por_tarea(bridge, monkeypatch):
    import ai.llm_provider as llm_provider_module

    monkeypatch.setattr(
        llm_provider_module, "destinos_de_tarea",
        lambda tarea: [("openai", "gpt-4o-mini")] if tarea == "razonamiento" else [],
    )
    escrituras = []
    monkeypatch.setattr(
        bridge_module.config_manager, "set_ai_provider_and_model",
        lambda *a, **k: escrituras.append((a, k)),
    )

    bridge.set_model("deepseek", "deepseek-chat")

    assert escrituras == []


def test_ca04_set_model_no_emite_notice_si_hay_destino_fijado_por_tarea(bridge, monkeypatch):
    import ai.llm_provider as llm_provider_module

    monkeypatch.setattr(
        llm_provider_module, "destinos_de_tarea",
        lambda tarea: [("openai", "gpt-4o-mini")] if tarea == "razonamiento" else [],
    )
    notices = []
    bridge.notice_shown.connect(lambda nivel, msg: notices.append((nivel, msg)))

    bridge.set_model("deepseek", "deepseek-chat")

    assert notices == []


def test_ca05_set_model_sin_destino_fijado_escribe_config_y_avisa(bridge, monkeypatch):
    """Regresión — sin destino fijado por tarea, el comportamiento pre-REQ-022 sigue
    intacto: `set_model()` SÍ escribe `config.json` y SÍ emite el toast de confirmación."""
    import ai.llm_provider as llm_provider_module

    monkeypatch.setattr(llm_provider_module, "destinos_de_tarea", lambda tarea: [])
    escrituras = []
    monkeypatch.setattr(
        bridge_module.config_manager, "set_ai_provider_and_model",
        lambda *a, **k: escrituras.append((a, k)),
    )
    monkeypatch.setattr(bridge_module, "_build_models_payload", lambda: {})
    notices = []
    bridge.notice_shown.connect(lambda nivel, msg: notices.append((nivel, msg)))

    bridge.set_model("deepseek", "deepseek-chat")

    assert escrituras == [(("deepseek", "deepseek-chat"), {})]
    assert notices and notices[0][0] == "ok"


# ---------------------------------------------------------------------------
# REQ-019/CA-05, CA-08, CA-16, CA-19, CA-21: sección "Seguridad" de Configuración
# ---------------------------------------------------------------------------

# Mismas 10 claves RED de REQ-005 (core/security_manager.py:_register_default_actions) —
# CA-08: ninguna fila del catálogo v1 puede coincidir con ellas.
_RED_CATEGORIES = [
    "format_disk", "delete_database", "expose_secrets", "modify_source_code",
    "send_email_as_user", "post_social_media", "elevated_system_command",
    "install_uninstall_software", "modify_system_env_vars", "grant_third_party_access",
]


def test_ca08_catalogo_v1_nunca_incluye_ninguna_clave_red():
    all_keys = [key for row in bridge_module._SECURITY_ROWS_V1 for key in row["keys"]]
    assert not (set(all_keys) & set(_RED_CATEGORIES))


def test_ca19_request_security_overrides_no_se_llama_en_request_initial_state(bridge, monkeypatch):
    from ai.memory_manager import memory
    import config_manager

    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "dark")

    received = []
    bridge.security_overrides_loaded.connect(lambda j: received.append(j))

    bridge.request_initial_state()

    assert received == []  # CA-19: carga perezosa, nunca desde el arranque


def test_request_security_overrides_emite_las_8_filas_del_catalogo_v1(bridge, monkeypatch):
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    monkeypatch.setattr(security_manager, "classify_action_base", lambda name: RiskLevel.GREEN)

    received = []
    bridge.security_overrides_loaded.connect(lambda j: received.append(json.loads(j)))

    bridge.request_security_overrides()

    assert len(received[0]) == 8
    assert all(row["options"] == ["green", "yellow"] for row in received[0])  # CA-16: techo v1


def test_ca16_fila_con_effective_level_yellow_solo_ofrece_yellow(monkeypatch):
    """Nota no bloqueante (3) del handoff de orion-security: la sección 'Pruebas
    sugeridas' pre-addendum de arquitectura-019.md decía `["yellow", "red"]` para este
    caso — ese valor quedó obsoleto con el techo v1 de §11.3. El resultado correcto es
    `["yellow"]` (sin "red")."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.YELLOW)
    monkeypatch.setattr(security_manager, "classify_action_base", lambda name: RiskLevel.YELLOW)

    payload = bridge_module._build_security_overrides_payload()
    row = next(r for r in payload if r["row_id"] == "open_chrome")
    assert row["options"] == ["yellow"]


def test_build_security_overrides_payload_omite_fila_con_clave_sin_clasificar(monkeypatch):
    from core.security_manager import RiskLevel, security_manager

    def fake_classify(name):
        return None if name in ("open_app", "OPEN_APP") else RiskLevel.GREEN

    monkeypatch.setattr(security_manager, "classify_action", fake_classify)
    monkeypatch.setattr(security_manager, "classify_action_base", fake_classify)

    payload = bridge_module._build_security_overrides_payload()
    assert "open_app" not in [row["row_id"] for row in payload]
    assert len(payload) == 7


def test_save_security_override_row_con_clave_sin_clasificar_se_rechaza(bridge, monkeypatch):
    """CA-05 — una clave del catálogo que dejó de estar registrada en código nunca se
    persiste, y la fila se rechaza completa."""
    from core.security_manager import RiskLevel, security_manager

    def fake_classify(name):
        return None if name == "OPEN_APP" else RiskLevel.GREEN

    monkeypatch.setattr(security_manager, "classify_action", fake_classify)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_app", "yellow")

    assert save_calls == []
    assert rejected == ["open_app"]


def test_ca21_save_security_override_rechaza_intento_de_bajada(bridge, monkeypatch):
    """CA-21 — defensa en profundidad: un intento directo al slot (sin pasar por el
    <select> de JS) con un nivel inferior al vigente se rechaza igual."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.YELLOW)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "green")

    assert save_calls == []
    assert rejected == ["open_chrome"]


def test_save_security_override_rechaza_nivel_por_encima_del_techo_v1(bridge, monkeypatch):
    """§11.3 — el catálogo v1 nunca acepta 'red', ni siquiera invocando el slot directo."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "red")

    assert save_calls == []
    assert rejected == ["open_chrome"]


def test_save_security_override_con_row_id_desconocido_se_rechaza(bridge, monkeypatch):
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("__row_id_inexistente__", "yellow")

    assert save_calls == []
    assert rejected == ["__row_id_inexistente__"]


def test_save_security_override_con_nivel_invalido_se_rechaza(bridge, monkeypatch):
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    rejected = []
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "purple")

    assert save_calls == []
    assert rejected == ["open_chrome"]


def test_save_security_override_persiste_todas_las_claves_de_la_fila_en_una_sola_llamada(bridge, monkeypatch):
    """Atomicidad de fila (arquitectura-019.md §2, riesgo dedicado en la tabla de
    mitigación): `open_app` cubre 2 claves internas (`open_app` + `OPEN_APP`) — deben
    persistirse juntas en una única llamada, nunca en dos separadas."""
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    save_calls = []
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: save_calls.append(d))

    saved = []
    bridge.security_override_saved.connect(lambda row_id, level: saved.append((row_id, level)))

    bridge.save_security_override("open_app", "yellow")

    assert len(save_calls) == 1
    assert save_calls[0] == {"open_app": "yellow", "OPEN_APP": "yellow"}
    assert saved == [("open_app", "yellow")]


def test_save_security_override_exitoso_emite_security_override_saved(bridge, monkeypatch):
    from core.security_manager import RiskLevel, security_manager

    monkeypatch.setattr(security_manager, "classify_action", lambda name: RiskLevel.GREEN)
    monkeypatch.setattr("core.security_config.save_security_overrides", lambda d: None)

    saved = []
    rejected = []
    bridge.security_override_saved.connect(lambda row_id, level: saved.append((row_id, level)))
    bridge.security_override_save_rejected.connect(rejected.append)

    bridge.save_security_override("open_chrome", "yellow")

    assert saved == [("open_chrome", "yellow")]
    assert rejected == []


# ---------------------------------------------------------------------------
# CA-42: superficie del contrato — nada oculto, nada de más
# ---------------------------------------------------------------------------

_EXPECTED_SLOTS = [
    "request_initial_state", "send_message", "new_conversation", "select_conversation",
    "request_delete_conversation", "load_more_conversations", "run_chip_action",
    "set_theme", "toggle_wake_word", "confirm_response", "start_resize", "start_move",
    "window_minimize", "window_toggle_maximize", "window_close",
    # REQ-016
    "request_tasks", "create_task", "complete_task", "request_delete_task",
    "request_projects", "create_project", "assign_conversation_to_project",
    "unassign_conversation_from_project", "request_project_conversations",
    "request_delete_project",
    # REQ-019
    "request_security_overrides", "save_security_override",
]

_EXPECTED_SIGNALS = [
    "conversation_list_updated", "conversation_cleared", "conversation_removed",
    "turns_loaded", "message_appended", "typing_started", "typing_stopped",
    "gui_state_changed", "wake_state_changed", "theme_changed",
    "confirmation_requested", "file_attached", "chips_loaded", "error_occurred",
    "attachment_preview", "image_loaded",   # REQ-054
    "last_turn_removed", "composer_text_requested",   # REQ-055
    # REQ-016
    "tasks_loaded", "projects_loaded", "project_conversations_loaded", "project_removed",
    # REQ-019
    "security_overrides_loaded", "security_override_saved", "security_override_save_rejected",
]


@pytest.mark.parametrize("slot_name", _EXPECTED_SLOTS)
def test_bridge_expone_cada_comando_del_contrato(bridge, slot_name):
    assert callable(getattr(bridge, slot_name, None)), f"falta el slot '{slot_name}'"


@pytest.mark.parametrize("signal_name", _EXPECTED_SIGNALS)
def test_bridge_expone_cada_evento_del_contrato(bridge, signal_name):
    assert hasattr(bridge, signal_name), f"falta la señal '{signal_name}'"


# ---------------------------------------------------------------------------
# REQ-033: el interruptor del modo autonomía
#
# Se prueba desde el bridge y no solo desde `core/autonomy.py` porque el primer intento de
# este slot usaba `security_manager` sin importarlo: compilaba perfecto y habría reventado
# con NameError la primera vez que alguien tocara el interruptor. `py_compile` no ve eso;
# un test que llama al slot, sí.
# ---------------------------------------------------------------------------

@pytest.fixture
def autonomia_aislada(monkeypatch, tmp_path):
    """El archivo real del usuario no se toca en ningún test."""
    import core.autonomy as autonomy

    monkeypatch.setattr(autonomy, "ARCHIVO_AUTONOMIA", str(tmp_path / "autonomy_mode.json"))
    return autonomy


def test_encender_el_nivel_proyectos_lo_guarda_y_lo_anuncia(bridge, qtbot, autonomia_aislada):
    with qtbot.waitSignal(bridge.autonomy_changed, timeout=1000) as senal:
        bridge.set_autonomy_mode("proyectos", "")

    assert autonomia_aislada.modo_actual() == "proyectos"
    assert json.loads(senal.args[0])["activo"] is True


def test_apagarlo_vuelve_a_normal(bridge, qtbot, autonomia_aislada):
    bridge.set_autonomy_mode("proyectos", "")

    bridge.set_autonomy_mode("normal", "")

    assert autonomia_aislada.modo_actual() == "normal"


def test_un_nivel_inventado_no_cambia_nada(bridge, qtbot, autonomia_aislada):
    with qtbot.waitSignal(bridge.error_occurred, timeout=1000):
        bridge.set_autonomy_mode("dios", "")

    assert autonomia_aislada.modo_actual() == "normal"


def test_el_nivel_total_sin_pin_configurado_no_se_enciende(bridge, qtbot, autonomia_aislada,
                                                          monkeypatch):
    """Sin PIN no hay nada que verificar: encenderlo igual sería teatro."""
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "has_pin", lambda: False)

    with qtbot.waitSignal(bridge.error_occurred, timeout=1000) as senal:
        bridge.set_autonomy_mode("total", "1234")

    assert autonomia_aislada.modo_actual() == "normal"
    assert "PIN" in senal.args[0]


def test_el_nivel_total_con_pin_incorrecto_no_se_enciende(bridge, qtbot, autonomia_aislada,
                                                         monkeypatch):
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "has_pin", lambda: True)
    monkeypatch.setattr(security_manager, "verify_pin", lambda pin: False)

    with qtbot.waitSignal(bridge.error_occurred, timeout=1000):
        bridge.set_autonomy_mode("total", "mal")

    assert autonomia_aislada.modo_actual() == "normal"


def test_el_nivel_total_sin_repositorio_git_no_se_enciende(bridge, qtbot, autonomia_aislada,
                                                           monkeypatch):
    """La rama es la red que hace reversible que toque su propio código. Sin ella, no."""
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "has_pin", lambda: True)
    monkeypatch.setattr(security_manager, "verify_pin", lambda pin: True)
    monkeypatch.setattr(
        "core.autonomy.preparar_rama",
        lambda: (_ for _ in ()).throw(RuntimeError("no es un repositorio git")),
    )

    with qtbot.waitSignal(bridge.error_occurred, timeout=1000):
        bridge.set_autonomy_mode("total", "correcto")

    assert autonomia_aislada.modo_actual() == "normal"


def test_el_nivel_total_con_pin_y_rama_se_enciende(bridge, qtbot, autonomia_aislada, monkeypatch):
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "has_pin", lambda: True)
    monkeypatch.setattr(security_manager, "verify_pin", lambda pin: True)
    monkeypatch.setattr("core.autonomy.preparar_rama", lambda: ("autonomia/prueba", "main"))

    with qtbot.waitSignal(bridge.autonomy_changed, timeout=1000) as senal:
        bridge.set_autonomy_mode("total", "correcto")

    assert autonomia_aislada.modo_actual() == "total"
    estado = json.loads(senal.args[0])
    assert estado["rama"] == "autonomia/prueba"


def test_encender_la_autonomia_no_es_una_herramienta_del_agente():
    """La regla que sostiene el resto: si el agente pudiera encender su propia autonomía,
    bastaría una instrucción inyectada en una página para que se suelte solo."""
    import agents.tool_registry as tool_registry

    nombres = tool_registry.list_tool_names()
    assert not [n for n in nombres if "autonom" in n.lower()], (
        "no puede existir una tool que encienda el modo autonomía"
    )


# ---------------------------------------------------------------------------
# REQ-053: los pasos del turno viajan con la respuesta
# ---------------------------------------------------------------------------

def test_los_pasos_del_turno_llegan_con_la_respuesta_y_no_se_arrastran(bridge, monkeypatch):
    """Lo que el reportero de progreso cuenta durante el turno (las herramientas) va en
    `pasos` del mensaje del agente; «Pensando» y «Entendiendo…» no son pasos; dos avisos
    iguales seguidos cuentan una vez; y el turno siguiente arranca en cero."""
    from ai.memory_manager import memory
    from core import progress

    def resolve_falso(*a, **k):
        progress.report("Entendiendo lo que me pides")
        progress.report("Pensando")
        progress.report("Buscando en internet: clima Bogotá")
        progress.report("Buscando en internet: clima Bogotá")
        progress.report("Pensando (2)")
        progress.report("Leyendo la página: https://ejemplo.com")
        return SimpleNamespace(text="18 grados", matched_by="llm")

    monkeypatch.setattr("core.resolution.resolve", resolve_falso)
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "c-1")
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])

    messages = []
    bridge.message_appended.connect(lambda j: messages.append(json.loads(j)))

    bridge.send_message("qué clima hace")
    respuesta = messages[-1]
    assert respuesta["role"] == "assistant"
    assert respuesta["pasos"] == [
        "Buscando en internet: clima Bogotá",
        "Leyendo la página: https://ejemplo.com",
    ]
    assert "pasos" not in messages[0]          # el eco del usuario no lleva pasos

    monkeypatch.setattr("core.resolution.resolve",
                        lambda *a, **k: SimpleNamespace(text="hola", matched_by="llm"))
    bridge.send_message("hola")
    assert messages[-1]["pasos"] == []


def test_un_turno_que_falla_entrega_los_pasos_que_alcanzo(bridge, monkeypatch):
    from core import progress

    def resolve_que_explota(*a, **k):
        progress.report("Buscando en internet: algo")
        raise RuntimeError("sin red")

    monkeypatch.setattr("core.resolution.resolve", resolve_que_explota)
    messages = []
    bridge.message_appended.connect(lambda j: messages.append(json.loads(j)))

    bridge.send_message("buscá algo")

    assert "Error" in messages[-1]["html"]
    assert messages[-1]["pasos"] == ["Buscando en internet: algo"]
    assert bridge._pasos_del_turno == []


def test_regenerate_last_mientras_se_guarda_el_turno_espera_a_que_termine(bridge, monkeypatch, fake_run_async):
    """`store_turn` corre en otro hilo y tarda (embeddings). Si «Regenerar» llega antes de
    que termine, borrar "el último par" borraría el ANTERIOR: la acción se encola y corre
    cuando el guardado avisa que terminó."""
    from ai.memory_manager import memory

    borrados = []
    monkeypatch.setattr(memory, "delete_last_turn",
                        lambda conversation_id, user_id="default": borrados.append(conversation_id)
                        or SimpleNamespace(id=7, role="user", text="otra vez", timestamp="t"))
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])
    bridge._conversation_id = "conv-1"
    bridge._guardando_turno = True

    bridge.regenerate_last()
    assert borrados == []                       # todavía no

    bridge._tras_guardar_turno()                # el guardado terminó
    assert borrados == ["conv-1"]
    assert bridge._guardando_turno is False
    assert bridge._accion_tras_guardar is None
    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert llamada["args"][0] == "otra vez"


def test_si_el_guardado_falla_la_accion_encolada_se_descarta(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "delete_last_turn", lambda *a, **k: pytest.fail("no debe borrar"))
    bridge._conversation_id = "conv-1"
    bridge._guardando_turno = True
    bridge.edit_last()

    bridge._on_error_guardando_turno("disco lleno")

    assert bridge._guardando_turno is False
    assert bridge._accion_tras_guardar is None


# ---------------------------------------------------------------------------
# REQ-056: exportar una conversación a Markdown desde la barra lateral
# ---------------------------------------------------------------------------

def test_export_conversation_pide_confirmacion_amarilla_y_exporta(bridge, monkeypatch):
    from ai.memory_manager import memory
    from core import exportar_chat
    from core.security_manager import security_manager

    confirmaciones = []
    monkeypatch.setattr(security_manager, "require_confirmation",
                        lambda action_name, channel, details="", user_id="default":
                        confirmaciones.append((action_name, details)) or True)
    monkeypatch.setattr(memory, "get_conversation_title", lambda cid, user_id="default": "Tesis")
    monkeypatch.setattr(exportar_chat, "exportar",
                        lambda cid, user_id, carpeta=None, nombre=None: r"C:\Users\j\Desktop\Tesis.md")
    avisos = []
    bridge.notice_shown.connect(lambda tipo, texto: avisos.append((tipo, texto)))

    bridge.export_conversation("conv-1")

    assert confirmaciones[0][0] == "chat_export_current"
    assert "Tesis" in confirmaciones[0][1]           # la confirmación dice qué chat
    assert avisos == [("ok", r"Conversación guardada en C:\Users\j\Desktop\Tesis.md")]


def test_export_conversation_cancelada_no_escribe_nada(bridge, monkeypatch):
    from core import exportar_chat
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: False)
    monkeypatch.setattr(exportar_chat, "exportar", lambda *a, **k: pytest.fail("no debe exportar"))
    avisos = []
    bridge.notice_shown.connect(lambda tipo, texto: avisos.append((tipo, texto)))

    bridge.export_conversation("conv-1")

    assert avisos == []


def test_export_conversation_muestra_el_rechazo_como_aviso(bridge, monkeypatch):
    from core import exportar_chat
    from core.documentos import DocumentoRechazado
    from core.security_manager import security_manager

    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)

    def _rechaza(*a, **k):
        raise DocumentoRechazado("Esa conversación no tiene mensajes guardados.")

    monkeypatch.setattr(exportar_chat, "exportar", _rechaza)
    avisos = []
    bridge.notice_shown.connect(lambda tipo, texto: avisos.append((tipo, texto)))

    bridge.export_conversation("conv-1")

    assert avisos == [("error", "Esa conversación no tiene mensajes guardados.")]


# ---------------------------------------------------------------------------
# Revisión de la noche del 2026-09-20 — regenerar/editar sobre un par que no se guardó
# ---------------------------------------------------------------------------

def test_regenerar_tras_un_error_no_toca_la_base_y_reenvia_lo_que_se_ve(bridge, monkeypatch, fake_run_async):
    """Un turno que terminó en «Error: …» se muestra pero no se guarda. Regenerar sobre él
    borraba el par ANTERIOR de la base y reenviaba ese texto viejo."""
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "delete_last_turn", lambda *a, **k: pytest.fail("no debe borrar nada"))
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    bridge._conversation_id = "conv-1"
    bridge._ultimo_par_persistido = False
    bridge._ultimo_texto_usuario = "la que falló"
    quitados = []
    bridge.last_turn_removed.connect(lambda: quitados.append(True))

    bridge.regenerate_last()

    assert quitados == [True]
    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][-1]
    assert llamada["args"][0] == "la que falló"


def test_editar_tras_un_error_devuelve_al_cuadro_lo_que_se_ve(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "delete_last_turn", lambda *a, **k: pytest.fail("no debe borrar nada"))
    bridge._conversation_id = "conv-1"
    bridge._ultimo_par_persistido = False
    bridge._ultimo_texto_usuario = "la que falló"
    textos = []
    bridge.composer_text_requested.connect(textos.append)

    bridge.edit_last()

    assert textos == ["la que falló"]


def test_un_turno_que_falla_deja_el_par_como_no_persistido_y_uno_guardado_lo_marca(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])
    monkeypatch.setattr(memory, "get_conversation_title", lambda *a, **k: "x")
    monkeypatch.setattr(memory, "new_conversation_id", lambda: "conv-1")

    def _falla(*a, **k):
        raise RuntimeError("se cayó")

    # `fake_run_async` es síncrono: el fallo llega a `_on_resolve_error` dentro del send.
    monkeypatch.setattr("core.resolution.resolve", _falla)
    bridge.send_message("hola")
    assert bridge._ultimo_par_persistido is False
    assert bridge._ultimo_texto_usuario == "hola"

    monkeypatch.setattr("core.resolution.resolve",
                        lambda *a, **k: SimpleNamespace(text="bien", matched_by="claude"))
    bridge.send_message("otra")   # store_turn síncrono → _tras_guardar_turno
    assert bridge._ultimo_par_persistido is True


def test_regenerar_no_reenvia_si_la_conversacion_cambio_durante_el_borrado(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    def _borra_y_cambia(conversation_id, user_id="default"):
        bridge._conversation_id = "otra"       # el usuario abrió otro chat mientras tanto
        return SimpleNamespace(id=1, role="user", text="vieja", timestamp="t")

    monkeypatch.setattr(memory, "delete_last_turn", _borra_y_cambia)
    bridge._conversation_id = "conv-1"
    quitados = []
    bridge.last_turn_removed.connect(lambda: quitados.append(True))

    bridge.regenerate_last()

    assert quitados == []
    assert not [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"]
    assert bridge._resolution_in_flight is False


def test_el_titulo_se_pide_sin_el_marcador_del_adjunto(bridge, monkeypatch, fake_run_async, tmp_path):
    from ai.memory_manager import memory

    ruta = _captura(tmp_path)
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    pedidos = []
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])
    monkeypatch.setattr(memory, "get_conversation_title", lambda *a, **k: "")
    from core import titulos
    monkeypatch.setattr(titulos, "titular_si_corresponde",
                        lambda cid, u, a, user_id="default": pedidos.append(u) or False)
    monkeypatch.setattr("core.resolution.resolve",
                        lambda *a, **k: SimpleNamespace(text="Dice hola.", matched_by="claude"))
    bridge._pending_attachments = [ruta]

    bridge.send_message("¿qué dice esta captura tan larga que sí pasa el umbral?")

    assert pedidos == ["¿qué dice esta captura tan larga que sí pasa el umbral?"]


def test_renombrar_refresca_recientes_y_proyectos(bridge, monkeypatch):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "rename_conversation", lambda *a, **k: True)
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])
    monkeypatch.setattr(memory, "list_projects", lambda **k: [])
    listas, proyectos = [], []
    bridge.conversation_list_updated.connect(listas.append)
    bridge.projects_loaded.connect(proyectos.append)

    bridge.rename_conversation("conv-1", "Tesis")

    assert len(listas) == 1 and len(proyectos) == 1


def test_los_turnos_se_arman_fuera_del_hilo_de_la_gui(bridge, monkeypatch, fake_run_async):
    """Las miniaturas se decodifican con Pillow: el payload entero se arma en el worker y
    la GUI solo emite."""
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    bridge.select_conversation("conv-1")
    assert getattr(fake_run_async[-1]["fn"], "__name__", "") == "_cargar_turnos"


def test_los_turnos_de_una_conversacion_que_ya_no_esta_abierta_se_descartan(bridge, monkeypatch):
    """Dos clics rápidos: la carga lenta de A (muchas imágenes) llega con B ya abierta y
    no puede pintarse encima."""
    recibidos = []
    bridge.turns_loaded.connect(recibidos.append)
    bridge._conversation_id = "B"

    bridge._on_turns_loaded(("A", [{"id": 1, "role": "user", "html": "<p>de A</p>", "timestamp": "t"}]))
    assert recibidos == []

    bridge._on_turns_loaded(("B", [{"id": 2, "role": "user", "html": "<p>de B</p>", "timestamp": "t"}]))
    assert len(recibidos) == 1


def test_editar_reserva_el_turno_mientras_borra_y_lo_libera_al_volver(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    vistos = []

    def _borra(conversation_id, user_id="default"):
        vistos.append(bridge._resolution_in_flight)     # True mientras el borrado corre
        return SimpleNamespace(id=1, role="user", text="hola", timestamp="t")

    monkeypatch.setattr(memory, "delete_last_turn", _borra)
    bridge._conversation_id = "conv-1"

    bridge.edit_last()

    assert vistos == [True]
    assert bridge._resolution_in_flight is False


# ---------------------------------------------------------------------------
# REQ-063: varias imágenes por mensaje
# ---------------------------------------------------------------------------

def test_dos_imagenes_viajan_como_lista_y_la_burbuja_trae_dos_miniaturas(bridge, fake_run_async, tmp_path):
    a = _captura(tmp_path, "a.png")
    b = _captura(tmp_path, "b.png")
    bridge._pending_attachments = [a, b]
    recibidos = []
    bridge.message_appended.connect(lambda payload: recibidos.append(json.loads(payload)))
    vaciados = []
    bridge.attachments_cleared.connect(lambda: vaciados.append(True))

    bridge.send_message("compará estas dos")

    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert llamada["kwargs"]["image_path"] == [a, b]
    assert llamada["args"][0] == f"compará estas dos\n\n[Imagen adjunta: {a}]\n[Imagen adjunta: {b}]"
    usuario = [m for m in recibidos if m["role"] == "user"][0]
    assert [x["nombre"] for x in usuario["adjuntos"]] == ["a.png", "b.png"]
    assert all(x["miniatura"].startswith("data:image/") for x in usuario["adjuntos"])
    assert vaciados == [True]                       # los chips se van al mandar
    assert bridge._pending_attachments == []


def test_una_imagen_sola_sin_texto_tambien_es_un_mensaje(bridge, fake_run_async, tmp_path):
    ruta = _captura(tmp_path)
    bridge._pending_attachments = [ruta]

    bridge.send_message("")

    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][0]
    assert llamada["args"][0] == f"[Imagen adjunta: {ruta}]"
    assert llamada["kwargs"]["image_path"] == ruta


def test_sin_texto_ni_adjuntos_no_se_manda_nada(bridge, fake_run_async):
    bridge.send_message("")
    assert not [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"]


def test_el_tope_de_adjuntos_y_los_repetidos(bridge, tmp_path):
    from core import imagenes

    avisos = []
    bridge.notice_shown.connect(lambda tipo, texto: avisos.append(texto))
    rutas = [_captura(tmp_path, f"{i}.png") for i in range(imagenes.MAX_ADJUNTOS + 1)]

    for ruta in rutas[:-1]:
        assert bridge.attach_file(ruta) is True
    assert bridge.attach_file(rutas[-1]) is False          # el quinto no entra
    assert bridge._pending_attachments == rutas[:-1]
    assert any("Hasta 4 adjuntos" in a for a in avisos)

    assert bridge.attach_file(rutas[0]) is True             # repetido: no se duplica
    assert bridge._pending_attachments.count(rutas[0]) == 1
    assert any("ya está adjunto" in a for a in avisos)


def test_quitar_un_chip_saca_solo_ese_adjunto_y_vacio_saca_todos(bridge, tmp_path):
    a = _captura(tmp_path, "a.png")
    b = _captura(tmp_path, "b.png")
    bridge._pending_attachments = [a, b]

    bridge.clear_attachment(a)
    assert bridge._pending_attachments == [b]

    vaciados = []
    bridge.attachments_cleared.connect(lambda: vaciados.append(True))
    bridge.clear_attachment("")
    assert bridge._pending_attachments == [] and vaciados == [True]


def test_pegar_varios_archivos_del_explorador_los_adjunta_todos(bridge, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication

    archivos = []
    for nombre in ("uno.md", "dos.md", "tres.md"):
        ruta = tmp_path / nombre
        ruta.write_text("x", encoding="utf-8")
        archivos.append(str(ruta))
    monkeypatch.setattr(QApplication, "clipboard",
                        staticmethod(lambda: _PortapapelesFalso(urls=archivos)))

    bridge.paste_from_clipboard()

    assert bridge._pending_attachments == archivos


def test_editar_devuelve_todos_los_adjuntos_al_chip_y_regenerar_reenvia_todas_las_imagenes(bridge, monkeypatch, fake_run_async, tmp_path):
    from ai.memory_manager import memory

    a = _captura(tmp_path, "a.png")
    b = _captura(tmp_path, "b.png")
    texto = f"compará\n\n[Imagen adjunta: {a}]\n[Imagen adjunta: {b}]"
    monkeypatch.setattr(memory, "delete_last_turn",
                        lambda conversation_id, user_id="default": SimpleNamespace(id=7, role="user", text=texto, timestamp="t"))
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    bridge._conversation_id = "conv-1"

    bridge.edit_last()
    assert bridge._pending_attachments == [a, b]

    bridge._pending_attachments = []
    bridge.regenerate_last()
    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][-1]
    assert llamada["kwargs"]["image_path"] == [a, b]


# ---------------------------------------------------------------------------
# REQ-064: regenerar / editar desde cualquier punto (rebobinar)
# ---------------------------------------------------------------------------

def _memoria_para_rebobinar(monkeypatch, posteriores, texto="la pregunta del medio"):
    from ai.memory_manager import memory

    borrados = []
    monkeypatch.setattr(memory, "turnos_posteriores",
                        lambda conversation_id, desde_id, user_id="default": posteriores)
    monkeypatch.setattr(memory, "delete_turns_from",
                        lambda conversation_id, desde_id, user_id="default": borrados.append(desde_id)
                        or SimpleNamespace(id=desde_id, role="user", text=texto, timestamp="t"))
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    return borrados


def test_regenerar_desde_un_mensaje_del_medio_pide_confirmacion_y_rebobina(bridge, monkeypatch, fake_run_async):
    from core.security_manager import security_manager

    borrados = _memoria_para_rebobinar(monkeypatch, posteriores=3)
    confirmaciones = []
    monkeypatch.setattr(security_manager, "require_confirmation",
                        lambda action_name, channel, details="", user_id="default":
                        confirmaciones.append((action_name, details)) or True)
    bridge._conversation_id = "conv-1"
    quitados = []
    bridge.turns_removed_from.connect(quitados.append)

    bridge.regenerate_from(41)

    assert confirmaciones[0][0] == "chat_rewind"
    assert "3 mensajes posteriores" in confirmaciones[0][1]
    assert borrados == [41]
    assert quitados == [41]
    llamada = [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"][-1]
    assert llamada["args"][0] == "la pregunta del medio"
    assert bridge._resolution_in_flight is False


def test_cancelar_la_confirmacion_no_borra_ni_reenvia(bridge, monkeypatch, fake_run_async):
    from core.security_manager import security_manager

    borrados = _memoria_para_rebobinar(monkeypatch, posteriores=2)
    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: False)
    bridge._conversation_id = "conv-1"

    bridge.regenerate_from(41)

    assert borrados == []
    assert not [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"]
    assert bridge._resolution_in_flight is False


def test_sin_mensajes_posteriores_no_pregunta(bridge, monkeypatch, fake_run_async):
    from core.security_manager import security_manager

    borrados = _memoria_para_rebobinar(monkeypatch, posteriores=0)
    monkeypatch.setattr(security_manager, "require_confirmation",
                        lambda *a, **k: pytest.fail("no debe preguntar"))
    bridge._conversation_id = "conv-1"

    bridge.regenerate_from(41)

    assert borrados == [41]


def test_editar_desde_el_medio_devuelve_ese_texto_al_cuadro(bridge, monkeypatch, fake_run_async):
    from core.security_manager import security_manager

    _memoria_para_rebobinar(monkeypatch, posteriores=1, texto="corregime esto")
    monkeypatch.setattr(security_manager, "require_confirmation", lambda *a, **k: True)
    bridge._conversation_id = "conv-1"
    textos = []
    bridge.composer_text_requested.connect(textos.append)

    bridge.edit_from(41)

    assert textos == ["corregime esto"]
    assert not [c for c in fake_run_async if getattr(c["fn"], "__name__", "") == "resolve"]


def test_un_id_que_no_es_del_usuario_o_no_existe_solo_avisa(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "turnos_posteriores", lambda *a, **k: None)
    monkeypatch.setattr(memory, "delete_turns_from", lambda *a, **k: pytest.fail("no debe borrar"))
    bridge._conversation_id = "conv-1"
    avisos = []
    bridge.notice_shown.connect(lambda tipo, texto: avisos.append(texto))

    bridge.regenerate_from(999)

    assert avisos == ["No encontré ese mensaje en la conversación."]


def test_al_guardar_el_turno_se_emiten_los_ids_de_las_burbujas(bridge, monkeypatch, fake_run_async):
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: (10, 11))
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    monkeypatch.setattr(memory, "list_conversations", lambda **k: [])
    monkeypatch.setattr(memory, "get_conversation_title", lambda *a, **k: "x")
    ids = []
    bridge.turn_ids_assigned.connect(lambda u, a: ids.append((u, a)))

    bridge.send_message("hola")

    assert ids == [(10, 11)]
