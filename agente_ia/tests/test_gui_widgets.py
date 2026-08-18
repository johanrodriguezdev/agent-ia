"""
tests/test_gui_widgets.py
Pruebas de los widgets nuevos de `ui/widgets/` y de `ui/gui.py:JarvisMainWindow`
(REQ-008), con `pytest-qt` (`qtbot`) en modo offscreen (fijado en tests/conftest.py).
Sin aserciones visuales/pixel — solo estado, señales y textos, como piden las
"Pruebas sugeridas" de arquitectura-008.md.

`WeatherCard`/`RecentActivityCard` disparan I/O real en su `__init__` (red y SQLite,
respectivamente) — la fixture `no_external_io` los neutraliza para que la suite completa
siga sin red y sin tocar la base de datos real (.claude/rules/testing.md).
"""

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

import ai.memory_manager as memory_module
import ui.gui as gui_module
import ui.theme as theme_module
import ui.widgets.recent_activity_card as recent_activity_module
import ui.widgets.weather_card as weather_card_module
from ai.memory_manager import MemoryItem
from core.security_manager import ChannelType
from os_integration.weather_data import WeatherData
from ui.gui import JarvisMainWindow
from ui.personality import get_time_based_greeting
from ui.theme import theme_manager
from ui.widgets.center_panel import CenterPanel
from ui.widgets.composer import Composer
from ui.widgets.quick_actions_card import QuickActionsCard
from ui.widgets.recent_activity_card import RecentActivityCard
from ui.widgets.right_panel import RightPanel
from ui.widgets.sidebar import Sidebar
from ui.widgets.system_status_card import SystemStatusCard
from ui.widgets.weather_card import WeatherCard


@pytest.fixture
def no_external_io(monkeypatch):
    """Evita que `WeatherCard` haga una petición HTTP real y que `RecentActivityCard`
    lea la base de datos de memoria real al construirse."""
    monkeypatch.setattr(weather_card_module, "run_async", lambda *a, **k: None)
    monkeypatch.setattr(recent_activity_module.memory, "get_recent", lambda **kwargs: [])
    # REQ-013: `JarvisMainWindow.__init__` pide el listado de conversaciones al arrancar;
    # sin esto la suite leería la base de datos real (.claude/rules/testing.md).
    monkeypatch.setattr(memory_module.memory, "list_conversations", lambda **kwargs: [])


@pytest.fixture
def theme_sandbox(monkeypatch):
    """REQ-013 — aísla el tema del `config.json` real.

    `theme_manager` es un singleton de módulo: `set_theme()` escribiría la preferencia real
    del usuario y `load_from_config()` haría que el resultado del test dependiera de ella.
    """
    monkeypatch.setattr(theme_module.config_manager, "set_ui_theme", lambda name: None)
    monkeypatch.setattr(theme_module.config_manager, "get_ui_theme", lambda: "dark")
    original = theme_manager.current_name()
    theme_manager.set_theme("dark")
    yield
    theme_manager.set_theme(original)


# ---------------------------------------------------------------------------
# Sidebar (CA-05)
# ---------------------------------------------------------------------------

def test_sidebar_inicio_emits_nav_selected(qtbot):
    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    received = []
    sidebar.nav_selected.connect(received.append)

    from PyQt6.QtWidgets import QPushButton
    # REQ-013/CA-22: el sidebar ya no contiene solo los botones de navegación (ahora
    # también los de `ConversationList`), y "Conversaciones" pasó a estar habilitado
    # (CA-08). La aserción se acota a los ítems de navegación por objectName.
    buttons = [b for b in sidebar.findChildren(QPushButton)
               if b.objectName() == "SidebarNavButton"]
    enabled_buttons = [b for b in buttons if b.isEnabled()]
    disabled_buttons = [b for b in buttons if not b.isEnabled()]

    assert len(enabled_buttons) == 2
    assert len(disabled_buttons) == 5

    enabled_buttons[0].click()
    assert received == ["inicio"]


# ---------------------------------------------------------------------------
# SystemStatusCard (CA-06)
# ---------------------------------------------------------------------------

def test_system_status_card_set_values_updates_labels(qtbot):
    card = SystemStatusCard()
    qtbot.addWidget(card)

    card.set_values(18, 42, 31, 12)

    assert "18%" in card._labels["cpu"].text()
    assert "42%" in card._labels["ram"].text()
    assert "31%" in card._labels["disk"].text()
    assert "12%" in card._labels["net"].text()


# ---------------------------------------------------------------------------
# QuickActionsCard (CA-07)
# ---------------------------------------------------------------------------

