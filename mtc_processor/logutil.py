from __future__ import annotations
import logging
import os
from logging.handlers import RotatingFileHandler
from functools import lru_cache


@lru_cache(maxsize=32)
def get_processor_logger(component: str = "processor") -> logging.Logger:
    """Return a configured shared logger for processors.

    Environment variables:
      PROCESSOR_LOG_LEVEL: Default log level (default INFO)
      PROCESSOR_LOG_FILE:  Log file path (default processor.log)
      PROCESSOR_LOG_MAX_MB: Rotate after this many MB (default 5)
      PROCESSOR_LOG_BACKUPS: Number of rotated backups to keep (default 3)
    """
    base_name = "mtc.processor"
    logger_name = f"{base_name}.{component}" if component else base_name
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger
    logger.propagate = False

    level_name = os.getenv("PROCESSOR_LOG_LEVEL", "INFO").upper().strip()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    log_file = os.getenv("PROCESSOR_LOG_FILE", "processor.log").strip()
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    try:
        max_mb = float(os.getenv("PROCESSOR_LOG_MAX_MB", "5"))
    except ValueError:
        max_mb = 5.0
    try:
        backups = int(os.getenv("PROCESSOR_LOG_BACKUPS", "3"))
    except ValueError:
        backups = 3

    handler = RotatingFileHandler(log_file, maxBytes=int(max_mb * 1024 * 1024), backupCount=backups)
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    handler.setLevel(level)
    logger.addHandler(handler)
    return logger
