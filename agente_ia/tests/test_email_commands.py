"""
tests/test_email_commands.py
REQ-049 — órdenes por correo, acotadas a herramientas MCP de solo lectura.

Lo que protege esta suite:
- Solo un correo con el prefijo, de un remitente de la lista, verificado por un servidor
  de confianza, se atiende. Cualquier otra combinación se descarta (fail-closed).
- Sin `trusted_authserv_ids` no se atiende ninguna orden: sin eso, la lista de remitentes
  la burla cualquiera escribiendo el `From`.
- La orden corre en el canal EMAIL sin turnos previos y la respuesta vuelve al remitente
  en el mismo hilo; el envío queda auditado.
- El adaptador del canal EMAIL aprueba SOLO herramientas `mcp__*` con excepción para
  EMAIL, y `mcp_manager` solo da esa excepción a herramientas `readOnlyHint`.
- `catalogo_para_modelo` ofrece las herramientas con excepción de canal (también arregla
  Telegram/Discord, donde una MCP amarilla habilitada no se ofrecía).
- Sin el interruptor encendido no se procesa nada.

Sin IMAP ni SMTP: los mensajes se construyen con `email.message.EmailMessage`.
"""

import email.message
from unittest.mock import patch

import pytest

import agents.tool_registry as registry
from agents.tool_registry import ToolSpec, register_tool, unregister_tool
from core import email_commands, mcp_manager
from core.security_manager import CHANNEL_ACTION_EXCEPTIONS, ChannelType, RiskLevel, security_manager

CUENTA = {
    "host": "imap.ejemplo.com", "user": "yo@ejemplo.com", "password": "x",
    "command_senders": ["Yo@Ejemplo.com"],
    "sender_auth": {"min": "none", "trusted_authserv_ids": ["mx.ejemplo.com"]},
}


def _mensaje(remitente="yo@ejemplo.com", asunto="ORION: qué hay en Notion sobre la reunión",
             cuerpo="Necesito el resumen.", auth="mx.ejemplo.com; dkim=pass spf=pass"):
    m = email.message.EmailMessage()
    m["From"] = remitente
    m["To"] = "yo@ejemplo.com"
    m["Subject"] = asunto
    m["Message-ID"] = "<abc@ejemplo.com>"
    if auth is not None:
        m["Authentication-Results"] = auth
    m.set_content(cuerpo)
    return m


@pytest.fixture(autouse=True)
def _sin_config_general(monkeypatch):
    monkeypatch.setattr(email_commands.email_reader, "cargar_config", lambda: {})


@pytest.fixture
def ejecucion(monkeypatch):
    """`run()` y `enviar()` falsos: registran con qué se llamaron."""
    visto = {"ordenes": [], "enviados": [], "auditadas": []}

    def run_falso(texto, canal, user_id="default", **kwargs):
        visto["ordenes"].append((texto, canal, user_id, kwargs))
        return "Hay tres notas sobre la reunión."

    def enviar_falso(config, destinatarios, asunto, cuerpo, responder_a=None):
        visto["enviados"].append((destinatarios, asunto, cuerpo, responder_a))
        return f"a {destinatarios[0]}"

    monkeypatch.setattr("core.reasoning_loop.run", run_falso)
    monkeypatch.setattr(email_commands.email_sender, "enviar", enviar_falso)
    monkeypatch.setattr(security_manager, "log_action",
                        lambda *a, **k: visto["auditadas"].append((a, k)))
    return visto


# ── qué es una orden ────────────────────────────────────────────────

def test_un_correo_sin_prefijo_no_es_una_orden():
    assert email_commands.extraer_orden(_mensaje(asunto="Hola, ¿cómo va?"), CUENTA) is None


def test_la_orden_es_el_asunto_sin_prefijo_mas_el_cuerpo():
    texto = email_commands.extraer_orden(_mensaje(), CUENTA)
    assert texto.startswith("qué hay en Notion sobre la reunión")
    assert "Necesito el resumen." in texto


def test_el_prefijo_se_puede_configurar_y_no_distingue_mayusculas():
    cuenta = {**CUENTA, "command_prefix": "Agente:"}
    assert email_commands.extraer_orden(_mensaje(asunto="agente: hola"), cuenta) == "hola\n\nNecesito el resumen."


# ── quién puede dar órdenes ─────────────────────────────────────────

def test_remitente_verificado_de_la_lista_pasa():
    assert email_commands.validar_remitente(_mensaje(), CUENTA) == "yo@ejemplo.com"


def test_sin_lista_de_remitentes_nadie_puede():
    with pytest.raises(email_commands.OrdenRechazada):
        email_commands.validar_remitente(_mensaje(), {**CUENTA, "command_senders": []})


