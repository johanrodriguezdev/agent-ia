"""
core/terminal_session.py
Terminales reales embebidas en el panel de escritorio: shells de verdad corriendo sobre
una pseudo-consola (ConPTY en Windows, PTY en Linux/macOS), no `subprocess` con tuberías.

Por qué una PTY y no `subprocess.PIPE`: con tuberías, el shell detecta que no hay consola y
apaga los colores, el autocompletado con Tab, el renglón de edición y todo lo interactivo
— `git log` no pagina, `pip install` no dibuja la barra, Ctrl+C no interrumpe. La PTY le
da al proceso una consola verdadera y devuelve el flujo de bytes con secuencias ANSI, que
es exactamente lo que xterm.js sabe pintar del otro lado.

**Modelo de seguridad** (ver `.claude/rules/security-levels.md`):

- Abrir una sesión es la acción gateada (`terminal_open`, 🟡 YELLOW en
  `core/security_manager.py`). Es el único momento con confirmación humana, porque
  confirmar tecla por tecla no es una terminal. Cada shell nueva se confirma aparte.
- Una vez abierta, lo que se escribe fluye sin gate — pero cada línea completa
  (todo lo que termina en Enter) queda registrada en el log y en la auditoría,
  venga del teclado del usuario o de la herramienta del agente.
- Los procesos mueren con el panel: `close()` los termina, y `MainWindow` cierra todo al
  salir. No queda una shell viva sin ventana que la muestre.

**Qué se registra y cómo.** La auditoría no se conforma con lo tecleado: `_LineaVisual`
reconstruye la línea que de verdad se está viendo en la consola (interpretando retornos de
carro, borrados y reposicionamientos de cursor), así que un comando traído con la flecha ↑
o completado con Tab —que el usuario nunca escribió— también queda registrado tal cual se
ejecutó. Esa misma reconstrucción alimenta el historial de salida que puede leer el agente.

Sin nada de Qt en este módulo: es Python plano con un hilo lector y callbacks, para que
`ui/webview/bridge.py` (que sí es Qt) sea el único que traduzca eso a señales.
"""

import itertools
import logging
import os
import re
import sys
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

ES_WINDOWS = sys.platform == "win32"

DEFAULT_COLS = 120
DEFAULT_ROWS = 30

_READ_CHUNK = 8192
_IDLE_POLL_S = 0.02

# Captura para la herramienta del agente: se corta cuando el flujo lleva `_CAPTURE_IDLE_S`
# en silencio (el prompt volvió) o cuando se acaba el tiempo/tamaño máximo.
_CAPTURE_IDLE_S = 0.7
_CAPTURE_TIMEOUT_S = 25.0
_CAPTURE_MAX_CHARS = 8000

# Historial de salida que el agente puede leer (`terminal_read_output`). Son líneas ya
# renderizadas, sin ANSI: lo que el usuario vio, no el flujo crudo.
_SCROLLBACK_LINEAS = 500

# Secuencias ANSI: CSI (colores, movimiento de cursor), OSC (título de ventana) y los
# escapes de dos caracteres.
_ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC ... BEL | ST
    r"|\x1b\[[0-9;?]*[ -/]*[@-~]"          # CSI
    r"|\x1b[@-Z\\-_]"                      # escapes de 2 caracteres
)

# CSI que MUEVEN o BORRAN (no las de color): son las únicas que le importan a `_LineaVisual`.
_CSI_RE = re.compile(r"\x1b\[([0-9;]*)([A-Za-z])")

# Un prompt cualquiera: PowerShell (`PS C:\x>`), cmd (`C:\x>`), bash/zsh (`user@host:~$`).
# Se usa para separar el prompt del comando dentro de una línea ya renderizada.
_PROMPT_SPLIT_RE = re.compile(r"^(?:PS\s+)?[^>$#\r\n]*[>$#]\s?(.*)$")

