"""Logging setup for the automation."""

from __future__ import annotations

import logging
import sys

from config.settings import Settings


def setup_logging(settings: Settings) -> logging.Logger:
    """Configure file and console logging."""
    settings.ensure_directories()

    logger = logging.getLogger("wavity_automation")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(settings.log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def get_logger() -> logging.Logger:
    """Return the automation logger."""
    return logging.getLogger("wavity_automation")