def test_quick_actions_card_click_calls_execute_action_via_channel(qtbot):
    card = QuickActionsCard()
    qtbot.addWidget(card)

    with patch("ui.widgets.quick_actions_card.run_async") as mock_run_async:
        from PyQt6.QtWidgets import QPushButton
        buttons = card.findChildren(QPushButton)
        buttons[0].click()

    assert mock_run_async.call_count == 1
    args, kwargs = mock_run_async.call_args
    # (execute_action, on_done, on_error, action_name)
    from agents.action_registry import execute_action
    assert args[0] is execute_action
    assert args[3] == "open_explorer"
    assert kwargs["channel"] == ChannelType.DESKTOP


# ---------------------------------------------------------------------------
# RecentActivityCard (CA-09)
# ---------------------------------------------------------------------------

def test_recent_activity_card_empty_state(qtbot, no_external_io):
    card = RecentActivityCard()
    qtbot.addWidget(card)

    card.set_items([])
    assert card._items_layout.count() == 1


def test_recent_activity_card_renders_items_with_time(qtbot, no_external_io):
    card = RecentActivityCard()
    qtbot.addWidget(card)

    item = MemoryItem(text="hola mundo", timestamp="2026-01-01T10:30:00")
    card.set_items([item])

    assert card._items_layout.count() == 1


# ---------------------------------------------------------------------------
# WeatherCard (CA-10)
# ---------------------------------------------------------------------------

def test_weather_card_set_data_none_shows_unavailable(qtbot, no_external_io):
    card = WeatherCard()
    qtbot.addWidget(card)

    card.set_data(None)
    assert "no disponible" in card._condition_label.text().lower()


def test_weather_card_set_data_shows_all_fields(qtbot, no_external_io):
    card = WeatherCard()
    qtbot.addWidget(card)

    data = WeatherData(temp_c=21.0, condition="Soleado", city="Bogota", time_str="10:30", date_str="01 ene, 2026")
    card.set_data(data)

    assert "21" in card._temp_label.text()
    assert card._condition_label.text() == "Soleado"
    assert card._city_label.text() == "Bogota"
    assert "10:30" in card._datetime_label.text()


# ---------------------------------------------------------------------------
# WeatherCard — ciudad configurable (REQ-012/CA-03, CA-04)
# ---------------------------------------------------------------------------

def test_weather_card_fetch_passes_configured_city(qtbot, monkeypatch):
    monkeypatch.setattr(
        "ui.widgets.weather_card.config_manager.get_weather_city", lambda: "Medellín"
    )

    with patch("ui.widgets.weather_card.run_async") as mock_run_async:
        card = WeatherCard()
        qtbot.addWidget(card)

    assert mock_run_async.call_count == 1
    assert mock_run_async.call_args.args[-1] == "Medellín"


def test_weather_card_fetch_passes_empty_city_by_default(qtbot, monkeypatch):
    monkeypatch.setattr(
        "ui.widgets.weather_card.config_manager.get_weather_city", lambda: ""
    )

    with patch("ui.widgets.weather_card.run_async") as mock_run_async:
        card = WeatherCard()
        qtbot.addWidget(card)

    assert mock_run_async.call_count == 1
    assert mock_run_async.call_args.args[-1] == ""


# ---------------------------------------------------------------------------
# CenterPanel (CA-03/CA-04)
# ---------------------------------------------------------------------------

def test_center_panel_greeting_matches_personality_helper(qtbot, monkeypatch):
    monkeypatch.setattr("ui.widgets.center_panel.config_manager.get_display_name", lambda: "Ana")

    panel = CenterPanel()
    qtbot.addWidget(panel)

    expected = get_time_based_greeting("Ana")
    assert panel._greeting_label.text() == expected


# ---------------------------------------------------------------------------
# CenterPanel — refresco periódico del saludo (REQ-012/CA-06, CA-07, CA-08, CA-09)
# ---------------------------------------------------------------------------

def test_center_panel_greeting_timer_starts_on_construction(qtbot):
    panel = CenterPanel()
    qtbot.addWidget(panel)

    assert panel._greeting_timer.isActive()
    assert panel._greeting_timer.interval() == 60_000


def test_center_panel_greeting_timer_parented_to_widget(qtbot):
    panel = CenterPanel()
    qtbot.addWidget(panel)

    assert panel._greeting_timer.parent() is panel


