"""
tests/test_chat_widgets.py
REQ-013 — cobertura de los widgets conversacionales nuevos de `ui/widgets/`:
`ChatBubble`, `ChatFeed`, `Composer` y `ConversationList`
(CA-06, CA-07, CA-13, CA-14, CA-15, CA-16, CA-17, CA-18, CA-19).

Con `pytest-qt` (`qtbot`) en modo offscreen (fijado en tests/conftest.py). Sin red, sin
SQLite y sin ejecutar ninguna acción real: los chips de acción pasan por un `run_async`
mockeado, igual que el test equivalente de `QuickActionsCard` (REQ-008).
"""

from unittest.mock import MagicMock

from PyQt6.QtCore import Qt

import ui.widgets.composer as composer_module
from core.security_manager import ChannelType
from ui.widgets.chat_bubble import ChatBubble
from ui.widgets.chat_feed import ChatFeed
from ui.widgets.composer import Composer
from ui.widgets.conversation_list import ConversationList


class _FakeTurn:
    """Doble mínimo de `MemoryItem` — el feed solo lee `.text` y `.role`."""

    def __init__(self, text, role):
        self.text = text
        self.role = role


class _FakeSummary:
    """Doble mínimo de `ConversationSummary`."""

    def __init__(self, conversation_id, title):
        self.conversation_id = conversation_id
        self.title = title


# ---------------------------------------------------------------------------
# ChatBubble (CA-13, CA-14)
# ---------------------------------------------------------------------------

def test_chat_bubble_role_property_user_vs_assistant(qtbot):
    """El QSS del feed distingue las burbujas por la propiedad dinámica `role`."""
    del_usuario = ChatBubble("hola", "user")
    del_asistente = ChatBubble("qué tal", "assistant")
    qtbot.addWidget(del_usuario)
    qtbot.addWidget(del_asistente)

    assert del_usuario.property("role") == "user"
    assert del_asistente.property("role") == "assistant"
    assert del_usuario.role() == "user"
    assert del_usuario.text() == "hola"


def test_chat_bubble_rol_desconocido_cae_en_assistant(qtbot):
    """Nunca se pinta como mensaje del usuario algo cuyo rol no se conoce."""
    burbuja = ChatBubble("texto", "sistema")
    qtbot.addWidget(burbuja)

    assert burbuja.role() == "assistant"


# ---------------------------------------------------------------------------
# ChatFeed (CA-13, CA-14, CA-15, CA-06, CA-07)
# ---------------------------------------------------------------------------

def test_chat_feed_add_message_incrementa_conteo_y_conserva_orden(qtbot):
    """CA-13, CA-14."""
    feed = ChatFeed()
    qtbot.addWidget(feed)

    feed.add_message("primero", "user")
    feed.add_message("segundo", "assistant")
    feed.add_message("tercero", "user")

    assert feed.message_count() == 3
    assert [b.text() for b in feed.bubbles()] == ["primero", "segundo", "tercero"]
    assert [b.role() for b in feed.bubbles()] == ["user", "assistant", "user"]


def test_chat_feed_load_turns_reemplaza_contenido_previo(qtbot):
    """CA-06."""
    feed = ChatFeed()
    qtbot.addWidget(feed)
    feed.add_message("de la conversación anterior", "user")

    feed.load_turns([_FakeTurn("hola", "user"), _FakeTurn("qué tal", "assistant")])

    assert feed.message_count() == 2
    assert [b.text() for b in feed.bubbles()] == ["hola", "qué tal"]


def test_chat_feed_load_turns_sin_rol_se_muestra_como_asistente(qtbot):
    """Filas legacy (`role IS NULL`) se muestran, nunca se descartan ni se inventan como
    mensajes del usuario (CA-12)."""
    feed = ChatFeed()
    qtbot.addWidget(feed)

    feed.load_turns([_FakeTurn("recuerdo viejo", None)])

    assert feed.message_count() == 1
    assert feed.bubbles()[0].role() == "assistant"


def test_chat_feed_clear_messages_deja_feed_vacio(qtbot):
    """CA-07."""
    feed = ChatFeed()
    qtbot.addWidget(feed)
    feed.add_message("hola", "user")
    feed.add_message("qué tal", "assistant")

    feed.clear_messages()

    assert feed.message_count() == 0
    assert feed.is_empty() is True