# Una línea que es SOLO prompt, sin comando: la que reaparece al terminar un comando.
_PROMPT_SOLO_RE = re.compile(r"^(?:PS\s+)?[^>$#\r\n]*[>$#]\s*$")

_contador_ids = itertools.count(1)


class TerminalUnavailable(RuntimeError):
    """No se pudo abrir una terminal real (falta la dependencia de PTY o falló el spawn)."""


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shell_por_defecto() -> List[str]:
    """El shell del sistema, con el perfil del usuario cargado a propósito.

    Una terminal que no conoce tus alias ni tu prompt no es tu terminal, así que no se
    pasa `-NoProfile` ni `--norc`. En POSIX se respeta `$SHELL` (zsh, fish, lo que el
    usuario tenga) y se cae a `/bin/sh`, que existe en cualquier Unix.
    """
    if ES_WINDOWS:
        return ["powershell.exe", "-NoLogo"]
    return [os.environ.get("SHELL") or "/bin/sh"]


def strip_ansi(text: str) -> str:
    """Saca las secuencias de escape de un volcado de terminal."""
    return _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "")


def _spawn_pty(argv: List[str], cwd: str, rows: int, cols: int):
    """Levanta el proceso sobre una pseudo-consola real, según el sistema.

    Las dos bibliotecas exponen la misma forma (`spawn`, `read`, `write`, `setwinsize`,
    `isalive`, `terminate`), así que el resto del módulo no distingue plataforma.
    """
    if ES_WINDOWS:
        try:
            from winpty import PtyProcess
        except ImportError as e:
            raise TerminalUnavailable(
                "falta la dependencia 'pywinpty' (pip install pywinpty)"
            ) from e
        return PtyProcess.spawn(argv, cwd=cwd, dimensions=(rows, cols))

    try:
        from ptyprocess import PtyProcessUnicode
    except ImportError as e:
        raise TerminalUnavailable(
            "falta la dependencia 'ptyprocess' (pip install ptyprocess)"
        ) from e
    return PtyProcessUnicode.spawn(argv, cwd=cwd, dimensions=(rows, cols))


class _LineaVisual:
    """Reconstruye la línea que se está viendo AHORA en la consola.

    No es un emulador de terminal completo ni pretende serlo: solo sigue la línea actual,
    que es lo que hace falta para dos cosas concretas —saber qué comando se ejecutó de
    verdad y guardar un historial legible de la salida—. Interpreta lo que el shell usa
    para redibujar el renglón de edición: retorno de carro, borrado, y las secuencias de
    posición/borrado de PSReadLine y readline.

    Sin esto, la auditoría solo veía lo TECLEADO, y un comando traído con ↑ o completado
    con Tab no lo teclea nadie: lo repone el shell.
    """

    def __init__(self, on_linea: Optional[Callable[[str], None]] = None):
        self._buf = ""
        self._col = 0
        self._on_linea = on_linea

    def feed(self, data: str) -> None:
        i = 0
        largo = len(data)
        while i < largo:
            ch = data[i]

            if ch == "\x1b":
                m = _CSI_RE.match(data, i)
                if m is not None:
                    self._aplicar_csi(m.group(1), m.group(2))
                    i = m.end()
                    continue
                m = _ANSI_RE.match(data, i)
                if m is not None:      # OSC/escape de 2 caracteres: no mueve el cursor
                    i = m.end()
                    continue
                i += 1
                continue

            if ch == "\n":
                self._terminar_linea()
            elif ch == "\r":
                self._col = 0
            elif ch == "\b":
                self._col = max(0, self._col - 1)
            elif ch >= " ":
                self._escribir(ch)
            # el resto de los caracteres de control (campana, tabulador de alineación) no
            # cambian lo que se lee en la línea

            i += 1

    def _escribir(self, ch: str) -> None:
        if self._col < len(self._buf):
            self._buf = self._buf[:self._col] + ch + self._buf[self._col + 1:]
        else:
            self._buf += " " * (self._col - len(self._buf)) + ch
        self._col += 1

    def _aplicar_csi(self, params: str, final: str) -> None:
        numeros = [int(p) for p in params.split(";") if p.isdigit()]
        n = numeros[0] if numeros else 0

        if final == "K":                       # borrar en la línea
            if n == 0:
                self._buf = self._buf[:self._col]
            elif n == 1:
                self._buf = " " * self._col + self._buf[self._col:]
            else:
                self._buf = ""
                self._col = 0
        elif final == "G":                     # columna absoluta
            self._col = max(0, (n or 1) - 1)
        elif final == "C":                     # cursor a la derecha
            self._col += max(1, n)
        elif final == "D":                     # cursor a la izquierda
            self._col = max(0, self._col - max(1, n))
        elif final in ("H", "f", "J"):
            # Saltó a otra parte de la pantalla o la borró entera: lo que había en la
            # línea ya no es lo que se ve. Se descarta SIN entregarla — al redibujar el
            # renglón de edición (PSReadLine lo hace en cada tecla) esto pasa muchas veces
            # por comando, y entregarlas llenaba el historial de líneas a medio escribir.
            self._descartar_linea()

    def _terminar_linea(self) -> None:
        """La línea se completó de verdad (llegó un salto de línea): se entrega."""
        linea = self._buf.rstrip()
        self._descartar_linea()
        if self._on_linea is not None and linea:
            self._on_linea(linea)

    def _descartar_linea(self) -> None:
        self._buf = ""
        self._col = 0

    def texto(self) -> str:
        return self._buf.rstrip()