def test_center_panel_refresh_greeting_noop_if_unchanged(qtbot, monkeypatch):
    panel = CenterPanel()
    qtbot.addWidget(panel)

    current_text = panel._greeting_label.text()
    monkeypatch.setattr(
        "ui.widgets.center_panel.get_time_based_greeting", lambda name: current_text
    )
    with patch.object(panel._greeting_label, "setText") as mock_set_text:
        panel._refresh_greeting()

    mock_set_text.assert_not_called()
    assert panel._greeting_label.text() == current_text


def test_center_panel_refresh_greeting_updates_on_franja_change(qtbot, monkeypatch):
    mock_greeting = MagicMock(side_effect=["Buenas tardes", "Buenas noches"])
    monkeypatch.setattr("ui.widgets.center_panel.get_time_based_greeting", mock_greeting)

    panel = CenterPanel()
    qtbot.addWidget(panel)
    assert panel._greeting_label.text() == "Buenas tardes"

    panel._greeting_timer.timeout.emit()

    assert panel._greeting_label.text() == "Buenas noches"


# ---------------------------------------------------------------------------
# JarvisMainWindow (CA-13)
# ---------------------------------------------------------------------------

def test_jarvis_main_window_close_hides_without_quitting_app(qtbot, no_external_io):
    window = JarvisMainWindow()
    qtbot.addWidget(window)
    window.show()

    window.close()

    assert window.isVisible() is False
    assert QApplication.instance() is not None


# ---------------------------------------------------------------------------
# REQ-011/CA-04 — la bandeja queda funcional aunque la ventana nunca haya sido
# mostrada (arranque `--tray` de main.py: se instancia JarvisMainWindow() sin llamar
# show()/showMaximized()).
# ---------------------------------------------------------------------------

def test_tray_icon_activo_sin_ventana_mostrada_ca04(qtbot, no_external_io):
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    # Replica el arranque --tray: nunca se llamó show()/showMaximized().
    assert window.isVisible() is False

    assert isinstance(window.tray_icon, QSystemTrayIcon)
    menu_texts = [accion.text() for accion in window.tray_icon.contextMenu().actions()]
    assert "Mostrar/Ocultar" in menu_texts
    assert "Salir" in menu_texts

    # El menú "Mostrar/Ocultar" funciona igual que en un arranque manual: alterna
    # visibilidad aunque la ventana jamás haya sido mostrada antes.
    window._toggle_visible()
    assert window.isVisible() is True
    window._toggle_visible()
    assert window.isVisible() is False


# ---------------------------------------------------------------------------
# REQ-013 — feed conversacional, conversaciones y tema (integración)
# ---------------------------------------------------------------------------

def test_center_panel_show_response_agrega_burbuja_completa_sin_truncar(qtbot):
    """CA-14 — antes de REQ-013 la respuesta iba a un QLabel truncado a 200 caracteres."""
    panel = CenterPanel()
    qtbot.addWidget(panel)

    largo = "x" * 500
    panel.show_response(largo)

    burbujas = panel._feed.bubbles()
    assert len(burbujas) == 1
    assert burbujas[0].text() == largo
    assert burbujas[0].role() == "assistant"


def test_center_panel_add_user_message_agrega_burbuja_user(qtbot):
    """CA-13."""
    panel = CenterPanel()
    qtbot.addWidget(panel)

    panel.add_user_message("hola Noddoo")

    burbujas = panel._feed.bubbles()
    assert len(burbujas) == 1
    assert burbujas[0].role() == "user"
    assert burbujas[0].text() == "hola Noddoo"


def test_center_panel_empty_state_se_oculta_al_primer_mensaje(qtbot):
    """CA-20 — el bloque de bienvenida (saludo + orbe) solo se ve con el feed vacío."""
    panel = CenterPanel()
    qtbot.addWidget(panel)

    assert panel._empty_state.isVisibleTo(panel) is True

    panel.add_user_message("hola")
    assert panel._empty_state.isVisibleTo(panel) is False

    panel.clear_feed()
    assert panel._empty_state.isVisibleTo(panel) is True


def test_main_window_handle_command_agrega_burbuja_usuario_antes_de_resolver(
    qtbot, no_external_io, monkeypatch
):
    """CA-13 — la burbuja del usuario ya existe cuando se agenda `resolve()`."""
    ventana = []
    registro = []

    def fake_run_async(fn, on_done, on_error, *args, **kwargs):
        burbujas = ventana[0].center_panel._feed.message_count() if ventana else -1
        registro.append((fn, args, kwargs, burbujas))

    monkeypatch.setattr(gui_module, "run_async", fake_run_async)

    window = JarvisMainWindow()
    ventana.append(window)
    qtbot.addWidget(window)
    registro.clear()

    window._handle_command("qué hora es")

    assert len(registro) == 1
    assert registro[0][3] == 1  # la burbuja ya estaba pintada al agendar resolve()
    assert window.center_panel._feed.bubbles()[0].role() == "user"
    assert window.center_panel._feed.bubbles()[0].text() == "qué hora es"


