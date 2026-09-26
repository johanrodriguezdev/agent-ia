"""
os_integration/navegador_cdp.py
El navegador en Linux, por el protocolo del propio navegador — REQ-069.

**Por qué existe.** Todo lo que el agente sabía hacer con el navegador estaba construido
sobre UI Automation, la API de accesibilidad de Windows: leer la página, pulsar un enlace,
cambiar de pestaña. Fuera de Windows eso no existe, así que en Linux las siete herramientas
`browser_*` estaban muertas.

**Por qué CDP y no la accesibilidad de Linux (AT-SPI).** Porque el navegador ya publica un
protocolo hecho para esto —el mismo que usan las herramientas de desarrollo de Chrome—, y
porque es el camino que toma OpenClaw. Con AT-SPI se leería *lo que se ve dibujado*; con
CDP se lee *el documento*, que es más fiable y no depende de que la página esté visible.

**Lo que se pierde, dicho antes de que sorprenda.** CDP solo alcanza a un navegador que se
haya iniciado con `--remote-debugging-port`. Un Chrome que el usuario ya tenía abierto no
se puede controlar: Chrome no acepta encender la depuración en caliente. Así que acá el
agente **lanza su propia ventana**, con un perfil aparte, y trabaja sobre ella. No son las
pestañas del usuario y no tiene sus sesiones iniciadas: para «leé mi correo» haría falta la
otra vía —una extensión de navegador, que es el segundo mecanismo de OpenClaw— y eso es
otro trabajo.

**En Windows esto no se usa.** Ahí sigue mandando `navegador.py` con UI Automation, que sí
lee el Chrome que el usuario ya tiene abierto. Este módulo es el adaptador del otro lado.
"""

import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Cuánto texto de una página se entrega como máximo. El mismo tope que la vía de Windows.
MAX_CARACTERES_DE_TEXTO = 6000

#: Cuántos elementos accionables se enumeran.
MAX_ELEMENTOS_DE_PAGINA = 40

#: Cuánto se espera a que el navegador levante su puerto de depuración.
_SEGUNDOS_PARA_QUE_ARRANQUE = 15.0

#: Cuánto se espera una respuesta del protocolo.
_SEGUNDOS_DE_PACIENCIA = 20.0

#: El proceso del navegador que lanzó el agente, y su puerto. Se conservan para no abrir
#: una ventana nueva en cada orden: «abrí esta página» y después «pulsá aceptar» tienen que
#: caer en la misma ventana.
_proceso: Optional[subprocess.Popen] = None
_puerto: Optional[int] = None
_perfil: Optional[str] = None


# ============================================================================ el navegador

def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ejecutable() -> Optional[Tuple[str, str]]:
    """Return `(nombre, ruta)` de un navegador basado en Chromium, o None.

    Firefox no sirve acá: habla otro protocolo de depuración, no CDP.
    """
    from os_integration.navegador import NAVEGADORES

    for nombre, candidatos in NAVEGADORES:
        if "Firefox" in nombre:
            continue
        for candidato in candidatos:
            if "\\" in candidato or "/" in candidato:
                if os.path.exists(candidato):
                    return nombre, candidato
                continue
            encontrado = shutil.which(candidato)
            if encontrado:
                return nombre, encontrado
    return None


def disponible() -> bool:
    """Return True si hay con qué manejar un navegador en este equipo."""
    return _ejecutable() is not None


def _vivo() -> bool:
    return _proceso is not None and _proceso.poll() is None


