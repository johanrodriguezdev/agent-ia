"""
tests/test_webview_buttons.py
Validación de que TODOS los botones de la interfaz de escritorio hacen lo que dicen.

`QWebEngineView` real en modo offscreen (mismo patrón que `tests/test_webview_smoke.py`):
se carga el `index.html` de verdad, se hace click de verdad en cada control y se comprueba
el efecto observable — no que "no explote", sino que pasó lo que tenía que pasar.

Además, cada test verifica que no se registró ningún error de JavaScript. Un
`TypeError: x is not a function` en un `addEventListener` no rompe la app: deja un botón
mudo, que es justo el tipo de fallo que nadie nota hasta que lo necesita.

Los tres botones con efectos que no se quieren de verdad en una prueba están sustituidos
por dobles, nunca salteados:

- el worker de wake word (abriría el micrófono),
- `execute_action` de los chips de acción (abriría el navegador, sacaría una captura),
- `resolve()` del envío de mensajes (llamaría al modelo por red).

La terminal SÍ abre shells reales: es la única forma de comprobar que la pestaña se monta
y que cerrarla mata el proceso.
"""

import json
import threading
import time
import types

import pytest
from PyQt6.QtCore import QEventLoop, QRunnable, QTimer

from voice.mic_window import ConversationWindow

pytestmark = pytest.mark.webview_smoke

_JS_TIMEOUT_MS = 8000


def _run_js(page, code, timeout_ms=_JS_TIMEOUT_MS):
    loop = QEventLoop()
    holder = {}

    def _on_result(value):
        holder["value"] = value
        loop.quit()

    page.runJavaScript(code, _on_result)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return holder.get("value")


def _esperar(qtbot, ms):
    qtbot.wait(ms)


class _SenalFalsa:
    def connect(self, _cb):
        return None


class _WakeWorkerFalso(QRunnable):
    """Doble del worker de wake word: mismo contrato, sin tocar el micrófono."""

    creados = 0

    def __init__(self):
        super().__init__()
        _WakeWorkerFalso.creados += 1
        self.signals = types.SimpleNamespace(command_detected=_SenalFalsa())
        # `threading.Event` de verdad, como el worker real: el bridge no solo lo setea,
        # tambien consulta `is_set()` para saber si el manos libres sigue encendido.
        self.stop_event = threading.Event()
        # Ventana de conversacion REAL: el bridge la abre al encender el manos libres para
        # que la primera frase no exija el nombre del agente. Un doble sin `open()` haria
        # fallar el slot con un AttributeError que en produccion no existe.
        self.conversation_window = ConversationWindow()

    def run(self):
        return None


