"""
tests/test_autonomy.py
REQ-033 — El modo autonomía.

Este REQ QUITA protecciones a pedido del dueño, así que estos tests son el contrato: lo
que importa no es tanto lo que el modo permite, sino **lo que sigue prohibido con el modo
encendido**. Si alguna vez uno de los tests de "no aprueba" empieza a fallar, la autonomía
dejó de estar acotada.

Ningún test toca el `autonomy_mode.json` real: se redirige a `tmp_path`.
"""

import json

import pytest

import core.autonomy as autonomy
from core.autonomy import NIVEL_NORMAL, NIVEL_PROYECTOS, NIVEL_TOTAL
from core.security_manager import ChannelType, RiskLevel, security_manager

CANALES_REMOTOS = [
    ChannelType.TELEGRAM, ChannelType.DISCORD, ChannelType.VOICE,
    ChannelType.API, ChannelType.EMAIL, ChannelType.UNKNOWN,
]

#: Los otros nueve rojos de REQ-005. Ninguno se desbloquea nunca.
OTRAS_ROJAS = [
    "format_disk", "delete_database", "expose_secrets", "send_email_as_user",
    "post_social_media", "elevated_system_command", "install_uninstall_software",
    "modify_system_env_vars", "SEND_EMAIL",
]


@pytest.fixture(autouse=True)
def archivo_aislado(monkeypatch, tmp_path):
    monkeypatch.setattr(autonomy, "ARCHIVO_AUTONOMIA", str(tmp_path / "autonomy_mode.json"))
    return tmp_path / "autonomy_mode.json"


# ─────────────────────────── fail-closed ───────────────────────────

def test_sin_archivo_el_modo_es_normal():
    """El estado de fábrica: pregunta todo."""
    assert autonomy.modo_actual() == NIVEL_NORMAL


def test_un_archivo_corrupto_no_enciende_la_autonomia(archivo_aislado):
    """Lo más importante del módulo: un archivo roto JAMÁS puede leerse como 'encendido'."""
    archivo_aislado.write_text("{roto", encoding="utf-8")

    assert autonomy.modo_actual() == NIVEL_NORMAL


def test_un_nivel_desconocido_no_enciende_la_autonomia(archivo_aislado):
    archivo_aislado.write_text(json.dumps({"nivel": "dios"}), encoding="utf-8")

    assert autonomy.modo_actual() == NIVEL_NORMAL


def test_un_json_que_no_es_objeto_no_enciende_la_autonomia(archivo_aislado):
    archivo_aislado.write_text(json.dumps(["total"]), encoding="utf-8")

    assert autonomy.modo_actual() == NIVEL_NORMAL


def test_guardar_y_leer_el_nivel(archivo_aislado):
    autonomy.guardar_modo(NIVEL_PROYECTOS)

    assert autonomy.modo_actual() == NIVEL_PROYECTOS
    assert autonomy.estado()["activo"] is True
    assert autonomy.estado()["desde"], "tiene que quedar registrado desde cuándo"


def test_un_nivel_invalido_no_se_guarda():
    with pytest.raises(ValueError):
        autonomy.guardar_modo("lo-que-sea")


def test_apagarlo_lo_deja_en_normal(archivo_aislado):
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")
    autonomy.guardar_modo(NIVEL_NORMAL)

    assert autonomy.modo_actual() == NIVEL_NORMAL
    assert autonomy.estado()["activo"] is False


# ─────────────────────────── lo que SÍ aprueba ───────────────────────────

@pytest.mark.parametrize("accion", ["file_write", "file_edit", "project_run"])
def test_las_acciones_de_trabajo_no_preguntan_con_el_modo_encendido(accion):
    autonomy.guardar_modo(NIVEL_PROYECTOS)

    assert autonomy.aprueba_sin_preguntar(accion, ChannelType.DESKTOP) is True


def test_el_nivel_total_autoriza_su_propio_codigo():
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert autonomy.aprueba_rojo("modify_source_code", ChannelType.DESKTOP) is True
    assert autonomy.puede_tocar_su_propio_codigo() is True


# ─────────────────────────── lo que NO aprueba (el contrato) ───────────────────────────

def test_en_modo_normal_no_aprueba_nada():
    assert autonomy.aprueba_sin_preguntar("file_write", ChannelType.DESKTOP) is False
    assert autonomy.aprueba_rojo("modify_source_code", ChannelType.DESKTOP) is False


@pytest.mark.parametrize("canal", CANALES_REMOTOS)
def test_ningun_canal_remoto_hereda_la_autonomia(canal):
    """La regla que sostiene todo lo demás: el modo vive en el escritorio. Si Telegram lo
    heredara, un mensaje —o una inyección en una página que esté leyendo— actuaría con
    permiso total y sin nadie mirando."""
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert autonomy.aprueba_sin_preguntar("file_write", canal) is False
    assert autonomy.aprueba_rojo("modify_source_code", canal) is False


@pytest.mark.parametrize("accion", ["shutdown", "delete_task", "pc_type", "terminal_run_command",
                                    "http_request", "workspace_add_folder",
                                    # REQ-035: borrar y mover se deshacen con git SOLO si el
                                    # archivo estaba versionado, y eso no lo sabe nadie a las
                                    # 3 de la mañana. Se confirman siempre.
                                    "file_delete", "file_move"])