def test_chat_feed_autoscroll_al_agregar_mensaje(qtbot):
    """CA-15 — con el usuario al final, un mensaje nuevo baja el scroll solo."""
    feed = ChatFeed()
    qtbot.addWidget(feed)
    feed.resize(400, 180)
    feed.show()
    qtbot.waitExposed(feed)

    for i in range(40):
        feed.add_message(f"mensaje número {i}", "assistant")

    barra = feed.verticalScrollBar()
    qtbot.waitUntil(lambda: barra.maximum() > 0, timeout=3000)
    qtbot.waitUntil(lambda: barra.value() == barra.maximum(), timeout=3000)


def test_chat_feed_no_autoscroll_si_usuario_subio(qtbot):
    """CA-15 — si el usuario está releyendo más arriba, no se le arranca la vista."""
    feed = ChatFeed()
    qtbot.addWidget(feed)
    feed.resize(400, 180)
    feed.show()
    qtbot.waitExposed(feed)

    for i in range(40):
        feed.add_message(f"mensaje número {i}", "assistant")

    barra = feed.verticalScrollBar()
    qtbot.waitUntil(lambda: barra.maximum() > 0, timeout=3000)
    barra.setValue(0)

    feed.add_message("mensaje nuevo mientras el usuario relee", "assistant")
    qtbot.wait(100)

    assert barra.value() == 0


# ---------------------------------------------------------------------------
# Composer (CA-16, CA-17, CA-18, CA-19)
# ---------------------------------------------------------------------------

def test_composer_submit_emite_command_submitted_y_limpia_input(qtbot):
    """CA-17."""
    composer = Composer()
    qtbot.addWidget(composer)
    recibidos = []
    composer.command_submitted.connect(recibidos.append)

    composer.set_text("  qué hora es  ")
    composer._send_button.click()

    assert recibidos == ["qué hora es"]
    assert composer.text() == ""


def test_composer_submit_vacio_no_emite_nada(qtbot):
    composer = Composer()
    qtbot.addWidget(composer)
    recibidos = []
    composer.command_submitted.connect(recibidos.append)

    composer.set_text("   ")
    composer._send_button.click()

    assert recibidos == []


def test_composer_chip_plantilla_prellena_input_sin_emitir_comando(qtbot):
    """CA-18 — un chip de plantilla deja al usuario completar y enviar."""
    composer = Composer()
    qtbot.addWidget(composer)
    recibidos = []
    composer.command_submitted.connect(recibidos.append)

    chips = [b for b in composer._chip_buttons if b.property("chipKind") == "template"]
    assert chips
    chips[0].click()

    assert composer.text() != ""
    assert recibidos == []


def test_composer_chip_accion_llama_execute_action_con_channel_desktop(qtbot, monkeypatch):
    """CA-19 — la acción pasa por el gate fail-closed con el canal real DESKTOP y nunca se
    invoca directo (espejo del test de `QuickActionsCard`, REQ-008)."""
    registro = []
    accion_falsa = MagicMock()
    monkeypatch.setattr(composer_module, "execute_action", accion_falsa)
    monkeypatch.setattr(
        composer_module, "run_async",
        lambda fn, on_done, on_error, *a, **k: registro.append((fn, a, k)),
    )

    composer = Composer()
    qtbot.addWidget(composer)

    chips = [b for b in composer._chip_buttons if b.property("chipKind") == "action"]
    assert chips
    chips[0].click()

    assert len(registro) == 1
    funcion, args, kwargs = registro[0]
    assert funcion is accion_falsa
    assert kwargs["channel"] is ChannelType.DESKTOP
    assert kwargs["user_id"] == "default"
    assert args and isinstance(args[0], str)
    # La acción se AGENDA, nunca se ejecuta desde el hilo de la GUI ni salteando el gate.
    assert accion_falsa.call_count == 0


def test_composer_set_input_enabled_bloquea_envio_y_cambia_placeholder(qtbot):
    """REQ-013 (3ra pasada)/CA-09, CA-16 — regresión de la condición de carrera de
    `_pending_user_text` (qa-audit-013.md): con el input deshabilitado, Qt no entrega
    `clicked` a un botón deshabilitado, así que un segundo envío queda descartado por
    construcción (no un guard que se pueda olvidar en otro punto de entrada). El placeholder
    también cambia, para que el bloqueo sea visible y no se confunda con la app colgada."""
    composer = Composer()
    qtbot.addWidget(composer)
    recibidos = []
    composer.command_submitted.connect(recibidos.append)

    composer.set_input_enabled(False)
    assert composer._input.isEnabled() is False
    assert composer._send_button.isEnabled() is False
    assert composer._input.placeholderText() == "Noddoo está pensando..."

    composer.set_text("no debería enviarse mientras resuelve el turno anterior")
    composer._send_button.click()
    assert recibidos == []

    composer.set_input_enabled(True)
    assert composer._input.isEnabled() is True
    assert composer._send_button.isEnabled() is True
    assert composer._input.placeholderText() == "Escribe un comando o habla con Noddoo..."

    composer._send_button.click()
    assert recibidos == ["no debería enviarse mientras resuelve el turno anterior"]


