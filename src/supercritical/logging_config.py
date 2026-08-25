"""Logging setup for the game.

Provides a single configuration entry point so no module resorts to ``print``.
"""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "supercritical"
_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the package logger.

    Idempotent: calling it more than once will not stack duplicate handlers.

    Parameters
    ----------
    level : int, optional
        Logging level applied to the package logger, by default ``logging.INFO``.

    Returns
    -------
    logging.Logger
        The configured package logger.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(suffix: str | None = None) -> logging.Logger:
    """Return a child of the package logger.

    Parameters
    ----------
    suffix : str or None, optional
        Dotted suffix appended to the package logger name, by default None.

    Returns
    -------
    logging.Logger
        The requested logger.
    """
    if suffix is None:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}")
