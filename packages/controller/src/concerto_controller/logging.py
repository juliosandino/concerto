"""Module for configuring logging to route through loguru."""

import logging

from loguru import logger


class _InterceptHandler(logging.Handler):
    """Route standard-library log records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
