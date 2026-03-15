import io
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


class _StreamToLogger(io.TextIOBase):
    def __init__(self, logger: logging.Logger, level: int, stream):
        self._logger = logger
        self._level = level
        self._stream = stream
        self._buffer = ""

    def write(self, text):
        if not text:
            return 0

        self._stream.write(text)
        self._stream.flush()

        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                self._logger.log(self._level, line)

        return len(text)

    def flush(self):
        self._stream.flush()
        if self._buffer.strip():
            self._logger.log(self._level, self._buffer.strip())
        self._buffer = ""


def configure_logging(log_dir: Path) -> Path:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    sys.stdout = _StreamToLogger(logger, logging.INFO, sys.__stdout__)
    sys.stderr = _StreamToLogger(logger, logging.ERROR, sys.__stderr__)

    logging.info("Logging inicializado em %s", log_file)
    return log_file
