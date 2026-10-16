"""
shared/logger.py  -  Structured logging for AuroLab.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def configure_logging() -> None:
    """
    Call once at startup in main.py lifespan.
    
    NOTE: add_logger_name is intentionally excluded from processors.
    It only works with stdlib LoggerFactory, not PrintLoggerFactory,
    and raises: AttributeError: 'PrintLogger' object has no attribute 'name'
    """
    env       = os.getenv("ENV", "prod").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(colors=(env == "dev")),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.INFO),
    )
    for noisy in ["httpx", "httpcore", "chromadb", "urllib3",
                  "multipart", "uvicorn.access"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)