def test_main_window_on_command_done_persiste_turno_con_conversation_id(
    qtbot, no_external_io, monkeypatch
):
    """CA-09 — el turno se persiste con `store_turn`, fuera del hilo de la GUI."""
    registro = []
    monkeypatch.setattr(
        gui_module, "run_async",
        lambda fn, on_done, on_error, *a, **k: registro.append((fn, a, k)),
    )

    window = JarvisMainWindow()
    qtbot.addWidget(window)
    window._pending_user_text = "hola"
    registro.clear()

    resolution = MagicMock()
    resolution.text = "Hola, ¿en qué te ayudo?"
    resolution.matched_by = "chat"

    window._on_command_done(resolution)

    persistidas = [(a, k) for fn, a, k in registro
                   if getattr(fn, "__name__", "") == "store_turn"]
    assert len(persistidas) == 1
    args, kwargs = persistidas[0]
    assert args[0] == "hola"
    assert args[1] == resolution.text
    assert args[2] and args[2] == window._conversation_id
    assert kwargs["user_id"] == "default"
    assert kwargs["matched_by"] == "chat"


def test_main_window_on_command_error_no_persiste_turno(qtbot, no_external_io, monkeypatch):
    """Un error no es una respuesta de la IA: se muestra pero no ensucia el historial."""
    registro = []
    monkeypatch.setattr(
        gui_module, "run_async",
        lambda fn, on_done, on_error, *a, **k: registro.append(getattr(fn, "__name__", "")),
    )

    window = JarvisMainWindow()
    qtbot.addWidget(window)
    registro.clear()

    window._on_command_error("timeout")

    assert "store_turn" not in registro
    assert window._conversation_id is None
    assert "timeout" in window.center_panel._feed.bubbles()[-1].text()
    # REQ-013 (3ra pasada) — el camino de error también debe reactivar el composer, si no
    # queda bloqueado para siempre tras el primer error.
    assert window.center_panel._composer._input.isEnabled() is True


def test_main_window_segundo_envio_bloqueado_mientras_resuelve_el_primero(
    qtbot, no_external_io, monkeypatch
):
    """REQ-013 (3ra pasada) — regresión del hallazgo bloqueante de qa-audit-013.md:
    `_pending_user_text` es un slot único compartido; si el composer no bloqueara el envío
    mientras `resolve()` está en vuelo, un segundo comando lo pisaría y `store_turn()`
    persistiría una atribución user/assistant incorrecta. Reproduce el escenario exacto:
    "A" se envía, todavía no resuelve, se intenta enviar "B" — debe descartarse — y recién al
    resolver "A" se libera el composer para poder enviar "B"."""
    registro = []
    monkeypatch.setattr(
        gui_module, "run_async",
        lambda fn, on_done, on_error, *a, **k: registro.append((fn, a, k)),
    )

    window = JarvisMainWindow()
    qtbot.addWidget(window)
    registro.clear()

    composer = window.center_panel._composer
    composer.set_text("A")
    composer._send_button.click()

    # El primer envío disparó resolve() y deshabilitó el composer (CA-16: feedback visual).
    resueltos = [r for r in registro if getattr(r[0], "__name__", "") == "resolve"]
    assert len(resueltos) == 1
    assert window._pending_user_text == "A"
    assert composer._input.isEnabled() is False
    assert composer._send_button.isEnabled() is False

    # Intento de segundo envío mientras "A" sigue resolviéndose: Qt no entrega `clicked` a un
    # botón deshabilitado, así que nunca llega a `_handle_command` ni pisa `_pending_user_text`.
    composer.set_text("B")
    composer._send_button.click()
    assert window._pending_user_text == "A"
    assert len([r for r in registro if getattr(r[0], "__name__", "") == "resolve"]) == 1

    # "A" resuelve: se persiste con SU PROPIO texto de usuario, nunca con "B".
    resolution_a = MagicMock()
    resolution_a.text = "respuesta A"
    resolution_a.matched_by = "chat"
    window._on_command_done(resolution_a)

    persistidas = [r for r in registro if getattr(r[0], "__name__", "") == "store_turn"]
    assert len(persistidas) == 1
    assert persistidas[0][1][0] == "A"
    assert persistidas[0][1][1] == "respuesta A"
    assert composer._input.isEnabled() is True
    assert window._pending_user_text == ""

    # El composer se liberó: ahora "B" sí se puede enviar.
    composer._send_button.click()
    assert window._pending_user_text == "B"
    resueltos = [r for r in registro if getattr(r[0], "__name__", "") == "resolve"]
    assert len(resueltos) == 2