def _asegurar_navegador() -> Optional[str]:
    """Levanta el navegador si hace falta. Return un mensaje de error, o None si todo bien."""
    global _proceso, _puerto, _perfil

    if _vivo():
        return None

    encontrado = _ejecutable()
    if not encontrado:
        return ("No encontré Chrome ni Chromium en este equipo. Instalá uno para que pueda "
                "manejar el navegador.")
    nombre, ruta = encontrado
    _puerto = _puerto_libre()
    # Perfil propio y descartable: con el del usuario, Chrome se niega a abrir una segunda
    # instancia y nos devolvería el control de nada.
    _perfil = tempfile.mkdtemp(prefix="orion-navegador-")

    error = _intentar_lanzar(nombre, ruta, sin_sandbox=False)
    if error and _en_contenedor():
        # Dentro de un contenedor, Chromium puede no poder crear sus espacios de nombres y
        # cerrarse al instante. Ahí —y SOLO ahí— se reintenta sin su recinto de seguridad:
        # el aislamiento lo pone el contenedor. En un escritorio normal esto no se hace
        # nunca, porque apagaría una protección real del navegador.
        logger.warning(f"{nombre} no arrancó con su recinto de seguridad; dentro de un "
                       f"contenedor se reintenta sin él: {error}")
        error = _intentar_lanzar(nombre, ruta, sin_sandbox=True)
    return error


def _en_contenedor() -> bool:
    """Return si esto corre dentro de un contenedor."""
    from os_integration.plataforma._linux import _en_contenedor as _dentro

    return _dentro()


def _intentar_lanzar(nombre: str, ruta: str, sin_sandbox: bool) -> Optional[str]:
    """Levanta el navegador y espera a que conteste. Return el error, o None si contestó."""
    global _proceso

    argumentos = [
        ruta,
        f"--remote-debugging-port={_puerto}",
        f"--user-data-dir={_perfil}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-background-networking",
    ]
    # Sin pantalla no hay dónde dibujar una ventana, y Chromium se cierra al arrancar. Es
    # lo que pasa por SSH, en el modo consola y dentro de un contenedor sin X11. En modo
    # «headless» el navegador funciona igual para lo que el agente necesita —leer la
    # página y pulsar en ella—, solo que nadie lo ve. Con pantalla se abre normal, que es
    # lo que se quiere en un escritorio: el usuario mira lo que el agente hace.
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        argumentos.append("--headless=new")
    if sin_sandbox:
        # `--disable-dev-shm-usage` va con esto: la memoria compartida por defecto de un
        # contenedor es de 64 MB y Chromium la agota y se cuelga a media página.
        argumentos += ["--no-sandbox", "--disable-dev-shm-usage"]
    argumentos.append("about:blank")

    try:
        _proceso = subprocess.Popen(argumentos, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
    except OSError as e:
        logger.error(f"no se pudo lanzar {nombre}: {e}")
        return f"No pude abrir {nombre}: {e}"

    limite = time.time() + _SEGUNDOS_PARA_QUE_ARRANQUE
    while time.time() < limite:
        if _proceso.poll() is not None:
            return f"{nombre} se cerró apenas arrancó."
        if _pedir("/json/version") is not None:
            return None
        time.sleep(0.2)
    return f"{nombre} no respondió a tiempo."


def cerrar_navegador() -> None:
    """Cierra la ventana que el agente abrió. La usa la salida de la aplicación y los tests."""
    global _proceso, _puerto, _perfil

    if _vivo():
        try:
            _proceso.terminate()
            _proceso.wait(timeout=5)
        except Exception as e:
            logger.debug(f"el navegador no cerró limpio: {e}")
            try:
                _proceso.kill()
            except Exception:
                pass
    if _perfil and os.path.isdir(_perfil):
        shutil.rmtree(_perfil, ignore_errors=True)
    _proceso, _puerto, _perfil = None, None, None


# ============================================================================== el protocolo

def _pedir(ruta: str) -> Optional[Any]:
    """GET al puerto de depuración. Return lo que devuelva, o None si no contesta."""
    if _puerto is None:
        return None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{_puerto}{ruta}", timeout=5) as r:
            cuerpo = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        logger.debug(f"el navegador no respondió a {ruta}: {e}")
        return None
    try:
        return json.loads(cuerpo)
    except json.JSONDecodeError:
        return cuerpo


def _pestanas() -> List[Dict[str, Any]]:
    """Return las pestañas reales (las páginas, no los service workers ni las extensiones)."""
    datos = _pedir("/json/list")
    if not isinstance(datos, list):
        return []
    return [t for t in datos if t.get("type") == "page" and not
            str(t.get("url", "")).startswith("devtools://")]


def _pestana_activa() -> Optional[Dict[str, Any]]:
    """Return la pestaña sobre la que se trabaja: la última con la que se interactuó.

    El protocolo lista primero la que tiene el foco, así que la primera de la lista es la
    que el usuario está viendo.
    """
    pestanas = _pestanas()
    return pestanas[0] if pestanas else None


def _evaluar(js: str, pestana: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], str]:
    """Ejecuta JavaScript en la pestaña. Return `(resultado, error)`.

    Es por WebSocket porque el protocolo solo acepta comandos por ahí; lo demás —listar,
    abrir, cerrar, activar— se resuelve por HTTP y no necesita esta dependencia.
    """
    try:
        from websocket import create_connection          # websocket-client
    except ImportError:
        return None, ("Falta la dependencia 'websocket-client' para leer la página "
                      "(pip install websocket-client).")

    objetivo = pestana or _pestana_activa()
    if not objetivo or not objetivo.get("webSocketDebuggerUrl"):
        return None, "No hay ninguna pestaña abierta que pueda leer."

    try:
        # `suppress_origin`: Chromium rechaza con 403 cualquier conexión que traiga una
        # cabecera `Origin` que no haya autorizado. La salida fácil sería lanzarlo con
        # `--remote-allow-origins=*`, que abre su depuración a cualquier página que el
        # propio navegador esté mostrando. No mandar la cabecera resuelve lo mismo sin
        # bajar nada: el puerto ya escucha solo en 127.0.0.1.
        ws = create_connection(objetivo["webSocketDebuggerUrl"],
                               timeout=_SEGUNDOS_DE_PACIENCIA, suppress_origin=True)
    except Exception as e:
        logger.warning(f"no se pudo abrir el canal con la pestaña: {e}")
        return None, f"No pude conectarme a la pestaña: {e}"

    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": js, "returnByValue": True, "awaitPromise": True},
        }))
        # El navegador manda también notificaciones sin `id`; se descartan hasta la nuestra.
        limite = time.time() + _SEGUNDOS_DE_PACIENCIA
        while time.time() < limite:
            respuesta = json.loads(ws.recv())
            if respuesta.get("id") != 1:
                continue
            if "error" in respuesta:
                return None, str(respuesta["error"].get("message", "error del navegador"))
            resultado = respuesta.get("result", {})
            if resultado.get("exceptionDetails"):
                detalle = resultado["exceptionDetails"].get("text", "error en la página")
                return None, str(detalle)
            return resultado.get("result", {}).get("value"), ""
        return None, "La página no respondió a tiempo."
    except Exception as e:
        logger.warning(f"fallo hablando con la pestaña: {e}")
        return None, f"No pude leer la página: {e}"
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ================================================================== lo que usa el agente