def test_las_amarillas_que_no_son_de_trabajo_siguen_preguntando(accion):
    """"Trabajar sin preguntar" es sobre CÓDIGO. Apagar el equipo, mandar un mensaje o
    habilitar otra carpeta no son parte de lo que se autorizó."""
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert autonomy.aprueba_sin_preguntar(accion, ChannelType.DESKTOP) is False


@pytest.mark.parametrize("accion", OTRAS_ROJAS)
def test_los_otros_rojos_no_se_desbloquean_ni_en_total(accion):
    """Formatear discos, borrar bases, exponer credenciales, mandar correo como el usuario.
    El pedido era sobre programar."""
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert autonomy.aprueba_rojo(accion, ChannelType.DESKTOP) is False


def test_el_nivel_proyectos_no_toca_su_propio_codigo():
    """Son dos niveles distintos a propósito: uno se prende con un clic, el otro con PIN."""
    autonomy.guardar_modo(NIVEL_PROYECTOS)

    assert autonomy.aprueba_rojo("modify_source_code", ChannelType.DESKTOP) is False
    assert autonomy.puede_tocar_su_propio_codigo() is False


# ─────────────── el gate de verdad: require_confirmation() ───────────────

def test_con_autonomia_la_escritura_pasa_sin_adaptador_de_confirmacion():
    """La prueba que representa la noche entera: sin adaptador no hay a quién preguntarle,
    y hoy eso significa bloquear (fail-closed). Con el modo encendido, pasa."""
    autonomy.guardar_modo(NIVEL_PROYECTOS)

    assert security_manager.require_confirmation(
        "file_write", ChannelType.DESKTOP, details="path=C:/repo/x.py"
    ) is True


def test_con_autonomia_ni_siquiera_le_pregunta_a_nadie(monkeypatch):
    """No es que la respuesta sea "sí": es que la pregunta no se hace. Eso es lo que hace
    que sirva de noche, cuando no hay nadie para contestarla."""
    preguntas = []
    monkeypatch.setattr(
        "core.confirmation.get_confirmation_adapter",
        lambda canal: (lambda accion, mensaje: preguntas.append(accion) or True),
    )
    autonomy.guardar_modo(NIVEL_PROYECTOS)

    assert security_manager.require_confirmation("file_write", ChannelType.DESKTOP) is True
    assert preguntas == [], "con el modo encendido no tenía que preguntar nada"


def test_sin_autonomia_la_decision_sigue_siendo_del_humano(monkeypatch):
    """La contracara: sin el modo, pregunta — y si el humano dice que no, no se escribe."""
    preguntas = []
    monkeypatch.setattr(
        "core.confirmation.get_confirmation_adapter",
        lambda canal: (lambda accion, mensaje: preguntas.append(accion) or False),
    )

    assert security_manager.require_confirmation("file_write", ChannelType.DESKTOP) is False
    assert preguntas == ["file_write"], "tenía que preguntarle a alguien"


def test_con_autonomia_total_el_gate_autoriza_modificar_su_codigo():
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert security_manager.require_confirmation(
        "modify_source_code", ChannelType.DESKTOP, details="path=core/x.py"
    ) is True


@pytest.mark.parametrize("canal", CANALES_REMOTOS)
def test_el_gate_sigue_bloqueando_su_codigo_desde_canales_remotos(canal):
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert security_manager.require_confirmation("modify_source_code", canal) is False


def test_el_gate_sigue_bloqueando_las_otras_rojas_con_autonomia_total():
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert security_manager.require_confirmation(
        "delete_database", ChannelType.DESKTOP
    ) is False


def test_modify_source_code_sigue_siendo_rojo_con_el_modo_encendido():
    """El modo NO baja el nivel de nada: autoriza una acción puntual. Bajarlo sería
    permanente y alcanzaría a todos los canales."""
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")

    assert security_manager.classify_action("modify_source_code") == RiskLevel.RED


# ─────────────── el confinamiento de rutas ───────────────

def test_con_el_modo_total_puede_resolver_una_ruta_de_su_propio_codigo():
    import os

    from core.workspace_files import resolver

    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")
    propio = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(autonomy.__file__))),
                          "main.py")

    assert resolver(propio, ["C:/lo-que-sea"]) == os.path.realpath(propio)


def test_apagar_el_modo_vuelve_a_cerrar_su_propio_codigo():
    """No se cachea: apagarlo tiene efecto en la operación siguiente, no en el próximo
    arranque."""
    import os

    from core.workspace_files import RutaFueraDeRaiz, resolver

    propio = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(autonomy.__file__))),
                          "main.py")
    autonomy.guardar_modo(NIVEL_TOTAL, rama="autonomia/prueba")
    resolver(propio, ["C:/lo-que-sea"])  # entra

    autonomy.guardar_modo(NIVEL_NORMAL)

    with pytest.raises(RutaFueraDeRaiz):
        resolver(propio, ["C:/lo-que-sea"])