def test_main_window_nueva_conversacion_limpia_feed_y_resetea_id(qtbot, no_external_io):
    """CA-07 — limpiar el feed no borra nada persistido."""
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._conversation_id = "cid-existente"
    window.center_panel.add_user_message("hola")
    window.center_panel.show_response("qué tal")

    window._on_new_conversation()

    assert window._conversation_id is None
    assert window.center_panel._feed.is_empty() is True


def test_main_window_doble_nueva_conversacion_no_acuna_ids(qtbot, no_external_io):
    """Caso borde de la SPEC: dos clics seguidos no dejan conversaciones fantasma."""
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._on_new_conversation()
    window._on_new_conversation()

    assert window._conversation_id is None


def test_main_window_carga_tema_de_config_al_iniciar(
    qtbot, no_external_io, theme_sandbox, monkeypatch
):
    """CA-02 — la preferencia persistida se aplica antes de construir los widgets."""
    monkeypatch.setattr(theme_module.config_manager, "get_ui_theme", lambda: "light")

    window = JarvisMainWindow()
    qtbot.addWidget(window)

    assert theme_manager.current_name() == "light"


def test_toggle_tema_cambia_stylesheet_de_sidebar_feed_composer_y_right_panel(
    qtbot, no_external_io, theme_sandbox
):
    """CA-01, CA-04, CA-21 — el cambio de tema alcanza a los cuatro bloques del panel."""
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    antes = {
        "sidebar": window.sidebar.styleSheet(),
        "feed": window.center_panel._feed.styleSheet(),
        "composer": window.center_panel._composer.styleSheet(),
        "right_panel": window.right_panel.styleSheet(),
    }

    theme_manager.set_theme("light")

    assert window.sidebar.styleSheet() != antes["sidebar"]
    assert window.center_panel._feed.styleSheet() != antes["feed"]
    assert window.center_panel._composer.styleSheet() != antes["composer"]
    assert window.right_panel.styleSheet() != antes["right_panel"]


def test_cambio_de_tema_no_altera_conversacion_activa(qtbot, no_external_io, theme_sandbox):
    """Caso borde de la SPEC: cambiar de tema solo reemplaza hojas de estilo."""
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    window._conversation_id = "cid-1"
    window.center_panel.add_user_message("hola")
    window.center_panel.show_response("qué tal")

    theme_manager.set_theme("light")

    assert window._conversation_id == "cid-1"
    assert window.center_panel._feed.message_count() == 2


def test_right_panel_y_las_4_tarjetas_siguen_visibles_en_el_layout(qtbot, no_external_io):
    """CA-20 — el rediseño no elimina el panel derecho ni ninguna de sus tarjetas."""
    window = JarvisMainWindow()
    qtbot.addWidget(window)

    assert isinstance(window.right_panel, RightPanel)
    assert window.findChild(SystemStatusCard) is not None
    assert window.findChild(QuickActionsCard) is not None
    assert window.findChild(RecentActivityCard) is not None
    assert window.findChild(WeatherCard) is not None


def test_sidebar_conversaciones_habilitado_y_resto_placeholders_deshabilitados(qtbot):
    """CA-08."""
    from PyQt6.QtWidgets import QPushButton

    sidebar = Sidebar()
    qtbot.addWidget(sidebar)

    nav = [b for b in sidebar.findChildren(QPushButton)
           if b.objectName() == "SidebarNavButton"]
    habilitados = [b.text() for b in nav if b.isEnabled()]

    assert len(nav) == 7
    assert len(habilitados) == 2
    assert any("Inicio" in texto for texto in habilitados)
    assert any("Conversaciones" in texto for texto in habilitados)


def test_center_panel_expone_composer_para_el_toggle_de_manos_libres(qtbot):
    """CA-16 — el toggle se movió al `Composer`; `CenterPanel._wake_toggle` sigue siendo
    el mismo objeto (contrato de REQ-009)."""
    panel = CenterPanel()
    qtbot.addWidget(panel)

    assert isinstance(panel._composer, Composer)
    assert panel._wake_toggle is panel._composer._wake_toggle