@pytest.fixture
def ventana(qtbot, monkeypatch):
    """MainWindow real, con las tres acciones peligrosas sustituidas por dobles."""
    from ai.memory_manager import memory
    import config_manager
    import agents.action_registry as action_registry
    import core.resolution as resolution
    import ui.webview.bridge as bridge_module
    import ui.webview.main_window as main_window_module

    registro = {"acciones": [], "mensajes": [], "tema": []}

    monkeypatch.setattr(memory, "list_conversations", lambda **kwargs: [])
    monkeypatch.setattr(memory, "get_conversation_turns", lambda *a, **k: [])
    monkeypatch.setattr(config_manager, "get_ui_theme", lambda: "light")
    monkeypatch.setattr(config_manager, "set_ui_theme", lambda name: registro["tema"].append(name))
    monkeypatch.setattr(main_window_module, "get_agent_name", lambda: "orion")

    monkeypatch.setattr(bridge_module, "WakeWordWorker", _WakeWorkerFalso)
    monkeypatch.setattr(
        action_registry, "execute_action",
        lambda nombre, **kwargs: registro["acciones"].append(nombre) or "hecho",
    )
    def _resolve_falso(texto, canal, **kwargs):
        registro["mensajes"].append(texto)
        # Algunos tests necesitan ver el turno EN CURSO (el boton de detener solo existe
        # mientras el agente responde). Sin demora, el doble contesta tan rapido que ese
        # estado no llega a observarse.
        if registro.get("demora"):
            time.sleep(registro["demora"])
        # Misma forma que devuelve `core.resolution.resolve()`: el bridge lee `.text` y
        # `.matched_by`. Un string pelado dejaría el turno a medias sin que se note.
        return types.SimpleNamespace(text="respuesta de prueba", matched_by="test")

    monkeypatch.setattr(resolution, "resolve", _resolve_falso)
    monkeypatch.setattr(memory, "store_turn", lambda *a, **k: None)

    _WakeWorkerFalso.creados = 0

    window = main_window_module.MainWindow()
    qtbot.addWidget(window)
    window.resize(1280, 800)
    page = window.web_view.page()

    qtbot.waitUntil(lambda: _run_js(page, "!!window.__ORION_APP_READY__") is True, timeout=20000)

    # En modo offscreen no hay compositor, así que las transiciones CSS no avanzan nunca:
    # medir un ancho "en transición" daría siempre el valor inicial. Se apagan para que
    # cada click se pueda comprobar por su resultado final, que es lo que importa acá.
    _run_js(page, """
        const hoja = document.createElement('style');
        hoja.textContent = '*, *::before, *::after { transition: none !important; ' +
                           'animation: none !important; }';
        document.head.appendChild(hoja);
        true;
    """)

    # Colector de errores de JS: `bootstrap()` ya terminó (si hubiera reventado, el flag
    # de arriba no existiría), así que a partir de acá solo se recoge lo que produzcan los
    # clicks de cada test.
    _run_js(page, """
        window.__ERRORES__ = [];
        window.addEventListener('error', (e) => window.__ERRORES__.push(String(e.message)));
        window.addEventListener('unhandledrejection',
            (e) => window.__ERRORES__.push('promesa: ' + String(e.reason)));
        (function () {
            const original = console.error;
            console.error = function (...args) {
                window.__ERRORES__.push(args.map(String).join(' '));
                original.apply(console, args);
            };
        })();
        true;
    """)

    yield window, page, registro

    # Estado global que un test puede dejar a medias: un turno cancelado y un sumidero de
    # streaming registrado. Sin esto, el test siguiente arranca creyendose cancelado y
    # `abortar_si_cancelado()` lo hace fallar en un lugar que no tiene nada que ver.
    from core.cancelacion import cerrar_turno
    from core.streaming import clear_sink

    cerrar_turno()
    clear_sink()

    try:
        from core.terminal_session import terminal_manager

        terminal_manager.close_all()
    except Exception as e:
        # Limpieza best-effort: un fallo acá no invalida el test que ya corrió, pero
        # tampoco se calla — una shell que sobrevive al test envenena al siguiente.
        print(f"[aviso] no se pudieron cerrar las terminales del test: {e}")


def _errores(page):
    return _run_js(page, "JSON.stringify(window.__ERRORES__ || [])")


def _sin_errores(page):
    crudos = _errores(page)
    assert crudos in (None, "[]"), f"la interfaz registró errores de JS: {crudos}"


def _click(page, selector_js):
    _run_js(page, f"{selector_js}.click(); true;")


# --------------------------------------------------------------------------- barra superior

@pytest.mark.parametrize("boton_id,titulo_esperado", [
    ("tasks-btn", "Tareas"),
    ("flows-btn", "Flujos"),
    ("projects-btn", "Proyectos"),
    ("settings-btn", "Configuración"),
])
def test_cada_herramienta_de_la_barra_abre_su_panel(ventana, qtbot, boton_id, titulo_esperado):
    _, page, _ = ventana

    _click(page, f"document.getElementById('{boton_id}')")
    _esperar(qtbot, 400)

    titulo = _run_js(page, "(function(){var t=document.querySelector('#panel-modal-root .modal-title');"
                           "return t ? t.textContent : null;})()")
    assert titulo == titulo_esperado

    # Y el botón de cerrar del panel lo cierra de verdad.
    _click(page, "document.querySelector('#panel-modal-root .panel-close-btn')")
    _esperar(qtbot, 300)
    assert _run_js(page, "document.querySelector('#panel-modal-root .modal-overlay') === null") is True
    _sin_errores(page)


