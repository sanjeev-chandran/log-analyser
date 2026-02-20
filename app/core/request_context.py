"""Request-scoped context using ContextVar.

Stores a ``request_id`` per async task so that every log line emitted
during a request can be correlated — without passing the ID through
every function signature.

Works exactly like the ``Database`` session ContextVar: the middleware
sets it at the start of a request and resets it when the request ends.
"""

from contextvars import ContextVar
from typing import Optional

_request_id: ContextVar[Optional[str]] = ContextVar("_request_id", default=None)


def get_request_id() -> Optional[str]:
    """Return the request ID for the current context, or ``None``."""
    return _request_id.get()


def set_request_id(request_id: str):
    """Set the request ID for the current context.

    Returns a token that **must** be passed to ``reset_request_id``
    when the request ends.
    """
    return _request_id.set(request_id)


def reset_request_id(token) -> None:
    """Reset the request ID ContextVar using the token from ``set_request_id``."""
    _request_id.reset(token)