def abrir(url: str) -> str:
    """Abre una dirección en el navegador del agente. Return qué pasó."""
    if not url or not str(url).strip():
        return "Necesito la dirección que querés abrir."
    direccion = str(url).strip()
    if not direccion.startswith(("http://", "https://", "file://", "about:")):
        direccion = "https://" + direccion

    error = _asegurar_navegador()
    if error:
        return error

    # `/json/new` crea la pestaña sin tocar el WebSocket, así que abrir una página funciona
    # aunque falte 'websocket-client'.
    destino = f"/json/new?{urllib.parse.quote(direccion, safe=':/?&=#%')}"
    try:
        peticion = urllib.request.Request(f"http://127.0.0.1:{_puerto}{destino}", method="PUT")
        with urllib.request.urlopen(peticion, timeout=10) as r:
            creada = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        logger.debug(f"no se pudo abrir la pestaña con PUT: {e}")
        creada = _pedir(destino)

    if not isinstance(creada, dict):
        return f"No pude abrir «{direccion}»."
    time.sleep(1.0)                                   # que empiece a cargar antes de leerla
    titulo = creada.get("title") or direccion
    return f"Abrí «{titulo}» en el navegador."


def listar_pestanas() -> str:
    """Return qué pestañas hay abiertas, marcando la que está delante."""
    if not _vivo():
        return "No hay ninguna ventana de navegador abierta."
    pestanas = _pestanas()
    if not pestanas:
        return "No hay ninguna pestaña abierta."

    lineas = ["En el navegador:"]
    for i, pestana in enumerate(pestanas):
        marca = "  ← la que estás viendo" if i == 0 else ""
        titulo = pestana.get("title") or pestana.get("url") or "(sin título)"
        lineas.append(f"  «{titulo}»{marca}")
    return "\n".join(lineas)