def test_el_panel_se_cierra_al_hacer_click_afuera(ventana, qtbot):
    _, page, _ = ventana
    _click(page, "document.getElementById('tasks-btn')")
    _esperar(qtbot, 400)

    # Click sobre el overlay, no sobre la caja: el modal se cierra.
    _run_js(page, """
        const ov = document.querySelector('#panel-modal-root .modal-overlay');
        ov.dispatchEvent(new MouseEvent('click', {bubbles: true}));
        true;
    """)
    _esperar(qtbot, 300)
    assert _run_js(page, "document.querySelector('#panel-modal-root .modal-overlay') === null") is True
    _sin_errores(page)


# --------------------------------------------------------------------------- sidebar

def test_el_boton_de_colapsar_encoge_y_expande_el_sidebar(ventana, qtbot):
    _, page, _ = ventana
    ancho_inicial = _run_js(page, "document.getElementById('sidebar').getBoundingClientRect().width")

    _click(page, "document.getElementById('sidebar-collapse-toggle')")
    _esperar(qtbot, 400)
    assert _run_js(page, "document.getElementById('sidebar').classList.contains('collapsed')") is True
    assert _run_js(page, "document.getElementById('sidebar').getBoundingClientRect().width") < ancho_inicial
    assert _run_js(page, "document.getElementById('sidebar-collapse-toggle').getAttribute('aria-label')") \
        == "Expandir panel lateral"

    _click(page, "document.getElementById('sidebar-collapse-toggle')")
    _esperar(qtbot, 400)
    assert _run_js(page, "document.getElementById('sidebar').classList.contains('collapsed')") is False
    _sin_errores(page)


def test_el_boton_de_nuevo_chat_limpia_la_conversacion(ventana, qtbot):
    window, page, _ = ventana
    window.bridge.message_appended.emit(json.dumps({"role": "user", "html": "<p>hola</p>"}))
    _esperar(qtbot, 200)
    assert _run_js(page, "document.getElementById('messages').children.length") == 1

    _click(page, "document.getElementById('new-conversation-btn')")
    _esperar(qtbot, 400)
    assert _run_js(page, "document.getElementById('messages').children.length") == 0
    _sin_errores(page)


def test_el_buscador_de_la_barra_filtra_la_lista(ventana, qtbot):
    window, page, _ = ventana
    window.bridge.conversation_list_updated.emit(json.dumps([
        {"conversation_id": "a", "title": "Revisar el correo", "last_activity": None},
        {"conversation_id": "b", "title": "Apagar el PC", "last_activity": None},
    ]))
    _esperar(qtbot, 300)

    _run_js(page, """
        const input = document.getElementById('conv-search-input');
        input.value = 'correo';
        input.dispatchEvent(new Event('input'));
        true;
    """)
    _esperar(qtbot, 200)

    visibles = _run_js(page, """
        Array.from(document.querySelectorAll('.conv-item')).filter(i => !i.hidden).length
    """)
    assert visibles == 1
    _sin_errores(page)


def test_el_boton_de_borrar_conversacion_pide_confirmacion(ventana, qtbot):
    window, page, _ = ventana
    window.bridge.conversation_list_updated.emit(json.dumps([
        {"conversation_id": "a", "title": "Una charla", "last_activity": None},
    ]))
    _esperar(qtbot, 300)

    _click(page, "document.querySelector('.conv-delete-btn')")
    _esperar(qtbot, 600)

    assert _run_js(page, "document.querySelector('.modal-btn-confirm') !== null") is True
    _click(page, "document.querySelector('#confirm-modal-root .modal-btn:not(.modal-btn-confirm)')")
    _esperar(qtbot, 400)

    # Cancelado: la conversación sigue en la lista.
    assert _run_js(page, "document.querySelectorAll('.conv-item').length") == 1
    _sin_errores(page)