def test_un_remitente_fuera_de_la_lista_se_rechaza():
    with pytest.raises(email_commands.OrdenRechazada):
        email_commands.validar_remitente(_mensaje(remitente="otro@ejemplo.com"), CUENTA)


def test_sin_servidores_de_confianza_no_se_atiende_nada():
    cuenta = {**CUENTA, "sender_auth": {"min": "none"}}
    with pytest.raises(email_commands.OrdenRechazada) as exc:
        email_commands.validar_remitente(_mensaje(), cuenta)
    assert "trusted_authserv_ids" in str(exc.value)


@pytest.mark.parametrize("auth", [
    None,                                    # sin cabecera
    "mx.ejemplo.com; dkim=fail spf=fail",    # falló
    "atacante.com; dkim=pass spf=pass",      # cabecera de un servidor que no es de confianza
])
def test_una_suplantacion_se_rechaza_aunque_la_cuenta_no_exija_nada(auth):
    with pytest.raises(email_commands.OrdenRechazada):
        email_commands.validar_remitente(_mensaje(auth=auth), CUENTA)


# ── ejecución y respuesta ───────────────────────────────────────────

def test_una_orden_valida_corre_en_email_sin_turnos_previos_y_responde_al_remitente(ejecucion):
    respuesta = email_commands.procesar_mensaje("principal", CUENTA, _mensaje())

    assert respuesta == "Hay tres notas sobre la reunión."
    texto, canal, user_id, kwargs = ejecucion["ordenes"][0]
    assert canal is ChannelType.EMAIL
    assert kwargs.get("prior_turns") == []
    destinatarios, asunto, cuerpo, responder_a = ejecucion["enviados"][0]
    assert destinatarios == ["yo@ejemplo.com"]
    assert asunto == "Re: ORION: qué hay en Notion sobre la reunión"
    assert cuerpo == respuesta
    assert responder_a["message_id"] == "<abc@ejemplo.com>"
    assert ejecucion["auditadas"][0][0][0] == "email_command_reply"


def test_un_correo_que_no_es_orden_no_ejecuta_ni_responde(ejecucion):
    assert email_commands.procesar_mensaje("principal", CUENTA, _mensaje(asunto="hola")) is None
    assert ejecucion["ordenes"] == [] and ejecucion["enviados"] == []


def test_un_remitente_no_verificado_no_ejecuta_ni_responde(ejecucion):
    assert email_commands.procesar_mensaje("principal", CUENTA, _mensaje(auth=None)) is None
    assert ejecucion["ordenes"] == [] and ejecucion["enviados"] == []


def test_si_el_envio_falla_no_revienta(ejecucion, monkeypatch):
    def explota(*a, **k):
        raise email_commands.email_sender.EnvioError("smtp caído")

    monkeypatch.setattr(email_commands.email_sender, "enviar", explota)
    assert email_commands.procesar_mensaje("principal", CUENTA, _mensaje()) == "Hay tres notas sobre la reunión."


# ── el interruptor ──────────────────────────────────────────────────

def test_sin_el_interruptor_no_se_revisa_nada(monkeypatch):
    monkeypatch.setattr(email_commands, "esta_activa", lambda: False)
    llamadas = []
    monkeypatch.setattr(email_commands.email_reader, "cargar_cuentas",
                        lambda: llamadas.append(1) or {"principal": CUENTA})

    assert email_commands.revisar_ordenes() == []
    assert llamadas == []
    assert email_commands.start_polling() is False


def test_la_capacidad_existe_y_esta_apagada_por_defecto(tmp_path, monkeypatch):
    from core import email_capabilities

    monkeypatch.setattr(email_capabilities, "CAPABILITIES_FILE", str(tmp_path / "caps.json"))
    assert "commands" in email_capabilities.CAPACIDADES
    assert email_capabilities.esta_activa("commands") is False


# ── el adaptador del canal EMAIL ────────────────────────────────────

def test_el_adaptador_aprueba_solo_remotas_con_excepcion_para_correo():
    CHANNEL_ACTION_EXCEPTIONS.add((ChannelType.EMAIL, "mcp__notion__search"))
    try:
        assert email_commands.confirmar_por_correo("mcp__notion__search", "") is True
        assert email_commands.confirmar_por_correo("mcp__notion__create_page", "") is False
        assert email_commands.confirmar_por_correo("file_read", "") is False
        assert email_commands.confirmar_por_correo("delete_task", "") is False
    finally:
        CHANNEL_ACTION_EXCEPTIONS.discard((ChannelType.EMAIL, "mcp__notion__search"))


