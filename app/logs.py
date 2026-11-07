"""Logging do aplicativo: arquivo com rotação + ponte para a aba LOGS.

Regra: nunca registrar senhas, tokens, cookies ou códigos. Os chamadores só
passam identificadores (username, nome da conexão), nunca segredos.
"""
import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCESSO")
logging.addLevelName(logging.WARNING, "AVISO")
logging.addLevelName(logging.ERROR, "ERRO")

log = logging.getLogger("studio")


def success(msg, *args):
    log.log(SUCCESS, msg, *args)


class _Emitter(QObject):
    record = Signal(str, str, str)  # hora, nível, mensagem


class QtLogHandler(logging.Handler):
    """Guarda os últimos registros em memória e avisa a interface (thread-safe via sinal)."""

    def __init__(self, maxlen: int = 5000):
        super().__init__()
        self.records: deque[tuple[str, str, str]] = deque(maxlen=maxlen)
        self.emitter = _Emitter()

    def emit(self, record):
        try:
            entry = (logging.Formatter().formatTime(record, "%H:%M:%S"),
                     record.levelname, record.getMessage())
            self.records.append(entry)
            self.emitter.record.emit(*entry)
        except Exception:
            self.handleError(record)


def setup_logging(log_dir: Path) -> QtLogHandler:
    log_dir.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    log.propagate = False
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    file_handler = RotatingFileHandler(log_dir / "studio.log", maxBytes=1_000_000,
                                       backupCount=5, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    qt_handler = QtLogHandler()
    log.addHandler(file_handler)
    log.addHandler(qt_handler)
    return qt_handler