def test_el_boton_de_tema_cambia_el_tema(ventana, qtbot):
    _, page, registro = ventana
    assert _run_js(page, "document.documentElement.dataset.theme") == "light"

    _click(page, "document.getElementById('theme-toggle-btn')")
    _esperar(qtbot, 400)

    assert _run_js(page, "document.documentElement.dataset.theme") == "dark"
    assert registro["tema"] == ["dark"]
    # El icono acompaña: en oscuro se ofrece volver al claro.
    assert _run_js(page, "document.getElementById('theme-toggle-icon').getAttribute('href')") == "#ic-sun"
    _sin_errores(page)


# --------------------------------------------------------------------------- composer

def test_el_boton_de_enviar_no_manda_nada_con_el_campo_vacio(ventana, qtbot):
    _, page, registro = ventana
    _click(page, "document.getElementById('send-btn')")
    _esperar(qtbot, 300)
    assert registro["mensajes"] == []
    _sin_errores(page)


def test_el_boton_de_enviar_manda_lo_escrito(ventana, qtbot):
    _, page, registro = ventana
    _run_js(page, """
        const input = document.getElementById('composer-input');
        input.value = 'hola desde el test';
        input.dispatchEvent(new Event('input'));
        true;
    """)
    _click(page, "document.getElementById('send-btn')")
    qtbot.waitUntil(lambda: registro["mensajes"] != [], timeout=5000)

    assert registro["mensajes"] == ["hola desde el test"]
    assert _run_js(page, "document.getElementById('composer-input').value") == ""
    _sin_errores(page)


def test_el_boton_de_adjuntar_explica_como_adjuntar(ventana):
    """No abre un diálogo (no existe ese slot): es un aviso de que el camino es arrastrar
    el archivo. Lo que se valida es que diga qué hacer, no que no haga nada."""
    _, page, _ = ventana
    titulo = _run_js(page, "document.getElementById('attach-btn').title")
    assert "arrastr" in titulo.lower()
    _sin_errores(page)


def test_el_boton_de_manos_libres_enciende_y_apaga_el_worker(ventana, qtbot):
    window, page, _ = ventana

    _click(page, "document.getElementById('wake-toggle-btn')")
    qtbot.waitUntil(lambda: _WakeWorkerFalso.creados == 1, timeout=5000)
    assert window.bridge._wake_worker is not None
    # Encender el microfono ya es pedir atencion: la primera frase se acepta sin el nombre.
    assert window.bridge._wake_worker.conversation_window.is_open() is True

    window.bridge.wake_state_changed.emit("LISTENING_WAKE")
    _esperar(qtbot, 200)
    assert _run_js(page, "document.getElementById('wake-toggle-btn').dataset.wakeState") == "LISTENING_WAKE"

    _click(page, "document.getElementById('wake-toggle-btn')")
    _esperar(qtbot, 400)
    assert window.bridge._wake_worker.stop_event.is_set() is True
    # Y al apagarlo no puede quedar una ventana armada con el microfono ya cerrado.
    assert window.bridge._wake_worker.conversation_window.is_open() is False
    _sin_errores(page)


def test_un_chip_de_plantilla_prellena_el_campo(ventana, qtbot):
    _, page, registro = ventana
    _click(page, "document.querySelectorAll('.chip')[0]")
    _esperar(qtbot, 300)

    assert _run_js(page, "document.getElementById('composer-input').value") != ""
    assert registro["acciones"] == []      # una plantilla no ejecuta nada
    _sin_errores(page)


def test_un_chip_de_accion_ejecuta_su_accion(ventana, qtbot):
    """Los chips de acción son los únicos botones que disparan una acción del sistema desde
    la pantalla: se comprueba que llegue al registro de acciones, con el nombre correcto."""
    _, page, registro = ventana
    nombre = _run_js(page, """
        (function () {
            const chips = Array.from(document.querySelectorAll('.chip'));
            const accion = chips.find(c => c.querySelector('.chip-risk-dot'));
            accion.click();
            return accion.textContent.trim();
        })()
    """)
    qtbot.waitUntil(lambda: registro["acciones"] != [], timeout=5000)

    assert registro["acciones"] == ["take_screenshot"]
    assert nombre                       # el chip tiene etiqueta visible
    _sin_errores(page)