def _buscar_pestana(objetivo: str) -> Optional[Dict[str, Any]]:
    """Return la pestaña cuyo título o dirección se parece más a `objetivo`."""
    from os_integration.ui_tree import _normalizar

    buscado = _normalizar(str(objetivo or ""))
    if not buscado:
        return None
    pestanas = _pestanas()

    if buscado.isdigit():
        indice = int(buscado) - 1
        return pestanas[indice] if 0 <= indice < len(pestanas) else None

    for pestana in pestanas:
        texto = _normalizar(f"{pestana.get('title', '')} {pestana.get('url', '')}")
        if buscado in texto:
            return pestana
    return None


def cambiar_de_pestana(objetivo: str) -> str:
    """Trae al frente la pestaña que se pida, por título o por número. Return qué pasó."""
    if not _vivo():
        return "No hay ninguna ventana de navegador abierta."
    pestana = _buscar_pestana(objetivo)
    if not pestana:
        return f"No encontré ninguna pestaña que se parezca a «{objetivo}»."
    if _pedir(f"/json/activate/{pestana['id']}") is None:
        return f"No pude cambiar a «{pestana.get('title') or objetivo}»."
    return f"Ahora estás en «{pestana.get('title') or objetivo}»."


def cerrar_pestana(objetivo: str) -> str:
    """Cierra la pestaña que se pida. Return qué pasó."""
    if not _vivo():
        return "No hay ninguna ventana de navegador abierta."
    pestana = _buscar_pestana(objetivo)
    if not pestana:
        return f"No encontré ninguna pestaña que se parezca a «{objetivo}»."
    titulo = pestana.get("title") or objetivo
    if _pedir(f"/json/close/{pestana['id']}") is None:
        return f"No pude cerrar «{titulo}»."
    return f"Cerré «{titulo}»."


#: Saca el texto legible de la página, sin los menús de navegación repetidos ni el código.
_JS_TEXTO = """
(() => {
  const fuera = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'SVG']);
  const partes = [];
  const recorrer = (nodo) => {
    if (nodo.nodeType === 3) {
      const t = nodo.textContent.trim();
      if (t) partes.push(t);
      return;
    }
    if (nodo.nodeType !== 1 || fuera.has(nodo.tagName)) return;
    const estilo = window.getComputedStyle(nodo);
    if (estilo.display === 'none' || estilo.visibility === 'hidden') return;
    for (const hijo of nodo.childNodes) recorrer(hijo);
  };
  recorrer(document.body || document.documentElement);
  return partes.join('\\n');
})()
"""


def texto_de_pagina(maximo_caracteres: int = MAX_CARACTERES_DE_TEXTO) -> str:
    """Return el texto visible de la pestaña que está delante."""
    if not _vivo():
        return "No hay ninguna ventana de navegador abierta."
    texto, error = _evaluar(_JS_TEXTO)
    if error:
        return error
    if not texto:
        return "La página no tiene texto que pueda leer."
    texto = str(texto).strip()
    if len(texto) > maximo_caracteres:
        return texto[:maximo_caracteres] + "\n[…texto cortado: la página sigue]"
    return texto


#: Enumera lo accionable y le pone a cada cosa un número, que es con lo que se pulsa luego.
_JS_ELEMENTOS = """
(() => {
  const selector = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]';
  const salida = [];
  let i = 0;
  for (const el of document.querySelectorAll(selector)) {
    const caja = el.getBoundingClientRect();
    if (caja.width < 1 || caja.height < 1) continue;
    const estilo = window.getComputedStyle(el);
    if (estilo.display === 'none' || estilo.visibility === 'hidden') continue;
    const etiqueta = (el.innerText || el.value || el.placeholder ||
                      el.getAttribute('aria-label') || el.title || '').trim();
    if (!etiqueta && el.tagName !== 'INPUT') continue;
    i += 1;
    el.setAttribute('data-orion-id', String(i));
    salida.push({n: i, tipo: el.tagName.toLowerCase(), texto: etiqueta.slice(0, 80)});
    if (salida.length >= MAXIMO) break;
  }
  return JSON.stringify({titulo: document.title, url: location.href, elementos: salida});
})()
"""


