from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path


LOGGER_NAME = "clawcodex_ext.latent_memory.passive"

_CONFIG_LOCK = threading.Lock()
_CONFIG_SIGNATURE: tuple[str, str] | None = None
_HANDLER_MARKER = "_clawcodex_passive_memory_handler"


def configure_passive_memory_logging() -> None:
    """Configure isolated passive-memory diagnostics from environment variables."""
    global _CONFIG_SIGNATURE

    level_name = os.getenv("CLAWCODEX_PASSIVE_MEMORY_LOG_LEVEL", "WARNING").strip().upper()
    log_file = os.getenv("CLAWCODEX_PASSIVE_MEMORY_LOG_FILE", "").strip()
    signature = (level_name, log_file)

    with _CONFIG_LOCK:
        if signature == _CONFIG_SIGNATURE:
            return

        logger = logging.getLogger(LOGGER_NAME)
        level = getattr(logging, level_name, logging.WARNING)
        if not isinstance(level, int):
            level = logging.WARNING
        logger.setLevel(level)
        logger.propagate = False

        for handler in list(logger.handlers):
            if getattr(handler, _HANDLER_MARKER, False):
                logger.removeHandler(handler)
                handler.close()

        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(level)
        stream_handler.setFormatter(formatter)
        setattr(stream_handler, _HANDLER_MARKER, True)
        logger.addHandler(stream_handler)

        if log_file:
            try:
                path = Path(log_file).expanduser()
                if not path.is_absolute():
                    path = Path.cwd() / path
                path.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(path, encoding="utf-8")
                file_handler.setLevel(level)
                file_handler.setFormatter(formatter)
                setattr(file_handler, _HANDLER_MARKER, True)
                logger.addHandler(file_handler)
            except OSError:
                logger.warning(
                    "event=logging_file_failed path=%s",
                    log_file,
                    exc_info=True,
                )

        _CONFIG_SIGNATURE = signature


__all__ = ["LOGGER_NAME", "configure_passive_memory_logging"]
