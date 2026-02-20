"""Centralized logging configuration.

Provides a ``get_logger`` helper that returns a stdlib logger writing
structured JSON via ``python-json-logger``.  Every module should call::

    logger = get_logger(__name__)

The root application logger is configured once at import time; child
loggers inherit the handler and level automatically.

The formatter automatically injects ``request_id`` from the
``ContextVar`` in ``app.core.request_context`` — no manual
``extra={"request_id": ...}`` needed.
"""

import logging
import sys

from pythonjsonlogger import jsonlogger

from app.config import LOG_LEVEL, APP_NAME

# --------------------------------------------------------------------------
# Formatter
# --------------------------------------------------------------------------

_LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"


class _AppJsonFormatter(jsonlogger.JsonFormatter):
    """Adds ``service`` and ``request_id`` to every JSON record.

    ``request_id`` is read from the ContextVar managed by the
    ``RequestIDMiddleware`` — it will be ``None`` (omitted) for log
    lines emitted outside of a request (e.g. startup / shutdown).
    """

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["service"] = APP_NAME
        log_record["level"] = record.levelname

        # Lazy import to avoid circular deps (logger.py is imported very early)
        from app.core.request_context import get_request_id

        request_id = get_request_id()
        if request_id is not None:
            log_record["request_id"] = request_id


# --------------------------------------------------------------------------
# One-time root configuration
# --------------------------------------------------------------------------

def _configure_root_logger() -> None:
    """Attach a JSON handler to the application root logger."""
    root = logging.getLogger("app")
    if root.handlers:
        return  # already configured (e.g. tests import multiple times)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_AppJsonFormatter(_LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    # Prevent duplicate output via the stdlib root logger
    root.propagate = False


_configure_root_logger()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped under the ``app`` hierarchy.

    Usage::

        from app.core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("hello", extra={"request_id": "abc"})
    """
    return logging.getLogger(name)