def test_main_registra_el_adaptador_de_correo():
    from pathlib import Path

    fuente = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    assert "register_confirmation_adapter(ChannelType.EMAIL, _confirmar_por_correo)" in fuente


# ── solo lectura, y el catálogo por canal ───────────────────────────

def test_mcp_manager_solo_da_el_canal_correo_a_herramientas_de_solo_lectura(monkeypatch):
    monkeypatch.setattr(mcp_manager, "canales_permitidos", lambda servidor: ["desktop", "email"])
    try:
        aplicados = mcp_manager._habilitar_canales("mcp__srv__lee", "srv", False, solo_lectura=True)
        assert aplicados == ["desktop", "email"]
        assert (ChannelType.EMAIL, "mcp__srv__lee") in CHANNEL_ACTION_EXCEPTIONS

        aplicados = mcp_manager._habilitar_canales("mcp__srv__escribe", "srv", False, solo_lectura=False)
        assert aplicados == ["desktop"]
        assert (ChannelType.EMAIL, "mcp__srv__escribe") not in CHANNEL_ACTION_EXCEPTIONS
    finally:
        for nombre in ("mcp__srv__lee", "mcp__srv__escribe"):
            for canal in (ChannelType.DESKTOP, ChannelType.EMAIL):
                CHANNEL_ACTION_EXCEPTIONS.discard((canal, nombre))


def test_es_solo_lectura_lee_la_anotacion_del_servidor():
    assert mcp_manager._es_solo_lectura({"annotations": {"readOnlyHint": True}}) is True
    assert mcp_manager._es_solo_lectura({"annotations": {"readOnlyHint": "true"}}) is False
    assert mcp_manager._es_solo_lectura({}) is False


def test_el_catalogo_ofrece_lo_habilitado_por_excepcion_en_cada_canal():
    """Una MCP amarilla habilitada para Telegram no está en los niveles del canal; sin la
    excepción en el catálogo el modelo nunca la veía ahí aunque el gate la dejara pasar."""
    register_tool(ToolSpec(
        name="mcp__srv__lee", description="lee", parameters_schema={"type": "object", "properties": {}},
        risk_level=RiskLevel.YELLOW, invoke=lambda p: "ok", origin="local",
    ))
    try:
        assert "mcp__srv__lee" not in {t["name"] for t in registry.catalogo_para_modelo(ChannelType.TELEGRAM)}
        assert "mcp__srv__lee" not in {t["name"] for t in registry.catalogo_para_modelo(ChannelType.EMAIL)}

        CHANNEL_ACTION_EXCEPTIONS.add((ChannelType.TELEGRAM, "mcp__srv__lee"))
        CHANNEL_ACTION_EXCEPTIONS.add((ChannelType.EMAIL, "mcp__srv__lee"))
        assert "mcp__srv__lee" in {t["name"] for t in registry.catalogo_para_modelo(ChannelType.TELEGRAM)}
        ofrecidas_email = {t["name"] for t in registry.catalogo_para_modelo(ChannelType.EMAIL)}
        assert ofrecidas_email == {"mcp__srv__lee"}          # y NADA más por correo
        assert "mcp__srv__lee" not in {t["name"] for t in registry.catalogo_para_modelo(ChannelType.DISCORD)}
    finally:
        CHANNEL_ACTION_EXCEPTIONS.discard((ChannelType.TELEGRAM, "mcp__srv__lee"))
        CHANNEL_ACTION_EXCEPTIONS.discard((ChannelType.EMAIL, "mcp__srv__lee"))
        unregister_tool("mcp__srv__lee")


def test_por_correo_una_herramienta_excepcionada_pasa_el_gate_y_las_demas_no(monkeypatch):
    """El gate real: YELLOW en EMAIL consulta al adaptador de correo, que aprueba solo lo
    preautorizado. Sin excepción, `is_action_allowed` ya dice que no."""
    from core.confirmation import register_confirmation_adapter

    register_confirmation_adapter(ChannelType.EMAIL, email_commands.confirmar_por_correo)
    security_manager.register_action("mcp__srv__lee", RiskLevel.YELLOW)
    security_manager.register_action("mcp__srv__escribe", RiskLevel.YELLOW)
    CHANNEL_ACTION_EXCEPTIONS.add((ChannelType.EMAIL, "mcp__srv__lee"))
    try:
        assert security_manager.require_confirmation("mcp__srv__lee", ChannelType.EMAIL) is True
        assert security_manager.require_confirmation("mcp__srv__escribe", ChannelType.EMAIL) is False
        assert security_manager.require_confirmation("open_app", ChannelType.EMAIL) is False
    finally:
        CHANNEL_ACTION_EXCEPTIONS.discard((ChannelType.EMAIL, "mcp__srv__lee"))
