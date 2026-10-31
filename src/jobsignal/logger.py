"""Central logging setup for JobSignal.

Call ``setup_logging()`` once at an entry point (script, API startup, dashboard).
Every module then uses ``logging.getLogger(__name__)``; because all module names sit
under the ``jobsignal`` package logger, they inherit its handler and level.

Level conventions:
    INFO    scrape/pipeline run lifecycle (started, finished, counts)
    WARNING recoverable problems (HTTP 429/5xx retry, rate-limit backoff)
    ERROR   failed requests after retries, unparseable responses
"""

import logging
import sys
from typing import TextIO

from jobsignal.config import get_settings

PACKAGE_LOGGER = "jobsignal"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_HANDLER_MARKER = "_jobsignal_handler"


def setup_logging(level: str | None = None, stream: TextIO | None = None) -> logging.Logger:
    """Configure the ``jobsignal`` package logger. Safe to call more than once."""
    level_name = (level or get_settings().log_level).strip().upper()
    numeric_level = logging.getLevelNamesMapping().get(level_name)
    if numeric_level is None:
        raise ValueError(f"Unknown log level: {level!r}")

    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    setattr(handler, _HANDLER_MARKER, True)

    logger.addHandler(handler)
    logger.setLevel(numeric_level)
    logger.propagate = False  # don't double-log through a root handler set by uvicorn etc.
    return logger
