import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "orion.log")

#: Variable de entorno para mandar el log a otro archivo. La usa `tests/conftest.py`: la
#: suite importa `main.py`, que llama a `setup_logging()` al importarse, y sin esto TODO lo
#: que registran los tests termina en el log de la aplicación. Depurar un problema real se
#: vuelve arqueología: al investigar por qué el micrófono ignoró un comando (2026-09-03)
#: aparecían errores de terminal y de wake word que eran de la suite, no del usuario.
LOG_FILE_ENV = "ORION_LOG_FILE"
LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def log_file_path() -> str:
    """Archivo al que se escribe: el de la app, o el que diga `ORION_LOG_FILE`."""
    return os.environ.get(LOG_FILE_ENV) or LOG_FILE


def setup_logging(log_level=logging.INFO):
    destino = log_file_path()
    os.makedirs(os.path.dirname(destino) or LOG_DIR, exist_ok=True)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    file_handler = RotatingFileHandler(destino, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
