"""shared — cross-service utilities for AuroLab."""
from .logger import get_logger, configure_logging
from .exceptions import AurolabError, SafetyBlockError, CollisionError
from .response import ok, err, paginated

__all__ = [
    "get_logger", "configure_logging",
    "AurolabError", "SafetyBlockError", "CollisionError",
    "ok", "err", "paginated",
]