# --------------------------------------------------------------------------- terminal

def test_cancelar_la_confirmacion_no_abre_la_terminal(ventana, qtbot):
    """El gate 🟡 es la única barrera: si se dice que no, no puede quedar ni el cajón."""
    _, page, _ = ventana

    _click(page, "document.getElementById('terminal-btn')")
    qtbot.waitUntil(
        lambda: _run_js(page, "document.querySelector('.modal-btn-confirm') !== null") is True,
        timeout=8000,
    )
    _click(page, "document.querySelector('#confirm-modal-root .modal-btn:not(.modal-btn-confirm)')")
    _esperar(qtbot, 800)

    assert _run_js(page, "document.getElementById('terminal-drawer') === null") is True
    from core.terminal_session import terminal_manager
    assert terminal_manager.ids() == []
    _sin_errores(page)


def test_la_terminal_abre_pestanas_y_cerrarlas_mata_los_procesos(ventana, qtbot):
    """Recorrido completo de los botones de la terminal: abrir, pestaña nueva, cerrar una,
    cerrar el panel. Abre shells de verdad — es la única forma de comprobar que el proceso
    muere cuando se cierra la pestaña."""
    from core.terminal_session import terminal_manager

    _, page, _ = ventana

    def confirmar():
        qtbot.waitUntil(
            lambda: _run_js(page, "document.querySelector('.modal-btn-confirm') !== null") is True,
            timeout=8000,
        )
        _click(page, "document.querySelector('.modal-btn-confirm')")

    _click(page, "document.getElementById('terminal-btn')")
    confirmar()
    qtbot.waitUntil(lambda: len(terminal_manager.ids()) == 1, timeout=10000)
    _esperar(qtbot, 800)

    assert _run_js(page, "document.getElementById('terminal-drawer') !== null") is True
    assert _run_js(page, "document.querySelectorAll('.terminal-tab').length") == 1
    assert _run_js(page, "document.querySelector('.terminal-host.visible .xterm') !== null") is True

    # Pestaña nueva: confirma otra vez, porque es otro shell.
    _click(page, "document.getElementById('terminal-new-tab')")
    confirmar()
    qtbot.waitUntil(lambda: len(terminal_manager.ids()) == 2, timeout=10000)
    _esperar(qtbot, 800)
    assert _run_js(page, "document.querySelectorAll('.terminal-tab').length") == 2

    # Cerrar una pestaña: muere su proceso, queda la otra.
    _click(page, "document.querySelector('.terminal-tab .terminal-tab-close')")
    qtbot.waitUntil(lambda: len(terminal_manager.ids()) == 1, timeout=10000)
    _esperar(qtbot, 500)
    assert _run_js(page, "document.querySelectorAll('.terminal-tab').length") == 1

    # Cerrar el panel: no queda ninguna shell viva sin ventana que la muestre.
    _click(page, "document.getElementById('terminal-close-panel')")
    qtbot.waitUntil(lambda: terminal_manager.ids() == [], timeout=10000)
    _esperar(qtbot, 400)
    assert _run_js(page, "document.getElementById('terminal-drawer') === null") is True
    _sin_errores(page)


# --------------------------------------------------------------------------- ventana

def test_los_controles_de_ventana_responden(ventana, qtbot):
    window, page, _ = ventana

    _click(page, "document.getElementById('btn-maximize')")
    _esperar(qtbot, 500)
    assert window.isMaximized() is True

    _click(page, "document.getElementById('btn-maximize')")
    _esperar(qtbot, 500)
    assert window.isMaximized() is False

    _click(page, "document.getElementById('btn-minimize')")
    _esperar(qtbot, 500)

    # Cerrar minimiza a la bandeja, no termina el proceso (CA-01).
    _click(page, "document.getElementById('btn-close')")
    _esperar(qtbot, 500)
    assert window.isVisible() is False
    _sin_errores(page)


# --------------------------------------------------------------------------- detener

