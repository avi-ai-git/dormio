"""Tracing setup for Dormio.

Langfuse traces every plan so the lookup and the model call are easy to inspect:
which model ran, how long it took, what it was given. It degrades quietly: if the
key is missing or the SDK is absent, the app still answers, it just stops sending
traces.
"""
from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)

_langfuse_handler = None
_handler_ready = False


def _build_langfuse_handler():
    global _langfuse_handler, _handler_ready
    if _handler_ready:
        return _langfuse_handler
    _handler_ready = True
    if not config.LANGFUSE_ENABLED:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        _langfuse_handler = CallbackHandler()
        logger.info("Langfuse tracing enabled")
    except Exception as exc:
        logger.warning("Langfuse handler unavailable, continuing without it: %s", exc)
        _langfuse_handler = None
    return _langfuse_handler


def get_callbacks() -> list:
    """Callback handlers for a run. The Langfuse handler if configured, else empty."""
    handler = _build_langfuse_handler()
    return [handler] if handler else []


def flush() -> None:
    """Push any buffered spans before the process moves on. Safe when tracing is off."""
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception:
        pass