def resumen_de_pagina(maximo: int = MAX_ELEMENTOS_DE_PAGINA) -> str:
    """Return qué hay en la página y qué se puede pulsar, numerado."""
    if not _vivo():
        return "No hay ninguna ventana de navegador abierta."
    crudo, error = _evaluar(_JS_ELEMENTOS.replace("MAXIMO", str(int(maximo))))
    if error:
        return error
    try:
        datos = json.loads(crudo) if isinstance(crudo, str) else (crudo or {})
    except json.JSONDecodeError:
        return "No pude entender lo que devolvió la página."

    elementos = datos.get("elementos") or []
    lineas = [f"«{datos.get('titulo') or 'sin título'}» — {datos.get('url', '')}"]
    if not elementos:
        lineas.append("No encontré nada accionable en la página.")
    else:
        lineas.append(f"{len(elementos)} cosas que se pueden usar:")
        for el in elementos:
            lineas.append(f"  {el['n']}. [{el['tipo']}] {el['texto']}")
        lineas.append("Para pulsar algo, pedímelo por su número o por su texto.")
    return "\n".join(lineas)


#: Pulsa o escribe en el elemento pedido. Devuelve qué hizo, para poder contarlo.
_JS_ACCIONAR = """
(() => {
  const objetivo = OBJETIVO;
  const texto = TEXTO;
  let el = null;
  if (/^\\d+$/.test(objetivo)) {
    el = document.querySelector(`[data-orion-id="${objetivo}"]`);
  }
  if (!el) {
    const buscado = objetivo.toLowerCase();
    const candidatos = document.querySelectorAll(
      'a[href], button, input, textarea, select, [role="button"], [role="link"], [onclick]');
    for (const c of candidatos) {
      const etiqueta = ((c.innerText || c.value || c.placeholder ||
                         c.getAttribute('aria-label') || c.title || '') + '').toLowerCase();
      if (etiqueta.includes(buscado)) { el = c; break; }
    }
  }
  if (!el) return JSON.stringify({ok: false, motivo: 'no encontrado'});

  const etiqueta = (el.innerText || el.value || el.placeholder ||
                    el.getAttribute('aria-label') || el.title || el.tagName).trim().slice(0, 60);
  el.scrollIntoView({block: 'center'});
  if (texto !== null) {
    el.focus();
    el.value = texto;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return JSON.stringify({ok: true, accion: 'escribir', etiqueta: etiqueta});
  }
  el.click();
  return JSON.stringify({ok: true, accion: 'pulsar', etiqueta: etiqueta});
})()
"""


def accionar(objetivo: str, texto: Optional[str] = None) -> str:
    """Pulsa un elemento de la página, o escribe en él si se da `texto`. Return qué pasó."""
    if not _vivo():
        return "No hay ninguna ventana de navegador abierta."
    if not objetivo or not str(objetivo).strip():
        return "Necesito saber qué querés pulsar."

    js = (_JS_ACCIONAR
          .replace("OBJETIVO", json.dumps(str(objetivo).strip()))
          .replace("TEXTO", json.dumps(texto) if texto is not None else "null"))
    crudo, error = _evaluar(js)
    if error:
        return error
    try:
        datos = json.loads(crudo) if isinstance(crudo, str) else (crudo or {})
    except json.JSONDecodeError:
        return "No pude entender lo que devolvió la página."

    if not datos.get("ok"):
        return (f"No encontré «{objetivo}» en la página. Mirá qué hay con 'browser_page' "
                f"y pedímelo por su número.")
    time.sleep(0.8)                                   # darle tiempo a que la página reaccione
    if datos.get("accion") == "escribir":
        return f"Escribí «{texto}» en «{datos.get('etiqueta')}»."
    return f"Pulsé «{datos.get('etiqueta')}»."