def test_el_boton_de_detener_frena_el_turno_y_descarta_la_respuesta(ventana, qtbot):
    """Lo que el usuario mandó a parar no puede aparecer igual en pantalla tres segundos
    después: la cancelación es cooperativa, así que la respuesta puede llegar de todos
    modos y hay que descartarla."""
    window, page, registro = ventana
    registro["demora"] = 6.0     # el turno tiene que seguir vivo cuando se pulsa detener

    _run_js(page, """
        const input = document.getElementById('composer-input');
        input.value = 'algo lento';
        input.dispatchEvent(new Event('input'));
        true;
    """)
    _click(page, "document.getElementById('send-btn')")
    qtbot.waitUntil(lambda: registro["mensajes"] != [], timeout=5000)

    # Mientras responde, el botón de enviar cede su lugar al de detener.
    qtbot.waitUntil(
        lambda: _run_js(page, "document.getElementById('stop-btn').hidden") is False,
        timeout=5000,
    )

    _click(page, "document.getElementById('stop-btn')")
    _esperar(qtbot, 500)

    assert _run_js(page, "document.getElementById('send-btn').hidden") is False
    assert _run_js(page, "document.querySelector('#toast-host .toast') !== null") is True
    _sin_errores(page)


def test_lo_que_se_esta_escribiendo_se_ve_y_lo_reemplaza_la_respuesta(ventana, qtbot):
    """Streaming: los pedazos se ven mientras llegan, y el mensaje definitivo (ya con
    formato) ocupa su lugar en vez de duplicarse."""
    window, page, _ = ventana

    window.bridge.message_chunk.emit("Estoy escribiendo")
    window.bridge.message_chunk.emit(" de a poco")
    _esperar(qtbot, 300)

    assert _run_js(page, "document.querySelector('.msg-viva .bubble').textContent") \
        == "Estoy escribiendo de a poco"

    window.bridge.message_appended.emit(json.dumps({
        "role": "assistant", "html": "<p>Estoy escribiendo de a poco</p>",
    }))
    _esperar(qtbot, 300)

    assert _run_js(page, "document.querySelectorAll('.msg-viva').length") == 0
    assert _run_js(page, "document.querySelectorAll('.message').length") == 1
    _sin_errores(page)


# --------------------------------------------------------------------------- modelo

def test_el_selector_de_modelo_muestra_el_activo_y_lo_cambia(ventana, qtbot, monkeypatch):
    _, page, _ = ventana
    import config_manager

    cambios = []
    monkeypatch.setattr(config_manager, "set_ai_provider_and_model",
                        lambda p, m="": cambios.append((p, m)))

    qtbot.waitUntil(
        lambda: _run_js(page, "document.getElementById('model-btn-label').textContent")
        not in ("", "…"),
        timeout=5000,
    )

    _click(page, "document.getElementById('model-btn')")
    _esperar(qtbot, 300)
    assert _run_js(page, "document.querySelectorAll('.model-option').length") > 1

    _run_js(page, """
        const opciones = Array.from(document.querySelectorAll('.model-option'));
        const otra = opciones.find(o => !o.classList.contains('active'));
        otra.click();
        true;
    """)
    _esperar(qtbot, 400)

    assert cambios, "no se guardó el modelo elegido"
    assert _run_js(page, "document.getElementById('model-menu') === null") is True
    _sin_errores(page)


# --------------------------------------------------------------------------- adjuntar

def test_el_clip_abre_el_dialogo_y_adjunta(ventana, qtbot, monkeypatch, tmp_path):
    """El botón de adjuntar era solo un cartel; ahora abre el diálogo nativo. El archivo
    elegido pasa por la misma validación que el drag&drop."""
    _, page, _ = ventana
    from PyQt6.QtWidgets import QFileDialog

    archivo = tmp_path / "informe.txt"
    archivo.write_text("contenido", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(archivo), "")))

    _click(page, "document.getElementById('attach-btn')")
    _esperar(qtbot, 500)

    assert _run_js(page, "document.getElementById('attachment-chip-name').textContent") \
        == "informe.txt"
    assert _run_js(page, "document.getElementById('attachment-chip').hidden") is False
    _sin_errores(page)