def test_composer_set_wake_state_no_reemite_hands_free_toggled(qtbot):
    """CA-16 — regresión del guard de REQ-009: reflejar el estado por polling no puede
    disparar la señal del clic del usuario."""
    composer = Composer()
    qtbot.addWidget(composer)
    recibidos = []
    composer.hands_free_toggled.connect(recibidos.append)

    composer.set_wake_state("LISTENING_WAKE")
    composer.set_wake_state("AWAKE")
    composer.set_wake_state("INACTIVE")

    assert recibidos == []
    assert composer._wake_toggle.property("wakeState") == "INACTIVE"


def test_composer_click_real_del_toggle_si_emite_hands_free_toggled(qtbot):
    composer = Composer()
    qtbot.addWidget(composer)
    recibidos = []
    composer.hands_free_toggled.connect(recibidos.append)

    composer._wake_toggle.click()

    assert recibidos == [True]


# ---------------------------------------------------------------------------
# ConversationList (CA-05, CA-06, CA-07, CA-10)
# ---------------------------------------------------------------------------

def test_conversation_list_click_emite_conversation_selected_con_id(qtbot):
    """CA-06."""
    lista = ConversationList()
    qtbot.addWidget(lista)
    recibidos = []
    lista.conversation_selected.connect(recibidos.append)

    lista.set_conversations([_FakeSummary("cid-1", "Primera"), _FakeSummary("cid-2", "Segunda")])
    lista._on_item_clicked(lista._list.item(1))

    assert recibidos == ["cid-2"]


def test_conversation_list_boton_nueva_emite_new_conversation_requested(qtbot):
    """CA-07."""
    lista = ConversationList()
    qtbot.addWidget(lista)
    recibidos = []
    lista.new_conversation_requested.connect(lambda: recibidos.append(True))

    lista._new_button.click()

    assert recibidos == [True]


def test_conversation_list_set_active_marca_el_item(qtbot):
    """CA-06."""
    lista = ConversationList()
    qtbot.addWidget(lista)
    lista.set_conversations([_FakeSummary("cid-1", "Primera"), _FakeSummary("cid-2", "Segunda")])

    lista.set_active("cid-2")
    assert lista.active_conversation() == "cid-2"

    lista.set_active(None)
    assert lista.active_conversation() is None


def test_conversation_list_append_agrega_pagina_sin_borrar_lo_anterior(qtbot):
    """Paginación del botón "Ver más" (CA-05)."""
    lista = ConversationList()
    qtbot.addWidget(lista)
    lista.set_conversations([_FakeSummary(f"cid-{i}", f"Conv {i}") for i in range(3)])

    lista.set_conversations([_FakeSummary(f"cid-{i}", f"Conv {i}") for i in range(3, 5)],
                            append=True)

    assert lista.count() == 5
    assert lista.conversation_ids()[0] == "cid-0"
    assert lista.conversation_ids()[-1] == "cid-4"


def test_conversation_list_vacia_muestra_placeholder_no_seleccionable(qtbot):
    """Caso borde: sin historial, la lista no queda muda ni ofrece un ítem clickeable."""
    lista = ConversationList()
    qtbot.addWidget(lista)

    lista.set_conversations([])

    assert lista.count() == 0
    assert lista._list.count() == 1
    assert lista._list.item(0).flags() == Qt.ItemFlag.NoItemFlags


def test_conversation_list_set_has_more_controla_boton_ver_mas(qtbot):
    lista = ConversationList()
    qtbot.addWidget(lista)

    assert lista._more_button.isVisibleTo(lista) is False

    lista.set_has_more(True)
    assert lista._more_button.isVisibleTo(lista) is True

    lista.set_has_more(False)
    assert lista._more_button.isVisibleTo(lista) is False