def extraer_comando(linea_visual: str) -> str:
    """Devuelve el comando de una línea renderizada, sin el prompt de adelante.

    `"PS C:\\proyecto> git status"` → `"git status"`. Si la línea es solo el prompt, o no
    parece un prompt, devuelve vacío: es preferible no registrar nada que registrar basura.
    """
    linea = linea_visual.strip()
    if not linea or _PROMPT_SOLO_RE.match(linea):
        return ""
    m = _PROMPT_SPLIT_RE.match(linea)
    if m is None:
        return ""
    return m.group(1).strip()


class TerminalSession:
    """Un shell vivo sobre una PTY, con un hilo que lee su salida.

    `on_output` se invoca DESDE EL HILO LECTOR con cada trozo crudo de salida. Quien la
    pase es responsable de marshalear al hilo que corresponda — en el caso del bridge, se
    pasa un método que hace `pyqtSignal.emit()`, que Qt encola solo.
    """

    def __init__(
        self,
        cwd: Optional[str] = None,
        cols: int = DEFAULT_COLS,
        rows: int = DEFAULT_ROWS,
        on_output: Optional[Callable[[str], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        session_id: Optional[str] = None,
        titulo: str = "",
    ):
        self.id = session_id or f"t{next(_contador_ids)}"
        self.titulo = titulo or f"Terminal {self.id[1:]}"
        self.cwd = cwd or _project_root()
        self.cols = cols
        self.rows = rows
        self.on_output = on_output
        self.on_exit = on_exit

        self._proc = None
        self._reader: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()

        # Línea en construcción del lado del TECLADO. Se compara con la línea visual al
        # llegar el Enter (ver `_audit_lines`).
        self._line_buf = ""

        # Lo que se está viendo, reconstruido desde la SALIDA. Alimenta la auditoría y el
        # historial que puede leer el agente.
        self._scrollback: Deque[str] = deque(maxlen=_SCROLLBACK_LINEAS)
        self._pantalla = _LineaVisual(on_linea=self._anotar_linea)
        # Comando ya anotado a mano al apretar Enter: si el shell lo vuelve a entregar como
        # linea terminada, se saltea UNA vez para no verlo duplicado en el historial.
        self._ultima_anotada = ""

        # Captura para `run_command_capture()`. `_capture_buf` solo lo toca el hilo lector.
        self._capturing = False
        self._capture_buf: List[str] = []
        self._last_chunk_at = 0.0
        self._capture_lock = threading.Lock()

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        """Levanta el shell. Lanza `TerminalUnavailable` si no se puede."""
        argv = shell_por_defecto()
        try:
            self._proc = _spawn_pty(argv, self.cwd, self.rows, self.cols)
        except TerminalUnavailable:
            raise
        except Exception as e:
            logger.error(f"no se pudo abrir la terminal: {e}")
            raise TerminalUnavailable(str(e)) from e

        self._stop.clear()
        self._reader = threading.Thread(
            target=self._read_loop, name=f"terminal-reader-{self.id}", daemon=True
        )
        self._reader.start()
        logger.info(f"terminal {self.id} abierta en {self.cwd} ({argv[0]})")

    def is_alive(self) -> bool:
        try:
            return self._proc is not None and self._proc.isalive()
        except Exception as e:
            logger.debug(f"isalive() falló, se asume terminal muerta: {e}")
            return False

    def close(self) -> None:
        """Termina el proceso y para el hilo lector. Idempotente."""
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.terminate(force=True)
        except Exception as e:
            logger.warning(f"error terminando la terminal {self.id}: {e}")
        logger.info(f"terminal {self.id} cerrada")

    # ------------------------------------------------------------------ entrada / salida
    def write(self, data: str) -> None:
        """Escribe en la terminal tal cual (teclas incluidas: Tab, Ctrl+C, flechas)."""
        if not data or self._proc is None:
            return
        self._audit_lines(data)
        with self._write_lock:
            try:
                self._proc.write(data)
            except Exception as e:
                logger.warning(f"error escribiendo en la terminal {self.id}: {e}")

    def resize(self, cols: int, rows: int) -> None:
        """Ajusta el tamaño de la consola para que el shell reparta bien las columnas."""
        cols = max(20, min(int(cols), 500))
        rows = max(5, min(int(rows), 200))
        self.cols, self.rows = cols, rows
        if self._proc is None:
            return
        try:
            self._proc.setwinsize(rows, cols)
        except Exception as e:
            logger.warning(f"error redimensionando la terminal {self.id}: {e}")

    def salida_reciente(self, lineas: int = 60) -> str:
        """Las últimas líneas que se vieron en esta terminal, sin ANSI.

        Es lo que le permite al agente responder sobre algo que corriste vos a mano: sin
        esto, solo podía leer la salida de sus propios comandos.
        """
        lineas = max(1, min(int(lineas), _SCROLLBACK_LINEAS))
        recientes = list(self._scrollback)[-lineas:]
        return "\n".join(recientes).strip()

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._proc.read(_READ_CHUNK) if self._proc else ""
            except EOFError:
                break
            except Exception as e:
                # La terminal cerrada desde adentro (`exit`) llega como error del handle:
                # no es una condición excepcional, es el final normal del proceso.
                logger.debug(f"lectura de la terminal {self.id} terminada: {e}")
                break

            if not data:
                if not self.is_alive():
                    break
                time.sleep(_IDLE_POLL_S)
                continue

            self._pantalla.feed(data)

            if self._capturing:
                self._capture_buf.append(data)
                self._last_chunk_at = time.monotonic()

            if self.on_output is not None:
                try:
                    self.on_output(data)
                except Exception as e:
                    logger.error(f"el consumidor de salida de la terminal falló: {e}")

        if self.on_exit is not None:
            try:
                self.on_exit()
            except Exception as e:
                logger.error(f"on_exit de la terminal falló: {e}")

    # ------------------------------------------------------------------ auditoría
    def _audit_lines(self, data: str) -> None:
        """Registra cada comando completo que entra a la terminal.

        El gate 🟡 corrió una sola vez, al abrir la sesión; a partir de ahí lo único que
        queda de rastro es esto. Se registra al llegar el Enter, no tecla por tecla, para
        que el log sea el comando y no el tipeo.

        Se cruzan DOS fuentes, porque ninguna alcanza sola:

        - lo **tecleado** (`_line_buf`): siempre disponible en el acto, pero se pierde lo
          que el usuario no escribió (un comando traído con ↑, o completado con Tab).
        - lo **visible** (`_pantalla`): es el comando de verdad, venga de donde venga, pero
          depende del eco del shell, que puede ir un carácter atrás del teclado, y no
          existe todavía cuando el agente escribe una línea entera de una vez.

        Se elige la más completa de las dos: si una extiende a la otra gana la más larga
        (eco atrasado, o completado con Tab); si no se parecen, gana lo visible, que es lo
        que el shell va a ejecutar. Las respuestas de escape que xterm.js manda por su
        cuenta (atributos del terminal, foco) se descartan antes de armar la línea.
        """
        # Solo se quitan las SECUENCIAS de escape: `strip_ansi()` normaliza además los
        # fines de línea, y acá el retorno de carro es justo lo que marca el final del
        # comando. Si se usara, no habría Enter que detectar y no se auditaría nada.
        for ch in _ANSI_RE.sub("", data):
            if ch in ("\r", "\n"):
                self._registrar_comando_actual()
            elif ch == "\x7f":            # backspace
                self._line_buf = self._line_buf[:-1]
            elif ch == "\x03":            # Ctrl+C: la línea se descarta sin ejecutarse
                self._line_buf = ""
            elif ch >= " ":
                self._line_buf += ch

    def _registrar_comando_actual(self) -> None:
        tecleado = self._line_buf.strip()
        self._line_buf = ""
        linea_visible = self._pantalla.texto()
        visible = extraer_comando(linea_visible)

        comando = self._elegir_comando(tecleado, visible)
        if not comando:
            return
        self._anotar_en_historial(linea_visible, visible, comando)
        self._record_command(comando)

    def _anotar_en_historial(self, linea_visible: str, visible: str, comando: str) -> None:
        """Deja el comando en el historial que lee el agente, junto a su salida.

        El renglón de edición nunca llega a "terminar" como una línea normal: al apretar
        Enter, el shell lo redibuja reposicionando el cursor y `_LineaVisual` lo descarta
        (si no, cada tecla dejaría una versión a medio escribir). Sin esto, el historial
        tendría la salida de los comandos pero no los comandos — y "¿por qué falló lo que
        acabo de correr?" no se puede contestar viendo solo el error.
        """
        prefijo = linea_visible[: len(linea_visible) - len(visible)] if visible else linea_visible
        if prefijo and not prefijo.endswith(" "):
            # `_LineaVisual.texto()` recorta la derecha, asi que el espacio que separa el
            # prompt del comando se pierde cuando todavia no hubo eco.
            prefijo += " "
        entrada = (prefijo + comando).strip()
        if not entrada:
            return
        self._scrollback.append(entrada)
        self._ultima_anotada = entrada

    def _anotar_linea(self, linea: str) -> None:
        """Sumidero de `_LineaVisual`: cada linea terminada va al historial."""
        if linea == self._ultima_anotada:
            self._ultima_anotada = ""     # ya estaba anotada; se saltea solo esta vez
            return
        self._scrollback.append(linea)

    @staticmethod
    def _elegir_comando(tecleado: str, visible: str) -> str:
        if not visible:
            return tecleado
        if not tecleado:
            return visible
        if visible.startswith(tecleado) or tecleado.startswith(visible):
            return visible if len(visible) >= len(tecleado) else tecleado
        return visible

    @staticmethod
    def _record_command(line: str) -> None:
        # INFO y no WARNING: la accion amarilla es ABRIR la sesion, y esa ya la registra
        # `require_confirmation()` con su nivel. Cada comando dentro de una terminal que el
        # usuario abrio a proposito no es una anomalia — y en WARNING competian con los
        # avisos que si importan (en las sesiones reales del 2026-09-03, los unicos WARNING
        # eran estos). El rastro fuerte no es el log igual: es la fila de auditoria de
        # abajo, que no depende del nivel.
        logger.info(f"terminal: comando ejecutado | {line}")
        try:
            from core.security_manager import ChannelType, security_manager

            security_manager.log_action(
                "terminal_command", ChannelType.DESKTOP, "ejecutado", details=line[:500]
            )
        except Exception as e:
            logger.error(f"no se pudo auditar el comando de terminal: {e}")

    # ------------------------------------------------------------------ captura (agente)
    def run_command_capture(self, command: str, timeout: float = _CAPTURE_TIMEOUT_S) -> str:
        """Corre `command` y devuelve su salida ya limpia, para que el agente pueda leerla.

        No hay forma de preguntarle a una PTY "¿terminaste?": lo que se ve es un flujo de
        bytes. Se corta cuando el flujo queda en silencio `_CAPTURE_IDLE_S` (el prompt
        volvió) o cuando se agota el tiempo. La salida igual se ve en vivo en el panel:
        esta captura es una derivación, no un desvío.
        """
        if not self.is_alive():
            raise TerminalUnavailable("la terminal no está abierta")

        with self._capture_lock:
            self._capture_buf = []
            self._last_chunk_at = time.monotonic()
            self._capturing = True
            try:
                self.write(command.rstrip("\r\n") + "\r")
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    time.sleep(0.05)
                    quieto = time.monotonic() - self._last_chunk_at
                    if self._capture_buf and quieto >= _CAPTURE_IDLE_S:
                        break
                    if len("".join(self._capture_buf)) > _CAPTURE_MAX_CHARS:
                        break
            finally:
                self._capturing = False
                raw = "".join(self._capture_buf)
                self._capture_buf = []

        return _clean_capture(raw, command)


def _clean_capture(raw: str, command: str) -> str:
    """Deja solo la salida del comando: sin ANSI, sin el eco de lo tipeado, sin el prompt."""
    texto = strip_ansi(raw)
    lineas = texto.split("\n")

    # El eco de lo que se escribió vuelve como primera línea (a veces partido por el ancho
    # de la consola); se descarta mientras siga pareciéndose al comando o al prompt.
    comando = command.strip()
    while lineas and (
        not lineas[0].strip()
        or comando.startswith(lineas[0].strip()[:40])
        or lineas[0].strip().endswith(comando[-40:])
        or _PROMPT_SOLO_RE.match(lineas[0].strip())
        or extraer_comando(lineas[0].strip()) == comando
    ):
        lineas.pop(0)

    # El prompt que reaparece al final tampoco es salida del comando.
    while lineas and (not lineas[-1].strip() or _PROMPT_SOLO_RE.match(lineas[-1].strip())):
        lineas.pop()

    # `rstrip()` y no `strip()`: la sangría de la izquierda puede significar algo. En
    # `git status --short`, " M archivo" (modificado sin preparar) y "M  archivo"
    # (preparado) se distinguen justamente por esos espacios, y esto lo lee el agente.
    salida = "\n".join(lineas).rstrip()
    if len(salida) > _CAPTURE_MAX_CHARS:
        salida = salida[:_CAPTURE_MAX_CHARS] + "\n… (salida recortada)"
    return salida


class TerminalManager:
    """Dueño de las sesiones de terminal del escritorio.

    Existe porque las sesiones tienen dos entradas posibles —el panel del webview y la
    herramienta del agente— y las dos tienen que dar contra los mismos shells: si el agente
    corriera comandos en una terminal invisible, el usuario perdería la única forma de ver
    qué se ejecutó en su máquina.

    Hay varias sesiones (pestañas) y una activa. La activa es contra la que trabaja el
    agente cuando no se le dice otra cosa, y es la que el panel muestra.

    El sink de salida lo instala el bridge una vez al construirse, así la salida llega a la
    pantalla sin importar quién abrió la sesión.
    """

    def __init__(self):
        self._sessions: Dict[str, TerminalSession] = {}
        self._orden: List[str] = []
        self._activa: Optional[str] = None
        self._on_output: Optional[Callable[[str, str], None]] = None
        self._on_state: Optional[Callable[[str, str, str], None]] = None
        self._lock = threading.RLock()

    def set_sink(
        self,
        on_output: Optional[Callable[[str, str], None]],
        on_state: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        self._on_output = on_output
        self._on_state = on_state

    # ------------------------------------------------------------------ consultas
    def get(self, session_id: str) -> Optional[TerminalSession]:
        with self._lock:
            sesion = self._sessions.get(session_id)
            if sesion is not None and not sesion.is_alive():
                self._olvidar(session_id)
                return None
            return sesion

    def active(self) -> Optional[TerminalSession]:
        with self._lock:
            if self._activa is None:
                return None
            return self.get(self._activa)

    def ids(self) -> List[str]:
        with self._lock:
            return [i for i in self._orden if self.get(i) is not None]

    def listado(self) -> List[Dict[str, str]]:
        """Descripción de las pestañas para la interfaz."""
        with self._lock:
            filas = []
            for sid in self.ids():
                sesion = self._sessions[sid]
                filas.append({
                    "id": sesion.id,
                    "titulo": sesion.titulo,
                    "cwd": sesion.cwd,
                    "activa": sid == self._activa,
                })
            return filas

    # ------------------------------------------------------------------ ciclo de vida
    def crear(self, cwd: Optional[str] = None) -> TerminalSession:
        """Abre una sesión NUEVA y la deja activa. Lanza `TerminalUnavailable` si no puede."""
        with self._lock:
            sesion = TerminalSession(cwd=cwd)
            sesion.on_output = lambda chunk, sid=sesion.id: self._emit_output(sid, chunk)
            sesion.on_exit = lambda sid=sesion.id: self._on_session_exit(sid)
            sesion.start()

            self._sessions[sesion.id] = sesion
            self._orden.append(sesion.id)
            self._activa = sesion.id

        self._emit_state(sesion.id, "abierta", sesion.cwd)
        return sesion

    def ensure(self, cwd: Optional[str] = None) -> TerminalSession:
        """Devuelve la sesión activa viva, o abre una."""
        with self._lock:
            actual = self.active()
            if actual is not None:
                return actual
        return self.crear(cwd=cwd)

    def set_active(self, session_id: str) -> bool:
        with self._lock:
            if self.get(session_id) is None:
                return False
            self._activa = session_id
            return True

    def close(self, session_id: Optional[str] = None) -> None:
        """Cierra una sesión (la activa si no se dice cuál) y activa otra si queda alguna."""
        with self._lock:
            sid = session_id or self._activa
            if sid is None:
                return
            sesion = self._sessions.get(sid)
            self._olvidar(sid)
        if sesion is not None:
            sesion.close()
            self._emit_state(sid, "cerrada", "")

    def close_all(self) -> None:
        for sid in list(self._sessions.keys()):
            self.close(sid)

    def _olvidar(self, session_id: str) -> None:
        """Saca la sesión del registro y reasigna la activa. Se llama con el lock tomado."""
        self._sessions.pop(session_id, None)
        if session_id in self._orden:
            self._orden.remove(session_id)
        if self._activa == session_id:
            self._activa = self._orden[-1] if self._orden else None

    # ------------------------------------------------------------------ señales
    def _emit_output(self, session_id: str, chunk: str) -> None:
        if self._on_output is not None:
            self._on_output(session_id, chunk)

    def _emit_state(self, session_id: str, estado: str, detalle: str) -> None:
        if self._on_state is not None:
            try:
                self._on_state(session_id, estado, detalle)
            except Exception as e:
                logger.error(f"no se pudo notificar el estado de la terminal: {e}")

    def _on_session_exit(self, session_id: str) -> None:
        with self._lock:
            self._olvidar(session_id)
        self._emit_state(session_id, "cerrada", "")


terminal_manager = TerminalManager()