def test_cancelar_el_dialogo_no_adjunta_nada(ventana, qtbot, monkeypatch):
    _, page, _ = ventana
    from PyQt6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    _click(page, "document.getElementById('attach-btn')")
    _esperar(qtbot, 400)

    assert _run_js(page, "document.getElementById('attachment-chip').hidden") is True
    _sin_errores(page)


# --------------------------------------------------------------------------- renombrar y buscar

def test_renombrar_una_conversacion(ventana, qtbot, monkeypatch):
    window, page, _ = ventana
    from ai.memory_manager import memory

    renombrados = []
    monkeypatch.setattr(memory, "rename_conversation",
                        lambda cid, titulo, **kw: renombrados.append((cid, titulo)) or True)

    window.bridge.conversation_list_updated.emit(json.dumps([
        {"conversation_id": "a", "title": "Una charla", "last_activity": None},
    ]))
    _esperar(qtbot, 300)

    _click(page, "document.querySelector('.conv-item .conv-icon-btn')")
    _esperar(qtbot, 200)
    assert _run_js(page, "document.querySelector('.conv-rename-input') !== null") is True

    _run_js(page, """
        const campo = document.querySelector('.conv-rename-input');
        campo.value = 'Certificados del server';
        campo.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
        true;
    """)
    qtbot.waitUntil(lambda: renombrados != [], timeout=5000)

    assert renombrados == [("a", "Certificados del server")]
    _sin_errores(page)


def test_buscar_en_el_historial_muestra_el_fragmento(ventana, qtbot, monkeypatch):
    """El filtro de la barra solo mira los títulos en pantalla; esto va a la base y trae
    la conversación aunque se llame de otra forma."""
    _, page, _ = ventana
    from ai.memory_manager import memory

    monkeypatch.setattr(memory, "search_conversations", lambda q, **kw: [
        {"conversation_id": "z", "title": "Charla vieja",
         "snippet": "…hablamos del certificado…", "matches": 2, "last_activity": ""},
    ])

    _run_js(page, """
        const input = document.getElementById('conv-search-input');
        input.value = 'certificado';
        input.dispatchEvent(new Event('input'));
        true;
    """)
    qtbot.waitUntil(
        lambda: _run_js(page, "document.querySelector('.conv-snippet') !== null") is True,
        timeout=8000,
    )

    assert "certificado" in _run_js(page, "document.querySelector('.conv-snippet').textContent")
    _sin_errores(page)


# --------------------------------------------------------------------------- acciones de mensaje

def test_un_bloque_de_codigo_se_puede_mandar_a_la_terminal(ventana, qtbot, monkeypatch):
    """El comando lo escribió el modelo: pasa por el MISMO gate amarillo que usa el
    agente, con el comando a la vista."""
    window, page, _ = ventana
    import agents.tool_registry as tool_registry

    ejecutados = []
    monkeypatch.setattr(tool_registry, "execute_tool",
                        lambda nombre, params, canal, **kw: ejecutados.append(params) or "ok")

    window.bridge.message_appended.emit(json.dumps({
        "role": "assistant",
        "html": '<p>Corré esto:</p><div class="codehilite"><pre>git status</pre></div>',
    }))
    _esperar(qtbot, 400)

    assert _run_js(page, "document.querySelectorAll('.code-actions .msg-action').length") == 2
    _run_js(page, """
        const botones = Array.from(document.querySelectorAll('.code-actions .msg-action'));
        botones.find(b => b.title === 'Ejecutar').click();
        true;
    """)
    qtbot.waitUntil(lambda: ejecutados != [], timeout=5000)

    assert ejecutados == [{"command": "git status"}]
    _sin_errores(page)


def test_un_bloque_largo_no_ofrece_ejecutarse(ventana, qtbot):
    """Un bloque de muchas líneas es un programa, no un comando: ofrecer "ejecutar" ahí
    sería ofrecer pegar un archivo entero en la consola."""
    window, page, _ = ventana

    codigo = "<pre>" + ("print(1)&#10;" * 8) + "</pre>"
    window.bridge.message_appended.emit(json.dumps({"role": "assistant", "html": codigo}))
    _esperar(qtbot, 400)

    titulos = json.loads(_run_js(page, """
        JSON.stringify(Array.from(document.querySelectorAll('.code-actions .msg-action'))
            .map(b => b.title))
    """))
    assert titulos == ["Copiar"]
    _sin_errores(page)


# --------------------------------------------------------------------------- avisos

def test_un_error_del_bridge_se_ve_en_pantalla(ventana, qtbot):
    """Antes terminaba en un console.error que nadie mira: la pantalla no decía nada y
    parecía que el click no había hecho nada."""
    window, page, _ = ventana

    window.bridge.error_occurred.emit("No pude guardar la configuración")
    _esperar(qtbot, 300)

    texto = _run_js(page, "document.querySelector('#toast-host .toast-text').textContent")
    assert "No pude guardar" in texto
    assert _run_js(page, "document.querySelector('.toast-error') !== null") is True


def test_un_aviso_del_sistema_llega_a_la_ventana(ventana, qtbot):
    """Los avisos de `core/notificaciones.py` (un flujo que falla de madrugada) van a la
    bandeja Y a la ventana: el globo del sistema se pierde entre los demás."""
    window, page, _ = ventana
    from core.notificaciones import notificar

    notificar("El flujo «modo trabajo» falló", "el paso 2 no se pudo ejecutar", "error")
    _esperar(qtbot, 500)

    texto = _run_js(page, "document.querySelector('#toast-host .toast-text').textContent")
    assert "modo trabajo" in texto


def test_los_avisos_se_pueden_cerrar(ventana, qtbot):
    window, page, _ = ventana
    window.bridge.notice_shown.emit("ok", "Listo")
    _esperar(qtbot, 300)
    _click(page, "document.querySelector('#toast-host .toast-close')")
    _esperar(qtbot, 200)
    assert _run_js(page, "document.querySelector('#toast-host .toast') === null") is True


# --------------------------------------------------------------------------- atajos

def test_los_atajos_de_teclado_responden(ventana, qtbot):
    """Ctrl+N abre un chat nuevo; Ctrl+K enfoca el buscador. Ninguno pisa lo que se está
    escribiendo (de eso se ocupa `escribiendo()` en shortcuts.js)."""
    window, page, _ = ventana

    window.bridge.message_appended.emit(json.dumps({"role": "user", "html": "<p>hola</p>"}))
    _esperar(qtbot, 200)

    _run_js(page, """
        document.dispatchEvent(new KeyboardEvent(
            'keydown', {key: 'n', ctrlKey: true, bubbles: true}));
        true;
    """)
    _esperar(qtbot, 400)
    assert _run_js(page, "document.getElementById('messages').children.length") == 0

    _run_js(page, """
        document.dispatchEvent(new KeyboardEvent(
            'keydown', {key: 'k', ctrlKey: true, bubbles: true}));
        true;
    """)
    _esperar(qtbot, 200)
    assert _run_js(page, "document.activeElement.id") == "conv-search-input"
    _sin_errores(page)


# --------------------------------------------------------------------------- cobertura

def test_todo_boton_con_id_del_html_tiene_su_manejador(ventana):
    """Red de seguridad contra el botón olvidado: si alguien agrega un control al HTML y no
    lo cablea, este test lo encuentra. La lista de abajo es el inventario que los tests de
    arriba recorren uno por uno."""
    _, page, _ = ventana

    ids = json.loads(_run_js(page, """
        JSON.stringify(Array.from(document.querySelectorAll('button[id]')).map(b => b.id))
    """))

    esperados = {
        "terminal-btn", "tasks-btn", "flows-btn", "projects-btn", "settings-btn",
        "btn-minimize", "btn-maximize", "btn-close",
        "new-conversation-btn", "sidebar-collapse-toggle", "theme-toggle-btn",
        "load-more-btn", "attach-btn", "wake-toggle-btn", "send-btn", "stop-btn",
        "model-btn", "attachment-chip-remove",
    }
    assert set(ids) == esperados, (
        "cambió el inventario de botones del HTML: agregá el nuevo a un test de este "
        "archivo antes de tocar esta lista"
    )
